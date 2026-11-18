"""Conservative research-result gate for starting a separate paper trial.

This never enables exchange execution or changes the live paper strategy.
"""
from __future__ import annotations

import math


def evaluate_paper_trial_eligibility(report, *, min_folds=6, min_oos_returns=180,
                                     max_drawdown_pct=20.0):
    reasons = []
    if not isinstance(report, dict):
        return {"eligible": False, "reasons": ["report must be a dictionary"], "scope": "paper trial only"}
    if isinstance(min_folds, bool) or not isinstance(min_folds, int) or min_folds < 1:
        raise ValueError("min_folds must be an integer >= 1")
    if isinstance(min_oos_returns, bool) or not isinstance(min_oos_returns, int) or min_oos_returns < 1:
        raise ValueError("min_oos_returns must be an integer >= 1")
    if isinstance(max_drawdown_pct, bool) or not isinstance(max_drawdown_pct, (int, float)) or not math.isfinite(max_drawdown_pct) or max_drawdown_pct <= 0:
        raise ValueError("max_drawdown_pct must be finite and positive")

    folds = report.get("fold_count")
    n = report.get("out_of_sample_returns")
    strategy = report.get("out_of_sample_metrics")
    benchmark = report.get("buy_and_hold_metrics")
    bootstrap = report.get("bootstrap")
    stressed = report.get("out_of_sample_metrics_at_2x_cost")
    if isinstance(folds, bool) or not isinstance(folds, int) or folds < min_folds:
        reasons.append(f"requires at least {min_folds} completed out-of-sample folds")
    if isinstance(n, bool) or not isinstance(n, int) or n < min_oos_returns:
        reasons.append(f"requires at least {min_oos_returns} out-of-sample returns")
    if (not isinstance(strategy, dict) or not isinstance(benchmark, dict)
            or not isinstance(bootstrap, dict) or not isinstance(stressed, dict)):
        reasons.append("missing strategy, benchmark, bootstrap, or 2x-cost stress evidence")
    else:
        def finite_metric(obj, key):
            value = obj.get(key)
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
        strat_return = finite_metric(strategy, "total_return_pct")
        bench_return = finite_metric(benchmark, "total_return_pct")
        drawdown = finite_metric(strategy, "max_drawdown_pct")
        sortino = finite_metric(strategy, "sortino_ratio")
        p05 = finite_metric(bootstrap, "final_equity_p05")
        stressed_return = finite_metric(stressed, "total_return_pct")
        if None in (strat_return, bench_return, drawdown, sortino, p05, stressed_return):
            reasons.append("required performance, stress, or bootstrap metrics are missing or invalid")
        else:
            if strat_return <= bench_return:
                reasons.append("out-of-sample return did not beat buy-and-hold")
            if drawdown < -max_drawdown_pct:
                reasons.append(f"maximum drawdown exceeded {max_drawdown_pct:g}%")
            if sortino <= 0:
                reasons.append("out-of-sample Sortino ratio is not positive")
            if p05 <= 1.0:
                reasons.append("bootstrap fifth-percentile ending equity is not above starting equity")
            if stressed_return <= 0.0:
                reasons.append("out-of-sample return is not positive at 2x estimated execution costs")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "scope": "eligibility for a separately monitored paper-forward trial only; never authorizes live trading",
        "minimums": {"folds": min_folds, "oos_returns": min_oos_returns, "max_drawdown_pct": max_drawdown_pct},
    }


def evaluate_strategy_abstention_gate(candidates, *, min_observations=180,
                                      min_probability_positive_pct=95.0):
    """Conservative descriptive gate: recommend cash unless a fixed candidate clears every check.

    This is an OOS research diagnostic only. It does not select a strategy,
    change paper-service positions, or authorize exchange execution.
    """
    if isinstance(min_observations, bool) or not isinstance(min_observations, int) or min_observations < 1:
        raise ValueError("min_observations must be an integer >= 1")
    if (isinstance(min_probability_positive_pct, bool)
            or not isinstance(min_probability_positive_pct, (int, float))
            or not math.isfinite(min_probability_positive_pct)
            or not 0 <= min_probability_positive_pct <= 100):
        raise ValueError("min_probability_positive_pct must be between 0 and 100")
    if not isinstance(candidates, dict) or not candidates:
        return {
            "recommended_action": "cash/abstain",
            "clearing_candidates": [],
            "candidate_results": {},
            "reasons": ["no fixed-candidate evidence is available"],
            "scope": "descriptive research gate only; not a trading instruction",
        }

    results = {}
    clearing = []
    for name, candidate in candidates.items():
        reasons = []
        if not isinstance(candidate, dict):
            candidate = {}
        uncertainty = candidate.get("paired_edge_uncertainty")
        stress = candidate.get("metrics_at_2x_cost")
        observations = uncertainty.get("observations") if isinstance(uncertainty, dict) else None
        lower_edge = uncertainty.get("excess_return_p05_pct") if isinstance(uncertainty, dict) else None
        probability = uncertainty.get("probability_positive_pct") if isinstance(uncertainty, dict) else None
        stressed_return = stress.get("total_return_pct") if isinstance(stress, dict) else None

        def valid_number(value):
            return (isinstance(value, (int, float)) and not isinstance(value, bool)
                    and math.isfinite(value))

        if not isinstance(observations, int) or isinstance(observations, bool) or observations < min_observations:
            reasons.append(f"requires at least {min_observations} paired held-out observations")
        if not valid_number(lower_edge) or lower_edge <= 0:
            reasons.append("paired edge fifth-percentile estimate is not positive")
        if not valid_number(probability) or probability < min_probability_positive_pct:
            reasons.append(f"bootstrap positive-edge share is below {min_probability_positive_pct:g}%")
        if not valid_number(stressed_return) or stressed_return <= 0:
            reasons.append("candidate return is not positive at 2x estimated execution costs")
        results[name] = {"clears_gate": not reasons, "reasons": reasons}
        if not reasons:
            clearing.append(name)

    return {
        "recommended_action": "paper-trial candidate review" if clearing else "cash/abstain",
        "clearing_candidates": clearing,
        "candidate_results": results,
        "reasons": [] if clearing else ["no fixed candidate clears every conservative evidence and cost check"],
        "minimums": {
            "paired_observations": min_observations,
            "probability_positive_pct": min_probability_positive_pct,
            "paired_edge_p05_pct": "greater than 0",
            "2x_cost_return_pct": "greater than 0",
        },
        "scope": "descriptive research gate only; not a trading instruction or authorization for live execution",
    }
