"""Bridge completed controlled experiments into the read-only fresh-evidence gate.

Only the exact pre-reserved interval belonging to this controlled run is exempted
from the prior-holdout overlap scan. The hash-chained ledger is still fully loaded
and verified by the evaluator before that one matching reservation is excluded.
"""
from __future__ import annotations

from pathlib import Path

from .fresh_evidence import FreshEvidenceError, evaluate_fresh_candidate


_ROLES = ("proposal", "source", "cash")


def evaluate_controlled_experiment(
    controlled_result: dict,
    *,
    candidate_registry_path: str | Path,
    holdout_ledger_path: str | Path,
    min_observations: int = 180,
    bootstrap_trials: int = 2000,
    block_size: int = 5,
    seed: int = 20261118,
) -> dict:
    """Evaluate paired streams from one completed, preregistered research run."""
    if not isinstance(controlled_result, dict) or controlled_result.get("status") != "completed_research_only":
        raise FreshEvidenceError("a completed research-only controlled experiment is required")
    if controlled_result.get("execution_authority") != "none":
        raise FreshEvidenceError("controlled experiment has unexpected execution authority")
    plan = controlled_result.get("plan")
    if not isinstance(plan, dict):
        raise FreshEvidenceError("controlled experiment plan is missing")
    fingerprint = plan.get("dataset_fingerprint")
    revision = plan.get("code_revision")
    window = plan.get("test_window")
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        raise FreshEvidenceError("controlled experiment test window is malformed")
    candidates = plan.get("candidates")
    if not isinstance(candidates, dict) or set(candidates) != {"proposal", "unchanged_source", "cash"}:
        raise FreshEvidenceError("controlled experiment candidate definitions are incomplete")

    trial_ids = controlled_result.get("registered_trials")
    if not isinstance(trial_ids, dict) or set(trial_ids) != set(_ROLES):
        raise FreshEvidenceError("controlled experiment trial IDs are incomplete")
    expected_names = {}
    for role in _ROLES:
        candidate = candidates["unchanged_source" if role == "source" else role]
        if not isinstance(candidate, dict) or set(candidate) != {"family", "lookback"}:
            raise FreshEvidenceError(f"{role} candidate definition is malformed")
        expected_names[role] = f"{candidate['family']}:{candidate['lookback']}"

    family_audit = controlled_result.get("candidate_family_audit")
    if not isinstance(family_audit, dict) or family_audit.get("status") != "complete":
        raise FreshEvidenceError("candidate family audit is not complete")
    audited = {
        item.get("trial_id"): item
        for item in family_audit.get("registered_trials", [])
        if isinstance(item, dict)
    }
    for role in _ROLES:
        item = audited.get(trial_ids[role])
        if (not isinstance(item, dict) or item.get("candidate_name") != expected_names[role]
                or item.get("completed") is not True or not isinstance(item.get("outcome"), dict)):
            raise FreshEvidenceError(f"{role} trial is not durably completed in the candidate registry")

    reservation = controlled_result.get("holdout_reservation")
    experiment_id = controlled_result.get("experiment_id")
    if (not isinstance(reservation, dict) or reservation.get("status") != "no_overlap_detected"
            or not isinstance(experiment_id, str) or not experiment_id.strip()):
        raise FreshEvidenceError("controlled experiment has no clean, identifiable holdout reservation")

    report = controlled_result.get("research_report")
    fixed = report.get("fixed_candidate_oos_comparison", {}).get("candidates") if isinstance(report, dict) else None
    regimes = report.get("out_of_sample_regime_labels") if isinstance(report, dict) else None
    if not isinstance(fixed, dict) or not isinstance(regimes, list):
        raise FreshEvidenceError("research report lacks retained paired OOS streams")
    returns, doubled = {}, {}
    for role in _ROLES:
        result = fixed.get(expected_names[role])
        if not isinstance(result, dict):
            raise FreshEvidenceError(f"research report omitted the {role} candidate")
        returns[role] = result.get("returns")
        doubled[role] = result.get("doubled_cost_returns")

    return evaluate_fresh_candidate(
        candidate_registry_path,
        holdout_ledger_path,
        trial_ids=trial_ids,
        expected_candidate_names=expected_names,
        dataset_fingerprint=fingerprint,
        test_start=window["start"],
        test_end=window["end"],
        code_revision=revision,
        returns=returns,
        doubled_cost_returns=doubled,
        regimes=regimes,
        min_observations=min_observations,
        bootstrap_trials=bootstrap_trials,
        block_size=block_size,
        seed=seed,
        reservation_experiment_id=experiment_id,
    )
