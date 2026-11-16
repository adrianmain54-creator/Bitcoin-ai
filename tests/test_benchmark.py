import json
from pathlib import Path

from bitcoin_ai.knowledge import BitcoinAnswerEngine, KnowledgeBase

ROOT = Path(__file__).parents[1]
KNOWLEDGE = ROOT / "data" / "knowledge" / "starter.jsonl"
BENCHMARK = ROOT / "data" / "knowledge" / "benchmark.jsonl"


def load_cases():
    with BENCHMARK.open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def test_benchmark_has_unique_ids_and_valid_expectations():
    cases = load_cases()
    ids = [case["id"] for case in cases]
    assert len(ids) == len(set(ids))
    assert all(isinstance(case["question"], str) and case["question"].strip() for case in cases)
    assert all(isinstance(case["expected_source_ids"], list) for case in cases)


def test_retrieval_benchmark_expected_sources_and_abstention():
    kb = KnowledgeBase.from_jsonl(KNOWLEDGE)
    engine = BitcoinAnswerEngine(kb)

    for case in load_cases():
        result = engine.answer(case["question"])
        assert result["abstained"] is case["should_abstain"], case["id"]
        actual_ids = {source["id"] for source in result["sources"]}
        if case["should_abstain"]:
            assert not actual_ids, case["id"]
        else:
            assert set(case["expected_source_ids"]) & actual_ids, case["id"]
