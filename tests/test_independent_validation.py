import pytest

from bitcoin_ai.promotion import evaluate_independent_strategy_validation


def passing_candidate():
    return {
        "paired_edge_uncertainty": {
            "observations": 240,
            "observed_excess_return_pct": 8.0,
            "excess_return_p05_pct": 1.0,
            "probability_positive_pct": 97.0,
            "bootstrap_null_p_value": 0.01,
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
    strong["paired_edge_uncertainty"]["probability_positive_pct"] = 99.0
    nearby["paired_edge_uncertainty"]["probability_positive_pct"] = 99.0
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


def test_holm_correction_rejects_candidates_that_fail_step_down_threshold():
    first = passing_candidate()
    second = passing_candidate()
    first["paired_edge_uncertainty"]["bootstrap_null_p_value"] = 0.03
    second["paired_edge_uncertainty"]["bootstrap_null_p_value"] = 0.04
    result = evaluate_independent_strategy_validation(
        {"candidate-a": first, "candidate-b": second},
        {"usable": True, "status": "pass"},
    )
    guard = result["evidence_reviewer"]["multiplicity_guard"]
    assert guard["candidate_count"] == 2
    assert guard["formal_multiple_testing_correction"] is True
    assert guard["holm_steps"][0]["threshold"] == pytest.approx(0.025)
    assert guard["holm_rejected_candidates"] == []
    assert result["verdict"] == "reject"


def test_holm_correction_accepts_step_down_family_when_all_p_values_pass():
    first = passing_candidate()
    second = passing_candidate()
    first["paired_edge_uncertainty"]["bootstrap_null_p_value"] = 0.01
    second["paired_edge_uncertainty"]["bootstrap_null_p_value"] = 0.04
    result = evaluate_independent_strategy_validation(
        {"candidate-a": first, "candidate-b": second},
        {"usable": True, "status": "pass"},
    )
    guard = result["evidence_reviewer"]["multiplicity_guard"]
    assert guard["holm_rejected_candidates"] == ["candidate-a", "candidate-b"]
    assert result["verdict"] == "eligible_for_paper_review"


def test_holm_correction_fails_closed_when_candidate_p_value_is_missing():
    candidate = passing_candidate()
    del candidate["paired_edge_uncertainty"]["bootstrap_null_p_value"]
    result = evaluate_independent_strategy_validation(
        {"candidate": candidate},
        {"usable": True, "status": "pass"},
    )
    guard = result["evidence_reviewer"]["multiplicity_guard"]
    assert guard["missing_or_invalid_p_values"] == ["candidate"]
    assert result["verdict"] == "reject"
    assert result["skeptic"]["candidate_reviews"]["candidate"]["eligible_for_review"] is False


def test_independent_validation_rejects_invalid_candidate_names():
    with pytest.raises(ValueError, match="candidate names must be non-empty strings"):
        evaluate_independent_strategy_validation(
            {1: passing_candidate()}, {"usable": True, "status": "pass"}
        )
