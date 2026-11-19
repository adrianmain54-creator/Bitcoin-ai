"""Explicit plan-only bridge from a queued task to fresh public BTC data.

This command prepares a deterministic plan. It never registers trials,
reserves holdouts, runs strategy evaluation, or mutates paper/trading state.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

from .research_experiment_plan import prepare_scheduled_experiment
from .research_market_ingestion import PublicResearchMarketIngestor
from .research_scheduler import load_research_queue


def build_plan_report(
    *, queue_path: str | Path, task_id: str, interval: str = "5m",
    limit: int = 100, train_bars: int = 50, test_bars: int = 10,
    code_revision: str, source_family: str, source_lookback: int,
    ingestor=None,
) -> dict:
    """Load one queued task, fetch validated data, and prepare a plan only."""
    queue = load_research_queue(queue_path)
    matches = [task for task in queue["tasks"] if task.get("task_id") == task_id]
    if len(matches) != 1:
        raise ValueError("task_id must identify exactly one task in the validated queue")
    task = matches[0]
    if task.get("status") != "queued" or task.get("execution_authority") != "none":
        raise ValueError("selected task is not queued with no execution authority")
    source = {"family": source_family, "lookback": source_lookback}
    dataset_report = (ingestor or PublicResearchMarketIngestor()).fetch_and_prepare(
        interval=interval, limit=limit, now=datetime.now(timezone.utc)
    )
    prepared = prepare_scheduled_experiment(
        task, dataset_report, train_bars=train_bars, test_bars=test_bars,
        code_revision=code_revision, source_strategy_definition=source,
    )
    # Bar objects are intentionally omitted from the portable JSON artifact;
    # the deterministic plan binds the exact dataset fingerprint and window.
    return {
        "status": prepared["status"],
        "plan_id": prepared["plan_id"],
        "plan": prepared["plan"],
        "execution_authority": "none",
        "side_effects": [],
        "limitations": prepared["limitations"] + [
            "This CLI does not preregister candidates or reserve a holdout.",
            "No strategy evaluation, paper-state mutation, or order execution occurs.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Prepare a deterministic BTC research plan without evaluating it."
    )
    parser.add_argument("--queue", type=Path, required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--interval", choices=("1m", "5m", "15m", "1h", "1d"), default="5m")
    parser.add_argument("--limit", type=int, choices=range(20, 301), default=100)
    parser.add_argument("--train-bars", type=int, default=50)
    parser.add_argument("--test-bars", type=int, default=10)
    parser.add_argument("--code-revision", required=True)
    parser.add_argument("--source-family", required=True)
    parser.add_argument("--source-lookback", type=int, required=True)
    parser.add_argument("--output", type=Path, default=Path("research-plan.json"))
    args = parser.parse_args(argv)
    try:
        report = build_plan_report(
            queue_path=args.queue, task_id=args.task_id, interval=args.interval,
            limit=args.limit, train_bars=args.train_bars, test_bars=args.test_bars,
            code_revision=args.code_revision, source_family=args.source_family,
            source_lookback=args.source_lookback,
        )
        serialized = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
        args.output.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
        return 0
    except Exception as exc:
        print(f"Research plan preparation failed closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
