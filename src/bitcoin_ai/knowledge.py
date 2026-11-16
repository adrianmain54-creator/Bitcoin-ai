import json
import re
from pathlib import Path
from collections import Counter
from .schemas import KnowledgeDocument, RetrievedChunk

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "how", "in", "is", "it", "of", "on", "or", "that", "the", "to",
    "what", "when", "why", "with", "does", "do", "can",
}


def tokenize(text: str) -> list[str]:
    return [
        token for token in re.findall(r"[a-z0-9]+", text.lower())
        if token not in _STOPWORDS
    ]


class KnowledgeBase:
    def __init__(self, documents: list[KnowledgeDocument]):
        self.documents = documents

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
                    raise ValueError(f"Invalid knowledge record on line {line_number}: {exc}") from exc
        return cls(docs)

    def search(self, query: str, limit: int = 3) -> list[RetrievedChunk]:
        query_terms = set(tokenize(query))
        if not query_terms:
            return []

        results = []
        for doc in self.documents:
            terms = tokenize(doc.title + " " + doc.text)
            counts = Counter(terms)
            overlap = sum(1 for term in query_terms if counts[term])
            if not overlap:
                continue
            coverage = overlap / len(query_terms)
            density = overlap / max(len(set(terms)), 1)
            score = coverage * 0.85 + density * 0.15
            results.append(RetrievedChunk(doc, score))

        return sorted(results, key=lambda item: item.score, reverse=True)[:limit]


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
                "score": round(match.score, 3),
                "license": doc.license,
            })

        answer = (
            "Here is what the current local reference material supports:\n"
            + "\n".join(excerpts)
            + "\n\nThis is a source-grounded summary, not a live network or market check."
        )
        return {"answer": answer, "sources": sources, "abstained": False}
