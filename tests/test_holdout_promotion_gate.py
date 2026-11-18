import pytest

from bitcoin_ai.promotion import evaluate_independent_strategy_validation


def candidate():
    return {
        "paired_edge_uncertainty": {
            "observations": 240,
            "observed_excess_return_pct": 8.0,
            "excess_return_p05_pct": 1.0,
            "probability_positive_pct": 97.0,
            "bootstrap_null_p_value": 0.001,
        },
        "metrics_at_2x_cost": {"total_return_pct": 3.0},
    }


def test_reused_holdout_blocks_paper_review_even_when_candidate_passes():
    result = evaluate_independent_strategy_validation(
        {"momentum:8": candidate()},
        {"usable": True, "status": "pass"},
        holdout_reuse_audit={
            "status": "reuse_detected",
            "eligible_for_fresh_holdout_review": False,
        },
    )
    assert result["verdict"] == "reject"
    assert result["evidence_reviewer"]["holdout_freshness_verified"] is False
    assert "held-out intervals overlap prior or same-run experiments" in (
        result["evidence_reviewer"]["errors"]
    )


def test_missing_prior_ledger_blocks_paper_review_when_audit_is_supplied():
    result = evaluate_independent_strategy_validation(
        {"momentum:8": candidate()},
        {"usable": True, "status": "pass"},
        holdout_reuse_audit={
            "status": "no_prior_ledger_supplied",
            "eligible_for_fresh_holdout_review": False,
        },
    )
    assert result["verdict"] == "reject"
    assert "no prior holdout ledger was supplied; freshness is unverified" in (
        result["evidence_reviewer"]["errors"]
    )


def test_clean_fresh_holdout_allows_review_gate_to_proceed():
    result = evaluate_independent_strategy_validation(
        {"momentum:8": candidate()},
        {"usable": True, "status": "pass"},
        holdout_reuse_audit={
            "status": "no_overlap_detected",
            "eligible_for_fresh_holdout_review": True,
        },
    )
    assert result["verdict"] == "eligible_for_paper_review"
    assert result["evidence_reviewer"]["holdout_freshness_verified"] is True
