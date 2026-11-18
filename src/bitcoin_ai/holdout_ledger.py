"""Durable, tamper-evident append-only storage for holdout audit records.

The ledger is single-writer: concurrent writers to the same path are unsupported.
Writes use fsync + atomic replace; malformed or tampered files fail closed.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import tempfile

from .holdout_audit import HoldoutAuditError, audit_holdout_reuse

_SCHEMA_VERSION = 1
_ZERO_HASH = "0" * 64


class HoldoutLedgerError(ValueError):
    """Raised when a persistent holdout ledger cannot be trusted or updated."""


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _entry_hash(record, previous_hash):
    payload = {"record": record, "previous_hash": previous_hash}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


def load_holdout_ledger(path):
    """Load and fully verify a ledger; a missing path means an empty ledger."""
    ledger_path = Path(path)
    if not ledger_path.exists():
        return []
    try:
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HoldoutLedgerError(f"Cannot read holdout ledger safely: {exc}") from exc
    if not isinstance(raw, dict) or set(raw) != {"schema_version", "records"}:
        raise HoldoutLedgerError("Ledger must contain exactly schema_version and records")
    if raw["schema_version"] != _SCHEMA_VERSION or not isinstance(raw["records"], list):
        raise HoldoutLedgerError("Unsupported ledger schema or invalid records list")
    verified = []
    previous_hash = _ZERO_HASH
    for index, item in enumerate(raw["records"]):
        if not isinstance(item, dict) or set(item) != {"record", "previous_hash", "entry_hash"}:
            raise HoldoutLedgerError(f"Ledger entry {index} has an invalid envelope")
        record = item["record"]
        try:
            # Reuse the strict public schema/timestamp validation.
            audit_holdout_reuse([], record)
        except HoldoutAuditError as exc:
            raise HoldoutLedgerError(f"Ledger entry {index} is invalid: {exc}") from exc
        if item["previous_hash"] != previous_hash:
            raise HoldoutLedgerError(f"Ledger hash chain is broken at entry {index}")
        expected = _entry_hash(record, previous_hash)
        if item["entry_hash"] != expected:
            raise HoldoutLedgerError(f"Ledger entry {index} failed integrity verification")
        verified.append(record)
        previous_hash = expected
    return verified


def _atomic_write(path, records):
    ledger_path = Path(path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (_canonical({"schema_version": _SCHEMA_VERSION, "records": records}) + "\n").encode("utf-8")
    fd, temp_name = tempfile.mkstemp(prefix=f".{ledger_path.name}.", suffix=".tmp", dir=str(ledger_path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, ledger_path)
        # Best-effort directory fsync so the rename itself is durable on POSIX.
        try:
            dir_fd = os.open(str(ledger_path.parent), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except OSError:
            pass
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def audit_and_append_holdout_records(path, proposed_records):
    """Audit proposed folds against prior history, then append every attempt.

    Records are appended even when overlap is detected, so repeated attempts remain
    visible. This operation assumes a single writer for the ledger path.
    """
    if not isinstance(proposed_records, list):
        raise HoldoutLedgerError("proposed_records must be a list")
    prior = load_holdout_ledger(path)
    audits = [audit_holdout_reuse(prior, record) for record in proposed_records]
    # Validate the whole batch before mutating persistent state.
    envelopes = []
    previous_hash = _ZERO_HASH
    ledger_path = Path(path)
    if ledger_path.exists():
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
        if raw["records"]:
            previous_hash = raw["records"][-1]["entry_hash"]
    else:
        previous_hash = _ZERO_HASH
    # Preserve existing envelopes byte-for-byte semantically after verification.
    if ledger_path.exists():
        raw = json.loads(ledger_path.read_text(encoding="utf-8"))
        envelopes.extend(raw["records"])
    for record in proposed_records:
        entry_hash = _entry_hash(record, previous_hash)
        envelopes.append({
            "record": record,
            "previous_hash": previous_hash,
            "entry_hash": entry_hash,
        })
        previous_hash = entry_hash
    if proposed_records:
        _atomic_write(path, envelopes)
    return {
        "status": "reuse_detected" if any(a["status"] == "reuse_detected" for a in audits) else "no_overlap_detected",
        "prior_record_count": len(prior),
        "appended_record_count": len(proposed_records),
        "fold_audits": audits,
        "eligible_for_fresh_holdout_review": bool(prior is not None) and not any(
            a["status"] == "reuse_detected" for a in audits
        ),
        "ledger_path": str(path),
        "integrity": "verified_hash_chain",
        "concurrency": "single_writer_only",
        "warning": "A clean audit is only as complete as this ledger and does not prove statistical independence or profitability.",
    }
