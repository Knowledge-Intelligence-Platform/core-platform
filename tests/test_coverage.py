"""Coverage reports what the index holds, and is never answered by the agent."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.coverage import coverage, is_coverage_request
from app.models import UNMAPPED_COMPONENT_ID, Chunk, SourceType
from app.registry import ComponentRegistry

REGISTRY = ComponentRegistry(Path("tests/fixtures-registry/components"))


def chunk(component_id: str, source_type: SourceType, index: int = 0) -> Chunk:
    return Chunk(
        chunk_id=f"{component_id}-{source_type.value}-{index}",
        document_id=f"{component_id}-{source_type.value}",
        title="Doc",
        text="content",
        source_type=source_type,
        source_location="s3://bucket/key",
        component_id=component_id,
    )


@pytest.mark.parametrize(
    "text",
    ["coverage", "Coverage?", "  what do you know  ", "What is covered?", "knowledge coverage"],
)
def test_a_coverage_request_is_recognised(text: str) -> None:
    assert is_coverage_request(text)


@pytest.mark.parametrize(
    "text",
    ["what do you know about KIP Service?", "how does patching work", "coverage of the estate"],
)
def test_an_ordinary_question_is_not_a_coverage_request(text: str) -> None:
    assert not is_coverage_request(text)


def test_documented_and_undocumented_components_are_separated() -> None:
    chunks = (
        chunk("kip-service", SourceType.CONFLUENCE),
        chunk("kip-service", SourceType.GITHUB),
        chunk("knowledge-source", SourceType.CONFLUENCE),
        chunk("observability", SourceType.REGISTRY),
    )
    report = coverage(REGISTRY, chunks)

    states = {item.component_id: item.state for item in report.components}
    assert states["kip-service"] == "documented"
    assert states["knowledge-source"] == "confluence only"
    assert states["observability"] == "no documentation"
    assert {item.component_id for item in report.undocumented} >= {"observability"}


def test_a_registry_only_component_counts_as_undocumented() -> None:
    report = coverage(REGISTRY, (chunk("operations", SourceType.REGISTRY),))

    entry = next(i for i in report.components if i.component_id == "operations")
    assert entry.registry == 1
    assert entry.documented == 0
    assert entry.state == "no documentation"


def test_unmapped_documents_are_counted_separately() -> None:
    chunks = (
        chunk(UNMAPPED_COMPONENT_ID, SourceType.CONFLUENCE, 0),
        chunk(UNMAPPED_COMPONENT_ID, SourceType.CONFLUENCE, 1),
        chunk("kip-service", SourceType.CONFLUENCE),
    )
    report = coverage(REGISTRY, chunks)

    assert report.unmapped_chunks == 2
    assert report.unmapped_documents == 1
    assert all(item.component_id != UNMAPPED_COMPONENT_ID for item in report.components)


def test_every_registry_component_appears_even_with_no_chunks() -> None:
    report = coverage(REGISTRY, ())

    assert len(report.components) == len(REGISTRY.components)
    assert report.total_chunks == 0
    assert len(report.undocumented) == len(REGISTRY.components)
