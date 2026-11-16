# Knowledge source and licensing register

**Corpus snapshot date:** 2026-11-16  
**Purpose:** document where the original Bitcoin AI summaries come from and what may be reused. Corpus entries are short original summaries with canonical source links; they are not copied source chapters.

## Source families

| Source family | Corpus coverage | What is verified | Reuse rule |
|---|---|---|---|
| Bitcoin Developer Documentation | Chain, mining, wallets, transactions, peer-to-peer networking, payment processing, operating modes | Primary technical documentation; source-document redistribution terms have not been independently verified in this project | Keep only our own summaries and links until the documentation license is verified |
| Bitcoin Core repository | Project overview and full-node validation role | Repository identifies the software as MIT licensed | MIT applies to the repository's covered software; preserve notices and check individual files/dependencies |
| Bitcoin Improvement Proposals | BIP process, BIP 32, 39, 141, 174, 341 and 342 | BIP 3 requires each proposal to state licensing terms in its Copyright section; historical proposals can have different terms | Inspect each proposal's Copyright section before copying or training on its text |
| Lightning BOLTs | Base messaging, channel peer protocol, routing gossip, invoices and offers | BOLTs repository states CC BY 4.0 | Attribution is required for reuse; keep source attribution and check current spec revisions |

## Important distinctions

- A public URL is not permission to copy or train on the entire work.
- A repository-level license is not necessarily the license for every third-party file or linked document.
- A BIP being published does not mean it is deployed, adopted, or consensus policy. Check each proposal's current status and implementation support.
- A technical specification can change. The corpus records a retrieval date; production answers about current behavior should re-check the canonical source.
- The corpus stores original summaries, not large source excerpts. A future training dataset must retain per-example provenance and rights status.

## Canonical references

- [Bitcoin Developer Documentation](https://developer.bitcoin.org/)
- [Bitcoin Core repository and license](https://github.com/bitcoin/bitcoin)
- [BIP 3: Updated BIP Process and license requirements](https://github.com/bitcoin/bips/blob/master/bip-0003.mediawiki)
- [Bitcoin Improvement Proposals repository](https://github.com/bitcoin/bips)
- [Lightning BOLTs repository and CC BY 4.0 notice](https://github.com/lightning/bolts)

## Corpus counts

The current starter corpus contains 21 short records across Bitcoin fundamentals, transactions, node operation, wallet standards, Taproot/SegWit, Bitcoin Core, and Lightning. This is a meaningful expansion of the original five-record seed set, not a complete Bitcoin encyclopedia or a trained model.
