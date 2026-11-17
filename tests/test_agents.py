import pytest

from bitcoin_ai.agents import run_agent_council


def test_agent_council_agrees_on_clean_uptrend():
    closes = [100.0 + i for i in range(80)]
    report = run_agent_council(closes)
    assert report.decision == "long"
    assert report.signal.target_allocation == pytest.approx(0.20)
    assert report.votes["trend"] == "bullish"
    assert report.votes["momentum"] == "bullish"
    assert report.regime["causal"] is True


def test_agent_council_stays_in_cash_on_downtrend():
    closes = [200.0 - i for i in range(80)]
    report = run_agent_council(closes)
    assert report.decision == "cash"
    assert report.signal.target_allocation == 0.0


def test_agent_council_reduces_exposure_in_range():
    closes = [100.0 + (0.1 if i % 2 else -0.1) for i in range(80)]
    report = run_agent_council(closes)
    assert report.signal.target_allocation <= 0.10


def test_agent_council_rejects_insufficient_history():
    with pytest.raises(ValueError, match="insufficient"):
        run_agent_council([100.0] * 20)


def test_agent_council_exposes_auditable_agent_reasons():
    report = run_agent_council([100.0 + i for i in range(80)])
    assert len(report.reasons) >= 3
    assert "skeptic" in report.votes
