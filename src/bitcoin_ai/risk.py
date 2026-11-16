"""Fail-closed risk gates for the paper-trading agent."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math


class RiskError(ValueError):
    """Invalid risk configuration or portfolio observation."""


@dataclass(frozen=True)
class RiskLimits:
    max_allocation: float = 0.20
    max_daily_loss_pct: float = 0.02
    max_drawdown_pct: float = 0.10
    max_data_age_seconds: float = 180.0
    cooldown_seconds: float = 900.0

    def __post_init__(self) -> None:
        fractions = (self.max_allocation, self.max_daily_loss_pct, self.max_drawdown_pct)
        if any(isinstance(v, bool) or not isinstance(v, (int, float))
               or not math.isfinite(v) for v in fractions):
            raise RiskError("risk fractions must be finite numbers")
        if not 0 <= self.max_allocation <= 1:
            raise RiskError("max_allocation must be between 0 and 1")
        if not 0 < self.max_daily_loss_pct < 1:
            raise RiskError("max_daily_loss_pct must be between 0 and 1")
        if not 0 < self.max_drawdown_pct < 1:
            raise RiskError("max_drawdown_pct must be between 0 and 1")
        for value, name in ((self.max_data_age_seconds, "max_data_age_seconds"),
                            (self.cooldown_seconds, "cooldown_seconds")):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise RiskError(f"{name} must be a finite non-negative number")


@dataclass
class RiskState:
    utc_day: str
    day_start_equity: float
    peak_equity: float
    last_trade_at: datetime | None = None
    halted: bool = False


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    target_allocation: float
    reason: str
    halted: bool


def new_risk_state(equity: float, now: datetime) -> RiskState:
    _validate_equity(equity)
    current = _utc(now)
    return RiskState(current.date().isoformat(), equity, equity)


def evaluate_risk(
    *,
    requested_allocation: float,
    current_allocation: float,
    equity: float,
    state: RiskState,
    observed_at: datetime,
    now: datetime,
    limits: RiskLimits = RiskLimits(),
    kill_switch: bool = False,
) -> RiskDecision:
    """Clamp exposure and fail closed on stale data, loss limits, or kill switch.

    A breached loss/drawdown limit permanently halts this state until an operator
    deliberately creates/resets state. A stale feed blocks trading without changing
    the requested portfolio target.
    """
    _validate_equity(equity)
    for value, name in ((requested_allocation, "requested_allocation"),
                        (current_allocation, "current_allocation")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 1:
            raise RiskError(f"{name} must be between 0 and 1")
    if not isinstance(state, RiskState):
        raise RiskError("state must be a RiskState")
    _validate_equity(state.day_start_equity)
    _validate_equity(state.peak_equity)
    if not isinstance(state.utc_day, str):
        raise RiskError("risk state utc_day must be an ISO date")
    try:
        datetime.fromisoformat(state.utc_day)
    except ValueError as exc:
        raise RiskError("risk state utc_day must be an ISO date") from exc
    if not isinstance(state.halted, bool):
        raise RiskError("risk state halted flag must be boolean")
    if state.last_trade_at is not None:
        _utc(state.last_trade_at)

    current_time = _utc(now)
    observation_time = _utc(observed_at)
    if observation_time > current_time:
        return RiskDecision(False, current_allocation, "Market data timestamp is in the future.", False)

    age = (current_time - observation_time).total_seconds()
    if age > limits.max_data_age_seconds:
        return RiskDecision(False, current_allocation, "Market data is stale; no rebalance allowed.", False)

    day = current_time.date().isoformat()
    if day != state.utc_day:
        state.utc_day = day
        state.day_start_equity = equity

    state.peak_equity = max(state.peak_equity, equity)
    daily_loss = max(0.0, 1.0 - equity / state.day_start_equity)
    drawdown = max(0.0, 1.0 - equity / state.peak_equity)

    if kill_switch:
        state.halted = True
        return RiskDecision(False, 0.0, "Emergency kill switch is active; target cash.", True)
    if state.halted:
        return RiskDecision(False, 0.0, "Trading is halted; manual reset is required.", True)
    if daily_loss >= limits.max_daily_loss_pct:
        state.halted = True
        return RiskDecision(False, 0.0, "Daily loss limit breached; trading halted and target cash.", True)
    if drawdown >= limits.max_drawdown_pct:
        state.halted = True
        return RiskDecision(False, 0.0, "Maximum drawdown breached; trading halted and target cash.", True)

    target = min(float(requested_allocation), limits.max_allocation)
    if state.last_trade_at is not None:
        elapsed = (current_time - _utc(state.last_trade_at)).total_seconds()
        if elapsed < limits.cooldown_seconds and abs(target - current_allocation) > 1e-9:
            return RiskDecision(False, current_allocation, "Trade cooldown is active; keep current allocation.", False)

    return RiskDecision(True, target, "Risk checks passed.", False)


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise RiskError("timestamps must be timezone-aware")
    return value.astimezone(timezone.utc)


def _validate_equity(value: float) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise RiskError("equity must be a finite positive number")
