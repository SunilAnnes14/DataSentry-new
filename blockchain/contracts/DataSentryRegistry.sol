// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @title DataSentryRegistry
/// @notice Tamper-evident audit trail for federated learning rounds.
/// @dev Only hashes, scores and decisions are stored on-chain. Raw datasets and
///      model parameters NEVER touch the chain.
///
///      Roles:
///        - coordinator : registers participants, opens rounds, records the AI
///                        security verdict for each update, finalizes rounds.
///        - participant : a registered, active organisation wallet that can only
///                        submit the hash of ITS OWN model update.
contract DataSentryRegistry {
    enum Decision { None, Accepted, Suspicious, Rejected }
    enum RoundStatus { None, Open, Finalized }

    struct Participant {
        string name;
        bool active;
        uint64 registeredAt;
        uint32 submissions;
        uint32 accepted;
        uint32 suspicious;
        uint32 rejected;
    }

    struct UpdateRecord {
        address participant;
        uint256 roundId;
        bytes32 updateHash;
        uint16 riskScoreBps;      // AI risk score * 10_000 (0..10_000)
        Decision decision;
        bool includedInAggregation;
        uint64 submittedAt;
        uint64 decidedAt;
    }

    struct Round {
        bytes32 experimentId;
        uint32 roundNumber;
        RoundStatus status;
        bytes32 globalModelHash;
        uint32 submissions;
        uint32 decided;
        uint32 includedCount;
        uint64 startedAt;
        uint64 finalizedAt;
    }

    uint16 public constant MAX_RISK_BPS = 10_000;

    address public coordinator;
    uint256 public roundCount;
    uint256 public updateCount;

    mapping(address => Participant) private participants;
    address[] private participantList;
    mapping(uint256 => Round) private rounds;
    mapping(uint256 => address[]) private roundParticipants;
    mapping(uint256 => mapping(address => UpdateRecord)) private updates;
    mapping(address => uint256[]) private participantRounds;

    // ------------------------------------------------------------------ events
    event CoordinatorTransferred(address indexed previousCoordinator, address indexed newCoordinator);
    event ParticipantRegistered(address indexed wallet, string name);
    event ParticipantStatusChanged(address indexed wallet, bool active);
    event RoundStarted(uint256 indexed roundId, bytes32 indexed experimentId, uint32 roundNumber);
    event UpdateSubmitted(uint256 indexed roundId, address indexed participant, bytes32 updateHash);
    event UpdateDecision(
        uint256 indexed roundId,
        address indexed participant,
        bytes32 updateHash,
        uint16 riskScoreBps,
        Decision decision,
        bool includedInAggregation
    );
    event VerdictOverridden(uint256 indexed roundId, address indexed participant, uint16 riskScoreBps);
    event RoundFinalized(uint256 indexed roundId, bytes32 globalModelHash, uint32 includedCount, uint32 submissions);

    // ------------------------------------------------------------------ errors
    error NotCoordinator();
    error NotAuthorizedParticipant(address caller);
    error ZeroAddress();
    error EmptyName();
    error AlreadyRegistered(address wallet);
    error UnknownParticipant(address wallet);
    error InvalidHash();
    error InvalidRiskScore(uint16 riskScoreBps);
    error InvalidDecision();
    error RoundNotOpen(uint256 roundId);
    error UnknownRound(uint256 roundId);
    error DuplicateSubmission(uint256 roundId, address participant);
    error NoSubmission(uint256 roundId, address participant);
    error AlreadyDecided(uint256 roundId, address participant);
    error PendingDecisions(uint256 roundId, uint32 pending);
    error EmptyRound(uint256 roundId);

    modifier onlyCoordinator() {
        if (msg.sender != coordinator) revert NotCoordinator();
        _;
    }

    modifier onlyActiveParticipant() {
        if (!participants[msg.sender].active) revert NotAuthorizedParticipant(msg.sender);
        _;
    }

    constructor() {
        coordinator = msg.sender;
        emit CoordinatorTransferred(address(0), msg.sender);
    }

    // --------------------------------------------------------- administration
    function transferCoordinator(address newCoordinator) external onlyCoordinator {
        if (newCoordinator == address(0)) revert ZeroAddress();
        emit CoordinatorTransferred(coordinator, newCoordinator);
        coordinator = newCoordinator;
    }

    function registerParticipant(address wallet, string calldata name) external onlyCoordinator {
        if (wallet == address(0)) revert ZeroAddress();
        if (bytes(name).length == 0) revert EmptyName();
        if (participants[wallet].registeredAt != 0) revert AlreadyRegistered(wallet);
        participants[wallet] = Participant({
            name: name,
            active: true,
            registeredAt: uint64(block.timestamp),
            submissions: 0,
            accepted: 0,
            suspicious: 0,
            rejected: 0
        });
        participantList.push(wallet);
        emit ParticipantRegistered(wallet, name);
    }

    function setParticipantActive(address wallet, bool active) external onlyCoordinator {
        if (participants[wallet].registeredAt == 0) revert UnknownParticipant(wallet);
        participants[wallet].active = active;
        emit ParticipantStatusChanged(wallet, active);
    }

    // ----------------------------------------------------------------- rounds
    function startRound(bytes32 experimentId, uint32 roundNumber) external onlyCoordinator returns (uint256 roundId) {
        roundId = ++roundCount;
        rounds[roundId] = Round({
            experimentId: experimentId,
            roundNumber: roundNumber,
            status: RoundStatus.Open,
            globalModelHash: bytes32(0),
            submissions: 0,
            decided: 0,
            includedCount: 0,
            startedAt: uint64(block.timestamp),
            finalizedAt: 0
        });
        emit RoundStarted(roundId, experimentId, roundNumber);
    }

    /// @notice A participant records the SHA-256 hash of its own model update.
    function submitUpdate(uint256 roundId, bytes32 updateHash) external onlyActiveParticipant {
        Round storage r = rounds[roundId];
        if (r.status != RoundStatus.Open) revert RoundNotOpen(roundId);
        if (updateHash == bytes32(0)) revert InvalidHash();
        if (updates[roundId][msg.sender].submittedAt != 0) revert DuplicateSubmission(roundId, msg.sender);

        updates[roundId][msg.sender] = UpdateRecord({
            participant: msg.sender,
            roundId: roundId,
            updateHash: updateHash,
            riskScoreBps: 0,
            decision: Decision.None,
            includedInAggregation: false,
            submittedAt: uint64(block.timestamp),
            decidedAt: 0
        });
        roundParticipants[roundId].push(msg.sender);
        participantRounds[msg.sender].push(roundId);
        r.submissions += 1;
        participants[msg.sender].submissions += 1;
        updateCount += 1;
        emit UpdateSubmitted(roundId, msg.sender, updateHash);
    }

    /// @notice The coordinator records the AI security engine's verdict.
    function recordDecision(
        uint256 roundId,
        address participant,
        uint16 riskScoreBps,
        Decision decision,
        bool includedInAggregation
    ) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.status != RoundStatus.Open) revert RoundNotOpen(roundId);
        UpdateRecord storage u = updates[roundId][participant];
        if (u.submittedAt == 0) revert NoSubmission(roundId, participant);
        if (u.decision != Decision.None) revert AlreadyDecided(roundId, participant);
        if (riskScoreBps > MAX_RISK_BPS) revert InvalidRiskScore(riskScoreBps);
        if (decision == Decision.None) revert InvalidDecision();
        // A Rejected verdict with includedInAggregation == true is deliberately
        // allowed: it truthfully records that the coordinator aggregated an update
        // the AI flagged (e.g. undefended baseline runs), making such behaviour
        // publicly auditable instead of hiding it. The event flags it explicitly.
        if (decision == Decision.Rejected && includedInAggregation) {
            emit VerdictOverridden(roundId, participant, riskScoreBps);
        }

        u.riskScoreBps = riskScoreBps;
        u.decision = decision;
        u.includedInAggregation = includedInAggregation;
        u.decidedAt = uint64(block.timestamp);
        r.decided += 1;
        if (includedInAggregation) r.includedCount += 1;

        Participant storage p = participants[participant];
        if (decision == Decision.Accepted) p.accepted += 1;
        else if (decision == Decision.Suspicious) p.suspicious += 1;
        else p.rejected += 1;

        emit UpdateDecision(roundId, participant, u.updateHash, riskScoreBps, decision, includedInAggregation);
    }

    function finalizeRound(uint256 roundId, bytes32 globalModelHash) external onlyCoordinator {
        Round storage r = rounds[roundId];
        if (r.status == RoundStatus.None) revert UnknownRound(roundId);
        if (r.status != RoundStatus.Open) revert RoundNotOpen(roundId);
        if (globalModelHash == bytes32(0)) revert InvalidHash();
        if (r.submissions == 0) revert EmptyRound(roundId);
        if (r.decided != r.submissions) revert PendingDecisions(roundId, r.submissions - r.decided);

        r.status = RoundStatus.Finalized;
        r.globalModelHash = globalModelHash;
        r.finalizedAt = uint64(block.timestamp);
        emit RoundFinalized(roundId, globalModelHash, r.includedCount, r.submissions);
    }

    // ---------------------------------------------------------------- getters
    function getParticipant(address wallet) external view returns (Participant memory) {
        if (participants[wallet].registeredAt == 0) revert UnknownParticipant(wallet);
        return participants[wallet];
    }

    function isActiveParticipant(address wallet) external view returns (bool) {
        return participants[wallet].active;
    }

    function getParticipants() external view returns (address[] memory) {
        return participantList;
    }

    function getRound(uint256 roundId) external view returns (Round memory) {
        if (rounds[roundId].status == RoundStatus.None) revert UnknownRound(roundId);
        return rounds[roundId];
    }

    function getRoundParticipants(uint256 roundId) external view returns (address[] memory) {
        return roundParticipants[roundId];
    }

    function getUpdate(uint256 roundId, address participant) external view returns (UpdateRecord memory) {
        if (updates[roundId][participant].submittedAt == 0) revert NoSubmission(roundId, participant);
        return updates[roundId][participant];
    }

    function getParticipantRounds(address participant) external view returns (uint256[] memory) {
        return participantRounds[participant];
    }
}
