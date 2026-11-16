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
    publisher: str = "unknown"
    retrieved_on: str = "unknown"
    license_status: str = "unverified"
    license_url: str = ""
    topics: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievedChunk:
    document: KnowledgeDocument
    score: float
