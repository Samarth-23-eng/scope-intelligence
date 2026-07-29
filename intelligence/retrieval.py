from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, replace
from threading import Lock
from typing import Any, Iterable
from urllib.parse import urlsplit

from qdrant_client.http import models

from config.settings import settings
from db.postgres import get_connection
from db.qdrant import COLLECTION_EVIDENCE_CHUNKS, get_client
from intelligence.foundation import DocumentStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RetrievalHit:
    chunk_id: int
    evidence_id: int | None
    document_id: int
    document_version_id: int
    source_url: str
    title: str | None
    source_type: str
    content: str
    published_at: Any
    collected_at: Any
    score: float
    retrieval_methods: tuple[str, ...]
    metadata: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "evidence_id": self.evidence_id,
            "document_id": self.document_id,
            "document_version_id": self.document_version_id,
            "source_url": self.source_url,
            "title": self.title,
            "source_type": self.source_type,
            "content": self.content,
            "published_at": self.published_at,
            "collected_at": self.collected_at,
            "score": self.score,
            "retrieval_methods": list(self.retrieval_methods),
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class EvidencePack:
    hits: tuple[RetrievalHit, ...]
    diagnostics: dict[str, Any]

    @property
    def prompt_text(self) -> str:
        return EvidenceRetriever.format_for_prompt(self.hits)


class ChunkIndexer:
    """Lazy local embeddings with resilient Qdrant indexing and cleanup."""

    _model_ready = False
    _model_lock = Lock()

    @classmethod
    def _prepare_model(cls) -> bool:
        if cls._model_ready:
            return True
        with cls._model_lock:
            if cls._model_ready:
                return True
            try:
                client = get_client()
                client.set_model(
                    settings.evidence_embedding_model,
                    cache_dir=settings.evidence_embedding_cache,
                )
                cls._model_ready = True
                return True
            except Exception as exc:
                logger.warning("Semantic evidence indexing unavailable: %s", exc)
                return False

    @staticmethod
    def _competitor_filter(competitor_id: int) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="competitor_id",
                    match=models.MatchValue(value=competitor_id),
                )
            ]
        )

    @classmethod
    def index_pending(cls, competitor_id: int, limit: int | None = None) -> dict[str, Any]:
        # Transformer memory grows quickly with both token count and batch size.
        # Keep this hard ceiling even if an operator configures a larger value so
        # indexing cannot take down the API on a modest local Docker allocation.
        batch_limit = min(max(limit or settings.evidence_index_batch_size, 1), 16)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chunk.id, chunk.content, chunk.document_version_id,
                           document.id AS document_id, document.canonical_url,
                           document.title, document.source_type,
                           document.published_at, document.metadata,
                           evidence.id AS evidence_id
                    FROM document_chunks chunk
                    JOIN document_versions version
                      ON version.id = chunk.document_version_id
                    JOIN documents document
                      ON document.id = version.document_id
                    LEFT JOIN LATERAL (
                        SELECT id
                        FROM evidence
                        WHERE document_version_id = version.id
                          AND competitor_id = %s
                        ORDER BY confidence DESC, collected_at DESC
                        LIMIT 1
                    ) evidence ON TRUE
                    WHERE chunk.competitor_id = %s
                      AND chunk.indexed_at IS NULL
                    ORDER BY chunk.id
                    LIMIT %s
                    """,
                    (competitor_id, competitor_id, batch_limit),
                )
                rows = cur.fetchall() or []
        if not rows:
            return {"indexed": 0, "pending": 0, "semantic": cls._model_ready}
        if not cls._prepare_model():
            return {
                "indexed": 0,
                "pending": len(rows),
                "semantic": False,
                "error": "embedding model unavailable",
            }

        client = get_client()
        documents = [row["content"] for row in rows]
        metadata = [
            {
                "competitor_id": competitor_id,
                "chunk_id": int(row["id"]),
                "document_id": int(row["document_id"]),
                "document_version_id": int(row["document_version_id"]),
                "evidence_id": int(row["evidence_id"]) if row.get("evidence_id") else None,
                "source_url": row["canonical_url"],
                "title": row.get("title"),
                "source_type": row["source_type"],
                "published_at": (
                    row["published_at"].isoformat() if row.get("published_at") else None
                ),
            }
            for row in rows
        ]
        ids = [int(row["id"]) for row in rows]
        try:
            inserted = client.add(
                collection_name=COLLECTION_EVIDENCE_CHUNKS,
                documents=documents,
                metadata=metadata,
                ids=ids,
                batch_size=batch_limit,
            )
            try:
                client.create_payload_index(
                    collection_name=COLLECTION_EVIDENCE_CHUNKS,
                    field_name="competitor_id",
                    field_schema=models.PayloadSchemaType.INTEGER,
                )
            except Exception:
                pass
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE document_chunks
                        SET qdrant_point_id = id::text, indexed_at = NOW()
                        WHERE competitor_id = %s AND id = ANY(%s)
                        """,
                        (competitor_id, ids),
                    )
                    conn.commit()
            return {"indexed": len(inserted), "pending": 0, "semantic": True}
        except Exception as exc:
            logger.warning("Failed to index evidence chunks for competitor %s: %s", competitor_id, exc)
            return {
                "indexed": 0,
                "pending": len(rows),
                "semantic": False,
                # Never return provider, filesystem, or stack details through
                # the public reindex endpoint. The complete diagnostic remains
                # available only in server logs.
                "error": "semantic indexing failed",
            }

    @classmethod
    def delete_competitor(cls, competitor_id: int) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS count FROM document_chunks WHERE competitor_id = %s",
                    (competitor_id,),
                )
                count = int(cur.fetchone()["count"])
        try:
            client = get_client()
            collections = {
                item.name for item in client.get_collections().collections
            }
            if COLLECTION_EVIDENCE_CHUNKS in collections:
                client.delete(
                    collection_name=COLLECTION_EVIDENCE_CHUNKS,
                    points_selector=models.FilterSelector(
                        filter=cls._competitor_filter(competitor_id)
                    ),
                    wait=True,
                )
        except Exception as exc:
            logger.warning(
                "Database data will be cleared, but Qdrant cleanup failed for %s: %s",
                competitor_id,
                exc,
            )
            return 0
        return count


class EvidenceRetriever:
    """Fuse semantic Qdrant retrieval with PostgreSQL lexical retrieval."""

    def __init__(self, competitor_id: int):
        self.competitor_id = competitor_id

    def prepare(self, backfill_limit: int = 500) -> dict[str, Any]:
        backfill = DocumentStore(self.competitor_id).backfill_evidence(backfill_limit)
        indexed_total = 0
        semantic = True
        error = None
        while True:
            result = ChunkIndexer.index_pending(self.competitor_id)
            indexed_total += int(result.get("indexed", 0))
            semantic = bool(result.get("semantic", False))
            error = result.get("error")
            if result.get("pending", 0) or result.get("indexed", 0) == 0:
                break
        return {
            **backfill,
            "chunks_indexed": indexed_total,
            "semantic": semantic,
            "error": error,
        }

    def search(
        self,
        query: str,
        limit: int | None = None,
        *,
        prepare: bool = True,
    ) -> list[RetrievalHit]:
        query = query.strip()
        result_limit = min(max(limit or settings.evidence_retrieval_limit, 1), 100)
        if prepare:
            self.prepare()

        vector_ranks: dict[int, int] = {}
        if query and ChunkIndexer._prepare_model():
            try:
                responses = get_client().query(
                    collection_name=COLLECTION_EVIDENCE_CHUNKS,
                    query_text=query,
                    query_filter=ChunkIndexer._competitor_filter(self.competitor_id),
                    limit=result_limit,
                )
                vector_ranks = {
                    int(response.id): rank
                    for rank, response in enumerate(responses, start=1)
                }
            except Exception as exc:
                logger.warning("Semantic evidence search failed: %s", exc)

        lexical_rows = self._lexical_search(query, result_limit)
        lexical_ranks = {
            int(row["chunk_id"]): rank
            for rank, row in enumerate(lexical_rows, start=1)
        }
        candidate_ids = list(dict.fromkeys(list(vector_ranks) + list(lexical_ranks)))
        if not candidate_ids:
            return []
        rows = self._load_chunks(candidate_ids)
        by_id = {int(row["chunk_id"]): row for row in rows}

        hits = []
        for chunk_id in candidate_ids:
            row = by_id.get(chunk_id)
            if not row:
                continue
            methods = []
            score = 0.0
            if chunk_id in vector_ranks:
                methods.append("semantic")
                score += 1.0 / (60 + vector_ranks[chunk_id])
            if chunk_id in lexical_ranks:
                methods.append("lexical")
                score += 1.0 / (60 + lexical_ranks[chunk_id])
            hits.append(
                RetrievalHit(
                    chunk_id=chunk_id,
                    evidence_id=(
                        int(row["evidence_id"]) if row.get("evidence_id") else None
                    ),
                    document_id=int(row["document_id"]),
                    document_version_id=int(row["document_version_id"]),
                    source_url=row["canonical_url"],
                    title=row.get("title"),
                    source_type=row["source_type"],
                    content=row["content"],
                    published_at=row.get("published_at"),
                    collected_at=row.get("collected_at"),
                    score=round(score, 8),
                    retrieval_methods=tuple(methods),
                    metadata=row.get("metadata") or {},
                )
            )
        return sorted(hits, key=lambda item: item.score, reverse=True)[:result_limit]

    def build_pack(
        self,
        queries: Iterable[str],
        *,
        max_hits: int | None = None,
        max_chars: int | None = None,
        per_query: int | None = None,
        max_per_document: int | None = None,
        max_per_domain: int | None = None,
        include_recent_fallback: bool = True,
        require_evidence_ids: bool = False,
    ) -> EvidencePack:
        """Build a deduplicated, query-fused and source-diverse evidence pack."""
        normalized_queries = list(
            dict.fromkeys(
                query.strip()
                for query in queries
                if isinstance(query, str) and query.strip()
            )
        )[:10]
        hit_limit = min(
            max(max_hits or settings.analysis_evidence_pack_max_hits, 1),
            100,
        )
        character_limit = max(
            max_chars or settings.analysis_evidence_pack_max_chars,
            1000,
        )
        query_limit = min(
            max(per_query or settings.analysis_evidence_pack_per_query, 1),
            50,
        )
        document_limit = max(
            max_per_document or settings.analysis_evidence_pack_max_per_document,
            1,
        )
        domain_limit = max(
            max_per_domain or settings.analysis_evidence_pack_max_per_domain,
            1,
        )

        self.prepare()
        candidates: dict[int, RetrievalHit] = {}
        fused_scores: dict[int, float] = {}
        matched_queries: dict[int, list[str]] = {}
        query_counts: dict[str, int] = {}
        for query in normalized_queries:
            results = self.search(query, query_limit, prepare=False)
            query_counts[query] = len(results)
            for rank, hit in enumerate(results, start=1):
                if require_evidence_ids and hit.evidence_id is None:
                    continue
                candidates.setdefault(hit.chunk_id, hit)
                fused_scores[hit.chunk_id] = (
                    fused_scores.get(hit.chunk_id, 0.0)
                    + 1.0 / (60 + rank)
                )
                matched_queries.setdefault(hit.chunk_id, []).append(query)

        used_recent_fallback = False
        if not candidates and include_recent_fallback:
            used_recent_fallback = True
            recent = self.search("", query_limit, prepare=False)
            query_counts["__recent__"] = len(recent)
            for rank, hit in enumerate(recent, start=1):
                if require_evidence_ids and hit.evidence_id is None:
                    continue
                candidates.setdefault(hit.chunk_id, hit)
                fused_scores[hit.chunk_id] = 1.0 / (60 + rank)
                matched_queries.setdefault(hit.chunk_id, []).append("__recent__")

        ranked = []
        for chunk_id, hit in candidates.items():
            ranked.append(
                replace(
                    hit,
                    score=round(fused_scores.get(chunk_id, hit.score), 8),
                    metadata={
                        **hit.metadata,
                        "matched_queries": matched_queries.get(chunk_id, []),
                    },
                )
            )
        ranked.sort(
            key=lambda item: (
                item.score,
                len(item.metadata.get("matched_queries", [])),
                item.chunk_id,
            ),
            reverse=True,
        )

        selected: list[RetrievalHit] = []
        document_counts: dict[int, int] = {}
        domain_counts: dict[str, int] = {}
        content_hashes: set[str] = set()
        prompt_chars = 0
        excluded = {
            "duplicate_content": 0,
            "document_limit": 0,
            "domain_limit": 0,
            "prompt_budget": 0,
            "hit_limit": 0,
        }
        for hit in ranked:
            if len(selected) >= hit_limit:
                excluded["hit_limit"] += 1
                continue
            content_key = hashlib.sha256(
                " ".join(hit.content.casefold().split()).encode("utf-8")
            ).hexdigest()
            if content_key in content_hashes:
                excluded["duplicate_content"] += 1
                continue
            if document_counts.get(hit.document_id, 0) >= document_limit:
                excluded["document_limit"] += 1
                continue
            domain = (urlsplit(hit.source_url).hostname or "unknown").casefold()
            if domain_counts.get(domain, 0) >= domain_limit:
                excluded["domain_limit"] += 1
                continue
            rendered = self.format_for_prompt((hit,))
            added_chars = len(rendered) + (2 if selected else 0)
            if prompt_chars + added_chars > character_limit:
                excluded["prompt_budget"] += 1
                continue
            selected.append(hit)
            prompt_chars += added_chars
            content_hashes.add(content_key)
            document_counts[hit.document_id] = document_counts.get(hit.document_id, 0) + 1
            domain_counts[domain] = domain_counts.get(domain, 0) + 1

        diagnostics = {
            "queries": normalized_queries,
            "query_result_counts": query_counts,
            "candidate_chunks": len(ranked),
            "selected_chunks": len(selected),
            "selected_documents": len(document_counts),
            "selected_domains": len(domain_counts),
            "selected_source_types": len({hit.source_type for hit in selected}),
            "prompt_chars": prompt_chars,
            "prompt_char_budget": character_limit,
            "used_recent_fallback": used_recent_fallback,
            "excluded": excluded,
        }
        return EvidencePack(hits=tuple(selected), diagnostics=diagnostics)

    def _lexical_search(self, query: str, limit: int) -> list[dict[str, Any]]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if query:
                    cur.execute(
                        """
                        SELECT chunk.id AS chunk_id,
                               ts_rank_cd(
                                   to_tsvector('english', chunk.content),
                                   websearch_to_tsquery('english', %s)
                               ) AS rank
                        FROM document_chunks chunk
                        WHERE chunk.competitor_id = %s
                          AND to_tsvector('english', chunk.content)
                              @@ websearch_to_tsquery('english', %s)
                        ORDER BY rank DESC, chunk.id DESC
                        LIMIT %s
                        """,
                        (query, self.competitor_id, query, limit),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id AS chunk_id, 0.0 AS rank
                        FROM document_chunks
                        WHERE competitor_id = %s
                        ORDER BY created_at DESC
                        LIMIT %s
                        """,
                        (self.competitor_id, limit),
                    )
                return cur.fetchall() or []

    def _load_chunks(self, chunk_ids: Iterable[int]) -> list[dict[str, Any]]:
        ids = list(chunk_ids)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT chunk.id AS chunk_id, chunk.content,
                           chunk.document_version_id, document.id AS document_id,
                           document.canonical_url, document.title,
                           document.source_type, document.published_at,
                           document.metadata,
                           evidence.id AS evidence_id,
                           evidence.collected_at
                    FROM document_chunks chunk
                    JOIN document_versions version
                      ON version.id = chunk.document_version_id
                    JOIN documents document
                      ON document.id = version.document_id
                    LEFT JOIN LATERAL (
                        SELECT id, collected_at
                        FROM evidence
                        WHERE document_version_id = version.id
                          AND competitor_id = %s
                        ORDER BY confidence DESC, collected_at DESC
                        LIMIT 1
                    ) evidence ON TRUE
                    WHERE chunk.competitor_id = %s
                      AND chunk.id = ANY(%s)
                    """,
                    (self.competitor_id, self.competitor_id, ids),
                )
                return cur.fetchall() or []

    @staticmethod
    def format_for_prompt(hits: Iterable[RetrievalHit]) -> str:
        blocks = []
        for hit in hits:
            citation = (
                f"EVIDENCE_ID: {hit.evidence_id}"
                if hit.evidence_id is not None
                else f"CHUNK_ID: {hit.chunk_id}"
            )
            blocks.append(
                "\n".join(
                    (
                        citation,
                        f"CHUNK_ID: {hit.chunk_id}",
                        f"URL: {hit.source_url}",
                        f"TITLE: {hit.title or ''}",
                        f"SOURCE_TYPE: {hit.source_type}",
                        f"TEXT: {hit.content}",
                    )
                )
            )
        return "\n\n".join(blocks)
