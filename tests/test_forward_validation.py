from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.forward_validation import (
    GENESIS_HASH, evaluate_forward_paper_evidence, observation_digest,
)


def observations(count=3, days=8):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    result = []
    for index in range(count):
        fraction = index / max(1, count - 1)
        result.append({
            "observed_at": (start + timedelta(days=days * fraction)).isoformat(),
            "price": 100.0 + index * 2,
            "equity": 1000.0 + index * 5,
        })
    previous = GENESIS_HASH
    for item in result:
        item["previous_hash"] = previous
        item["observation_hash"] = observation_digest(item)
        previous = item["observation_hash"]
    return result


def resign(data):
    previous = GENESIS_HASH
    for item in data:
        item["previous_hash"] = previous
        item.pop("observation_hash", None)
        item["observation_hash"] = observation_digest(item)
        previous = item["observation_hash"]


def test_forward_evidence_requires_both_observation_count_and_elapsed_time():
    result = evaluate_forward_paper_evidence(
        observations(3, 8), min_observations=3, min_days=7,
    )
    assert result["status"] == "evidence_collected"
    assert result["observations"] == 3
    assert result["strategy_return_pct"] == 1.0
    assert result["buy_and_hold_return_pct"] == 4.0
    assert result["excess_return_vs_buy_and_hold_pct_points"] == -3.0


def test_forward_evidence_does_not_confuse_many_fast_samples_with_time():
    result = evaluate_forward_paper_evidence(
        observations(100, 0.1), min_observations=100, min_days=7,
    )
    assert result["status"] == "insufficient_evidence"


def test_forward_evidence_requires_unique_chronological_timestamps():
    data = observations()
    data[2]["observed_at"] = data[1]["observed_at"]
    resign(data)
    with pytest.raises(ValueError, match="strictly increasing"):
        evaluate_forward_paper_evidence(data)


@pytest.mark.parametrize("field", ["price", "equity"])
def test_forward_evidence_rejects_invalid_financial_values(field):
    data = observations()
    data[1][field] = float("nan")
    with pytest.raises(ValueError, match="finite and positive"):
        evaluate_forward_paper_evidence(data)


def test_forward_evidence_rejects_naive_timestamps():
    data = observations()
    data[0]["observed_at"] = "2026-01-01T00:00:00"
    resign(data)
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_forward_paper_evidence(data)



def test_forward_evidence_rejects_tampered_observation():
    data = observations()
    data[1]["equity"] += 1
    with pytest.raises(ValueError, match="hash verification failed"):
        evaluate_forward_paper_evidence(data)


def test_forward_evidence_rejects_broken_chain_link():
    data = observations()
    data[1]["previous_hash"] = "f" * 64
    with pytest.raises(ValueError, match="broken previous-hash link"):
        evaluate_forward_paper_evidence(data)
