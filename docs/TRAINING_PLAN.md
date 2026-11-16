# Bitcoin AI: Knowledge and Risk Training Plan

## Objective

Build a Bitcoin-specialist research assistant that is accurate, evidence-grounded, calibrated about uncertainty, and conservative around financial risk. The objective is better decisions and fewer avoidable mistakes—not a promise of profit.

## Training stages

### 1. Build a licensed knowledge corpus

Organize source material into versioned domains:

- Protocol and consensus: transactions, UTXOs, blocks, validation, proof of work, difficulty adjustment, halvings, fees, mempool, forks, and consensus changes.
- Cryptography and security: signatures, hashes, key management, multisig, hardware wallets, backups, threat models, and common scams.
- Scaling and applications: Lightning, payment channels, sidechains, and relevant standards.
- Development: Bitcoin Core, RPC, BIPs, testing, and reproducible builds.
- Economics and history: monetary issuance, fee markets, adoption, historical cycles, and clearly labelled competing interpretations.
- Markets and risk: volatility, liquidity, leverage, drawdowns, custody/exchange risk, market structure, and behavioural errors.

For every source, record its canonical URL, publisher, source class, publication/update date, retrieval date, license and redistribution status, and a short summary. Do not ingest or train on material unless its license permits the intended use. Prefer primary sources and public-domain or permissively licensed material.

### 2. Build an evaluation set before fine-tuning

Create human-reviewed questions with expected evidence and citations. Test:
- factual correctness and protocol precision
- retrieval recall and citation correctness
- ability to distinguish current facts from historical facts
- calibrated uncertainty and appropriate abstention
- resistance to prompt injection in retrieved documents
- financial-risk reasoning, including identifying missing data and invalid assumptions

Keep a held-out test set that is never used to create training examples. Report scores by domain, not just one overall score.

### 3. Add current-data tools

Use free public endpoints only where their terms permit it. Every market/on-chain observation must carry provider, timestamp, units, and freshness status. Cache responses and handle outages. Never silently substitute stale data for live data.

### 4. Create specialist training examples

Only after the corpus and evaluation set are reliable:
- create original question/answer and tool-use examples grounded in permitted sources
- include counterexamples where the correct answer is "not enough evidence"
- include uncertainty, source conflict, and changing-protocol examples
- split train/validation/test by source and time to reduce leakage
- document provenance and licenses for every example

### 5. Model selection and $0 constraints

Start with retrieval-augmented generation and small local models that can run on available hardware. Compare open-weight models by license, hardware requirements, factual accuracy, citation quality, and risk calibration. Fine-tuning is optional and comes later; do not claim a model has been trained until an actual training run, configuration, dataset version, and evaluation are recorded. No paid API, hosted GPU, or cloud bill is allowed.

## Financial-risk boundary

The system is a research and decision-support tool, not a profit machine. It must never guarantee returns, fabricate probabilities, or treat a model's confidence as a calibrated market probability. Initially, all strategies are research-only and paper-trading-only. No private keys, wallet signing, custody, exchange credentials, leverage, or automated real-money orders.

A strategy report must state its timestamp, data sources, assumptions, fees/slippage assumptions, invalidation conditions, downside scenarios, and reasons to take no action. Backtests must account for fees, slippage, survivorship/look-ahead bias, and out-of-sample periods. Past performance is not evidence of future returns.
