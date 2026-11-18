"""Turn observed strategy failures into bounded, untested improvement hypotheses.

This module never tunes against returns, runs backtests, or promotes candidates.
"""
from __future__ import annotations

import math


class StrategyImprovementError(ValueError):
    """Invalid failure diagnostics or proposal configuration."""


def propose_strategy_improvements(
    candidate_name: str,
    failure_report: dict,
    *,
    max_drawdown_trigger_pct: float = 15.0,
    loss_concentration_trigger_pct: float = 60.0,
) -> dict:
    """Suggest a small set of risk-reducing candidates from OOS diagnostics.

    Proposals are hypotheses only. They must be registered before evaluation on
    a new, untouched dataset. No return values are used to tune parameters.
    """
    if not isinstance(candidate_name, str) or ":" not in candidate_name:
        raise StrategyImprovementError("candidate_name must use family:lookback format")
    family, raw_lookback = candidate_name.rsplit(":", 1)
    if family not in {
        "sma", "momentum", "breakout", "vol_target_sma",
        "defensive_vol_target_sma", "agent_council",
        "agent_council_50", "agent_council_25", "cash",
    }:
        raise StrategyImprovementError("unsupported candidate family")
    try:
        lookback = int(raw_lookback)
    except (TypeError, ValueError) as exc:
        raise StrategyImprovementError("candidate lookback must be an integer") from exc
    if isinstance(max_drawdown_trigger_pct, bool) or not isinstance(max_drawdown_trigger_pct, (int, float)) or not math.isfinite(max_drawdown_trigger_pct) or max_drawdown_trigger_pct <= 0:
        raise StrategyImprovementError("max_drawdown_trigger_pct must be finite and positive")
    if isinstance(loss_concentration_trigger_pct, bool) or not isinstance(loss_concentration_trigger_pct, (int, float)) or not math.isfinite(loss_concentration_trigger_pct) or not 0 < loss_concentration_trigger_pct <= 100:
        raise StrategyImprovementError("loss_concentration_trigger_pct must be in (0, 100]")

    if not isinstance(failure_report, dict) or failure_report.get("status") != "diagnostic_only":
        raise StrategyImprovementError("failure_report must be a diagnostic-only report")
    observations = failure_report.get("observations")
    drawdown = failure_report.get("max_drawdown_pct")
    concentration = failure_report.get("worst_bar_loss_concentration_pct")
    if isinstance(observations, bool) or not isinstance(observations, int) or observations < 1:
        raise StrategyImprovementError("failure report observations are invalid")
    for value, field in ((drawdown, "max_drawdown_pct"), (concentration, "worst_bar_loss_concentration_pct")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise StrategyImprovementError(f"failure report {field} is invalid")
    if drawdown > 0 or concentration < 0 or concentration > 100:
        raise StrategyImprovementError("failure report risk diagnostics are out of range")

    proposals = []
    if drawdown <= -max_drawdown_trigger_pct:
        proposals.append({
            "candidate": {"family": "cash", "lookback": 2},
            "hypothesis": "A cash-only baseline can show whether avoiding exposure removes the observed drawdown.",
            "trigger": "drawdown_threshold_exceeded",
        })
        if family == "agent_council":
            proposals.extend([
                {
                    "candidate": {"family": "agent_council_50", "lookback": max(48, lookback)},
                    "hypothesis": "A 50% exposure cap may reduce drawdown while retaining the council's signals.",
                    "trigger": "drawdown_threshold_exceeded",
                },
                {
                    "candidate": {"family": "agent_council_25", "lookback": max(48, lookback)},
                    "hypothesis": "A 25% exposure cap may reduce drawdown further, at the cost of lower participation.",
                    "trigger": "drawdown_threshold_exceeded",
                },
            ])
        elif family == "agent_council_50":
            proposals.append({
                "candidate": {"family": "agent_council_25", "lookback": max(48, lookback)},
                "hypothesis": "A 25% exposure cap may reduce drawdown relative to the current capped council.",
                "trigger": "drawdown_threshold_exceeded",
            })

    if concentration >= loss_concentration_trigger_pct and family != "cash":
        proposals.append({
            "candidate": {"family": "cash", "lookback": 2},
            "hypothesis": "Compare against cash to test whether exposure is necessary during concentrated loss periods.",
            "trigger": "loss_concentration_threshold_exceeded",
        })

    # Deduplicate candidate definitions without scoring or ranking them.
    unique = []
    seen = set()
    for proposal in proposals:
        key = (proposal["candidate"]["family"], proposal["candidate"]["lookback"])
        if key not in seen and key != (family, lookback):
            seen.add(key)
            unique.append(proposal)

    return {
        "status": "hypotheses_only",
        "source_candidate": {"family": family, "lookback": lookback},
        "source_observations": observations,
        "proposals": unique,
        "proposal_count": len(unique),
        "evaluation_requirements": [
            "Assign a new trial ID and register the exact candidate definition before evaluation.",
            "Use a dataset fingerprint and holdout interval not previously used by this candidate or experiment.",
            "Keep candidate selection and parameter decisions inside training data only.",
            "Compare every proposal against the unchanged source candidate and a cash baseline on identical fresh test intervals.",
            "Report uncertainty, doubled-cost results, regime robustness, and failure diagnostics; insufficient evidence is not a pass.",
            "Do not promote or execute from this proposal report.",
        ],
        "limitations": [
            "The rules are conservative heuristics, not learned improvements.",
            "Observed historical losses do not establish that a proposed variant will perform better.",
            "No backtest or holdout evaluation is performed by this function.",
        ],
    }
