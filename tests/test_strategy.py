import pytest

from bitcoin_ai.strategy import StrategyError, generate_signal


def test_uptrend_generates_capped_long_target():
    closes = list(range(100, 161))
    signal = generate_signal(closes, fast_window=5, slow_window=20, max_allocation=0.2)
    assert signal.action == "buy"
    assert signal.target_allocation == 0.2
    assert signal.fast_sma > signal.slow_sma


def test_downtrend_targets_cash():
    closes = list(range(160, 99, -1))
    signal = generate_signal(closes, fast_window=5, slow_window=20)
    assert signal.action == "hold"
    assert signal.target_allocation == 0


def test_insufficient_or_invalid_data_is_rejected():
    with pytest.raises(StrategyError):
        generate_signal([100, 101], fast_window=2, slow_window=3)
    with pytest.raises(StrategyError):
        generate_signal([100, float("nan"), 102], fast_window=2, slow_window=3)
    with pytest.raises(StrategyError):
        generate_signal([100, 101, 102], fast_window=1, slow_window=3)


def test_signal_sells_only_when_exposure_exists():
    closes = list(range(160, 99, -1))
    signal = generate_signal(
        closes, fast_window=5, slow_window=20, current_allocation=0.15,
    )
    assert signal.action == "sell"
    assert signal.target_allocation == 0


def test_signal_holds_when_target_allocation_is_already_reached():
    closes = list(range(100, 161))
    signal = generate_signal(
        closes, fast_window=5, slow_window=20,
        max_allocation=0.2, current_allocation=0.2,
    )
    assert signal.action == "hold"
    assert signal.target_allocation == 0.2


def test_signal_rejects_invalid_current_allocation():
    with pytest.raises(StrategyError, match="current_allocation"):
        generate_signal(
            list(range(100, 161)), fast_window=5, slow_window=20,
            current_allocation=1.1,
        )


def test_bullish_signal_reduces_exposure_above_configured_cap():
    closes = list(range(100, 161))
    signal = generate_signal(
        closes, fast_window=5, slow_window=20,
        max_allocation=0.2, current_allocation=0.4,
    )
    assert signal.action == "sell"
    assert signal.target_allocation == 0.2
