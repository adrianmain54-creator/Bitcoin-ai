from datetime import datetime, timedelta, timezone
import json

import pytest

from bitcoin_ai.candidate_registry import (
    CandidateRegistryError,
    audit_candidate_family,
    complete_candidate_trial,
    load_candidate_registry,
    register_candidate_trial,
)


FINGERPRINT = "a" * 64
START = "2025-01-01T00:00:00+00:00"
END = "2025-02-01T00:00:00+00:00"


def register(path, trial_id="trial-1", name="momentum"):
    return register_candidate_trial(
        path,
        trial_id=trial_id,
        candidate_name=name,
        strategy_definition={"lookback": 20, "fees_bps": 10, "timeframe": "1d"},
        dataset_fingerprint=FINGERPRINT,
        code_revision="abc123",
        test_start=START,
        test_end=END,
        registered_at="2024-12-01T00:00:00+00:00",
    )


def test_registration_precedes_completion_and_family_counts_all_trials(tmp_path):
    path = tmp_path / "trials.json"
    register(path, "one", "momentum")
    register(path, "two", "mean-reversion")
    audit = audit_candidate_family(
        path, dataset_fingerprint=FINGERPRINT, test_start=START, test_end=END
    )
    assert audit["candidate_count"] == 2
    assert audit["status"] == "review_required"
    assert audit["incomplete_trials"] == ["one", "two"]

    complete_candidate_trial(
        path, trial_id="one", outcome={"return_pct": 3.2, "p_value": 0.01},
        completed_at="2025-02-02T00:00:00+00:00",
    )
    audit = audit_candidate_family(
        path, dataset_fingerprint=FINGERPRINT, test_start=START, test_end=END
    )
    assert audit["candidate_count"] == 2
    assert audit["incomplete_trials"] == ["two"]


def test_rejects_duplicate_registration_and_second_completion(tmp_path):
    path = tmp_path / "trials.json"
    register(path)
    with pytest.raises(CandidateRegistryError, match="already been registered"):
        register(path)
    complete_candidate_trial(
        path, trial_id="trial-1", outcome={"return_pct": 1},
        completed_at="2025-02-02T00:00:00+00:00",
    )
    with pytest.raises(CandidateRegistryError, match="already completed"):
        complete_candidate_trial(
            path, trial_id="trial-1", outcome={"return_pct": 2},
            completed_at="2025-02-03T00:00:00+00:00",
        )


def test_cannot_complete_unregistered_trial(tmp_path):
    with pytest.raises(CandidateRegistryError, match="registered before completion"):
        complete_candidate_trial(
            tmp_path / "trials.json", trial_id="unknown", outcome={"return_pct": 1},
            completed_at="2025-02-02T00:00:00+00:00",
        )


def test_audit_ignores_other_datasets_and_non_overlapping_windows(tmp_path):
    path = tmp_path / "trials.json"
    register(path)
    other = register_candidate_trial(
        path, trial_id="other-data", candidate_name="other",
        strategy_definition={"lookback": 5}, dataset_fingerprint="b" * 64,
        code_revision="abc123", test_start=START, test_end=END,
        registered_at="2024-12-01T00:00:00+00:00",
    )
    audit = audit_candidate_family(
        path, dataset_fingerprint="b" * 64,
        test_start="2025-03-01T00:00:00+00:00",
        test_end="2025-04-01T00:00:00+00:00",
    )
    assert audit["candidate_count"] == 0
    assert audit["status"] == "review_required"


@pytest.mark.parametrize("kwargs", [
    {"dataset_fingerprint": "bad"},
    {"test_start": "2025-01-01T00:00:00"},
    {"test_end": "2024-12-01T00:00:00+00:00"},
])
def test_rejects_invalid_registration_fields(tmp_path, kwargs):
    values = dict(
        trial_id="x", candidate_name="x", strategy_definition={"x": 1},
        dataset_fingerprint=FINGERPRINT, code_revision="abc",
        test_start=START, test_end=END, registered_at=START,
    )
    values.update(kwargs)
    with pytest.raises(CandidateRegistryError):
        register_candidate_trial(tmp_path / "trials.json", **values)


def test_detects_tampering(tmp_path):
    path = tmp_path / "trials.json"
    register(path)
    data = json.loads(path.read_text())
    data["events"][0]["event"]["definition"]["candidate_name"] = "rewritten"
    path.write_text(json.dumps(data))
    with pytest.raises(CandidateRegistryError, match="integrity failure"):
        load_candidate_registry(path)


def test_registration_after_holdout_start_is_rejected(tmp_path):
    with pytest.raises(CandidateRegistryError, match="before its holdout window"):
        register_candidate_trial(
            tmp_path / "trials.json",
            trial_id="late", candidate_name="late",
            strategy_definition={"lookback": 10},
            dataset_fingerprint=FINGERPRINT, code_revision="abc123",
            test_start=START, test_end=END,
            registered_at="2025-01-02T00:00:00+00:00",
        )


def test_completion_before_holdout_end_is_rejected(tmp_path):
    path = tmp_path / "trials.json"
    register(path)
    with pytest.raises(CandidateRegistryError, match="before its holdout window ends"):
        complete_candidate_trial(
            path, trial_id="trial-1", outcome={"return_pct": 1},
            completed_at="2025-01-15T00:00:00+00:00",
        )
