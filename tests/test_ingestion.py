"""One unreadable repository must not discard an entire ingestion run."""

from __future__ import annotations

from typing import Any

import pytest

from app.ingestion import Ingestion
from app.models import (
    UNMAPPED_COMPONENT_ID,
    Chunk,
    Component,
    ParsedDocument,
    SourceType,
)

COMPONENT = Component(id="kip-service", name="KIP Service As A Service", description="KIP Service.")
README = "# Title\n\nOnboarding starts with a cluster request.\n"


class StubRegistry:
    def __init__(self, *repositories: str) -> None:
        self.names = repositories

    def repositories(self) -> tuple[tuple[Component, str, str | None], ...]:
        return tuple((COMPONENT, name, None) for name in self.names)


class StubGitHub:
    """Returns a README, nothing, or raises — one behaviour per repository."""

    def __init__(self, behaviour: dict[str, str]) -> None:
        self.behaviour = behaviour
        self.seen: list[str] = []

    def read_readme(self, repository: str, branch: str | None = None) -> tuple[str, str] | None:
        self.seen.append(repository)
        outcome = self.behaviour[repository]
        if outcome == "raise":
            raise RuntimeError(f"Unable to read README.md from {repository}.")
        if outcome == "missing":
            return None
        return README, f"https://github.com/{repository}/blob/main/README.md"


def make_ingestion(registry: StubRegistry, github: StubGitHub) -> Ingestion:
    unused: Any = None
    return Ingestion(
        s3=unused,
        github=github,  # type: ignore[arg-type]
        registry=registry,  # type: ignore[arg-type]
        embeddings=unused,
        vectors=unused,
        search=unused,
        s3_prefix="raw/confluence",
        batch_size=16,
        diagram_analyzer=None,
    )


def test_an_unreadable_repository_is_skipped_not_fatal() -> None:
    github = StubGitHub({"example-org/broken": "raise", "example-org/good": "readme"})
    ingestion = make_ingestion(StubRegistry("example-org/broken", "example-org/good"), github)

    documents, skipped = ingestion._github_documents()

    assert skipped == 1
    assert len(documents) == 1
    assert documents[0].component_id == "kip-service"
    assert github.seen == ["example-org/broken", "example-org/good"]


def test_a_repository_without_a_readme_is_not_counted_as_skipped() -> None:
    github = StubGitHub({"example-org/empty": "missing"})
    ingestion = make_ingestion(StubRegistry("example-org/empty"), github)

    documents, skipped = ingestion._github_documents()

    assert documents == ()
    assert skipped == 0


def test_every_repository_failing_still_returns_cleanly() -> None:
    github = StubGitHub({"example-org/a": "raise", "example-org/b": "raise"})
    ingestion = make_ingestion(StubRegistry("example-org/a", "example-org/b"), github)

    documents, skipped = ingestion._github_documents()

    assert documents == ()
    assert skipped == 2


def test_an_unexpected_error_still_propagates() -> None:
    """Only a README read failure is tolerated; real defects must surface."""

    class ExplodingRegistry:
        def repositories(self) -> tuple[tuple[Component, str, str | None], ...]:
            raise MemoryError("not a README problem")

    ingestion = make_ingestion(ExplodingRegistry(), StubGitHub({}))  # type: ignore[arg-type]
    with pytest.raises(MemoryError):
        ingestion._github_documents()

PDF_KEY = "raw/confluence/kip-service/onboarding.pdf"


def make_chunk(chunk_id: str, source_type: SourceType) -> Chunk:
    return Chunk(
        chunk_id=chunk_id,
        document_id="d1",
        title="Existing",
        text="Existing indexed content.",
        source_type=source_type,
        source_location="s3://bucket/key",
        component_id="kip-service",
    )

EXISTING = (
    make_chunk("pdf-1", SourceType.CONFLUENCE),
    make_chunk("readme-1", SourceType.GITHUB),
    make_chunk("registry-1", SourceType.REGISTRY),
)


class StubS3:
    bucket = "bucket"

    def __init__(self) -> None:
        self.reads = 0

    def iter_pdfs(self, prefix: str) -> Any:
        self.reads += 1
        yield PDF_KEY, b"%PDF-1.4 fake"


class StubVectors:
    def __init__(self) -> None:
        self.finalized: tuple[str, ...] = ()
        self.written: list[Chunk] = []

    def load_chunks(self) -> tuple[Chunk, ...]:
        return EXISTING

    def put(self, chunks: tuple[Chunk, ...], embeddings: Any) -> int:
        self.written.extend(chunks)
        return len(chunks)

    def finalize(self, active_chunk_ids: tuple[str, ...]) -> None:
        self.finalized = active_chunk_ids


class StubSearch:
    def __init__(self) -> None:
        self.cached: tuple[Chunk, ...] = ()

    def replace_keyword_cache(self, chunks: tuple[Chunk, ...]) -> None:
        self.cached = chunks


class StubEmbeddings:
    def create(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        return tuple((0.1,) * 4 for _ in texts)


class FullRegistry(StubRegistry):
    def __init__(self) -> None:
        super().__init__("example-org/good")

    def as_documents(self) -> tuple[ParsedDocument, ...]:
        return (
            ParsedDocument(
                document_id="reg-doc",
                title="KIP Service component registry",
                source_type=SourceType.REGISTRY,
                source_location="tests/fixtures-registry/components/kip-service.yaml",
                component_id="kip-service",
                blocks=(),
            ),
        )

    def component_for_s3_key(self, key: str) -> Component:
        return COMPONENT


@pytest.fixture
def parts(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    def fake_parse_pdf(content: bytes, **kwargs: Any) -> ParsedDocument:
        return ParsedDocument(
            document_id="pdf-doc",
            title="Onboarding",
            source_type=SourceType.CONFLUENCE,
            source_location=f"s3://bucket/{PDF_KEY}",
            component_id="kip-service",
            blocks=(),
        )

    def fake_chunk_document(document: ParsedDocument) -> tuple[Chunk, ...]:
        return (make_chunk(f"new-{document.source_type.value}", document.source_type),)

    monkeypatch.setattr("app.ingestion.parse_pdf", fake_parse_pdf)
    monkeypatch.setattr("app.ingestion.chunk_document", fake_chunk_document)
    s3, vectors, search = StubS3(), StubVectors(), StubSearch()
    ingestion = Ingestion(
        s3=s3,  # type: ignore[arg-type]
        github=StubGitHub({"example-org/good": "readme"}),  # type: ignore[arg-type]
        registry=FullRegistry(),  # type: ignore[arg-type]
        embeddings=StubEmbeddings(),  # type: ignore[arg-type]
        vectors=vectors,  # type: ignore[arg-type]
        search=search,  # type: ignore[arg-type]
        s3_prefix="raw/confluence",
        batch_size=16,
        diagram_analyzer=None,
    )
    return {"ingestion": ingestion, "s3": s3, "vectors": vectors, "search": search}


def test_a_full_run_replaces_everything(parts: dict[str, Any]) -> None:
    summary = parts["ingestion"].run()

    assert summary.documents == 3
    assert set(parts["vectors"].finalized) == {
        "new-confluence",
        "new-github",
        "new-registry",
    }


def test_a_github_only_run_keeps_the_confluence_index(parts: dict[str, Any]) -> None:
    summary = parts["ingestion"].run(frozenset({SourceType.GITHUB}))

    assert summary.documents == 1
    assert parts["s3"].reads == 0
    assert [chunk.chunk_id for chunk in parts["vectors"].written] == ["new-github"]
    assert set(parts["vectors"].finalized) == {"new-github", "pdf-1", "registry-1"}
    assert "readme-1" not in parts["vectors"].finalized


def test_a_confluence_only_run_keeps_the_readme_index(parts: dict[str, Any]) -> None:
    parts["ingestion"].run(frozenset({SourceType.CONFLUENCE}))

    assert set(parts["vectors"].finalized) == {"new-confluence", "readme-1", "registry-1"}


def test_retained_chunks_are_searchable_after_a_partial_run(parts: dict[str, Any]) -> None:
    parts["ingestion"].run(frozenset({SourceType.GITHUB}))

    cached = {chunk.chunk_id for chunk in parts["search"].cached}
    assert cached == {"new-github", "pdf-1", "registry-1"}


class UnmappedRegistry(FullRegistry):
    """Every S3 key is unclaimed: nothing in the registry maps it."""

    def component_for_s3_key(self, key: str) -> Component | None:
        return None


@pytest.fixture
def unmapped(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    seen: dict[str, str] = {}

    def fake_parse_pdf(content: bytes, **kwargs: Any) -> ParsedDocument:
        seen["component_id"] = kwargs["component_id"]
        return ParsedDocument(
            document_id="pdf-doc",
            title="Onboarding",
            source_type=SourceType.CONFLUENCE,
            source_location=f"s3://bucket/{PDF_KEY}",
            component_id=kwargs["component_id"],
            blocks=(),
        )

    monkeypatch.setattr("app.ingestion.parse_pdf", fake_parse_pdf)
    monkeypatch.setattr(
        "app.ingestion.chunk_document",
        lambda document: (make_chunk(f"new-{document.source_type.value}", document.source_type),),
    )
    return {"seen": seen}


def build(registry: Any, *, ingest_unmapped: bool) -> Ingestion:
    return Ingestion(
        s3=StubS3(),  # type: ignore[arg-type]
        github=None,
        registry=registry,
        embeddings=StubEmbeddings(),  # type: ignore[arg-type]
        vectors=StubVectors(),  # type: ignore[arg-type]
        search=StubSearch(),  # type: ignore[arg-type]
        s3_prefix="raw/confluence",
        batch_size=16,
        diagram_analyzer=None,
        ingest_unmapped_documents=ingest_unmapped,
    )


def test_an_unmapped_pdf_is_indexed(unmapped: dict[str, Any]) -> None:
    summary = build(UnmappedRegistry(), ingest_unmapped=True).run(
        frozenset({SourceType.CONFLUENCE})
    )

    assert summary.unmapped == 1
    assert summary.skipped == 0
    assert summary.documents == 1


def test_an_unmapped_pdf_is_indexed_without_an_owner(unmapped: dict[str, Any]) -> None:
    build(UnmappedRegistry(), ingest_unmapped=True).run(frozenset({SourceType.CONFLUENCE}))

    assert unmapped["seen"]["component_id"] == UNMAPPED_COMPONENT_ID


def test_the_stricter_behaviour_is_still_available(unmapped: dict[str, Any]) -> None:
    summary = build(UnmappedRegistry(), ingest_unmapped=False).run(
        frozenset({SourceType.CONFLUENCE})
    )

    assert summary.documents == 0
    assert summary.skipped == 1
    assert summary.unmapped == 0


def test_a_mapped_pdf_still_gets_its_component(unmapped: dict[str, Any]) -> None:
    summary = build(FullRegistry(), ingest_unmapped=True).run(
        frozenset({SourceType.CONFLUENCE})
    )

    assert unmapped["seen"]["component_id"] == "kip-service"
    assert summary.unmapped == 0
