import json
from datetime import datetime, timedelta, timezone

from bitcoin_ai import research_plan_cli
from bitcoin_ai.research_scheduler import GENESIS_HASH, _event_digest


class FakeIngestor:
    def __init__(self, report):
        self.report = report
        self.calls = []

    def fetch_and_prepare(self, **kwargs):
        self.calls.append(kwargs)
        return self.report


def _fixtures():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        {"timestamp": (start + timedelta(minutes=i)).isoformat(),
         "open": 100+i, "high": 102+i, "low": 99+i, "close": 101+i, "volume": 1}
        for i in range(81)
    ]
    fingerprint = "a" * 64
    report = {
        "status": "prepared", "dataset_fingerprint": fingerprint,
        "holdout_status": "not_assessed",
        "dataset": {
            "symbol": "BTC-USDT", "interval": "5m", "row_count": len(bars),
            "canonical_bars": bars,
            "cross_source": {
                "status": "cross_checked",
                "sources": ["binance", "coinbase", "kraken"],
            },
        },
        "provenance": {"dataset_fingerprint": fingerprint},
    }
    task = {
        "event_type": "task_queued", "task_id": "queued-task-1",
        "status": "queued", "execution_authority": "none",
        "source_candidate": "sma:12",
        "candidate": {"family": "momentum", "lookback": 5},
    }
    event_hash = _event_digest(task)
    queue = {
        "schema_version": 1,
        "events": [{"event": task, "previous_hash": GENESIS_HASH, "event_hash": event_hash}],
    }
    return report, queue, task


def test_build_plan_report_is_plan_only_and_uses_exact_queued_task(tmp_path):
    report, queue, task = _fixtures()
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    client = FakeIngestor(report)
    result = research_plan_cli.build_plan_report(
        queue_path=queue_path, task_id=task["task_id"], code_revision="abc123",
        source_family="sma", source_lookback=12, train_bars=50, test_bars=10,
        ingestor=client,
    )
    assert result["status"] == "plan_prepared"
    assert result["execution_authority"] == "none"
    assert result["side_effects"] == []
    assert result["plan"]["task_id"] == task["task_id"]
    assert result["plan"]["dataset_fingerprint"] == "a" * 64
    assert client.calls[0]["interval"] == "5m"
    assert "bars" not in result
    assert "holdout" in " ".join(result["limitations"]).lower()


def test_unknown_task_fails_before_market_fetch(tmp_path):
    report, queue, _ = _fixtures()
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    client = FakeIngestor(report)
    try:
        research_plan_cli.build_plan_report(
            queue_path=queue_path, task_id="not-in-queue", code_revision="abc123",
            source_family="sma", source_lookback=12, ingestor=client,
        )
    except ValueError as exc:
        assert "exactly one task" in str(exc)
    else:
        raise AssertionError("unknown tasks must be rejected")
    assert client.calls == []


def test_cli_writes_json_plan(monkeypatch, tmp_path):
    report, queue, task = _fixtures()
    queue_path = tmp_path / "queue.json"
    queue_path.write_text(json.dumps(queue), encoding="utf-8")
    output = tmp_path / "plan.json"
    client = FakeIngestor(report)
    monkeypatch.setattr(research_plan_cli, "PublicResearchMarketIngestor", lambda: client)
    monkeypatch.setattr(
        "sys.argv",
        ["research-plan", "--queue", str(queue_path), "--task-id", task["task_id"],
         "--code-revision", "abc123", "--source-family", "sma",
         "--source-lookback", "12", "--output", str(output)],
    )
    assert research_plan_cli.main() == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["status"] == "plan_prepared"
    assert payload["execution_authority"] == "none"
