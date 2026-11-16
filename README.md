# Bitcoin AI

A Bitcoin-native intelligence project built from a transparent, testable foundation.

**Current stage:** Phase 1 — foundation. This release is deliberately local-first and does not require paid APIs, API keys, hosted inference, or a GPU.

## What exists now

- A small Bitcoin knowledge base with source metadata.
- Deterministic, IDF-weighted retrieval that gives title matches extra weight and reduces the influence of generic terms.
- A retrieval-based question answering engine that returns cited excerpts.
- Conservative abstention when evidence is missing.
- Corpus integrity checks for duplicate IDs, empty required fields, and non-HTTP(S) source URLs.
- A CLI for asking questions.
- A seven-question benchmark covering expected top-ranked evidence and out-of-domain abstention.
- Unit tests for ranking, deterministic results, citations, abstention, and corpus validation.
- An optional model-adapter boundary for future open-weight models.

This is **not yet a trained Bitcoin model**. The first milestone builds reliable data, evaluation, and interfaces before fine-tuning any model. The starter corpus is intentionally small; passing its benchmark does not establish broad Bitcoin expertise.

## Quick start

Requires Python 3.10+.

```bash
python -m venv .venv
# macOS/Linux:
source .venv/bin/activate
# Windows PowerShell:
# .venv\\Scripts\\Activate.ps1

python -m pip install -e ".[dev]"
bitcoin-ai ask "What is proof of work?"
pytest
```

No network connection is needed for the knowledge-base demo.

## Project structure

```text
bitcoin-ai/
├── data/knowledge/       # Small, curated starter corpus
├── docs/                 # Architecture and roadmap
├── src/bitcoin_ai/
│   ├── cli.py            # Command-line interface
│   ├── knowledge.py      # Retrieval and citation logic
│   ├── models.py         # Future model integration boundary
│   └── schemas.py        # Typed data structures
└── tests/
```

## Design principles

1. **Cite evidence.** Knowledge answers include source IDs and titles.
2. **Abstain when uncertain.** Missing evidence is not a reason to invent.
3. **Separate facts from analysis.** Market commentary must distinguish observed data from interpretation.
4. **No custody or trading by default.** This project does not hold keys, sign transactions, or execute trades.
5. **Reproducible improvement.** Every model or retrieval change should be measured against a versioned benchmark.
6. **Respect licenses.** Only use data and model weights whose terms permit the intended use.

## Roadmap

- [x] Phase 1A: repository scaffold, local retrieval, CLI, tests
- [ ] Phase 1B: expand curated corpus with source URLs, dates, and license metadata
- [x] Phase 1C: initial retrieval benchmark and top-ranked evidence checks (human review and expansion still needed)
- [ ] Phase 2: live public Bitcoin data adapters with caching and provenance
- [ ] Phase 3: agent tools with strict permissions and verification
- [ ] Phase 4: compare suitable open-weight base models
- [ ] Phase 5: create a licensed Bitcoin instruction dataset and fine-tune using LoRA/QLoRA
- [ ] Phase 6: publish model cards, evaluation results, and reproducible training recipes

## Safety

Bitcoin AI is an educational and research tool, not financial advice. Never enter seed phrases, private keys, wallet backups, or exchange credentials. Do not connect a wallet or enable transaction signing in an experimental agent.
