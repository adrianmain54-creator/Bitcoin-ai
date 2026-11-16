from datetime import datetime, timezone
import json

import pytest

from bitcoin_ai.market_data import MarketDataError
from bitcoin_ai.paper_service import PaperService
from bitcoin_ai.state_store import StateStoreError


NOW = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, closes=None, observed_at=NOW):
        self.closes = closes or [100.0 + i for i in range(100)]
        self.observed_at = observed_at
    def completed_closes(self, **kwargs):
        return self.closes, self.observed_at


def test_first_cycle_initializes_then_persists_state(tmp_path):
    path = tmp_path / "paper.json"
    service = PaperService(state_path=str(path), client=FakeClient(),
                           clock=lambda: NOW)
    report = service.run_once()
    assert report["mode"] == "paper"
    assert path.exists()
    before = json.loads(path.read_text())
    service.run_once()
    after = json.loads(path.read_text())
    assert before["version"] == after["version"] == 1


def test_corrupt_state_is_not_silently_reset(tmp_path):
    path = tmp_path / "paper.json"
    path.write_text("{broken", encoding="utf-8")
    service = PaperService(state_path=str(path), client=FakeClient(),
                           clock=lambda: NOW)
    with pytest.raises(StateStoreError):
        service.run_once()


def test_market_data_failure_does_not_create_account_state(tmp_path):
    class BrokenClient:
        def completed_closes(self, **kwargs):
            raise MarketDataError("offline")
    path = tmp_path / "paper.json"
    service = PaperService(state_path=str(path), client=BrokenClient(),
                           clock=lambda: NOW)
    with pytest.raises(MarketDataError):
        service.run_once()
    assert not path.exists()
