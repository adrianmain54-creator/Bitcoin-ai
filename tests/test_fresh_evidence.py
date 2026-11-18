from bitcoin_ai.candidate_registry import register_candidate_trial
from bitcoin_ai.holdout_ledger import audit_and_append_holdout_records
from bitcoin_ai.fresh_evidence import FreshEvidenceError, evaluate_fresh_candidate
import pytest


FP = "a" * 64
START = "2026-01-01T00:00:00+00:00"
END = "2026-07-01T00:00:00+00:00"
REV = "deadbeef"


def setup_trials(tmp_path):
    registry = tmp_path / "candidates.json"
    ledger = tmp_path / "holdouts.json"
    ids = {"proposal": "trial-proposal", "source": "trial-source", "cash": "trial-cash"}
    names = {"proposal": "agent_council_25:48", "source": "agent_council:48", "cash": "cash:2"}
    for role in ids:
        register_candidate_trial(
            registry, trial_id=ids[role], candidate_name=names[role],
            strategy_definition={"family": names[role], "cost_bps": 10},
            dataset_fingerprint=FP, code_revision=REV,
            test_start=START, test_end=END,
            registered_at="2025-12-01T00:00:00+00:00",
        )
    return registry, ledger, ids, names


def evidence(n=200):
    returns = {
        "proposal": [0.002] * n,
        "source": [0.0005] * n,
        "cash": [0.0] * n,
    }
    stress = {
        "proposal": [0.0015] * n,
        "source": [0.0002] * n,
        "cash": [0.0] * n,
    }
    regimes = ["uptrend"] * (n // 2) + ["range"] * (n - n // 2)
    return returns, stress, regimes


def evaluate(registry, ledger, ids, names, **overrides):
    returns, stress, regimes = evidence()
    args = dict(
        trial_ids=ids, expected_candidate_names=names,
        dataset_fingerprint=FP, test_start=START, test_end=END,
        code_revision=REV, returns=returns, doubled_cost_returns=stress,
        regimes=regimes, bootstrap_trials=200,
    )
    args.update(overrides)
    return evaluate_fresh_candidate(registry, ledger, **args)


def test_fresh_paired_evidence_can_only_reach_human_review(tmp_path):
    registry, ledger, ids, names = setup_trials(tmp_path)
    report = evaluate(registry, ledger, ids, names)
    assert report["status"] == "eligible_for_human_review"
    assert report["evaluation_type"] == "read_only_fresh_evidence"
    assert all(report["gates"].values())
    assert report["provenance"]["holdout_freshness"] == "no_overlap_detected"
    assert "no promotion" in report["limitations"][-1]


def test_requires_all_three_preregistered_trials(tmp_path):
    registry, ledger, ids, names = setup_trials(tmp_path)
    ids["proposal"] = "missing"
    with pytest.raises(FreshEvidenceError, match="not preregistered"):
        evaluate(registry, ledger, ids, names)


def test_rejects_candidate_identity_mismatch(tmp_path):
    registry, ledger, ids, names = setup_trials(tmp_path)
    names["proposal"] = "agent_council_50:48"
    with pytest.raises(FreshEvidenceError, match="identity differs"):
        evaluate(registry, ledger, ids, names)


def test_rejects_dataset_or_code_mismatch(tmp_path):
    registry, ledger, ids, names = setup_trials(tmp_path)
    with pytest.raises(FreshEvidenceError, match="fingerprint differs"):
        evaluate(registry, ledger, ids, names, dataset_fingerprint="b" * 64)
    with pytest.raises(FreshEvidenceError, match="code revision differs"):
        evaluate(registry, ledger, ids, names, code_revision="other")


def test_rejects_already_used_holdout_interval(tmp_path):
    registry, ledger, ids, names = setup_trials(tmp_path)
    audit_and_append_holdout_records(ledger, [{
        "experiment_id": "old-run", "dataset_fingerprint": FP,
        "test_start": START, "test_end": END,
    }])
    with pytest.raises(FreshEvidenceError, match="already been used"):
        evaluate(registry, ledger, ids, names)


def test_underpowered_evidence_fails_closed(tmp_path):
    registry, ledger, ids, names = setup_trials(tmp_path)
    returns, stress, regimes = evidence(30)
    with pytest.raises(FreshEvidenceError, match="underpowered"):
        evaluate(registry, ledger, ids, names, returns=returns,
                 doubled_cost_returns=stress, regimes=regimes)


def test_rejects_misaligned_or_nonfinite_series(tmp_path):
    registry, ledger, ids, names = setup_trials(tmp_path)
    returns, stress, regimes = evidence()
    returns["source"] = returns["source"][:-1]
    with pytest.raises(FreshEvidenceError, match="not aligned"):
        evaluate(registry, ledger, ids, names, returns=returns)
    returns, stress, regimes = evidence()
    returns["proposal"][0] = float("nan")
    with pytest.raises(FreshEvidenceError, match="non-finite"):
        evaluate(registry, ledger, ids, names, returns=returns)


def test_negative_doubled_cost_or_underpowered_regime_blocks_review(tmp_path):
    registry, ledger, ids, names = setup_trials(tmp_path)
    returns, stress, regimes = evidence()
    stress["proposal"] = [-0.001] * len(stress["proposal"])
    report = evaluate(registry, ledger, ids, names, doubled_cost_returns=stress)
    assert report["status"] == "rejected_or_insufficient"
    assert not report["gates"]["positive_compounded_return_at_doubled_costs"]
    returns, stress, regimes = evidence()
    regimes = ["tiny"] + ["main"] * (len(regimes) - 1)
    report = evaluate(registry, ledger, ids, names, regimes=regimes)
    assert report["status"] == "rejected_or_insufficient"
    assert report["regime_robustness"]["tiny"]["interpretation"] == "underpowered_unknown"
