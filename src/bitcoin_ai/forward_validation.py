"""Descriptive evaluation of genuinely forward paper observations.

This module never authorizes trading. It reports whether enough unique,
chronologically ordered paper observations exist for a human review.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math

GENESIS_HASH = "0" * 64


def observation_digest(observation):
    """Hash an observation's canonical contents, excluding its own digest."""
    payload = {key: value for key, value in observation.items()
               if key != "observation_hash"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def verify_observation_chain(observations):
    previous = GENESIS_HASH
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            raise ValueError(f"observation {index} must be an object")
        if item.get("previous_hash") != previous:
            raise ValueError(f"observation {index} has a broken previous-hash link")
        try:
            actual = observation_digest(item)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"observation {index} cannot be hashed") from exc
        if item.get("observation_hash") != actual:
            raise ValueError(f"observation {index} hash verification failed")
        previous = actual
    return True


def evaluate_forward_paper_evidence(observations, *, min_observations=100,
                                    min_days=7.0):
    if not isinstance(observations, list):
        raise ValueError("observations must be a list")
    if (isinstance(min_observations, bool) or not isinstance(min_observations, int)
            or min_observations < 2):
        raise ValueError("min_observations must be an integer >= 2")
    if (isinstance(min_days, bool) or not isinstance(min_days, (int, float))
            or not math.isfinite(min_days) or min_days < 0):
        raise ValueError("min_days must be a finite non-negative number")

    verify_observation_chain(observations)
    parsed = []
    for index, item in enumerate(observations):
        if not isinstance(item, dict):
            raise ValueError(f"observation {index} must be an object")
        try:
            timestamp = datetime.fromisoformat(item["observed_at"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"observation {index} has an invalid timestamp") from exc
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError(f"observation {index} timestamp must be timezone-aware")
        price, equity = item.get("price"), item.get("equity")
        for value, label in ((price, "price"), (equity, "equity")):
            if (isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(value) or value <= 0):
                raise ValueError(f"observation {index} {label} must be finite and positive")
        parsed.append((timestamp, float(price), float(equity)))

    if any(parsed[i][0] <= parsed[i - 1][0] for i in range(1, len(parsed))):
        raise ValueError("observations must have strictly increasing timestamps")

    count = len(parsed)
    elapsed_days = (
        (parsed[-1][0] - parsed[0][0]).total_seconds() / 86400.0
        if count >= 2 else 0.0
    )
    sufficient = count >= min_observations and elapsed_days >= min_days
    if count >= 2:
        first_equity = observations[0].get("baseline_equity", parsed[0][2])
        if (isinstance(first_equity, bool) or not isinstance(first_equity, (int, float))
                or not math.isfinite(first_equity) or first_equity <= 0):
            raise ValueError("first observation baseline_equity must be finite and positive")
        last_equity = parsed[-1][2]
        strategy_return = (last_equity / first_equity - 1.0) * 100.0
        benchmark_return = (parsed[-1][1] / parsed[0][1] - 1.0) * 100.0
        peak = parsed[0][2]
        max_drawdown = 0.0
        for _, _, equity in parsed:
            peak = max(peak, equity)
            max_drawdown = min(max_drawdown, (equity / peak - 1.0) * 100.0)
    else:
        strategy_return = benchmark_return = max_drawdown = None

    return {
        "status": "evidence_collected" if sufficient else "insufficient_evidence",
        "observations": count,
        "required_observations": min_observations,
        "elapsed_days": round(elapsed_days, 4),
        "required_days": float(min_days),
        "strategy_return_pct": round(strategy_return, 4) if strategy_return is not None else None,
        "buy_and_hold_return_pct": round(benchmark_return, 4) if benchmark_return is not None else None,
        "excess_return_vs_buy_and_hold_pct_points": (
            round(strategy_return - benchmark_return, 4)
            if strategy_return is not None and benchmark_return is not None else None
        ),
        "max_drawdown_pct": round(max_drawdown, 4) if max_drawdown is not None else None,
        "interpretation": (
            "Forward paper evidence has reached the configured review minimum. "
            "This is descriptive evidence, not proof of edge or permission to trade."
            if sufficient else
            "Keep collecting unique forward paper observations; historical backtests do not count."
        ),
    }
