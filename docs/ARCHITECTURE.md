# Architecture (Phase 1)

## Request flow

1. CLI accepts a question.
2. `KnowledgeBase` tokenizes the query and ranks curated records using a transparent lexical baseline.
3. `BitcoinAnswerEngine` returns retrieved source excerpts with metadata.
4. If no result clears the minimum evidence threshold, the engine abstains.

## Why start without a generative model?

A model can sound convincing while being wrong. First we need provenance, a small clean corpus, benchmark questions, and measurable retrieval quality. The `TextModel` protocol is the seam where a locally runnable open-weight model can be added later. The current baseline does not claim to be a trained model.

## Planned modules

- `sources/`: ingestion, license checks, snapshots, provenance
- `market/`: price and market data adapters with timestamps and provider attribution
- `chain/`: Bitcoin Core RPC and public chain data adapters
- `agent/`: permissioned tools, planning, retries, verification
- `training/`: dataset validation, deduplication, split management, LoRA recipes
- `evaluation/`: factuality, citation precision, abstention, robustness, regression tests
