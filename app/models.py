"""Bedrock retrieval and application response models."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class Chunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: str
    document_id: str
    title: str
    text: str = Field(min_length=1)
    source_location: str
    page_number: int | None = Field(default=None, ge=1)


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_id: str
    chunk: Chunk
    score: float

    @property
    def citation(self) -> str:
        if self.chunk.page_number:
            return f"{self.chunk.title} — Page {self.chunk.page_number}"
        return self.chunk.title


class MindMapBranch(BaseModel):
    model_config = ConfigDict(frozen=True)

    label: str = Field(min_length=1)
    items: tuple[str, ...] = ()


class MindMap(BaseModel):
    model_config = ConfigDict(frozen=True)

    center: str = Field(min_length=1)
    branches: tuple[MindMapBranch, ...] = Field(min_length=2, max_length=6)


class KnowledgeAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    answer: str
    visual: str | None = None
    mindmap: MindMap | None = None
    suggested_questions: tuple[str, ...] = ()
    response_type: str = "general"


class KnowledgeQueryResponse(BaseModel):
    """Public API response; source details remain internal."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    answer: str = Field(min_length=1)


class QueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    prompt: str = Field(min_length=3, max_length=4_000)
    conversation_id: str | None = Field(default=None, min_length=1, max_length=200)


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    knowledge_base_reachable: bool


class SyncJob(BaseModel):
    knowledge_base_id: str
    data_source_id: str
    ingestion_job_id: str
    status: str
