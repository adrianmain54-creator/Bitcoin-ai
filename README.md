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
