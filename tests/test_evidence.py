from datetime import UTC, datetime

from app.evidence import collect_evidence
from app.models import Chunk, SearchResult
from tests.conftest import StubSearch


class FixedSearch:
    def __init__(self, text: str) -> None:
        self.chunk = Chunk(
            chunk_id="c1",
            document_id="doc-1",
            title="SSH access standard",
            text=text,
            source_location="https://example.atlassian.net/wiki/spaces/KIP/pages/9",
            space="Knowledge Intelligence Platform",
            last_updated_at=datetime(2026, 10, 3, 14, 15, 59, tzinfo=UTC),
        )

    def search(self, query: str, limit: int) -> tuple[SearchResult, ...]:
        return (SearchResult(source_id="S1", chunk=self.chunk, score=0.9),)


def test_evidence_keeps_original_passage_source_and_version() -> None:
    evidence = collect_evidence(FixedSearch("No unrestricted SSH."), "ssh standard", 5)
    item = evidence.items[0]
    assert not evidence.empty
    assert item.text == "No unrestricted SSH."
    assert item.title == "SSH access standard"
    assert item.url.endswith("/pages/9")
    assert item.space == "Knowledge Intelligence Platform"
    assert item.last_updated_at == datetime(2026, 10, 3, 14, 15, 59, tzinfo=UTC)
    assert item.source_id == "S1"


def test_empty_retrieval_is_explicit() -> None:
    evidence = collect_evidence(StubSearch(results=0), "anything", 5)
    assert evidence.empty
    assert evidence.items == ()
    assert evidence.references() == ()


def test_reference_omits_text_and_changes_when_the_passage_changes() -> None:
    first = collect_evidence(FixedSearch("No unrestricted SSH."), "q", 5).references()[0]
    second = collect_evidence(FixedSearch("SSH from the office only."), "q", 5).references()[0]
    assert "text" not in first.model_dump()
    assert first.content_hash != second.content_hash
    assert first.document_id == second.document_id
