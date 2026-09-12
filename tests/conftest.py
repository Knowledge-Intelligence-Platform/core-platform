"""Shared fakes. Every test runs offline: no AWS, OpenAI, or Slack calls."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Iterator
from typing import Any

import pytest

from app.agent import IntelligentResponse
from app.models import Chunk, SearchResult, SourceType


@pytest.fixture(autouse=True)
def _quiet_logging() -> Iterator[None]:
    logging.disable(logging.CRITICAL)
    yield
    logging.disable(logging.NOTSET)


def make_chunk(chunk_id: str = "c1", text: str = "Raise a cluster request.") -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="d1",
        title="KIP Service onboarding",
        text=text,
        source_type=SourceType.CONFLUENCE,
        source_location="s3://bucket/key.pdf",
        component_id="kip-service",
    )


class StubSearch:
    """Hybrid search stand-in that records the queries it was asked for."""

    def __init__(self, results: int = 1) -> None:
        self.results = results
        self.queries: list[str] = []

    def search(self, query: str, limit: int) -> tuple[SearchResult, ...]:
        self.queries.append(query)
        chunk = make_chunk()
        return tuple(
            SearchResult(source_id=f"S{index + 1}", chunk=chunk, score=1.0)
            for index in range(self.results)
        )


class StubStreamingAgent:
    """Mimics a Strands agent: JSON deltas, then a structured-output event."""

    def __init__(self, payload: dict[str, Any], *, emit_structured: bool = True) -> None:
        self.payload = payload
        self.emit_structured = emit_structured
        self.prompts: list[str] = []

    async def stream_async(self, prompt: str, **_: Any) -> AsyncIterator[dict[str, Any]]:
        self.prompts.append(prompt)
        serialized = json.dumps(self.payload)
        for start in range(0, len(serialized), 8):
            yield {"data": serialized[start : start + 8], "delta": {}}
        if self.emit_structured:
            yield {"structured_output": IntelligentResponse(**self.payload)}


@pytest.fixture
def answer_payload() -> dict[str, Any]:
    return {
        "answer": "Onboarding starts with a cluster request 🚀 [S1] then approval.",
        "response_type": "onboarding",
        "visual_nodes": ["Request", "Approve", "Deploy"],
        "suggested_questions": ["What happens after approval?"],
    }
