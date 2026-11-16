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
    if isinstance(folds, bool) or not isinstance(folds, int) or folds < min_folds:
        reasons.append(f"requires at least {min_folds} completed out-of-sample folds")
    if isinstance(n, bool) or not isinstance(n, int) or n < min_oos_returns:
        reasons.append(f"requires at least {min_oos_returns} out-of-sample returns")
    if not isinstance(strategy, dict) or not isinstance(benchmark, dict) or not isinstance(bootstrap, dict):
        reasons.append("missing strategy, benchmark, or bootstrap evidence")
    else:
        def finite_metric(obj, key):
            value = obj.get(key)
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
        strat_return = finite_metric(strategy, "total_return_pct")
        bench_return = finite_metric(benchmark, "total_return_pct")
        drawdown = finite_metric(strategy, "max_drawdown_pct")
        sortino = finite_metric(strategy, "sortino_ratio")
        p05 = finite_metric(bootstrap, "final_equity_p05")
        if None in (strat_return, bench_return, drawdown, sortino, p05):
            reasons.append("required performance or bootstrap metrics are missing or invalid")
        else:
            if strat_return <= bench_return:
                reasons.append("out-of-sample return did not beat buy-and-hold")
            if drawdown < -max_drawdown_pct:
                reasons.append(f"maximum drawdown exceeded {max_drawdown_pct:g}%")
            if sortino <= 0:
                reasons.append("out-of-sample Sortino ratio is not positive")
            if p05 <= 1.0:
                reasons.append("bootstrap fifth-percentile ending equity is not above starting equity")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "scope": "eligibility for a separately monitored paper-forward trial only; never authorizes live trading",
        "minimums": {"folds": min_folds, "oos_returns": min_oos_returns, "max_drawdown_pct": max_drawdown_pct},
    }
