"""Fail-closed, read-only evaluation of pre-registered strategy proposals.

All compared return streams cover the same untouched interval. This module
reads existing append-only ledgers but never registers, completes, or promotes.
"""
from __future__ import annotations
from datetime import datetime
import hashlib
import math
import random
from pathlib import Path
from typing import Sequence
from .candidate_registry import CandidateRegistryError, load_candidate_registry
from .holdout_audit import HoldoutAuditError, audit_holdout_reuse
from .holdout_ledger import HoldoutLedgerError, load_holdout_ledger


class FreshEvidenceError(ValueError):
    """Unsafe trial provenance or evaluation evidence."""


def _stamp(value, field):
    if not isinstance(value, str):
        raise FreshEvidenceError(f"{field} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise FreshEvidenceError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise FreshEvidenceError(f"{field} must include a timezone")
    return parsed


def _series(values, field, expected=None):
    if isinstance(values, (str, bytes)) or not isinstance(values, Sequence):
        raise FreshEvidenceError(f"{field} must be a numeric sequence")
    result = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise FreshEvidenceError(f"{field} contains a non-finite or non-numeric value")
        if value <= -1:
            raise FreshEvidenceError(f"{field} contains a return at or below -100%")
        result.append(float(value))
    if expected is not None and len(result) != expected:
        raise FreshEvidenceError(f"{field} length does not match the shared interval")
    return result


def _compound(values):
    return (math.prod(1.0 + value for value in values) - 1.0) * 100.0


def _bootstrap_lower_edge(candidate, comparator, *, trials, seed, block_size):
    """Paired circular block bootstrap of arithmetic per-bar return differences."""
    differences = [a - b for a, b in zip(candidate, comparator)]
    n = len(differences)
    rng = random.Random(seed)
    samples = []
    blocks = math.ceil(n / block_size)
    for _ in range(trials):
        sample = []
        for _ in range(blocks):
            start = rng.randrange(n)
            sample.extend(differences[(start + offset) % n] for offset in range(block_size))
        samples.append(sum(sample[:n]) / n * 100.0)
    samples.sort()
    lower = samples[max(0, math.ceil(0.05 * trials) - 1)]
    positive_share = sum(value > 0 for value in samples) / trials
    return lower, positive_share


def evaluate_fresh_candidate(
    registry_path: str | Path, holdout_ledger_path: str | Path, *,
    trial_ids: dict[str, str], expected_candidate_names: dict[str, str],
    dataset_fingerprint: str, test_start: str, test_end: str, code_revision: str,
    returns: dict[str, Sequence[float]],
    doubled_cost_returns: dict[str, Sequence[float]], regimes: Sequence[str],
    min_observations: int = 180, bootstrap_trials: int = 2000,
    block_size: int = 5, seed: int = 20261118,
    reservation_experiment_id: str | None = None,
) -> dict:
    """Compare proposal with unchanged source and cash on one fresh paired window."""
    roles = {"proposal", "source", "cash"}
    if not isinstance(trial_ids, dict) or set(trial_ids) != roles:
        raise FreshEvidenceError("trial_ids must identify proposal, source, and cash")
    if not isinstance(expected_candidate_names, dict) or set(expected_candidate_names) != roles:
        raise FreshEvidenceError("expected_candidate_names must identify all three roles")
    if len(set(trial_ids.values())) != 3 or any(
        not isinstance(v, str) or not v.strip() for v in trial_ids.values()
    ):
        raise FreshEvidenceError("each role requires a distinct non-empty trial ID")
    if not isinstance(dataset_fingerprint, str) or len(dataset_fingerprint) != 64:
        raise FreshEvidenceError("dataset_fingerprint must be a SHA-256 digest")
    try:
        bytes.fromhex(dataset_fingerprint)
    except ValueError as exc:
        raise FreshEvidenceError("dataset_fingerprint must be a SHA-256 digest") from exc
    start, end = _stamp(test_start, "test_start"), _stamp(test_end, "test_end")
    if start >= end:
        raise FreshEvidenceError("test_start must precede test_end")
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise FreshEvidenceError("code_revision is required")
    if isinstance(min_observations, bool) or not isinstance(min_observations, int) or min_observations < 1:
        raise FreshEvidenceError("min_observations must be a positive integer")
    if isinstance(bootstrap_trials, bool) or not isinstance(bootstrap_trials, int) or bootstrap_trials < 100:
        raise FreshEvidenceError("bootstrap_trials must be at least 100")
    if isinstance(block_size, bool) or not isinstance(block_size, int) or block_size < 1:
        raise FreshEvidenceError("block_size must be positive")

    try:
        registry = load_candidate_registry(registry_path)
        prior = load_holdout_ledger(holdout_ledger_path)
    except (CandidateRegistryError, HoldoutLedgerError) as exc:
        raise FreshEvidenceError(f"provenance ledger failed integrity validation: {exc}") from exc
    registrations = {
        event["trial_id"]: event for item in registry["events"]
        if (event := item["event"])["type"] == "registered"
    }
    verified = {}
    for role in roles:
        trial_id = trial_ids[role]
        event = registrations.get(trial_id)
        if event is None:
            raise FreshEvidenceError(f"{role} trial is not preregistered")
        definition = event["definition"]
        if definition["candidate_name"] != expected_candidate_names[role]:
            raise FreshEvidenceError(f"{role} candidate identity differs from preregistration")
        if definition["dataset_fingerprint"] != dataset_fingerprint:
            raise FreshEvidenceError(f"{role} dataset fingerprint differs from preregistration")
        if definition["code_revision"] != code_revision:
            raise FreshEvidenceError(f"{role} code revision differs from preregistration")
        if _stamp(definition["test_start"], "registered test_start") != start:
            raise FreshEvidenceError(f"{role} registered test_start does not match")
        if _stamp(definition["test_end"], "registered test_end") != end:
            raise FreshEvidenceError(f"{role} registered test_end does not match")
        verified[role] = {
            "trial_id": trial_id, "candidate_name": definition["candidate_name"],
            "definition_hash": event["definition_hash"], "registered_at": event["registered_at"],
        }

    if reservation_experiment_id is not None:
        if not isinstance(reservation_experiment_id, str) or not reservation_experiment_id.strip():
            raise FreshEvidenceError("reservation_experiment_id must be non-empty")
        own = [item for item in prior if item.get("experiment_id") == reservation_experiment_id]
        if len(own) != 1:
            raise FreshEvidenceError("the experiment's exact holdout reservation is missing or ambiguous")
        reservation = own[0]
        if (reservation.get("dataset_fingerprint") != dataset_fingerprint
                or _stamp(reservation.get("test_start"), "reservation test_start") != start
                or _stamp(reservation.get("test_end"), "reservation test_end") != end):
            raise FreshEvidenceError("the experiment's holdout reservation does not match its registered window")
        # Exclude only this experiment's own pre-evaluation reservation. Every
        # other record remains in the audit and can still reject overlapping reuse.
        prior = [item for item in prior if item is not reservation]

    proposed_record = {
        "experiment_id": "fresh-evaluation:" + hashlib.sha256(
            "|".join(sorted(trial_ids.values())).encode("utf-8")
        ).hexdigest(),
        "dataset_fingerprint": dataset_fingerprint,
        "test_start": start.isoformat(), "test_end": end.isoformat(),
    }
    try:
        freshness = audit_holdout_reuse(prior, proposed_record)
    except HoldoutAuditError as exc:
        raise FreshEvidenceError(f"holdout history is invalid: {exc}") from exc
    if freshness["status"] != "no_overlap_detected":
        raise FreshEvidenceError("holdout interval has already been used; evaluation refused")

    if not isinstance(returns, dict) or set(returns) != roles:
        raise FreshEvidenceError("returns must contain exactly proposal, source, and cash")
    if not isinstance(doubled_cost_returns, dict) or set(doubled_cost_returns) != roles:
        raise FreshEvidenceError("doubled_cost_returns must contain all three roles")
    normalized = {r: _series(returns[r], f"returns.{r}") for r in roles}
    n = len(normalized["proposal"])
    if n < min_observations:
        raise FreshEvidenceError("insufficient observations; underpowered evidence cannot pass")
    if any(len(v) != n for v in normalized.values()):
        raise FreshEvidenceError("candidate return streams are not aligned")
    stress = {r: _series(doubled_cost_returns[r], f"doubled_cost_returns.{r}", n) for r in roles}
    if not isinstance(regimes, Sequence) or isinstance(regimes, (str, bytes)) or len(regimes) != n:
        raise FreshEvidenceError("regime labels must align exactly with all return streams")
    if any(not isinstance(x, str) or not x.strip() for x in regimes):
        raise FreshEvidenceError("regime labels must be non-empty strings")

    comparisons = {}
    for index, comparator in enumerate(("source", "cash")):
        lower, positive_share = _bootstrap_lower_edge(
            normalized["proposal"], normalized[comparator], trials=bootstrap_trials,
            seed=seed + index, block_size=block_size,
        )
        comparisons[comparator] = {
            "paired_edge_lower_5pct_pct_points": round(lower, 6),
            "bootstrap_positive_share_pct": round(positive_share * 100.0, 4),
            "proposal_compounded_return_pct": round(_compound(normalized["proposal"]), 6),
            "comparator_compounded_return_pct": round(_compound(normalized[comparator]), 6),
            "doubled_cost_proposal_return_pct": round(_compound(stress["proposal"]), 6),
            "doubled_cost_comparator_return_pct": round(_compound(stress[comparator]), 6),
        }
    regime_report = {}
    for label in sorted(set(regimes)):
        indices = [i for i, value in enumerate(regimes) if value == label]
        regime_return = _compound([stress["proposal"][i] for i in indices])
        regime_report[label] = {
            "observations": len(indices),
            "proposal_return_pct": round(_compound([normalized["proposal"][i] for i in indices]), 6),
            "proposal_doubled_cost_return_pct": round(regime_return, 6),
            "interpretation": "underpowered_unknown" if len(indices) < 10 else (
                "negative_after_doubled_costs" if regime_return < 0 else "descriptive_nonnegative"
            ),
        }
    gates = {
        "beats_source_on_compounded_return": _compound(normalized["proposal"]) > _compound(normalized["source"]),
        "beats_cash_on_compounded_return": _compound(normalized["proposal"]) > _compound(normalized["cash"]),
        "positive_paired_lower_bound_vs_source": comparisons["source"]["paired_edge_lower_5pct_pct_points"] > 0,
        "positive_paired_lower_bound_vs_cash": comparisons["cash"]["paired_edge_lower_5pct_pct_points"] > 0,
        "at_least_95pct_bootstrap_positive_vs_source": comparisons["source"]["bootstrap_positive_share_pct"] >= 95,
        "at_least_95pct_bootstrap_positive_vs_cash": comparisons["cash"]["bootstrap_positive_share_pct"] >= 95,
        "positive_compounded_return_at_doubled_costs": _compound(stress["proposal"]) > 0,
        "all_regimes_sufficiently_sampled_and_nonnegative_at_doubled_costs": all(
            item["observations"] >= 10 and item["proposal_doubled_cost_return_pct"] >= 0
            for item in regime_report.values()
        ),
    }
    return {
        "status": "eligible_for_human_review" if all(gates.values()) else "rejected_or_insufficient",
        "evaluation_type": "read_only_fresh_evidence",
        "provenance": {
            "dataset_fingerprint": dataset_fingerprint, "test_start": start.isoformat(),
            "test_end": end.isoformat(), "code_revision": code_revision,
            "observations": n, "trials": verified, "holdout_freshness": freshness["status"],
        },
        "comparisons": comparisons, "regime_robustness": regime_report, "gates": gates,
        "limitations": [
            "Bootstrap intervals are approximate and depend on block size and stationarity assumptions.",
            "Ledgers cannot prove that no unrecorded prior inspection occurred.",
            "Regime slices are descriptive and do not establish future profitability.",
            "Passing means human review only; no promotion, paper execution, or live orders are authorized.",
        ],
    }


def evaluate_completed_experiment(
    registry_path: str | Path, holdout_ledger_path: str | Path, *,
    plan_id: str, trial_ids: dict[str, str],
    expected_candidate_names: dict[str, str], dataset_fingerprint: str,
    test_start: str, test_end: str, code_revision: str,
    min_observations: int = 180, bootstrap_trials: int = 2000,
    block_size: int = 5, seed: int = 20261118,
) -> dict:
    """Evaluate the exact paired streams recorded by a completed controlled run.

    The run's own exact holdout reservation is recognized, but all other ledger
    records remain active reuse checks. No synthetic or scalar-only evidence is
    accepted, and this function never changes either ledger.
    """
    if not isinstance(plan_id, str) or not plan_id.strip():
        raise FreshEvidenceError("plan_id is required")
    roles = {"proposal", "source", "cash"}
    if not isinstance(trial_ids, dict) or set(trial_ids) != roles:
        raise FreshEvidenceError("trial_ids must identify proposal, source, and cash")
    try:
        registry = load_candidate_registry(registry_path)
    except CandidateRegistryError as exc:
        raise FreshEvidenceError(f"candidate registry failed integrity validation: {exc}") from exc
    completions = {
        event["trial_id"]: event
        for item in registry["events"]
        if (event := item["event"])["type"] == "completed"
    }
    outcomes = {}
    shared_regimes = shared_timestamps = None
    for role in ("proposal", "source", "cash"):
        completion = completions.get(trial_ids[role])
        if completion is None:
            raise FreshEvidenceError(f"{role} trial has no completed outcome")
        outcome = completion.get("outcome")
        if not isinstance(outcome, dict) or outcome.get("role") != role:
            raise FreshEvidenceError(f"{role} completed outcome has the wrong role")
        if outcome.get("plan_id") != plan_id:
            raise FreshEvidenceError(f"{role} completed outcome belongs to a different plan")
        returns = outcome.get("oos_returns")
        doubled = outcome.get("oos_returns_at_2x_cost")
        regimes = outcome.get("oos_regimes")
        timestamps = outcome.get("oos_timestamps")
        if not isinstance(regimes, list) or not isinstance(timestamps, list):
            raise FreshEvidenceError(f"{role} outcome is missing aligned regime/timestamp evidence")
        if shared_regimes is None:
            shared_regimes, shared_timestamps = regimes, timestamps
        elif regimes != shared_regimes or timestamps != shared_timestamps:
            raise FreshEvidenceError("completed candidate outcomes do not share identical OOS dates and regimes")
        outcomes[role] = (returns, doubled)
    if not shared_timestamps or len(shared_timestamps) != len(shared_regimes):
        raise FreshEvidenceError("completed experiment has no aligned OOS timestamps")
    parsed_timestamps = [_stamp(value, "OOS timestamp") for value in shared_timestamps]
    if any(parsed_timestamps[i] <= parsed_timestamps[i - 1] for i in range(1, len(parsed_timestamps))):
        raise FreshEvidenceError("OOS timestamps must be strictly increasing")
    start, end = _stamp(test_start, "test_start"), _stamp(test_end, "test_end")
    if parsed_timestamps[0] <= start or parsed_timestamps[-1] != end:
        raise FreshEvidenceError("OOS timestamps do not exactly terminate at the registered test window")
    return evaluate_fresh_candidate(
        registry_path, holdout_ledger_path,
        trial_ids=trial_ids,
        expected_candidate_names=expected_candidate_names,
        dataset_fingerprint=dataset_fingerprint,
        test_start=test_start, test_end=test_end, code_revision=code_revision,
        returns={role: outcomes[role][0] for role in roles},
        doubled_cost_returns={role: outcomes[role][1] for role in roles},
        regimes=shared_regimes,
        min_observations=min_observations,
        bootstrap_trials=bootstrap_trials, block_size=block_size, seed=seed,
        reservation_experiment_id=f"walk-forward:{plan_id}",
    )
