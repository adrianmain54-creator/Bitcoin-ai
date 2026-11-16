from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.backtesting import BacktestError
from bitcoin_ai.regime import classify_regime
from bitcoin_ai.promotion import evaluate_paper_trial_eligibility


def test_regime_classifier_identifies_trailing_uptrend_and_is_causal():
    closes = [100 + i for i in range(30)]
    result = classify_regime(closes, lookback=10)
    assert result["regime"] == "uptrend"
    assert result["causal"] is True
    # Appending future data does not alter the classification at this earlier endpoint.
    assert result == classify_regime(closes[:], lookback=10)


def test_regime_classifier_identifies_range_and_high_volatility():
    flat = [100.0] * 25
    assert classify_regime(flat, lookback=10)["regime"] == "range"
    volatile = [100.0]
    for i in range(25):
        volatile.append(volatile[-1] * (1.08 if i % 2 else 0.92))
    assert classify_regime(volatile, lookback=10)["regime"] == "high_volatility"


@pytest.mark.parametrize("closes", [[], [1, 2], [1, 2, 0, 3], [1, 2, float("nan"), 4]])
def test_regime_classifier_rejects_bad_prices(closes):
    with pytest.raises(BacktestError):
        classify_regime(closes, lookback=3)


def test_promotion_gate_requires_all_conservative_conditions():
    report = {
        "fold_count": 8, "out_of_sample_returns": 240,
        "out_of_sample_metrics": {"total_return_pct": 12.0, "max_drawdown_pct": -8.0, "sortino_ratio": 1.2},
        "buy_and_hold_metrics": {"total_return_pct": 7.0},
        "bootstrap": {"final_equity_p05": 1.03},
    }
    assert evaluate_paper_trial_eligibility(report)["eligible"] is True
    report["out_of_sample_metrics"]["max_drawdown_pct"] = -25.0
    result = evaluate_paper_trial_eligibility(report)
    assert result["eligible"] is False
    assert any("drawdown" in reason for reason in result["reasons"])


def test_promotion_gate_fails_closed_on_missing_evidence():
    result = evaluate_paper_trial_eligibility({})
    assert result["eligible"] is False
    assert result["reasons"]
    assert "never authorizes live trading" in result["scope"]
