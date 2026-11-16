"""One-cycle autonomous paper trader orchestration.

This module joins completed candle closes, the baseline strategy, independent risk
checks, and the simulation-only broker. It never accesses a network or exchange.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from .paper_trading import PaperAccount
from .risk import RiskDecision, RiskLimits, RiskState, evaluate_risk
from .strategy import TradingSignal, generate_signal


@dataclass(frozen=True)
class PaperCycleResult:
    signal: TradingSignal
    risk: RiskDecision
    execution: dict | None
    equity: float


def run_paper_cycle(
    *,
    closes: list[float] | tuple[float, ...],
    account: PaperAccount,
    risk_state: RiskState,
    observed_at: datetime,
    now: datetime,
    fast_window: int = 12,
    slow_window: int = 48,
    limits: RiskLimits = RiskLimits(),
    kill_switch: bool = False,
) -> PaperCycleResult:
    """Evaluate one completed-candle cycle and optionally rebalance paper holdings.

    Invalid strategy input raises before any account mutation. Stale/future data
    blocks execution. A risk halt requests a simulated move to cash, while normal
    strategy changes pass through exposure and cooldown gates.
    """
    if not isinstance(closes, (list, tuple)) or not closes:
        raise ValueError("closes must be a non-empty list or tuple")
    latest = closes[-1]
    if (isinstance(latest, bool) or not isinstance(latest, (int, float))
            or not math.isfinite(latest) or latest <= 0):
        raise ValueError("latest close must be a finite positive number")
    price = float(latest)
    equity = account.equity(price)
    if equity <= 0:
        raise ValueError("paper account equity must be positive")
    current_allocation = (account.btc * price) / equity
    signal = generate_signal(
        closes,
        fast_window=fast_window,
        slow_window=slow_window,
        max_allocation=limits.max_allocation,
        current_allocation=current_allocation,
    )

    decision = evaluate_risk(
        requested_allocation=signal.target_allocation,
        current_allocation=current_allocation,
        equity=equity,
        state=risk_state,
        observed_at=observed_at,
        now=now,
        limits=limits,
        kill_switch=kill_switch,
    )

    execution = None
    if decision.allowed:
        execution = account.rebalance(decision.target_allocation, price)
    elif decision.halted and current_allocation > 1e-12:
        # Risk halts are fail-safe: simulate reducing exposure to cash immediately.
        execution = account.rebalance(0.0, price)

    if execution is not None and execution["side"] != "hold":
        risk_state.last_trade_at = now

    return PaperCycleResult(
        signal=signal,
        risk=decision,
        execution=execution,
        equity=account.equity(price),
    )
