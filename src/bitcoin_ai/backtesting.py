"""Leakage-aware historical BTC backtesting from user-supplied OHLCV CSV data.

Signals are calculated using closing prices and applied to the following bar.
This is research tooling, not a trading recommendation or execution system.
"""
from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, pstdev


class BacktestError(ValueError):
    """Invalid historical price data or strategy parameters."""


@dataclass(frozen=True)
class Bar:
    timestamp: datetime
    close: float


def _parse_timestamp(value: str) -> datetime:
    raw = value.strip()
    try:
        # Accept ISO-8601 timestamps and YYYY-MM-DD dates.
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BacktestError(f"Invalid timestamp: {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def load_close_csv(path: str | Path) -> list[Bar]:
    """Load a CSV containing timestamp and close columns; reject ambiguous data."""
    bars: list[Bar] = []
    try:
        with Path(path).open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                raise BacktestError("CSV must have a header row")
            names = {name.strip().lower(): name for name in reader.fieldnames if name}
            if "timestamp" not in names or "close" not in names:
                raise BacktestError("CSV requires timestamp and close columns")
            for line_number, row in enumerate(reader, start=2):
                try:
                    timestamp = _parse_timestamp(row[names["timestamp"]])
                    close = float(row[names["close"]])
                except (TypeError, ValueError) as exc:
                    raise BacktestError(f"Invalid timestamp/close at CSV line {line_number}") from exc
                if not math.isfinite(close) or close <= 0:
                    raise BacktestError(f"Close must be finite and positive at CSV line {line_number}")
                bars.append(Bar(timestamp, close))
    except OSError as exc:
        raise BacktestError(f"Cannot read CSV: {exc}") from exc

    if len(bars) < 3:
        raise BacktestError("At least 3 valid price rows are required")
    bars.sort(key=lambda bar: bar.timestamp)
    if len({bar.timestamp for bar in bars}) != len(bars):
        raise BacktestError("Duplicate timestamps are not allowed")
    return bars


def _sma(values: list[float], end: int, window: int) -> float:
    return sum(values[end - window + 1 : end + 1]) / window


def _metrics(returns: list[float], equity: list[float], periods_per_year: float) -> dict:
    if not returns:
        return {"total_return_pct": 0.0, "cagr_pct": 0.0, "annualized_volatility_pct": 0.0,
                "sharpe_ratio": 0.0, "max_drawdown_pct": 0.0}
    total = equity[-1] - 1.0
    years = len(returns) / periods_per_year if periods_per_year > 0 else 0
    cagr = equity[-1] ** (1 / years) - 1 if years > 0 and equity[-1] > 0 else -1.0
    volatility = pstdev(returns) * math.sqrt(periods_per_year) if len(returns) > 1 else 0.0
    avg = mean(returns)
    daily_std = pstdev(returns) if len(returns) > 1 else 0.0
    sharpe = (avg / daily_std * math.sqrt(periods_per_year)) if daily_std > 0 else 0.0
    peak = 1.0
    max_dd = 0.0
    for value in equity:
        peak = max(peak, value)
        max_dd = min(max_dd, value / peak - 1.0)
    downside_deviation = math.sqrt(
        mean(min(value, 0.0) ** 2 for value in returns)
    ) if returns else 0.0
    sortino = (
        avg / downside_deviation * math.sqrt(periods_per_year)
        if downside_deviation > 0 else 0.0
    )
    gross_profit = sum(value for value in returns if value > 0)
    gross_loss = -sum(value for value in returns if value < 0)
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else None
    calmar = cagr / abs(max_dd) if max_dd < 0 else None
    win_rate = sum(value > 0 for value in returns) / len(returns)
    return {
        "total_return_pct": round(total * 100, 4),
        "cagr_pct": round(cagr * 100, 4),
        "annualized_volatility_pct": round(volatility * 100, 4),
        "sharpe_ratio": round(sharpe, 4),
        "sortino_ratio": round(sortino, 4),
        "calmar_ratio": round(calmar, 4) if calmar is not None else None,
        "profit_factor": round(profit_factor, 4) if profit_factor is not None else None,
        "win_rate_pct": round(win_rate * 100, 4),
        "max_drawdown_pct": round(max_dd * 100, 4),
    }


def run_sma_backtest(
    bars: list[Bar],
    fast_window: int = 10,
    slow_window: int = 30,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    periods_per_year: float = 365.0,
) -> dict:
    """Long/cash SMA crossover; close-t signal is held from the next bar onward."""
    for value, name in ((fast_window, "fast_window"), (slow_window, "slow_window")):
        if isinstance(value, bool) or not isinstance(value, int):
            raise BacktestError(f"{name} must be an integer")
    if fast_window < 1 or slow_window <= fast_window:
        raise BacktestError("Require 1 <= fast_window < slow_window")
    for value, name in ((fee_bps, "fee_bps"), (slippage_bps, "slippage_bps"),
                        (periods_per_year, "periods_per_year")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise BacktestError(f"{name} must be a finite number")
    if fee_bps < 0 or slippage_bps < 0 or fee_bps + slippage_bps >= 10000:
        raise BacktestError("Costs must be non-negative and total less than 10000 bps")
    if periods_per_year <= 0:
        raise BacktestError("periods_per_year must be positive")
    if not isinstance(bars, (list, tuple)) or any(not isinstance(bar, Bar) for bar in bars):
        raise BacktestError("bars must be a list or tuple of Bar records")
    if len(bars) <= slow_window:
        raise BacktestError("Not enough rows for the slow moving-average window")
    for index, bar in enumerate(bars):
        if (not isinstance(bar.timestamp, datetime) or bar.timestamp.tzinfo is None
                or bar.timestamp.utcoffset() is None):
            raise BacktestError(f"Bar {index} timestamp must be timezone-aware")
        if (isinstance(bar.close, bool) or not isinstance(bar.close, (int, float))
                or not math.isfinite(bar.close) or bar.close <= 0):
            raise BacktestError(f"Bar {index} close must be finite and positive")
    if any(bars[i].timestamp <= bars[i - 1].timestamp for i in range(1, len(bars))):
        raise BacktestError("Bars must have strictly increasing timestamps")
    closes = [float(bar.close) for bar in bars]
    fee_rate = (fee_bps + slippage_bps) / 10000.0

    strategy_returns: list[float] = []
    benchmark_returns: list[float] = []
    strategy_equity = [1.0]
    benchmark_equity = [1.0]
    position = 0.0
    turnover_events = 0

    # At bar i close, compute signal; it can only affect bar i+1 return.
    for i in range(slow_window - 1, len(bars) - 1):
        signal = 1.0 if _sma(closes, i, fast_window) > _sma(closes, i, slow_window) else 0.0
        next_position = signal
        turnover = abs(next_position - position)
        gross_return = closes[i + 1] / closes[i] - 1.0
        net_return = next_position * gross_return - turnover * fee_rate
        strategy_returns.append(net_return)
        benchmark_returns.append(gross_return)
        strategy_equity.append(strategy_equity[-1] * (1.0 + net_return))
        benchmark_equity.append(benchmark_equity[-1] * (1.0 + gross_return))
        if turnover:
            turnover_events += 1
        position = next_position

    return {
        "strategy": "SMA crossover, long/cash",
        "signal_timing": "Signal from close of bar t is applied to return from close t to close t+1",
        "fast_window": fast_window,
        "slow_window": slow_window,
        "fee_bps_per_turnover": fee_bps,
        "slippage_bps_per_turnover": slippage_bps,
        "bars_in_test": len(strategy_returns),
        "start": bars[slow_window - 1].timestamp.isoformat(),
        "end": bars[-1].timestamp.isoformat(),
        "turnover_events": turnover_events,
        "strategy_metrics": _metrics(strategy_returns, strategy_equity, periods_per_year),
        "buy_and_hold_metrics": _metrics(benchmark_returns, benchmark_equity, periods_per_year),
        "limitations": [
            "Uses close-to-close returns and charges estimated costs when position changes.",
            "No spread, market impact, funding, taxes, exchange outages, or execution simulation.",
            "No parameter optimization or out-of-sample claim is performed by this command.",
            "Results depend on CSV source, interval, missing bars, and chosen assumptions.",
            "Past performance does not predict future results; this is not financial advice.",
        ],
    }
