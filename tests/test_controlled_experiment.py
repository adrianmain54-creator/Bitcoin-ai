from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.research_experiment_plan import prepare_scheduled_experiment
from bitcoin_ai.controlled_experiment import (
    ControlledExperimentError,
    run_preregistered_experiment,
)


def fixtures():
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    bars = [
        {"timestamp": (start + timedelta(minutes=i)).isoformat(),
         "open": 100+i, "high": 102+i, "low": 99+i, "close": 101+i, "volume": 1.0}
        for i in range(81)
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
    prepared = prepare_scheduled_experiment(
        task, report, train_bars=50, test_bars=10, code_revision="abc123",
        source_strategy_definition={"family": "sma", "lookback": 12},
    )
    return prepared


def fake_lab(*args, **kwargs):
    candidates = kwargs["candidates"]
    rows = {
        f"{item['family']}:{item['lookback']}": {
            "observations": 30, "return_pct": 2.0,
            "excess_return_vs_buy_and_hold_pct_points": 1.0,
            "metrics_at_2x_cost": {"total_return_pct": 0.5},
        }
        for item in candidates
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


def test_rejects_plan_row_count_mismatch_before_registration(tmp_path):
    prepared = fixtures()
    prepared["plan"]["row_count"] -= 1
    import hashlib
    import json
    prepared["plan_id"] = hashlib.sha256(json.dumps(
        prepared["plan"], sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()).hexdigest()
    with pytest.raises(ControlledExperimentError, match="row_count"):
        run_preregistered_experiment(
            prepared, candidate_registry_path=tmp_path / "registry.json",
            holdout_ledger_path=tmp_path / "holdouts.json",
            registered_at="2026-01-01T00:00:00+00:00",
        )
    assert not (tmp_path / "registry.json").exists()
    assert not (tmp_path / "holdouts.json").exists()


def test_rejects_interior_bar_timestamp_cadence_mismatch_before_registration(tmp_path):
    prepared = fixtures()
    prepared["bars"][55].timestamp += timedelta(seconds=30)
    with pytest.raises(ControlledExperimentError, match="exact interval cadence"):
        run_preregistered_experiment(
            prepared, candidate_registry_path=tmp_path / "registry.json",
            holdout_ledger_path=tmp_path / "holdouts.json",
            registered_at="2026-01-01T00:00:00+00:00",
        )
    assert not (tmp_path / "registry.json").exists()
    assert not (tmp_path / "holdouts.json").exists()


def test_rejects_caller_interval_override_that_conflicts_with_plan(tmp_path):
    with pytest.raises(ControlledExperimentError, match="conflicts"):
        run_preregistered_experiment(
            fixtures(), candidate_registry_path=tmp_path / "registry.json",
            holdout_ledger_path=tmp_path / "holdouts.json",
            registered_at="2026-01-01T00:00:00+00:00",
            expected_interval_seconds=300,
        )
    assert not (tmp_path / "registry.json").exists()
    assert not (tmp_path / "holdouts.json").exists()
