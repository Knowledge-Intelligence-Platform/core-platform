"""Hybrid keyword and S3 Vector search."""

import logging
import math
import re
from collections import Counter
from threading import RLock
from time import monotonic

from app.embeddings import Embeddings, EmbeddingUnavailableError
from app.models import UNMAPPED_COMPONENT_ID, Chunk, SearchResult
from app.vector_store import VectorStore

LOGGER = logging.getLogger(__name__)

STOP_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "for",
        "from",
        "how",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "what",
        "when",
        "where",
        "which",
        "with",
    }
)


class HybridSearch:
    def __init__(
        self,
        embeddings: Embeddings,
        vectors: VectorStore,
        top_k: int,
        per_document: int = 3,
    ) -> None:
        self.embeddings = embeddings
        self.vectors = vectors
        self.top_k = top_k
        self.per_document = max(1, per_document)
        self._chunks_by_id: dict[str, Chunk] = {}
        self._postings: dict[str, tuple[tuple[str, float], ...]] = {}
        self._lock = RLock()

    def cached_chunks(self) -> tuple[Chunk, ...]:
        with self._lock:
            return tuple(self._chunks_by_id.values())

    @property
    def cached_chunk_count(self) -> int:
        with self._lock:
            return len(self._chunks_by_id)

    def replace_keyword_cache(self, chunks: tuple[Chunk, ...]) -> None:
        """Build an inverted index so a query only visits chunks that match it."""
        postings: dict[str, list[tuple[str, float]]] = {}
        for chunk in chunks:
            counts = Counter(_tokens(_searchable(chunk)))
            total = counts.total()
            if not total:
                continue
            for term, count in counts.items():
                postings.setdefault(term, []).append((chunk.chunk_id, count / total))
        with self._lock:
            self._chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
            self._postings = {term: tuple(entries) for term, entries in postings.items()}

    def search(self, query: str, limit: int) -> tuple[SearchResult, ...]:
        normalized = query.strip()
        if not normalized:
            return ()
        self._restore_keyword_cache_if_empty()
        returned = max(limit, 1)
        candidates = max(returned, self.top_k)
        started = monotonic()
        try:
            semantic = self._semantic(normalized, candidates)
        except (EmbeddingUnavailableError, RuntimeError):
            LOGGER.exception(
                "Semantic search unavailable; continuing with keyword search.",
                extra={"operation": "semantic_search", "component": "search"},
            )
            semantic = ()
        semantic_ms = (monotonic() - started) * 1_000
        keyword_started = monotonic()
        keyword = self._keyword(normalized, candidates)
        ranked = self._reciprocal_rank_fusion(semantic, keyword, returned, self.per_document)
        LOGGER.info(
            "Knowledge search completed.",
            extra={
                "operation": "hybrid_search",
                "component": "search",
                "duration_ms": round((monotonic() - started) * 1_000, 2),
                "semantic_ms": round(semantic_ms, 2),
                "keyword_ms": round((monotonic() - keyword_started) * 1_000, 2),
                "candidates": candidates,
                "semantic_hits": len(semantic),
                "keyword_hits": len(keyword),
                "returned": len(ranked),
            },
        )
        return tuple(
            SearchResult(source_id=f"S{index}", chunk=chunk, score=score)
            for index, (chunk, score) in enumerate(ranked, start=1)
        )

    def _restore_keyword_cache_if_empty(self) -> None:
        with self._lock:
            if self._chunks_by_id:
                return
        try:
            chunks = self.vectors.load_chunks()
        except RuntimeError:
            LOGGER.exception(
                "Keyword search cache could not be restored during a query.",
                extra={"operation": "restore_keyword_cache", "component": "search"},
            )
            return
        if chunks:
            self.replace_keyword_cache(chunks)

    def _semantic(self, query: str, limit: int) -> tuple[tuple[Chunk, float], ...]:
        vector = self.embeddings.create((query,))[0]
        return self.vectors.query(vector, limit)

    def _keyword(self, query: str, limit: int) -> tuple[tuple[Chunk, float], ...]:
        terms = tuple(dict.fromkeys(_tokens(query)))
        with self._lock:
            postings = self._postings
            by_id = self._chunks_by_id
        if not terms or not by_id:
            return ()
        total_chunks = len(by_id)
        scores: dict[str, float] = {}
        for term in terms:
            entries = postings.get(term)
            if not entries:
                continue
            weight = math.log((total_chunks + 1) / (len(entries) + 1)) + 1
            for chunk_id, frequency in entries:
                scores[chunk_id] = scores.get(chunk_id, 0.0) + frequency * weight
        return tuple(
            (by_id[chunk_id], scores[chunk_id])
            for chunk_id in sorted(scores, key=lambda item: (-scores[item], item))[
                :limit
            ]
        )

    @staticmethod
    def _reciprocal_rank_fusion(
        semantic: tuple[tuple[Chunk, float], ...],
        keyword: tuple[tuple[Chunk, float], ...],
        limit: int,
        per_document: int = 3,
    ) -> tuple[tuple[Chunk, float], ...]:
        """Fuse both rankings, then stop any one document filling every slot.

        A long document usually holds the best chunk *and* the next several, which
        crowds out the document that answers the rest of the question. Chunks
        beyond the per-document cap are held back and only used to top up.
        """
        scores: dict[str, float] = {}
        chunks: dict[str, Chunk] = {}
        for ranking in (semantic, keyword):
            for rank, (chunk, _) in enumerate(ranking, start=1):
                chunks[chunk.chunk_id] = chunk
                scores[chunk.chunk_id] = scores.get(chunk.chunk_id, 0.0) + 1 / (
                    60 + rank
                )
        ordered = sorted(scores, key=lambda item: (-scores[item], item))
        selected: list[str] = []
        overflow: list[str] = []
        taken: Counter[str] = Counter()
        for chunk_id in ordered:
            document = chunks[chunk_id].document_id
            if taken[document] >= per_document:
                overflow.append(chunk_id)
                continue
            taken[document] += 1
            selected.append(chunk_id)
            if len(selected) == limit:
                break
        for chunk_id in overflow:
            if len(selected) >= limit:
                break
            selected.append(chunk_id)
        return tuple((chunks[chunk_id], scores[chunk_id]) for chunk_id in selected[:limit])


def _singular(term: str) -> str:
    """Fold a simple plural so `knowledge-source` and `knowledge-source` share a posting list."""
    if len(term) > 4 and term.endswith("s") and not term.endswith(("ss", "us", "is")):
        return term[:-1]
    return term


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(
        _singular(term)
        for term in re.findall(r"[a-zA-Z0-9][a-zA-Z0-9_.:/-]*", text.casefold())
        if term not in STOP_WORDS and len(term) > 1
    )


def _searchable(chunk: Chunk) -> str:
    """Indexed text. The unmapped placeholder is an owner, not a keyword."""
    return "\n".join(
        value
        for value in (
            chunk.title,
            "" if chunk.component_id == UNMAPPED_COMPONENT_ID else chunk.component_id,
            " ".join(chunk.heading_path),
            chunk.text,
        )
        if value
    )
