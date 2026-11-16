from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.backtesting import BacktestError, Bar
from bitcoin_ai.research_lab import run_strategy_lab, _selection_score


def bars(count=260):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    prices = []
    price = 100.0
    for i in range(count):
        # Alternating trend and pullback regimes, deterministic for reproducibility.
        drift = 0.0015 if (i // 35) % 2 == 0 else -0.0008
        price *= 1 + drift + ((i % 7) - 3) * 0.0004
        prices.append(Bar(start + timedelta(days=i), price))
    return prices


def test_strategy_lab_runs_multi_family_oos_and_bootstrap():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[
            {"family": "sma", "lookback": 12},
            {"family": "momentum", "lookback": 8},
            {"family": "breakout", "lookback": 15},
        ],
        bootstrap_trials=100, seed=11,
    )
    assert set(result["families"]) == {"sma", "momentum", "breakout"}
    assert result["fold_count"] > 1
    assert result["out_of_sample_returns"] == result["fold_count"] * 30
    assert result["bootstrap"]["trials"] == 100
    assert result["bootstrap"]["final_equity_p05"] <= result["bootstrap"]["final_equity_p95"]
    assert sum(item["observations"] for item in result["out_of_sample_regime_metrics"].values()) == result["out_of_sample_returns"]
    assert sum(result["training_selection_counts"].values()) == result["fold_count"]
    assert result["out_of_sample_metrics_at_2x_cost"]["total_return_pct"] <= result["out_of_sample_metrics"]["total_return_pct"]
    for regime in result["out_of_sample_regime_metrics"].values():
        assert "strategy" in regime and "buy_and_hold" in regime
    for fold in result["folds"]:
        assert fold["train_end"] < fold["test_start"]
        assert fold["selected_family"] in result["families"]


def test_strategy_lab_supports_short_sma_lookback_without_invalid_window():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "sma", "lookback": 2}], bootstrap_trials=100,
    )
    assert result["fold_count"] > 0


def test_strategy_lab_rejects_naive_timestamps():
    naive = [Bar(datetime(2024, 1, 1) + timedelta(days=i), 100 + i) for i in range(150)]
    with pytest.raises(BacktestError, match="timezone-aware"):
        run_strategy_lab(naive, train_bars=100, test_bars=20, bootstrap_trials=100)


def test_strategy_lab_is_deterministic_for_fixed_seed():
    kwargs = dict(train_bars=100, test_bars=30, bootstrap_trials=100, seed=42)
    a = run_strategy_lab(bars(), **kwargs)
    b = run_strategy_lab(bars(), **kwargs)
    assert a["bootstrap"] == b["bootstrap"]
    assert a["folds"] == b["folds"]


@pytest.mark.parametrize("kwargs", [
    {"train_bars": 2, "test_bars": 20},
    {"train_bars": 100, "test_bars": 20, "step_bars": 10},
    {"train_bars": 100, "test_bars": 20, "bootstrap_trials": 10},
    {"train_bars": 100, "test_bars": 20, "candidates": [{"family": "neural", "lookback": 10}]},
    {"train_bars": 100, "test_bars": 20, "candidates": [{"family": "sma", "lookback": 100}]},
])
def test_strategy_lab_rejects_invalid_configuration(kwargs):
    with pytest.raises(BacktestError):
        run_strategy_lab(bars(), **kwargs)



def test_cash_is_a_valid_abstention_candidate():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    assert result["families"] == ["cash"]
    assert result["out_of_sample_metrics"]["total_return_pct"] == 0.0
    assert result["out_of_sample_metrics"]["max_drawdown_pct"] == 0.0
    assert all(fold["selected_family"] == "cash" for fold in result["folds"])



def test_selection_score_rewards_consistency_and_penalizes_bad_segments():
    metrics = {"sortino_ratio": 1.0, "max_drawdown_pct": -5.0}
    steady = [0.01] * 40
    volatile = [0.05] * 10 + [0.01] * 10 + [-0.08] * 10 + [0.01] * 10
    steady_score, steady_share, steady_worst, _, _ = _selection_score(steady, metrics)
    volatile_score, volatile_share, volatile_worst, _, _ = _selection_score(volatile, metrics)
    assert steady_share == 1.0
    assert steady_worst > 0
    assert volatile_share < steady_share
    assert volatile_worst < steady_worst
    assert steady_score > volatile_score


def test_strategy_lab_reports_training_consistency_diagnostics():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "sma", "lookback": 12}, {"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    for fold in result["folds"]:
        assert 0.0 <= fold["training_positive_segment_share"] <= 1.0
        assert isinstance(fold["training_worst_segment_return_pct"], float)
    assert "positive-segment share" in result["selection_policy"]



def test_regime_selection_penalizes_weak_training_regime():
    metrics = {"sortino_ratio": 1.0, "max_drawdown_pct": -5.0}
    returns = [0.01] * 12 + [-0.03] * 12
    regimes = ["uptrend"] * 12 + ["downtrend"] * 12
    balanced = ["uptrend"] * 12 + ["downtrend"] * 12
    _, _, _, weak_regime, coverage = _selection_score(returns, metrics, regimes)
    assert weak_regime < 0
    assert coverage == 2


def test_strategy_lab_reports_causal_training_regime_diagnostics():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "sma", "lookback": 12}, {"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    for fold in result["folds"]:
        assert isinstance(fold["training_worst_regime_return_pct"], float)
        assert 0 <= fold["training_regimes_scored"] <= 4
    assert "trailing observations" in result["selection_policy"]
