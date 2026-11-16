from pathlib import Path

import pytest

from bitcoin_ai.knowledge import KnowledgeBase, BitcoinAnswerEngine
from bitcoin_ai.schemas import KnowledgeDocument

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


def test_search_is_deterministic_and_respects_limit():
    kb = KnowledgeBase.from_jsonl(DATA)
    first = kb.search("Bitcoin transactions and proof of work", limit=2)
    second = kb.search("Bitcoin transactions and proof of work", limit=2)
    assert [item.document.id for item in first] == [item.document.id for item in second]
    assert len(first) <= 2


def test_empty_query_and_nonpositive_limit_return_no_results():
    kb = KnowledgeBase.from_jsonl(DATA)
    assert kb.search("the and of") == []
    assert kb.search("bitcoin", limit=0) == []


def test_duplicate_document_ids_are_rejected():
    doc = KnowledgeDocument("same", "Bitcoin", "Bitcoin protocol", "https://example.org")
    with pytest.raises(ValueError, match="unique"):
        KnowledgeBase([doc, doc])


def test_invalid_source_url_is_rejected():
    doc = KnowledgeDocument("bad-url", "Bitcoin", "Bitcoin protocol", "file:///tmp/source")
    with pytest.raises(ValueError, match="source_url"):
        KnowledgeBase([doc])


def test_every_corpus_entry_has_source_provenance():
    kb = KnowledgeBase.from_jsonl(DATA)
    assert len(kb.documents) >= 20
    for doc in kb.documents:
        assert doc.publisher and doc.publisher != "unknown"
        assert doc.retrieved_on == "2026-11-16"
        assert doc.license_status and doc.license_status != "unverified"
        assert doc.topics


def test_engine_abstains_on_overly_broad_or_weakly_supported_queries():
    engine = BitcoinAnswerEngine(KnowledgeBase.from_jsonl(DATA))
    assert engine.answer("Bitcoin")["abstained"] is True
    assert engine.answer("Bitcoin price prediction")["abstained"] is True
