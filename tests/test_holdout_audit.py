from datetime import datetime, timezone

import pytest

from bitcoin_ai.holdout_audit import HoldoutAuditError, audit_holdout_reuse


FINGERPRINT = "a" * 64


def record(experiment_id, start, end, fingerprint=FINGERPRINT):
    return {
        "experiment_id": experiment_id,
        "dataset_fingerprint": fingerprint,
        "test_start": start,
        "test_end": end,
    }


def test_flags_overlapping_window_on_same_dataset():
    result = audit_holdout_reuse(
        [record("old-run", "2025-01-01T00:00:00Z", "2025-01-10T00:00:00Z")],
        record("new-run", "2025-01-10T00:00:00+00:00", "2025-01-20T00:00:00+00:00"),
    )
    assert result["status"] == "reuse_detected"
    assert result["eligible_for_fresh_holdout_review"] is False
    assert result["conflict_count"] == 1


def test_allows_non_overlapping_window_on_same_dataset():
    result = audit_holdout_reuse(
        [record("old-run", "2025-01-01T00:00:00Z", "2025-01-10T00:00:00Z")],
        record("new-run", "2025-01-11T00:00:00Z", "2025-01-20T00:00:00Z"),
    )
    assert result["status"] == "no_overlap_detected"
    assert result["eligible_for_fresh_holdout_review"] is True


def test_different_dataset_fingerprint_does_not_conflict():
    result = audit_holdout_reuse(
        [record("old-run", "2025-01-01T00:00:00Z", "2025-01-10T00:00:00Z")],
        record("new-run", "2025-01-05T00:00:00Z", "2025-01-20T00:00:00Z", "b" * 64),
    )
    assert result["conflict_count"] == 0


@pytest.mark.parametrize("bad", [
    record("run", "2025-01-02T00:00:00Z", "2025-01-01T00:00:00Z"),
    record("run", "2025-01-01T00:00:00", "2025-01-02T00:00:00Z"),
    record("run", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z", "not-a-hash"),
])
def test_rejects_invalid_proposed_record(bad):
    with pytest.raises(HoldoutAuditError):
        audit_holdout_reuse([], bad)


def test_rejects_malformed_ledger_entry():
    with pytest.raises(HoldoutAuditError):
        audit_holdout_reuse([{"experiment_id": "missing-fields"}], record(
            "new", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"
        ))


def test_requires_list_ledger():
    with pytest.raises(HoldoutAuditError):
        audit_holdout_reuse(None, record(
            "new", "2025-01-01T00:00:00Z", "2025-01-02T00:00:00Z"
        ))
