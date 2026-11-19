"""Manual, read-only public BTC market-data smoke check.

This command validates three public venue feeds and emits a compact report.
It deliberately does not create a task, reserve a holdout, or run a strategy.
"""
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
import sys

from .research_market_ingestion import PublicResearchMarketIngestor


def run_market_data_smoke_check(*, interval: str = "5m", limit: int = 100,
                                ingestor=None, now: datetime | None = None) -> dict:
    """Fetch and validate public BTC-USDT candles without evaluating a strategy."""
    client = ingestor or PublicResearchMarketIngestor()
    report = client.fetch_and_prepare(interval=interval, limit=limit, now=now)
    dataset = report["dataset"]
    provenance = report["provenance"]
    cross_source = dataset["cross_source"]
    return {
        "status": "market_data_validated",
        "symbol": dataset["symbol"],
        "interval": dataset["interval"],
        "dataset_fingerprint": report["dataset_fingerprint"],
        "start": dataset["start"],
        "end": dataset["end"],
        "row_count": provenance["row_count"],
        "source_count": cross_source["source_count"],
        "sources": cross_source["sources"],
        "maximum_close_deviation": cross_source["maximum_close_deviation"],
        "cross_source_status": cross_source["status"],
        "holdout_status": report["holdout_status"],
        "strategy_evaluation": "not_run",
        "execution_authority": "none",
        "limitations": [
            "This is a market-data quality check, not a strategy backtest or profitability result.",
            "A dataset fingerprint does not prove that a holdout is fresh or unused.",
            "No candidate registry, holdout ledger, paper account, wallet, or order endpoint is accessed.",
            "All three public venues must pass; outages and shared upstream data faults remain possible.",
        ],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Validate public BTC-USDT candles from three exchanges.")
    parser.add_argument("--interval", choices=("1m", "5m", "15m", "1h", "1d"), default="5m")
    parser.add_argument("--limit", type=int, choices=range(20, 301), default=100)
    parser.add_argument("--output", type=Path, default=Path("market-data-smoke-report.json"))
    args = parser.parse_args(argv)
    try:
        result = run_market_data_smoke_check(interval=args.interval, limit=args.limit)
        serialized = json.dumps(result, indent=2, sort_keys=True) + "\n"
        args.output.write_text(serialized, encoding="utf-8")
        print(serialized, end="")
        return 0
    except Exception as exc:
        print(f"Market-data smoke check failed closed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
