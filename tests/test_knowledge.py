from pathlib import Path
from bitcoin_ai.knowledge import KnowledgeBase, BitcoinAnswerEngine

DATA = Path(__file__).parents[1] / "data" / "knowledge" / "starter.jsonl"


def test_retrieval_finds_proof_of_work_source():
    kb = KnowledgeBase.from_jsonl(DATA)
    results = kb.search("How does proof of work mining work?")
    assert results
    assert results[0].document.id == "btc-dev-guide-mining"


def test_answer_includes_source_citations():
    engine = BitcoinAnswerEngine(KnowledgeBase.from_jsonl(DATA))
    result = engine.answer("What is the Bitcoin blockchain?")
    assert result["abstained"] is False
    assert result["sources"]
    assert result["sources"][0]["url"].startswith("https://")


def test_engine_abstains_on_unrelated_question():
    engine = BitcoinAnswerEngine(KnowledgeBase.from_jsonl(DATA))
    result = engine.answer("How do I bake a chocolate cake?")
    assert result["abstained"] is True
    assert result["sources"] == []
