from datetime import datetime, timedelta, timezone
import json

from bitcoin_ai.forward_validation import GENESIS_HASH, observation_digest
from bitcoin_ai.paper_health import build_paper_health_report
from bitcoin_ai.paper_trading import PaperAccount
from bitcoin_ai.risk import new_risk_state
from bitcoin_ai.state_store import PaperStateStore


NOW = datetime(2026, 1, 8, tzinfo=timezone.utc)


def save_state(path, observed_at, *, halted=False):
    item = {
        "observed_at": observed_at.isoformat(), "price": 100.0,
        "equity": 1000.0, "previous_hash": GENESIS_HASH,
    }
    item["observation_hash"] = observation_digest(item)
    account = PaperAccount(paper_observations=[item])
    risk = new_risk_state(1000.0, NOW)
    risk.halted = halted
    PaperStateStore(path).save(account, risk)


def test_missing_state_is_not_started(tmp_path):
    report = build_paper_health_report(tmp_path / "missing.json", now=NOW)
    assert report["status"] == "not_started"
    assert report["alert"] == "paper_state_missing"


def test_fresh_valid_state_is_healthy(tmp_path):
    path = tmp_path / "paper.json"
    save_state(path, NOW - timedelta(seconds=30))
    report = build_paper_health_report(path, now=NOW, max_age_seconds=180)
    assert report["status"] == "healthy"
    assert report["healthy"] is True
    assert report["risk_halted"] is False


def test_old_observation_is_stale(tmp_path):
    path = tmp_path / "paper.json"
    save_state(path, NOW - timedelta(seconds=600))
    report = build_paper_health_report(path, now=NOW, max_age_seconds=180)
    assert report["status"] == "stale"
    assert report["alert"] == "paper_observations_stale"


def test_broken_hash_chain_is_corrupt(tmp_path):
    path = tmp_path / "paper.json"
    save_state(path, NOW)
    payload = json.loads(path.read_text())
    payload["account"]["paper_observations"][0]["equity"] = 900
    path.write_text(json.dumps(payload))
    report = build_paper_health_report(path, now=NOW)
    assert report["status"] == "corrupt"
    assert report["alert"] == "paper_state_integrity_failure"


def test_risk_halt_is_never_cleared_by_health_monitor(tmp_path):
    path = tmp_path / "paper.json"
    save_state(path, NOW, halted=True)
    report = build_paper_health_report(path, now=NOW)
    assert report["status"] == "risk_halted"
    assert report["risk_halted"] is True
    assert "never clears it" in report["action"]


def test_new_valid_observation_clears_stale_alert_but_not_risk_halt(tmp_path):
    path = tmp_path / "paper.json"
    save_state(path, NOW - timedelta(hours=1))
    assert build_paper_health_report(path, now=NOW)["status"] == "stale"
    save_state(path, NOW - timedelta(seconds=5))
    assert build_paper_health_report(path, now=NOW)["status"] == "healthy"


def test_health_monitor_rejects_naive_clock_and_invalid_age(tmp_path):
    path = tmp_path / "paper.json"
    try:
        build_paper_health_report(path, now=datetime(2026, 1, 8))
    except ValueError as exc:
        assert "timezone-aware" in str(exc)
    else:
        raise AssertionError("naive now must be rejected")
    try:
        build_paper_health_report(path, now=NOW, max_age_seconds=0)
    except ValueError as exc:
        assert "finite positive" in str(exc)
    else:
        raise AssertionError("zero max age must be rejected")


def test_strategy_degradation_requires_review_in_health_report(tmp_path):
    from bitcoin_ai.forward_validation import observation_digest
    path = tmp_path / "paper.json"
    start = NOW - timedelta(minutes=36)
    observations = []
    equity = 1000.0
    for index in range(36):
        if index:
            equity *= 1.01 if index <= 30 else 0.98
        item = {
            "observed_at": (start + timedelta(minutes=index)).isoformat(),
            "price": 100.0,
            "equity": equity,
            "baseline_equity": 1000.0,
            "signal": "hold",
            "risk_allowed": True,
            "risk_halted": False,
            "trade_count": 0,
            "previous_hash": observations[-1]["observation_hash"] if observations else GENESIS_HASH,
        }
        item["observation_hash"] = observation_digest(item)
        observations.append(item)
    account = PaperAccount(paper_observations=observations)
    risk = new_risk_state(1000.0, NOW)
    PaperStateStore(path).save(account, risk)
    report = build_paper_health_report(path, now=NOW, max_age_seconds=3600)
    assert report["performance_anomalies"]["status"] == "anomaly_detected"
    assert report["status"] == "review_required"
    assert report["alert"] == "strategy_performance_degradation"
    assert report["healthy"] is False


def test_observation_cadence_gap_requires_human_review(tmp_path):
    path = tmp_path / "paper.json"
    start = NOW - timedelta(minutes=40)
    observations = []
    for index in range(4):
        stamp = start + timedelta(minutes=index if index < 2 else index + 20)
        item = {
            "observed_at": stamp.isoformat(), "price": 100.0,
            "equity": 1000.0, "baseline_equity": 1000.0,
            "previous_hash": observations[-1]["observation_hash"] if observations else GENESIS_HASH,
        }
        item["observation_hash"] = observation_digest(item)
        observations.append(item)
    account = PaperAccount(paper_observations=observations)
    risk = new_risk_state(1000.0, NOW)
    PaperStateStore(path).save(account, risk)
    report = build_paper_health_report(path, now=NOW, max_age_seconds=3600)
    assert report["forward_evidence_status"] == "insufficient_evidence"
    assert report["status"] == "review_required"
    assert report["alert"] == "paper_observation_cadence_gap"
    assert report["healthy"] is False
