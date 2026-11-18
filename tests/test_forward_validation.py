from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.forward_validation import evaluate_forward_paper_evidence


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
    return result


def test_forward_evidence_requires_both_observation_count_and_elapsed_time():
    result = evaluate_forward_paper_evidence(
        observations(3, 8), min_observations=3, min_days=7,
    )
    assert result["status"] == "evidence_collected"
    assert result["observations"] == 3
    assert result["strategy_return_pct"] == 0.5
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
    with pytest.raises(ValueError, match="timezone-aware"):
        evaluate_forward_paper_evidence(data)
