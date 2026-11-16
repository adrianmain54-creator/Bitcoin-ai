"""Simulation-only portfolio execution with explicit exposure and cost limits.

This module has no exchange client, network access, wallet support, or live-order path.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math


class PaperTradingError(ValueError):
    """Raised when a simulated trade request or account configuration is invalid."""


@dataclass
class PaperAccount:
    cash: float = 10_000.0
    btc: float = 0.0
    fee_bps: float = 10.0
    slippage_bps: float = 5.0
    max_allocation: float = 0.25
    trades: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        values = (self.cash, self.btc, self.fee_bps, self.slippage_bps, self.max_allocation)
        if any(isinstance(value, bool) or not isinstance(value, (int, float))
               or not math.isfinite(value) for value in values):
            raise PaperTradingError("account values must be finite numbers")
        if not isinstance(self.trades, list) or any(not isinstance(event, dict) for event in self.trades):
            raise PaperTradingError("trades must be a list of event objects")
        if self.cash < 0 or self.btc < 0:
            raise PaperTradingError("cash and BTC balances cannot be negative")
        if self.fee_bps < 0 or self.slippage_bps < 0:
            raise PaperTradingError("fees and slippage cannot be negative")
        if self.fee_bps >= 10_000 or self.slippage_bps >= 10_000:
            raise PaperTradingError("fees and slippage must each be below 10,000 bps")
        if not 0 <= self.max_allocation <= 1:
            raise PaperTradingError("max_allocation must be between 0 and 1")

    def equity(self, price: float) -> float:
        _validate_price(price)
        return self.cash + self.btc * price

    def rebalance(self, target_allocation: float, price: float) -> dict:
        """Move toward a BTC allocation target, capped by max_allocation.

        Slippage is applied adversely to the simulated execution price and fees are
        deducted from cash/proceeds. No order is sent to an exchange.
        """
        _validate_price(price)
        if (isinstance(target_allocation, bool)
                or not isinstance(target_allocation, (int, float))
                or not math.isfinite(target_allocation)):
            raise PaperTradingError("target_allocation must be a finite number")
        if not 0 <= target_allocation <= 1:
            raise PaperTradingError("target_allocation must be between 0 and 1")

        target = min(target_allocation, self.max_allocation)
        equity_before = self.equity(price)
        target_value = equity_before * target
        current_value = self.btc * price
        delta = target_value - current_value
        fee_rate = self.fee_bps / 10_000
        slip_rate = self.slippage_bps / 10_000
        side = "hold"
        quantity = 0.0
        execution_price = price
        fee_paid = 0.0

        if delta > max(1e-12, equity_before * 1e-12):
            side = "buy"
            execution_price = price * (1 + slip_rate)
            spend = min(delta, self.cash / (1 + fee_rate))
            quantity = spend / (execution_price * (1 + fee_rate))
            gross = quantity * execution_price
            fee_paid = gross * fee_rate
            self.cash -= gross + fee_paid
            self.btc += quantity
        elif delta < -max(1e-12, equity_before * 1e-12):
            side = "sell"
            execution_price = price * (1 - slip_rate)
            quantity = min(self.btc, (-delta) / price)
            gross = quantity * execution_price
            fee_paid = gross * fee_rate
            self.btc -= quantity
            self.cash += gross - fee_paid

        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "mode": "paper",
            "side": side,
            "reference_price": price,
            "execution_price": execution_price,
            "quantity_btc": quantity,
            "fee_paid": fee_paid,
            "target_allocation": target,
            "equity_before": equity_before,
            "equity_after": self.equity(price),
            "cash_after": self.cash,
            "btc_after": self.btc,
        }
        if side != "hold":
            self.trades.append(event)
        return event


def _validate_price(price: float) -> None:
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        raise PaperTradingError("price must be a finite positive number")
