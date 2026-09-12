"""What the platform actually holds, counted from the index.

This is knowledge about the system, not about the platform, so it is never answered by
the agent — an answer with no retrieved passages behind it would be ungrounded
by definition. It is computed here and delivered directly.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from app.models import UNMAPPED_COMPONENT_ID, Chunk, SourceType
from app.registry import ComponentRegistry

COVERAGE_REQUEST = frozenset(
    {
        "coverage",
        "what do you know",
        "what do you know about",
        "knowledge coverage",
        "what is covered",
    }
)


def is_coverage_request(text: str) -> bool:
    normalized = " ".join(text.casefold().split()).strip(" ?.!")
    return normalized in COVERAGE_REQUEST


@dataclass(frozen=True)
class ComponentCoverage:
    component_id: str
    name: str
    confluence: int
    github: int
    registry: int

    @property
    def documented(self) -> int:
        return self.confluence + self.github

    @property
    def state(self) -> str:
        if self.confluence and self.github:
            return "documented"
        if self.confluence:
            return "confluence only"
        if self.github:
            return "readme only"
        return "no documentation"


@dataclass(frozen=True)
class Coverage:
    components: tuple[ComponentCoverage, ...]
    unmapped_chunks: int
    unmapped_documents: int
    total_chunks: int

    @property
    def undocumented(self) -> tuple[ComponentCoverage, ...]:
        return tuple(item for item in self.components if not item.documented)


def coverage(registry: ComponentRegistry, chunks: tuple[Chunk, ...]) -> Coverage:
    by_component: dict[str, Counter[str]] = {}
    for chunk in chunks:
        counts = by_component.setdefault(chunk.component_id, Counter())
        counts[chunk.source_type.value] += 1

    components = tuple(
        ComponentCoverage(
            component_id=component.id,
            name=component.name,
            confluence=by_component.get(component.id, Counter())[SourceType.CONFLUENCE],
            github=by_component.get(component.id, Counter())[SourceType.GITHUB],
            registry=by_component.get(component.id, Counter())[SourceType.REGISTRY],
        )
        for component in sorted(registry.components, key=lambda item: item.name)
    )
    unmapped = by_component.get(UNMAPPED_COMPONENT_ID, Counter())
    return Coverage(
        components=components,
        unmapped_chunks=sum(unmapped.values()),
        unmapped_documents=len(
            {
                chunk.document_id
                for chunk in chunks
                if chunk.component_id == UNMAPPED_COMPONENT_ID
            }
        ),
        total_chunks=len(chunks),
    )
