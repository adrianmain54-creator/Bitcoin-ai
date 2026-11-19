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

### Deterministic catalog audit report

After creating a review catalog, use `bitcoin_ai.research_catalog_audit_report` to reverify the exact original bundle set and emit a deterministic JSON audit report. The report binds the catalog ID and every manifest/comparison/plan/receipt ID plus comparison and HTML SHA-256 hashes. Its report ID detects accidental or unauthorized content changes when compared with a separately retained trusted copy; it is not a digital signature, trusted timestamp, or proof of who created it.

Example:

```bash
python -m bitcoin_ai.research_catalog_audit_report \
  --catalog research-catalog.json \
  --bundle comparison.json review.html manifest.json \
  --output catalog-audit-report.json
```

The command fails closed if any bundle is missing, extra, altered, or mismatched. It is read-only with respect to the catalog and source bundles; only the explicitly requested report file is written. Execution authority remains none.

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


### Controlled experiment to fresh-evidence review bridge (research-only)

After a controlled experiment completes, `bitcoin_ai.controlled_evidence.evaluate_controlled_experiment` connects its fixed-candidate per-bar return streams to the strict paired fresh-evidence evaluator. The walk-forward report retains aligned base-cost and doubled-cost streams for proposal, unchanged source, and cash, together with the exact OOS regime labels. The runner stores those streams in each append-only candidate completion event so the bridge can verify the supplied report against the hash-chained registry rather than trusting a mutable in-memory summary.

The bridge recomputes the candidate-family audit from the registry, checks the canonical plan fingerprint and deterministic role trial IDs, verifies each completed role and its stored streams, and recognizes only the exact holdout reservation created by that controlled run. The entire holdout ledger is integrity-checked; every other overlapping prior record remains disqualifying. A clean result can reach only `eligible_for_human_review`, never automatic promotion or execution.

Example after obtaining `controlled_result` from `run_preregistered_experiment`:

```python
from bitcoin_ai.controlled_evidence import evaluate_controlled_experiment

review = evaluate_controlled_experiment(
    controlled_result,
    candidate_registry_path="state/candidate_registry.json",
    holdout_ledger_path="state/holdout_ledger.json",
)
print(review["status"])
print(review["gates"])
```

The evidence gate requires a minimum paired sample, distinct preregistered roles, exact dataset/code/window identity, a fresh non-overlapping holdout reservation, positive paired bootstrap lower bounds versus both source and cash, at least 95% positive bootstrap samples, positive compounded proposal return under doubled costs, and sufficiently sampled nonnegative doubled-cost regime slices. Bootstrap and regime checks are approximate/descriptive, not forecasts. Registry and ledger files remain single-writer, and a clean ledger cannot prove the absence of external inspection. Passing means human review only; paper-state mutation, strategy promotion, and live orders are not authorized.


### Explicit end-to-end scheduled research cycle

`bitcoin_ai.research_cycle.run_scheduled_research_cycle` is the single-call orchestration boundary for a caller-supplied queued task and an already validated three-source dataset report. It prepares the deterministic plan, preregisters and reserves the holdout through the controlled runner, then sends a completed experiment to the strict fresh-evidence bridge. A reused/rejected holdout stops before evidence review. The result includes the experiment and evidence-review reports for inspection.

This is an explicit function call, not a background worker: it does not poll the scheduler queue, fetch market data, or run continuously. It requires caller-supplied registry/ledger paths and registration timestamp. All stages remain historical research only. Even `eligible_for_human_review` grants no strategy promotion, paper execution, or live order authority.


### Public-market-data to research-review entry point

`bitcoin_ai.public_market_cycle.run_public_market_research_cycle` is the explicit, caller-invoked entry point for using current public BTC-USDT candles in the research workflow. It fetches completed candles from Binance, Kraken, and Coinbase, requires all three providers to pass the strict shared ingestion gate, then forwards the resulting fingerprinted dataset into the scheduled plan, controlled walk-forward, and fresh-evidence review stages.

Example:

```python
from bitcoin_ai.public_market_cycle import run_public_market_research_cycle

result = run_public_market_research_cycle(
    queued_task,
    code_revision="the-exact-git-commit-being-reviewed",
    source_strategy_definition={"family": "sma", "lookback": 48},
    candidate_registry_path="state/candidate_registry.json",
    holdout_ledger_path="state/holdout_ledger.json",
    registered_at="2026-11-19T00:00:00+00:00",
    interval="5m",
    limit=300,
    train_bars=99,
    test_bars=20,
)
print(result["status"])
print(result["market_data"])
```

The 300-bar / 99-train / 20-test example creates 200 out-of-sample observations across ten fixed rolling folds, subject to the runner's exact-window checks. Use the actual code revision and a genuinely unused dataset/window. A repeated fingerprint/window is expected to be rejected by the holdout ledger. Network access is triggered only by this explicit function call; it uses public market-data endpoints, never account credentials or order APIs. Provider outage, staleness, incomplete candles, or cross-venue divergence aborts before preregistration. Even `eligible_for_human_review` is not an instruction to trade.


### Manual public market-data smoke check

After this workflow file is present on the repository's default branch, a manual GitHub Actions run named **Public BTC market-data smoke check** can be started from the Actions tab. It executes `python -m bitcoin_ai.market_data_smoke` against the public Binance, Kraken, and Coinbase BTC-USDT candle endpoints. It validates the three-source dataset and uploads a compact JSON provenance report. This is intentionally an ingestion-only check: it does not create scheduler tasks, run strategy evaluation, reserve or consume a holdout, write candidate/ledger state, or access trading endpoints. A successful run proves only that the requested market-data snapshot passed the configured checks at that time; it says nothing about strategy profitability. Provider failures stop the workflow rather than falling back to fewer venues.


### Plan-only queued research CLI

The explicit `bitcoin_ai.research_plan_cli` command connects one task from the validated hash-chained scheduler queue to a newly fetched, three-venue BTC-USDT dataset and writes a portable deterministic plan JSON. It requires the unchanged source strategy family/lookback and exact code revision as explicit inputs. Unknown task IDs, invalid queue integrity, provider failures, or dataset/plan validation failures stop before an output is written.

Example:

```bash
python -m bitcoin_ai.research_plan_cli \
  --queue state/research-queue.json \
  --task-id <queued-task-id> \
  --code-revision "$(git rev-parse HEAD)" \
  --source-family sma \
  --source-lookback 48 \
  --interval 5m --limit 101 \
  --train-bars 50 --test-bars 10 \
  --output state/research-plan.json
```

The output binds the task, dataset fingerprint, three sources, candidate roles, costs, code revision, and exact terminal walk-forward test-window specification. The row count must end exactly on a test-fold boundary; extra trailing observations are rejected before a plan is written. Proposal, unchanged source, and cash definitions must also be distinct. It intentionally omits raw typed bars from the portable artifact. This command only prepares a plan: it does not preregister candidates, reserve/consume a holdout, run a backtest, mutate paper state, or place orders. A successful plan is not evidence of strategy performance or holdout freshness. Use the controlled preregistration/evaluation path only as a separate, explicitly reviewed step.


### Portable research-plan provenance audit (research-only)

A plan-only JSON can now be independently checked with `python -m bitcoin_ai.research_plan_artifact --input state/research-plan.json --output state/research-plan-audit.json`. The audit recomputes the canonical plan SHA-256 and validates the task identity, BTC-USDT dataset fingerprint, three unique source venues, row count and exact walk-forward boundary, timezone-aware test window, code revision, distinct proposal/source/cash definitions, and fee/slippage assumptions. It emits a compact provenance report without raw candles.

This is an integrity check, not a cryptographic signature or trusted timestamp: it detects edits that do not also replace the digest, but cannot prove that the dataset was fresh or unused, that source venues were authentic, or that the stated code revision actually ran. It performs no network fetch, experiment, holdout reservation, ledger mutation, paper-state change, or order execution.


### Reproducibility receipts for completed experiments

Successful controlled research runs now include a `reproducibility_receipt` in the returned JSON. It binds the plan and dataset fingerprints, code revision, exact test window, interval, train/test/step sizes, fee and slippage assumptions, bootstrap trial count, random seed, canonical research-report SHA-256, final candidate-registry hash-chain head, and completion timestamp. The receipt itself has a canonical SHA-256 identifier.

Retain the receipt alongside the research report and plan. Hashes help detect later edits when a trusted copy is retained independently; they are not signatures, trusted timestamps, or proof that a particular code revision executed. Dependency and hardware versions are not fully captured, so bit-for-bit reruns are not guaranteed. No execution authority is added.

### Completed research-results comparison (research-only)

After a controlled experiment and the existing read-only fresh-evidence evaluation have both completed, `bitcoin_ai.research_comparison.compare_completed_research` creates a compact comparison of the proposal against the unchanged source and cash baseline. It verifies the canonical plan ID, report digest, receipt digest, dataset/code/window provenance, aligned candidate streams, and evidence observation count before summarizing compounded net returns, doubled-cost returns, and maximum drawdown. Existing paired bootstrap evidence and gates are carried through unchanged. Corrected p-values are explicitly marked unavailable when the supplied evaluator does not provide them.

CLI:

```bash
python -m bitcoin_ai.research_comparison --controlled state/controlled-result.json --evidence state/fresh-evidence.json --output state/research-comparison.json
```

The output is comparison-only, research-only, and has no execution authority. It does not rerun a holdout, mutate a ledger, calculate new significance tests, or authorize a trade. A favorable result means only that the existing evidence supports further human review; it is not a profitability claim or trading recommendation.


### Static research-review dashboard

A completed, integrity-checked comparison can be rendered as a portable HTML review page:

```bash
python -m bitcoin_ai.research_review --input state/research-comparison.json --output state/research-review.html
```

The renderer verifies the comparison fingerprint and required provenance/metric fields before producing a self-contained static page. Untrusted text is HTML-escaped; no scripts, external assets, network requests, or interactive trading controls are included. Missing or malformed metrics fail closed. The page displays candidate definitions, after-cost comparisons, existing statistical evidence, limitations, and links by ID to the plan and reproducibility receipt. It is a read-only research aid, not a trading dashboard or execution interface.


### End-to-end research review bundle (research-only)

Once a controlled research result and its matching read-only fresh-evidence result have already been produced, the post-run bundle command validates both, writes the comparison JSON, renders the static HTML review, and publishes a SHA-256 manifest last as the bundle-complete marker:

```bash
python -m bitcoin_ai.research_review_pipeline \
  --controlled state/controlled-result.json \
  --evidence state/fresh-evidence.json \
  --comparison-output state/research-comparison.json \
  --html-output state/research-review.html \
  --manifest-output state/research-review-manifest.json
```

The manifest binds the comparison ID, plan ID, reproducibility receipt ID, source report digest, and exact output hashes. Each output is staged in its destination directory and individually published with an atomic replace; the manifest is published last so its presence indicates that the bundle publication completed. Filesystem replacement across multiple files is not a single transaction, so an interrupted publication can leave comparison/HTML outputs without a manifest. Re-run only from the same already-completed inputs to republish; this step never reruns a holdout or evaluator.

This is a local, deterministic post-run artifact step. It makes no network requests and does not alter source artifacts, candidate registries, holdout ledgers, paper state, or trading accounts. All output remains research-only with no execution authority.


### Verify a saved research review bundle

After producing the comparison JSON, static HTML, and manifest, independently verify that all three still belong together:

```bash
python -m bitcoin_ai.research_review_bundle_audit \
  --comparison state/research-comparison.json \
  --html state/research-review.html \
  --manifest state/research-review-manifest.json
```

The verifier is read-only. It checks the manifest's canonical fingerprint, comparison identity and provenance, both output SHA-256 hashes, and that the HTML exactly matches a fresh rendering of the verified comparison artifact. It reports verified IDs and hashes; it does not establish a trusted signature, timestamp, source authenticity, or profitability. Keep the manifest with the two outputs: it is the retained digest reference used to detect later changes.


### Catalog verified research-review bundles

Create a deterministic, portable index from one or more saved review bundles:

```bash
python -m bitcoin_ai.research_review_catalog \
  --bundle state/research-comparison.json state/research-review.html state/research-review-manifest.json \
  --bundle archive/older-comparison.json archive/older-review.html archive/older-manifest.json \
  --output state/research-review-catalog.json
```

Each input bundle is fully checked by the read-only bundle verifier before it can be indexed. The catalog sorts entries by manifest ID, rejects duplicates and tampered bundles, and binds comparison, plan, receipt, and artifact hashes in a deterministic SHA-256 hash chain. Reordering the same input set produces the same catalog. Verify a saved catalog with `verify_review_catalog` from `bitcoin_ai.research_review_catalog`.

This is an export-only index: it does not edit, move, or delete source bundles, does not create a mutable history database, and does not fetch data, rerun research, touch holdout/registry state, change paper state, or execute trades. Hashes provide integrity checks only when compared with a separately retained trusted copy; they are not signatures, trusted timestamps, or proof of profitability. No execution authority is granted.


### Reverify a saved catalog against bundle files

A catalog can be checked again later against the exact comparison, HTML, and manifest files it indexes:

```bash
python -m bitcoin_ai.research_review_catalog \
  --verify-catalog state/research-review-catalog.json \
  --bundle state/research-comparison.json state/research-review.html state/research-review-manifest.json \
  --bundle archive/older-comparison.json archive/older-review.html archive/older-manifest.json
```

This recomputes each bundle's own verification, requires the supplied manifest IDs to match the catalog exactly (no missing or extra bundles), and compares the recorded comparison/plan/receipt IDs and artifact hashes. It detects changed or substituted files relative to the saved catalog. It cannot prove who created the catalog or that it was never replaced; retain a trusted catalog copy separately. Verification is read-only and grants no execution authority.
