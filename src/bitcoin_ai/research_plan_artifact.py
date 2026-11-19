"""Verify portable research-plan provenance without fetching data or running trials.

The audit checks the deterministic plan digest and the provenance fields carried
by the portable artifact. It cannot independently prove that a dataset was fresh,
unused, or faithfully fetched; those claims require the original source and ledgers.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sys


class PlanArtifactError(ValueError):
    """A portable plan artifact is malformed or its digest does not match."""


def _aware_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise PlanArtifactError(f"{field} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise PlanArtifactError(f"{field} must be a valid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise PlanArtifactError(f"{field} must include a timezone")
    return parsed


def audit_plan_artifact(artifact: dict) -> dict:
    """Return a deterministic provenance audit for one plan-only JSON artifact."""
    if not isinstance(artifact, dict) or artifact.get("status") != "plan_prepared":
        raise PlanArtifactError("artifact must have status plan_prepared")
    if artifact.get("execution_authority") != "none" or artifact.get("side_effects") != []:
        raise PlanArtifactError("artifact must declare no execution authority and no side effects")
    plan = artifact.get("plan")
    if not isinstance(plan, dict):
        raise PlanArtifactError("artifact plan must be an object")
    expected_id = hashlib.sha256(json.dumps(
        plan, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()
    if artifact.get("plan_id") != expected_id:
        raise PlanArtifactError("plan_id does not match the canonical plan contents")

    required = {
        "task_id", "dataset_fingerprint", "symbol", "interval", "sources",
        "row_count", "train_bars", "test_bars", "test_window", "code_revision",
        "candidates", "costs_bps",
    }
    missing = required - set(plan)
    if missing:
        raise PlanArtifactError(f"plan is missing provenance fields: {', '.join(sorted(missing))}")
    if not isinstance(plan["task_id"], str) or not plan["task_id"].strip():
        raise PlanArtifactError("task_id is required")
    if plan["symbol"] != "BTC-USDT":
        raise PlanArtifactError("only BTC-USDT plan artifacts are supported")
    if not isinstance(plan["interval"], str) or not plan["interval"]:
        raise PlanArtifactError("interval is required")
    revision = plan["code_revision"]
    if not isinstance(revision, str) or not revision.strip():
        raise PlanArtifactError("code_revision is required")

    fingerprint = plan["dataset_fingerprint"]
    if not isinstance(fingerprint, str) or len(fingerprint) != 64:
        raise PlanArtifactError("dataset fingerprint must be a 64-character SHA-256")
    try:
        bytes.fromhex(fingerprint)
    except ValueError as exc:
        raise PlanArtifactError("dataset fingerprint must be hexadecimal") from exc

    sources = plan["sources"]
    if (not isinstance(sources, list) or len(sources) < 3
            or any(not isinstance(source, str) or not source for source in sources)
            or len(set(sources)) != len(sources)):
        raise PlanArtifactError("plan must identify at least three unique source venues")

    row_count, train_bars, test_bars = (
        plan["row_count"], plan["train_bars"], plan["test_bars"]
    )
    for value, name, minimum in (
        (row_count, "row_count", 4), (train_bars, "train_bars", 3),
        (test_bars, "test_bars", 3),
    ):
        if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
            raise PlanArtifactError(f"{name} must be an integer >= {minimum}")
    cursor, last_test_index = train_bars, None
    while cursor + test_bars < row_count:
        last_test_index = cursor + test_bars
        cursor += test_bars
    if last_test_index is None or last_test_index != row_count - 1:
        raise PlanArtifactError("row_count does not terminate on the exact walk-forward test boundary")

    window = plan["test_window"]
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        raise PlanArtifactError("test_window must contain exactly start and end")
    start = _aware_timestamp(window["start"], "test_window.start")
    end = _aware_timestamp(window["end"], "test_window.end")
    if end <= start:
        raise PlanArtifactError("test_window.end must be later than test_window.start")

    candidates = plan["candidates"]
    if not isinstance(candidates, dict) or set(candidates) != {
        "proposal", "unchanged_source", "cash"
    }:
        raise PlanArtifactError("candidate roles must be proposal, unchanged_source, and cash")
    definitions = []
    for role in ("proposal", "unchanged_source", "cash"):
        definition = candidates[role]
        if (not isinstance(definition, dict) or set(definition) != {"family", "lookback"}
                or not isinstance(definition["family"], str)
                or not definition["family"]
                or isinstance(definition["lookback"], bool)
                or not isinstance(definition["lookback"], int)
                or definition["lookback"] < 2):
            raise PlanArtifactError(f"{role} candidate definition is malformed")
        definitions.append((definition["family"], definition["lookback"]))
    if len(set(definitions)) != 3 or candidates["cash"] != {"family": "cash", "lookback": 2}:
        raise PlanArtifactError("candidate roles must be distinct and include the explicit cash baseline")

    costs = plan["costs_bps"]
    if not isinstance(costs, dict) or set(costs) != {"fee", "slippage"}:
        raise PlanArtifactError("costs_bps must contain fee and slippage")
    for name, value in costs.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise PlanArtifactError(f"costs_bps.{name} must be finite and non-negative")
    if costs["fee"] + costs["slippage"] >= 10000:
        raise PlanArtifactError("combined execution costs must be less than 10000 bps")

    return {
        "status": "plan_integrity_verified",
        "plan_id": expected_id,
        "task_id": plan["task_id"],
        "dataset": {
            "symbol": plan["symbol"], "interval": plan["interval"],
            "fingerprint": fingerprint, "row_count": row_count,
            "sources": sorted(sources),
        },
        "experiment": {
            "code_revision": revision,
            "train_bars": train_bars, "test_bars": test_bars,
            "test_window": {"start": start.isoformat(), "end": end.isoformat()},
            "candidates": candidates,
            "costs_bps": costs,
        },
        "execution_authority": "none",
        "limitations": [
            "Digest verification detects accidental or uncoordinated artifact edits; it is not a signature or trusted timestamp.",
            "This audit cannot independently prove dataset freshness, holdout non-use, source authenticity, or that the stated code revision was executed.",
            "No market data is fetched, no strategy is evaluated, no ledger is changed, and no orders are placed.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Verify a portable Bitcoin AI research-plan artifact without executing it."
    )
    parser.add_argument("--input", type=Path, required=True, help="Path to the plan JSON")
    parser.add_argument("--output", type=Path, help="Optional path for the audit JSON")
    args = parser.parse_args(argv)
    try:
        artifact = json.loads(args.input.read_text(encoding="utf-8"))
        report = audit_plan_artifact(artifact)
        serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        if args.output:
            args.output.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
        return 0
    except Exception as exc:
        print(f"Research plan audit failed closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
