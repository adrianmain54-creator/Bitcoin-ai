"""Controlled, preregistered walk-forward execution for research experiments.

This runner reserves the exact holdout interval before evaluation, requires
three immutable trial registrations, and records outcomes after the lab returns.
It has no paper/live execution authority.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path

from .candidate_registry import (
    CandidateRegistryError,
    audit_candidate_family,
    complete_candidate_trial,
    load_candidate_registry,
    register_candidate_trial,
)
from .holdout_ledger import (
    HoldoutLedgerError,
    audit_and_append_holdout_records,
    load_holdout_ledger,
)
from .research_lab import run_strategy_lab


class ControlledExperimentError(ValueError):
    """Raised when an experiment cannot safely pass its preregistration gates."""


_ROLES = ("proposal", "source", "cash")


def _iso(value: str, field: str) -> str:
    if not isinstance(value, str):
        raise ControlledExperimentError(f"{field} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ControlledExperimentError(f"{field} must be a valid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ControlledExperimentError(f"{field} must include a timezone")
    return parsed.isoformat()


def _verify_plan(prepared: dict) -> tuple[dict, list]:
    if not isinstance(prepared, dict) or prepared.get("status") != "plan_prepared":
        raise ControlledExperimentError("prepared experiment plan is required")
    if prepared.get("execution_authority") != "none" or prepared.get("side_effects") != []:
        raise ControlledExperimentError("plan execution authority or side-effect declaration is invalid")
    plan = prepared.get("plan")
    bars = prepared.get("bars")
    if not isinstance(plan, dict) or not isinstance(bars, list) or len(bars) < 4:
        raise ControlledExperimentError("plan or typed bars are missing")
    expected_id = hashlib.sha256(json.dumps(
        plan, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()
    if prepared.get("plan_id") != expected_id:
        raise ControlledExperimentError("experiment plan fingerprint does not match its contents")
    if plan.get("symbol") != "BTC-USDT" or not isinstance(plan.get("dataset_fingerprint"), str):
        raise ControlledExperimentError("plan must identify a BTC-USDT dataset")
    if len(plan["dataset_fingerprint"]) != 64:
        raise ControlledExperimentError("dataset fingerprint is malformed")
    try:
        bytes.fromhex(plan["dataset_fingerprint"])
    except ValueError as exc:
        raise ControlledExperimentError("dataset fingerprint is malformed") from exc
    candidates = plan.get("candidates")
    if not isinstance(candidates, dict) or set(candidates) != {"proposal", "unchanged_source", "cash"}:
        raise ControlledExperimentError("plan must define proposal, source, and cash candidates")
    normalized = []
    for role in _ROLES:
        item = candidates["unchanged_source" if role == "source" else role]
        if not isinstance(item, dict) or set(item) != {"family", "lookback"}:
            raise ControlledExperimentError(f"{role} candidate definition is malformed")
        family, lookback = item["family"], item["lookback"]
        if not isinstance(family, str) or not family or isinstance(lookback, bool) or not isinstance(lookback, int):
            raise ControlledExperimentError(f"{role} candidate definition is malformed")
        normalized.append((family, lookback))
    if len(set(normalized)) != 3:
        raise ControlledExperimentError("proposal, source, and cash must be distinct strategy definitions")
    if candidates["cash"] != {"family": "cash", "lookback": 2}:
        raise ControlledExperimentError("cash comparator must be the explicit cash baseline")
    train_bars, test_bars = plan.get("train_bars"), plan.get("test_bars")
    if (isinstance(train_bars, bool) or not isinstance(train_bars, int)
            or isinstance(test_bars, bool) or not isinstance(test_bars, int)):
        raise ControlledExperimentError("training and test sizes must be integers")
    if train_bars < 3 or test_bars < 3 or train_bars + test_bars >= len(bars):
        raise ControlledExperimentError("training/test sizes do not fit the supplied bars")
    # Match the lab's exact rolling-fold convention. The broad holdout window
    # in the plan must end on the final test bar, not on unused trailing data.
    cursor = train_bars
    last_end = None
    while cursor + test_bars < len(bars):
        last_end = cursor + test_bars
        cursor += test_bars
    if last_end != len(bars) - 1:
        raise ControlledExperimentError(
            "bar count leaves unused trailing observations outside the preregistered test window"
        )
    window = plan.get("test_window")
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        raise ControlledExperimentError("test window is malformed")
    if _iso(window["start"], "test_window.start") != bars[train_bars].timestamp.isoformat():
        raise ControlledExperimentError("test window start does not match the walk-forward folds")
    if _iso(window["end"], "test_window.end") != bars[last_end].timestamp.isoformat():
        raise ControlledExperimentError("test window end does not match the walk-forward folds")
    return plan, bars


def run_preregistered_experiment(
    prepared: dict,
    *,
    candidate_registry_path: str | Path,
    holdout_ledger_path: str | Path,
    registered_at: str,
    bootstrap_trials: int = 500,
    seed: int = 7,
    expected_interval_seconds: int | None = None,
) -> dict:
    """Reserve a fresh holdout, preregister all roles, then run the research lab.

    The holdout attempt is appended before evaluation. If evaluation fails, its
    reservation and incomplete registrations remain visible; retrying the same
    interval is therefore rejected rather than silently reusing exposed data.
    """
    plan, bars = _verify_plan(prepared)
    registered = _iso(registered_at, "registered_at")
    registry_path, ledger_path = Path(candidate_registry_path), Path(holdout_ledger_path)
    fingerprint = plan["dataset_fingerprint"]
    window = plan["test_window"]
    start, end = _iso(window["start"], "test_start"), _iso(window["end"], "test_end")
    revision = plan.get("code_revision")
    if not isinstance(revision, str) or not revision.strip():
        raise ControlledExperimentError("code revision is required")
    costs = plan.get("costs_bps")
    if not isinstance(costs, dict) or set(costs) != {"fee", "slippage"}:
        raise ControlledExperimentError("plan execution costs are malformed")
    if isinstance(bootstrap_trials, bool) or not isinstance(bootstrap_trials, int) or not 100 <= bootstrap_trials <= 10000:
        raise ControlledExperimentError("bootstrap_trials must be between 100 and 10000")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise ControlledExperimentError("seed must be an integer")

    experiment_id = "walk-forward:" + prepared["plan_id"]
    trial_ids = {role: f"{prepared['plan_id']}:{role}" for role in _ROLES}
    candidate_names = {
        role: f"{plan['candidates']['unchanged_source' if role == 'source' else role]['family']}:{plan['candidates']['unchanged_source' if role == 'source' else role]['lookback']}"
        for role in _ROLES
    }

    try:
        # Verify both append-only histories before making any changes.
        registry = load_candidate_registry(registry_path)
        prior_holdouts = load_holdout_ledger(ledger_path)
        if any(item["event"].get("trial_id") in set(trial_ids.values()) for item in registry["events"]):
            raise ControlledExperimentError("this deterministic plan has already been registered")
        for role in _ROLES:
            definition = {
                "family": plan["candidates"]["unchanged_source" if role == "source" else role]["family"],
                "lookback": plan["candidates"]["unchanged_source" if role == "source" else role]["lookback"],
                "fee_bps": float(costs["fee"]),
                "slippage_bps": float(costs["slippage"]),
                "train_bars": plan["train_bars"],
                "test_bars": plan["test_bars"],
                "step_bars": plan["test_bars"],
                "plan_id": prepared["plan_id"],
                "role": role,
            }
            register_candidate_trial(
                registry_path,
                trial_id=trial_ids[role],
                candidate_name=candidate_names[role],
                strategy_definition=definition,
                dataset_fingerprint=fingerprint,
                code_revision=revision,
                test_start=start,
                test_end=end,
                registered_at=registered,
            )
        reservation = audit_and_append_holdout_records(
            ledger_path,
            [{
                "experiment_id": experiment_id,
                "dataset_fingerprint": fingerprint,
                "test_start": start,
                "test_end": end,
            }],
        )
    except (CandidateRegistryError, HoldoutLedgerError) as exc:
        raise ControlledExperimentError(f"preregistration or holdout reservation failed: {exc}") from exc

    if reservation["status"] != "no_overlap_detected":
        return {
            "status": "rejected_holdout_reuse",
            "experiment_id": experiment_id,
            "plan_id": prepared["plan_id"],
            "holdout_reservation": reservation,
            "registered_trials": trial_ids,
            "execution_authority": "none",
            "limitations": ["The attempted interval remains recorded and must not be retried."],
        }

    candidates = [
        {"family": plan["candidates"]["unchanged_source" if role == "source" else role]["family"],
         "lookback": plan["candidates"]["unchanged_source" if role == "source" else role]["lookback"]}
        for role in _ROLES
    ]
    if expected_interval_seconds is None:
        interval_seconds = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600, "1d": 86400}
        expected_interval_seconds = interval_seconds.get(plan.get("interval"))
    report = run_strategy_lab(
        bars,
        train_bars=plan["train_bars"],
        test_bars=plan["test_bars"],
        candidates=candidates,
        step_bars=plan["test_bars"],
        fee_bps=float(costs["fee"]),
        slippage_bps=float(costs["slippage"]),
        bootstrap_trials=bootstrap_trials,
        seed=seed,
        expected_interval_seconds=expected_interval_seconds,
        previous_holdout_experiments=prior_holdouts,
    )
    if report.get("holdout_reuse_audit", {}).get("status") != "no_overlap_detected":
        raise ControlledExperimentError("research lab holdout audit disagrees with the pre-run reservation")

    fixed = report.get("fixed_candidate_oos_comparison", {}).get("candidates", {})
    completed_at = datetime.now().astimezone().isoformat()
    try:
        for role in _ROLES:
            result = fixed.get(candidate_names[role])
            if not isinstance(result, dict):
                raise ControlledExperimentError(f"research lab omitted the {role} fixed-candidate result")
            complete_candidate_trial(
                registry_path,
                trial_id=trial_ids[role],
                outcome={
                    "plan_id": prepared["plan_id"],
                    "role": role,
                    "observations": result.get("observations"),
                    "return_pct": result.get("return_pct"),
                    "excess_return_vs_buy_and_hold_pct_points": result.get(
                        "excess_return_vs_buy_and_hold_pct_points"
                    ),
                    "metrics_at_2x_cost": result.get("metrics_at_2x_cost"),
                },
                completed_at=completed_at,
            )
        family_audit = audit_candidate_family(
            registry_path,
            dataset_fingerprint=fingerprint,
            test_start=start,
            test_end=end,
        )
    except CandidateRegistryError as exc:
        raise ControlledExperimentError(f"trial completion failed; inspect registry before retrying: {exc}") from exc

    return {
        "status": "completed_research_only",
        "experiment_id": experiment_id,
        "plan_id": prepared["plan_id"],
        "plan": plan,
        "registered_trials": trial_ids,
        "holdout_reservation": reservation,
        "candidate_family_audit": family_audit,
        "research_report": report,
        "execution_authority": "none",
        "limitations": [
            "The holdout interval was reserved before the research lab evaluated it.",
            "A failed run leaves an exposed reservation and incomplete trial registrations; do not retry the same interval.",
            "This is historical backtesting only; no paper-state mutation, strategy promotion, or live orders occur.",
            "A clean ledger cannot prove that the data was never inspected outside this system.",
        ],
    }
