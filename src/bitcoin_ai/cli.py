import argparse
import json
from pathlib import Path
from .knowledge import KnowledgeBase, BitcoinAnswerEngine

DEFAULT_DATA = Path(__file__).resolve().parents[2] / "data" / "knowledge" / "starter.jsonl"


def main() -> None:
    parser = argparse.ArgumentParser(prog="bitcoin-ai", description="Local Bitcoin knowledge assistant")
    subparsers = parser.add_subparsers(dest="command", required=True)
    ask_parser = subparsers.add_parser("ask", help="Ask the local Bitcoin knowledge base")
    ask_parser.add_argument("question", help="Question to answer")
    ask_parser.add_argument("--data", type=Path, default=DEFAULT_DATA, help="Path to knowledge JSONL")
    ask_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
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


if __name__ == "__main__":
    main()
