# Roadmap

## Phase 1 — Foundation
- [x] Python package and CLI
- [x] Curated Bitcoin corpus with source metadata
- [x] Deterministic IDF-weighted retrieval with title weighting
- [x] Retrieval with citations and conservative abstention
- [x] Corpus integrity and provenance checks
- [x] Unit tests for ranking, determinism, citations, and abstention

## Phase 1B — Knowledge quality
- [x] Expand starter corpus from 5 to 21 original, source-linked summaries
- [x] Cover transactions/UTXOs, peer networking, node modes, Bitcoin Core, wallet standards, SegWit, Taproot, PSBT, and Lightning
- [x] Record publisher, canonical URL, retrieval date, topics, and license-review status per entry
- [x] Document source-family licensing boundaries and BIP per-document license checks
- [x] Expand retrieval benchmark from 7 to 21 questions and assert expected evidence ranks first
- [ ] Human-review benchmark answers and add held-out questions written independently of corpus summaries
- [ ] Verify remaining source-document redistribution rights before copying source text or creating training examples
- [ ] Add content-level deduplication, source revision hashes, and scheduled freshness checks

## Phase 2 — Live Bitcoin data
- [x] Read-only BTC price, block-height, mempool, and recommended-fee adapter
- [x] Include provider, source URL, observation time, units, age, and cache status
- [x] Bounded timeouts, short in-memory caching, and response validation
- [ ] Add historical market data and robust time-series storage
- [ ] Add difficulty, hashrate, and Lightning network adapters
- [ ] Optional Bitcoin Core RPC integration
- [ ] Never label stale or unavailable data as live

## Phase 3 — Agent
- [ ] Tool registry with explicit allowlists
- [ ] Read-only tools first
- [ ] Tool output validation and audit log
- [ ] No wallet signing, custody, or trading execution

## Phase 4–6 — Model development
- [x] Document staged Bitcoin knowledge, dataset, and evaluation training plan
- [x] Define research-only trading risk controls and paper-trading boundary
- [ ] Select an open-weight base model by license, hardware needs, and benchmark score
- [ ] Build high-quality licensed Bitcoin instruction data
- [ ] Fine-tune with LoRA/QLoRA where compute permits
- [ ] Compare against the unchanged base model
- [ ] Publish model card, dataset card, and reproducible evaluation
