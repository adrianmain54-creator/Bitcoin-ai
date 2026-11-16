"""Multi-family walk-forward strategy research and block-bootstrap robustness.

Signals use completed closes and trade only the following bar. All tuning is
confined to each training window; test returns are never used for selection.
This is research tooling, not a profitability claim.
"""
from __future__ import annotations

import math
import random
from statistics import mean, pstdev

from .backtesting import BacktestError, Bar, _metrics, _equity_curve


DEFAULT_CANDIDATES = [
    {"family": "sma", "lookback": 12},
    {"family": "sma", "lookback": 24},
    {"family": "momentum", "lookback": 5},
    {"family": "momentum", "lookback": 10},
    {"family": "breakout", "lookback": 20},
]


def _validate(bars, train_bars, test_bars, candidates, fee_bps, slippage_bps):
    if not isinstance(bars, list) or len(bars) < 3 or any(not isinstance(b, Bar) for b in bars):
        raise BacktestError("bars must be a list of at least 3 Bar observations")
    if any(bars[i].timestamp <= bars[i - 1].timestamp for i in range(1, len(bars))):
        raise BacktestError("Bars must have strictly increasing timestamps")
    if any(not isinstance(b.close, (int, float)) or isinstance(b.close, bool)
           or not math.isfinite(b.close) or b.close <= 0 for b in bars):
        raise BacktestError("Bar closes must be finite positive numbers")
    for value, name in ((train_bars, "train_bars"), (test_bars, "test_bars")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 3:
            raise BacktestError(f"{name} must be an integer >= 3")
    if not isinstance(candidates, (list, tuple)) or not candidates:
        raise BacktestError("At least one strategy candidate is required")
    normalized = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {"family", "lookback"}:
            raise BacktestError("Candidates require exactly family and lookback")
        family, lookback = candidate["family"], candidate["lookback"]
        if family not in {"sma", "momentum", "breakout"}:
            raise BacktestError("Unknown strategy family")
        if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2 or lookback >= train_bars:
            raise BacktestError("lookback must be an integer >= 2 and smaller than train_bars")
        item = (family, lookback)
        if item in normalized:
            raise BacktestError("Duplicate strategy candidates are not allowed")
        normalized.append(item)
    for value, name in ((fee_bps, "fee_bps"), (slippage_bps, "slippage_bps")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise BacktestError(f"{name} must be finite and non-negative")
    if fee_bps + slippage_bps >= 10000:
        raise BacktestError("Combined costs must be less than 10000 bps")
    return normalized


def _signal(closes, i, family, lookback):
    if family == "sma":
        fast = sum(closes[i - max(2, lookback // 3) + 1:i + 1]) / max(2, lookback // 3)
        slow = sum(closes[i - lookback + 1:i + 1]) / lookback
        return 1.0 if fast > slow and closes[i] > slow else 0.0
    if family == "momentum":
        return 1.0 if closes[i] > closes[i - lookback] else 0.0
    # Strictly prior rolling high: today's close is not part of the threshold.
    prior_high = max(closes[i - lookback:i])
    return 1.0 if closes[i] > prior_high else 0.0


def _simulate(closes, start, end, family, lookback, cost):
    position = 0.0
    returns = []
    for i in range(start, end):
        target = _signal(closes, i, family, lookback)
        turnover = abs(target - position)
        market_return = closes[i + 1] / closes[i] - 1.0
        returns.append(target * market_return - turnover * cost)
        position = target
    if position:
        returns[-1] -= cost
    return returns


def _bootstrap(returns, trials, seed, block_size=5):
    if not returns:
        return {"trials": 0, "final_equity_p05": None, "final_equity_median": None,
                "final_equity_p95": None, "max_drawdown_p05_pct": None,
                "max_drawdown_median_pct": None, "max_drawdown_p95_pct": None}
    rng = random.Random(seed)
    finals, drawdowns = [], []
    n = len(returns)
    for _ in range(trials):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(returns[(start + offset) % n] for offset in range(block_size))
        equity = _equity_curve(sample[:n])
        finals.append(equity[-1])
        peak, worst = 1.0, 0.0
        for value in equity:
            peak = max(peak, value)
            worst = min(worst, value / peak - 1.0)
        drawdowns.append(worst * 100)
    def percentile(values, p):
        ordered = sorted(values)
        return ordered[round((len(ordered) - 1) * p)]
    return {
        "trials": trials,
        "block_size": block_size,
        "final_equity_p05": round(percentile(finals, .05), 6),
        "final_equity_median": round(percentile(finals, .50), 6),
        "final_equity_p95": round(percentile(finals, .95), 6),
        "max_drawdown_p05_pct": round(percentile(drawdowns, .05), 4),
        "max_drawdown_median_pct": round(percentile(drawdowns, .50), 4),
        "max_drawdown_p95_pct": round(percentile(drawdowns, .95), 4),
        "warning": "Bootstrap resamples historical returns; it is not a forecast and cannot model unseen regimes.",
    }


def run_strategy_lab(bars: list[Bar], *, train_bars: int, test_bars: int,
                     candidates=None, step_bars=None, fee_bps=10.0,
                     slippage_bps=5.0, periods_per_year=365.0,
                     bootstrap_trials=500, seed=7):
    """Compare SMA, momentum and breakout candidates using rolling OOS folds."""
    candidates = DEFAULT_CANDIDATES if candidates is None else candidates
    normalized = _validate(bars, train_bars, test_bars, candidates, fee_bps, slippage_bps)
    step = test_bars if step_bars is None else step_bars
    if isinstance(step, bool) or not isinstance(step, int) or step < test_bars:
        raise BacktestError("step_bars must be an integer >= test_bars")
    if isinstance(bootstrap_trials, bool) or not isinstance(bootstrap_trials, int) or not 100 <= bootstrap_trials <= 10000:
        raise BacktestError("bootstrap_trials must be an integer between 100 and 10000")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise BacktestError("seed must be an integer")
    if isinstance(periods_per_year, bool) or not isinstance(periods_per_year, (int, float)) or not math.isfinite(periods_per_year) or periods_per_year <= 0:
        raise BacktestError("periods_per_year must be finite and positive")
    closes = [float(b.close) for b in bars]
    cost = (fee_bps + slippage_bps) / 10000
    cursor, folds, oos, benchmark = train_bars, [], [], []
    while cursor + test_bars < len(bars):
        scored = []
        for family, lookback in normalized:
            train_returns = _simulate(closes, cursor - train_bars + lookback - 1,
                                      cursor - 1, family, lookback, cost)
            if not train_returns:
                continue
            equity = _equity_curve(train_returns)
            metrics = _metrics(train_returns, equity, periods_per_year)
            # Conservative deterministic score: reward risk-adjusted return,
            # penalize deep drawdowns. Candidate choice sees training data only.
            score = metrics["sortino_ratio"] - abs(metrics["max_drawdown_pct"]) / 10
            scored.append((score, family, lookback, metrics))
        if not scored:
            raise BacktestError("Training window produced no candidate scores")
        chosen = max(scored, key=lambda item: (item[0], item[1], -item[2]))
        family, lookback = chosen[1], chosen[2]
        test_start = cursor
        test_end = cursor + test_bars
        # Include training history so the first test signal has sufficient lookback.
        fold_returns = _simulate(closes, test_start, test_end, family, lookback, cost)
        market_returns = [closes[i + 1] / closes[i] - 1 for i in range(test_start, test_end)]
        oos.extend(fold_returns)
        benchmark.extend(market_returns)
        folds.append({
            "train_start": bars[cursor - train_bars].timestamp.isoformat(),
            "train_end": bars[cursor - 1].timestamp.isoformat(),
            "test_start": bars[test_start].timestamp.isoformat(),
            "test_end": bars[test_end].timestamp.isoformat(),
            "selected_family": family, "selected_lookback": lookback,
            "training_selection_score": round(chosen[0], 4),
            "training_sortino": chosen[3]["sortino_ratio"],
            "oos_metrics": _metrics(fold_returns, _equity_curve(fold_returns), periods_per_year),
        })
        cursor += step
    if not folds:
        raise BacktestError("Not enough bars for one complete train/test fold")
    return {
        "method": "multi-family rolling walk-forward with block bootstrap",
        "families": sorted({family for family, _ in normalized}),
        "fold_count": len(folds),
        "out_of_sample_returns": len(oos),
        "out_of_sample_metrics": _metrics(oos, _equity_curve(oos), periods_per_year),
        "buy_and_hold_metrics": _metrics(benchmark, _equity_curve(benchmark), periods_per_year),
        "cash_metrics": _metrics([0.0] * len(oos), _equity_curve([0.0] * len(oos)), periods_per_year),
        "bootstrap": _bootstrap(oos, bootstrap_trials, seed),
        "folds": folds,
        "selection_policy": "Maximize training Sortino minus 0.1 times absolute training max drawdown percentage; deterministic tie-break. Test data never selects parameters.",
        "limitations": [
            "Close-only signals execute on the next close-to-close interval; estimated fee and slippage are charged on position changes and fold liquidation.",
            "No spread, market impact, partial fills, funding, taxes, outages, or latency are modeled.",
            "Block bootstrap assumes historical return blocks are informative and cannot capture unprecedented regimes.",
            "Research results do not establish future profitability; paper trading remains the only execution mode.",
        ],
    }
