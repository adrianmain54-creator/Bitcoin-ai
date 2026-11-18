"""Conservative research-result gate for starting a separate paper trial.

This never enables exchange execution or changes the live paper strategy.
"""
from __future__ import annotations

import math


def evaluate_paper_trial_eligibility(report, *, min_folds=6, min_oos_returns=180,
                                     max_drawdown_pct=20.0):
    reasons = []
    if not isinstance(report, dict):
        return {"eligible": False, "reasons": ["report must be a dictionary"], "scope": "paper trial only"}
    if isinstance(min_folds, bool) or not isinstance(min_folds, int) or min_folds < 1:
        raise ValueError("min_folds must be an integer >= 1")
    if isinstance(min_oos_returns, bool) or not isinstance(min_oos_returns, int) or min_oos_returns < 1:
        raise ValueError("min_oos_returns must be an integer >= 1")
    if isinstance(max_drawdown_pct, bool) or not isinstance(max_drawdown_pct, (int, float)) or not math.isfinite(max_drawdown_pct) or max_drawdown_pct <= 0:
        raise ValueError("max_drawdown_pct must be finite and positive")

    folds = report.get("fold_count")
    n = report.get("out_of_sample_returns")
    strategy = report.get("out_of_sample_metrics")
    benchmark = report.get("buy_and_hold_metrics")
    bootstrap = report.get("bootstrap")
    stressed = report.get("out_of_sample_metrics_at_2x_cost")
    if isinstance(folds, bool) or not isinstance(folds, int) or folds < min_folds:
        reasons.append(f"requires at least {min_folds} completed out-of-sample folds")
    if isinstance(n, bool) or not isinstance(n, int) or n < min_oos_returns:
        reasons.append(f"requires at least {min_oos_returns} out-of-sample returns")
    if (not isinstance(strategy, dict) or not isinstance(benchmark, dict)
            or not isinstance(bootstrap, dict) or not isinstance(stressed, dict)):
        reasons.append("missing strategy, benchmark, bootstrap, or 2x-cost stress evidence")
    else:
        def finite_metric(obj, key):
            value = obj.get(key)
            return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None
        strat_return = finite_metric(strategy, "total_return_pct")
        bench_return = finite_metric(benchmark, "total_return_pct")
        drawdown = finite_metric(strategy, "max_drawdown_pct")
        sortino = finite_metric(strategy, "sortino_ratio")
        p05 = finite_metric(bootstrap, "final_equity_p05")
        stressed_return = finite_metric(stressed, "total_return_pct")
        if None in (strat_return, bench_return, drawdown, sortino, p05, stressed_return):
            reasons.append("required performance, stress, or bootstrap metrics are missing or invalid")
        else:
            if strat_return <= bench_return:
                reasons.append("out-of-sample return did not beat buy-and-hold")
            if drawdown < -max_drawdown_pct:
                reasons.append(f"maximum drawdown exceeded {max_drawdown_pct:g}%")
            if sortino <= 0:
                reasons.append("out-of-sample Sortino ratio is not positive")
            if p05 <= 1.0:
                reasons.append("bootstrap fifth-percentile ending equity is not above starting equity")
            if stressed_return <= 0.0:
                reasons.append("out-of-sample return is not positive at 2x estimated execution costs")
    return {
        "eligible": not reasons,
        "reasons": reasons,
        "scope": "eligibility for a separately monitored paper-forward trial only; never authorizes live trading",
        "minimums": {"folds": min_folds, "oos_returns": min_oos_returns, "max_drawdown_pct": max_drawdown_pct},
    }


def evaluate_strategy_abstention(candidates, *, min_observations=180,
                                 min_probability_positive_pct=95.0):
    """Report-only conservative evidence gate for fixed candidates.

    This is an OOS diagnostic, not a selector or execution instruction. A failed
    gate means remain in cash; a pass only warrants human review and paper-forward
    validation. No live or paper-service behavior is changed.
    """
    if not isinstance(candidates, dict):
        raise ValueError("candidates must be a dictionary")
    if isinstance(min_observations, bool) or not isinstance(min_observations, int) or min_observations < 1:
        raise ValueError("min_observations must be an integer >= 1")
    if (isinstance(min_probability_positive_pct, bool)
            or not isinstance(min_probability_positive_pct, (int, float))
            or not math.isfinite(min_probability_positive_pct)
            or not 0.0 <= min_probability_positive_pct <= 100.0):
        raise ValueError("min_probability_positive_pct must be between 0 and 100")

    assessments = {}
    for name, candidate in candidates.items():
        reasons = []
        if not isinstance(candidate, dict):
            reasons.append("candidate evidence is missing or invalid")
            candidate = {}
        uncertainty = candidate.get("paired_edge_uncertainty")
        stress = candidate.get("metrics_at_2x_cost")
        if not isinstance(uncertainty, dict) or not isinstance(stress, dict):
            reasons.append("paired uncertainty or 2x-cost evidence is missing")
        else:
            def metric(obj, key):
                value = obj.get(key)
                return (value if isinstance(value, (int, float))
                        and not isinstance(value, bool) and math.isfinite(value)
                        else None)
            observations = uncertainty.get("observations")
            if (isinstance(observations, bool) or not isinstance(observations, int)
                    or observations < min_observations):
                reasons.append(f"requires at least {min_observations} paired OOS observations")
            p05 = metric(uncertainty, "excess_return_p05_pct")
            observed = metric(uncertainty, "observed_excess_return_pct")
            probability = metric(uncertainty, "probability_positive_pct")
            stressed = metric(stress, "total_return_pct")
            if None in (p05, observed, probability, stressed):
                reasons.append("required edge, probability, or stress metrics are missing or invalid")
            else:
                if p05 <= 0:
                    reasons.append("paired edge fifth percentile is not positive")
                if observed <= 0:
                    reasons.append("observed paired excess return is not positive")
                if probability < min_probability_positive_pct:
                    reasons.append(
                        f"bootstrap positive-edge share is below {min_probability_positive_pct:g}%"
                    )
                if stressed <= 0:
                    reasons.append("candidate return is not positive at 2x estimated costs")
        assessments[name] = {"eligible_for_review": not reasons, "reasons": reasons}

    passing = [name for name, item in assessments.items() if item["eligible_for_review"]]
    return {
        "action": "manual_review_required" if passing else "abstain_cash",
        "passing_candidates": passing,
        "candidate_assessments": assessments,
        "thresholds": {
            "minimum_paired_oos_observations": min_observations,
            "minimum_bootstrap_positive_edge_pct": min_probability_positive_pct,
            "paired_edge_p05_pct": "strictly greater than 0",
            "observed_excess_return_pct": "strictly greater than 0",
            "2x_cost_return_pct": "strictly greater than 0",
        },
        "scope": (
            "Report-only historical evidence gate. A pass is not a strategy selection, "
            "forecast, proof of edge, or authorization to trade; require independent "
            "review and paper-forward validation. A fail means abstain to cash."
        ),
    }


def evaluate_independent_strategy_validation(candidates, data_quality_audit, *,
                                            holdout_reuse_audit=None,
                                            min_observations=180,
                                            min_probability_positive_pct=95.0):
    """Run deterministic proposer, skeptic, and evidence-review roles.

    This is an auditable rules engine, not an LLM or proof of strategy skill.
    It only recommends whether a human may review a separate paper-forward
    trial. It never selects a strategy or authorizes execution.
    """
    if not isinstance(candidates, dict):
        raise ValueError("candidates must be a dictionary")
    if not isinstance(data_quality_audit, dict):
        raise ValueError("data_quality_audit must be a dictionary")

    # A statistically clean-looking backtest is not fresh evidence if its
    # holdout has been reused, or if no durable prior-experiment ledger was
    # supplied. Fail closed before any candidate can become paper-review eligible.
    holdout_status = (
        holdout_reuse_audit.get("status")
        if isinstance(holdout_reuse_audit, dict) else None
    )
    holdout_fresh = (
        holdout_status == "no_overlap_detected"
        and holdout_reuse_audit.get("eligible_for_fresh_holdout_review") is True
    ) if isinstance(holdout_reuse_audit, dict) else None

    # Proposer: enumerate the fixed candidates already defined before OOS scoring.
    proposed = sorted(candidates)
    if any(not isinstance(name, str) or not name.strip() for name in proposed):
        raise ValueError("candidate names must be non-empty strings")
    # More tried candidates create more opportunities to find a lucky winner.
    # Tighten the bootstrap positive-share hurdle as a conservative heuristic.
    # This is NOT a formal multiple-testing correction: bootstrap share is not a p-value.
    candidate_count = max(1, len(proposed))
    multiplicity_floor = 100.0 * (1.0 - 0.05 / candidate_count)
    effective_probability_threshold = max(
        float(min_probability_positive_pct), multiplicity_floor
    )
    # Skeptic: independently re-run the conservative evidence gate per candidate.
    skeptic_reviews = {}
    for name in proposed:
        skeptic_reviews[name] = evaluate_strategy_abstention(
            {name: candidates[name]},
            min_observations=min_observations,
            min_probability_positive_pct=effective_probability_threshold,
        )["candidate_assessments"][name]
    # Evidence reviewer: verify audit state and reconcile every proposed candidate.
    audit_status = data_quality_audit.get("status")
    audit_usable = data_quality_audit.get("usable") is True
    missing_reviews = [name for name in proposed if name not in skeptic_reviews]
    passing = [name for name in proposed
               if skeptic_reviews.get(name, {}).get("eligible_for_review") is True]
    evidence_errors = []
    if not audit_usable or audit_status == "fail":
        evidence_errors.append("historical data quality audit is not usable")
    if missing_reviews:
        evidence_errors.append("one or more proposed candidates lack skeptic review")
    if not proposed:
        evidence_errors.append("no fixed candidates were proposed")
    if holdout_reuse_audit is not None and not holdout_fresh:
        if holdout_status == "reuse_detected":
            evidence_errors.append("held-out intervals overlap prior or same-run experiments")
        elif holdout_status == "no_prior_ledger_supplied":
            evidence_errors.append("no prior holdout ledger was supplied; freshness is unverified")
        else:
            evidence_errors.append("fresh holdout audit is invalid or not eligible")

    # Regime slices are descriptive evidence, not tuning inputs. If a candidate
    # has regime results but positive excess is confined to one adequately
    # sampled regime, downgrade it to human review rather than rejecting it.
    regime_diagnostics = {}
    regime_concentration = []
    for name in proposed:
        candidate = candidates.get(name)
        slices = candidate.get("regime_attribution") if isinstance(candidate, dict) else None
        if not isinstance(slices, dict) or not slices:
            regime_diagnostics[name] = {
                "available": False,
                "interpretation": "No regime attribution supplied; no regime robustness conclusion.",
            }
            continue
        supported = []
        positive = []
        for regime, metrics in slices.items():
            if not isinstance(metrics, dict):
                continue
            observations = metrics.get("observations")
            excess = metrics.get("excess_return_vs_buy_and_hold_pct_points")
            if (isinstance(observations, int) and not isinstance(observations, bool)
                    and observations >= 30
                    and isinstance(excess, (int, float)) and not isinstance(excess, bool)
                    and math.isfinite(excess)):
                supported.append(regime)
                if excess > 0:
                    positive.append(regime)
        concentrated = len(supported) >= 2 and len(positive) <= 1
        regime_diagnostics[name] = {
            "available": True,
            "adequately_sampled_regimes": supported,
            "positive_excess_regimes": positive,
            "concentrated_in_one_or_fewer_regimes": concentrated,
            "minimum_observations_per_regime": 30,
            "interpretation": (
                "Edge is concentrated in one or fewer adequately sampled regimes; require human review."
                if concentrated else
                "No single-regime concentration detected in adequately sampled slices; this is not proof of robustness."
            ),
        }
        if concentrated and name in passing:
            regime_concentration.append(name)

    # Compare only already-declared fixed candidates from the same family.
    # This is a diagnostic, never a parameter search or replacement selector.
    parameter_diagnostics = {}
    parameter_sensitivity = []
    for name in proposed:
        candidate = candidates.get(name)
        if not isinstance(candidate, dict):
            parameter_diagnostics[name] = {"available": False, "nearby_candidates": []}
            continue
        family = candidate.get("family")
        lookback = candidate.get("lookback")
        edge = candidate.get("excess_return_vs_buy_and_hold_pct_points")
        observations = candidate.get("observations")
        valid_identity = (
            isinstance(family, str)
            and isinstance(lookback, int) and not isinstance(lookback, bool)
            and lookback > 0
        )
        if not valid_identity:
            parameter_diagnostics[name] = {
                "available": False,
                "nearby_candidates": [],
                "interpretation": "Candidate family/lookback metadata unavailable.",
            }
            continue
        radius = max(1, math.ceil(lookback * 0.25))
        nearby = []
        for peer_name in proposed:
            if peer_name == name:
                continue
            peer = candidates.get(peer_name)
            if not isinstance(peer, dict) or peer.get("family") != family:
                continue
            peer_lookback = peer.get("lookback")
            peer_edge = peer.get("excess_return_vs_buy_and_hold_pct_points")
            peer_obs = peer.get("observations")
            if (isinstance(peer_lookback, int) and not isinstance(peer_lookback, bool)
                    and 0 < abs(peer_lookback - lookback) <= radius
                    and isinstance(peer_obs, int) and not isinstance(peer_obs, bool)
                    and peer_obs >= 30
                    and isinstance(peer_edge, (int, float)) and not isinstance(peer_edge, bool)
                    and math.isfinite(peer_edge)):
                nearby.append({
                    "candidate": peer_name,
                    "lookback": peer_lookback,
                    "excess_return_vs_buy_and_hold_pct_points": peer_edge,
                })
        supported = (
            isinstance(observations, int) and not isinstance(observations, bool)
            and observations >= 30
            and isinstance(edge, (int, float)) and not isinstance(edge, bool)
            and math.isfinite(edge)
        )
        collapses = supported and edge > 0 and any(
            peer["excess_return_vs_buy_and_hold_pct_points"] <= 0 for peer in nearby
        )
        parameter_diagnostics[name] = {
            "available": bool(nearby),
            "nearby_candidates": nearby,
            "comparison_radius_lookback_bars": radius,
            "edge_collapses_in_nearby_variant": bool(collapses),
            "interpretation": (
                "Positive edge disappears in a nearby fixed parameter variant; require human review."
                if collapses else
                "No collapse detected among supplied nearby variants; this is not proof of parameter robustness."
            ),
        }
        if collapses and name in passing:
            parameter_sensitivity.append(name)

    if evidence_errors or not passing:
        verdict = "reject"
    elif audit_status != "pass" or regime_concentration or parameter_sensitivity:
        verdict = "needs_review"
    else:
        verdict = "eligible_for_paper_review"

    return {
        "verdict": verdict,
        "proposer": {
            "fixed_candidates": proposed,
            "basis": "candidate definitions supplied before held-out evaluation",
        },
        "skeptic": {
            "candidate_reviews": skeptic_reviews,
            "passing_candidates": passing,
            "method": "paired OOS edge, bootstrap lower bound and positive share, minimum sample, and 2x-cost checks",
        },
        "evidence_reviewer": {
            "data_quality_status": audit_status,
            "data_quality_usable": audit_usable,
            "holdout_reuse_status": holdout_status,
            "holdout_freshness_verified": holdout_fresh,
            "errors": evidence_errors,
            "candidate_review_coverage": len(skeptic_reviews),
            "proposed_candidate_count": len(proposed),
            "multiplicity_guard": {
                "base_minimum_bootstrap_positive_edge_pct": float(min_probability_positive_pct),
                "effective_minimum_bootstrap_positive_edge_pct": effective_probability_threshold,
                "candidate_count": candidate_count,
                "reference_alpha": 0.05,
                "method": "conservative heuristic: max(base threshold, 100 * (1 - 0.05 / candidate count))",
                "formal_multiple_testing_correction": False,
                "warning": "Bootstrap positive-edge share is not a p-value; this guard does not provide formal family-wise error control.",
            },
            "regime_diagnostics": regime_diagnostics,
            "regime_concentration_requires_review": regime_concentration,
            "parameter_sensitivity_diagnostics": parameter_diagnostics,
            "parameter_sensitivity_requires_review": parameter_sensitivity,
        },
        "scope": (
            "Deterministic independent-role review only. Eligibility means a human "
            "may consider a separately monitored paper-forward trial; it is not a "
            "strategy selection, profitability claim, or authorization to trade."
        ),
    }
