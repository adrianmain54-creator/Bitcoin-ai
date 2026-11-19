"""Bridge validated market datasets to deterministic, reviewable research plans.

This module prepares an experiment specification only. It does not register
trials, reserve holdouts, run backtests, mutate paper state, or place orders.
"""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math

from .backtesting import Bar


class ResearchPlanError(ValueError):
    """A queued task or validated dataset cannot safely form a research plan."""


_ALLOWED_FAMILIES = {
    "sma", "momentum", "breakout", "vol_target_sma",
    "defensive_vol_target_sma", "agent_council",
    "agent_council_50", "agent_council_25", "cash",
}


def _stamp(value: str, field: str) -> datetime:
    if not isinstance(value, str):
        raise ResearchPlanError(f"{field} must be a timezone-aware ISO timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchPlanError(f"{field} is not a valid ISO timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ResearchPlanError(f"{field} must include a timezone")
    return parsed


def _candidate(value: dict, field: str, train_bars: int) -> dict:
    if not isinstance(value, dict) or set(value) != {"family", "lookback"}:
        raise ResearchPlanError(f"{field} must contain exactly family and lookback")
    family, lookback = value["family"], value["lookback"]
    if family not in _ALLOWED_FAMILIES:
        raise ResearchPlanError(f"{field} uses an unsupported strategy family")
    if isinstance(lookback, bool) or not isinstance(lookback, int) or not 2 <= lookback < train_bars:
        raise ResearchPlanError(f"{field} lookback must be >= 2 and smaller than train_bars")
    if family.startswith("agent_council") and lookback < 48:
        raise ResearchPlanError(f"{field} agent-council lookback must be >= 48")
    return {"family": family, "lookback": lookback}


def prepare_scheduled_experiment(
    task: dict,
    dataset_report: dict,
    *,
    train_bars: int,
    test_bars: int,
    code_revision: str,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
) -> dict:
    """Create a reproducible plan from one queued task and a clean data bundle.

    The result is a handoff artifact, not permission to evaluate a holdout.
    """
    if not isinstance(task, dict) or task.get("event_type") != "task_queued":
        raise ResearchPlanError("task must be a queued research scheduler event")
    if task.get("status") != "queued" or task.get("execution_authority") != "none":
        raise ResearchPlanError("task status or execution authority is invalid")
    if not isinstance(task.get("task_id"), str) or not task["task_id"]:
        raise ResearchPlanError("task_id is required")
    candidate = _candidate(task.get("candidate"), "task candidate", train_bars)
    if not isinstance(task.get("source_candidate"), str) or not task["source_candidate"].strip():
        raise ResearchPlanError("source_candidate is required for paired comparison")
    if not isinstance(dataset_report, dict) or dataset_report.get("status") != "prepared":
        raise ResearchPlanError("dataset report is not prepared")
    if dataset_report.get("holdout_status") != "not_assessed":
        raise ResearchPlanError("dataset holdout status must remain not_assessed")
    dataset = dataset_report.get("dataset")
    provenance = dataset_report.get("provenance")
    if not isinstance(dataset, dict) or not isinstance(provenance, dict):
        raise ResearchPlanError("dataset or provenance metadata is missing")
    if dataset.get("symbol") != "BTC-USDT" or dataset.get("cross_source", {}).get("status") != "cross_checked":
        raise ResearchPlanError("only cross-checked BTC-USDT research datasets are accepted")
    sources = dataset.get("cross_source", {}).get("sources")
    if not isinstance(sources, list) or len(set(sources)) < 3:
        raise ResearchPlanError("at least three unique aligned sources are required")
    bars = dataset.get("canonical_bars")
    if not isinstance(bars, list) or len(bars) != dataset.get("row_count") or len(bars) < 4:
        raise ResearchPlanError("canonical bar count is invalid")
    if isinstance(train_bars, bool) or not isinstance(train_bars, int) or train_bars < 3:
        raise ResearchPlanError("train_bars must be an integer >= 3")
    if isinstance(test_bars, bool) or not isinstance(test_bars, int) or test_bars < 3:
        raise ResearchPlanError("test_bars must be an integer >= 3")
    if train_bars + test_bars >= len(bars):
        raise ResearchPlanError("dataset needs bars beyond the initial train and test windows")
    if not isinstance(code_revision, str) or not code_revision.strip():
        raise ResearchPlanError("code_revision is required")
    for value, name in ((fee_bps, "fee_bps"), (slippage_bps, "slippage_bps")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ResearchPlanError(f"{name} must be finite and non-negative")
    if fee_bps + slippage_bps >= 10000:
        raise ResearchPlanError("combined costs must be less than 10000 bps")

    normalized = []
    previous = None
    for index, row in enumerate(bars):
        if not isinstance(row, dict):
            raise ResearchPlanError(f"canonical bar {index} is malformed")
        stamp = _stamp(row.get("timestamp"), f"canonical bar {index} timestamp")
        close = row.get("close")
        if isinstance(close, bool) or not isinstance(close, (int, float)) or not math.isfinite(close) or close <= 0:
            raise ResearchPlanError(f"canonical bar {index} close must be finite and positive")
        if previous is not None and stamp <= previous:
            raise ResearchPlanError("canonical bars must be strictly chronological")
        previous = stamp
        normalized.append(Bar(timestamp=stamp, close=float(close)))

    fingerprint = dataset_report.get("dataset_fingerprint")
    if (not isinstance(fingerprint, str) or len(fingerprint) != 64
            or provenance.get("dataset_fingerprint") != fingerprint):
        raise ResearchPlanError("dataset fingerprint and provenance do not agree")
    try:
        bytes.fromhex(fingerprint)
    except ValueError as exc:
        raise ResearchPlanError("dataset fingerprint must be hexadecimal SHA-256") from exc

    test_start = normalized[train_bars].timestamp.isoformat()
    test_end = normalized[-1].timestamp.isoformat()
    plan_core = {
        "task_id": task["task_id"],
        "dataset_fingerprint": fingerprint,
        "symbol": dataset["symbol"],
        "interval": dataset.get("interval"),
        "sources": sorted(sources),
        "row_count": len(normalized),
        "train_bars": train_bars,
        "test_bars": test_bars,
        "test_window": {"start": test_start, "end": test_end},
        "code_revision": code_revision,
        "candidates": {
            "proposal": candidate,
            "unchanged_source_label": task["source_candidate"],
            "cash": {"family": "cash", "lookback": 2},
        },
        "costs_bps": {"fee": float(fee_bps), "slippage": float(slippage_bps)},
        "comparison_requirements": [
            "Register distinct proposal, unchanged-source, and cash trials before any holdout evaluation.",
            "Verify the dataset fingerprint, code revision, and exact test window in each registration.",
            "Audit the holdout ledger and candidate family for overlap before evaluation.",
            "Run identical walk-forward folds and paired out-of-sample observations for all roles.",
            "Retain uncertainty, doubled-cost, regime, and failure-analysis checks.",
        ],
    }
    plan_id = hashlib.sha256(json.dumps(
        plan_core, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")).hexdigest()
    return {
        "status": "plan_prepared",
        "plan_id": plan_id,
        "plan": plan_core,
        "bars": normalized,
        "execution_authority": "none",
        "side_effects": [],
        "limitations": [
            "Preparation does not preregister trials or reserve a holdout.",
            "The source candidate is a label supplied by the queued task and must be resolved to an explicit strategy definition before execution.",
            "The supplied dataset fingerprint is not proof of freshness or unused holdout history.",
            "No backtest, paper-state mutation, promotion, or order execution occurs.",
        ],
    }
