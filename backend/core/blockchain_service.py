"""Web3.py integration with the DataSentryRegistry contract.

* ABI/bytecode come from the Hardhat compilation artifact.
* The contract address is resolved from (in order): DATASENTRY_CONTRACT_ADDRESS,
  the backend deployment file, the Hardhat Ignition deployment. If none has
  code on the connected chain (e.g. the local node was restarted) the backend
  deploys the compiled contract itself with the coordinator account.
* Signing: if private keys are provided via environment variables the backend
  signs transactions locally; otherwise it uses the accounts managed (unlocked)
  by the local Hardhat node. Keys are never sent to the frontend.
* Every transaction waits for its receipt and is only reported as confirmed
  when ``receipt.status == 1``; failures raise ``BlockchainError``.
"""
from __future__ import annotations

import json
import logging
import threading
from pathlib import Path
from typing import Any, Optional

from web3 import Web3
from web3.exceptions import ContractLogicError
from web3.logs import DISCARD

import config

log = logging.getLogger("datasentry.blockchain")

DECISION_CODES = {"ACCEPT": 1, "SUSPICIOUS": 2, "REJECT": 3}
DECISION_NAMES = {0: "NONE", 1: "ACCEPT", 2: "SUSPICIOUS", 3: "REJECT"}
ROUND_STATUS = {0: "NONE", 1: "OPEN", 2: "FINALIZED"}


class BlockchainError(RuntimeError):
    def __init__(self, message: str, tx_hash: Optional[str] = None):
        super().__init__(message)
        self.tx_hash = tx_hash


def to_bytes32(hex_hash: str) -> bytes:
    h = hex_hash[2:] if hex_hash.startswith("0x") else hex_hash
    b = bytes.fromhex(h)
    if len(b) != 32:
        raise ValueError("hash must be 32 bytes")
    return b


class _Signer:
    def __init__(self, address: str, key: Optional[str]):
        self.address = Web3.to_checksum_address(address)
        self.key = key


class BlockchainService:
    def __init__(self, rpc_url: str = config.RPC_URL, artifact_path: Path = config.CONTRACT_ARTIFACT):
        self.rpc_url = rpc_url
        self.artifact_path = Path(artifact_path)
        self.w3: Optional[Web3] = None
        self.contract = None
        self.address: Optional[str] = None
        self.coordinator: Optional[_Signer] = None
        self.client_signers: list[_Signer] = []
        self.last_error: Optional[str] = None
        self.deployed_by_backend = False
        self._lock = threading.RLock()

    # ------------------------------------------------------------ connection
    @property
    def ready(self) -> bool:
        return self.contract is not None and self.w3 is not None and self._is_connected()

    def _is_connected(self) -> bool:
        try:
            return bool(self.w3 and self.w3.is_connected())
        except Exception:
            return False

    def _load_artifact(self) -> dict:
        if not self.artifact_path.exists():
            raise BlockchainError(
                f"contract artifact not found at {self.artifact_path}; run `npx hardhat compile` in blockchain/"
            )
        return json.loads(self.artifact_path.read_text(encoding="utf-8"))

    def _signers(self) -> None:
        managed = []
        try:
            managed = self.w3.eth.accounts
        except Exception:
            managed = []
        def make(key: str, idx: int) -> _Signer:
            if key:
                acct = self.w3.eth.account.from_key(key)
                return _Signer(acct.address, key)
            if len(managed) <= idx:
                raise BlockchainError("no private key configured and node exposes too few unlocked accounts")
            return _Signer(managed[idx], None)
        self.coordinator = make(config.COORDINATOR_PRIVATE_KEY, 0)
        self.client_signers = [make(config.CLIENT_PRIVATE_KEYS[i], i + 1) for i in range(len(config.CLIENT_NAMES))]

    def _candidate_addresses(self) -> list[str]:
        out = []
        if config.CONTRACT_ADDRESS:
            out.append(config.CONTRACT_ADDRESS)
        if config.DEPLOYMENT_FILE.exists():
            try:
                out.append(json.loads(config.DEPLOYMENT_FILE.read_text())["address"])
            except Exception:
                pass
        if config.IGNITION_DEPLOYMENT.exists():
            try:
                data = json.loads(config.IGNITION_DEPLOYMENT.read_text())
                out.extend(v for k, v in data.items() if k.endswith("#DataSentryRegistry"))
            except Exception:
                pass
        return out

    def connect(self, auto_deploy: bool = True) -> bool:
        with self._lock:
            try:
                self.w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 15}))
                if not self.w3.is_connected():
                    raise BlockchainError(f"cannot reach Ethereum RPC at {self.rpc_url} (is `npx hardhat node` running?)")
                chain_id = self.w3.eth.chain_id
                if chain_id != config.CHAIN_ID:
                    raise BlockchainError(f"connected to chain {chain_id}, expected {config.CHAIN_ID}")
                art = self._load_artifact()
                self._signers()
                address = None
                for cand in self._candidate_addresses():
                    try:
                        cs = Web3.to_checksum_address(cand)
                    except Exception:
                        continue
                    if len(self.w3.eth.get_code(cs)) > 0:
                        c = self.w3.eth.contract(address=cs, abi=art["abi"])
                        try:
                            if c.functions.coordinator().call() == self.coordinator.address:
                                address = cs
                                break
                        except Exception:
                            continue
                if address is None:
                    if not auto_deploy:
                        raise BlockchainError("DataSentryRegistry is not deployed on this chain")
                    address = self._deploy(art)
                self.address = address
                self.contract = self.w3.eth.contract(address=address, abi=art["abi"])
                self.last_error = None
                log.info("blockchain connected chain=%s contract=%s", chain_id, address)
                return True
            except Exception as e:  # keep the API up; health endpoint reports the reason
                self.contract = None
                self.last_error = str(e)
                log.warning("blockchain unavailable: %s", e)
                return False

    def _deploy(self, art: dict) -> str:
        factory = self.w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
        receipt = self._send(self.coordinator, factory.constructor())
        address = receipt["contractAddress"]
        config.DEPLOYMENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        config.DEPLOYMENT_FILE.write_text(json.dumps({
            "address": address, "chain_id": config.CHAIN_ID, "tx_hash": receipt["transactionHash"],
            "block_number": receipt["blockNumber"], "deployer": self.coordinator.address,
        }, indent=2))
        self.deployed_by_backend = True
        log.info("deployed DataSentryRegistry at %s", address)
        return address

    def require_ready(self) -> None:
        if not self.ready:
            if not self.connect():
                raise BlockchainError(self.last_error or "blockchain unavailable")

    # ---------------------------------------------------------- transactions
    def _send(self, signer: _Signer, fn) -> dict:
        """Send a contract call/constructor, wait for the receipt, verify status."""
        with self._lock:
            tx_hash = None
            try:
                params: dict[str, Any] = {"from": signer.address, "chainId": config.CHAIN_ID}
                if signer.key:
                    params["nonce"] = self.w3.eth.get_transaction_count(signer.address, "pending")
                    params["gas"] = int(fn.estimate_gas({"from": signer.address}) * 1.25)
                    params["gasPrice"] = self.w3.eth.gas_price
                    tx = fn.build_transaction(params)
                    signed = self.w3.eth.account.sign_transaction(tx, signer.key)
                    tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
                else:
                    params["gas"] = int(fn.estimate_gas({"from": signer.address}) * 1.25)
                    tx_hash = fn.transact(params)
                receipt = self.w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
            except ContractLogicError as e:
                raise BlockchainError(f"contract reverted: {e}", tx_hash.hex() if tx_hash else None) from e
            except BlockchainError:
                raise
            except Exception as e:
                raise BlockchainError(f"transaction failed: {e}", tx_hash.hex() if tx_hash else None) from e
            h = "0x" + bytes(receipt["transactionHash"]).hex().removeprefix("0x")
            if receipt["status"] != 1:
                raise BlockchainError("transaction reverted (receipt status 0)", h)
            return {
                "transactionHash": h,
                "blockNumber": int(receipt["blockNumber"]),
                "gasUsed": int(receipt["gasUsed"]),
                "from": signer.address,
                "contractAddress": receipt.get("contractAddress"),
                "logs": receipt["logs"],
                "_raw": receipt,
            }

    def client_address(self, client_index: int) -> str:
        return self.client_signers[client_index].address

    def register_participant(self, client_index: int, name: str) -> Optional[dict]:
        """Register a client wallet; returns the receipt or None if already active."""
        self.require_ready()
        addr = self.client_address(client_index)
        if self.contract.functions.isActiveParticipant(addr).call():
            return None
        return self._send(self.coordinator, self.contract.functions.registerParticipant(addr, name))

    def start_round(self, experiment_id: str, round_number: int) -> tuple[int, dict]:
        self.require_ready()
        exp = Web3.keccak(text=experiment_id)
        rc = self._send(self.coordinator, self.contract.functions.startRound(exp, round_number))
        events = self.contract.events.RoundStarted().process_receipt(rc["_raw"])
        if not events:
            raise BlockchainError("RoundStarted event missing from receipt", rc["transactionHash"])
        return int(events[0]["args"]["roundId"]), rc

    def submit_update(self, client_index: int, chain_round_id: int, update_hash: str) -> dict:
        self.require_ready()
        return self._send(self.client_signers[client_index],
                          self.contract.functions.submitUpdate(chain_round_id, to_bytes32(update_hash)))

    def record_decision(self, chain_round_id: int, client_index: int, risk: float, decision: str, included: bool) -> dict:
        self.require_ready()
        bps = int(round(min(max(risk, 0.0), 1.0) * 10_000))
        return self._send(self.coordinator, self.contract.functions.recordDecision(
            chain_round_id, self.client_address(client_index), bps, DECISION_CODES[decision], bool(included)))

    def finalize_round(self, chain_round_id: int, global_hash: str) -> dict:
        self.require_ready()
        return self._send(self.coordinator, self.contract.functions.finalizeRound(chain_round_id, to_bytes32(global_hash)))

    # ---------------------------------------------------------------- reads
    def get_update(self, chain_round_id: int, address: str) -> dict:
        self.require_ready()
        r = self.contract.functions.getUpdate(chain_round_id, Web3.to_checksum_address(address)).call()
        return {
            "participant": r[0], "round_id": int(r[1]), "update_hash": "0x" + bytes(r[2]).hex(),
            "risk_score_bps": int(r[3]), "risk_score": int(r[3]) / 10_000, "decision": DECISION_NAMES[int(r[4])],
            "included_in_aggregation": bool(r[5]), "submitted_at": int(r[6]), "decided_at": int(r[7]),
        }

    def get_round(self, chain_round_id: int) -> dict:
        self.require_ready()
        r = self.contract.functions.getRound(chain_round_id).call()
        return {
            "experiment_id": "0x" + bytes(r[0]).hex(), "round_number": int(r[1]), "status": ROUND_STATUS[int(r[2])],
            "global_model_hash": "0x" + bytes(r[3]).hex(), "submissions": int(r[4]), "decided": int(r[5]),
            "included_count": int(r[6]), "started_at": int(r[7]), "finalized_at": int(r[8]),
        }

    def get_participant(self, address: str) -> dict:
        self.require_ready()
        p = self.contract.functions.getParticipant(Web3.to_checksum_address(address)).call()
        return {"name": p[0], "active": p[1], "registered_at": int(p[2]), "submissions": int(p[3]),
                "accepted": int(p[4]), "suspicious": int(p[5]), "rejected": int(p[6])}

    def get_transaction(self, tx_hash: str) -> dict:
        """Fetch a receipt from the chain and decode DataSentry events in it."""
        self.require_ready()
        receipt = self.w3.eth.get_transaction_receipt(tx_hash)
        tx = self.w3.eth.get_transaction(tx_hash)
        block = self.w3.eth.get_block(receipt["blockNumber"])
        events = []
        for ev_name in ("ParticipantRegistered", "RoundStarted", "UpdateSubmitted", "UpdateDecision",
                        "VerdictOverridden", "RoundFinalized"):
            try:
                for ev in getattr(self.contract.events, ev_name)().process_receipt(receipt, errors=DISCARD):
                    args = {}
                    for k, v in dict(ev["args"]).items():
                        if isinstance(v, (bytes, bytearray)):
                            v = "0x" + bytes(v).hex()
                        if ev_name == "UpdateDecision" and k == "decision":
                            v = DECISION_NAMES.get(int(v), v)
                        args[k] = v
                    events.append({"event": ev_name, "args": args})
            except Exception:
                continue
        return {
            "tx_hash": tx_hash,
            "status": "confirmed" if receipt["status"] == 1 else "failed",
            "block_number": int(receipt["blockNumber"]),
            "block_hash": "0x" + bytes(receipt["blockHash"]).hex().removeprefix("0x"),
            "timestamp": int(block["timestamp"]),
            "from": tx["from"],
            "to": tx["to"],
            "gas_used": int(receipt["gasUsed"]),
            "confirmations": max(0, int(self.w3.eth.block_number) - int(receipt["blockNumber"]) + 1),
            "events": events,
        }

    def status(self) -> dict:
        connected = self._is_connected()
        out = {
            "connected": connected and self.contract is not None,
            "rpc_url": self.rpc_url,
            "chain_id": config.CHAIN_ID,
            "contract_address": self.address,
            "coordinator": self.coordinator.address if self.coordinator else None,
            "signing": ("local-keys" if (self.coordinator and self.coordinator.key) else "node-managed-accounts")
            if self.coordinator else None,
            "error": self.last_error,
        }
        if out["connected"]:
            try:
                out["block_number"] = int(self.w3.eth.block_number)
                out["round_count"] = int(self.contract.functions.roundCount().call())
                out["update_count"] = int(self.contract.functions.updateCount().call())
            except Exception as e:
                out["connected"] = False
                out["error"] = str(e)
        return out

    def abi(self) -> list:
        return self._load_artifact()["abi"]


blockchain = BlockchainService()
