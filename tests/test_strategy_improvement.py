import pytest

from bitcoin_ai.strategy_improvement import (
    StrategyImprovementError,
    propose_strategy_improvements,
)


def failure_report(**overrides):
    report = {
        "status": "diagnostic_only",
        "observations": 240,
        "max_drawdown_pct": -22.5,
        "worst_bar_loss_concentration_pct": 72.0,
    }
    report.update(overrides)
    return report


def test_high_drawdown_proposes_cash_and_capped_council_variants():
    result = propose_strategy_improvements("agent_council:48", failure_report())
    candidates = [item["candidate"] for item in result["proposals"]]
    assert {"family": "cash", "lookback": 2} in candidates
    assert {"family": "agent_council_50", "lookback": 48} in candidates
    assert {"family": "agent_council_25", "lookback": 48} in candidates
    assert result["status"] == "hypotheses_only"


def test_under_threshold_report_does_not_create_risk_hypotheses():
    result = propose_strategy_improvements(
        "momentum:10",
        failure_report(max_drawdown_pct=-4.0, worst_bar_loss_concentration_pct=20.0),
    )
    assert result["proposals"] == []


def test_concentrated_losses_propose_cash_baseline():
    result = propose_strategy_improvements(
        "breakout:20",
        failure_report(max_drawdown_pct=-3.0, worst_bar_loss_concentration_pct=80.0),
    )
    assert [item["candidate"]["family"] for item in result["proposals"]] == ["cash"]


def test_cash_candidate_does_not_propose_itself():
    result = propose_strategy_improvements("cash:2", failure_report())
    assert result["proposals"] == []


def test_proposals_require_fresh_preregistered_evaluation():
    result = propose_strategy_improvements("agent_council:48", failure_report())
    requirements = " ".join(result["evaluation_requirements"]).lower()
    assert "register" in requirements
    assert "dataset fingerprint" in requirements
    assert "previously used" in requirements


@pytest.mark.parametrize("bad", [None, {}, {"status": "healthy"}])
def test_rejects_missing_or_non_diagnostic_failure_report(bad):
    with pytest.raises(StrategyImprovementError):
        propose_strategy_improvements("sma:12", bad)


def test_rejects_invalid_candidate_and_metrics():
    with pytest.raises(StrategyImprovementError):
        propose_strategy_improvements("unknown:12", failure_report())
    with pytest.raises(StrategyImprovementError):
        propose_strategy_improvements("sma:12", failure_report(max_drawdown_pct=float("nan")))
