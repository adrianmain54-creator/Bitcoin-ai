from datetime import datetime, timezone, timedelta

import pytest

from bitcoin_ai.backtesting import Bar
from bitcoin_ai.research_experiment_plan import (
    ResearchPlanError,
    prepare_scheduled_experiment,
)


def fixtures():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        {"timestamp": (start + timedelta(minutes=i)).isoformat(), "open": 100+i,
         "high": 102+i, "low": 99+i, "close": 101+i, "volume": 1.0}
        for i in range(80)
    ]
    fingerprint = "a" * 64
    report = {
        "status": "prepared", "dataset_fingerprint": fingerprint,
        "holdout_status": "not_assessed",
        "dataset": {
            "symbol": "BTC-USDT", "interval": "1m", "row_count": len(bars),
            "canonical_bars": bars,
            "cross_source": {"status": "cross_checked",
                             "sources": ["binance", "coinbase", "kraken"]},
        },
        "provenance": {"dataset_fingerprint": fingerprint},
    }
    task = {
        "event_type": "task_queued", "task_id": "task-1", "status": "queued",
        "execution_authority": "none", "source_candidate": "sma:12",
        "candidate": {"family": "momentum", "lookback": 5},
    }
    return task, report


def test_prepares_deterministic_plan_and_typed_bars_without_side_effects():
    task, report = fixtures()
    first = prepare_scheduled_experiment(
        task, report, train_bars=50, test_bars=10, code_revision="abc123", source_strategy_definition={"family": "sma", "lookback": 12}
    )
    second = prepare_scheduled_experiment(
        task, report, train_bars=50, test_bars=10, code_revision="abc123", source_strategy_definition={"family": "sma", "lookback": 12}
    )
    assert first["status"] == "plan_prepared"
    assert first["plan_id"] == second["plan_id"]
    assert len(first["bars"]) == 80
    assert isinstance(first["bars"][0], Bar)
    assert first["plan"]["candidates"]["cash"] == {"family": "cash", "lookback": 2}
    assert first["execution_authority"] == "none"
    assert first["side_effects"] == []


@pytest.mark.parametrize("mutation", [
    lambda task, report: report.update(holdout_status="fresh"),
    lambda task, report: report.update(status="rejected"),
    lambda task, report: report["dataset"]["cross_source"].update(sources=["binance"]),
    lambda task, report: report["provenance"].update(dataset_fingerprint="b" * 64),
    lambda task, report: task.update(execution_authority="paper"),
    lambda task, report: task["candidate"].update(lookback=50),
])
def test_rejects_unsafe_or_inconsistent_inputs(mutation):
    task, report = fixtures()
    mutation(task, report)
    with pytest.raises(ResearchPlanError):
        prepare_scheduled_experiment(
            task, report, train_bars=50, test_bars=10, code_revision="abc123", source_strategy_definition={"family": "sma", "lookback": 12}
        )


def test_rejects_out_of_order_or_invalid_close():
    task, report = fixtures()
    report["dataset"]["canonical_bars"][4]["close"] = float("nan")
    with pytest.raises(ResearchPlanError, match="finite and positive"):
        prepare_scheduled_experiment(
            task, report, train_bars=50, test_bars=10, code_revision="abc123", source_strategy_definition={"family": "sma", "lookback": 12}
        )


def test_rejects_too_short_dataset_and_invalid_costs():
    task, report = fixtures()
    with pytest.raises(ResearchPlanError, match="needs bars"):
        prepare_scheduled_experiment(
            task, report, train_bars=70, test_bars=10, code_revision="abc123", source_strategy_definition={"family": "sma", "lookback": 12}
        )
    with pytest.raises(ResearchPlanError, match="combined costs"):
        prepare_scheduled_experiment(
            task, report, train_bars=50, test_bars=10, code_revision="abc123",
            fee_bps=6000, slippage_bps=4000,
            source_strategy_definition={"family": "sma", "lookback": 12},
        )
