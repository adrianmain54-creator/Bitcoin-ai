"""Multi-family walk-forward strategy research and block-bootstrap robustness.

Signals use completed closes and trade only the following bar. All tuning is
confined to each training window; test returns are never used for selection.
This is research tooling, not a profitability claim.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import uuid
from datetime import datetime, timezone
from statistics import mean, pstdev

from .backtesting import BacktestError, Bar, _metrics
from .data_quality import audit_price_bars
from .agents import run_agent_council
from .regime import classify_regime
from .regime_robustness import audit_regime_robustness
from .strategy_failure_analysis import analyze_strategy_failures
from .strategy_improvement import propose_strategy_improvements
from .promotion import (
    evaluate_paper_trial_eligibility,
    evaluate_strategy_abstention,
    evaluate_independent_strategy_validation,
)


def _equity_curve(returns):
    equity = [1.0]
    for value in returns:
        equity.append(equity[-1] * (1.0 + value))
    return equity


DEFAULT_CANDIDATES = [
    {"family": "sma", "lookback": 12},
    {"family": "sma", "lookback": 24},
    {"family": "momentum", "lookback": 5},
    {"family": "momentum", "lookback": 10},
    {"family": "breakout", "lookback": 20},
    {"family": "vol_target_sma", "lookback": 20},
    {"family": "defensive_vol_target_sma", "lookback": 20},
    # Full multi-agent council; 48 bars covers the baseline trend warm-up.
    {"family": "agent_council", "lookback": 48},
    # Same council votes with hard exposure caps, to test risk-adjusted variants.
    {"family": "agent_council_50", "lookback": 48},
    {"family": "agent_council_25", "lookback": 48},
    # Explicit abstention baseline: staying in cash must be a selectable action.
    {"family": "cash", "lookback": 2},
]


def _validate(bars, train_bars, test_bars, candidates, fee_bps, slippage_bps):
    if not isinstance(bars, list) or len(bars) < 3 or any(not isinstance(b, Bar) for b in bars):
        raise BacktestError("bars must be a list of at least 3 Bar observations")
    for index, bar in enumerate(bars):
        if (not hasattr(bar.timestamp, "tzinfo") or bar.timestamp.tzinfo is None
                or bar.timestamp.utcoffset() is None):
            raise BacktestError(f"Bar {index} timestamp must be timezone-aware")
    if any(bars[i].timestamp <= bars[i - 1].timestamp for i in range(1, len(bars))):
        raise BacktestError("Bars must have strictly increasing timestamps")
    if any(not isinstance(b.close, (int, float)) or isinstance(b.close, bool)
           or not math.isfinite(b.close) or b.close <= 0 for b in bars):
        raise BacktestError("Bar closes must be finite positive numbers")
    for value, name in ((train_bars, "train_bars"), (test_bars, "test_bars")):
        if isinstance(value, bool) or not isinstance(value, int) or value < 3:
            raise BacktestError(f"{name} must be an integer >= 3")
    if not isinstance(candidates, (list, tuple)) or not candidates:
        raise BacktestError("At least one strategy candidate is required")
    normalized = []
    for candidate in candidates:
        if not isinstance(candidate, dict) or set(candidate) != {"family", "lookback"}:
            raise BacktestError("Candidates require exactly family and lookback")
        family, lookback = candidate["family"], candidate["lookback"]
        if family not in {"sma", "momentum", "breakout", "vol_target_sma", "defensive_vol_target_sma", "agent_council", "agent_council_50", "agent_council_25", "cash"}:
            raise BacktestError("Unknown strategy family")
        if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 2 or lookback >= train_bars:
            raise BacktestError("lookback must be an integer >= 2 and smaller than train_bars")
        if family in {"agent_council", "agent_council_50", "agent_council_25"} and lookback < 48:
            raise BacktestError("agent council lookback must be >= 48 for the baseline trend warm-up")
        item = (family, lookback)
        if item in normalized:
            raise BacktestError("Duplicate strategy candidates are not allowed")
        normalized.append(item)
    for value, name in ((fee_bps, "fee_bps"), (slippage_bps, "slippage_bps")):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise BacktestError(f"{name} must be finite and non-negative")
    if fee_bps + slippage_bps >= 10000:
        raise BacktestError("Combined costs must be less than 10000 bps")
    return normalized


def _signal(closes, i, family, lookback):
    if family == "cash":
        return 0.0
    if family in {"agent_council", "agent_council_50", "agent_council_25"}:
        # Only closes through i are passed: future bars are unavailable to the council.
        # Variants retain identical votes but impose lower maximum portfolio exposure.
        cap = {"agent_council": 1.0, "agent_council_50": 0.50,
               "agent_council_25": 0.25}[family]
        return run_agent_council(closes[:i + 1], max_allocation=cap).signal.target_allocation
    if family == "sma":
        fast_window = max(1, lookback // 3)
        fast = sum(closes[i - fast_window + 1:i + 1]) / fast_window
        slow = sum(closes[i - lookback + 1:i + 1]) / lookback
        return 1.0 if fast > slow and closes[i] > slow else 0.0
    if family == "momentum":
        return 1.0 if closes[i] > closes[i - lookback] else 0.0
    if family in {"vol_target_sma", "defensive_vol_target_sma"}:
        fast_window = max(1, lookback // 3)
        fast = sum(closes[i - fast_window + 1:i + 1]) / fast_window
        slow = sum(closes[i - lookback + 1:i + 1]) / lookback
        if not (fast > slow and closes[i] > slow):
            return 0.0
        # Both variants use trailing volatility known at close i. The defensive
        # variant targets 20% annualized volatility and caps exposure at 50%.
        trailing_returns = [
            closes[j] / closes[j - 1] - 1.0
            for j in range(i - lookback + 1, i + 1)
        ]
        realized_daily_vol = pstdev(trailing_returns) if len(trailing_returns) > 1 else 0.0
        if family == "defensive_vol_target_sma":
            target_daily_vol = 0.20 / math.sqrt(365.0)
            max_exposure = 0.50
        else:
            target_daily_vol = 0.40 / math.sqrt(365.0)
            max_exposure = 1.0
        return min(max_exposure, target_daily_vol / realized_daily_vol) if realized_daily_vol > 0 else max_exposure
    # Strictly prior rolling high: today's close is not part of the threshold.
    prior_high = max(closes[i - lookback:i])
    return 1.0 if closes[i] > prior_high else 0.0


def _simulate(closes, start, end, family, lookback, cost, *,
              initial_position=0.0, liquidate=True):
    """Simulate a continuous position; fold boundaries need not imply liquidation."""
    position = initial_position
    returns = []
    for i in range(start, end):
        target = _signal(closes, i, family, lookback)
        turnover = abs(target - position)
        market_return = closes[i + 1] / closes[i] - 1.0
        returns.append(target * market_return - turnover * cost)
        position = target
    if liquidate and position and returns:
        returns[-1] -= position * cost
    return returns




def _agent_council_diagnostics(closes, start, end):
    """Aggregate auditable agent votes on held-out bars only."""
    from .agents import run_agent_council

    decisions = {}
    votes = {"trend": {}, "momentum": {}, "regime": {}, "skeptic": {}}
    confidence = []
    observations = 0
    for i in range(start, end):
        report = run_agent_council(closes[:i + 1], max_allocation=1.0)
        observations += 1
        decisions[report.decision] = decisions.get(report.decision, 0) + 1
        confidence.append(report.confidence)
        for agent, vote in report.votes.items():
            bucket = votes.setdefault(agent, {})
            bucket[vote] = bucket.get(vote, 0) + 1
    return {
        "observations": observations,
        "decision_counts": decisions,
        "agent_vote_counts": votes,
        "skeptic_intervention_count": (
            votes["skeptic"].get("veto_disagreement", 0)
            + votes["skeptic"].get("caution", 0)
        ),
        "mean_confidence": round(mean(confidence), 4) if confidence else None,
        "interpretation": "Descriptive held-out diagnostics, not evidence of predictive accuracy.",
    }


def _position_diagnostics(closes, start, end, family, lookback, initial_position=0.0):
    """Return held exposure and turnover for each OOS return interval."""
    positions, turnovers, entries, exits = [], [], [], []
    previous = initial_position
    for i in range(start, end):
        target = _signal(closes, i, family, lookback)
        positions.append(target)
        turnovers.append(abs(target - previous))
        if target > previous:
            entries.append(i)
        elif target < previous:
            exits.append(i)
        previous = target
    return {
        "positions": positions,
        "turnovers": turnovers,
        "entries": entries,
        "exits": exits,
    }


def _attribution(returns, market_returns, positions, turnovers, entries, exits, cost):
    """Summarize exposure, trade activity, gross contribution and estimated costs."""
    count = len(returns)
    gross = sum(position * market for position, market in zip(positions, market_returns))
    cost_drag = sum(turnovers) * cost
    return {
        "observations": count,
        "in_market_bars": sum(position > 0 for position in positions),
        "exposure_pct": round(100 * sum(position > 0 for position in positions) / count, 4) if count else 0.0,
        "average_exposure_pct": round(100 * sum(positions) / count, 4) if count else 0.0,
        "entries": len(entries),
        "exits": len(exits),
        "turnover_events": sum(turnover > 0 for turnover in turnovers),
        "total_turnover_units": round(sum(turnovers), 6),
        "gross_market_return_contribution_pct": round(gross * 100, 4),
        "estimated_cost_drag_pct": round(cost_drag * 100, 4),
        "net_return_pct": round((math.prod(1 + value for value in returns) - 1) * 100, 4),
    }



def _bootstrap(returns, trials, seed, block_size=5):
    if not returns:
        return {"trials": 0, "final_equity_p05": None, "final_equity_median": None,
                "final_equity_p95": None, "max_drawdown_p05_pct": None,
                "max_drawdown_median_pct": None, "max_drawdown_p95_pct": None}
    rng = random.Random(seed)
    finals, drawdowns = [], []
    n = len(returns)
    for _ in range(trials):
        sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            sample.extend(returns[(start + offset) % n] for offset in range(block_size))
        equity = _equity_curve(sample[:n])
        finals.append(equity[-1])
        peak, worst = 1.0, 0.0
        for value in equity:
            peak = max(peak, value)
            worst = min(worst, value / peak - 1.0)
        drawdowns.append(worst * 100)
    def percentile(values, p):
        ordered = sorted(values)
        return ordered[round((len(ordered) - 1) * p)]
    return {
        "trials": trials,
        "block_size": block_size,
        "final_equity_p05": round(percentile(finals, .05), 6),
        "final_equity_median": round(percentile(finals, .50), 6),
        "final_equity_p95": round(percentile(finals, .95), 6),
        "max_drawdown_p05_pct": round(percentile(drawdowns, .05), 4),
        "max_drawdown_median_pct": round(percentile(drawdowns, .50), 4),
        "max_drawdown_p95_pct": round(percentile(drawdowns, .95), 4),
        "warning": "Bootstrap resamples historical returns; it is not a forecast and cannot model unseen regimes.",
    }



def _paired_edge_bootstrap(strategy_returns, benchmark_returns, trials, seed, block_size=5):
    """Estimate uncertainty in compounded relative performance using paired blocks.

    Pairing preserves the same market intervals for strategy and benchmark.
    This is a descriptive historical uncertainty interval, not a p-value.
    """
    if len(strategy_returns) != len(benchmark_returns):
        raise BacktestError("Paired strategy and benchmark returns must have equal lengths")
    if not strategy_returns:
        return {
            "trials": 0, "observations": 0,
            "excess_return_p05_pct": None, "excess_return_median_pct": None,
            "excess_return_p95_pct": None, "probability_positive_pct": None,
            "interpretation": "No paired held-out observations are available.",
        }
    paired = []
    for strategy, benchmark in zip(strategy_returns, benchmark_returns):
        if (not isinstance(strategy, (int, float)) or isinstance(strategy, bool)
                or not math.isfinite(strategy) or strategy <= -1
                or not isinstance(benchmark, (int, float)) or isinstance(benchmark, bool)
                or not math.isfinite(benchmark) or benchmark <= -1):
            raise BacktestError("Paired returns must be finite numbers greater than -1")
        paired.append(math.log1p(strategy) - math.log1p(benchmark))
    rng = random.Random(seed)
    n = len(paired)
    block_size = min(block_size, n)
    samples = []
    observed_log_edge = sum(paired)
    centered = [value - mean(paired) for value in paired]
    null_exceedances = 0
    for _ in range(trials):
        sample = []
        null_sample = []
        while len(sample) < n:
            start = rng.randrange(n)
            indices = [(start + offset) % n for offset in range(block_size)]
            sample.extend(paired[index] for index in indices)
            null_sample.extend(centered[index] for index in indices)
        sample = sample[:n]
        null_sample = null_sample[:n]
        samples.append((math.exp(sum(sample)) - 1.0) * 100.0)
        if sum(null_sample) >= observed_log_edge:
            null_exceedances += 1
    # Plus-one correction avoids a zero Monte Carlo p-value. This is an
    # approximate one-sided null-centered circular block-bootstrap test,
    # not an exact finite-sample test.
    bootstrap_null_p_value = (null_exceedances + 1) / (trials + 1)

    def percentile(values, p):
        ordered = sorted(values)
        return ordered[round((len(ordered) - 1) * p)]

    observed = (math.exp(sum(paired)) - 1.0) * 100.0
    return {
        "trials": trials,
        "observations": n,
        "block_size": block_size,
        "observed_excess_return_pct": round(observed, 4),
        "excess_return_p05_pct": round(percentile(samples, 0.05), 4),
        "excess_return_median_pct": round(percentile(samples, 0.50), 4),
        "excess_return_p95_pct": round(percentile(samples, 0.95), 4),
        "probability_positive_pct": round(100.0 * sum(value > 0 for value in samples) / trials, 2),
        "bootstrap_null_p_value": round(bootstrap_null_p_value, 8),
        "bootstrap_null_test": "one-sided null-centered paired circular block bootstrap with plus-one Monte Carlo correction",
        "interpretation": (
            "Paired circular block-bootstrap uncertainty from historical held-out intervals. "
            "This descriptive interval is not a formal hypothesis test. "
            "The separate null-centered bootstrap p-value is approximate, assumption-dependent, "
            "and not a forecast of unseen regimes."
        ),
    }


def _selection_score(returns, metrics, regime_labels=None, *,
                    turnover_units=0.0, turnover_penalty_weight=0.05):
    """Score training candidates, including a small normalized turnover regularizer."""
    segment_count = min(4, len(returns))
    segment_returns = []
    for index in range(segment_count):
        start = index * len(returns) // segment_count
        end = (index + 1) * len(returns) // segment_count
        segment_returns.append(math.prod(1.0 + value for value in returns[start:end]) - 1.0)
    positive_share = sum(value > 0 for value in segment_returns) / segment_count
    worst_segment_pct = min(segment_returns) * 100.0
    drawdown_penalty = abs(metrics["max_drawdown_pct"]) / 10.0
    worst_segment_penalty = abs(min(0.0, worst_segment_pct)) / 10.0
    regime_means = []
    if regime_labels is not None and len(regime_labels) == len(returns):
        for label in ("uptrend", "downtrend", "range", "high_volatility"):
            bucket = [value for value, regime in zip(returns, regime_labels) if regime == label]
            if len(bucket) >= 3:
                regime_means.append((label, math.prod(1.0 + value for value in bucket) - 1.0))
    worst_regime_pct = min((value * 100.0 for _, value in regime_means), default=0.0)
    regime_penalty = abs(min(0.0, worst_regime_pct)) / 20.0
    turnover_per_100_bars = turnover_units / max(1, len(returns)) * 100.0
    turnover_penalty = turnover_penalty_weight * turnover_per_100_bars
    # Penalize the average of the worst 5% of training bars, not just peak-to-
    # trough drawdown. This discourages candidates with ugly single-bar tails.
    tail_count = max(1, math.ceil(len(returns) * 0.05))
    worst_tail_pct = mean(sorted(returns)[:tail_count]) * 100.0
    tail_loss_penalty = abs(min(0.0, worst_tail_pct)) / 10.0
    score = (metrics["sortino_ratio"] - drawdown_penalty + positive_share
             - worst_segment_penalty - regime_penalty - turnover_penalty
             - tail_loss_penalty)
    return (score, positive_share, worst_segment_pct, worst_regime_pct,
            len(regime_means), turnover_per_100_bars, turnover_penalty,
            worst_tail_pct, tail_loss_penalty)


def run_strategy_lab(bars: list[Bar], *, train_bars: int, test_bars: int,
                     candidates=None, step_bars=None, fee_bps=10.0,
                     slippage_bps=5.0, periods_per_year=365.0,
                     bootstrap_trials=500, seed=7,
                     expected_interval_seconds=None,
                     previous_holdout_experiments=None,
                     candidate_registry_path=None, code_revision=None):
    """Compare candidates using rolling OOS folds after auditing source data."""
    candidates = DEFAULT_CANDIDATES if candidates is None else candidates
    data_quality_report = audit_price_bars(
        bars, expected_interval_seconds=expected_interval_seconds,
    )
    if not data_quality_report["usable"]:
        raise BacktestError(
            "Historical data quality audit failed: "
            + "; ".join(data_quality_report["errors"])
        )
    normalized = _validate(bars, train_bars, test_bars, candidates, fee_bps, slippage_bps)
    step = test_bars if step_bars is None else step_bars
    if isinstance(step, bool) or not isinstance(step, int) or step < test_bars:
        raise BacktestError("step_bars must be an integer >= test_bars")
    if isinstance(bootstrap_trials, bool) or not isinstance(bootstrap_trials, int) or not 100 <= bootstrap_trials <= 10000:
        raise BacktestError("bootstrap_trials must be an integer between 100 and 10000")
    if isinstance(seed, bool) or not isinstance(seed, int):
        raise BacktestError("seed must be an integer")
    if isinstance(periods_per_year, bool) or not isinstance(periods_per_year, (int, float)) or not math.isfinite(periods_per_year) or periods_per_year <= 0:
        raise BacktestError("periods_per_year must be finite and positive")

    # Fingerprint the exact input and pre-register every fixed candidate before
    # the first held-out return is evaluated. The broad first-to-last test span
    # is intentionally conservative when walk-forward folds have gaps.
    canonical_dataset = json.dumps(
        [{"timestamp": bar.timestamp.isoformat(), "close": float(bar.close)} for bar in bars],
        sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")
    dataset_fingerprint = hashlib.sha256(canonical_dataset).hexdigest()
    candidate_trial_ids = {}
    registry_test_start = registry_test_end = None
    if candidate_registry_path is not None:
        if not isinstance(code_revision, str) or not code_revision.strip():
            raise BacktestError("code_revision is required when candidate_registry_path is supplied")
        from .candidate_registry import register_candidate_trial
        preview_cursor = train_bars
        planned_windows = []
        while preview_cursor + test_bars < len(bars):
            planned_windows.append((preview_cursor, preview_cursor + test_bars))
            preview_cursor += step
        if not planned_windows:
            raise BacktestError("Not enough bars to pre-register a candidate holdout window")
        registry_test_start = bars[planned_windows[0][0]].timestamp.isoformat()
        registry_test_end = bars[planned_windows[-1][1]].timestamp.isoformat()
        registry_run_id = uuid.uuid4().hex
        registered_at = datetime.now(timezone.utc).isoformat()
        for family, lookback in normalized:
            candidate_name = f"{family}:{lookback}"
            trial_id = f"{registry_run_id}:{candidate_name}"
            register_candidate_trial(
                candidate_registry_path,
                trial_id=trial_id,
                candidate_name=candidate_name,
                strategy_definition={
                    "family": family,
                    "lookback": lookback,
                    "fee_bps": float(fee_bps),
                    "slippage_bps": float(slippage_bps),
                    "periods_per_year": float(periods_per_year),
                    "train_bars": train_bars,
                    "test_bars": test_bars,
                    "step_bars": step,
                    "expected_interval_seconds": expected_interval_seconds,
                    "bootstrap_trials": bootstrap_trials,
                    "seed": seed,
                    "test_window_policy": "first-to-last-walk-forward-test-window",
                },
                dataset_fingerprint=dataset_fingerprint,
                code_revision=code_revision,
                test_start=registry_test_start,
                test_end=registry_test_end,
                registered_at=registered_at,
            )
            candidate_trial_ids[candidate_name] = trial_id
    closes = [float(b.close) for b in bars]
    cost = (fee_bps + slippage_bps) / 10000
    cursor, folds, oos, benchmark, stress_oos = train_bars, [], [], [], []
    oos_regimes = []
    oos_timestamps = []
    oos_positions, oos_turnovers, oos_market_returns = [], [], []
    oos_entries, oos_exits = [], []
    family_attribution = {}
    oos_position = 0.0
    stress_position = 0.0
    regime_counts = {"uptrend": 0, "downtrend": 0, "range": 0, "high_volatility": 0}
    selection_counts = {family: 0 for family, _ in normalized}
    # Counterfactual fixed-candidate portfolios share every held-out interval.
    comparison_returns = {item: [] for item in normalized}
    comparison_stress_returns = {item: [] for item in normalized}
    comparison_positions = {item: 0.0 for item in normalized}
    comparison_stress_positions = {item: 0.0 for item in normalized}
    regime_lookback = min(20, max(3, train_bars - 1))
    oos_start_index = None
    oos_end_index = None
    while cursor + test_bars < len(bars):
        scored = []
        # Every candidate must be scored on the same effective training dates.
        # The longest warm-up is shared so candidates are compared fairly.
        train_start = cursor - train_bars + max(max(lookback for _, lookback in normalized), regime_lookback)
        for family, lookback in normalized:
            train_returns = _simulate(closes, train_start, cursor - 1, family, lookback, cost)
            # Select against doubled estimated costs, not just the base-cost case.
            # This makes fee sensitivity part of training selection rather than
            # a report-only diagnostic after a candidate has already been chosen.
            stress_train_returns = _simulate(
                closes, train_start, cursor - 1, family, lookback, cost * 2
            )
            if not train_returns or not stress_train_returns:
                continue
            base_metrics = _metrics(
                train_returns, _equity_curve(train_returns), periods_per_year
            )
            stress_metrics = _metrics(
                stress_train_returns, _equity_curve(stress_train_returns), periods_per_year
            )
            train_diagnostics = _position_diagnostics(
                closes, train_start, cursor - 1, family, lookback
            )
            # Include the terminal liquidation, matching _simulate's training cost.
            training_turnover = sum(train_diagnostics["turnovers"])
            if train_diagnostics["positions"] and train_diagnostics["positions"][-1]:
                training_turnover += train_diagnostics["positions"][-1]
            training_cost_drag_pct = training_turnover * cost * 2 * 100
            # Regimes use only trailing observations available at each training close.
            train_regimes = [
                classify_regime(closes[max(0, i - regime_lookback):i + 1],
                                lookback=regime_lookback)["regime"]
                for i in range(train_start, cursor - 1)
            ]
            score_result = _selection_score(
                stress_train_returns, stress_metrics, train_regimes,
                turnover_units=training_turnover,
            )
            (score, positive_share, worst_segment_pct, worst_regime_pct,
             regime_coverage, turnover_per_100_bars, turnover_penalty,
             worst_tail_pct, tail_loss_penalty) = score_result
            scored.append((score, family, lookback, stress_metrics, positive_share,
                           worst_segment_pct, worst_regime_pct, regime_coverage,
                           base_metrics, training_turnover, training_cost_drag_pct,
                           turnover_per_100_bars, turnover_penalty,
                           worst_tail_pct, tail_loss_penalty))
        if not scored:
            raise BacktestError("Training window produced no candidate scores")
        chosen = max(scored, key=lambda item: (item[0], item[1], -item[2]))
        # Preserve the training-only ranking so every adaptive choice is auditable.
        candidate_ranking = sorted(scored, key=lambda item: (item[0], item[1], -item[2]), reverse=True)
        best_score = candidate_ranking[0][0]
        candidate_diagnostics = [
            {
                "family": item[1],
                "lookback": item[2],
                "training_score": round(item[0], 6),
                "score_gap_from_best": round(best_score - item[0], 6),
                "training_sortino_at_2x_cost": round(item[3]["sortino_ratio"], 6),
                "training_max_drawdown_pct_at_2x_cost": round(item[3]["max_drawdown_pct"], 4),
                "training_positive_segment_share": round(item[4], 4),
                "training_worst_segment_return_pct": round(item[5], 4),
                "training_worst_regime_return_pct": round(item[6], 4),
                "training_turnover_per_100_bars": round(item[11], 4),
                "training_turnover_penalty": round(item[12], 4),
                "training_worst_5pct_bar_return_pct": round(item[13], 4),
                "training_tail_loss_penalty": round(item[14], 4),
            }
            for item in candidate_ranking
        ]
        family, lookback = chosen[1], chosen[2]
        test_start = cursor
        test_end = cursor + test_bars
        if oos_start_index is None:
            oos_start_index = test_start
        oos_end_index = test_end
        # Include training history so the first test signal has sufficient lookback.
        contiguous_folds = step == test_bars
        fold_returns = _simulate(
            closes, test_start, test_end, family, lookback, cost,
            initial_position=oos_position if contiguous_folds and folds else 0.0,
            liquidate=not contiguous_folds,
        )
        # Track the same position path used by the simulator for attribution.
        fold_initial_position = oos_position if contiguous_folds and folds else 0.0
        diagnostics = _position_diagnostics(
            closes, test_start, test_end, family, lookback, fold_initial_position
        )
        # Keep the training-selected candidate fixed while doubling estimated costs.
        stress_returns = _simulate(
            closes, test_start, test_end, family, lookback, cost * 2,
            initial_position=stress_position if contiguous_folds and folds else 0.0,
            liquidate=not contiguous_folds,
        )
        oos_position = _signal(closes, test_end - 1, family, lookback)
        stress_position = oos_position
        market_returns = [closes[i + 1] / closes[i] - 1 for i in range(test_start, test_end)]
        # Evaluate every fixed candidate on these exact held-out bars, independent
        # of which candidate the adaptive selector chose for this fold.
        for candidate in normalized:
            candidate_family, candidate_lookback = candidate
            initial = comparison_positions[candidate] if contiguous_folds and folds else 0.0
            stress_initial = comparison_stress_positions[candidate] if contiguous_folds and folds else 0.0
            candidate_returns = _simulate(
                closes, test_start, test_end, candidate_family, candidate_lookback,
                cost, initial_position=initial, liquidate=not contiguous_folds,
            )
            candidate_stress = _simulate(
                closes, test_start, test_end, candidate_family, candidate_lookback,
                cost * 2, initial_position=stress_initial, liquidate=not contiguous_folds,
            )
            comparison_returns[candidate].extend(candidate_returns)
            comparison_stress_returns[candidate].extend(candidate_stress)
            next_position = _signal(closes, test_end - 1, candidate_family, candidate_lookback)
            comparison_positions[candidate] = next_position
            comparison_stress_positions[candidate] = next_position
        fold_regimes = []
        for i in range(test_start, test_end):
            label = classify_regime(closes[max(0, i - regime_lookback):i + 1],
                                    lookback=regime_lookback)["regime"]
            regime_counts[label] += 1
            fold_regimes.append(label)
        oos.extend(fold_returns)
        stress_oos.extend(stress_returns)
        benchmark.extend(market_returns)
        oos_regimes.extend(fold_regimes)
        oos_timestamps.extend(bars[i + 1].timestamp.isoformat() for i in range(test_start, test_end))
        oos_positions.extend(diagnostics["positions"])
        oos_turnovers.extend(diagnostics["turnovers"])
        oos_market_returns.extend(market_returns)
        oos_entries.extend(diagnostics["entries"])
        oos_exits.extend(diagnostics["exits"])
        family_bucket = family_attribution.setdefault(family, {
            "returns": [], "market_returns": [], "positions": [], "turnovers": [],
            "entries": [], "exits": [], "cost": cost,
        })
        family_bucket["returns"].extend(fold_returns)
        family_bucket["market_returns"].extend(market_returns)
        family_bucket["positions"].extend(diagnostics["positions"])
        family_bucket["turnovers"].extend(diagnostics["turnovers"])
        family_bucket["entries"].extend(diagnostics["entries"])
        family_bucket["exits"].extend(diagnostics["exits"])
        selection_counts[family] += 1
        folds.append({
            "train_start": bars[cursor - train_bars].timestamp.isoformat(),
            "train_end": bars[cursor - 1].timestamp.isoformat(),
            "training_scoring_start": bars[train_start].timestamp.isoformat(),
            "training_scoring_observations": len(_simulate(closes, train_start, cursor - 1, family, lookback, cost)),
            "test_start": bars[test_start].timestamp.isoformat(),
            "test_end": bars[test_end].timestamp.isoformat(),
            "selected_family": family, "selected_lookback": lookback,
            "training_selection_score": round(chosen[0], 4),
            "training_runner_up_score": round(candidate_ranking[1][0], 4) if len(candidate_ranking) > 1 else None,
            "training_winner_margin": round(chosen[0] - candidate_ranking[1][0], 4) if len(candidate_ranking) > 1 else None,
            "training_candidate_ranking": candidate_diagnostics,
            "training_sortino_at_2x_cost": chosen[3]["sortino_ratio"],
            "training_base_cost_sortino": chosen[8]["sortino_ratio"],
            "training_turnover_units": round(chosen[9], 6),
            "training_cost_drag_at_2x_pct": round(chosen[10], 4),
            "training_turnover_per_100_bars": round(chosen[11], 4),
            "training_turnover_penalty": round(chosen[12], 4),
            "training_worst_5pct_bar_return_pct": round(chosen[13], 4),
            "training_tail_loss_penalty": round(chosen[14], 4),
            "training_positive_segment_share": round(chosen[4], 4),
            "training_worst_segment_return_pct": round(chosen[5], 4),
            "training_worst_regime_return_pct": round(chosen[6], 4),
            "training_regimes_scored": chosen[7],
            "oos_metrics": _metrics(fold_returns, _equity_curve(fold_returns), periods_per_year),
            "oos_metrics_at_2x_cost": _metrics(stress_returns, _equity_curve(stress_returns), periods_per_year),
        })
        cursor += step
    if not folds:
        raise BacktestError("Not enough bars for one complete train/test fold")
    # Liquidate once at the end of the complete OOS stream, not at every
    # contiguous model-reselection boundary.
    if step == test_bars and oos_position:
        oos[-1] -= oos_position * cost
        stress_oos[-1] -= stress_position * cost * 2
        # Include the final liquidation in portfolio-level turnover and exits.
        oos_turnovers[-1] += oos_position
        if oos_position:
            oos_exits.append(len(oos) - 1)
    if step == test_bars:
        for candidate in normalized:
            position = comparison_positions[candidate]
            if position and comparison_returns[candidate]:
                comparison_returns[candidate][-1] -= position * cost
            stress_position_for_candidate = comparison_stress_positions[candidate]
            if stress_position_for_candidate and comparison_stress_returns[candidate]:
                comparison_stress_returns[candidate][-1] -= stress_position_for_candidate * cost * 2
    # Regime buckets are descriptive slices of held-out returns, never tuning inputs.
    regime_metrics = {}
    for label in regime_counts:
        strategy_slice = [value for value, regime in zip(oos, oos_regimes) if regime == label]
        benchmark_slice = [value for value, regime in zip(benchmark, oos_regimes) if regime == label]
        regime_indices = [i for i, regime in enumerate(oos_regimes) if regime == label]
        regime_metrics[label] = {
            "observations": len(strategy_slice),
            "strategy": _metrics(strategy_slice, _equity_curve(strategy_slice), periods_per_year),
            "buy_and_hold": _metrics(benchmark_slice, _equity_curve(benchmark_slice), periods_per_year),
            "attribution": _attribution(
                [oos[i] for i in regime_indices],
                [oos_market_returns[i] for i in regime_indices],
                [oos_positions[i] for i in regime_indices],
                [oos_turnovers[i] for i in regime_indices],
                [], [], cost,
            ),
            "interpretation": "Descriptive out-of-sample subset; small samples are not reliable evidence.",
        }
    overall_attribution = _attribution(
        oos, oos_market_returns, oos_positions, oos_turnovers,
        oos_entries, oos_exits, cost,
    )
    family_metrics = {}
    for family, bucket in family_attribution.items():
        family_metrics[family] = {
            "folds_selected": selection_counts[family],
            "strategy": _metrics(bucket["returns"], _equity_curve(bucket["returns"]), periods_per_year),
            "attribution": _attribution(
                bucket["returns"], bucket["market_returns"], bucket["positions"],
                bucket["turnovers"], bucket["entries"], bucket["exits"], cost,
            ),
            "interpretation": "Descriptive results only for folds where this family was selected; selection is adaptive.",
        }
    benchmark_equity = math.prod(1.0 + value for value in benchmark)
    fixed_candidate_comparison = {}
    for candidate_index, (family, lookback) in enumerate(normalized):
        key = f"{family}:{lookback}"
        candidate_returns = comparison_returns[(family, lookback)]
        candidate_equity = math.prod(1.0 + value for value in candidate_returns)
        # Attribute each fixed candidate on the same held-out regime labels
        # and intervals as buy-and-hold. These are descriptive slices only.
        candidate_regimes = {}
        candidate_stress_returns = comparison_stress_returns[(family, lookback)]
        for label in regime_counts:
            indices = [i for i, regime in enumerate(oos_regimes) if regime == label]
            strategy_slice = [candidate_returns[i] for i in indices]
            benchmark_slice = [benchmark[i] for i in indices]
            stress_slice = [candidate_stress_returns[i] for i in indices]
            strategy_equity = math.prod(1.0 + value for value in strategy_slice)
            benchmark_regime_equity = math.prod(1.0 + value for value in benchmark_slice)
            candidate_regimes[label] = {
                "observations": len(indices),
                "strategy_return_pct": round((strategy_equity - 1.0) * 100.0, 4),
                "buy_and_hold_return_pct": round((benchmark_regime_equity - 1.0) * 100.0, 4),
                "excess_return_vs_buy_and_hold_pct_points": round(
                    (strategy_equity - benchmark_regime_equity) * 100.0, 4
                ),
                "strategy_return_at_2x_cost_pct": round(
                    (math.prod(1.0 + value for value in stress_slice) - 1.0) * 100.0, 4
                ),
                "positive_bar_share_pct": round(
                    100.0 * sum(value > 0 for value in strategy_slice) / len(strategy_slice), 4
                ) if strategy_slice else None,
            }
        fixed_candidate_comparison[key] = {
            "regime_attribution": candidate_regimes,
            "family": family,
            "lookback": lookback,
            "observations": len(candidate_returns),
            "metrics": _metrics(candidate_returns, _equity_curve(candidate_returns), periods_per_year),
            "return_pct": round((candidate_equity - 1.0) * 100.0, 4),
            "excess_return_vs_buy_and_hold_pct_points": round((candidate_equity - benchmark_equity) * 100.0, 4),
            "paired_edge_uncertainty": _paired_edge_bootstrap(
                candidate_returns, benchmark, bootstrap_trials, seed + candidate_index,
            ),
            "metrics_at_2x_cost": _metrics(
                comparison_stress_returns[(family, lookback)],
                _equity_curve(comparison_stress_returns[(family, lookback)]),
                periods_per_year,
            ),
        }
    strategy_failure_reports = {}
    for family, lookback in normalized:
        key = f"{family}:{lookback}"
        strategy_failure_reports[key] = analyze_strategy_failures(
            comparison_returns[(family, lookback)],
            stress_returns=comparison_stress_returns[(family, lookback)],
            regimes=oos_regimes,
            timestamps=oos_timestamps,
        )

    strategy_improvement_proposals = {
        name: propose_strategy_improvements(name, report)
        for name, report in strategy_failure_reports.items()
    }

    # Holdout identity was fingerprinted before any test-window evaluation.
    from .holdout_audit import audit_holdout_reuse

    prior_ledger = [] if previous_holdout_experiments is None else previous_holdout_experiments
    holdout_audits = []
    holdout_ledger_records = []
    experiment_run_id = uuid.uuid4().hex
    for fold_index, fold in enumerate(folds):
        proposed = {
            "experiment_id": f"{experiment_run_id}:fold-{fold_index + 1}",
            "dataset_fingerprint": dataset_fingerprint,
            "test_start": fold["test_start"],
            "test_end": fold["test_end"],
        }
        audit = audit_holdout_reuse(prior_ledger, proposed)
        holdout_audits.append(audit)
        holdout_ledger_records.append(proposed)
    holdout_reuse_detected = any(
        item["status"] == "reuse_detected" for item in holdout_audits
    )
    if candidate_registry_path is not None:
        from .candidate_registry import audit_candidate_family, complete_candidate_trial
        completed_at = datetime.now(timezone.utc).isoformat()
        for candidate_name, candidate in fixed_candidate_comparison.items():
            uncertainty = candidate["paired_edge_uncertainty"]
            complete_candidate_trial(
                candidate_registry_path,
                trial_id=candidate_trial_ids[candidate_name],
                outcome={
                    "bootstrap_null_p_value": uncertainty["bootstrap_null_p_value"],
                    "observations": uncertainty["observations"],
                    "return_pct": candidate["return_pct"],
                    "excess_return_vs_buy_and_hold_pct_points": candidate[
                        "excess_return_vs_buy_and_hold_pct_points"
                    ],
                },
                completed_at=completed_at,
            )
        candidate_family_audit = audit_candidate_family(
            candidate_registry_path,
            dataset_fingerprint=dataset_fingerprint,
            test_start=registry_test_start,
            test_end=registry_test_end,
        )
    else:
        candidate_family_audit = {
            "status": "not_supplied",
            "candidate_count": 0,
            "registered_trials": [],
            "incomplete_trials": [],
            "warning": "No durable candidate registry was supplied; family completeness is unverified.",
        }

    report = {
        "candidate_registry_audit": candidate_family_audit,
        "holdout_reuse_audit": {
            "status": "reuse_detected" if holdout_reuse_detected else (
                "no_prior_ledger_supplied" if previous_holdout_experiments is None
                else "no_overlap_detected"
            ),
            "dataset_fingerprint": dataset_fingerprint,
            "fold_audits": holdout_audits,
            "ledger_records_to_append": holdout_ledger_records,
            "eligible_for_fresh_holdout_review": (
                previous_holdout_experiments is not None and not holdout_reuse_detected
            ),
            "warning": (
                "Append ledger_records_to_append to a durable append-only ledger after "
                "the run. If no prior ledger was supplied, freshness cannot be assessed."
            ),
        },
        "data_quality_audit": data_quality_report,
        "method": "multi-family rolling walk-forward with regime-conditioned OOS analysis, defensive volatility targeting, fixed-candidate paired OOS comparison, and cost stress",
        "regime_robustness_audit": audit_regime_robustness(fixed_candidate_comparison),
        "strategy_failure_analysis": strategy_failure_reports,
        "strategy_improvement_proposals": strategy_improvement_proposals,
        "fixed_candidate_oos_comparison": {
            "candidates": fixed_candidate_comparison,
            "observations_per_candidate": len(benchmark),
            "buy_and_hold_return_pct": round((benchmark_equity - 1.0) * 100.0, 4),
            "interpretation": "Every listed candidate is run on the same held-out intervals with identical costs and no fold-by-fold winner selection. Candidate definitions were specified before evaluating these held-out results; these comparisons are descriptive, not proof of future performance.",
        },
        "families": sorted({family for family, _ in normalized}),
        "fold_count": len(folds),
        "out_of_sample_returns": len(oos),
        "out_of_sample_metrics": _metrics(oos, _equity_curve(oos), periods_per_year),
        "out_of_sample_attribution": overall_attribution,
        "agent_council_oos_diagnostics": _agent_council_diagnostics(closes, oos_start_index, oos_end_index),
        "selected_family_attribution": family_metrics,
        "buy_and_hold_metrics": _metrics(benchmark, _equity_curve(benchmark), periods_per_year),
        "cash_metrics": _metrics([0.0] * len(oos), _equity_curve([0.0] * len(oos)), periods_per_year),
        "bootstrap": _bootstrap(oos, bootstrap_trials, seed),
        "out_of_sample_metrics_at_2x_cost": _metrics(stress_oos, _equity_curve(stress_oos), periods_per_year),
        "out_of_sample_regime_counts": regime_counts,
        "out_of_sample_regime_metrics": regime_metrics,
        "training_selection_counts": selection_counts,
        "training_selection_stability": {
            "most_selected_family": max(selection_counts, key=selection_counts.get),
            "selection_share_pct": round(max(selection_counts.values()) / len(folds) * 100, 2),
            "warning": "Selection frequency is descriptive and does not establish superiority.",
        },
        "folds": folds,
        "selection_policy": "Maximize training Sortino calculated after doubling estimated fees and slippage, minus 0.1 times absolute training max drawdown percentage, plus positive-segment share, minus 0.1 times the absolute worst negative segment return percentage, minus 0.05 times the absolute worst negative training-regime return percentage, and minus 0.05 times training turnover units per 100 scored bars, and minus one tenth of the average return of the worst 5% of training bars (if negative). Turnover includes terminal liquidation. Turnover penalty is a modest regularizer in addition to directly modeled execution costs, not a substitute for fees. Regimes use trailing observations available at each training timestamp; regime buckets require at least 3 observations. Deterministic tie-break; test data never selects parameters.",
        "limitations": [
            "Close-only signals execute on the next close-to-close interval; estimated fee and slippage are charged on position changes and fold liquidation.",
            "No spread, market impact, partial fills, funding, taxes, outages, or latency are modeled.",
            "Block bootstrap resamples concatenated fold returns; fold boundaries and changing market structure limit interpretation.",
            "Regime-conditioned and selected-family attribution are descriptive; adaptive fold selection means family subsets are not independent strategy backtests.",
            "Exposure and trade attribution use the selected position held over each OOS close-to-close interval; entries/exits count position transitions and costs are estimated from turnover.",
            "Gross contribution and cost drag are additive return contributions, while net return is compounded; they should not be expected to sum exactly to net return.",
            "All candidates in a fold are scored on identical effective training dates after the shared maximum warm-up.",
            "The 2x-cost scenario is a sensitivity check, not a calibrated execution-cost forecast.",
            "Research results do not establish future profitability; paper trading remains the only execution mode.",
        ],
    }
    report["strategy_abstention_gate"] = evaluate_strategy_abstention(
        fixed_candidate_comparison
    )
    report["paper_trial_eligibility"] = evaluate_paper_trial_eligibility(report)
    report["independent_validation"] = evaluate_independent_strategy_validation(
        fixed_candidate_comparison, data_quality_report,
        holdout_reuse_audit=report["holdout_reuse_audit"],
        candidate_family_audit=candidate_family_audit,
    )
    return report
