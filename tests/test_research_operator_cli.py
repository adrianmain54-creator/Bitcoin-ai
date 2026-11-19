import json
import sys
from pathlib import Path

import pytest

import bitcoin_ai.cli as cli
from bitcoin_ai.research_ingestion import compute_research_dataset_fingerprint


def test_research_fetch_writes_validated_dataset_report(monkeypatch, tmp_path, capsys):
    report = {
        "status": "prepared",
        "dataset_fingerprint": "a" * 64,
        "dataset": {"row_count": 100, "cross_source": {"status": "cross_checked"}},
        "provenance": {"source_count": 3},
        "holdout_status": "not_assessed",
    }

    class FakeIngestor:
        def fetch_and_prepare(self, **kwargs):
            assert kwargs == {
                "interval": "5m", "limit": 80,
                "max_age_seconds": 900, "max_price_deviation": 0.01,
            }
            return report

    monkeypatch.setattr(cli, "PublicResearchMarketIngestor", FakeIngestor)
    output = tmp_path / "data" / "dataset.json"
    monkeypatch.setattr(sys, "argv", [
        "bitcoin-ai", "research-fetch", "--interval", "5m", "--limit", "80",
        "--output", str(output),
    ])
    cli.main()
    assert json.loads(output.read_text()) == report
    assert "Holdout status remains not_assessed" in capsys.readouterr().out


def test_research_run_uses_validated_queue_and_persists_report(monkeypatch, tmp_path):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps({"status": "prepared"}))
    queue_task = {
        "task_id": "task-123", "event_type": "task_queued",
        "status": "queued", "execution_authority": "none",
        "source_candidate": "sma:12",
        "candidate": {"family": "momentum", "lookback": 5},
    }
    monkeypatch.setattr(cli, "load_research_queue", lambda path: {
        "status": "valid", "tasks": [queue_task],
    })
    prepared = {
        "status": "plan_prepared", "plan_id": "plan-abc",
        "plan": {
            "dataset_fingerprint": "b" * 64,
            "test_window": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"},
            "code_revision": "deadbeef",
            "candidates": {
                "proposal": {"family": "momentum", "lookback": 5},
                "unchanged_source": {"family": "sma", "lookback": 12},
                "cash": {"family": "cash", "lookback": 2},
            },
        },
    }
    captured = {}

    def fake_prepare(task, dataset, **kwargs):
        captured["task"] = task
        captured["dataset"] = dataset
        captured["prepare_kwargs"] = kwargs
        return prepared

    def fake_run(plan, **kwargs):
        captured["plan"] = plan
        captured["run_kwargs"] = kwargs
        return {"status": "completed_research_only", "execution_authority": "none"}

    monkeypatch.setattr(cli, "prepare_scheduled_experiment", fake_prepare)
    monkeypatch.setattr(cli, "run_preregistered_experiment", fake_run)
    output = tmp_path / "reports" / "experiment.json"
    monkeypatch.setattr(sys, "argv", [
        "bitcoin-ai", "research-run",
        "--dataset-report", str(dataset_path),
        "--queue", str(tmp_path / "queue.json"),
        "--task-id", "task-123",
        "--source-family", "sma", "--source-lookback", "12",
        "--train-bars", "50", "--test-bars", "10",
        "--candidate-ledger", str(tmp_path / "candidate.json"),
        "--experiment-ledger", str(tmp_path / "holdout.json"),
        "--code-revision", "deadbeef",
        "--bootstrap-trials", "200",
        "--output", str(output),
    ])
    cli.main()
    saved = json.loads(output.read_text())
    assert saved["plan_id"] == "plan-abc"
    assert saved["candidate_names"] == {
        "proposal": "momentum:5", "source": "sma:12", "cash": "cash:2",
    }
    assert captured["prepare_kwargs"]["source_strategy_definition"] == {
        "family": "sma", "lookback": 12,
    }
    assert captured["run_kwargs"]["bootstrap_trials"] == 200
    assert captured["run_kwargs"]["candidate_registry_path"] == Path(tmp_path / "candidate.json")


def test_research_run_rejects_missing_task_before_preregistration(monkeypatch, tmp_path):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("{}")
    monkeypatch.setattr(cli, "load_research_queue", lambda path: {"tasks": []})
    monkeypatch.setattr(
        cli, "run_preregistered_experiment",
        lambda *args, **kwargs: pytest.fail("runner must not execute without a queued task"),
    )
    monkeypatch.setattr(sys, "argv", [
        "bitcoin-ai", "research-run",
        "--dataset-report", str(dataset_path),
        "--queue", str(tmp_path / "queue.json"),
        "--task-id", "missing",
        "--source-family", "sma", "--source-lookback", "12",
        "--candidate-ledger", str(tmp_path / "candidate.json"),
        "--experiment-ledger", str(tmp_path / "holdout.json"),
        "--code-revision", "deadbeef",
        "--output", str(tmp_path / "out.json"),
    ])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1


def test_research_run_rejects_source_label_mismatch(monkeypatch, tmp_path):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text("{}")
    task = {
        "task_id": "task-123", "source_candidate": "agent_council:48",
    }
    monkeypatch.setattr(cli, "load_research_queue", lambda path: {"tasks": [task]})
    monkeypatch.setattr(
        cli, "prepare_scheduled_experiment",
        lambda *args, **kwargs: pytest.fail("plan must not be prepared with a mismatched source"),
    )
    monkeypatch.setattr(sys, "argv", [
        "bitcoin-ai", "research-run",
        "--dataset-report", str(dataset_path),
        "--queue", str(tmp_path / "queue.json"),
        "--task-id", "task-123",
        "--source-family", "sma", "--source-lookback", "12",
        "--candidate-ledger", str(tmp_path / "candidate.json"),
        "--experiment-ledger", str(tmp_path / "holdout.json"),
        "--code-revision", "deadbeef",
        "--output", str(tmp_path / "out.json"),
    ])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1



def _schedule_inputs(tmp_path, *, anomalous=False):
    from datetime import datetime, timedelta, timezone

    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = []
    for index in range(30):
        high = 500.0 if anomalous and index == 29 else 101.0
        bars.append({
            "timestamp": (start + timedelta(minutes=5 * index)).isoformat(),
            "open": 100.0, "high": high, "low": 99.0,
            "close": 100.0, "volume": 10.0,
        })
    dataset_core = {
        "schema_version": 1, "symbol": "BTC-USDT", "interval": "5m",
        "start": bars[0]["timestamp"], "end": bars[-1]["timestamp"],
        "row_count": len(bars), "canonical_bars": bars,
        "cross_source": {
            "status": "cross_checked",
            "sources": ["binance", "coinbase", "kraken"],
            "aligned_candles": 30, "divergent_candles": 0,
        },
    }
    fingerprint = compute_research_dataset_fingerprint(dataset_core)
    dataset = {
        "status": "prepared", "holdout_status": "not_assessed",
        "dataset_fingerprint": fingerprint,
        "provenance": {"dataset_fingerprint": fingerprint},
        "dataset": dataset_core,
    }
    previous = {
        "strategy_improvement_proposals": {
            "sma:12": {
                "status": "hypotheses_only",
                "proposals": [{
                    "candidate": {"family": "momentum", "lookback": 5},
                    "hypothesis": "Test a distinct candidate.",
                    "trigger": "drawdown_threshold_exceeded",
                }],
            },
        },
    }
    dataset_path = tmp_path / "dataset.json"
    previous_path = tmp_path / "previous.json"
    dataset_path.write_text(json.dumps(dataset))
    previous_path.write_text(json.dumps(previous))
    return dataset_path, previous_path


def test_research_schedule_builds_context_and_queues_only_distinct_hypotheses(monkeypatch, tmp_path):
    from bitcoin_ai.research_scheduler import load_research_queue

    dataset_path, previous_path = _schedule_inputs(tmp_path)
    queue_path = tmp_path / "queue.json"
    monkeypatch.setattr(sys, "argv", [
        "bitcoin-ai", "research-schedule",
        "--dataset-report", str(dataset_path),
        "--previous-research-report", str(previous_path),
        "--source-candidate", "sma:12",
        "--queue", str(queue_path),
        "--observed-at", "2026-01-02T00:00:00+00:00",
        "--json",
    ])
    cli.main()
    loaded = load_research_queue(queue_path)
    assert loaded["task_count"] == 1
    assert loaded["tasks"][0]["candidate"] == {"family": "momentum", "lookback": 5}
    assert loaded["tasks"][0]["source_candidate"] == "sma:12"


def test_research_schedule_abstains_on_ohlcv_anomaly(monkeypatch, tmp_path, capsys):
    dataset_path, previous_path = _schedule_inputs(tmp_path, anomalous=True)
    queue_path = tmp_path / "queue.json"
    monkeypatch.setattr(sys, "argv", [
        "bitcoin-ai", "research-schedule",
        "--dataset-report", str(dataset_path),
        "--previous-research-report", str(previous_path),
        "--source-candidate", "sma:12",
        "--queue", str(queue_path),
    ])
    cli.main()
    output = capsys.readouterr().out
    assert "abstained" in output
    assert not queue_path.exists()



def test_research_run_auto_sizes_three_oos_folds_for_actual_row_count(monkeypatch, tmp_path):
    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(json.dumps({
        "dataset": {"canonical_bars": [{} for _ in range(299)]},
    }))
    task = {
        "task_id": "task-123", "source_candidate": "sma:12",
    }
    monkeypatch.setattr(cli, "load_research_queue", lambda path: {"tasks": [task]})
    prepared = {
        "plan_id": "plan-auto",
        "plan": {
            "dataset_fingerprint": "c" * 64,
            "test_window": {"start": "2026-01-01T00:00:00+00:00", "end": "2026-02-01T00:00:00+00:00"},
            "code_revision": "deadbeef",
            "candidates": {
                "proposal": {"family": "momentum", "lookback": 5},
                "unchanged_source": {"family": "sma", "lookback": 12},
                "cash": {"family": "cash", "lookback": 2},
            },
        },
    }
    captured = {}

    def fake_prepare(task, dataset, **kwargs):
        captured.update(kwargs)
        return prepared

    monkeypatch.setattr(cli, "prepare_scheduled_experiment", fake_prepare)
    monkeypatch.setattr(
        cli, "run_preregistered_experiment",
        lambda *args, **kwargs: {"status": "completed_research_only"},
    )
    output = tmp_path / "experiment.json"
    monkeypatch.setattr(sys, "argv", [
        "bitcoin-ai", "research-run",
        "--dataset-report", str(dataset_path),
        "--queue", str(tmp_path / "queue.json"),
        "--task-id", "task-123",
        "--source-family", "sma", "--source-lookback", "12",
        "--candidate-ledger", str(tmp_path / "candidate.json"),
        "--experiment-ledger", str(tmp_path / "holdout.json"),
        "--code-revision", "deadbeef",
        "--output", str(output),
    ])
    cli.main()
    assert captured["train_bars"] == 118
    assert captured["test_bars"] == 60



def test_research_schedule_rejects_dataset_content_tampering(monkeypatch, tmp_path):
    dataset_path, previous_path = _schedule_inputs(tmp_path)
    dataset = json.loads(dataset_path.read_text())
    dataset["dataset"]["canonical_bars"][10]["volume"] += 1.0
    dataset_path.write_text(json.dumps(dataset))
    queue_path = tmp_path / "queue.json"
    monkeypatch.setattr(sys, "argv", [
        "bitcoin-ai", "research-schedule",
        "--dataset-report", str(dataset_path),
        "--previous-research-report", str(previous_path),
        "--source-candidate", "sma:12",
        "--queue", str(queue_path),
    ])
    with pytest.raises(SystemExit) as exc:
        cli.main()
    assert exc.value.code == 1
    assert not queue_path.exists()
