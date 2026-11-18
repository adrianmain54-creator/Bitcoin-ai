"""Detect reuse of the same held-out market interval across research experiments.

This is an audit helper: callers must persist prior experiment records themselves.
It does not make a holdout statistically independent or prevent adaptive research.
"""
from __future__ import annotations

from datetime import datetime
import re


class HoldoutAuditError(ValueError):
    """Raised when an experiment ledger record is malformed."""


_REQUIRED = {"experiment_id", "dataset_fingerprint", "test_start", "test_end"}
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


def _parse_record(record, label):
    if not isinstance(record, dict) or set(record) != _REQUIRED:
        raise HoldoutAuditError(
            f"{label} must contain exactly: {', '.join(sorted(_REQUIRED))}"
        )
    experiment_id = record["experiment_id"]
    fingerprint = record["dataset_fingerprint"]
    if not isinstance(experiment_id, str) or not experiment_id.strip():
        raise HoldoutAuditError(f"{label}.experiment_id must be a non-empty string")
    if not isinstance(fingerprint, str) or not _FINGERPRINT.fullmatch(fingerprint):
        raise HoldoutAuditError(
            f"{label}.dataset_fingerprint must be a lowercase SHA-256 hex digest"
        )
    parsed = []
    for field in ("test_start", "test_end"):
        value = record[field]
        if not isinstance(value, str):
            raise HoldoutAuditError(f"{label}.{field} must be an ISO-8601 string")
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HoldoutAuditError(f"{label}.{field} is not a valid ISO-8601 timestamp") from exc
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            raise HoldoutAuditError(f"{label}.{field} must include a timezone")
        parsed.append(stamp)
    start, end = parsed
    if end < start:
        raise HoldoutAuditError(f"{label}.test_end must not precede test_start")
    return {
        "experiment_id": experiment_id,
        "dataset_fingerprint": fingerprint,
        "test_start": start,
        "test_end": end,
    }


def audit_holdout_reuse(previous_experiments, proposed_experiment):
    """Flag inclusive time overlap on an identical immutable dataset fingerprint.

    A dataset fingerprint should be SHA-256 over the canonical source dataset
    (including timestamps, prices, and relevant adjustment/source metadata).
    Distinct datasets do not conflict merely because their timestamps overlap.
    """
    if not isinstance(previous_experiments, list):
        raise HoldoutAuditError("previous_experiments must be a list")
    proposed = _parse_record(proposed_experiment, "proposed_experiment")
    conflicts = []
    for index, raw in enumerate(previous_experiments):
        prior = _parse_record(raw, f"previous_experiments[{index}]")
        if prior["dataset_fingerprint"] != proposed["dataset_fingerprint"]:
            continue
        overlaps = (
            proposed["test_start"] <= prior["test_end"]
            and prior["test_start"] <= proposed["test_end"]
        )
        if overlaps:
            conflicts.append({
                "experiment_id": prior["experiment_id"],
                "test_start": prior["test_start"].isoformat(),
                "test_end": prior["test_end"].isoformat(),
            })
    return {
        "status": "reuse_detected" if conflicts else "no_overlap_detected",
        "eligible_for_fresh_holdout_review": not conflicts,
        "conflict_count": len(conflicts),
        "conflicts": conflicts,
        "proposed_experiment_id": proposed["experiment_id"],
        "dataset_fingerprint": proposed["dataset_fingerprint"],
        "interpretation": (
            "A previously inspected interval on the same dataset fingerprint overlaps "
            "this proposed test window. Treat it as exposed research data; do not call "
            "it a fresh holdout."
            if conflicts else
            "No overlapping prior interval was found in the supplied ledger. This is "
            "only as complete as that ledger and does not prove independence."
        ),
        "limitations": [
            "The caller must maintain an append-only, complete experiment ledger.",
            "A dataset fingerprint must cover every input that can change the observed series.",
            "Non-overlap does not prevent indirect adaptive leakage through repeated strategy design.",
            "This audit is not a statistical test and does not establish profitability.",
        ],
    }
