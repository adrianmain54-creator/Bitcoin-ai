import json

import pytest

from bitcoin_ai.corpus_audit import build_corpus_report
from bitcoin_ai.knowledge import KnowledgeBase


def test_corpus_report_counts_topics_domains_and_license_status(tmp_path):
    path = tmp_path / "knowledge.jsonl"
    records = [
        {
            "id": "one", "title": "Bitcoin mining", "text": "Miners find proof of work.",
            "source_url": "https://example.org/mining", "publisher": "Example",
            "retrieved_on": "2026-11-16", "license_status": "review-required",
            "topics": ["mining", "consensus"],
        },
        {
            "id": "two", "title": "Bitcoin wallets", "text": "Wallets manage keys.",
            "source_url": "https://docs.example.org/wallets", "publisher": "Docs",
            "retrieved_on": "2026-11-16", "license_status": "verified",
            "topics": ["wallets"],
        },
    ]
    path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")

    report = build_corpus_report(path)

    assert report["document_count"] == 2
    assert report["topic_counts"] == {"consensus": 1, "mining": 1, "wallets": 1}
    assert report["source_domain_counts"] == {
        "docs.example.org": 1, "example.org": 1
    }
    assert report["license_status_counts"] == {
        "review-required": 1, "verified": 1
    }
    assert report["duplicate_summary_groups"] == []


def test_corpus_report_detects_duplicate_summaries(tmp_path):
    path = tmp_path / "knowledge.jsonl"
    common = {
        "title": "Bitcoin", "text": "  Bitcoin   uses proof of work. ",
        "source_url": "https://example.org", "publisher": "Example",
        "retrieved_on": "2026-11-16", "license_status": "review-required",
        "topics": ["consensus"],
    }
    records = [{**common, "id": "a"}, {**common, "id": "b"}]
    path.write_text("\n".join(json.dumps(item) for item in records), encoding="utf-8")

    report = build_corpus_report(path)

    assert report["duplicate_summary_groups"] == [["a", "b"]]
    assert report["quality_flags"] == ["duplicate summaries detected"]


def test_corpus_report_rejects_invalid_corpus(tmp_path):
    path = tmp_path / "bad.jsonl"
    path.write_text('{"id": "broken"}\n', encoding="utf-8")
    with pytest.raises(ValueError):
        build_corpus_report(path)
