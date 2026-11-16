from datetime import datetime, timezone

import pytest

from bitcoin_ai.paper_trading import PaperAccount, PaperTradingError
from bitcoin_ai.performance import build_performance_report


def test_report_marks_account_to_market_and_summarizes_costs():
    account = PaperAccount(cash=8_000, btc=0.04)
    account.trades = [
        {"equity_after": 9_900, "fee_paid": 10},
        {"equity_after": 10_100, "fee_paid": 12},
    ]
    report = build_performance_report(account, price=50_000, starting_cash=10_000)
    assert report["equity"] == pytest.approx(10_000)
    assert report["net_pnl"] == pytest.approx(0)
    assert report["return_pct"] == pytest.approx(0)
    assert report["exposure_pct"] == pytest.approx(20)
    assert report["cumulative_simulated_fees"] == pytest.approx(22)
    assert report["trade_count"] == 2
    assert report["observed_checkpoint_max_drawdown_pct"] == pytest.approx(1)


def test_report_uses_only_recorded_checkpoints_for_drawdown():
    account = PaperAccount(cash=9_000, btc=0.02)
    account.trades = [{"equity_after": 9_000, "fee_paid": 1}]
    report = build_performance_report(account, price=50_000, starting_cash=10_000)
    assert report["observed_checkpoint_max_drawdown_pct"] == pytest.approx(10)
    assert "not a continuous" in report["drawdown_note"]


@pytest.mark.parametrize("price,starting_cash", [
    (0, 10_000), (float("nan"), 10_000), (50_000, 0), (50_000, float("inf")),
    (True, 10_000), (50_000, False),
])
def test_report_rejects_invalid_inputs(price, starting_cash):
    with pytest.raises(PaperTradingError):
        build_performance_report(PaperAccount(), price=price, starting_cash=starting_cash)


def test_report_rejects_malformed_trade_checkpoint():
    account = PaperAccount()
    account.trades = [{"equity_after": float("nan"), "fee_paid": 0}]
    with pytest.raises(PaperTradingError):
        build_performance_report(account, price=50_000, starting_cash=10_000)
