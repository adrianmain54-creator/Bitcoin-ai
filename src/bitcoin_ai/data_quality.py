"""Fail-closed quality diagnostics for historical Bitcoin price bars.

The audit is deliberately separate from strategy scoring: it never repairs,
sorts, drops, or silently imputes observations.
"""
from __future__ import annotations

import math
from datetime import datetime


def audit_price_bars(
    bars,
    *,
    expected_interval_seconds: int | None = None,
    max_abs_return_pct: float = 25.0,
    flatline_run: int = 8,
) -> dict:
    """Audit ordered Bar-like observations and return explicit findings.

    Structural defects make the dataset unusable. Large moves and long runs of
    identical closes are warnings requiring source review, not auto-corrections.
    """
    if not isinstance(bars, (list, tuple)):
        raise ValueError("bars must be a list or tuple")
    if (expected_interval_seconds is not None
            and (isinstance(expected_interval_seconds, bool)
                 or not isinstance(expected_interval_seconds, int)
                 or expected_interval_seconds <= 0)):
        raise ValueError("expected_interval_seconds must be a positive integer or None")
    if (isinstance(max_abs_return_pct, bool)
            or not isinstance(max_abs_return_pct, (int, float))
            or not math.isfinite(max_abs_return_pct) or max_abs_return_pct <= 0):
        raise ValueError("max_abs_return_pct must be finite and positive")
    if isinstance(flatline_run, bool) or not isinstance(flatline_run, int) or flatline_run < 2:
        raise ValueError("flatline_run must be an integer >= 2")

    errors, warnings = [], []
    if len(bars) < 3:
        errors.append("at least 3 observations are required")

    previous_time = None
    previous_close = None
    flatline = 1
    max_gap = 0.0
    gaps = []
    outliers = []
    longest_flatline = 1

    for index, bar in enumerate(bars):
        timestamp = getattr(bar, "timestamp", None)
        close = getattr(bar, "close", None)
        if (not isinstance(timestamp, datetime) or timestamp.tzinfo is None
                or timestamp.utcoffset() is None):
            errors.append(f"bar {index} timestamp must be timezone-aware")
            continue
        if (isinstance(close, bool) or not isinstance(close, (int, float))
                or not math.isfinite(close) or close <= 0):
            errors.append(f"bar {index} close must be finite and positive")
            continue

        if previous_time is not None:
            delta = (timestamp - previous_time).total_seconds()
            if delta <= 0:
                errors.append(f"bar {index} timestamp is duplicate or out of order")
            else:
                max_gap = max(max_gap, delta)
                if expected_interval_seconds is not None and delta != expected_interval_seconds:
                    gaps.append({
                        "after_index": index - 1,
                        "before_index": index,
                        "actual_seconds": delta,
                        "expected_seconds": expected_interval_seconds,
                    })
            change_pct = (float(close) / float(previous_close) - 1.0) * 100.0
            if abs(change_pct) > max_abs_return_pct:
                outliers.append({"index": index, "return_pct": round(change_pct, 4)})
            if close == previous_close:
                flatline += 1
            else:
                flatline = 1
            longest_flatline = max(longest_flatline, flatline)

        previous_time, previous_close = timestamp, close

    if gaps:
        errors.append(f"{len(gaps)} interval mismatch(es); expected cadence is not continuous")
    if outliers:
        warnings.append(
            f"{len(outliers)} one-bar move(s) exceed the {max_abs_return_pct:g}% review threshold"
        )
    if longest_flatline >= flatline_run:
        warnings.append(
            f"identical closes persisted for {longest_flatline} consecutive observations"
        )

    return {
        "usable": not errors,
        "status": "fail" if errors else ("review" if warnings else "pass"),
        "observations": len(bars),
        "errors": errors,
        "warnings": warnings,
        "interval_audit": {
            "expected_seconds": expected_interval_seconds,
            "mismatch_count": len(gaps),
            "mismatches": gaps,
            "maximum_observed_gap_seconds": max_gap,
        },
        "anomaly_audit": {
            "return_threshold_pct": max_abs_return_pct,
            "outlier_count": len(outliers),
            "outliers": outliers,
            "longest_identical_close_run": longest_flatline,
            "flatline_run_threshold": flatline_run,
        },
        "policy": (
            "No sorting, deletion, interpolation, or repair is performed. "
            "Structural failures block research; anomaly warnings require source review."
        ),
    }
