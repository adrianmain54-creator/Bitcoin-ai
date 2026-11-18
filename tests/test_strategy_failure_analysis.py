import pytest

from bitcoin_ai.strategy_failure_analysis import (
    StrategyFailureAnalysisError,
    analyze_strategy_failures,
)


def test_reports_drawdown_episodes_and_recovery():
    report = analyze_strategy_failures(
        [0.10, -0.20, -0.10, 0.50, -0.05],
        stress_returns=[0.09, -0.22, -0.12, 0.48, -0.07],
        regimes=["uptrend", "downtrend", "downtrend", "uptrend", "range"],
        timestamps=[f"2026-01-0{i + 1}T00:00:00+00:00" for i in range(5)],
        min_regime_observations=2,
    )
    assert report["status"] == "diagnostic_only"
    assert report["drawdown_episode_count"] == 2
    assert report["drawdown_episodes"][0]["trough"]["index"] == 2
    assert report["drawdown_episodes"][0]["recovered"] is True
    assert report["drawdown_episodes"][1]["recovered"] is False
    assert report["worst_bars"][0]["regime"] == "downtrend"
    assert report["regime_loss_concentration"]["downtrend"]["observations"] == 2


def test_underpowered_regime_is_explicitly_unknown():
    report = analyze_strategy_failures(
        [0.01, -0.02, 0.01],
        regimes=["uptrend", "range", "range"],
        min_regime_observations=3,
    )
    assert report["regime_loss_concentration"]["range"]["sample_status"] == "underpowered"


def test_loss_concentration_is_zero_without_negative_bars():
    report = analyze_strategy_failures([0.01, 0.02, 0.03])
    assert report["worst_bar_loss_concentration_pct"] == 0.0
    assert report["worst_bars"] == []


def test_rejects_misaligned_stress_regime_and_timestamp_arrays():
    with pytest.raises(StrategyFailureAnalysisError, match="stress_returns"):
        analyze_strategy_failures([0.01, -0.01], stress_returns=[0.01])
    with pytest.raises(StrategyFailureAnalysisError, match="regimes"):
        analyze_strategy_failures([0.01, -0.01], regimes=["uptrend"])
    with pytest.raises(StrategyFailureAnalysisError, match="timestamps"):
        analyze_strategy_failures([0.01, -0.01], timestamps=["t1"])


@pytest.mark.parametrize("bad", [True, float("nan"), float("inf"), -1.0])
def test_rejects_invalid_returns(bad):
    with pytest.raises(StrategyFailureAnalysisError):
        analyze_strategy_failures([0.01, bad])


def test_rejects_invalid_top_n_and_empty_returns():
    with pytest.raises(StrategyFailureAnalysisError):
        analyze_strategy_failures([])
    with pytest.raises(StrategyFailureAnalysisError):
        analyze_strategy_failures([0.01], top_n=0)
