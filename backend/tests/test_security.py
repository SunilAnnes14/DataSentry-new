"""Security engine & anomaly detector tests (real training, no mocked scores)."""
import math

import numpy as np
import pytest

import config
from core.attack_simulator import AttackConfig
from core.client_manager import FederatedClient, LocalTrainingConfig
from core.security_engine import SecurityConfig, SecurityEngine
from datasets.prepare_data import load_federated_dataset
from models.anomaly_detector import InsufficientHistoryError, UpdateAnomalyDetector
from models.neural_network import create_model, flatten, get_params


@pytest.fixture(scope="module")
def setup():
    data = load_federated_dataset(config.CLIENT_NAMES, seed=42)
    template = get_params(create_model(42))
    g = flatten(template)
    return data, template, g


def _round_updates(data, template, g, attack=None):
    cfg = LocalTrainingConfig()
    ups = [FederatedClient(p, i).local_train(g, template, cfg, seed=100 + i, attack=attack)
           for i, p in enumerate(data.clients)]
    steps = [cfg.epochs * math.ceil(u.num_samples / cfg.batch_size) for u in ups]
    return ups, steps


def _analyze(engine, data, template, g, ups, steps):
    return engine.analyze([u.client for u in ups], [u.delta for u in ups], g, template,
                          data.X_val, data.y_val, local_steps=steps)


def test_clean_round_accepts_all_honest_clients(setup):
    data, template, g = setup
    ups, steps = _round_updates(data, template, g)
    res = _analyze(SecurityEngine(SecurityConfig()), data, template, g, ups, steps)
    assert [a.decision for a in res] == ["ACCEPT"] * 4
    assert all(0.0 <= a.risk_score < 0.4 for a in res)
    assert all(a.detector_mode == "rule-based (warm-up)" for a in res)   # no history yet


def test_boosted_label_flip_is_rejected_with_explanation(setup):
    data, template, g = setup
    atk = AttackConfig(enabled=True, attack_type="label_flip_scaled", flip_rate=1.0, strength=3.0)
    ups, steps = _round_updates(data, template, g, atk)
    res = {a.client: a for a in _analyze(SecurityEngine(SecurityConfig()), data, template, g, ups, steps)}
    delta = res["Hospital Delta"]
    assert delta.decision == "REJECT" and delta.risk_score >= 0.7
    assert delta.aggregation_weight == 0.0
    assert delta.cosine_similarity < 0
    assert any("cosine" in e for e in delta.explanation)
    for name in ("Hospital Alpha", "Hospital Beta", "Hospital Gamma"):
        assert res[name].decision == "ACCEPT"


def test_sign_flip_attack_is_flagged(setup):
    data, template, g = setup
    atk = AttackConfig(enabled=True, attack_type="sign_flip", strength=2.0)
    ups, steps = _round_updates(data, template, g, atk)
    res = {a.client: a for a in _analyze(SecurityEngine(SecurityConfig()), data, template, g, ups, steps)}
    assert res["Hospital Delta"].decision in ("SUSPICIOUS", "REJECT")
    assert res["Hospital Delta"].risk_score > max(res[c].risk_score for c in res if c != "Hospital Delta")


def test_risk_formula_weights(setup):
    data, template, g = setup
    ups, steps = _round_updates(data, template, g)
    for a in _analyze(SecurityEngine(SecurityConfig()), data, template, g, ups, steps):
        expected = (0.35 * a.norm_anomaly + 0.30 * a.cosine_disagreement + 0.20 * a.deviation_score
                    + 0.15 * a.validation_impact)
        assert a.risk_score == pytest.approx(expected, abs=1e-4)
        for f in (a.norm_anomaly, a.cosine_disagreement, a.deviation_score, a.validation_impact):
            assert 0.0 <= f <= 1.0


def test_thresholds_are_configurable_and_validated(setup):
    data, template, g = setup
    ups, steps = _round_updates(data, template, g)
    strict = SecurityConfig(accept_threshold=0.0001, reject_threshold=0.0002)
    res = _analyze(SecurityEngine(strict), data, template, g, ups, steps)
    assert any(a.decision != "ACCEPT" for a in res)
    with pytest.raises(ValueError):
        SecurityConfig(accept_threshold=0.8, reject_threshold=0.5).validate()


def test_suspicious_policies():
    assert SecurityConfig(suspicious_policy="exclude").aggregation_weight("SUSPICIOUS") == 0.0
    assert SecurityConfig(suspicious_policy="downweight", suspicious_weight=0.3).aggregation_weight("SUSPICIOUS") == 0.3
    assert SecurityConfig().aggregation_weight("REJECT") == 0.0


def test_zero_updates_do_not_divide_by_zero(setup):
    data, template, g = setup
    zeros = [np.zeros_like(g) for _ in range(4)]
    res = SecurityEngine(SecurityConfig()).analyze(config.CLIENT_NAMES, zeros, g, template, data.X_val, data.y_val)
    assert all(np.isfinite(a.risk_score) for a in res)
    assert all(a.decision == "ACCEPT" for a in res)


def test_single_update_uses_fallback(setup):
    data, template, g = setup
    res = SecurityEngine(SecurityConfig()).analyze(["Hospital Alpha"], [np.ones_like(g) * 0.01], g, template,
                                                   data.X_val, data.y_val)
    assert len(res) == 1 and res[0].isolation_score is None
    assert res[0].detector_mode == "rule-based (warm-up)"


def test_isolation_forest_needs_history_and_becomes_hybrid(setup):
    with pytest.raises(InsufficientHistoryError):
        UpdateAnomalyDetector(min_samples=6).fit(np.zeros((1, 4)))
    with pytest.raises(ValueError):
        UpdateAnomalyDetector(min_samples=1)
    data, template, g = setup
    engine = SecurityEngine(SecurityConfig())
    ups, steps = _round_updates(data, template, g)
    _analyze(engine, data, template, g, ups, steps)                 # round 1: warm-up
    res2 = _analyze(engine, data, template, g, ups, steps)          # round 2: 4 history + 4 current
    assert all(a.detector_mode == "hybrid" and a.isolation_score is not None for a in res2)
    det = UpdateAnomalyDetector(min_samples=6, seed=0).fit(np.random.default_rng(0).normal(0, 0.01, (20, 4)))
    scores = det.score(np.array([[0, 0, 0, 0], [5, 5, 5, 5]]))
    assert scores[1] > scores[0] and np.all((scores >= 0) & (scores <= 1))
