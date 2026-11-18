"""Robust, descriptive anomaly flags for forward paper-strategy performance."""
from __future__ import annotations

import math
from statistics import median


def evaluate_performance_anomalies(observations, *, baseline_window=30,
                                  recent_window=5, min_baseline=20,
                                  mad_threshold=3.0):
    """Compare recent paired strategy-vs-market returns with prior observations.

    This is a monitoring heuristic, not a forecast, statistical significance test,
    or strategy-selection mechanism. It never changes positions or risk state.
    """
    for value, name in ((baseline_window, "baseline_window"),
                        (recent_window, "recent_window"),
                        (min_baseline, "min_baseline")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(f"{name} must be a positive integer")
    if baseline_window < min_baseline:
        raise ValueError("baseline_window must be at least min_baseline")
    if (isinstance(mad_threshold, bool) or not isinstance(mad_threshold, (int, float))
            or not math.isfinite(mad_threshold) or mad_threshold <= 0):
        raise ValueError("mad_threshold must be finite and positive")
    if not isinstance(observations, list):
        raise ValueError("observations must be a list")

    previous_time = None
    previous_equity = previous_price = previous_baseline = None
    paired_edges = []
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            raise ValueError(f"observation {index} must be an object")
        stamp = item.get("observed_at")
        from datetime import datetime
        try:
            current_time = datetime.fromisoformat(stamp)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"observation {index} has an invalid timestamp") from exc
        if current_time.tzinfo is None or current_time.utcoffset() is None:
            raise ValueError(f"observation {index} timestamp must be timezone-aware")
        if previous_time is not None and current_time <= previous_time:
            raise ValueError("observation timestamps must be strictly increasing")
        values = []
        for field in ("equity", "price"):
            value = item.get(field)
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ValueError(f"observation {index} {field} must be finite and positive")
            values.append(float(value))
        equity, price = values
        if previous_equity is not None:
            strategy_return = equity / previous_equity - 1.0
            market_return = price / previous_price - 1.0
            paired_edges.append(strategy_return - market_return)
        previous_time = current_time
        previous_equity, previous_price = equity, price

    required = baseline_window + recent_window
    if len(paired_edges) < required:
        return {
            "status": "insufficient_observations",
            "observations": len(paired_edges),
            "required_observations": required,
            "anomalies": [],
            "interpretation": "Not enough consecutive paired returns for a baseline and recent window.",
        }

    baseline = paired_edges[-required:-recent_window]
    recent = paired_edges[-recent_window:]
    center = median(baseline)
    mad = median([abs(value - center) for value in baseline])
    robust_scale = 1.4826 * mad
    recent_center = median(recent)
    threshold = center - mad_threshold * robust_scale
    flagged = recent_center < threshold if robust_scale > 1e-12 else recent_center < center - 1e-9
    anomalies = []
    if flagged:
        anomalies.append({
            "type": "relative_performance_degradation",
            "baseline_median_excess_return_pct_points": round(center * 100, 6),
            "recent_median_excess_return_pct_points": round(recent_center * 100, 6),
            "lower_control_threshold_pct_points": round(threshold * 100, 6),
            "robust_scale_pct_points": round(robust_scale * 100, 6),
            "severity": "review",
            "message": "Recent paired performance is materially weaker than its own prior baseline.",
        })
    return {
        "status": "anomaly_detected" if anomalies else "no_anomaly_detected",
        "observations": len(paired_edges),
        "baseline_observations": len(baseline),
        "recent_observations": len(recent),
        "baseline_median_excess_return_pct_points": round(center * 100, 6),
        "recent_median_excess_return_pct_points": round(recent_center * 100, 6),
        "mad_threshold": float(mad_threshold),
        "anomalies": anomalies,
        "interpretation": (
            "Robust rolling monitoring heuristic only; not a prediction, p-value, "
            "proof of edge loss, or automatic trading/risk decision."
        ),
    }
