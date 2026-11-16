"""Deterministic, explainable BTC trend signal baseline.

This is a research baseline, not a prediction model or a claim of profitability.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
from statistics import fmean


class StrategyError(ValueError):
    """Invalid strategy inputs."""


@dataclass(frozen=True)
class TradingSignal:
    action: str
    target_allocation: float
    reason: str
    fast_sma: float
    slow_sma: float
    close: float


def generate_signal(
    closes: list[float] | tuple[float, ...],
    *,
    fast_window: int = 12,
    slow_window: int = 48,
    max_allocation: float = 0.20,
    current_allocation: float = 0.0,
) -> TradingSignal:
    """Return a long/cash trend signal using only the supplied completed closes.

    Buy exposure is allowed only when fast SMA > slow SMA and the latest close
    is above the slow SMA. Otherwise the strategy targets cash. This intentionally
    simple baseline is easy to audit and must be evaluated out of sample.
    """
    if isinstance(fast_window, bool) or isinstance(slow_window, bool):
        raise StrategyError("SMA windows must be integers")
    if not isinstance(fast_window, int) or not isinstance(slow_window, int):
        raise StrategyError("SMA windows must be integers")
    if fast_window < 2 or slow_window <= fast_window:
        raise StrategyError("Require 2 <= fast_window < slow_window")
    if isinstance(max_allocation, bool) or not isinstance(max_allocation, (int, float)):
        raise StrategyError("max_allocation must be a finite number")
    if not math.isfinite(max_allocation) or not 0 <= max_allocation <= 1:
        raise StrategyError("max_allocation must be between 0 and 1")
    if (isinstance(current_allocation, bool) or not isinstance(current_allocation, (int, float))
            or not math.isfinite(current_allocation) or not 0 <= current_allocation <= 1):
        raise StrategyError("current_allocation must be between 0 and 1")
    if len(closes) < slow_window:
        raise StrategyError(f"At least {slow_window} closes are required")

    values = list(closes)
    if any(isinstance(value, bool) or not isinstance(value, (int, float))
           or not math.isfinite(value) or value <= 0 for value in values):
        raise StrategyError("closes must contain only finite positive prices")

    fast = fmean(values[-fast_window:])
    slow = fmean(values[-slow_window:])
    latest = values[-1]
    if fast > slow and latest > slow:
        target = float(max_allocation)
        action = "buy" if current_allocation < target - 1e-9 else "hold"
        return TradingSignal(
            action=action, target_allocation=target,
            reason="Bullish trend confirmed; increase exposure to the configured cap." if action == "buy" else "Bullish trend remains valid; target exposure is already reached.",
            fast_sma=fast, slow_sma=slow, close=latest,
        )
    return TradingSignal(
        action="sell" if current_allocation > 1e-9 else "hold",
        target_allocation=0.0,
        reason="Trend confirmation is absent; reduce existing exposure to cash." if current_allocation > 1e-9 else "Trend confirmation is absent; remain in cash.",
        fast_sma=fast, slow_sma=slow, close=latest,
    )
