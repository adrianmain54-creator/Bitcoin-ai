"""Walk-forward research with strict chronological train/test separation.

This module selects SMA parameters only on each training window, then evaluates
those frozen parameters on the following unseen test window. It is research
software: repeated historical success is not a guarantee of future returns.
"""
from __future__ import annotations

import math

from .backtesting import BacktestError, Bar, _metrics, run_sma_backtest


def walk_forward_sma_backtest(
    bars: list[Bar],
    *,
    candidates: list[tuple[int, int]],
    train_bars: int,
    test_bars: int,
    step_bars: int | None = None,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    periods_per_year: float = 365.0,
) -> dict:
    """Tune on rolling past windows and score only on subsequent unseen returns.

    Each fold starts flat at its first test close. A signal formed at close t
    affects only the t-to-t+1 return. Folds do not overlap by default.
    """
    if not isinstance(bars, list) or len(bars) < 3:
        raise BacktestError("bars must contain at least 3 observations")
    if any(not isinstance(bar, Bar) for bar in bars):
        raise BacktestError("bars must contain Bar observations")
    if any(bars[i].timestamp <= bars[i - 1].timestamp for i in range(1, len(bars))):
        raise BacktestError("Bars must have strictly increasing timestamps")
    if any(not math.isfinite(bar.close) or bar.close <= 0 for bar in bars):
        raise BacktestError("Bar closes must be finite and positive")
    for value, name in ((train_bars, "train_bars"), (test_bars, "test_bars")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 2:
            raise BacktestError(f"{name} must be an integer >= 2")
    step = test_bars if step_bars is None else step_bars
    if isinstance(step, bool) or not isinstance(step, int) or step < test_bars:
        raise BacktestError("step_bars must be an integer >= test_bars (no overlapping test folds)")
    if not candidates:
        raise BacktestError("At least one (fast, slow) candidate is required")
    normalized: list[tuple[int, int]] = []
    for pair in candidates:
        if not isinstance(pair, (tuple, list)) or len(pair) != 2:
            raise BacktestError("Each candidate must be a (fast_window, slow_window) pair")
        fast, slow = pair
        if (isinstance(fast, bool) or isinstance(slow, bool)
                or not isinstance(fast, int) or not isinstance(slow, int)
                or fast < 1 or slow <= fast):
            raise BacktestError("Candidates must satisfy 1 <= fast_window < slow_window")
        if slow > train_bars:
            raise BacktestError("Every candidate slow window must fit inside train_bars")
        normalized.append((fast, slow))
    if len(set(normalized)) != len(normalized):
        raise BacktestError("Duplicate parameter candidates are not allowed")
    if (not math.isfinite(fee_bps) or not math.isfinite(slippage_bps)
            or fee_bps < 0 or slippage_bps < 0 or fee_bps + slippage_bps >= 10000):
        raise BacktestError("Costs must be finite, non-negative, and total less than 10000 bps")
    if not math.isfinite(periods_per_year) or periods_per_year <= 0:
        raise BacktestError("periods_per_year must be finite and positive")

    folds = []
    out_of_sample_returns: list[float] = []
    benchmark_returns: list[float] = []
    cursor = train_bars
    while cursor + test_bars < len(bars):
        train = bars[cursor - train_bars:cursor]
        test_end = cursor + test_bars
        history_and_test = bars[cursor - train_bars:test_end + 1]

        scored = []
        for fast, slow in normalized:
            report = run_sma_backtest(
                train, fast_window=fast, slow_window=slow,
                fee_bps=fee_bps, slippage_bps=slippage_bps,
                periods_per_year=periods_per_year,
            )
            metrics = report["strategy_metrics"]
            scored.append((metrics["sharpe_ratio"], metrics["max_drawdown_pct"],
                           -slow, -fast, fast, slow))
        # Deterministic tie-break: higher Sharpe, shallower drawdown, then shorter windows.
        chosen = max(scored)
        fast, slow = chosen[-2], chosen[-1]

        closes = [bar.close for bar in history_and_test]
        offset = train_bars
        position = 0.0
        fold_returns = []
        fold_benchmark = []
        cost = (fee_bps + slippage_bps) / 10000.0
        for local_i in range(offset, offset + test_bars):
            fast_mean = sum(closes[local_i - fast + 1:local_i + 1]) / fast
            slow_mean = sum(closes[local_i - slow + 1:local_i + 1]) / slow
            next_position = 1.0 if fast_mean > slow_mean else 0.0
            turnover = abs(next_position - position)
            market_return = closes[local_i + 1] / closes[local_i] - 1.0
            fold_returns.append(next_position * market_return - turnover * cost)
            fold_benchmark.append(market_return)
            position = next_position

        out_of_sample_returns.extend(fold_returns)
        benchmark_returns.extend(fold_benchmark)
        folds.append({
            "train_start": train[0].timestamp.isoformat(),
            "train_end": train[-1].timestamp.isoformat(),
            "test_start": bars[cursor].timestamp.isoformat(),
            "test_end": bars[test_end].timestamp.isoformat(),
            "selected_fast_window": fast,
            "selected_slow_window": slow,
            "training_sharpe_ratio": chosen[0],
            "out_of_sample_metrics": _metrics(
                fold_returns, _equity_curve(fold_returns), periods_per_year
            ),
            "out_of_sample_returns": len(fold_returns),
        })
        cursor += step

    if not folds:
        raise BacktestError("Not enough bars for one complete train/test fold")
    return {
        "method": "rolling walk-forward SMA selection",
        "selection_rule": "Highest training Sharpe; ties prefer shallower training drawdown, then shorter windows",
        "test_policy": "Parameters are frozen per fold; no test return is used for selection",
        "fold_count": len(folds),
        "out_of_sample_returns": len(out_of_sample_returns),
        "out_of_sample_metrics": _metrics(
            out_of_sample_returns, _equity_curve(out_of_sample_returns), periods_per_year
        ),
        "buy_and_hold_metrics": _metrics(
            benchmark_returns, _equity_curve(benchmark_returns), periods_per_year
        ),
        "folds": folds,
        "assumptions": [
            "Each test fold starts in cash; position is carried only within that fold.",
            "Signals use completed close data and apply to the next close-to-close return.",
            "Fees and slippage are charged on each full position change.",
            "No spread, market impact, funding, taxes, or exchange outages are modeled.",
            "This historical research result is not a calibrated forecast or a guarantee.",
        ],
    }


def _equity_curve(returns: list[float]) -> list[float]:
    equity = [1.0]
    for value in returns:
        equity.append(equity[-1] * (1.0 + value))
    return equity
