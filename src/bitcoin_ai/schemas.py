from dataclasses import dataclass


@dataclass(frozen=True)
class KnowledgeDocument:
    id: str
    title: str
    text: str
    source_url: str
    source_type: str = "reference"
    license: str = "See source"
    published: str = "unknown"


@dataclass(frozen=True)
class RetrievedChunk:
    document: KnowledgeDocument
    score: float
