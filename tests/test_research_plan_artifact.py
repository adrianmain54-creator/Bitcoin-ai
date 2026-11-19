import copy
import hashlib
import json

import pytest

from bitcoin_ai.research_plan_artifact import PlanArtifactError, audit_plan_artifact


def _artifact():
    plan = {
        "task_id": "queued-1",
        "dataset_fingerprint": "a" * 64,
        "symbol": "BTC-USDT",
        "interval": "5m",
        "sources": ["binance", "coinbase", "kraken"],
        "row_count": 81,
        "train_bars": 50,
        "test_bars": 10,
        "test_window": {
            "start": "2026-01-01T00:50:00+00:00",
            "end": "2026-01-01T01:20:00+00:00",
        },
        "code_revision": "abc123",
        "candidates": {
            "proposal": {"family": "momentum", "lookback": 5},
            "unchanged_source": {"family": "sma", "lookback": 12},
            "cash": {"family": "cash", "lookback": 2},
        },
        "costs_bps": {"fee": 10.0, "slippage": 5.0},
    }
    digest = hashlib.sha256(json.dumps(
        plan, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    return {
        "status": "plan_prepared", "plan_id": digest, "plan": plan,
        "execution_authority": "none", "side_effects": [],
    }


def test_audits_portable_plan_and_reports_complete_provenance():
    report = audit_plan_artifact(_artifact())
    assert report["status"] == "plan_integrity_verified"
    assert report["dataset"]["fingerprint"] == "a" * 64
    assert report["dataset"]["sources"] == ["binance", "coinbase", "kraken"]
    assert report["experiment"]["code_revision"] == "abc123"
    assert report["execution_authority"] == "none"


def test_rejects_modified_plan_contents():
    artifact = _artifact()
    artifact["plan"]["code_revision"] = "different"
    with pytest.raises(PlanArtifactError, match="does not match"):
        audit_plan_artifact(artifact)


@pytest.mark.parametrize("mutation, message", [
    (lambda p: p.update(sources=["binance", "binance", "kraken"]), "three unique"),
    (lambda p: p.update(row_count=82), "exact walk-forward"),
    (lambda p: p.update(dataset_fingerprint="z" * 64), "hexadecimal"),
    (lambda p: p["candidates"].update(unchanged_source={"family": "momentum", "lookback": 5}), "distinct"),
    (lambda p: p["costs_bps"].update(fee=float("nan")), "does not match"),
    (lambda p: p["test_window"].update(end="2025-01-01T00:00:00"), "does not match"),
])
def test_rejects_invalid_or_tampered_provenance(mutation, message):
    artifact = _artifact()
    mutation(artifact["plan"])
    if message != "does not match":
        artifact["plan_id"] = hashlib.sha256(json.dumps(
            artifact["plan"], sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()).hexdigest()
    with pytest.raises((PlanArtifactError, ValueError)):
        audit_plan_artifact(artifact)


def test_rejects_execution_authority_or_side_effects():
    artifact = _artifact()
    artifact["execution_authority"] = "paper"
    with pytest.raises(PlanArtifactError, match="no execution authority"):
        audit_plan_artifact(artifact)


def test_rejects_digest_that_is_not_a_sha256_of_plan():
    artifact = _artifact()
    artifact["plan_id"] = "0" * 64
    with pytest.raises(PlanArtifactError, match="does not match"):
        audit_plan_artifact(artifact)
