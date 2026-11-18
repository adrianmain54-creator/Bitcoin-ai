"""Regime-by-regime fragility audit for fixed OOS candidate comparisons.

This is a diagnostic layer: it never promotes a strategy or changes execution.
"""
from __future__ import annotations

import math


class RegimeRobustnessError(ValueError):
    """Candidate regime evidence is malformed."""


def audit_regime_robustness(candidates, *, min_observations: int = 10) -> dict:
    """Flag under-sampled regimes and losses at doubled estimated costs.

    Input is the `fixed_candidate_oos_comparison.candidates` mapping emitted by
    research_lab. Every regime is evaluated on the same held-out intervals as
    its buy-and-hold benchmark. A candidate is never called robust or promoted.
    """
    if isinstance(min_observations, bool) or not isinstance(min_observations, int) or min_observations < 1:
        raise RegimeRobustnessError("min_observations must be an integer >= 1")
    if not isinstance(candidates, dict) or not candidates:
        raise RegimeRobustnessError("candidates must be a non-empty mapping")

    audited = {}
    all_underpowered = False
    any_fragile = False
    for name, candidate in sorted(candidates.items()):
        if not isinstance(name, str) or not name or not isinstance(candidate, dict):
            raise RegimeRobustnessError("candidate entries must have non-empty names and mapping values")
        regimes = candidate.get("regime_attribution")
        if not isinstance(regimes, dict) or not regimes:
            raise RegimeRobustnessError(f"{name}: missing regime_attribution")
        regime_results = {}
        underpowered, weak = [], []
        benchmark_wins, stress_positive = 0, 0
        for regime, values in sorted(regimes.items()):
            if not isinstance(regime, str) or not regime or not isinstance(values, dict):
                raise RegimeRobustnessError(f"{name}: malformed regime entry")
            observations = values.get("observations")
            net_2x = values.get("strategy_return_at_2x_cost_pct")
            excess = values.get("excess_return_vs_buy_and_hold_pct_points")
            for value, field in ((observations, "observations"), (net_2x, "strategy_return_at_2x_cost_pct"),
                                  (excess, "excess_return_vs_buy_and_hold_pct_points")):
                if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                    raise RegimeRobustnessError(f"{name}/{regime}: invalid {field}")
            if observations < 0 or int(observations) != observations:
                raise RegimeRobustnessError(f"{name}/{regime}: observations must be a non-negative integer")
            enough = observations >= min_observations
            if not enough:
                underpowered.append(regime)
            elif net_2x < 0:
                weak.append(regime)
            if enough and excess > 0:
                benchmark_wins += 1
            if enough and net_2x > 0:
                stress_positive += 1
            regime_results[regime] = {
                "observations": int(observations),
                "sample_status": "sufficient_for_diagnostic" if enough else "underpowered",
                "strategy_return_at_2x_cost_pct": round(float(net_2x), 4),
                "excess_return_vs_buy_and_hold_pct_points": round(float(excess), 4),
                "benchmark_outperformed": bool(excess < 0) if enough else None,
                "negative_at_2x_costs": bool(net_2x < 0) if enough else None,
            }
        all_underpowered = all_underpowered or bool(underpowered)
        any_fragile = any_fragile or bool(weak)
        audited[name] = {
            "status": "insufficient_evidence" if underpowered else (
                "regime_losses_detected" if weak else "no_obvious_regime_loss_detected"
            ),
            "regimes": regime_results,
            "underpowered_regimes": underpowered,
            "negative_regimes_at_2x_costs": weak,
            "benchmark_outperformance_regime_count": benchmark_wins,
            "positive_regime_count_at_2x_costs": stress_positive,
            "interpretation": (
                "Descriptive fixed-candidate OOS slices. Sample-size thresholds are screening "
                "heuristics; correlated regimes and repeated testing limit inference."
            ),
        }
    return {
        "status": "review_required" if all_underpowered or any_fragile else "no_obvious_regime_loss_detected",
        "minimum_observations_per_regime": min_observations,
        "candidates": audited,
        "promotion_effect": "none",
        "limitations": [
            "This audit does not establish robustness, predictive power, or future profitability.",
            "Regime observations are dependent and may overlap in time across candidate comparisons.",
            "Underpowered regimes are unknown, not successful.",
            "A positive result after doubled estimated costs is only a historical sensitivity check.",
            "No result from this audit authorizes paper promotion or live trading.",
        ],
    }
