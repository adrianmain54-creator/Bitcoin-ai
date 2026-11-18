"""Conservative OHLCV anomaly diagnostics; not a spoofing detector."""
from __future__ import annotations

import math
import statistics
from typing import Iterable, Mapping


class MarketAnomalyError(ValueError):
    """OHLCV input is malformed or insufficient for a meaningful audit."""


def audit_ohlcv_anomalies(
    candles: Iterable[Mapping[str, object]],
    *,
    min_history: int = 20,
    volume_robust_z_threshold: float = 6.0,
    range_multiple_threshold: float = 6.0,
    absolute_return_threshold: float = 0.08,
) -> dict:
    """Flag abnormal volume, candle range, and close-to-close moves.

    Baselines use only preceding candles (never the candle being evaluated).
    The function is diagnostic: alerts are not proof of spoofing, manipulation,
    wash trading, or a reliable directional signal.
    """
    if isinstance(min_history, bool) or not isinstance(min_history, int) or min_history < 5:
        raise ValueError("min_history must be an integer >= 5")
    for name, value in (
        ("volume_robust_z_threshold", volume_robust_z_threshold),
        ("range_multiple_threshold", range_multiple_threshold),
        ("absolute_return_threshold", absolute_return_threshold),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
            raise ValueError(f"{name} must be a finite positive number")

    rows = list(candles)
    if len(rows) < min_history + 1:
        raise MarketAnomalyError(f"at least {min_history + 1} candles are required")
    parsed = []
    previous_timestamp = None
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise MarketAnomalyError(f"candle {index} must be a mapping")
        try:
            timestamp = row["timestamp"]
            values = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise MarketAnomalyError(f"candle {index} has missing or invalid fields") from exc
        if isinstance(timestamp, bool) or not isinstance(timestamp, (int, float)) or not math.isfinite(timestamp):
            raise MarketAnomalyError(f"candle {index} has invalid timestamp")
        if previous_timestamp is not None and timestamp <= previous_timestamp:
            raise MarketAnomalyError("candle timestamps must be strictly increasing")
        previous_timestamp = timestamp
        if any(not math.isfinite(value) for value in values.values()):
            raise MarketAnomalyError(f"candle {index} contains non-finite values")
        o, h, low, close, volume = (values[k] for k in ("open", "high", "low", "close", "volume"))
        if min(o, h, low, close) <= 0 or volume < 0 or h < max(o, close, low) or low > min(o, close):
            raise MarketAnomalyError(f"candle {index} violates OHLCV price/volume constraints")
        parsed.append({"timestamp": timestamp, **values})

    alerts = []
    volume_scores = []
    range_scores = []
    for i in range(min_history, len(parsed)):
        current = parsed[i]
        history = parsed[i - min_history:i]
        volumes = [row["volume"] for row in history]
        ranges = [(row["high"] - row["low"]) / row["close"] for row in history]
        median_volume = statistics.median(volumes)
        mad_volume = statistics.median(abs(value - median_volume) for value in volumes)
        current_volume = current["volume"]
        if mad_volume > 0:
            volume_score = 0.67448975 * (current_volume - median_volume) / mad_volume
        elif current_volume > median_volume:
            volume_score = math.inf
        else:
            volume_score = 0.0
        median_range = statistics.median(ranges)
        current_range = (current["high"] - current["low"]) / current["close"]
        range_multiple = current_range / median_range if median_range > 0 else (
            math.inf if current_range > 0 else 0.0
        )
        previous_close = parsed[i - 1]["close"]
        close_return = current["close"] / previous_close - 1.0
        volume_scores.append(volume_score)
        range_scores.append(range_multiple)
        reasons = []
        if volume_score > volume_robust_z_threshold:
            reasons.append("abnormal_volume")
        if range_multiple > range_multiple_threshold:
            reasons.append("abnormal_candle_range")
        if abs(close_return) > absolute_return_threshold:
            reasons.append("extreme_close_return")
        if reasons:
            alerts.append({
                "timestamp": current["timestamp"],
                "index": i,
                "reasons": reasons,
                "volume_robust_z": volume_score if math.isfinite(volume_score) else None,
                "volume_spike_with_zero_mad": not math.isfinite(volume_score),
                "range_multiple": range_multiple if math.isfinite(range_multiple) else None,
                "close_return": close_return,
            })

    return {
        "status": "alerts_found" if alerts else "no_anomalies_detected",
        "candles_analyzed": len(parsed),
        "candles_scored": len(parsed) - min_history,
        "baseline_window": min_history,
        "alerts": alerts,
        "limitations": [
            "OHLCV anomalies cannot establish spoofing, intent, wash trading, or manipulation.",
            "Volume is venue-reported and may be incomplete or unreliable.",
            "Thresholds are heuristics and require calibration by asset, venue, and interval.",
            "No alert does not mean the market is safe or manipulation-free.",
        ],
    }
