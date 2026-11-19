"""Explicit orchestration for one scheduled, research-only BTC experiment.

This function is invoked by a caller; it is not a background scheduler and does
not fetch market data, mutate the scheduler queue, or grant execution authority.
"""
from __future__ import annotations

from pathlib import Path

from .controlled_evidence import evaluate_controlled_experiment
from .controlled_experiment import run_preregistered_experiment
from .research_experiment_plan import prepare_scheduled_experiment


def run_scheduled_research_cycle(
    task: dict,
    dataset_report: dict,
    *,
    train_bars: int,
    test_bars: int,
    code_revision: str,
    source_strategy_definition: dict,
    candidate_registry_path: str | Path,
    holdout_ledger_path: str | Path,
    registered_at: str,
    fee_bps: float = 10.0,
    slippage_bps: float = 5.0,
    bootstrap_trials: int = 500,
    seed: int = 7,
    min_evidence_observations: int = 180,
    evidence_bootstrap_trials: int = 2000,
) -> dict:
    """Prepare, preregister, evaluate, and review one caller-supplied task.

    All market data must already have passed the three-source ingestion gate.
    A rejected holdout stops before evidence review. A completed experiment is
    passed to the strict read-only evidence gate; no execution follows either
    an eligible or rejected evidence result.
    """
    prepared = prepare_scheduled_experiment(
        task,
        dataset_report,
        train_bars=train_bars,
        test_bars=test_bars,
        code_revision=code_revision,
        source_strategy_definition=source_strategy_definition,
        fee_bps=fee_bps,
        slippage_bps=slippage_bps,
    )
    experiment = run_preregistered_experiment(
        prepared,
        candidate_registry_path=candidate_registry_path,
        holdout_ledger_path=holdout_ledger_path,
        registered_at=registered_at,
        bootstrap_trials=bootstrap_trials,
        seed=seed,
    )
    if experiment.get("status") != "completed_research_only":
        return {
            "status": experiment.get("status", "research_not_completed"),
            "prepared_plan_id": prepared["plan_id"],
            "experiment": experiment,
            "evidence_review": None,
            "execution_authority": "none",
            "limitations": [
                "Evidence review was not run because the controlled experiment did not complete cleanly.",
                "Inspect the append-only registry and holdout ledger before attempting any new dataset/window.",
                "No paper-state mutation, strategy promotion, or live orders are authorized.",
            ],
        }

    review = evaluate_controlled_experiment(
        experiment,
        candidate_registry_path=candidate_registry_path,
        holdout_ledger_path=holdout_ledger_path,
        min_observations=min_evidence_observations,
        bootstrap_trials=evidence_bootstrap_trials,
    )
    return {
        "status": review["status"],
        "prepared_plan_id": prepared["plan_id"],
        "experiment": experiment,
        "evidence_review": review,
        "execution_authority": "none",
        "limitations": [
            "This explicit orchestration call performs historical research only.",
            "Eligible evidence means human review only; it is not a profitability forecast or permission to trade.",
            "No paper-state mutation, strategy promotion, or live orders occur.",
        ],
    }
