import json
import math
import re
from collections import Counter
from pathlib import Path

from .schemas import KnowledgeDocument, RetrievedChunk

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "to",
    "what", "when", "why", "with", "does", "do", "can", "use",
    "manage", "manages", "managing", "support", "supports",
}


def tokenize(text: str) -> list[str]:
    """Normalize prose into searchable terms without external dependencies."""
    return [
        token for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _STOPWORDS
    ]


class KnowledgeBase:
    """Small local corpus with deterministic, IDF-weighted retrieval."""

    def __init__(self, documents: list[KnowledgeDocument]):
        ids = [doc.id for doc in documents]
        if len(ids) != len(set(ids)):
            raise ValueError("Knowledge document IDs must be unique")
        self.documents = documents
        self._indexed = []
        self._document_frequency = Counter()
        for doc in documents:
            if not doc.id.strip() or not doc.title.strip() or not doc.text.strip():
                raise ValueError("Knowledge documents require non-empty id, title, and text")
            if not doc.source_url.startswith(("https://", "http://")):
                raise ValueError(f"Knowledge document {doc.id!r} has an invalid source_url")
            if not doc.publisher.strip() or doc.publisher == "unknown":
                raise ValueError(f"Knowledge document {doc.id!r} is missing publisher provenance")
            if not doc.retrieved_on.strip() or doc.retrieved_on == "unknown":
                raise ValueError(f"Knowledge document {doc.id!r} is missing retrieved_on provenance")
            if not doc.license_status.strip() or doc.license_status == "unverified":
                raise ValueError(f"Knowledge document {doc.id!r} is missing license_status")
            if not isinstance(doc.topics, (list, tuple)) or not doc.topics:
                raise ValueError(f"Knowledge document {doc.id!r} requires at least one topic")
            title_terms = Counter(tokenize(doc.title))
            body_terms = Counter(tokenize(doc.text))
            self._indexed.append((doc, title_terms, body_terms))
            self._document_frequency.update(set(title_terms) | set(body_terms))

    @classmethod
    def from_jsonl(cls, path: str | Path) -> "KnowledgeBase":
        docs = []
        with Path(path).open(encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    docs.append(KnowledgeDocument(**item))
                except (json.JSONDecodeError, TypeError) as exc:
                    raise ValueError(
                        f"Invalid knowledge record on line {line_number}: {exc}"
                    ) from exc
        try:
            return cls(docs)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"Invalid knowledge corpus: {exc}") from exc

    def search(self, query: str, limit: int = 3) -> list[RetrievedChunk]:
        if limit <= 0:
            return []
        query_terms = set(tokenize(query))
        if not query_terms or not self.documents:
            return []

        # IDF reduces the influence of generic terms shared by many documents.
        total_docs = len(self.documents)
        idf = {
            term: math.log(1 + (total_docs - self._document_frequency[term] + 0.5)
                           / (self._document_frequency[term] + 0.5))
            for term in query_terms
        }
        denominator = sum(idf.values()) or 1.0
        normalized_query = " ".join(tokenize(query))
        results = []

        for doc, title_terms, body_terms in self._indexed:
            weighted_match = 0.0
            matched = 0
            for term in query_terms:
                title_frequency = title_terms[term]
                body_frequency = body_terms[term]
                if title_frequency or body_frequency:
                    matched += 1
                    # Title hits count more than body hits; repeated terms have diminishing value.
                    weighted_match += idf[term] * (
                        2.0 * min(title_frequency, 2) + min(body_frequency, 3)
                    )
            if not matched:
                continue

            coverage = sum(idf[t] for t in query_terms
                           if title_terms[t] or body_terms[t]) / denominator
            length_norm = math.sqrt(max(sum(body_terms.values()), 1))
            score = 0.65 * coverage + 0.35 * (weighted_match / (denominator * length_norm))
            searchable_text = " ".join(tokenize(doc.title + " " + doc.text))
            if len(normalized_query) >= 8 and normalized_query in searchable_text:
                score += 0.05
            results.append(RetrievedChunk(doc, round(score, 6)))

        return sorted(results, key=lambda item: (-item.score, item.document.id))[:limit]


class BitcoinAnswerEngine:
    def __init__(self, knowledge_base: KnowledgeBase, minimum_score: float = 0.12):
        self.knowledge_base = knowledge_base
        self.minimum_score = minimum_score

    def answer(self, question: str) -> dict:
        matches = self.knowledge_base.search(question)
        if not matches or matches[0].score < self.minimum_score:
            return {
                "answer": (
                    "I don't have enough evidence in the current local Bitcoin "
                    "knowledge base to answer that reliably. Add a trustworthy "
                    "source or connect an approved data provider, then try again."
                ),
                "sources": [],
                "abstained": True,
            }

        excerpts = []
        sources = []
        seen = set()
        for match in matches:
            doc = match.document
            if doc.id in seen:
                continue
            seen.add(doc.id)
            excerpts.append(f"- {doc.text.strip()}")
            sources.append({
                "id": doc.id,
                "title": doc.title,
                "url": doc.source_url,
                "score": match.score,
                "license": doc.license,
            })

        answer = (
            "Here is what the current local reference material supports:\n"
            + "\n".join(excerpts)
            + "\n\nThis is a source-grounded summary, not a live network or market check."
        )
        return {"answer": answer, "sources": sources, "abstained": False}
