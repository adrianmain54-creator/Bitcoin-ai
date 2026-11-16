from datetime import datetime, timezone
import json

import pytest

from bitcoin_ai.paper_trading import PaperAccount
from bitcoin_ai.risk import new_risk_state
from bitcoin_ai.state_store import PaperStateStore, StateStoreError


NOW = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_round_trip_persists_account_trades_and_risk(tmp_path):
    account = PaperAccount(cash=8_000, btc=0.04)
    account.trades.append({"side": "buy", "timestamp": NOW.isoformat()})
    risk = new_risk_state(10_000, NOW)
    risk.last_trade_at = NOW
    risk.halted = True
    store = PaperStateStore(tmp_path / "state.json")
    store.save(account, risk)
    loaded_account, loaded_risk = store.load()
    assert loaded_account.cash == account.cash
    assert loaded_account.btc == account.btc
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
