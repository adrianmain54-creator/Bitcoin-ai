from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.risk import RiskError, RiskLimits, evaluate_risk, new_risk_state


NOW = datetime(2026, 1, 2, 12, 0, tzinfo=timezone.utc)


def state(equity=10_000):
    return new_risk_state(equity, NOW)


def test_caps_requested_allocation():
    result = evaluate_risk(
        requested_allocation=0.9, current_allocation=0, equity=10_000,
        state=state(), observed_at=NOW, now=NOW,
        limits=RiskLimits(max_allocation=0.2),
    )
    assert result.allowed and result.target_allocation == 0.2


def test_stale_or_future_market_data_fails_closed():
    stale = evaluate_risk(
        requested_allocation=0.2, current_allocation=0.1, equity=10_000,
        state=state(), observed_at=NOW - timedelta(minutes=10), now=NOW,
    )
    assert not stale.allowed and stale.target_allocation == 0.1
    future = evaluate_risk(
        requested_allocation=0.2, current_allocation=0.1, equity=10_000,
        state=state(), observed_at=NOW + timedelta(seconds=1), now=NOW,
    )
    assert not future.allowed


def test_daily_loss_breach_halts_and_targets_cash():
    risk_state = state()
    result = evaluate_risk(
        requested_allocation=0.2, current_allocation=0.2, equity=9_700,
        state=risk_state, observed_at=NOW, now=NOW,
        limits=RiskLimits(max_daily_loss_pct=0.02),
    )
    assert not result.allowed and result.halted and result.target_allocation == 0
    again = evaluate_risk(
        requested_allocation=0.2, current_allocation=0.2, equity=9_700,
        state=risk_state, observed_at=NOW, now=NOW,
    )
    assert again.halted


def test_drawdown_breach_and_kill_switch_halt():
    risk_state = state()
    result = evaluate_risk(
        requested_allocation=0.2, current_allocation=0.2, equity=8_900,
        state=risk_state, observed_at=NOW, now=NOW,
    )
    assert result.halted
    other = state()
    killed = evaluate_risk(
        requested_allocation=0.2, current_allocation=0, equity=10_000,
        state=other, observed_at=NOW, now=NOW, kill_switch=True,
    )
    assert killed.halted and killed.target_allocation == 0


def test_cooldown_blocks_rebalance_but_allows_hold():
    risk_state = state()
    risk_state.last_trade_at = NOW - timedelta(minutes=2)
    result = evaluate_risk(
        requested_allocation=0.2, current_allocation=0, equity=10_000,
        state=risk_state, observed_at=NOW, now=NOW,
        limits=RiskLimits(cooldown_seconds=900),
    )
    assert not result.allowed and result.target_allocation == 0

def test_stale_data_does_not_change_daily_or_peak_risk_accounting():
    risk_state = state()
    risk_state.day_start_equity = 9_000
    risk_state.peak_equity = 11_000
    before = (risk_state.utc_day, risk_state.day_start_equity, risk_state.peak_equity)
    result = evaluate_risk(
        requested_allocation=0.2, current_allocation=0.1, equity=8_000,
        state=risk_state, observed_at=NOW - timedelta(minutes=10), now=NOW,
    )
    assert not result.allowed
    assert (risk_state.utc_day, risk_state.day_start_equity, risk_state.peak_equity) == before


@pytest.mark.parametrize("field,value", [
    ("day_start_equity", float("nan")),
    ("day_start_equity", 0),
    ("peak_equity", float("inf")),
    ("utc_day", "not-a-date"),
    ("halted", 1),
    ("last_trade_at", datetime(2026, 1, 2, 12, 0)),
])
def test_invalid_persisted_risk_state_is_rejected(field, value):
    risk_state = state()
    setattr(risk_state, field, value)
    with pytest.raises(RiskError):
        evaluate_risk(
            requested_allocation=0.2, current_allocation=0.0, equity=10_000,
            state=risk_state, observed_at=NOW, now=NOW,
        )
