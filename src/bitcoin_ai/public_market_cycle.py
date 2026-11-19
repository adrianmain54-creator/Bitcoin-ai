"""Explicit public-market-data to evidence-review research workflow.

Network retrieval is opt-in by calling this function. It uses public OHLCV
endpoints only and delegates all evaluation to the existing fail-closed stages.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .research_cycle import run_scheduled_research_cycle
from .research_market_ingestion import PublicResearchMarketIngestor


def run_public_market_research_cycle(
    task: dict,
    *,
    code_revision: str,
    source_strategy_definition: dict,
    candidate_registry_path: str | Path,
    holdout_ledger_path: str | Path,
    registered_at: str,
    interval: str = "5m",
    limit: int = 300,
    train_bars: int = 99,
    test_bars: int = 20,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    bootstrap_trials: int = 500,
    seed: int = 7,
    min_evidence_observations: int = 180,
    evidence_bootstrap_trials: int = 2000,
    now: datetime | None = None,
    ingestor: PublicResearchMarketIngestor | None = None,
) -> dict:
    """Fetch/cross-check three public venues, then run one queued research task.

    The caller must provide an existing queued task and the unchanged source
    strategy definition. The ingestor requires all three venues and rejects
    stale, incomplete, misaligned, or divergent history. No private exchange
    credentials or trading endpoints are used.

    A successful evidence result can only be eligible for human review. This
    function does not trade, promote a candidate, or mutate a paper account.
    """
    market = ingestor or PublicResearchMarketIngestor()
    dataset_report = market.fetch_and_prepare(
        interval=interval,
        limit=limit,
        now=now,
    )
    cycle = run_scheduled_research_cycle(
        task,
        dataset_report,
        train_bars=train_bars,
        test_bars=test_bars,
        code_revision=code_revision,
        source_strategy_definition=source_strategy_definition,
        candidate_registry_path=candidate_registry_path,
        holdout_ledger_path=holdout_ledger_path,
        registered_at=registered_at,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
        bootstrap_trials=bootstrap_trials,
        seed=seed,
        min_evidence_observations=min_evidence_observations,
        evidence_bootstrap_trials=evidence_bootstrap_trials,
    )
    return {
        "status": cycle["status"],
        "market_data": {
            "status": dataset_report["status"],
            "dataset_fingerprint": dataset_report["dataset_fingerprint"],
            "symbol": dataset_report["dataset"]["symbol"],
            "interval": dataset_report["dataset"]["interval"],
            "row_count": dataset_report["provenance"]["row_count"],
            "sources": dataset_report["provenance"]["sources"],
            "cross_source": dataset_report["dataset"]["cross_source"],
            "holdout_status": dataset_report["holdout_status"],
        },
        "research_cycle": cycle,
        "execution_authority": "none",
        "limitations": [
            "Public exchange endpoints may be unavailable, rate-limited, or share upstream data dependencies.",
            "All three venues must pass strict alignment and quality checks; there is no two-source fallback.",
            "The dataset fingerprint is not proof of an unused holdout; the preregistration ledger remains authoritative.",
            "Eligible evidence means human review only and is not a profitability forecast or permission to trade.",
            "No paper-state mutation, strategy promotion, or live orders occur.",
        ],
    }
