"""Append-only, hash-chained registry for pre-registered strategy trials.

This is an accountability ledger, not proof that a registration happened before
an experiment outside this process. Call register_candidate_trial before any
holdout evaluation, then complete_candidate_trial exactly once afterwards.
Single-writer operation is required.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any


class CandidateRegistryError(ValueError):
    """Raised when a candidate registry is malformed or an operation is unsafe."""


_SCHEMA_VERSION = 1
_ZERO_HASH = "0" * 64


def _canonical(value: Any) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise CandidateRegistryError("registry values must be finite JSON data") from exc


def _timestamp(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise CandidateRegistryError(f"{field} must be an ISO-8601 timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CandidateRegistryError(f"{field} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise CandidateRegistryError(f"{field} must include a timezone")
    return parsed.isoformat()


def _sha256(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise CandidateRegistryError(f"{field} must be a SHA-256 hex digest")
    try:
        bytes.fromhex(value)
    except ValueError as exc:
        raise CandidateRegistryError(f"{field} must be a SHA-256 hex digest") from exc
    return value.lower()


def _empty() -> dict[str, Any]:
    return {"schema_version": _SCHEMA_VERSION, "events": []}


def _event_hash(previous_hash: str, event: dict[str, Any]) -> str:
    payload = _canonical({"previous_hash": previous_hash, "event": event})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_candidate_registry(path: str | Path) -> dict[str, Any]:
    """Load and fully verify a registry. A missing file is an empty registry."""
    target = Path(path)
    if not target.exists():
        return _empty()
    try:
        data = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CandidateRegistryError("candidate registry is unreadable or invalid JSON") from exc
    if not isinstance(data, dict) or data.get("schema_version") != _SCHEMA_VERSION:
        raise CandidateRegistryError("unsupported candidate registry schema")
    events = data.get("events")
    if not isinstance(events, list):
        raise CandidateRegistryError("candidate registry events must be a list")
    previous = _ZERO_HASH
    seen_trials: dict[str, str] = {}
    completed: set[str] = set()
    for index, item in enumerate(events):
        if not isinstance(item, dict) or set(item) != {"event", "previous_hash", "event_hash"}:
            raise CandidateRegistryError(f"malformed candidate registry event at index {index}")
        event = item["event"]
        if not isinstance(event, dict) or item["previous_hash"] != previous:
            raise CandidateRegistryError(f"broken candidate registry hash chain at index {index}")
        expected = _event_hash(previous, event)
        if item["event_hash"] != expected:
            raise CandidateRegistryError(f"candidate registry integrity failure at index {index}")
        kind = event.get("type")
        trial_id = event.get("trial_id")
        if not isinstance(trial_id, str) or not trial_id.strip():
            raise CandidateRegistryError(f"invalid trial id at index {index}")
        if kind == "registered":
            if trial_id in seen_trials:
                raise CandidateRegistryError("duplicate candidate trial registration")
            seen_trials[trial_id] = event.get("definition_hash")
        elif kind == "completed":
            if trial_id not in seen_trials or trial_id in completed:
                raise CandidateRegistryError("orphan or duplicate candidate completion")
            if event.get("definition_hash") != seen_trials[trial_id]:
                raise CandidateRegistryError("candidate definition changed after registration")
            completed.add(trial_id)
        else:
            raise CandidateRegistryError(f"unknown candidate registry event type at index {index}")
        previous = expected
    return data


def _append(path: str | Path, event: dict[str, Any]) -> dict[str, Any]:
    target = Path(path)
    data = load_candidate_registry(target)
    previous = data["events"][-1]["event_hash"] if data["events"] else _ZERO_HASH
    data["events"].append({
        "event": event,
        "previous_hash": previous,
        "event_hash": _event_hash(previous, event),
    })
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(_canonical(data) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        try:
            directory_fd = os.open(str(target.parent), os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            pass
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return data


def register_candidate_trial(
    path: str | Path,
    *,
    trial_id: str,
    candidate_name: str,
    strategy_definition: dict[str, Any],
    dataset_fingerprint: str,
    code_revision: str,
    test_start: str,
    test_end: str,
    registered_at: str,
) -> dict[str, Any]:
    """Persist immutable candidate identity before holdout evaluation begins."""
    if not isinstance(trial_id, str) or not trial_id.strip():
        raise CandidateRegistryError("trial_id must be non-empty")
    if not isinstance(candidate_name, str) or not candidate_name.strip():
        raise CandidateRegistryError("candidate_name must be non-empty")
    if not isinstance(strategy_definition, dict) or not strategy_definition:
        raise CandidateRegistryError("strategy_definition must be a non-empty JSON object")
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise CandidateRegistryError("code_revision must be non-empty")
    fingerprint = _sha256(dataset_fingerprint, "dataset_fingerprint")
    start, end = _timestamp(test_start, "test_start"), _timestamp(test_end, "test_end")
    if datetime.fromisoformat(start) >= datetime.fromisoformat(end):
        raise CandidateRegistryError("test_start must precede test_end")
    registered = _timestamp(registered_at, "registered_at")
    definition = {
        "candidate_name": candidate_name,
        "strategy_definition": strategy_definition,
        "dataset_fingerprint": fingerprint,
        "code_revision": code_revision,
        "test_start": start,
        "test_end": end,
    }
    definition_hash = hashlib.sha256(_canonical(definition).encode("utf-8")).hexdigest()
    existing = load_candidate_registry(path)
    if any(e["event"].get("trial_id") == trial_id for e in existing["events"]):
        raise CandidateRegistryError("trial_id has already been registered")
    return _append(path, {
        "type": "registered",
        "trial_id": trial_id,
        "registered_at": registered,
        "definition": definition,
        "definition_hash": definition_hash,
    })


def complete_candidate_trial(
    path: str | Path, *, trial_id: str, outcome: dict[str, Any], completed_at: str
) -> dict[str, Any]:
    """Attach results once; never alter the pre-registered definition."""
    if not isinstance(outcome, dict) or not outcome:
        raise CandidateRegistryError("outcome must be a non-empty JSON object")
    completed = _timestamp(completed_at, "completed_at")
    data = load_candidate_registry(path)
    registrations = {
        e["event"]["trial_id"]: e["event"]
        for e in data["events"] if e["event"]["type"] == "registered"
    }
    done = {
        e["event"]["trial_id"] for e in data["events"]
        if e["event"]["type"] == "completed"
    }
    if trial_id not in registrations:
        raise CandidateRegistryError("candidate trial must be registered before completion")
    if trial_id in done:
        raise CandidateRegistryError("candidate trial is already completed")
    registration = registrations[trial_id]
    return _append(path, {
        "type": "completed",
        "trial_id": trial_id,
        "completed_at": completed,
        "definition_hash": registration["definition_hash"],
        "outcome": outcome,
    })


def audit_candidate_family(
    path: str | Path, *, dataset_fingerprint: str, test_start: str, test_end: str
) -> dict[str, Any]:
    """Count every registered trial on the same dataset with overlapping test windows."""
    fingerprint = _sha256(dataset_fingerprint, "dataset_fingerprint")
    start, end = _timestamp(test_start, "test_start"), _timestamp(test_end, "test_end")
    if datetime.fromisoformat(start) >= datetime.fromisoformat(end):
        raise CandidateRegistryError("test_start must precede test_end")
    data = load_candidate_registry(path)
    completions = {
        e["event"]["trial_id"] for e in data["events"]
        if e["event"]["type"] == "completed"
    }
    matches = []
    for item in data["events"]:
        event = item["event"]
        if event["type"] != "registered":
            continue
        definition = event["definition"]
        if definition["dataset_fingerprint"] != fingerprint:
            continue
        overlaps = definition["test_start"] <= end and start <= definition["test_end"]
        if overlaps:
            matches.append({
                "trial_id": event["trial_id"],
                "candidate_name": definition["candidate_name"],
                "definition_hash": event["definition_hash"],
                "completed": event["trial_id"] in completions,
            })
    return {
        "status": "complete" if matches and all(item["completed"] for item in matches) else "review_required",
        "candidate_count": len(matches),
        "registered_trials": matches,
        "incomplete_trials": [item["trial_id"] for item in matches if not item["completed"]],
        "warning": "This ledger counts only trials registered here; it cannot prove unrecorded experiments did not occur. Single-writer operation is required.",
    }
