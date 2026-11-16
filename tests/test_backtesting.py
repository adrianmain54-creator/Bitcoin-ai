import json
from datetime import datetime, timezone

import pytest

from bitcoin_ai.backtesting import BacktestError, Bar, load_close_csv, run_sma_backtest


def sample_bars():
    prices = [100, 99, 98, 99, 101, 104, 108, 112, 115, 117, 116, 114, 110, 108]
    return [Bar(datetime(2024, 1, i + 1, tzinfo=timezone.utc), p) for i, p in enumerate(prices)]


def test_sma_signal_is_applied_after_signal_bar_and_costs_reduce_return():
    bars = sample_bars()
    free = run_sma_backtest(bars, fast_window=2, slow_window=4, fee_bps=0, slippage_bps=0)
    costly = run_sma_backtest(bars, fast_window=2, slow_window=4, fee_bps=20, slippage_bps=10)
    assert "close of bar t" in free["signal_timing"]
    assert costly["strategy_metrics"]["total_return_pct"] < free["strategy_metrics"]["total_return_pct"]
    assert "buy_and_hold_metrics" in free


def test_backtest_rejects_invalid_parameters_and_short_history():
    with pytest.raises(BacktestError):
        run_sma_backtest(sample_bars(), fast_window=4, slow_window=4)
    with pytest.raises(BacktestError):
        run_sma_backtest(sample_bars()[:3], fast_window=1, slow_window=3)


def test_csv_loader_validates_and_sorts_rows(tmp_path):
    path = tmp_path / "prices.csv"
    path.write_text("timestamp,close\n2024-01-02,101\n2024-01-01,100\n2024-01-03,102\n", encoding="utf-8")
    bars = load_close_csv(path)
    assert [bar.close for bar in bars] == [100, 101, 102]


def test_csv_loader_rejects_duplicate_timestamps_and_nonpositive_close(tmp_path):
    duplicate = tmp_path / "duplicate.csv"
    duplicate.write_text("timestamp,close\n2024-01-01,100\n2024-01-01,101\n2024-01-02,102\n", encoding="utf-8")
    with pytest.raises(BacktestError, match="Duplicate"):
        load_close_csv(duplicate)
    invalid = tmp_path / "invalid.csv"
    invalid.write_text("timestamp,close\n2024-01-01,100\n2024-01-02,0\n2024-01-03,102\n", encoding="utf-8")
    with pytest.raises(BacktestError, match="positive"):
        load_close_csv(invalid)


@pytest.mark.parametrize("kwargs", [
    {"fast_window": True},
    {"fast_window": 2.5},
    {"slow_window": False},
    {"fee_bps": float("nan")},
    {"slippage_bps": float("inf")},
    {"fee_bps": True},
    {"periods_per_year": float("nan")},
    {"periods_per_year": 0},
])
def test_backtest_rejects_nonfinite_or_wrongly_typed_parameters(kwargs):
    with pytest.raises(BacktestError):
        run_sma_backtest(sample_bars(), fast_window=2, slow_window=4, **kwargs)


@pytest.mark.parametrize("bar", [
    Bar(datetime(2024, 1, 1), 100),
    Bar(datetime(2024, 1, 1, tzinfo=timezone.utc), float("nan")),
    Bar(datetime(2024, 1, 1, tzinfo=timezone.utc), float("inf")),
    Bar(datetime(2024, 1, 1, tzinfo=timezone.utc), True),
])
def test_backtest_rejects_invalid_bar_observations(bar):
    bars = sample_bars()
    bars[0] = bar
    with pytest.raises(BacktestError):
        run_sma_backtest(bars, fast_window=2, slow_window=4)


def test_backtest_rejects_non_bar_input():
    with pytest.raises(BacktestError, match="Bar records"):
        run_sma_backtest([1, 2, 3, 4, 5], fast_window=2, slow_window=4)
