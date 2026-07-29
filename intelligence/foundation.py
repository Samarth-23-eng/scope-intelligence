from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Callable, Iterable, TypeVar
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from psycopg2.extras import Json

from config.settings import settings
from db.postgres import get_connection

logger = logging.getLogger(__name__)
T = TypeVar("T")

TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
}


class PipelineCancelled(RuntimeError):
    """Raised between durable tasks when cancellation has been requested."""


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    return str(value)


def parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


@dataclass(frozen=True)
class DocumentIngestResult:
    document_id: int
    version_id: int
    created_version: bool
    chunk_ids: tuple[int, ...]


@dataclass(frozen=True)
class TextBudgetResult:
    text: str
    original_bytes: int
    stored_bytes: int
    truncated: bool


def apply_text_byte_budget(value: str, max_bytes: int) -> TextBudgetResult:
    """Bound stored text by an explicit byte budget without splitting UTF-8."""
    text = value or ""
    encoded = text.encode("utf-8")
    limit = max(int(max_bytes), 1)
    if len(encoded) <= limit:
        return TextBudgetResult(
            text=text,
            original_bytes=len(encoded),
            stored_bytes=len(encoded),
            truncated=False,
        )
    bounded = encoded[:limit].decode("utf-8", errors="ignore")
    return TextBudgetResult(
        text=bounded,
        original_bytes=len(encoded),
        stored_bytes=len(bounded.encode("utf-8")),
        truncated=True,
    )


class RunTracker:
    """Persist run/task state and execute idempotent tasks with bounded retries."""

    def __init__(self, run_id: int | None = None):
        self.run_id = run_id

    def create_run(
        self,
        competitor_id: int,
        *,
        run_type: str = "full",
        trigger_type: str = "manual",
        model: str | None = None,
        configuration: dict[str, Any] | None = None,
        parent_run_id: int | None = None,
    ) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_runs (
                        competitor_id, parent_run_id, run_type, trigger_type,
                        status, model, configuration
                    )
                    VALUES (%s, %s, %s, %s, 'queued', %s, %s)
                    RETURNING id
                    """,
                    (
                        competitor_id,
                        parent_run_id,
                        run_type,
                        trigger_type,
                        model,
                        Json(json_safe(configuration or {})),
                    ),
                )
                self.run_id = int(cur.fetchone()["id"])
                conn.commit()
        return self.run_id

    def start_run(self) -> None:
        if self.run_id is None:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = 'running',
                        started_at = COALESCE(started_at, NOW()),
                        error = NULL
                    WHERE id = %s AND status IN ('queued', 'running')
                    """,
                    (self.run_id,),
                )
                conn.commit()

    def finish_run(
        self,
        status: str,
        *,
        summary: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        if self.run_id is None:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pipeline_runs
                    SET status = %s,
                        summary = %s,
                        error = %s,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        status,
                        Json(json_safe(summary or {})),
                        error[:10000] if error else None,
                        self.run_id,
                    ),
                )
                conn.commit()

    def is_cancel_requested(self) -> bool:
        if self.run_id is None:
            return False
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT cancel_requested_at IS NOT NULL AS requested,
                           status
                    FROM pipeline_runs
                    WHERE id = %s
                    """,
                    (self.run_id,),
                )
                row = cur.fetchone()
        return bool(row and (row["requested"] or row["status"] == "cancelled"))

    def check_cancelled(self) -> None:
        if self.is_cancel_requested():
            raise PipelineCancelled("Pipeline cancellation requested")

    def execute(
        self,
        *,
        task_key: str,
        stage: str,
        agent_name: str,
        operation: Callable[[], T],
        max_attempts: int = 2,
        input_data: dict[str, Any] | None = None,
    ) -> T:
        if self.run_id is None:
            return operation()

        self.check_cancelled()
        last_error: Exception | None = None
        for _ in range(max(max_attempts, 1)):
            task_id, attempt = self._start_task(
                task_key=task_key,
                stage=stage,
                agent_name=agent_name,
                max_attempts=max_attempts,
                input_data=input_data,
            )
            started = time.perf_counter()
            try:
                result = operation()
                self._finish_task(
                    task_id,
                    status="completed",
                    output=result,
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                return result
            except PipelineCancelled:
                self._finish_task(task_id, status="cancelled")
                raise
            except Exception as exc:
                last_error = exc
                final = attempt >= max(max_attempts, 1)
                self._finish_task(
                    task_id,
                    status="failed" if final else "retrying",
                    error=str(exc),
                    latency_ms=int((time.perf_counter() - started) * 1000),
                )
                if final:
                    raise
                logger.warning(
                    "Retrying pipeline task %s after attempt %s: %s",
                    task_key,
                    attempt,
                    exc,
                )
        if last_error:
            raise last_error
        raise RuntimeError(f"Task {task_key} did not execute")

    def _start_task(
        self,
        *,
        task_key: str,
        stage: str,
        agent_name: str,
        max_attempts: int,
        input_data: dict[str, Any] | None,
    ) -> tuple[int, int]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO pipeline_tasks (
                        run_id, task_key, stage, agent_name, status, attempt,
                        max_attempts, input, started_at, heartbeat_at
                    )
                    VALUES (%s, %s, %s, %s, 'running', 1, %s, %s, NOW(), NOW())
                    ON CONFLICT (run_id, task_key)
                    DO UPDATE SET
                        status = 'running',
                        attempt = pipeline_tasks.attempt + 1,
                        max_attempts = EXCLUDED.max_attempts,
                        input = EXCLUDED.input,
                        output = '{}'::jsonb,
                        error = NULL,
                        started_at = NOW(),
                        completed_at = NULL,
                        heartbeat_at = NOW()
                    RETURNING id, attempt
                    """,
                    (
                        self.run_id,
                        task_key[:160],
                        stage[:60],
                        agent_name[:120],
                        max(max_attempts, 1),
                        Json(json_safe(input_data or {})),
                    ),
                )
                row = cur.fetchone()
                conn.commit()
        return int(row["id"]), int(row["attempt"])

    @staticmethod
    def _finish_task(
        task_id: int,
        *,
        status: str,
        output: Any = None,
        error: str | None = None,
        latency_ms: int | None = None,
    ) -> None:
        payload = json_safe(output)
        if not isinstance(payload, dict):
            payload = {"result": payload}
        if latency_ms is not None:
            payload["_latency_ms"] = latency_ms
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE pipeline_tasks
                    SET status = %s,
                        output = %s,
                        error = %s,
                        heartbeat_at = NOW(),
                        completed_at = CASE
                            WHEN %s IN ('completed', 'failed', 'skipped', 'cancelled')
                            THEN NOW()
                            ELSE NULL
                        END
                    WHERE id = %s
                    """,
                    (
                        status,
                        Json(payload),
                        error[:10000] if error else None,
                        status,
                        task_id,
                    ),
                )
                conn.commit()

    @staticmethod
    def request_cancel(run_id: int, competitor_id: int | None = None) -> bool:
        params: list[Any] = [run_id]
        condition = "id = %s"
        if competitor_id is not None:
            condition += " AND competitor_id = %s"
            params.append(competitor_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    UPDATE pipeline_runs
                    SET cancel_requested_at = NOW(),
                        status = CASE WHEN status = 'queued' THEN 'cancelled' ELSE status END,
                        completed_at = CASE WHEN status = 'queued' THEN NOW() ELSE completed_at END
                    WHERE {condition}
                      AND status IN ('queued', 'running')
                    """,
                    tuple(params),
                )
                changed = cur.rowcount > 0
                conn.commit()
        return changed


class DocumentStore:
    """Create canonical, versioned documents and deterministic retrieval chunks."""

    def __init__(self, competitor_id: int):
        self.competitor_id = competitor_id

    @staticmethod
    def canonicalize_url(url: str) -> str:
        value = (url or "").strip()
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return value
        host = (parsed.hostname or "").casefold()
        port = parsed.port
        netloc = host
        if port and not (
            (parsed.scheme == "http" and port == 80)
            or (parsed.scheme == "https" and port == 443)
        ):
            netloc = f"{host}:{port}"
        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        if path != "/":
            path = path.rstrip("/")
        query = [
            (key, item)
            for key, item in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in TRACKING_QUERY_KEYS
        ]
        return urlunsplit(
            (parsed.scheme.casefold(), netloc, path, urlencode(sorted(query)), "")
        )

    @staticmethod
    def normalize_text(content: str) -> str:
        paragraphs = []
        for block in re.split(r"\n\s*\n", content.replace("\r\n", "\n")):
            cleaned = re.sub(r"[ \t]+", " ", block)
            cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
            if cleaned:
                paragraphs.append(cleaned)
        return "\n\n".join(paragraphs)

    @classmethod
    def chunk_text(
        cls,
        content: str,
        *,
        max_chars: int = 2400,
        overlap_chars: int = 280,
    ) -> list[tuple[int, int, str]]:
        text = cls.normalize_text(content)
        if not text:
            return []
        chunks: list[tuple[int, int, str]] = []
        start = 0
        while start < len(text):
            end = min(start + max_chars, len(text))
            if end < len(text):
                window = text[start:end]
                minimum = int(max_chars * 0.55)
                boundaries = [
                    window.rfind("\n\n", minimum),
                    window.rfind(". ", minimum),
                    window.rfind("? ", minimum),
                    window.rfind("! ", minimum),
                    window.rfind(" ", minimum),
                ]
                boundary = max(boundaries)
                if boundary > 0:
                    end = start + boundary + 1
            chunk = text[start:end].strip()
            if chunk:
                chunk_start = text.find(chunk, start, end + 1)
                chunk_start = start if chunk_start < 0 else chunk_start
                chunks.append((chunk_start, chunk_start + len(chunk), chunk))
            if end >= len(text):
                break
            start = max(end - overlap_chars, start + 1)
        return chunks

    def ingest(
        self,
        *,
        source_url: str,
        title: str | None,
        content: str,
        source_type: str,
        source_name: str | None = None,
        media_type: str = "text/plain",
        language: str | None = None,
        author: str | None = None,
        published_at: datetime | str | None = None,
        extraction_method: str = "legacy",
        metadata: dict[str, Any] | None = None,
        raw_text: str | None = None,
    ) -> DocumentIngestResult | None:
        budgeted = apply_text_byte_budget(
            content,
            settings.crawler_max_document_bytes,
        )
        normalized = self.normalize_text(budgeted.text)
        if not normalized:
            return None
        canonical_url = self.canonicalize_url(source_url)
        canonical_key = hashlib.sha256(
            f"{canonical_url}\0{source_type}".encode("utf-8")
        ).hexdigest()
        content_hash = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        supplied_metadata = metadata or {}
        safe_metadata = json_safe(
            {
                **supplied_metadata,
                "content_budget": supplied_metadata.get("content_budget")
                or {
                    "limit_bytes": settings.crawler_max_document_bytes,
                    "original_bytes": budgeted.original_bytes,
                    "stored_bytes": budgeted.stored_bytes,
                    "truncated": budgeted.truncated,
                },
            }
        )
        raw_budgeted = (
            apply_text_byte_budget(
                raw_text,
                settings.crawler_max_document_bytes,
            )
            if raw_text is not None
            else None
        )
        publication_time = parse_timestamp(published_at)
        chunks = self.chunk_text(
            normalized,
            max_chars=max(settings.evidence_chunk_chars, 400),
            overlap_chars=max(
                min(settings.evidence_chunk_overlap_chars, settings.evidence_chunk_chars // 2),
                0,
            ),
        )

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO documents (
                        competitor_id, canonical_key, canonical_url, source_type,
                        source_name, media_type, language, title, author,
                        published_at, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (competitor_id, canonical_key)
                    DO UPDATE SET
                        source_name = COALESCE(EXCLUDED.source_name, documents.source_name),
                        media_type = EXCLUDED.media_type,
                        language = COALESCE(EXCLUDED.language, documents.language),
                        title = COALESCE(EXCLUDED.title, documents.title),
                        author = COALESCE(EXCLUDED.author, documents.author),
                        published_at = COALESCE(EXCLUDED.published_at, documents.published_at),
                        metadata = documents.metadata || EXCLUDED.metadata,
                        last_seen_at = NOW()
                    RETURNING id
                    """,
                    (
                        self.competitor_id,
                        canonical_key,
                        canonical_url[:2048],
                        source_type[:100],
                        source_name[:255] if source_name else None,
                        media_type[:255],
                        language[:20] if language else None,
                        title[:1000] if title else None,
                        author[:500] if author else None,
                        publication_time,
                        Json(safe_metadata),
                    ),
                )
                document_id = int(cur.fetchone()["id"])
                cur.execute(
                    """
                    INSERT INTO document_versions (
                        document_id, content_hash, normalized_text, raw_text,
                        byte_size, extraction_method, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (document_id, content_hash) DO NOTHING
                    RETURNING id
                    """,
                    (
                        document_id,
                        content_hash,
                        normalized,
                        raw_budgeted.text if raw_budgeted else None,
                        (
                            raw_budgeted.stored_bytes
                            if raw_budgeted
                            else len(normalized.encode("utf-8"))
                        ),
                        extraction_method[:100],
                        Json(safe_metadata),
                    ),
                )
                version_row = cur.fetchone()
                created_version = bool(version_row)
                if version_row:
                    version_id = int(version_row["id"])
                    chunk_ids = []
                    for chunk_index, (start_char, end_char, chunk) in enumerate(chunks):
                        cur.execute(
                            """
                            INSERT INTO document_chunks (
                                competitor_id, document_version_id, chunk_index,
                                content, content_hash, start_char, end_char,
                                token_count, metadata
                            )
                            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            RETURNING id
                            """,
                            (
                                self.competitor_id,
                                version_id,
                                chunk_index,
                                chunk,
                                hashlib.sha256(chunk.encode("utf-8")).hexdigest(),
                                start_char,
                                end_char,
                                max(1, len(chunk) // 4),
                                Json({"source_type": source_type}),
                            ),
                        )
                        chunk_ids.append(int(cur.fetchone()["id"]))
                    cur.execute(
                        "UPDATE documents SET current_version_id = %s WHERE id = %s",
                        (version_id, document_id),
                    )
                else:
                    cur.execute(
                        """
                        SELECT id
                        FROM document_versions
                        WHERE document_id = %s AND content_hash = %s
                        """,
                        (document_id, content_hash),
                    )
                    version_id = int(cur.fetchone()["id"])
                    cur.execute(
                        """
                        SELECT id
                        FROM document_chunks
                        WHERE document_version_id = %s
                        ORDER BY chunk_index
                        """,
                        (version_id,),
                    )
                    chunk_ids = [int(row["id"]) for row in cur.fetchall()]
                conn.commit()
        return DocumentIngestResult(
            document_id=document_id,
            version_id=version_id,
            created_version=created_version,
            chunk_ids=tuple(chunk_ids),
        )

    def backfill_evidence(self, limit: int = 500) -> dict[str, int]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, source_url, title, full_text, snippet, metadata
                    FROM evidence
                    WHERE competitor_id = %s
                      AND document_version_id IS NULL
                    ORDER BY collected_at
                    LIMIT %s
                    """,
                    (self.competitor_id, max(limit, 1)),
                )
                rows = cur.fetchall() or []

        linked = 0
        versions = 0
        for row in rows:
            metadata = row.get("metadata") or {}
            result = self.ingest(
                source_url=row["source_url"],
                title=row.get("title"),
                content=row.get("full_text") or row.get("snippet") or "",
                source_type=str(
                    metadata.get("source_type")
                    or metadata.get("kind")
                    or "legacy_evidence"
                ),
                source_name=metadata.get("publisher"),
                media_type=str(metadata.get("content_type") or "text/plain"),
                published_at=metadata.get("published_at"),
                extraction_method=str(metadata.get("engine") or "legacy_backfill"),
                metadata=metadata,
            )
            if not result:
                continue
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        UPDATE evidence
                        SET document_version_id = %s
                        WHERE id = %s AND competitor_id = %s
                        """,
                        (result.version_id, row["id"], self.competitor_id),
                    )
                    conn.commit()
            linked += 1
            versions += int(result.created_version)
        return {"evidence_linked": linked, "versions_created": versions}


class ClaimStore:
    """Persist evidence-bound claims and validate every citation."""

    def __init__(self, competitor_id: int, run_id: int | None = None):
        self.competitor_id = competitor_id
        self.run_id = run_id

    def create(
        self,
        *,
        statement: str,
        claim_type: str,
        evidence_ids: Iterable[int] = (),
        chunk_ids: Iterable[int] = (),
        confidence: float = 0.5,
        status: str = "supported",
        subject: str | None = None,
        predicate: str | None = None,
        object_text: str | None = None,
        occurred_at: datetime | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        statement = statement.strip()
        if not statement:
            return None
        requested_evidence = list(dict.fromkeys(int(item) for item in evidence_ids))
        requested_chunks = list(dict.fromkeys(int(item) for item in chunk_ids))
        with get_connection() as conn:
            with conn.cursor() as cur:
                valid_evidence: list[dict[str, Any]] = []
                if requested_evidence:
                    cur.execute(
                        """
                        SELECT id, COALESCE(snippet, full_text, '') AS excerpt, confidence
                        FROM evidence
                        WHERE competitor_id = %s AND id = ANY(%s)
                        """,
                        (self.competitor_id, requested_evidence),
                    )
                    valid_evidence = cur.fetchall() or []
                valid_chunks: list[dict[str, Any]] = []
                if requested_chunks:
                    cur.execute(
                        """
                        SELECT id, content AS excerpt
                        FROM document_chunks
                        WHERE competitor_id = %s AND id = ANY(%s)
                        """,
                        (self.competitor_id, requested_chunks),
                    )
                    valid_chunks = cur.fetchall() or []
                # "Proposed" describes a forecast's lifecycle, not permission to
                # omit provenance. Every persisted claim must still be grounded
                # in evidence that belongs to this competitor.
                if not valid_evidence and not valid_chunks:
                    logger.warning("Rejected uncited %s claim: %s", claim_type, statement[:120])
                    return None

                cur.execute(
                    """
                    INSERT INTO claims (
                        competitor_id, pipeline_run_id, claim_type, subject,
                        predicate, object_text, statement, confidence, status,
                        occurred_at, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        self.competitor_id,
                        self.run_id,
                        claim_type[:100],
                        subject[:1000] if subject else None,
                        predicate[:255] if predicate else None,
                        object_text,
                        statement,
                        min(max(float(confidence), 0.0), 1.0),
                        status,
                        parse_timestamp(occurred_at),
                        Json(json_safe(metadata or {})),
                    ),
                )
                claim_id = int(cur.fetchone()["id"])
                for evidence in valid_evidence:
                    cur.execute(
                        """
                        INSERT INTO claim_evidence (
                            claim_id, evidence_id, stance, excerpt, confidence
                        )
                        VALUES (%s, %s, 'supports', %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (
                            claim_id,
                            evidence["id"],
                            (evidence.get("excerpt") or "")[:1500],
                            float(evidence.get("confidence") or 0.5),
                        ),
                    )
                for chunk in valid_chunks:
                    cur.execute(
                        """
                        INSERT INTO claim_evidence (
                            claim_id, document_chunk_id, stance, excerpt, confidence
                        )
                        VALUES (%s, %s, 'supports', %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (claim_id, chunk["id"], (chunk.get("excerpt") or "")[:1500], 0.7),
                    )
                conn.commit()
        return claim_id


class SourceHealthStore:
    @staticmethod
    def record(
        competitor_id: int,
        *,
        adapter_name: str,
        source_key: str,
        success: bool,
        items: int = 0,
        latency_ms: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        disabled: bool = False,
    ) -> None:
        source_hash = hashlib.sha256(source_key.encode("utf-8")).hexdigest()
        if disabled:
            status = "disabled"
        elif success:
            status = "healthy"
        else:
            status = "error"
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO source_health (
                        competitor_id, adapter_name, source_key, source_key_hash,
                        status, consecutive_failures, total_attempts, total_items,
                        last_latency_ms, last_error, last_attempt_at,
                        last_success_at, metadata
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, 1, %s, %s, %s, NOW(),
                        CASE WHEN %s THEN NOW() ELSE NULL END, %s
                    )
                    ON CONFLICT (competitor_id, adapter_name, source_key_hash)
                    DO UPDATE SET
                        source_key = EXCLUDED.source_key,
                        status = EXCLUDED.status,
                        consecutive_failures = CASE
                            WHEN %s THEN 0
                            ELSE source_health.consecutive_failures + 1
                        END,
                        total_attempts = source_health.total_attempts + 1,
                        total_items = source_health.total_items + EXCLUDED.total_items,
                        last_latency_ms = EXCLUDED.last_latency_ms,
                        last_error = EXCLUDED.last_error,
                        last_attempt_at = NOW(),
                        last_success_at = CASE
                            WHEN %s THEN NOW()
                            ELSE source_health.last_success_at
                        END,
                        metadata = source_health.metadata || EXCLUDED.metadata
                    """,
                    (
                        competitor_id,
                        adapter_name[:120],
                        source_key[:2048],
                        source_hash,
                        status,
                        0 if success else 1,
                        max(items, 0),
                        latency_ms,
                        error[:5000] if error else None,
                        success,
                        Json(json_safe(metadata or {})),
                        success,
                        success,
                    ),
                )
                conn.commit()
