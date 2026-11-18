"""Explain historical OOS loss concentration and drawdown episodes.

Diagnostics only: no forecasting, candidate selection, or execution authority.
"""
from __future__ import annotations

import math


class StrategyFailureAnalysisError(ValueError):
    """Malformed or misaligned out-of-sample return evidence."""


def analyze_strategy_failures(
    returns,
    *,
    stress_returns=None,
    regimes=None,
    timestamps=None,
    top_n: int = 5,
    min_regime_observations: int = 10,
) -> dict:
    """Summarize drawdown episodes, worst bars, and regime loss concentration.

    All arrays must describe the same chronological, already-held-out intervals.
    Returns are net of the supplied base costs; stress_returns are net of doubled
    estimated costs. This function does not infer causal explanations.
    """
    if not isinstance(returns, (list, tuple)) or not returns:
        raise StrategyFailureAnalysisError("returns must be a non-empty sequence")
    if isinstance(top_n, bool) or not isinstance(top_n, int) or not 1 <= top_n <= 50:
        raise StrategyFailureAnalysisError("top_n must be an integer from 1 to 50")
    if (isinstance(min_regime_observations, bool)
            or not isinstance(min_regime_observations, int)
            or min_regime_observations < 1):
        raise StrategyFailureAnalysisError("min_regime_observations must be a positive integer")

    n = len(returns)
    clean_returns = []
    for i, value in enumerate(returns):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= -1:
            raise StrategyFailureAnalysisError(f"return {i} must be finite and greater than -100%")
        clean_returns.append(float(value))

    def aligned_optional(values, name, numeric=False):
        if values is None:
            return None
        if not isinstance(values, (list, tuple)) or len(values) != n:
            raise StrategyFailureAnalysisError(f"{name} must align with returns")
        if numeric:
            result = []
            for i, value in enumerate(values):
                if (isinstance(value, bool) or not isinstance(value, (int, float))
                        or not math.isfinite(value) or value <= -1):
                    raise StrategyFailureAnalysisError(f"{name}[{i}] must be finite and greater than -100%")
                result.append(float(value))
            return result
        if any(not isinstance(value, str) or not value for value in values):
            raise StrategyFailureAnalysisError(f"{name} entries must be non-empty strings")
        return list(values)

    stress = aligned_optional(stress_returns, "stress_returns", numeric=True)
    labels = aligned_optional(regimes, "regimes")
    dates = aligned_optional(timestamps, "timestamps")

    equity = 1.0
    peak = 1.0
    peak_index = -1
    max_drawdown = 0.0
    max_drawdown_trough = None
    drawdowns = []
    active = None
    equity_curve = []
    for i, value in enumerate(clean_returns):
        equity *= 1.0 + value
        equity_curve.append(equity)
        if equity >= peak:
            if active is not None:
                active["trough_equity"] = round(active["trough_equity"], 8)
                active["drawdown_pct"] = round(active["drawdown_pct"], 4)
                active["recovery_index"] = i
                active["recovered"] = True
                drawdowns.append(active)
                active = None
            peak = equity
            peak_index = i
        else:
            dd = equity / peak - 1.0
            if dd < max_drawdown:
                max_drawdown = dd
                max_drawdown_trough = i
            if active is None:
                active = {
                    "peak_index": peak_index,
                    "trough_index": i,
                    "trough_equity": equity,
                    "drawdown_pct": dd * 100.0,
                    "recovery_index": None,
                    "recovered": False,
                }
            elif dd < active["drawdown_pct"] / 100.0:
                active["trough_index"] = i
                active["trough_equity"] = equity
                active["drawdown_pct"] = dd * 100.0
    if active is not None:
        active["trough_equity"] = round(active["trough_equity"], 8)
        active["drawdown_pct"] = round(active["drawdown_pct"], 4)
        drawdowns.append(active)

    losses = [(value, i) for i, value in enumerate(clean_returns) if value < 0]
    worst = sorted(losses, key=lambda pair: (pair[0], pair[1]))[:top_n]
    total_loss_magnitude = -sum(value for value, _ in losses)
    tail_count = max(1, math.ceil(n * 0.05))
    tail = sorted(clean_returns)[:tail_count]
    worst_loss_magnitude = -sum(value for value, _ in worst)
    loss_concentration = (
        min(1.0, worst_loss_magnitude / total_loss_magnitude)
        if total_loss_magnitude > 0 else 0.0
    )

    regime_report = {}
    if labels is not None:
        for label in sorted(set(labels)):
            indices = [i for i, item in enumerate(labels) if item == label]
            subset = [clean_returns[i] for i in indices]
            compounded = math.prod(1.0 + value for value in subset) - 1.0
            loss_magnitude = -sum(value for value in subset if value < 0)
            enough = len(indices) >= min_regime_observations
            regime_report[label] = {
                "observations": len(indices),
                "sample_status": "sufficient_for_diagnostic" if enough else "underpowered",
                "compounded_return_pct": round(compounded * 100.0, 4),
                "negative_bar_share_pct": round(
                    100.0 * sum(value < 0 for value in subset) / len(subset), 4
                ),
                "loss_contribution_pct": round(
                    100.0 * loss_magnitude / total_loss_magnitude, 4
                ) if total_loss_magnitude else 0.0,
                "interpretation": (
                    "descriptive loss concentration" if enough else "insufficient observations"
                ),
            }

    def describe_index(index):
        item = {"index": index, "return_pct": round(clean_returns[index] * 100.0, 6)}
        if dates is not None:
            item["timestamp"] = dates[index]
        if labels is not None:
            item["regime"] = labels[index]
        if stress is not None:
            item["return_at_2x_cost_pct"] = round(stress[index] * 100.0, 6)
        return item

    return {
        "status": "diagnostic_only",
        "observations": n,
        "compounded_return_pct": round((math.prod(1.0 + value for value in clean_returns) - 1.0) * 100.0, 4),
        "max_drawdown_pct": round(max_drawdown * 100.0, 4),
        "max_drawdown_trough": describe_index(max_drawdown_trough) if max_drawdown_trough is not None else None,
        "drawdown_episode_count": len(drawdowns),
        "drawdown_episodes": [
            {
                "peak_index": item["peak_index"],
                "trough": describe_index(item["trough_index"]),
                "drawdown_pct": item["drawdown_pct"],
                "recovery_index": item["recovery_index"],
                "recovered": item["recovered"],
                "duration_bars_to_recovery_or_end": (
                    (item["recovery_index"] - item["peak_index"])
                    if item["recovery_index"] is not None
                    else n - 1 - item["peak_index"]
                ),
            }
            for item in drawdowns
        ],
        "worst_bars": [describe_index(index) for _, index in worst],
        "worst_5pct_mean_return_pct": round(sum(tail) / len(tail) * 100.0, 4),
        "worst_bar_loss_concentration_pct": round(loss_concentration * 100.0, 4),
        "regime_loss_concentration": regime_report,
        "limitations": [
            "These are descriptive associations, not causal explanations of losses.",
            "Drawdown episodes are computed from the supplied net return stream and depend on interval ordering.",
            "The worst-bar concentration statistic ranks individual negative bars; it does not model serial dependence.",
            "Regime slices can be small, dependent, and sensitive to the regime definition.",
            "Historical failure diagnostics do not predict future losses or establish profitability.",
            "This report cannot promote candidates or authorize paper/live orders.",
        ],
    }
