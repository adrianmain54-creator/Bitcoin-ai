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


def test_regime_concentrated_edge_requires_human_review():
    candidate = passing_candidate()
    candidate["regime_attribution"] = {
        "uptrend": {
            "observations": 45,
            "excess_return_vs_buy_and_hold_pct_points": 4.0,
        },
        "range": {
            "observations": 50,
            "excess_return_vs_buy_and_hold_pct_points": -2.0,
        },
        "high_volatility": {
            "observations": 12,
            "excess_return_vs_buy_and_hold_pct_points": 8.0,
        },
    }
    result = evaluate_independent_strategy_validation(
        {"candidate": candidate}, {"usable": True, "status": "pass"},
    )
    assert result["verdict"] == "needs_review"
    diagnostic = result["evidence_reviewer"]["regime_diagnostics"]["candidate"]
    assert diagnostic["adequately_sampled_regimes"] == ["uptrend", "range"]
    assert diagnostic["positive_excess_regimes"] == ["uptrend"]
    assert result["evidence_reviewer"]["regime_concentration_requires_review"] == ["candidate"]


def test_regime_diagnostic_does_not_overinterpret_small_samples():
    candidate = passing_candidate()
    candidate["regime_attribution"] = {
        "uptrend": {
            "observations": 20,
            "excess_return_vs_buy_and_hold_pct_points": 5.0,
        },
        "range": {
            "observations": 18,
            "excess_return_vs_buy_and_hold_pct_points": -2.0,
        },
    }
    result = evaluate_independent_strategy_validation(
        {"candidate": candidate}, {"usable": True, "status": "pass"},
    )
    assert result["verdict"] == "eligible_for_paper_review"
    assert result["evidence_reviewer"]["regime_diagnostics"]["candidate"]["adequately_sampled_regimes"] == []


def test_nearby_parameter_variant_erasing_edge_requires_review():
    strong = passing_candidate()
    strong.update({
        "family": "momentum",
        "lookback": 10,
        "observations": 240,
        "excess_return_vs_buy_and_hold_pct_points": 2.5,
    })
    nearby = passing_candidate()
    nearby.update({
        "family": "momentum",
        "lookback": 12,
        "observations": 240,
        "excess_return_vs_buy_and_hold_pct_points": -0.4,
    })
    result = evaluate_independent_strategy_validation(
        {"momentum:10": strong, "momentum:12": nearby},
        {"usable": True, "status": "pass"},
    )
    assert result["verdict"] == "needs_review"
    diagnostic = result["evidence_reviewer"]["parameter_sensitivity_diagnostics"]["momentum:10"]
    assert diagnostic["edge_collapses_in_nearby_variant"] is True
    assert diagnostic["nearby_candidates"][0]["candidate"] == "momentum:12"
    assert result["evidence_reviewer"]["parameter_sensitivity_requires_review"] == ["momentum:10"]


def test_parameter_sensitivity_ignores_distant_or_different_family_candidates():
    candidate = passing_candidate()
    candidate.update({
        "family": "momentum",
        "lookback": 10,
        "observations": 240,
        "excess_return_vs_buy_and_hold_pct_points": 2.0,
    })
    distant = passing_candidate()
    distant.update({
        "family": "momentum",
        "lookback": 30,
        "observations": 240,
        "excess_return_vs_buy_and_hold_pct_points": -5.0,
    })
    other_family = passing_candidate()
    other_family.update({
        "family": "sma",
        "lookback": 11,
        "observations": 240,
        "excess_return_vs_buy_and_hold_pct_points": -5.0,
    })
    result = evaluate_independent_strategy_validation(
        {"momentum:10": candidate, "momentum:30": distant, "sma:11": other_family},
        {"usable": True, "status": "pass"},
    )
    diagnostic = result["evidence_reviewer"]["parameter_sensitivity_diagnostics"]["momentum:10"]
    assert diagnostic["available"] is False
    assert diagnostic["nearby_candidates"] == []


def test_candidate_multiplicity_tightens_positive_bootstrap_share_hurdle():
    strong = passing_candidate()
    strong["paired_edge_uncertainty"]["probability_positive_pct"] = 97.0
    result = evaluate_independent_strategy_validation(
        {"candidate-a": strong, "candidate-b": passing_candidate()},
        {"usable": True, "status": "pass"},
    )
    guard = result["evidence_reviewer"]["multiplicity_guard"]
    assert guard["candidate_count"] == 2
    assert guard["effective_minimum_bootstrap_positive_edge_pct"] == pytest.approx(97.5)
    assert guard["formal_multiple_testing_correction"] is False
    assert result["skeptic"]["candidate_reviews"]["candidate-a"]["eligible_for_review"] is False
    assert any(
        "bootstrap positive-edge share is below 97.5%" in reason
        for reason in result["skeptic"]["candidate_reviews"]["candidate-a"]["reasons"]
    )


def test_candidate_multiplicity_guard_does_not_call_bootstrap_share_a_p_value():
    result = evaluate_independent_strategy_validation(
        {"one": passing_candidate()},
        {"usable": True, "status": "pass"},
    )
    guard = result["evidence_reviewer"]["multiplicity_guard"]
    assert guard["effective_minimum_bootstrap_positive_edge_pct"] == 95.0
    assert "not a p-value" in guard["warning"]


def test_independent_validation_rejects_invalid_candidate_names():
    with pytest.raises(ValueError, match="candidate names must be non-empty strings"):
        evaluate_independent_strategy_validation(
            {1: passing_candidate()}, {"usable": True, "status": "pass"}
        )
