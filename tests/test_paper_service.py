from datetime import datetime, timezone
import json

import pytest

from bitcoin_ai.market_data import MarketDataError
from bitcoin_ai.paper_service import PaperService
from bitcoin_ai.forward_validation import GENESIS_HASH, observation_digest
from bitcoin_ai.state_store import StateStoreError


NOW = datetime(2026, 1, 1, 0, 10, tzinfo=timezone.utc)


class FakeClient:
    def __init__(self, closes=None, observed_at=NOW):
        self.closes = closes or [100.0 + i for i in range(100)]
        self.observed_at = observed_at
        self.cross_check_calls = 0
    def completed_closes(self, **kwargs):
        raise AssertionError("paper trading must not use a single exchange feed")
    def cross_checked_three_source_candle_history(self, **kwargs):
        self.cross_check_calls += 1
        return {"closes": self.closes, "latest": self.observed_at,
                "audit": {"status": "three_source_cross_checked"}}


def test_first_cycle_initializes_then_persists_state(tmp_path):
    path = tmp_path / "paper.json"
    service = PaperService(state_path=str(path), client=FakeClient(),
                           clock=lambda: NOW)
    report = service.run_once()
    assert report["mode"] == "paper"
    assert service.client.cross_check_calls == 1
    assert path.exists()
    before = json.loads(path.read_text())
    duplicate = service.run_once()
    after = json.loads(path.read_text())
    assert before["version"] == after["version"] == 1
    assert duplicate["status"] == "duplicate_or_stale_observation"
    assert len(after["account"]["paper_observations"]) == 1
    assert report["forward_evidence"]["status"] == "insufficient_evidence"


def test_corrupt_state_is_not_silently_reset(tmp_path):
    path = tmp_path / "paper.json"
    path.write_text("{broken", encoding="utf-8")
    service = PaperService(state_path=str(path), client=FakeClient(),
                           clock=lambda: NOW)
    with pytest.raises(StateStoreError):
        service.run_once()


def test_market_data_failure_does_not_create_account_state(tmp_path):
    class BrokenClient:
        def cross_checked_three_source_candle_history(self, **kwargs):
            raise MarketDataError("Coinbase offline; three-source check unavailable")
    path = tmp_path / "paper.json"
    service = PaperService(state_path=str(path), client=BrokenClient(),
                           clock=lambda: NOW)
    with pytest.raises(MarketDataError):
        service.run_once()
    assert not path.exists()

def test_forward_observations_survive_service_restart(tmp_path):
    path = tmp_path / "paper.json"
    first = PaperService(state_path=str(path), client=FakeClient(),
                         clock=lambda: NOW)
    first.run_once()

    later = NOW.replace(minute=11)
    second = PaperService(
        state_path=str(path),
        client=FakeClient(observed_at=later),
        clock=lambda: later,
    )
    report = second.run_once()
    persisted = json.loads(path.read_text(encoding="utf-8"))
    observations = persisted["account"]["paper_observations"]
    assert len(observations) == 2
    assert observations[0]["observed_at"] < observations[1]["observed_at"]
    assert report["forward_evidence"]["observations"] == 2




def test_tampered_forward_history_stops_next_paper_cycle(tmp_path):
    path = tmp_path / "paper.json"
    first = PaperService(state_path=str(path), client=FakeClient(),
                         clock=lambda: NOW)
    first.run_once()
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["account"]["paper_observations"][0]["equity"] += 50
    path.write_text(json.dumps(payload), encoding="utf-8")

    later = NOW.replace(minute=11)
    second = PaperService(
        state_path=str(path),
        client=FakeClient(observed_at=later),
        clock=lambda: later,
    )
    with pytest.raises(ValueError, match="hash verification failed"):
        second.run_once()



def test_semantically_invalid_but_rehashed_history_fails_before_paper_cycle(tmp_path):
    path = tmp_path / "paper.json"
    first = PaperService(state_path=str(path), client=FakeClient(),
                         clock=lambda: NOW)
    first.run_once()
    later = NOW.replace(minute=11)
    second = PaperService(
        state_path=str(path),
        client=FakeClient(observed_at=later),
        clock=lambda: later,
    )
    second.run_once()

    payload = json.loads(path.read_text(encoding="utf-8"))
    observations = payload["account"]["paper_observations"]
    observations[0]["observed_at"], observations[1]["observed_at"] = (
        observations[1]["observed_at"], observations[0]["observed_at"]
    )
    previous = GENESIS_HASH
    for item in observations:
        item["previous_hash"] = previous
        item.pop("observation_hash", None)
        item["observation_hash"] = observation_digest(item)
        previous = item["observation_hash"]
    path.write_text(json.dumps(payload), encoding="utf-8")
    before = path.read_text(encoding="utf-8")

    later_again = NOW.replace(minute=12)
    service = PaperService(
        state_path=str(path),
        client=FakeClient(observed_at=later_again),
        clock=lambda: later_again,
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        service.run_once()
    assert path.read_text(encoding="utf-8") == before
