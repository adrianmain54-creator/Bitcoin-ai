import json

import pytest

from bitcoin_ai.research_scheduler import (
    ResearchSchedulerError,
    load_research_queue,
    scan_and_queue_research,
)


def clean_context(**overrides):
    context = {
        "status": "classified",
        "posture": "research_only",
        "regime": "uptrend_low_volatility",
        "exchange_sources": ["binance", "kraken", "coinbase"],
        "aligned_candles": 100,
        "anomaly_alert_count": 0,
        "risk_flags": [],
    }
    context.update(overrides)
    return context


def proposal_report():
    return {
        "status": "hypotheses_only",
        "proposals": [
            {
                "candidate": {"family": "agent_council_25", "lookback": 48},
                "hypothesis": "A lower cap may reduce drawdown.",
                "trigger": "drawdown_threshold_exceeded",
            },
            {
                "candidate": {"family": "cash", "lookback": 2},
                "hypothesis": "Cash is the defensive baseline.",
                "trigger": "drawdown_threshold_exceeded",
            },
        ],
    }


def scan(path, **overrides):
    args = {
        "observed_at": "2026-11-18T12:00:00+00:00",
        "market_context": clean_context(),
        "proposal_report": proposal_report(),
        "source_candidate": "agent_council:48",
    }
    args.update(overrides)
    return scan_and_queue_research(path, **args)


def test_clean_market_context_queues_hash_chained_tasks(tmp_path):
    path = tmp_path / "queue.json"
    report = scan(path)
    assert report["status"] == "queued"
    assert report["queued_count"] == 2
    assert report["queue_mutated"] is True
    loaded = load_research_queue(path)
    assert loaded["integrity"] == "valid_hash_chain"
    assert loaded["task_count"] == 2
    assert all(task["execution_authority"] == "none" for task in loaded["tasks"])
    assert all(task["status"] == "queued" for task in loaded["tasks"])


def test_repeated_identical_scan_is_idempotent(tmp_path):
    path = tmp_path / "queue.json"
    first = scan(path)
    original = path.read_text()
    second = scan(path)
    assert first["queued_count"] == 2
    assert second["status"] == "no_new_tasks"
    assert second["queue_mutated"] is False
    assert path.read_text() == original


@pytest.mark.parametrize("context", [
    clean_context(status="review_required", posture="abstain"),
    clean_context(anomaly_alert_count=1, risk_flags=["ohlcv_anomalies_detected"]),
    clean_context(exchange_sources=["binance", "kraken"]),
])
def test_uncertain_market_conditions_abstain_without_queue_mutation(tmp_path, context):
    path = tmp_path / "queue.json"
    report = scan(path, market_context=context)
    assert report["status"] == "abstained"
    assert report["queued"] == []
    assert not path.exists()


def test_requires_three_unique_verified_sources_and_sufficient_history(tmp_path):
    path = tmp_path / "queue.json"
    with pytest.raises(ResearchSchedulerError, match="three unique"):
        scan(path, market_context=clean_context(exchange_sources=["binance", "kraken", "kraken"]))
    with pytest.raises(ResearchSchedulerError, match="20 aligned"):
        scan(path, market_context=clean_context(aligned_candles=19))


def test_rejects_invalid_proposal_definitions(tmp_path):
    path = tmp_path / "queue.json"
    invalid = proposal_report()
    invalid["proposals"][0]["candidate"]["lookback"] = True
    with pytest.raises(ResearchSchedulerError, match="lookback"):
        scan(path, proposal_report=invalid)
    assert not path.exists()


def test_rejects_naive_timestamp_and_non_hypothesis_report(tmp_path):
    path = tmp_path / "queue.json"
    with pytest.raises(ResearchSchedulerError, match="timezone-aware"):
        scan(path, observed_at="2026-11-18T12:00:00")
    with pytest.raises(ResearchSchedulerError, match="hypotheses only"):
        scan(path, proposal_report={"status": "approved", "proposals": []})


def test_tampered_queue_is_rejected(tmp_path):
    path = tmp_path / "queue.json"
    scan(path)
    payload = json.loads(path.read_text())
    payload["events"][0]["event"]["hypothesis"] = "tampered"
    path.write_text(json.dumps(payload))
    with pytest.raises(ResearchSchedulerError, match="hash is invalid"):
        load_research_queue(path)


def test_empty_proposal_report_does_not_create_file(tmp_path):
    path = tmp_path / "queue.json"
    report = scan(path, proposal_report={"status": "hypotheses_only", "proposals": []})
    assert report["status"] == "no_new_tasks"
    assert report["queue_mutated"] is False
    assert not path.exists()
