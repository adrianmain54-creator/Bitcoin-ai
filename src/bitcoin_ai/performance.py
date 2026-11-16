"""Transparent mark-to-market summary for a persisted paper account.

Drawdown is measured only at recorded trade checkpoints plus the current mark.
It is not an intrabar or continuous equity-curve drawdown.
"""
from __future__ import annotations

import math

from .paper_trading import PaperAccount, PaperTradingError


def build_performance_report(account: PaperAccount, *, price: float,
                             starting_cash: float) -> dict:
    if not isinstance(account, PaperAccount):
        raise PaperTradingError("account must be a PaperAccount")
    for name, value in (("price", price), ("starting_cash", starting_cash)):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise PaperTradingError(f"{name} must be a finite positive number")

    checkpoints = [float(starting_cash)]
    fees = 0.0
    for event in account.trades:
        if not isinstance(event, dict):
            raise PaperTradingError("trade history contains an invalid event")
        equity = event.get("equity_after")
        fee = event.get("fee_paid")
        if (isinstance(equity, bool) or not isinstance(equity, (int, float))
                or not math.isfinite(equity) or equity <= 0):
            raise PaperTradingError("trade history has invalid equity checkpoints")
        if (isinstance(fee, bool) or not isinstance(fee, (int, float))
                or not math.isfinite(fee) or fee < 0):
            raise PaperTradingError("trade history has invalid fee values")
        checkpoints.append(float(equity))
        fees += float(fee)

    equity = account.equity(price)
    if not math.isfinite(equity) or equity <= 0:
        raise PaperTradingError("current marked equity must be finite and positive")
    checkpoints.append(equity)
    peak = checkpoints[0]
    max_drawdown = 0.0
    for value in checkpoints[1:]:
        peak = max(peak, value)
        max_drawdown = max(max_drawdown, (peak - value) / peak)

    btc_value = account.btc * price
    return {
        "mode": "paper",
        "starting_cash": float(starting_cash),
        "mark_price": float(price),
        "cash": account.cash,
        "btc": account.btc,
        "btc_market_value": btc_value,
        "equity": equity,
        "net_pnl": equity - starting_cash,
        "return_pct": (equity / starting_cash - 1.0) * 100.0,
        "exposure_pct": btc_value / equity * 100.0,
        "cumulative_simulated_fees": fees,
        "trade_count": len(account.trades),
        "observed_checkpoint_max_drawdown_pct": max_drawdown * 100.0,
        "drawdown_note": (
            "Measured only at recorded trade checkpoints and this current mark; "
            "not a continuous or intrabar maximum drawdown."
        ),
    }
