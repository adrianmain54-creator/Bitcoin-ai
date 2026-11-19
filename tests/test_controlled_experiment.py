from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.research_experiment_plan import prepare_scheduled_experiment
from bitcoin_ai.controlled_experiment import (
    ControlledExperimentError,
    run_preregistered_experiment,
)
from bitcoin_ai.fresh_evidence import FreshEvidenceError, evaluate_completed_experiment
from bitcoin_ai.holdout_ledger import audit_and_append_holdout_records
from bitcoin_ai.research_ingestion import compute_research_dataset_fingerprint


def fixtures():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        {"timestamp": (start + timedelta(minutes=i)).isoformat(),
         "open": 100+i, "high": 102+i, "low": 99+i, "close": 101+i, "volume": 1.0}
        for i in range(81)
    ]
    dataset = {
        "schema_version": 1, "symbol": "BTC-USDT", "interval": "1m",
        "start": bars[0]["timestamp"], "end": bars[-1]["timestamp"],
        "row_count": len(bars), "canonical_bars": bars,
        "cross_source": {"status": "cross_checked",
                         "sources": ["binance", "coinbase", "kraken"],
                         "aligned_candles": len(bars), "divergent_candles": 0},
    }
    fingerprint = compute_research_dataset_fingerprint(dataset)
    report = {
        "status": "prepared", "dataset_fingerprint": fingerprint,
        "holdout_status": "not_assessed", "dataset": dataset,
        "provenance": {"dataset_fingerprint": fingerprint},
    }
    task = {
        "event_type": "task_queued", "task_id": "task-1", "status": "queued",
        "execution_authority": "none", "source_candidate": "sma:12",
        "candidate": {"family": "momentum", "lookback": 5},
    }
    prepared = prepare_scheduled_experiment(
        task, report, train_bars=50, test_bars=10, code_revision="abc123",
        source_strategy_definition={"family": "sma", "lookback": 12},
    )
    return prepared


def fake_lab(*args, **kwargs):
    bars = args[0]
    candidates = kwargs["candidates"]
    timestamps = [bars[i].timestamp.isoformat() for i in range(51, 81)]
    regimes = ["uptrend"] * 15 + ["range"] * 15
    streams = {
        "momentum:5": ([0.002] * 30, [0.0015] * 30),
        "sma:12": ([0.0005] * 30, [0.0002] * 30),
        "cash:2": ([0.0] * 30, [0.0] * 30),
    }
    rows = {}
    for item in candidates:
        name = f"{item['family']}:{item['lookback']}"
        returns, doubled = streams[name]
        rows[name] = {
            "observations": 30, "return_pct": 2.0,
            "excess_return_vs_buy_and_hold_pct_points": 1.0,
            "metrics_at_2x_cost": {"total_return_pct": 0.5},
            "oos_returns": returns,
            "oos_returns_at_2x_cost": doubled,
            "oos_regimes": regimes,
            "oos_timestamps": timestamps,
        }
    return {
        "holdout_reuse_audit": {"status": "no_overlap_detected"},
        "fixed_candidate_oos_comparison": {"candidates": rows},
    }


def test_preregisters_reserves_runs_and_completes_all_roles(tmp_path, monkeypatch):
    import bitcoin_ai.controlled_experiment as module
    monkeypatch.setattr(module, "run_strategy_lab", fake_lab)
    result = run_preregistered_experiment(
        fixtures(), candidate_registry_path=tmp_path / "registry.json",
        holdout_ledger_path=tmp_path / "holdouts.json",
        registered_at="2026-01-01T00:00:00+00:00",
    )
    assert result["status"] == "completed_research_only"
    assert result["execution_authority"] == "none"
    assert result["candidate_family_audit"]["status"] == "complete"
    assert result["candidate_family_audit"]["candidate_count"] == 3


def test_rejects_second_attempt_on_reserved_interval(tmp_path, monkeypatch):
    import bitcoin_ai.controlled_experiment as module
    monkeypatch.setattr(module, "run_strategy_lab", fake_lab)
    prepared = fixtures()
    kwargs = {
        "candidate_registry_path": tmp_path / "registry.json",
        "holdout_ledger_path": tmp_path / "holdouts.json",
        "registered_at": "2026-01-01T00:00:00+00:00",
    }
    first = run_preregistered_experiment(prepared, **kwargs)
    assert first["status"] == "completed_research_only"
    with pytest.raises(ControlledExperimentError, match="already been registered"):
        run_preregistered_experiment(prepared, **kwargs)


def test_rejects_tampered_plan_before_any_ledger_write(tmp_path):
    prepared = fixtures()
    prepared["plan"]["code_revision"] = "tampered"
    with pytest.raises(ControlledExperimentError, match="fingerprint"):
        run_preregistered_experiment(
            prepared, candidate_registry_path=tmp_path / "registry.json",
            holdout_ledger_path=tmp_path / "holdouts.json",
            registered_at="2026-01-01T00:00:00+00:00",
        )
    assert not (tmp_path / "registry.json").exists()
    assert not (tmp_path / "holdouts.json").exists()


def test_rejects_nonterminal_test_window_before_registration(tmp_path):
    prepared = fixtures()
    prepared["bars"].pop()
    with pytest.raises(ControlledExperimentError, match="trailing observations"):
        run_preregistered_experiment(
            prepared, candidate_registry_path=tmp_path / "registry.json",
            holdout_ledger_path=tmp_path / "holdouts.json",
            registered_at="2026-01-01T00:00:00+00:00",
        )
    assert not (tmp_path / "registry.json").exists()
    assert not (tmp_path / "holdouts.json").exists()



def test_completed_experiment_flows_into_read_only_fresh_evaluator(tmp_path, monkeypatch):
    import bitcoin_ai.controlled_experiment as module
    monkeypatch.setattr(module, "run_strategy_lab", fake_lab)
    prepared = fixtures()
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "holdouts.json"
    result = run_preregistered_experiment(
        prepared, candidate_registry_path=registry, holdout_ledger_path=ledger,
        registered_at="2026-01-01T00:00:00+00:00",
    )
    names = {"proposal": "momentum:5", "source": "sma:12", "cash": "cash:2"}
    report = evaluate_completed_experiment(
        registry, ledger, plan_id=prepared["plan_id"],
        trial_ids=result["registered_trials"], expected_candidate_names=names,
        dataset_fingerprint=prepared["plan"]["dataset_fingerprint"],
        test_start=prepared["plan"]["test_window"]["start"],
        test_end=prepared["plan"]["test_window"]["end"],
        code_revision=prepared["plan"]["code_revision"],
        min_observations=20, bootstrap_trials=200,
    )
    assert report["status"] == "eligible_for_human_review"
    assert report["provenance"]["holdout_freshness"] == "no_overlap_detected"
    assert report["provenance"]["observations"] == 30


def test_completed_experiment_still_rejects_other_overlapping_holdout(tmp_path, monkeypatch):
    import bitcoin_ai.controlled_experiment as module
    monkeypatch.setattr(module, "run_strategy_lab", fake_lab)
    prepared = fixtures()
    registry = tmp_path / "registry.json"
    ledger = tmp_path / "holdouts.json"
    result = run_preregistered_experiment(
        prepared, candidate_registry_path=registry, holdout_ledger_path=ledger,
        registered_at="2026-01-01T00:00:00+00:00",
    )
    audit_and_append_holdout_records(ledger, [{
        "experiment_id": "other-inspection",
        "dataset_fingerprint": prepared["plan"]["dataset_fingerprint"],
        "test_start": prepared["plan"]["test_window"]["start"],
        "test_end": prepared["plan"]["test_window"]["end"],
    }])
    with pytest.raises(FreshEvidenceError, match="already been used"):
        evaluate_completed_experiment(
            registry, ledger, plan_id=prepared["plan_id"],
            trial_ids=result["registered_trials"],
            expected_candidate_names={"proposal": "momentum:5", "source": "sma:12", "cash": "cash:2"},
            dataset_fingerprint=prepared["plan"]["dataset_fingerprint"],
            test_start=prepared["plan"]["test_window"]["start"],
            test_end=prepared["plan"]["test_window"]["end"],
            code_revision=prepared["plan"]["code_revision"],
            min_observations=20, bootstrap_trials=200,
        )
