from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.performance_anomaly import evaluate_performance_anomalies


def sample_observations(recent_return):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = []
    equity = 1000.0
    for index in range(36):
        if index:
            equity *= 1.01 if index <= 30 else (1.0 + recent_return)
        result.append({
            "observed_at": (start + timedelta(minutes=index)).isoformat(),
            "price": 100.0,
            "equity": equity,
        })
    return result


def test_flags_material_recent_performance_degradation():
    report = evaluate_performance_anomalies(sample_observations(-0.02))
    assert report["status"] == "anomaly_detected"
    assert report["anomalies"][0]["type"] == "relative_performance_degradation"
    assert report["anomalies"][0]["severity"] == "review"


def test_does_not_flag_stable_performance():
    report = evaluate_performance_anomalies(sample_observations(0.01))
    assert report["status"] == "no_anomaly_detected"
    assert report["anomalies"] == []


def test_insufficient_history_is_not_misreported_as_healthy():
    report = evaluate_performance_anomalies(sample_observations(0.01)[:10])
    assert report["status"] == "insufficient_observations"


def test_rejects_non_chronological_or_invalid_observations():
    data = sample_observations(0.01)
    data[2]["observed_at"] = data[1]["observed_at"]
    with pytest.raises(ValueError, match="strictly increasing"):
        evaluate_performance_anomalies(data)
    data = sample_observations(0.01)
    data[3]["equity"] = float("nan")
    with pytest.raises(ValueError, match="finite and positive"):
        evaluate_performance_anomalies(data)


def test_rejects_invalid_window_configuration():
    with pytest.raises(ValueError, match="at least min_baseline"):
        evaluate_performance_anomalies([], baseline_window=2, min_baseline=3)
    with pytest.raises(ValueError, match="finite and positive"):
        evaluate_performance_anomalies([], mad_threshold=float("inf"))


def test_withholds_anomaly_verdict_when_observation_cadence_has_a_gap():
    data = sample_observations(-0.02)
    for item in data[12:]:
        stamp = datetime.fromisoformat(item["observed_at"]) + timedelta(minutes=20)
        item["observed_at"] = stamp.isoformat()
    report = evaluate_performance_anomalies(data)
    assert report["status"] == "unreliable_cadence"
    assert report["cadence_gaps"]
    assert report["anomalies"] == []


def test_rejects_invalid_cadence_gap_multiple():
    with pytest.raises(ValueError, match="greater than 1"):
        evaluate_performance_anomalies([], max_gap_multiple=1)
