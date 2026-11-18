import pytest

from bitcoin_ai.regime_robustness import (
    RegimeRobustnessError,
    audit_regime_robustness,
)


def sample_candidates():
    return {
        "momentum:10": {
            "regime_attribution": {
                "uptrend": {
                    "observations": 30,
                    "strategy_return_at_2x_cost_pct": 4.0,
                    "excess_return_vs_buy_and_hold_pct_points": 1.5,
                },
                "downtrend": {
                    "observations": 25,
                    "strategy_return_at_2x_cost_pct": -3.0,
                    "excess_return_vs_buy_and_hold_pct_points": 2.0,
                },
                "range": {
                    "observations": 8,
                    "strategy_return_at_2x_cost_pct": 0.2,
                    "excess_return_vs_buy_and_hold_pct_points": 0.1,
                },
            }
        }
    }


def test_flags_negative_regime_after_doubled_costs():
    result = audit_regime_robustness(sample_candidates(), min_observations=10)
    candidate = result["candidates"]["momentum:10"]
    assert result["status"] == "review_required"
    assert candidate["status"] == "insufficient_evidence"
    assert candidate["negative_regimes_at_2x_costs"] == ["downtrend"]
    assert candidate["underpowered_regimes"] == ["range"]
    assert candidate["regimes"]["range"]["benchmark_outperformed"] is None


def test_underpowered_regime_is_not_treated_as_a_pass():
    data = {
        "cash:2": {
            "regime_attribution": {
                "uptrend": {
                    "observations": 4,
                    "strategy_return_at_2x_cost_pct": 0.0,
                    "excess_return_vs_buy_and_hold_pct_points": -2.0,
                }
            }
        }
    }
    result = audit_regime_robustness(data, min_observations=10)
    assert result["status"] == "review_required"
    assert result["candidates"]["cash:2"]["status"] == "insufficient_evidence"
    assert result["candidates"]["cash:2"]["regimes"]["uptrend"]["benchmark_outperformed"] is None


def test_clean_sufficient_regimes_are_only_descriptive_not_promoted():
    data = {
        "sma:12": {
            "regime_attribution": {
                "uptrend": {
                    "observations": 40,
                    "strategy_return_at_2x_cost_pct": 2.0,
                    "excess_return_vs_buy_and_hold_pct_points": 0.5,
                },
                "downtrend": {
                    "observations": 35,
                    "strategy_return_at_2x_cost_pct": 0.1,
                    "excess_return_vs_buy_and_hold_pct_points": 1.0,
                },
            }
        }
    }
    result = audit_regime_robustness(data, min_observations=10)
    assert result["status"] == "no_obvious_regime_loss_detected"
    assert result["promotion_effect"] == "none"
    assert result["candidates"]["sma:12"]["status"] == "no_obvious_regime_loss_detected"


@pytest.mark.parametrize("value", [True, -1, 1.5, float("nan")])
def test_rejects_invalid_observation_counts(value):
    data = {
        "bad": {
            "regime_attribution": {
                "range": {
                    "observations": value,
                    "strategy_return_at_2x_cost_pct": 0.0,
                    "excess_return_vs_buy_and_hold_pct_points": 0.0,
                }
            }
        }
    }
    with pytest.raises(RegimeRobustnessError):
        audit_regime_robustness(data)


def test_rejects_missing_or_non_finite_metrics():
    data = {"bad": {"regime_attribution": {"range": {
        "observations": 20,
        "strategy_return_at_2x_cost_pct": float("inf"),
        "excess_return_vs_buy_and_hold_pct_points": 0.0,
    }}}}
    with pytest.raises(RegimeRobustnessError):
        audit_regime_robustness(data)


def test_rejects_empty_candidate_family_and_invalid_threshold():
    with pytest.raises(RegimeRobustnessError):
        audit_regime_robustness({})
    with pytest.raises(RegimeRobustnessError):
        audit_regime_robustness(sample_candidates(), min_observations=True)
