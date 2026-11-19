import copy
import hashlib
import json

import pytest

from bitcoin_ai.research_comparison import ComparisonError, compare_completed_research


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def fixtures(n=200):
    plan = {
        "dataset_fingerprint": "a" * 64, "code_revision": "abc123",
        "test_window": {"start": "2025-01-01T00:00:00+00:00", "end": "2025-01-09T08:00:00+00:00"},
        "candidates": {
            "proposal": {"family": "momentum", "lookback": 20},
            "unchanged_source": {"family": "sma", "lookback": 50},
            "cash": {"family": "cash", "lookback": 1},
        },
    }
    streams = {
        "momentum:20": [0.002] * n,
        "sma:50": [0.001] * n,
        "cash:1": [0.0] * n,
    }
    fixed = {name: {"returns": values, "doubled_cost_returns": [v - 0.0001 for v in values]} for name, values in streams.items()}
    report = {"fixed_candidate_oos_comparison": {"candidates": fixed}}
    receipt_core = {
        "schema_version": 1, "experiment_id": "walk-forward:" + _hash(plan),
        "plan_id": _hash(plan), "dataset_fingerprint": plan["dataset_fingerprint"],
        "code_revision": plan["code_revision"], "test_window": plan["test_window"],
        "research_report_sha256": _hash(report),
    }
    receipt = {**receipt_core, "receipt_id": _hash(receipt_core), "limitations": []}
    controlled = {
        "status": "completed_research_only", "execution_authority": "none",
        "experiment_id": receipt_core["experiment_id"], "plan_id": _hash(plan),
        "plan": plan, "research_report": report, "reproducibility_receipt": receipt,
    }
    evidence = {
        "evaluation_type": "read_only_fresh_evidence", "status": "eligible_for_human_review",
        "provenance": {"dataset_fingerprint": plan["dataset_fingerprint"], "code_revision": plan["code_revision"],
                       "test_start": plan["test_window"]["start"], "test_end": plan["test_window"]["end"], "observations": n},
        "comparisons": {"source": {"paired_edge_lower_5pct_pct_points": 0.1}, "cash": {"paired_edge_lower_5pct_pct_points": 0.2}},
        "gates": {"paired": True},
    }
    return controlled, evidence


def test_comparison_binds_receipt_and_reports_research_only_status():
    controlled, evidence = fixtures()
    result = compare_completed_research(controlled, evidence)
    assert result["status"] == "supports_further_human_review"
    assert result["execution_authority"] == "none"
    assert result["comparisons"]["source"]["proposal_minus_comparator_pct_points"] > 0
    assert result["statistical_evidence"]["corrected_p_values"] == "not_available_in_supplied_evidence"


def test_tampered_report_is_rejected():
    controlled, evidence = fixtures()
    controlled["research_report"]["tampered"] = True
    with pytest.raises(ComparisonError, match="report digest"):
        compare_completed_research(controlled, evidence)


def test_invalid_receipt_digest_is_rejected():
    controlled, evidence = fixtures()
    controlled["reproducibility_receipt"]["receipt_id"] = "0" * 64
    with pytest.raises(ComparisonError, match="receipt digest"):
        compare_completed_research(controlled, evidence)


def test_provenance_mismatch_is_rejected():
    controlled, evidence = fixtures()
    evidence["provenance"]["dataset_fingerprint"] = "b" * 64
    with pytest.raises(ComparisonError, match="dataset_fingerprint"):
        compare_completed_research(controlled, evidence)


def test_missing_candidate_or_misaligned_stream_fails_closed():
    controlled, evidence = fixtures()
    del controlled["research_report"]["fixed_candidate_oos_comparison"]["candidates"]["cash:1"]
    controlled["reproducibility_receipt"]["research_report_sha256"] = _hash(controlled["research_report"])
    core = {k: v for k, v in controlled["reproducibility_receipt"].items() if k not in {"receipt_id", "limitations"}}
    controlled["reproducibility_receipt"]["receipt_id"] = _hash(core)
    with pytest.raises(ComparisonError, match="missing the cash"):
        compare_completed_research(controlled, evidence)


def test_underpowered_stream_is_labeled_insufficient():
    controlled, evidence = fixtures(n=20)
    result = compare_completed_research(controlled, evidence, min_observations=180)
    assert result["status"] == "insufficient_evidence"


def test_execution_authority_is_never_accepted():
    controlled, evidence = fixtures()
    controlled["execution_authority"] = "paper_trading"
    with pytest.raises(ComparisonError, match="execution authority"):
        compare_completed_research(controlled, evidence)
