from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from app.models import SearchResult


class Searcher(Protocol):
    def search(self, query: str, limit: int) -> tuple[SearchResult, ...]: ...


class EvidenceRef(BaseModel):
    """What a task record keeps about a passage: where it came from, never its text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    document_id: str
    title: str
    url: str
    space: str | None = None
    last_updated_at: datetime | None = None
    content_hash: str


class Evidence(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str
    document_id: str
    title: str
    url: str
    space: str | None = None
    last_updated_at: datetime | None = None
    chunk_id: str
    content_hash: str
    text: str
    score: float

    def reference(self) -> EvidenceRef:
        return EvidenceRef(
            document_id=self.document_id,
            title=self.title,
            url=self.url,
            space=self.space,
            last_updated_at=self.last_updated_at,
            content_hash=self.content_hash,
        )


class EvidenceSet(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    query: str
    retrieved_at: datetime
    items: tuple[Evidence, ...] = ()

    @property
    def empty(self) -> bool:
        return not self.items

    def references(self) -> tuple[EvidenceRef, ...]:
        return tuple(item.reference() for item in self.items)


def collect_evidence(search: Searcher, query: str, limit: int) -> EvidenceSet:
    """Return the original passages with source and version, or an explicit empty set."""
    return EvidenceSet(
        query=query,
        retrieved_at=datetime.now(UTC),
        items=tuple(_evidence(result) for result in search.search(query, limit)),
    )


def _evidence(result: SearchResult) -> Evidence:
    chunk = result.chunk
    return Evidence(
        source_id=result.source_id,
        document_id=chunk.document_id,
        title=chunk.title,
        url=chunk.source_location,
        space=chunk.space,
        last_updated_at=chunk.last_updated_at,
        chunk_id=chunk.chunk_id,
        content_hash=hashlib.sha256(chunk.text.encode()).hexdigest(),
        text=chunk.text,
        score=result.score,
    )
