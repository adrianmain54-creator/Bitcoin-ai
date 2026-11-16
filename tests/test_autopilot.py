from datetime import datetime, timezone, timedelta

import pytest

from bitcoin_ai.autopilot import run_paper_cycle
from bitcoin_ai.paper_trading import PaperAccount
from bitcoin_ai.risk import RiskLimits, new_risk_state


NOW = datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)


def prices_trending_up(count=48):
    return [100.0 + i for i in range(count)]


def test_cycle_runs_strategy_through_risk_and_paper_execution():
    account = PaperAccount(cash=10_000, max_allocation=0.20)
    state = new_risk_state(10_000, NOW)
    result = run_paper_cycle(
        closes=prices_trending_up(), account=account, risk_state=state,
        observed_at=NOW, now=NOW,
    )
    assert result.signal.action == "buy"
    assert result.risk.allowed
    assert result.execution["side"] == "buy"
    assert account.btc > 0
    assert result.equity < 10_000
    assert state.last_trade_at == NOW


def test_stale_data_never_trades():
    account = PaperAccount(cash=10_000)
    state = new_risk_state(10_000, NOW)
    result = run_paper_cycle(
        closes=prices_trending_up(), account=account, risk_state=state,
        observed_at=NOW - timedelta(minutes=10), now=NOW,
    )
    assert not result.risk.allowed
    assert result.execution is None
    assert account.btc == 0


def test_daily_loss_halt_de_risks_existing_paper_position():
    account = PaperAccount(cash=0, btc=100.0)
    state = new_risk_state(10_000, NOW)
    result = run_paper_cycle(
        closes=[90.0] * 48, account=account,
        risk_state=state, observed_at=NOW, now=NOW,
        limits=RiskLimits(max_daily_loss_pct=0.02),
    )
    assert result.risk.halted
    assert result.execution is not None
    assert result.execution["side"] == "sell"
    assert account.btc == pytest.approx(0)


def test_invalid_history_does_not_mutate_account():
    account = PaperAccount(cash=10_000)
    state = new_risk_state(10_000, NOW)
    with pytest.raises(ValueError):
        run_paper_cycle(
            closes=[100.0], account=account, risk_state=state,
            observed_at=NOW, now=NOW,
        )
    assert account.cash == 10_000
    assert account.btc == 0


def test_future_dated_data_cannot_trigger_emergency_de_risk():
    account = PaperAccount(cash=5_000, btc=0.05)
    state = new_risk_state(account.equity(100_000), NOW)
    state.halted = True
    cash_before, btc_before = account.cash, account.btc
    result = run_paper_cycle(
        closes=[100_000.0] * 48, account=account, risk_state=state,
        observed_at=NOW + timedelta(seconds=1), now=NOW,
    )
    assert not result.risk.allowed
    assert not result.risk.halted
    assert result.execution is None
    assert (account.cash, account.btc) == (cash_before, btc_before)


@pytest.mark.parametrize("closes", [[], [float("nan")], [float("inf")], [True], ["100"]])
def test_invalid_latest_close_is_rejected_before_account_access(closes):
    account = PaperAccount(cash=10_000)
    state = new_risk_state(10_000, NOW)
    with pytest.raises(ValueError, match="latest close"):
        run_paper_cycle(
            closes=closes, account=account, risk_state=state,
            observed_at=NOW, now=NOW,
        )
    assert account.cash == 10_000
    assert account.btc == 0
