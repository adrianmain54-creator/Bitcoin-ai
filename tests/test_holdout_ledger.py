from datetime import datetime, timezone
import json

import pytest

from bitcoin_ai.holdout_ledger import (
    HoldoutLedgerError,
    audit_and_append_holdout_records,
    load_holdout_ledger,
)


FINGERPRINT = "a" * 64


def record(run, start="2025-01-01T00:00:00+00:00", end="2025-01-10T00:00:00+00:00"):
    return {
        "experiment_id": run,
        "dataset_fingerprint": FINGERPRINT,
        "test_start": start,
        "test_end": end,
    }


def test_missing_ledger_is_an_empty_history(tmp_path):
    path = tmp_path / "ledger.json"
    assert load_holdout_ledger(path) == []


def test_appends_and_reloads_hash_chained_records(tmp_path):
    path = tmp_path / "nested" / "ledger.json"
    first = record("run-1")
    result = audit_and_append_holdout_records(path, [first])
    assert result["appended_record_count"] == 1
    assert result["status"] == "no_overlap_detected"
    assert load_holdout_ledger(path) == [first]
    raw = json.loads(path.read_text())
    assert raw["schema_version"] == 1
    assert len(raw["records"][0]["entry_hash"]) == 64


def test_reuse_is_detected_and_attempt_is_still_appended(tmp_path):
    path = tmp_path / "ledger.json"
    first = record("run-1")
    second = record("run-2", "2025-01-05T00:00:00+00:00", "2025-01-15T00:00:00+00:00")
    audit_and_append_holdout_records(path, [first])
    result = audit_and_append_holdout_records(path, [second])
    assert result["status"] == "reuse_detected"
    assert result["eligible_for_fresh_holdout_review"] is False
    assert result["appended_record_count"] == 1
    assert [item["experiment_id"] for item in load_holdout_ledger(path)] == ["run-1", "run-2"]


def test_rejects_modified_record_or_broken_hash_chain(tmp_path):
    path = tmp_path / "ledger.json"
    audit_and_append_holdout_records(path, [record("run-1")])
    raw = json.loads(path.read_text())
    raw["records"][0]["record"]["experiment_id"] = "tampered"
    path.write_text(json.dumps(raw))
    with pytest.raises(HoldoutLedgerError, match="integrity"):
        load_holdout_ledger(path)


def test_refuses_corrupt_json_without_overwriting(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text("{broken")
    with pytest.raises(HoldoutLedgerError):
        audit_and_append_holdout_records(path, [record("run-1")])
    assert path.read_text() == "{broken"


def test_refuses_malformed_schema(tmp_path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps({"schema_version": 99, "records": []}))
    with pytest.raises(HoldoutLedgerError):
        load_holdout_ledger(path)



def test_detects_overlapping_folds_inside_same_run(tmp_path):
    path = tmp_path / "ledger.json"
    first = record("run-1:fold-1")
    second = record(
        "run-1:fold-2",
        "2025-01-05T00:00:00+00:00",
        "2025-01-15T00:00:00+00:00",
    )
    result = audit_and_append_holdout_records(path, [first, second])
    assert result["status"] == "reuse_detected"
    assert result["fold_audits"][0]["status"] == "no_overlap_detected"
    assert result["fold_audits"][1]["status"] == "reuse_detected"
    assert result["appended_record_count"] == 2


def test_duplicate_experiment_id_is_rejected_without_mutation(tmp_path):
    path = tmp_path / "ledger.json"
    first = record("run-1")
    audit_and_append_holdout_records(path, [first])
    before = path.read_bytes()
    with pytest.raises(HoldoutLedgerError, match="Duplicate experiment_id"):
        audit_and_append_holdout_records(path, [record("run-1")])
    assert path.read_bytes() == before
