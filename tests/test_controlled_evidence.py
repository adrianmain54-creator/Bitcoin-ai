from bitcoin_ai.candidate_registry import (
    complete_candidate_trial, register_candidate_trial,
)
from bitcoin_ai.holdout_ledger import audit_and_append_holdout_records
from bitcoin_ai.controlled_evidence import evaluate_controlled_experiment
from bitcoin_ai.candidate_registry import audit_candidate_family
from bitcoin_ai.fresh_evidence import FreshEvidenceError
import pytest


FP = "a" * 64
START = "2026-01-01T00:00:00+00:00"
END = "2026-07-01T00:00:00+00:00"
REV = "deadbeef"
PLAN_ID = "plan-123"
EXPERIMENT_ID = "walk-forward:" + PLAN_ID


def build_result(tmp_path):
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "holdouts.json"
    ids = {"proposal": "p", "source": "s", "cash": "c"}
    names = {
        "proposal": "agent_council_25:48",
        "source": "agent_council:48",
        "cash": "cash:2",
    }
    for role in ids:
        register_candidate_trial(
            registry, trial_id=ids[role], candidate_name=names[role],
            strategy_definition={"family": names[role]},
            dataset_fingerprint=FP, code_revision=REV,
            test_start=START, test_end=END,
            registered_at="2025-12-01T00:00:00+00:00",
        )
        complete_candidate_trial(
            registry, trial_id=ids[role],
            outcome={"observations": 200},
            completed_at="2026-07-02T00:00:00+00:00",
        )
    reservation = audit_and_append_holdout_records(ledger, [{
        "experiment_id": EXPERIMENT_ID,
        "dataset_fingerprint": FP,
        "test_start": START,
        "test_end": END,
    }])
    family = audit_candidate_family(
        registry, dataset_fingerprint=FP, test_start=START, test_end=END,
    )
    returns = {
        "agent_council_25:48": [0.002] * 200,
        "agent_council:48": [0.0005] * 200,
        "cash:2": [0.0] * 200,
    }
    stress = {
        "agent_council_25:48": [0.0015] * 200,
        "agent_council:48": [0.0002] * 200,
        "cash:2": [0.0] * 200,
    }
    result = {
        "status": "completed_research_only",
        "execution_authority": "none",
        "experiment_id": EXPERIMENT_ID,
        "plan": {
            "dataset_fingerprint": FP, "code_revision": REV,
            "test_window": {"start": START, "end": END},
            "candidates": {
                "proposal": {"family": "agent_council_25", "lookback": 48},
                "unchanged_source": {"family": "agent_council", "lookback": 48},
                "cash": {"family": "cash", "lookback": 2},
            },
        },
        "registered_trials": ids,
        "holdout_reservation": reservation,
        "candidate_family_audit": family,
        "research_report": {
            "fixed_candidate_oos_comparison": {
                "candidates": {
                    name: {
                        "returns": returns[name],
                        "doubled_cost_returns": stress[name],
                    } for name in names.values()
                }
            },
            "out_of_sample_regime_labels": ["uptrend"] * 100 + ["range"] * 100,
        },
    }
    return result, registry, ledger


def test_completed_controlled_run_bridges_exact_reserved_interval(tmp_path):
    result, registry, ledger = build_result(tmp_path)
    report = evaluate_controlled_experiment(
        result, candidate_registry_path=registry, holdout_ledger_path=ledger,
        bootstrap_trials=200,
    )
    assert report["status"] == "eligible_for_human_review"
    assert report["provenance"]["holdout_freshness"] == "no_overlap_detected"
    assert report["provenance"]["trials"]["proposal"]["candidate_name"] == "agent_council_25:48"


def test_bridge_rejects_missing_or_incomplete_family_audit(tmp_path):
    result, registry, ledger = build_result(tmp_path)
    result["candidate_family_audit"]["status"] = "review_required"
    with pytest.raises(FreshEvidenceError, match="family audit is not complete"):
        evaluate_controlled_experiment(
            result, candidate_registry_path=registry, holdout_ledger_path=ledger,
        )


def test_bridge_rejects_mismatched_reservation_and_streams(tmp_path):
    result, registry, ledger = build_result(tmp_path)
    result["experiment_id"] = "other-experiment"
    with pytest.raises(FreshEvidenceError, match="reservation is missing or ambiguous"):
        evaluate_controlled_experiment(
            result, candidate_registry_path=registry, holdout_ledger_path=ledger,
        )
    result, registry, ledger = build_result(tmp_path / "second")
    result["research_report"]["fixed_candidate_oos_comparison"]["candidates"]["cash:2"]["returns"].pop()
    with pytest.raises(FreshEvidenceError, match="not aligned"):
        evaluate_controlled_experiment(
            result, candidate_registry_path=registry, holdout_ledger_path=ledger,
            bootstrap_trials=200,
        )
