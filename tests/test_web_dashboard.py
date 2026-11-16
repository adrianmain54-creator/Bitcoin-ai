from datetime import datetime, timezone

import pytest

from bitcoin_ai.paper_trading import PaperAccount
from bitcoin_ai.risk import new_risk_state
from bitcoin_ai.state_store import PaperStateStore
from bitcoin_ai.web_dashboard import build_dashboard_status, serve_dashboard


class FakeFeed:
    def completed_closes(self, **kwargs):
        return [100.0 + i for i in range(100)], datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_dashboard_status_is_read_only_and_contains_signal(tmp_path):
    path = tmp_path / "state.json"
    account = PaperAccount(cash=9_000, btc=0.01)
    risk = new_risk_state(account.equity(100_000), datetime(2026, 1, 1, tzinfo=timezone.utc))
    PaperStateStore(path).save(account, risk)
    before = path.read_bytes()
    result = build_dashboard_status(state_path=str(path), client=FakeFeed())
    assert result["execution_mode"].startswith("PAPER ONLY")
    assert result["signal"]["action"] in {"buy", "sell", "hold"}
    assert result["equity"] > 0
    assert path.read_bytes() == before


def test_dashboard_refuses_non_localhost_binding():
    with pytest.raises(ValueError, match="localhost"):
        serve_dashboard(state_path="paper.json", host="0.0.0.0")
