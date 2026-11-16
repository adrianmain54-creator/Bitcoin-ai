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
- A **paper-only portfolio execution simulator** that caps BTC allocation, models fees and adverse slippage, and records simulated fills.
- GitHub Actions CI and unit tests.

This is **not yet a trained Bitcoin model, a validated profitable strategy, or a live trading bot**. The market data adapter is read-only; the paper broker never submits exchange orders. Backtests and simulations do not guarantee future results.

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
bitcoin-ai ask "How does a Bitcoin transaction use UTXOs?"
bitcoin-ai network --currency USD
pytest
```

## Trading development sequence

1. Historical data collection with provenance and validation.
2. Walk-forward evaluation with untouched holdout data and realistic costs.
3. Paper-trading loop with persistent state, risk gates, and monitoring.
4. Forward paper observation across market regimes.
5. Only after explicit review: isolated exchange adapter, disabled by default, with strict permissions and a kill switch.

A bot only runs while its host and network are available. Free hosting is not guaranteed to stay awake. No strategy can guarantee profits or eliminate losses.

## Safety

Never enter seed phrases, private keys, wallet backups, or exchange credentials. Live trading is not enabled. See [docs/SAFETY.md](docs/SAFETY.md), [docs/PAPER_TRADING.md](docs/PAPER_TRADING.md), and [docs/TRADING_RISK.md](docs/TRADING_RISK.md).
