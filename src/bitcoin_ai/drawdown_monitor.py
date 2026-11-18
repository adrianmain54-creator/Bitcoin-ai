"""Read-only drawdown summaries from persisted paper-equity checkpoints."""
from __future__ import annotations

import math


def summarize_drawdown(observations):
    """Return current and maximum observed peak-to-trough drawdown percentages.

    This is a checkpoint-based description, not an intrabar maximum or a
    substitute for the execution-time risk gate.
    """
    if not isinstance(observations, list):
        raise ValueError("observations must be a list")
    if not observations:
        return {
            "status": "insufficient_observations",
            "observations": 0,
            "current_drawdown_pct": None,
            "max_observed_drawdown_pct": None,
            "peak_equity": None,
        }

    peak = 0.0
    max_drawdown = 0.0
    current_equity = None
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            raise ValueError(f"observation {index} must be an object")
        equity = item.get("equity")
        if (isinstance(equity, bool) or not isinstance(equity, (int, float))
                or not math.isfinite(equity) or equity <= 0):
            raise ValueError(f"observation {index} equity must be finite and positive")
        equity = float(equity)
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, 1.0 - equity / peak)
        current_equity = equity

    return {
        "status": "available",
        "observations": len(observations),
        "peak_equity": round(peak, 8),
        "current_equity": round(current_equity, 8),
        "current_drawdown_pct": round(max(0.0, 1.0 - current_equity / peak) * 100, 6),
        "max_observed_drawdown_pct": round(max_drawdown * 100, 6),
        "interpretation": (
            "Checkpoint-based drawdown only; intrabar losses may be larger. "
            "This report does not change risk state or trading decisions."
        ),
    }
