"""Unit tests: data partitioning, model, hashing, aggregation, attacks, trust."""
import numpy as np
import pytest
import torch

import config
from core.aggregation import AggregationInput, fedavg
from core.attack_simulator import AttackConfig, flip_labels, manipulate_update
from core.client_manager import FederatedClient, LocalTrainingConfig
from core.trust_engine import NEUTRAL_TRUST, TrustEngine
from datasets.prepare_data import load_federated_dataset, partition_indices
from models.neural_network import (create_model, flatten, get_params, hash_params, serialize_params,
                                   set_params, unflatten)


@pytest.fixture(scope="module")
def data():
    return load_federated_dataset(config.CLIENT_NAMES, seed=42)


# ------------------------------------------------------------- partitioning
def test_partition_is_disjoint_complete_and_deterministic():
    y = np.array([0] * 60 + [1] * 100)
    a = partition_indices(y, 4, seed=7)
    b = partition_indices(y, 4, seed=7)
    allidx = np.concatenate(a)
    assert sorted(allidx.tolist()) == list(range(len(y)))          # complete & disjoint
    assert all(np.array_equal(x, z) for x, z in zip(a, b))          # deterministic
    for p in a:                                                     # every client has both classes
        assert (y[p] == 0).sum() >= 5 and (y[p] == 1).sum() >= 5


def test_iid_partition_is_balanced():
    parts = partition_indices(np.zeros(100, dtype=int), 4, seed=1, strategy="iid")
    assert [len(p) for p in parts] == [25, 25, 25, 25]


def test_federated_dataset_split(data):
    assert len(data.clients) == 4
    assert data.X_test.shape[1] == 30
    total = sum(c.num_samples for c in data.clients) + len(data.y_val) + len(data.y_test)
    assert total == 569
    # test set rows never appear in any client partition
    test_rows = {r.tobytes() for r in data.X_test}
    for c in data.clients:
        assert not test_rows & {r.tobytes() for r in c.X}


# ------------------------------------------------------------------- model
def test_network_architecture_and_local_training_reduces_loss(data):
    model = create_model(0)
    assert [p.shape for p in model.parameters()] == [
        torch.Size([64, 30]), torch.Size([64]), torch.Size([32, 64]), torch.Size([32]),
        torch.Size([2, 32]), torch.Size([2])]
    template = get_params(model)
    client = FederatedClient(data.clients[2], 2)
    upd = client.local_train(flatten(template), template, LocalTrainingConfig(epochs=3), seed=1)
    assert upd.epoch_losses[-1] < upd.epoch_losses[0]
    assert upd.delta.shape == flatten(template).shape
    assert not upd.is_malicious


def test_hash_is_deterministic_and_sensitive():
    p = get_params(create_model(3))
    assert hash_params(p) == hash_params(get_params(create_model(3)))
    assert len(hash_params(p)) == 66 and hash_params(p).startswith("0x")
    q = unflatten(flatten(p).copy(), p)
    q["fc3.bias"][0] += 1e-6
    assert hash_params(q) != hash_params(p)
    assert serialize_params(p).startswith(b"DSv1")


def test_flatten_roundtrip():
    m = create_model(5)
    p = get_params(m)
    m2 = create_model(6)
    set_params(m2, unflatten(flatten(p), p))
    assert np.array_equal(flatten(get_params(m2)), flatten(p))
    with pytest.raises(ValueError):
        unflatten(np.zeros(10), p)


# ------------------------------------------------------------- aggregation
def _inp(name, vec, n=10, w=1.0, decision="ACCEPT"):
    return AggregationInput(name, np.asarray(vec, dtype=np.float32), n, w, decision)


def test_fedavg_weighted_mean():
    g = np.zeros(2, dtype=np.float32)
    res = fedavg(g, [_inp("a", [1, 1], n=10), _inp("b", [4, 4], n=30)])
    assert np.allclose(res.new_global, [3.25, 3.25])
    assert res.included == ["a", "b"] and res.excluded == []


def test_rejected_updates_never_enter_aggregation():
    g = np.zeros(2, dtype=np.float32)
    # even with a non-zero weight multiplier a REJECT decision is filtered out
    res = fedavg(g, [_inp("a", [1, 1]), _inp("evil", [1000, -1000], w=1.0, decision="REJECT")])
    assert np.allclose(res.new_global, [1, 1])
    assert res.excluded == ["evil"]
    assert "evil" not in res.effective_weights


def test_suspicious_downweighting_and_all_rejected():
    g = np.ones(2, dtype=np.float32)
    res = fedavg(g, [_inp("a", [2, 2]), _inp("s", [6, 6], w=0.5, decision="SUSPICIOUS")])
    assert np.allclose(res.aggregated_delta, [(2 * 10 + 6 * 5) / 15] * 2)
    none = fedavg(g, [_inp("x", [5, 5], decision="REJECT")])
    assert np.array_equal(none.new_global, g) and none.included == []


# ----------------------------------------------------------------- attacks
def test_label_flipping_flips_exact_fraction():
    y = np.array([0, 1] * 50)
    flipped, idx = flip_labels(y, 0.3, seed=1)
    assert len(idx) == 30
    assert np.all(flipped[idx] == 1 - y[idx])
    mask = np.ones(len(y), bool)
    mask[idx] = False
    assert np.array_equal(flipped[mask], y[mask])
    assert np.array_equal(flip_labels(y, 1.0, 0)[0], 1 - y)


def test_update_manipulation():
    d = np.array([1.0, -2.0], dtype=np.float32)
    assert np.allclose(manipulate_update(d, AttackConfig(True, attack_type="sign_flip", strength=2)), [-2, 4])
    assert np.allclose(manipulate_update(d, AttackConfig(True, attack_type="scaling", strength=3)), [3, -6])
    assert np.allclose(manipulate_update(d, AttackConfig(True, attack_type="label_flip")), d)
    with pytest.raises(ValueError):
        AttackConfig(True, attack_type="nope").validate()


def test_attack_only_applies_to_target(data):
    template = get_params(create_model(0))
    atk = AttackConfig(enabled=True, target_client="Hospital Delta", attack_type="label_flip", flip_rate=1.0)
    honest = FederatedClient(data.clients[0], 0).local_train(flatten(template), template, LocalTrainingConfig(), 1, atk)
    evil = FederatedClient(data.clients[3], 3).local_train(flatten(template), template, LocalTrainingConfig(), 1, atk)
    assert not honest.is_malicious and evil.is_malicious
    assert evil.attack_details["labels_flipped"] == data.clients[3].num_samples


# ------------------------------------------------------------------- trust
def test_trust_score_formula():
    t = TrustEngine(alpha=0.5)
    assert t.trust("new") == NEUTRAL_TRUST
    t.update("a", 0.1, "ACCEPT")             # ema = 0.5*0.1 + 0.5*0.5 = 0.3
    assert t.trust("a") == pytest.approx(70.0)
    t.update("a", 0.1, "ACCEPT")             # ema = 0.2
    assert t.trust("a") == pytest.approx(80.0)
    t.update("b", 1.0, "REJECT")             # ema = 0.75
    assert t.trust("b") == pytest.approx(25.0)
    snap = t.snapshot()
    assert snap["a"]["accepted"] == 2 and snap["b"]["rejected"] == 1
    assert snap["a"]["history"] == [70.0, 80.0]
    with pytest.raises(ValueError):
        TrustEngine(alpha=0)
