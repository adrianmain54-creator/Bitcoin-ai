# Bitcoin AI

A Bitcoin-native intelligence and automated-trading research project built from a transparent, testable foundation.

**Goal:** develop a BTC system that can monitor markets and make disciplined buy/sell/hold decisions around the clock. **Current execution is simulation-only.** The project is designed around a $0 software budget using local development and public data sources.

## What exists now

- A 25-record curated Bitcoin knowledge corpus spanning fundamentals, transactions/UTXOs, mining, peer-to-peer networking, node modes, Bitcoin Core, wallet standards, SegWit, Taproot, PSBT, and Lightning.
- Per-record publisher, canonical URL, retrieval date, topics, and explicit license-review status.
- Deterministic IDF-weighted retrieval with cited excerpts and abstention when evidence is insufficient.
- Corpus integrity checks and an audit command.
- A read-only public data adapter for BTC spot price, block height, mempool statistics, and recommended transaction fees, with provenance and bounded caching.
- A CSV-based SMA research backtester with configurable fee/slippage assumptions and buy-and-hold comparison.
- A rolling walk-forward research engine that selects parameters only on prior training windows and reports non-overlapping, out-of-sample results against buy-and-hold.
- A multi-family research lab comparing SMA trend, momentum, and breakout rules with training-only selection, downside-risk scoring, cash/buy-and-hold benchmarks, deterministic block-bootstrap ranges, regime-conditioned out-of-sample metrics, selection-stability reporting, and a 2x execution-cost sensitivity test.
- Causal trailing-window regime labels and a fail-closed evidence gate for eligibility to begin a separately monitored paper-forward trial. The gate never authorizes live trading.
- A **paper-only portfolio execution simulator** that caps BTC allocation, models fees and adverse slippage, and records simulated fills.
- An explainable SMA trend-signal baseline and independent fail-closed risk gates (20% default exposure cap, 2% daily-loss halt, 10% drawdown halt, stale-data rejection, cooldown, and kill switch).
- A one-cycle autonomous paper-trading orchestrator that connects signals, risk decisions, and simulated execution; risk halts de-risk to cash while stale data blocks trading.
- A public Binance BTC/USDT candle adapter that validates candles and excludes the still-forming candle.
- Atomic, versioned persistence for simulated balances, trade history, and risk state.
- A restart-safe continuous paper service and `bitcoin-ai paper-run` command; it polls public 1-minute candles and never sends exchange orders.
- A read-only `bitcoin-ai paper-report` command for mark-to-market equity, net P&L, exposure, simulated fees, and clearly qualified checkpoint drawdown.
- An on-demand GitHub Actions workflow that downloads completed BTC/USDT daily candles, runs the walk-forward research lab with 2x-cost stress and regime breakdowns, and uploads the full report as an artifact.\n- GitHub Actions CI and unit tests.

This is **not yet a trained Bitcoin model, a validated profitable strategy, or a hosted always-on trading bot**. The market data adapter is read-only; the paper broker never submits exchange orders. Backtests and simulations do not guarantee future results.

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
bitcoin-ai ask "How does a Bitcoin transaction use UTXOs?"
bitcoin-ai network --currency USD
bitcoin-ai walk-forward --csv ./btc-daily.csv --train-bars 365 --test-bars 90 --periods-per-year 365
bitcoin-ai research-lab --csv ./btc-daily.csv --train-bars 365 --test-bars 90 --bootstrap-trials 500 --experiment-ledger ./research-holdouts.json
bitcoin-ai paper-run --state ./paper-state.json --interval 1m --poll-seconds 60
bitcoin-ai paper-report --state ./paper-state.json --initial-cash 10000
pytest
```

The optional `--experiment-ledger` file is created at the path you specify. Keep it backed up and do not edit it manually: corruption or hash-chain changes cause the research command to stop rather than silently reset history. Use one research process at a time per ledger file; concurrent writers are not supported. Every run is recorded, including runs that reuse an exposed holdout. A clean overlap audit is not proof of independence or profitability.

## Trading development sequence

1. Historical data collection with provenance and validation.
2. Walk-forward evaluation with untouched holdout data and realistic costs.
3. Run the continuous local paper service with public completed candles and restart-safe state; add monitoring, alerts, and operational hardening.
4. Forward paper observation across market regimes.
5. Only after explicit review: isolated exchange adapter, disabled by default, with strict permissions and a kill switch.

A bot only runs while its host and network are available. Free hosting is not guaranteed to stay awake. No strategy can guarantee profits or eliminate losses.

## Safety

Never enter seed phrases, private keys, wallet backups, or exchange credentials. Live trading is not enabled. See [docs/PAPER_SERVICE.md](docs/PAPER_SERVICE.md), [docs/PAPER_PERFORMANCE.md](docs/PAPER_PERFORMANCE.md), [docs/SAFETY.md](docs/SAFETY.md), [docs/PAPER_TRADING.md](docs/PAPER_TRADING.md), [docs/AUTOPILOT.md](docs/AUTOPILOT.md), [docs/PAPER_CYCLE.md](docs/PAPER_CYCLE.md), and [docs/TRADING_RISK.md](docs/TRADING_RISK.md).


## Candidate trial registry (research-only)

The candidate registry records a strategy definition before its holdout evaluation and permits one later completion event. Each registration fingerprints the complete supplied strategy definition, dataset, test interval, and code revision. Events are stored in an atomic, hash-chained JSON ledger; duplicate trial IDs, edits/tampering, orphan completions, and second completions are rejected.

Example API:

```python
from bitcoin_ai.candidate_registry import (
    register_candidate_trial,
    complete_candidate_trial,
    audit_candidate_family,
)

ledger = "./candidate-trials.json"
register_candidate_trial(
    ledger,
    trial_id="run-2026-001",
    candidate_name="momentum-20",
    strategy_definition={"lookback": 20, "fees_bps": 10, "timeframe": "1d"},
    dataset_fingerprint="<64-character SHA-256 of the exact dataset>",
    code_revision="<git commit SHA>",
    test_start="2025-01-01T00:00:00+00:00",
    test_end="2025-03-01T00:00:00+00:00",
    registered_at="2024-12-31T12:00:00+00:00",
)
# Run the predeclared experiment only after registration.
complete_candidate_trial(
    ledger,
    trial_id="run-2026-001",
    outcome={"net_return_pct": 2.1, "bootstrap_null_p_value": 0.04},
    completed_at="2025-03-02T00:00:00+00:00",
)
```

Use `audit_candidate_family` to count all registered trials on the same dataset with overlapping test windows, including incomplete trials. The integrated research-lab workflow now pre-registers its fixed candidate family and requires the completed registry audit to match the candidate names, count, and recorded p-value evidence before paper-review eligibility can be considered. It cannot detect trials run outside the registry or prove a registration timestamp against an external trusted clock. Back up the ledger and use one writer at a time; concurrent writers are not supported.


### Integrated candidate-registry workflow

The research lab can now pre-register the full fixed candidate set before evaluating any OOS window, then attach each candidate's result after the holdout window has completed. The integrated promotion review fails closed unless the registry is complete and its candidate names/count exactly match the candidate family supplied to the run.

Example:

```bash
bitcoin-ai research-lab \
  --csv btc-daily.csv \
  --experiment-ledger holdout-history.json \
  --candidate-ledger candidate-trials.json \
  --code-revision "$(git rev-parse HEAD)" \
  --json
```

Both ledgers should be backed up and used by one process at a time. A repeated overlapping run on the same dataset is deliberately counted as additional trials and will block fresh-holdout eligibility. The registry's local timestamp is not a trusted external clock; this cannot prove experiments outside the tool were not run. Omitting `--candidate-ledger` leaves the research report diagnostic-only and blocks candidate-registry verification for paper-review eligibility. The code revision must identify the exact source used for the run.


### Cross-source market-data integrity

The paper service requires both Binance and Kraken. The cross-check now compares the full overlapping tail of completed candles, not only the final price. Both histories must be fresh, contiguous, and aligned; at least 20 overlapping candles are required by default. A divergence beyond the configured tolerance in even one overlapping close blocks the paper cycle before account state is changed. The report exposes aligned-candle count and maximum/mean deviation. Agreement between two exchanges is a consistency check, not proof against coordinated manipulation, shared upstream errors, or incorrect market-wide prices.


### Three-source paper market-data verification

The paper service now requires aligned completed BTC-USDT candle histories from Binance, Kraken, and Coinbase. Each source must be fresh and contiguous, and every overlapping candle is compared pairwise against the configured deviation tolerance. An unavailable, stale, unsupported, or divergent Coinbase feed stops the paper cycle; the service does not silently downgrade to two sources. Coinbase's public BTC-USDT product availability and API limits may vary, so this check can make paper cycles unavailable when that venue cannot provide the requested interval. Three-venue agreement is still not proof against shared upstream errors, coordinated manipulation, or market-wide price distortion. Simulation only; no live exchange orders.


### OHLCV anomaly diagnostics

The research-only `bitcoin_ai.market_anomaly.audit_ohlcv_anomalies` helper validates timestamp order and OHLCV relationships, then flags abnormal volume using a prior-only rolling median/MAD baseline, unusually wide candle ranges, and extreme close-to-close returns. The evaluated candle is excluded from its own baseline. These are heuristic diagnostics, not a spoofing or manipulation detector, and they are not currently wired into paper execution. Venue-reported volume can be incomplete or unreliable; alerts require human review and calibration before any strategy use.



### Market-regime intelligence (research-only)

The `bitcoin_ai.market_regime_intelligence.classify_market_conditions` helper combines the causal trailing-close regime classifier with the OHLCV anomaly report and the two-/three-source candle audit. It emits descriptive trend/volatility labels and a research-only posture. Any OHLCV alert changes the posture to `abstain`; an unsuccessful, divergent, or too-short exchange audit is rejected. It requires completed-candle inputs and never creates orders or forecasts. Thresholds remain heuristics, and a clean cross-check cannot prove market-wide data integrity.



### Regime robustness audit

The research lab now emits `regime_robustness_audit` for every fixed candidate. It screens regime-conditioned OOS slices for underpowered samples and negative returns after doubled estimated costs, while retaining same-interval buy-and-hold comparisons. Underpowered regimes are explicitly unknown, not passes. The default 10-observation screen is a diagnostic heuristic, not a statistical sufficiency guarantee. The audit is report-only and has no promotion or execution effect; correlated observations, repeated testing, and unseen regimes remain limitations.



### Strategy failure analysis

Each fixed candidate's out-of-sample return stream now receives a chronological failure report: drawdown episodes and recovery status, worst individual loss bars, worst-5%-bar average, loss concentration, and regime-conditioned loss contribution. The report includes timestamps and doubled-cost return context. It is diagnostic only: it describes where losses cluster, does not prove why they happened, and cannot promote a strategy or authorize execution. Underpowered regime slices are marked unknown.



### Strategy improvement hypotheses

The research lab emits `strategy_improvement_proposals` from each fixed candidate's failure diagnostics. Current rules only suggest bounded risk-reducing comparisons (cash baseline and, for council candidates, lower exposure caps) when drawdown or loss concentration crosses explicit thresholds. Proposals are untested hypotheses, not optimized parameters or recommendations to trade. Each requires a new pre-registered trial and a genuinely unused dataset fingerprint and holdout interval. The helper does not run backtests, mutate the candidate registry, select winners, or authorize execution.


### Fresh-evidence proposal evaluation

The research-only `bitcoin_ai.fresh_evidence.evaluate_fresh_candidate` gate compares a proposed candidate with its unchanged source strategy and a cash baseline using exactly aligned return streams on one preregistered dataset fingerprint and test interval. It verifies three distinct trial registrations, exact candidate identities, code revision, interval and dataset provenance, and the existing tamper-evident candidate and holdout ledgers. Any prior overlapping interval, missing registration, provenance mismatch, malformed/non-finite series, or underpowered sample is rejected before scoring. The report includes paired circular block-bootstrap lower bounds, bootstrap positive-share checks, compounded returns, doubled-cost sensitivity, and regime slices. Passing only yields `eligible_for_human_review`; it does not register or complete trials, append to the ledger, promote a strategy, or authorize paper/live execution. Ledger completeness and bootstrap assumptions remain material limitations.


### Autonomous research task scheduler

`bitcoin_ai.research_scheduler.scan_and_queue_research` consumes a clean market-regime intelligence report and an untested strategy-improvement proposal report. It abstains when the market context is uncertain, anomaly flags are present, or three-source verification is missing. Otherwise it queues deterministic candidate/regime tasks in a durable hash-chained JSON queue; identical scans are idempotent. The read-only `load_research_queue` validates the chain before exposing tasks. Queue entries contain the prerequisites for later preregistration and fresh-evidence evaluation. The scheduler does not fetch market data, run experiments, register trials, reserve holdouts, promote candidates, or authorize paper/live orders. Queue storage is single-writer; hash chaining detects edits but is not a concurrency lock or external timestamp authority.

### Historical research data ingestion and experiment preparation

`bitcoin_ai.research_ingestion.prepare_research_dataset` accepts normalized, completed OHLCV payloads from explicit callers and prepares a deterministic research bundle only after strict validation. It checks source identity, symbol/interval provenance, timezone-aware retrieval times, staleness/future timestamps, finite OHLCV values and candle relationships, strictly increasing timestamps, exact cadence, exact cross-source timestamp alignment, and close-price agreement across at least three unique sources. The bundle records source provenance, coverage, row count, quality status, and a SHA-256 dataset fingerprint. It never sorts, drops, fills, interpolates, resamples, or repairs candles. The fingerprint is deterministic for the same data/provenance and is not proof of a fresh or unused holdout: candidate preregistration and the existing holdout-ledger/fresh-evidence checks remain mandatory. This stage consumes supplied payloads and does not fetch data or run experiments.

### Live historical OHLCV ingestion (research-only)

`bitcoin_ai.research_market_ingestion.PublicResearchMarketIngestor` retrieves completed BTC-USDT OHLCV candles directly from the public Binance, Kraken, and Coinbase market-data endpoints. It uses no API keys, account endpoints, wallet information, or order APIs. All three providers are mandatory: an outage or unsupported interval aborts the dataset rather than silently reducing the source count. Only intervals supported by all three providers are accepted (`1m`, `5m`, `15m`, `1h`, and `1d`); the requested history is bounded to 20–300 candles.

Example:

```python
from datetime import datetime, timezone
from bitcoin_ai.research_market_ingestion import PublicResearchMarketIngestor

report = PublicResearchMarketIngestor().fetch_and_prepare(
    interval="5m",
    limit=100,
    now=datetime.now(timezone.utc),
)
print(report["dataset_fingerprint"])
print(report["provenance"])
```

The fetched OHLCV payloads pass through the same strict ingestion gate as caller-supplied data: exact timestamp cadence and alignment, retrieval freshness, a latest-completed-candle age limit of two intervals, finite and structurally valid OHLCV, and cross-source close-price tolerance. The Coinbase adapter verifies the provider's documented newest-first order before reversing it into chronological order; it does not sort arbitrary malformed data. No candles are interpolated, filled, resampled, or repaired. Provider outages, rate limits, product availability, and shared upstream faults remain possible. A successful fetch is a data-quality result only: `holdout_status` remains `not_assessed`, and this operation does not register candidates, evaluate strategies, or authorize paper/live orders.



### Scheduled dataset-to-experiment planning (research-only)

`bitcoin_ai.research_experiment_plan.prepare_scheduled_experiment` connects one hash-chained scheduler task to a successful three-source `PublicResearchMarketIngestor` dataset report. It checks the queued-task authority, BTC-USDT identity, three unique cross-checked sources, aligned canonical bar count, fingerprint/provenance agreement, chronological finite closes, candidate family/lookback, training/test sizing, and execution costs. It returns typed `Bar` observations plus a deterministic experiment-plan ID and a shared test-window specification for proposal/source/cash comparison.

This is deliberately a preparation boundary, not an autonomous experiment runner. It does not register candidates, reserve holdouts, execute the walk-forward lab, or mark a dataset fresh. The unchanged source strategy must be supplied explicitly by the caller. Before any evaluation, a separate controlled step must preregister all three immutable trials and pass the existing holdout-reuse/fresh-evidence gates. No paper or live trading authority is granted.


### Controlled preregistered walk-forward runner (research-only)

`bitcoin_ai.controlled_experiment.run_preregistered_experiment` executes a prepared plan only after it verifies the plan fingerprint, exact rolling-fold window, three distinct candidate definitions, and explicit cash comparator. It registers immutable proposal/source/cash trial identities, reserves the full test interval in the append-only holdout ledger before running the existing walk-forward research lab, and records each role's fixed-candidate outcome after completion. Repeated plans and overlapping holdout intervals are rejected. Failed runs leave their reservation and incomplete registrations visible; use a genuinely new, unused dataset/window rather than retrying exposed evidence.

This remains historical research only. It does not promote strategies, mutate paper accounts, or place orders. Registry and holdout ledger files require single-writer operation, and cannot prove that no unrecorded external inspection occurred.


### Completed experiment evidence review

The controlled walk-forward runner stores each fixed candidate's exact aligned
out-of-sample per-bar return stream, doubled-cost stream, regime labels, and
timestamps in its immutable completion event. After a completed run, call
`evaluate_completed_experiment` from `bitcoin_ai.fresh_evidence` with the
registry, holdout ledger, plan ID, registered trial IDs, candidate names, and
the plan's exact dataset fingerprint, test window, and code revision.

The evaluator recognizes and excludes only that run's single exact pre-evaluation
holdout reservation. Any other overlapping record remains a hard rejection.
All three completed roles must contain identical OOS timestamps and regime
labels, and the evaluator uses the recorded paired streams rather than scalar
summary metrics. A passing result is still only `eligible_for_human_review`;
it does not authorize promotion, paper execution, or live orders.


The completed-evidence gate is also available as a read-only CLI command after a
controlled experiment finishes. It derives the three deterministic trial IDs
from the plan ID and verifies the exact completed outcomes in both ledgers:

```bash
bitcoin-ai research-review \
  --candidate-ledger candidate-trials.json \
  --experiment-ledger holdout-history.json \
  --plan-id "$PLAN_ID" \
  --dataset-fingerprint "$DATASET_FINGERPRINT" \
  --test-start "2026-01-01T00:00:00+00:00" \
  --test-end "2026-07-01T00:00:00+00:00" \
  --code-revision "$CODE_REVISION" \
  --proposal-candidate "momentum:5" \
  --source-candidate "sma:12" \
  --json
```

The candidate names, fingerprint, interval, and revision must exactly match the
preregistered plan. A result of `eligible_for_human_review` is not a trade
signal or execution authorization; the command cannot promote a strategy or
change paper/live account state.
