from datetime import datetime, timedelta, timezone

import pytest

from bitcoin_ai.backtesting import BacktestError, Bar
from bitcoin_ai.research_lab import run_strategy_lab, _selection_score, _simulate


def bars(count=260):
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    prices = []
    price = 100.0
    for i in range(count):
        # Alternating trend and pullback regimes, deterministic for reproducibility.
        drift = 0.0015 if (i // 35) % 2 == 0 else -0.0008
        price *= 1 + drift + ((i % 7) - 3) * 0.0004
        prices.append(Bar(start + timedelta(days=i), price))
    return prices


def test_strategy_lab_runs_multi_family_oos_and_bootstrap():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[
            {"family": "sma", "lookback": 12},
            {"family": "momentum", "lookback": 8},
            {"family": "breakout", "lookback": 15},
        ],
        bootstrap_trials=100, seed=11,
    )
    assert set(result["families"]) == {"sma", "momentum", "breakout"}
    assert result["fold_count"] > 1
    assert result["out_of_sample_returns"] == result["fold_count"] * 30
    assert result["bootstrap"]["trials"] == 100
    assert result["bootstrap"]["final_equity_p05"] <= result["bootstrap"]["final_equity_p95"]
    assert sum(item["observations"] for item in result["out_of_sample_regime_metrics"].values()) == result["out_of_sample_returns"]
    assert sum(result["training_selection_counts"].values()) == result["fold_count"]
    assert result["out_of_sample_metrics_at_2x_cost"]["total_return_pct"] <= result["out_of_sample_metrics"]["total_return_pct"]
    for regime in result["out_of_sample_regime_metrics"].values():
        assert "strategy" in regime and "buy_and_hold" in regime
    for fold in result["folds"]:
        assert fold["train_end"] < fold["test_start"]
        assert fold["selected_family"] in result["families"]


def test_strategy_lab_supports_short_sma_lookback_without_invalid_window():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "sma", "lookback": 2}], bootstrap_trials=100,
    )
    assert result["fold_count"] > 0


def test_strategy_lab_rejects_naive_timestamps():
    naive = [Bar(datetime(2024, 1, 1) + timedelta(days=i), 100 + i) for i in range(150)]
    with pytest.raises(BacktestError, match="timezone-aware"):
        run_strategy_lab(naive, train_bars=100, test_bars=20, bootstrap_trials=100)


def test_strategy_lab_is_deterministic_for_fixed_seed():
    kwargs = dict(train_bars=100, test_bars=30, bootstrap_trials=100, seed=42)
    a = run_strategy_lab(bars(), **kwargs)
    b = run_strategy_lab(bars(), **kwargs)
    assert a["bootstrap"] == b["bootstrap"]
    assert a["folds"] == b["folds"]


@pytest.mark.parametrize("kwargs", [
    {"train_bars": 2, "test_bars": 20},
    {"train_bars": 100, "test_bars": 20, "step_bars": 10},
    {"train_bars": 100, "test_bars": 20, "bootstrap_trials": 10},
    {"train_bars": 100, "test_bars": 20, "candidates": [{"family": "neural", "lookback": 10}]},
    {"train_bars": 100, "test_bars": 20, "candidates": [{"family": "sma", "lookback": 100}]},
])
def test_strategy_lab_rejects_invalid_configuration(kwargs):
    with pytest.raises(BacktestError):
        run_strategy_lab(bars(), **kwargs)



def test_cash_is_a_valid_abstention_candidate():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    assert result["families"] == ["cash"]
    assert result["out_of_sample_metrics"]["total_return_pct"] == 0.0
    assert result["out_of_sample_metrics"]["max_drawdown_pct"] == 0.0
    assert all(fold["selected_family"] == "cash" for fold in result["folds"])



def test_selection_score_rewards_consistency_and_penalizes_bad_segments():
    metrics = {"sortino_ratio": 1.0, "max_drawdown_pct": -5.0}
    steady = [0.01] * 40
    volatile = [0.05] * 10 + [0.01] * 10 + [-0.08] * 10 + [0.01] * 10
    steady_score, steady_share, steady_worst, _, _, _, _, _, _ = _selection_score(steady, metrics)
    volatile_score, volatile_share, volatile_worst, _, _, _, _, _, _ = _selection_score(volatile, metrics)
    assert steady_share == 1.0
    assert steady_worst > 0
    assert volatile_share < steady_share
    assert volatile_worst < steady_worst
    assert steady_score > volatile_score


def test_strategy_lab_reports_training_consistency_diagnostics():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "sma", "lookback": 12}, {"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    for fold in result["folds"]:
        assert 0.0 <= fold["training_positive_segment_share"] <= 1.0
        assert isinstance(fold["training_worst_segment_return_pct"], float)
        assert "training_sortino_at_2x_cost" in fold
        assert "training_base_cost_sortino" in fold
        assert fold["training_turnover_units"] >= 0
        assert fold["training_cost_drag_at_2x_pct"] >= 0
        assert fold["training_turnover_per_100_bars"] >= 0
        assert fold["training_turnover_penalty"] >= 0
        assert isinstance(fold["training_worst_5pct_bar_return_pct"], float)
        assert fold["training_tail_loss_penalty"] >= 0
        ranking = fold["training_candidate_ranking"]
        assert len(ranking) == 2
        assert ranking[0]["training_score"] >= ranking[1]["training_score"]
        assert ranking[0]["score_gap_from_best"] == 0
        assert fold["training_winner_margin"] >= 0
    assert "doubling estimated fees and slippage" in result["selection_policy"]
    assert "positive-segment share" in result["selection_policy"]



def test_regime_selection_penalizes_weak_training_regime():
    metrics = {"sortino_ratio": 1.0, "max_drawdown_pct": -5.0}
    returns = [0.01] * 12 + [-0.03] * 12
    regimes = ["uptrend"] * 12 + ["downtrend"] * 12
    balanced = ["uptrend"] * 12 + ["downtrend"] * 12
    _, _, _, weak_regime, coverage, _, _, _, _ = _selection_score(returns, metrics, regimes)
    assert weak_regime < 0
    assert coverage == 2


def test_strategy_lab_reports_causal_training_regime_diagnostics():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "sma", "lookback": 12}, {"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    for fold in result["folds"]:
        assert isinstance(fold["training_worst_regime_return_pct"], float)
        assert 0 <= fold["training_regimes_scored"] <= 4
    assert "trailing observations" in result["selection_policy"]



def test_candidates_share_identical_effective_training_window():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[
            {"family": "sma", "lookback": 5},
            {"family": "breakout", "lookback": 24},
            {"family": "cash", "lookback": 2},
        ],
        bootstrap_trials=100,
    )
    first = result["folds"][0]
    assert first["training_scoring_start"] == bars()[24].timestamp.isoformat()
    assert first["training_scoring_observations"] == 75


def test_regime_classification_uses_only_bounded_trailing_slice(monkeypatch):
    import bitcoin_ai.research_lab as research_lab

    original = research_lab.classify_regime
    observed_lengths = []

    def recording_classifier(closes, *, lookback=20):
        observed_lengths.append(len(closes))
        return original(closes, lookback=lookback)

    monkeypatch.setattr(research_lab, "classify_regime", recording_classifier)
    run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "sma", "lookback": 12}],
        bootstrap_trials=100,
    )
    assert observed_lengths
    assert max(observed_lengths) <= 21



def test_contiguous_simulation_can_carry_position_without_forced_fold_exit():
    closes = [100.0, 101.0, 102.0, 103.0, 104.0]
    carried = _simulate(
        closes, 2, 4, "momentum", 2, 0.001,
        initial_position=1.0, liquidate=False,
    )
    forcibly_closed = _simulate(
        closes, 2, 4, "momentum", 2, 0.001,
        initial_position=1.0, liquidate=True,
    )
    assert len(carried) == 2
    assert carried[0] == pytest.approx(103.0 / 102.0 - 1.0)
    assert carried[1] == pytest.approx(104.0 / 103.0 - 1.0)
    assert forcibly_closed[-1] == pytest.approx(carried[-1] - 0.001)



def test_strategy_lab_reports_exposure_trade_and_regime_attribution():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[
            {"family": "sma", "lookback": 12},
            {"family": "momentum", "lookback": 8},
            {"family": "cash", "lookback": 2},
        ],
        bootstrap_trials=100,
    )
    overall = result["out_of_sample_attribution"]
    assert overall["observations"] == result["out_of_sample_returns"]
    assert 0 <= overall["exposure_pct"] <= 100
    assert overall["entries"] >= 0 and overall["exits"] >= 0
    assert overall["total_turnover_units"] >= 0
    assert "estimated_cost_drag_pct" in overall
    assert set(result["selected_family_attribution"]) <= {"sma", "momentum", "cash"}
    for family in result["selected_family_attribution"].values():
        assert "exposure_pct" in family["attribution"]
        assert family["folds_selected"] > 0
    for regime in result["out_of_sample_regime_metrics"].values():
        assert regime["attribution"]["observations"] == regime["observations"]



def test_selection_score_penalizes_excessive_turnover():
    metrics = {"sortino_ratio": 1.0, "max_drawdown_pct": -5.0}
    returns = [0.001] * 100
    low_turnover = _selection_score(
        returns, metrics, turnover_units=2.0
    )
    high_turnover = _selection_score(
        returns, metrics, turnover_units=20.0
    )
    assert low_turnover[0] > high_turnover[0]
    assert low_turnover[5] == pytest.approx(2.0)
    assert high_turnover[5] == pytest.approx(20.0)
    assert high_turnover[6] > low_turnover[6]
    assert high_turnover[7] == pytest.approx(0.1)
    assert high_turnover[8] == pytest.approx(0.0)



def test_volatility_targeted_sma_scales_exposure_using_trailing_returns():
    from bitcoin_ai.research_lab import _signal

    # A clean uptrend with alternating larger daily moves should keep the
    # trend signal active but reduce position size below full exposure.
    closes = [100.0]
    for i in range(1, 25):
        closes.append(closes[-1] * (1.04 if i % 2 else 0.985))
    position = _signal(closes, 23, "vol_target_sma", 20)
    assert 0.0 < position < 1.0


def test_volatility_targeted_sma_is_zero_without_uptrend():
    from bitcoin_ai.research_lab import _signal

    closes = [100.0 - i * 0.5 for i in range(25)]
    assert _signal(closes, 23, "vol_target_sma", 20) == 0.0


def test_defensive_volatility_target_caps_exposure_and_reduces_risk():
    from bitcoin_ai.research_lab import _signal

    closes = [100.0]
    for i in range(1, 25):
        closes.append(closes[-1] * (1.04 if i % 2 else 0.985))
    regular = _signal(closes, 23, "vol_target_sma", 20)
    defensive = _signal(closes, 23, "defensive_vol_target_sma", 20)
    assert 0.0 < defensive <= 0.50
    assert defensive < regular


def test_defensive_volatility_target_is_zero_without_uptrend():
    from bitcoin_ai.research_lab import _signal

    closes = [100.0 - i * 0.5 for i in range(25)]
    assert _signal(closes, 23, "defensive_vol_target_sma", 20) == 0.0


def test_selection_score_penalizes_severe_left_tail_returns():
    metrics = {"sortino_ratio": 1.0, "max_drawdown_pct": -5.0}
    calm = [0.002] * 95 + [-0.005] * 5
    tail_heavy = [0.003] * 95 + [-0.05] * 5
    calm_result = _selection_score(calm, metrics)
    tail_result = _selection_score(tail_heavy, metrics)
    assert calm_result[7] > tail_result[7]
    assert tail_result[8] > calm_result[8]
    assert calm_result[0] > tail_result[0]





def test_research_report_includes_held_out_agent_council_diagnostics():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "agent_council", "lookback": 48}, {"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    diagnostics = result["agent_council_oos_diagnostics"]
    assert diagnostics["observations"] == result["out_of_sample_returns"]
    assert "agent_vote_counts" in diagnostics
    assert "skeptic_intervention_count" in diagnostics

def test_agent_council_is_a_walk_forward_candidate():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "agent_council", "lookback": 48}, {"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    assert "agent_council" in result["families"]
    assert sum(result["training_selection_counts"].values()) == result["fold_count"]


def test_agent_council_candidate_rejects_insufficient_warmup():
    with pytest.raises(BacktestError, match="lookback must be >= 48"):
        run_strategy_lab(
            bars(), train_bars=100, test_bars=30,
            candidates=[{"family": "agent_council", "lookback": 20}],
            bootstrap_trials=100,
        )


def test_agent_council_exposure_caps_scale_the_same_signal():
    from bitcoin_ai.research_lab import _signal

    closes = [100.0 + i for i in range(60)]
    full = _signal(closes, 59, "agent_council", 48)
    half = _signal(closes, 59, "agent_council_50", 48)
    quarter = _signal(closes, 59, "agent_council_25", 48)
    assert full > 0
    assert half == pytest.approx(full * 0.5)
    assert quarter == pytest.approx(full * 0.25)


@pytest.mark.parametrize("family", ["agent_council_50", "agent_council_25"])
def test_risk_capped_agent_council_candidates_are_researchable(family):
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": family, "lookback": 48}, {"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    assert family in result["families"]
    assert sum(result["training_selection_counts"].values()) == result["fold_count"]


def test_risk_capped_agent_council_rejects_insufficient_warmup():
    with pytest.raises(BacktestError, match="agent council lookback must be >= 48"):
        run_strategy_lab(
            bars(), train_bars=100, test_bars=30,
            candidates=[{"family": "agent_council_50", "lookback": 20}],
            bootstrap_trials=100,
        )


def test_fixed_candidate_comparison_reports_paired_regime_attribution():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[
            {"family": "momentum", "lookback": 8},
            {"family": "cash", "lookback": 2},
        ],
        bootstrap_trials=100,
    )
    comparison = result["fixed_candidate_oos_comparison"]
    for candidate in comparison["candidates"].values():
        assert set(candidate["regime_attribution"]) == {
            "uptrend", "downtrend", "range", "high_volatility"
        }
        assert sum(
            regime["observations"]
            for regime in candidate["regime_attribution"].values()
        ) == comparison["observations_per_candidate"]
        for regime in candidate["regime_attribution"].values():
            assert "excess_return_vs_buy_and_hold_pct_points" in regime
            assert "strategy_return_at_2x_cost_pct" in regime
            assert (
                regime["positive_bar_share_pct"] is None
                or 0.0 <= regime["positive_bar_share_pct"] <= 100.0
            )


def test_cash_candidate_has_zero_return_in_every_regime():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    candidate = result["fixed_candidate_oos_comparison"]["candidates"]["cash:2"]
    for regime in candidate["regime_attribution"].values():
        assert regime["strategy_return_pct"] == 0.0
        assert regime["strategy_return_at_2x_cost_pct"] == 0.0


def test_paired_edge_bootstrap_detects_clear_synthetic_relative_edge():
    from bitcoin_ai.research_lab import _paired_edge_bootstrap

    result = _paired_edge_bootstrap(
        [0.01] * 60, [0.001] * 60, trials=200, seed=19,
    )
    assert result["observations"] == 60
    assert result["excess_return_p05_pct"] > 0
    assert result["probability_positive_pct"] == 100.0
    assert result["excess_return_p05_pct"] <= result["excess_return_median_pct"]
    assert result["excess_return_median_pct"] <= result["excess_return_p95_pct"]
    assert "not a formal hypothesis test" in result["interpretation"]


def test_paired_edge_bootstrap_keeps_benchmark_intervals_paired():
    from bitcoin_ai.research_lab import _paired_edge_bootstrap

    result = _paired_edge_bootstrap(
        [0.0] * 60, [0.01] * 60, trials=200, seed=19,
    )
    assert result["observed_excess_return_pct"] < 0
    assert result["excess_return_p95_pct"] < 0
    assert result["probability_positive_pct"] == 0.0


def test_paired_edge_bootstrap_rejects_mismatched_or_invalid_returns():
    from bitcoin_ai.research_lab import _paired_edge_bootstrap

    with pytest.raises(BacktestError, match="equal lengths"):
        _paired_edge_bootstrap([0.01], [], trials=100, seed=1)
    with pytest.raises(BacktestError, match="greater than -1"):
        _paired_edge_bootstrap([-1.0], [0.0], trials=100, seed=1)


def test_fixed_candidate_report_includes_deterministic_edge_uncertainty():
    kwargs = dict(
        train_bars=100, test_bars=30, bootstrap_trials=100, seed=31,
        candidates=[
            {"family": "momentum", "lookback": 8},
            {"family": "cash", "lookback": 2},
        ],
    )
    first = run_strategy_lab(bars(), **kwargs)
    second = run_strategy_lab(bars(), **kwargs)
    for key, candidate in first["fixed_candidate_oos_comparison"]["candidates"].items():
        uncertainty = candidate["paired_edge_uncertainty"]
        assert uncertainty["observations"] == first["out_of_sample_returns"]
        assert uncertainty == second["fixed_candidate_oos_comparison"]["candidates"][key]["paired_edge_uncertainty"]
        assert 0.0 <= uncertainty["probability_positive_pct"] <= 100.0


def test_strategy_abstention_gate_requires_all_conservative_conditions():
    from bitcoin_ai.promotion import evaluate_strategy_abstention

    passing = {
        "paired_edge_uncertainty": {
            "observations": 240,
            "observed_excess_return_pct": 8.0,
            "excess_return_p05_pct": 1.0,
            "probability_positive_pct": 97.0,
        },
        "metrics_at_2x_cost": {"total_return_pct": 3.0},
    }
    result = evaluate_strategy_abstention({"candidate-a": passing})
    assert result["action"] == "manual_review_required"
    assert result["passing_candidates"] == ["candidate-a"]

    weak = {
        "paired_edge_uncertainty": {
            "observations": 240,
            "observed_excess_return_pct": 8.0,
            "excess_return_p05_pct": -1.0,
            "probability_positive_pct": 97.0,
        },
        "metrics_at_2x_cost": {"total_return_pct": 3.0},
    }
    result = evaluate_strategy_abstention({"weak": weak})
    assert result["action"] == "abstain_cash"
    assert "paired edge fifth percentile is not positive" in result["candidate_assessments"]["weak"]["reasons"]


@pytest.mark.parametrize("change", [
    {"observations": 100},
    {"probability_positive_pct": 80.0},
    {"observed_excess_return_pct": -0.1},
    {"excess_return_p05_pct": 0.0},
])
def test_strategy_abstention_gate_fails_closed_on_weak_evidence(change):
    from bitcoin_ai.promotion import evaluate_strategy_abstention

    uncertainty = {
        "observations": 240,
        "observed_excess_return_pct": 4.0,
        "excess_return_p05_pct": 0.5,
        "probability_positive_pct": 98.0,
    }
    uncertainty.update(change)
    candidate = {
        "paired_edge_uncertainty": uncertainty,
        "metrics_at_2x_cost": {"total_return_pct": 1.0},
    }
    result = evaluate_strategy_abstention({"candidate": candidate})
    assert result["action"] == "abstain_cash"
    assert not result["candidate_assessments"]["candidate"]["eligible_for_review"]


def test_strategy_abstention_gate_rejects_candidate_erased_by_costs():
    from bitcoin_ai.promotion import evaluate_strategy_abstention

    candidate = {
        "paired_edge_uncertainty": {
            "observations": 240,
            "observed_excess_return_pct": 4.0,
            "excess_return_p05_pct": 0.5,
            "probability_positive_pct": 98.0,
        },
        "metrics_at_2x_cost": {"total_return_pct": -0.01},
    }
    result = evaluate_strategy_abstention({"candidate": candidate})
    assert result["action"] == "abstain_cash"
    assert "candidate return is not positive at 2x estimated costs" in result["candidate_assessments"]["candidate"]["reasons"]


def test_research_report_includes_report_only_abstention_gate():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[
            {"family": "momentum", "lookback": 8},
            {"family": "cash", "lookback": 2},
        ],
        bootstrap_trials=100,
    )
    gate = result["strategy_abstention_gate"]
    assert gate["action"] in {"abstain_cash", "manual_review_required"}
    assert "momentum:8" in gate["candidate_assessments"]
    assert gate["candidate_assessments"]["cash:2"]["eligible_for_review"] is False
    assert "Report-only" in gate["scope"]


def test_research_lab_embeds_data_quality_audit():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    assert result["data_quality_audit"]["usable"] is True
    assert result["data_quality_audit"]["status"] == "pass"


def test_research_lab_rejects_cadence_gaps_when_interval_is_declared():
    data = bars()
    data[120] = Bar(data[120].timestamp + timedelta(hours=1), data[120].close)
    with pytest.raises(BacktestError, match="data quality audit failed"):
        run_strategy_lab(
            data, train_bars=100, test_bars=30,
            candidates=[{"family": "cash", "lookback": 2}],
            bootstrap_trials=100, expected_interval_seconds=86400,
        )


def test_research_lab_reports_anomaly_warnings_without_rewriting_prices():
    data = bars()
    original_close = data[120].close
    data[120] = Bar(data[120].timestamp, original_close * 1.5)
    result = run_strategy_lab(
        data, train_bars=100, test_bars=30,
        candidates=[{"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    assert result["data_quality_audit"]["status"] == "review"
    assert result["data_quality_audit"]["anomaly_audit"]["outlier_count"] >= 1
    assert data[120].close == original_close * 1.5


def test_research_report_includes_independent_validation_roles():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[
            {"family": "momentum", "lookback": 8},
            {"family": "cash", "lookback": 2},
        ],
        bootstrap_trials=100,
    )
    validation = result["independent_validation"]
    assert validation["verdict"] in {
        "reject", "needs_review", "eligible_for_paper_review"
    }
    assert validation["proposer"]["fixed_candidates"] == ["cash:2", "momentum:8"]
    assert set(validation["skeptic"]["candidate_reviews"]) == {"cash:2", "momentum:8"}
    assert validation["evidence_reviewer"]["candidate_review_coverage"] == 2



def test_research_lab_reports_holdout_records_and_requires_prior_ledger_for_freshness():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    audit = result["holdout_reuse_audit"]
    assert audit["status"] == "no_prior_ledger_supplied"
    assert audit["eligible_for_fresh_holdout_review"] is False
    assert len(audit["ledger_records_to_append"]) == result["fold_count"]
    assert all(len(item["dataset_fingerprint"]) == 64 for item in audit["ledger_records_to_append"])


def test_research_lab_flags_reused_oos_windows_from_supplied_ledger():
    result = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "cash", "lookback": 2}],
        bootstrap_trials=100,
    )
    records = result["holdout_reuse_audit"]["ledger_records_to_append"]
    repeated = run_strategy_lab(
        bars(), train_bars=100, test_bars=30,
        candidates=[{"family": "cash", "lookback": 2}],
        bootstrap_trials=100, previous_holdout_experiments=records,
    )
    audit = repeated["holdout_reuse_audit"]
    assert audit["status"] == "reuse_detected"
    assert audit["eligible_for_fresh_holdout_review"] is False
    assert all(item["status"] == "reuse_detected" for item in audit["fold_audits"])
