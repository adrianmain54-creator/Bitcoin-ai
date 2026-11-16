# Bitcoin AI

A Bitcoin-native intelligence project built from a transparent, testable foundation.

**Current stage:** local-first Bitcoin knowledge core plus read-only public network data. The project is designed to work without paid APIs, hosted inference, or a GPU.

## What exists now

- A 21-record curated Bitcoin knowledge corpus spanning fundamentals, transactions/UTXOs, mining, peer-to-peer networking, node modes, Bitcoin Core, wallet standards, SegWit, Taproot, PSBT, and Lightning.
- Per-record publisher, canonical URL, retrieval date, topics, and explicit license-review status.
- A source register explaining why public availability is not blanket permission to copy or train on a source.
- Deterministic IDF-weighted retrieval that gives title matches extra weight and reduces generic verb noise.
- A retrieval-based question answering engine that returns cited excerpts and abstains when evidence is insufficient.
- Corpus integrity checks for duplicate IDs, empty required fields, invalid source URL schemes, and missing provenance.
- A corpus audit command reporting topic coverage, source-domain distribution, license-review status counts, and exact duplicate summaries.
- A read-only public data adapter for BTC spot price, block height, mempool statistics, and recommended transaction fees, with provider, source URL, observation time, units, age, and cache status.
- Bounded network timeouts, short in-memory caching, response validation, and explicit errors when live data is unavailable.
- A CLI for knowledge questions and live network snapshots.
- A 21-question benchmark covering expected top-ranked evidence and out-of-domain abstention.
- Unit tests for ranking, determinism, citations, abstention, corpus provenance, and mocked live-data behavior.

This is **not yet a trained Bitcoin model**. The corpus is a compact specialist foundation, not a complete encyclopedia. The benchmark is still small and requires human review; passing it does not establish broad Bitcoin expertise. Live network data is descriptive, not a price forecast or trading signal.

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\\Scripts\\Activate.ps1

python -m pip install -e ".[dev]"
bitcoin-ai ask "How does a Bitcoin transaction use UTXOs?"
bitcoin-ai network --currency USD
pytest
```

The knowledge-base demo works offline. The `network` command requires internet access and uses the public Mempool.space REST API. Respect its rate limits.

## Project structure

```text
bitcoin-ai/
├── data/knowledge/       # Curated corpus and versioned benchmark
├── docs/                 # Architecture, roadmap, safety, source register
├── src/bitcoin_ai/
│   ├── cli.py            # Command-line interface
│   ├── data_sources.py   # Read-only live Bitcoin data and provenance
│   ├── knowledge.py      # Retrieval and citation logic
│   ├── models.py         # Future model integration boundary
│   └── schemas.py        # Typed data structures
└── tests/
```

## Design principles

1. **Cite evidence.** Knowledge answers include source IDs and canonical links.
2. **Abstain when uncertain.** Missing evidence is not a reason to invent.
3. **Separate facts from analysis.** Market commentary must distinguish observed data from interpretation.
4. **No custody or trading by default.** This project does not hold keys, sign transactions, or execute trades.
5. **Reproducible improvement.** Every model or retrieval change should be measured against a versioned benchmark.
6. **Respect licenses.** Source provenance and per-document reuse rights must be checked before copying or training.

## Roadmap

- [x] Phase 1A: repository scaffold, local retrieval, CLI, tests
- [x] Phase 1B: expand initial corpus and record source provenance/license status (rights verification remains in progress)
- [x] Phase 1C: 21-question retrieval benchmark with top-ranked evidence assertions (human review and further expansion needed)
- [x] Phase 2A: read-only BTC price, block height, mempool, and fee adapter with provenance and caching
- [ ] Phase 2B: historical market data, additional network metrics, and robust time-series storage
- [ ] Phase 3: agent tools with strict permissions and verification
- [ ] Phase 4: compare suitable open-weight base models
- [ ] Phase 5: create a licensed Bitcoin instruction dataset and fine-tune using LoRA/QLoRA
- [ ] Phase 6: publish model cards, evaluation results, and reproducible training recipes

## Safety

Bitcoin AI is an educational and research tool, not financial advice. Never enter seed phrases, private keys, wallet backups, or exchange credentials. Do not connect a wallet or enable transaction signing in an experimental agent.
