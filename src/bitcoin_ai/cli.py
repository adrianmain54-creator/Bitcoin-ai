import argparse
import json
from pathlib import Path

from .data_sources import DataSourceError, MempoolSpaceClient
from .corpus_audit import build_corpus_report, format_corpus_report
from .knowledge import KnowledgeBase, BitcoinAnswerEngine

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "starter.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(prog="bitcoin-ai", description="Local Bitcoin knowledge assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ask_parser = subparsers.add_parser("ask", help="Ask the local Bitcoin knowledge base")
    ask_parser.add_argument("question", help="Question to answer")
    ask_parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Path to knowledge JSONL")
    ask_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    audit_parser = subparsers.add_parser("audit", help="Audit local knowledge corpus quality")
    audit_parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Path to knowledge JSONL")
    audit_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")

    network_parser = subparsers.add_parser(
        "network", help="Fetch a read-only live Bitcoin network snapshot"
    )
    network_parser.add_argument("--currency", default="USD", help="Three-letter currency code")
    network_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    if args.command == "ask":
        engine = BitcoinAnswerEngine(KnowledgeBase.from_jsonl(args.data))
        result = engine.answer(args.question)
        if args.json:
            print(json.dumps(result, indent=2))
            return
        print(result["answer"])
        if result["sources"]:
            print("\nSources:")
            for source in result["sources"]:
                print(f'[{source["id"]}] {source["title"]} — {source["url"]}')
        print(f'\nEvidence status: {"insufficient" if result["abstained"] else "retrieved"}')
        return

    if args.command == "audit":
        try:
            report = build_corpus_report(args.data)
        except (OSError, ValueError) as exc:
            parser.exit(1, f"bitcoin-ai: corpus audit failed: {exc}\\n")
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            print(format_corpus_report(report))
        return

    if args.command == "network":
        try:
            result = MempoolSpaceClient().snapshot(currency=args.currency)
        except (DataSourceError, ValueError) as exc:
            parser.exit(1, f"bitcoin-ai: live data unavailable: {exc}\n")
        if args.json:
            print(json.dumps(result, indent=2))
            return
        print(f'Bitcoin network snapshot ({result["currency"]})')
        print(f'BTC price: {result["price"]["value"]:,.2f} {result["currency"]}')
        print(f'Block height: {result["block_height"]["value"]:,}')
        print(f'Mempool transactions: {result["mempool"]["value"]["count"]:,}')
        print(f'Fastest fee: {result["recommended_fees"]["value"]["fastestFee"]} sat/vB')
        print(f'Provider: {result["provider"]}')
        print(f'Retrieved: {result["retrieved_at"]}')
        print(result["disclaimer"])


if __name__ == "__main__":
    main()
