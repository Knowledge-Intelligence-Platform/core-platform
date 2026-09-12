"""Hybrid search: the inverted keyword index and its ranking."""

from __future__ import annotations

from typing import Any

from app.models import Chunk, SourceType
from app.search import HybridSearch, _singular, _tokens

CORPUS = (
    "KIP Service onboarding requires a cluster request and approval",
    "Golden AMI patching lifecycle and validation runbook",
    "Integration pipeline observability dashboards",
    "KIP Service cluster upgrade runbook with validation steps",
    "Onboarding prerequisites for new KIP users",
)


class UnavailableEmbeddings:
    def create(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
        raise RuntimeError("semantic search unavailable")


class EmptyVectors:
    def query(self, embedding: tuple[float, ...], limit: int) -> tuple[Any, ...]:
        return ()

    def load_chunks(self) -> tuple[Chunk, ...]:
        return ()


def build_search() -> HybridSearch:
    chunks = tuple(
        Chunk(
            chunk_id=f"c{index}",
            document_id="d",
            title="doc",
            text=text,
            source_type=SourceType.CONFLUENCE,
            source_location="s3://b/k",
            component_id="kip-service",
        )
        for index, text in enumerate(CORPUS)
    )
    search = HybridSearch(UnavailableEmbeddings(), EmptyVectors(), top_k=5)  # type: ignore[arg-type]
    search.replace_keyword_cache(chunks)
    return search


def test_keyword_search_survives_semantic_failure() -> None:
    # The embedding provider raises; keyword results must still come back.
    assert build_search().search("KIP Service cluster runbook", 5)


def test_source_ids_are_sequential_from_one() -> None:
    results = build_search().search("KIP Service cluster runbook", 5)
    assert [r.source_id for r in results] == [f"S{i}" for i in range(1, len(results) + 1)]


def test_results_are_ranked_by_descending_score() -> None:
    results = build_search().search("KIP Service onboarding", 5)
    scores = [r.score for r in results]
    assert scores == sorted(scores, reverse=True)


def test_unmatched_query_returns_nothing() -> None:
    assert build_search().search("zzzz qqqq", 5) == ()


def test_blank_query_returns_nothing() -> None:
    assert build_search().search("   ", 5) == ()


def test_empty_index_returns_nothing() -> None:
    search = build_search()
    search.replace_keyword_cache(())
    assert search.search("KIP Service", 5) == ()
    assert search.cached_chunk_count == 0


def test_cached_chunk_count_tracks_the_index() -> None:
    assert build_search().cached_chunk_count == len(CORPUS)


def test_limit_is_respected() -> None:
    assert len(build_search().search("KIP Service onboarding runbook", 2)) <= 2


def test_a_plural_and_its_singular_share_a_token() -> None:
    assert _singular("knowledge-source") == _singular("knowledge-source") == "knowledge-source"
    assert _singular("clusters") == "cluster"


def test_words_that_only_look_plural_are_left_alone() -> None:
    assert _singular("process") == "process"
    assert _singular("status") == "status"
    assert _singular("analysis") == "analysis"
    assert _singular("aws") == "aws"


def test_a_query_matches_the_component_id_in_either_form() -> None:
    assert set(_tokens("how knowledge-source works")) & set(_tokens("knowledge-source golden ami"))


def test_retrieval_is_wide_but_the_answer_gets_few() -> None:
    from app.models import Chunk, SourceType

    def chunk(index: int) -> Chunk:
        return Chunk(
            chunk_id=f"c{index}",
            document_id="d1",
            title=f"Doc {index}",
            text=f"cluster onboarding text {index}",
            source_type=SourceType.CONFLUENCE,
            source_location="s3://bucket/key.pdf",
            component_id="kip-service",
        )

    corpus = tuple(chunk(index) for index in range(40))
    asked: dict[str, int] = {}

    class Vectors:
        def query(self, embedding: tuple[float, ...], limit: int):
            asked["semantic"] = limit
            return tuple((item, 1.0) for item in corpus[:limit])

        def load_chunks(self) -> tuple[Chunk, ...]:
            return corpus

    class Embeddings:
        def create(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            return tuple((0.1, 0.2) for _ in texts)

    search = HybridSearch(Embeddings(), Vectors(), top_k=25)  # type: ignore[arg-type]
    search.replace_keyword_cache(corpus)

    results = search.search("cluster onboarding", 5)

    assert asked["semantic"] == 25
    assert len(results) == 5
    assert [r.source_id for r in results] == ["S1", "S2", "S3", "S4", "S5"]


def test_a_request_larger_than_top_k_is_honoured() -> None:
    from app.models import Chunk, SourceType

    corpus = tuple(
        Chunk(
            chunk_id=f"c{index}",
            document_id="d1",
            title="Doc",
            text="cluster text",
            source_type=SourceType.CONFLUENCE,
            source_location="s3://bucket/key.pdf",
            component_id="kip-service",
        )
        for index in range(10)
    )
    asked: dict[str, int] = {}

    class Vectors:
        def query(self, embedding: tuple[float, ...], limit: int):
            asked["semantic"] = limit
            return ()

        def load_chunks(self) -> tuple[Chunk, ...]:
            return corpus

    class Embeddings:
        def create(self, texts: tuple[str, ...]) -> tuple[tuple[float, ...], ...]:
            return tuple((0.1, 0.2) for _ in texts)

    search = HybridSearch(Embeddings(), Vectors(), top_k=3)  # type: ignore[arg-type]
    search.replace_keyword_cache(corpus)
    search.search("cluster", 8)

    assert asked["semantic"] == 8
