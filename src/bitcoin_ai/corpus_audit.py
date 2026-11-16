"""Corpus quality report: provenance, topic coverage, and duplicate summaries."""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

from .knowledge import KnowledgeBase


def build_corpus_report(path: str | Path) -> dict:
    """Audit a JSONL corpus without fetching or trusting external source content."""
    kb = KnowledgeBase.from_jsonl(path)
    topic_counts: Counter[str] = Counter()
    license_counts: Counter[str] = Counter()
    domain_counts: Counter[str] = Counter()
    fingerprints: dict[str, list[str]] = defaultdict(list)

    for doc in kb.documents:
        topic_counts.update(doc.topics)
        license_counts.update([doc.license_status])
        domain = urlparse(doc.source_url).netloc.lower()
        domain_counts.update([domain])

        # Hash normalized original summaries, not source pages. This catches exact
        # duplicate knowledge entries while avoiding external content downloads.
        normalized = " ".join(doc.text.casefold().split())
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        fingerprints[digest].append(doc.id)

    duplicate_groups = [
        sorted(ids) for ids in fingerprints.values() if len(ids) > 1
    ]
    duplicate_groups.sort(key=lambda group: group[0])

    return {
        "document_count": len(kb.documents),
        "topic_counts": dict(sorted(topic_counts.items())),
        "license_status_counts": dict(sorted(license_counts.items())),
        "source_domain_counts": dict(sorted(domain_counts.items())),
        "duplicate_summary_groups": duplicate_groups,
        "quality_flags": (
            ["duplicate summaries detected"] if duplicate_groups else []
        ),
        "note": (
            "This is a structural corpus audit, not verification that sources are "
            "accurate, current, authoritative, or licensed for redistribution."
        ),
    }


def format_corpus_report(report: dict) -> str:
    """Render a compact, stable human-readable corpus report."""
    lines = [
        f"Knowledge documents: {report['document_count']}",
        f"Duplicate summary groups: {len(report['duplicate_summary_groups'])}",
        "Topics:",
    ]
    lines.extend(
        f"  {topic}: {count}"
        for topic, count in report["topic_counts"].items()
    )
    lines.append("License review statuses:")
    lines.extend(
        f"  {status}: {count}"
        for status, count in report["license_status_counts"].items()
    )
    lines.append("Source domains:")
    lines.extend(
        f"  {domain}: {count}"
        for domain, count in report["source_domain_counts"].items()
    )
    lines.append(report["note"])
    return "\n".join(lines)
