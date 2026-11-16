import pytest

from bitcoin_ai.paper_trading import PaperAccount, PaperTradingError


def test_buy_respects_allocation_cap_and_costs():
    account = PaperAccount(cash=10_000, max_allocation=0.2, fee_bps=10, slippage_bps=5)
    event = account.rebalance(1.0, 50_000)
    assert event["mode"] == "paper"
    assert event["side"] == "buy"
    assert account.btc > 0
    assert account.cash >= 0
    assert account.btc * 50_000 <= account.equity(50_000) * 0.201


def test_sell_to_cash_and_never_go_short():
    account = PaperAccount(cash=0, btc=0.1, max_allocation=1)
    event = account.rebalance(0, 40_000)
    assert event["side"] == "sell"
    assert account.btc == pytest.approx(0)
    assert account.cash > 0


def test_hold_when_already_at_target():
    account = PaperAccount(cash=5_000, btc=0.1, max_allocation=1)
    event = account.rebalance(0.5, 50_000)
    assert event["side"] == "hold"
    assert account.trades == []


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf")])
def test_invalid_price_rejected(price):
    with pytest.raises(PaperTradingError):
        PaperAccount().rebalance(0.1, price)


@pytest.mark.parametrize("allocation", [-0.1, 1.1, float("nan")])
def test_invalid_target_rejected(allocation):
    with pytest.raises(PaperTradingError):
        PaperAccount().rebalance(allocation, 50_000)


def test_invalid_account_risk_configuration_rejected():
    with pytest.raises(PaperTradingError):
        PaperAccount(max_allocation=1.5)

def test_non_numeric_target_rejected():
    with pytest.raises(PaperTradingError):
        PaperAccount().rebalance("0.2", 50_000)


@pytest.mark.parametrize("kwargs", [
    {"cash": "100"},
    {"btc": True},
    {"fee_bps": "10"},
    {"slippage_bps": float("nan")},
    {"max_allocation": True},
    {"trades": ["not-an-event"]},
])
def test_invalid_account_configuration_types_rejected(kwargs):
    with pytest.raises(PaperTradingError):
        PaperAccount(**kwargs)


@pytest.mark.parametrize("field,value", [
    ("cash", float("nan")),
    ("btc", -0.1),
    ("fee_bps", float("inf")),
    ("slippage_bps", -1),
    ("max_allocation", 1.5),
    ("trades", [None]),
])
def test_mutated_account_state_is_rejected_before_valuation(field, value):
    account = PaperAccount()
    setattr(account, field, value)
    with pytest.raises(PaperTradingError):
        account.equity(50_000)
