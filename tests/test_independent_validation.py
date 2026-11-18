import pytest

from bitcoin_ai.promotion import evaluate_independent_strategy_validation


def passing_candidate():
    return {
        "paired_edge_uncertainty": {
            "observations": 240,
            "observed_excess_return_pct": 8.0,
            "excess_return_p05_pct": 1.0,
            "probability_positive_pct": 97.0,
        },
        "metrics_at_2x_cost": {"total_return_pct": 3.0},
    }


def test_independent_validation_allows_human_paper_review_only():
    result = evaluate_independent_strategy_validation(
        {"momentum:8": passing_candidate()},
        {"usable": True, "status": "pass"},
    )
    assert result["verdict"] == "eligible_for_paper_review"
    assert result["proposer"]["fixed_candidates"] == ["momentum:8"]
    assert result["skeptic"]["passing_candidates"] == ["momentum:8"]
    assert result["evidence_reviewer"]["candidate_review_coverage"] == 1
    assert "never" not in result["scope"] or "authorization to trade" in result["scope"]


def test_independent_validation_rejects_weak_candidate():
    weak = passing_candidate()
    weak["paired_edge_uncertainty"]["excess_return_p05_pct"] = -0.1
    result = evaluate_independent_strategy_validation(
        {"weak": weak}, {"usable": True, "status": "pass"},
    )
    assert result["verdict"] == "reject"
    assert result["skeptic"]["candidate_reviews"]["weak"]["eligible_for_review"] is False


def test_independent_validation_requires_clean_data_for_eligibility():
    result = evaluate_independent_strategy_validation(
        {"candidate": passing_candidate()},
        {"usable": True, "status": "review"},
    )
    assert result["verdict"] == "needs_review"


def test_independent_validation_rejects_unusable_data_even_with_edge():
    result = evaluate_independent_strategy_validation(
        {"candidate": passing_candidate()},
        {"usable": False, "status": "fail"},
    )
    assert result["verdict"] == "reject"
    assert "historical data quality audit is not usable" in result["evidence_reviewer"]["errors"]


def test_independent_validation_rejects_empty_proposals():
    result = evaluate_independent_strategy_validation({}, {"usable": True, "status": "pass"})
    assert result["verdict"] == "reject"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("observed_excess_return_pct", float("nan")),
        ("excess_return_p05_pct", float("inf")),
        ("probability_positive_pct", True),
        ("observations", True),
    ],
)
def test_independent_validation_rejects_malformed_numeric_evidence(field, value):
    candidate = passing_candidate()
    target = "paired_edge_uncertainty"
    candidate[target][field] = value
    result = evaluate_independent_strategy_validation(
        {"tampered": candidate}, {"usable": True, "status": "pass"},
    )
    assert result["verdict"] == "reject"
    assert result["skeptic"]["candidate_reviews"]["tampered"]["eligible_for_review"] is False


def test_independent_validation_rejects_missing_cost_stress_evidence():
    candidate = passing_candidate()
    candidate["metrics_at_2x_cost"] = {}
    result = evaluate_independent_strategy_validation(
        {"tampered": candidate}, {"usable": True, "status": "pass"},
    )
    assert result["verdict"] == "reject"
    assert "required edge, probability, or stress metrics are missing or invalid" in (
        result["skeptic"]["candidate_reviews"]["tampered"]["reasons"]
    )
