from datetime import datetime, timezone

import pytest

from bitcoin_ai import public_market_cycle


NOW = datetime(2026, 11, 19, 0, 0, tzinfo=timezone.utc)


class FakeIngestor:
    def __init__(self, report=None, error=None):
        self.report = report
        self.error = error
        self.calls = []

    def fetch_and_prepare(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        return self.report


def prepared_report():
    return {
        "status": "prepared",
        "dataset_fingerprint": "a" * 64,
        "dataset": {
            "symbol": "BTC-USDT",
            "interval": "5m",
            "cross_source": {
                "status": "cross_checked",
                "source_count": 3,
                "sources": ["binance", "coinbase", "kraken"],
                "aligned_candles": 300,
            },
        },
        "provenance": {
            "row_count": 300,
            "sources": ["binance", "coinbase", "kraken"],
        },
        "holdout_status": "not_assessed",
    }


def test_public_market_cycle_fetches_then_invokes_research_cycle(monkeypatch, tmp_path):
    ingestor = FakeIngestor(prepared_report())
    observed = {}

    def run(task, dataset, **kwargs):
        observed["task"] = task
        observed["dataset"] = dataset
        observed["kwargs"] = kwargs
        return {
            "status": "rejected_or_insufficient",
            "execution_authority": "none",
            "evidence_review": {"status": "rejected_or_insufficient"},
        }

    monkeypatch.setattr(public_market_cycle, "run_scheduled_research_cycle", run)
    task = {"event_type": "task_queued", "task_id": "queued-1"}
    result = public_market_cycle.run_public_market_research_cycle(
        task,
        code_revision="commit-sha",
        source_strategy_definition={"family": "sma", "lookback": 12},
        candidate_registry_path=tmp_path / "registry.json",
        holdout_ledger_path=tmp_path / "holdouts.json",
        registered_at="2026-11-19T00:00:00+00:00",
        now=NOW,
        ingestor=ingestor,
    )

    assert ingestor.calls == [{"interval": "5m", "limit": 300, "now": NOW}]
    assert observed["task"] is task
    assert observed["dataset"] is ingestor.report
    assert observed["kwargs"]["train_bars"] == 99
    assert observed["kwargs"]["test_bars"] == 20
    assert result["market_data"]["sources"] == ["binance", "coinbase", "kraken"]
    assert result["market_data"]["holdout_status"] == "not_assessed"
    assert result["execution_authority"] == "none"
    assert result["status"] == "rejected_or_insufficient"


def test_public_market_failure_aborts_before_any_research(monkeypatch, tmp_path):
    ingestor = FakeIngestor(error=RuntimeError("simulated provider outage"))
    monkeypatch.setattr(
        public_market_cycle, "run_scheduled_research_cycle",
        lambda *args, **kwargs: pytest.fail("research must not run without validated market data"),
    )

    with pytest.raises(RuntimeError, match="provider outage"):
        public_market_cycle.run_public_market_research_cycle(
            {"event_type": "task_queued"},
            code_revision="commit-sha",
            source_strategy_definition={"family": "sma", "lookback": 12},
            candidate_registry_path=tmp_path / "registry.json",
            holdout_ledger_path=tmp_path / "holdouts.json",
            registered_at="2026-11-19T00:00:00+00:00",
            ingestor=ingestor,
        )
