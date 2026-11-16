# Roadmap

## Phase 1 — Foundation
- [x] Python package and CLI
- [x] Curated starter corpus with source metadata
- [x] Retrieval with citations
- [x] Abstention when evidence is missing
- [x] Unit tests

## Phase 1B — Data quality
- [ ] Verify redistribution rights and record per-document license
- [ ] Add canonical source snapshots and retrieval dates
- [x] Add an initial seven-question retrieval/abstention benchmark (human review still needed)
- [ ] Add document deduplication and provenance checks

## Phase 2 — Live Bitcoin data
- [ ] Price adapter (timestamp, currency, provider, cache)
- [ ] Block-height and mempool adapters
- [ ] Optional Bitcoin Core RPC integration
- [ ] Never label stale or unavailable data as live

## Phase 3 — Agent
- [ ] Tool registry with explicit allowlists
- [ ] Read-only tools first
- [ ] Tool output validation and audit log
- [ ] No wallet signing, custody, or trading execution

## Phase 4–6 — Model development
- [ ] Select an open-weight base model by license, hardware needs, and benchmark score
- [ ] Build high-quality licensed Bitcoin instruction data
- [ ] Fine-tune with LoRA/QLoRA where compute permits
- [ ] Compare against the unchanged base model
- [ ] Publish model card, dataset card, and reproducible evaluation
