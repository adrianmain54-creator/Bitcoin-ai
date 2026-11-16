"""Causal, trailing-window BTC market regime classification.

Uses only closes available at each timestamp. Labels are descriptive research
metadata, not forecasts or standalone trading signals.
"""
from __future__ import annotations

import math
from statistics import pstdev

from .backtesting import BacktestError


def classify_regime(closes, *, lookback=20, high_volatility_threshold=0.04):
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 3:
        raise BacktestError("lookback must be an integer >= 3")
    if not isinstance(closes, (list, tuple)) or len(closes) < lookback + 1:
        raise BacktestError("closes must contain at least lookback + 1 observations")
    if (isinstance(high_volatility_threshold, bool)
            or not isinstance(high_volatility_threshold, (int, float))
            or not math.isfinite(high_volatility_threshold)
            or high_volatility_threshold <= 0):
        raise BacktestError("high_volatility_threshold must be finite and positive")
    values = []
    for close in closes:
        if isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(close) or close <= 0:
            raise BacktestError("closes must contain finite positive prices")
        values.append(float(close))
    window = values[-(lookback + 1):]
    returns = [window[i] / window[i - 1] - 1.0 for i in range(1, len(window))]
    volatility = pstdev(returns)
    momentum = window[-1] / window[0] - 1.0
    trend_threshold = max(0.005, volatility * math.sqrt(lookback) * 0.5)
    if volatility >= high_volatility_threshold:
        label = "high_volatility"
    elif momentum >= trend_threshold:
        label = "uptrend"
    elif momentum <= -trend_threshold:
        label = "downtrend"
    else:
        label = "range"
    return {
        "regime": label,
        "lookback": lookback,
        "momentum_pct": round(momentum * 100, 4),
        "realized_volatility_pct_per_bar": round(volatility * 100, 4),
        "trend_threshold_pct": round(trend_threshold * 100, 4),
        "causal": True,
    }
