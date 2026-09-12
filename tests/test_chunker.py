"""Chunking must stay deterministic: the same document yields the same ids."""

from __future__ import annotations

from app.chunker import chunk_document
from app.markdown_parser import parse_markdown


def build(content: str) -> object:
    return parse_markdown(
        content,
        document_id="d1",
        title="README",
        source_location="https://github.com/example-org/repo",
        component_id="kip-service",
    )


def test_chunk_ids_are_stable_across_runs() -> None:
    document = build("# Title\n\n" + "word " * 900)
    first = chunk_document(document)  # type: ignore[arg-type]
    second = chunk_document(document)  # type: ignore[arg-type]
    assert [c.chunk_id for c in first] == [c.chunk_id for c in second]


def test_chunk_ids_are_unique() -> None:
    chunks = chunk_document(build("# T\n\n" + "word " * 2000))  # type: ignore[arg-type]
    assert len({c.chunk_id for c in chunks}) == len(chunks)


def test_chunks_respect_the_size_limit() -> None:
    chunks = chunk_document(build("# T\n\n" + "word " * 2000))  # type: ignore[arg-type]
    assert chunks and all(len(chunk.text) <= 2_000 for chunk in chunks)


def test_heading_path_is_preserved() -> None:
    chunks = chunk_document(build("# Guide\n\n## Prerequisites\n\nYou need access."))  # type: ignore[arg-type]
    assert any(chunk.heading_path == ("Guide", "Prerequisites") for chunk in chunks)


def test_component_and_source_propagate_to_every_chunk() -> None:
    chunks = chunk_document(build("# T\n\nbody text here"))  # type: ignore[arg-type]
    assert all(chunk.component_id == "kip-service" for chunk in chunks)
    assert all(chunk.source_location.startswith("https://github.com/") for chunk in chunks)
