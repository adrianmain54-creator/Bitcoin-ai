from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.backtesting import BacktestError, Bar
from bitcoin_ai.walk_forward import walk_forward_sma_backtest


def make_bars(count=160):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    values = []
    for i in range(count):
        segment = (i // 25) % 2
        drift = 0.8 if segment == 0 else -0.55
        values.append(100 + i * 0.08 + (i % 25) * drift)
    return [Bar(start + timedelta(days=i), float(value)) for i, value in enumerate(values)]


def test_walk_forward_uses_chronological_non_overlapping_test_folds():
    result = walk_forward_sma_backtest(
        make_bars(), candidates=[(3, 8), (5, 15), (8, 20)],
        train_bars=60, test_bars=20,
    )
    assert result["fold_count"] > 1
    assert result["out_of_sample_returns"] == result["fold_count"] * 20
    for fold in result["folds"]:
        assert fold["train_end"] < fold["test_start"]
        assert fold["selected_fast_window"] < fold["selected_slow_window"]
        assert fold["out_of_sample_returns"] == 20
    assert "buy_and_hold_metrics" in result


def test_walk_forward_rejects_invalid_candidates_and_overlapping_folds():
    bars = make_bars()
    with pytest.raises(BacktestError, match="slow window"):
        walk_forward_sma_backtest(
            bars, candidates=[(5, 60)], train_bars=60, test_bars=10,
        )
    with pytest.raises(BacktestError, match="no overlapping"):
        walk_forward_sma_backtest(
            bars, candidates=[(3, 8)], train_bars=60,
            test_bars=20, step_bars=10,
        )


def test_walk_forward_requires_enough_data_for_one_fold():
    with pytest.raises(BacktestError, match="Not enough bars"):
        walk_forward_sma_backtest(
            make_bars(50), candidates=[(3, 8)],
            train_bars=30, test_bars=20,
        )
