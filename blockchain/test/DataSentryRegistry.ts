import { expect } from "chai";
import { network } from "hardhat";

const { ethers, networkHelpers } = await network.create();

const ACCEPTED = 1;
const SUSPICIOUS = 2;
const REJECTED = 3;

const hashOf = (s: string) => ethers.sha256(ethers.toUtf8Bytes(s));
const EXP = ethers.id("experiment-1");

describe("DataSentryRegistry", function () {
  async function deployFixture() {
    const [coordinator, alpha, beta, outsider] = await ethers.getSigners();
    const registry = await ethers.deployContract("DataSentryRegistry");
    return { registry, coordinator, alpha, beta, outsider };
  }

  async function registeredWithOpenRound() {
    const f = await deployFixture();
    await f.registry.registerParticipant(f.alpha.address, "Hospital Alpha");
    await f.registry.registerParticipant(f.beta.address, "Hospital Beta");
    await f.registry.startRound(EXP, 1);
    return { ...f, roundId: 1n };
  }

  describe("deployment", function () {
    it("sets the deployer as coordinator and starts empty", async function () {
      const { registry, coordinator } = await networkHelpers.loadFixture(deployFixture);
      expect(await registry.coordinator()).to.equal(coordinator.address);
      expect(await registry.roundCount()).to.equal(0n);
      expect(await registry.getParticipants()).to.deep.equal([]);
    });
  });

  describe("registration", function () {
    it("registers a participant and emits ParticipantRegistered", async function () {
      const { registry, alpha } = await networkHelpers.loadFixture(deployFixture);
      await expect(registry.registerParticipant(alpha.address, "Hospital Alpha"))
        .to.emit(registry, "ParticipantRegistered")
        .withArgs(alpha.address, "Hospital Alpha");
      const p = await registry.getParticipant(alpha.address);
      expect(p.name).to.equal("Hospital Alpha");
      expect(p.active).to.equal(true);
      expect(await registry.isActiveParticipant(alpha.address)).to.equal(true);
    });

    it("rejects registration from a non-coordinator", async function () {
      const { registry, alpha, outsider } = await networkHelpers.loadFixture(deployFixture);
      await expect(registry.connect(outsider).registerParticipant(alpha.address, "X"))
        .to.be.revertedWithCustomError(registry, "NotCoordinator");
    });

    it("rejects duplicate, zero-address and empty-name registrations", async function () {
      const { registry, alpha } = await networkHelpers.loadFixture(deployFixture);
      await registry.registerParticipant(alpha.address, "Hospital Alpha");
      await expect(registry.registerParticipant(alpha.address, "Again"))
        .to.be.revertedWithCustomError(registry, "AlreadyRegistered");
      await expect(registry.registerParticipant(ethers.ZeroAddress, "Zero"))
        .to.be.revertedWithCustomError(registry, "ZeroAddress");
      const [, , , , other] = await ethers.getSigners();
      await expect(registry.registerParticipant(other.address, ""))
        .to.be.revertedWithCustomError(registry, "EmptyName");
    });
  });

  describe("update recording", function () {
    it("lets a registered participant submit its own update hash", async function () {
      const { registry, alpha, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      const h = hashOf("alpha-update");
      await expect(registry.connect(alpha).submitUpdate(roundId, h))
        .to.emit(registry, "UpdateSubmitted")
        .withArgs(roundId, alpha.address, h);
      const rec = await registry.getUpdate(roundId, alpha.address);
      expect(rec.updateHash).to.equal(h);
      expect(rec.participant).to.equal(alpha.address);
      expect(await registry.updateCount()).to.equal(1n);
    });

    it("blocks unregistered wallets and deactivated participants", async function () {
      const { registry, alpha, outsider, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      await expect(registry.connect(outsider).submitUpdate(roundId, hashOf("x")))
        .to.be.revertedWithCustomError(registry, "NotAuthorizedParticipant")
        .withArgs(outsider.address);
      await registry.setParticipantActive(alpha.address, false);
      await expect(registry.connect(alpha).submitUpdate(roundId, hashOf("x")))
        .to.be.revertedWithCustomError(registry, "NotAuthorizedParticipant");
    });

    it("prevents duplicate submissions in the same round", async function () {
      const { registry, alpha, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      await registry.connect(alpha).submitUpdate(roundId, hashOf("a"));
      await expect(registry.connect(alpha).submitUpdate(roundId, hashOf("b")))
        .to.be.revertedWithCustomError(registry, "DuplicateSubmission")
        .withArgs(roundId, alpha.address);
    });

    it("rejects zero hashes and submissions to unopened rounds", async function () {
      const { registry, alpha, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      await expect(registry.connect(alpha).submitUpdate(roundId, ethers.ZeroHash))
        .to.be.revertedWithCustomError(registry, "InvalidHash");
      await expect(registry.connect(alpha).submitUpdate(99n, hashOf("a")))
        .to.be.revertedWithCustomError(registry, "RoundNotOpen");
    });
  });

  describe("security decisions", function () {
    it("records a risk score and decision and updates participant counters", async function () {
      const { registry, alpha, beta, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      const h = hashOf("beta-poisoned");
      await registry.connect(alpha).submitUpdate(roundId, hashOf("alpha"));
      await registry.connect(beta).submitUpdate(roundId, h);
      await expect(registry.recordDecision(roundId, beta.address, 8123, REJECTED, false))
        .to.emit(registry, "UpdateDecision")
        .withArgs(roundId, beta.address, h, 8123, REJECTED, false);
      await registry.recordDecision(roundId, alpha.address, 1200, ACCEPTED, true);
      const rec = await registry.getUpdate(roundId, beta.address);
      expect(rec.riskScoreBps).to.equal(8123n);
      expect(rec.decision).to.equal(BigInt(REJECTED));
      expect(rec.includedInAggregation).to.equal(false);
      const p = await registry.getParticipant(beta.address);
      expect(p.rejected).to.equal(1n);
      expect(p.submissions).to.equal(1n);
    });

    it("rejects invalid risk scores and invalid decisions", async function () {
      const { registry, alpha, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      await registry.connect(alpha).submitUpdate(roundId, hashOf("a"));
      await expect(registry.recordDecision(roundId, alpha.address, 10_001, ACCEPTED, true))
        .to.be.revertedWithCustomError(registry, "InvalidRiskScore")
        .withArgs(10_001);
      await expect(registry.recordDecision(roundId, alpha.address, 100, 0, true))
        .to.be.revertedWithCustomError(registry, "InvalidDecision");
    });

    it("rejects decisions from non-coordinators, for missing submissions and twice", async function () {
      const { registry, alpha, beta, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      await registry.connect(alpha).submitUpdate(roundId, hashOf("a"));
      await expect(registry.connect(alpha).recordDecision(roundId, alpha.address, 0, ACCEPTED, true))
        .to.be.revertedWithCustomError(registry, "NotCoordinator");
      await expect(registry.recordDecision(roundId, beta.address, 0, ACCEPTED, true))
        .to.be.revertedWithCustomError(registry, "NoSubmission");
      await registry.recordDecision(roundId, alpha.address, 500, SUSPICIOUS, true);
      await expect(registry.recordDecision(roundId, alpha.address, 500, SUSPICIOUS, true))
        .to.be.revertedWithCustomError(registry, "AlreadyDecided");
    });

    it("flags an overridden REJECT verdict with VerdictOverridden", async function () {
      const { registry, alpha, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      await registry.connect(alpha).submitUpdate(roundId, hashOf("a"));
      await expect(registry.recordDecision(roundId, alpha.address, 9000, REJECTED, true))
        .to.emit(registry, "VerdictOverridden")
        .withArgs(roundId, alpha.address, 9000);
    });
  });

  describe("round finalization", function () {
    it("only the coordinator can start or finalize rounds", async function () {
      const { registry, alpha, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      await expect(registry.connect(alpha).startRound(EXP, 2))
        .to.be.revertedWithCustomError(registry, "NotCoordinator");
      await registry.connect(alpha).submitUpdate(roundId, hashOf("a"));
      await registry.recordDecision(roundId, alpha.address, 100, ACCEPTED, true);
      await expect(registry.connect(alpha).finalizeRound(roundId, hashOf("global")))
        .to.be.revertedWithCustomError(registry, "NotCoordinator");
    });

    it("refuses to finalize with pending decisions, empty rounds or zero hash", async function () {
      const { registry, alpha, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      await expect(registry.finalizeRound(roundId, hashOf("g")))
        .to.be.revertedWithCustomError(registry, "EmptyRound");
      await registry.connect(alpha).submitUpdate(roundId, hashOf("a"));
      await expect(registry.finalizeRound(roundId, hashOf("g")))
        .to.be.revertedWithCustomError(registry, "PendingDecisions")
        .withArgs(roundId, 1);
      await registry.recordDecision(roundId, alpha.address, 100, ACCEPTED, true);
      await expect(registry.finalizeRound(roundId, ethers.ZeroHash))
        .to.be.revertedWithCustomError(registry, "InvalidHash");
      await expect(registry.finalizeRound(42n, hashOf("g")))
        .to.be.revertedWithCustomError(registry, "UnknownRound");
    });

    it("finalizes a round with the global model hash and closes it", async function () {
      const { registry, alpha, beta, roundId } = await networkHelpers.loadFixture(registeredWithOpenRound);
      await registry.connect(alpha).submitUpdate(roundId, hashOf("a"));
      await registry.connect(beta).submitUpdate(roundId, hashOf("b"));
      await registry.recordDecision(roundId, alpha.address, 1000, ACCEPTED, true);
      await registry.recordDecision(roundId, beta.address, 9000, REJECTED, false);
      const g = hashOf("global-model-r1");
      await expect(registry.finalizeRound(roundId, g))
        .to.emit(registry, "RoundFinalized")
        .withArgs(roundId, g, 1, 2);
      const r = await registry.getRound(roundId);
      expect(r.status).to.equal(2n);
      expect(r.globalModelHash).to.equal(g);
      expect(r.includedCount).to.equal(1n);
      expect(await registry.getRoundParticipants(roundId)).to.deep.equal([alpha.address, beta.address]);
      expect(await registry.getParticipantRounds(alpha.address)).to.deep.equal([roundId]);
      // a finalized round is closed for further submissions and finalization
      await expect(registry.finalizeRound(roundId, g)).to.be.revertedWithCustomError(registry, "RoundNotOpen");
      const [, , , , late] = await ethers.getSigners();
      await registry.registerParticipant(late.address, "Late");
      await expect(registry.connect(late).submitUpdate(roundId, hashOf("late")))
        .to.be.revertedWithCustomError(registry, "RoundNotOpen");
    });

    it("emits RoundStarted with incrementing ids", async function () {
      const { registry } = await networkHelpers.loadFixture(deployFixture);
      await expect(registry.startRound(EXP, 1)).to.emit(registry, "RoundStarted").withArgs(1n, EXP, 1);
      await expect(registry.startRound(EXP, 2)).to.emit(registry, "RoundStarted").withArgs(2n, EXP, 2);
    });
  });

  describe("administration", function () {
    it("transfers the coordinator role", async function () {
      const { registry, coordinator, alpha } = await networkHelpers.loadFixture(deployFixture);
      await expect(registry.transferCoordinator(alpha.address))
        .to.emit(registry, "CoordinatorTransferred")
        .withArgs(coordinator.address, alpha.address);
      await expect(registry.startRound(EXP, 1)).to.be.revertedWithCustomError(registry, "NotCoordinator");
    });
  });
});
