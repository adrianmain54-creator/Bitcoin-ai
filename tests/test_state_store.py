from datetime import datetime, timezone
import json

import pytest

from bitcoin_ai.paper_trading import PaperAccount
from bitcoin_ai.risk import new_risk_state
from bitcoin_ai.state_store import PaperStateStore, StateStoreError


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_round_trip_persists_account_trades_and_risk(tmp_path):
    account = PaperAccount(cash=8_000, btc=0.04, initial_cash=10_000)
    account.trades.append({"side": "buy", "timestamp": NOW.isoformat()})
    risk = new_risk_state(10_000, NOW)
    risk.last_trade_at = NOW
    risk.halted = True
    store = PaperStateStore(tmp_path / "state.json")
    store.save(account, risk)
    loaded_account, loaded_risk = store.load()
    assert loaded_account.cash == account.cash
    assert loaded_account.btc == account.btc
    assert loaded_account.initial_cash == 10_000
    assert loaded_account.trades == account.trades
    assert loaded_risk.utc_day == risk.utc_day
    assert loaded_risk.last_trade_at == NOW
    assert loaded_risk.halted is True


def test_corrupt_or_unknown_state_fails_closed(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"version": 999}), encoding="utf-8")
    with pytest.raises(StateStoreError):
        PaperStateStore(path).load()


def test_non_finite_state_cannot_be_saved(tmp_path):
    account = PaperAccount()
    account.cash = float("nan")
    store = PaperStateStore(tmp_path / "state.json")
    with pytest.raises(StateStoreError):
        store.save(account, new_risk_state(10_000, NOW))
    assert not store.path.exists()


def test_non_object_document_fails_closed(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("[]", encoding="utf-8")
    with pytest.raises(StateStoreError):
        PaperStateStore(path).load()


@pytest.mark.parametrize("trades", [None, {}, ["not-an-event"], [{"bad": float("nan")} ]])
def test_invalid_trade_history_fails_closed(tmp_path, trades):
    path = tmp_path / "state.json"
    payload = {
        "version": 1,
        "account": {
            "cash": 10_000, "btc": 0, "fee_bps": 10,
            "slippage_bps": 5, "max_allocation": 0.25,
            "trades": trades,
        },
        "risk": {
            "utc_day": "2026-01-01", "day_start_equity": 10_000,
            "peak_equity": 10_000, "last_trade_at": None, "halted": False,
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StateStoreError):
        PaperStateStore(path).load()


def test_invalid_risk_day_fails_closed(tmp_path):
    path = tmp_path / "state.json"
    store = PaperStateStore(path)
    store.save(PaperAccount(), new_risk_state(10_000, NOW))
    payload = json.loads(path.read_text())
    payload["risk"]["utc_day"] = "not-a-date"
    path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(StateStoreError):
        store.load()


def test_invalid_mutated_trade_history_cannot_be_saved(tmp_path):
    account = PaperAccount()
    account.trades = ["not-an-event"]
    with pytest.raises(StateStoreError):
        PaperStateStore(tmp_path / "state.json").save(
            account, new_risk_state(10_000, NOW)
        )


def test_mutated_invalid_account_cannot_be_saved(tmp_path):
    account = PaperAccount()
    account.cash = "not-money"
    with pytest.raises(StateStoreError):
        PaperStateStore(tmp_path / "state.json").save(
            account, new_risk_state(10_000, NOW)
        )
