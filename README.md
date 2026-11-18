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
