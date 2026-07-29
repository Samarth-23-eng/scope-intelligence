import hashlib
import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from db.postgres import get_connection
from psycopg2.extras import Json
from db.redis_client import get_last_seen, set_last_seen
from config.settings import settings
from intelligence.foundation import (
    DocumentStore,
    apply_text_byte_budget,
    json_safe,
)
from intelligence.sources import SourceAdapter

logger = logging.getLogger(__name__)


class BaseIngestionAgent(SourceAdapter, ABC):
    """Base class for all ingestion agents."""

    def __init__(self, competitor_id: int, competitor_name: str, domain: str):
        self.competitor_id = competitor_id
        self.competitor_name = competitor_name
        self.domain = domain
        self.run_id: int | None = None

    @abstractmethod
    async def collect(self) -> List[Dict[str, Any]]:
        """Collect raw data from the source. Returns list of structured dicts."""
        pass

    def _hash_content(self, content: str) -> str:
        """Generate MD5 hash of content for deduplication."""
        return hashlib.md5(content.encode()).hexdigest()

    def save_raw_data(
        self,
        source: str,
        content: str,
        content_hash: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Insert raw data into PostgreSQL with deduplication check.
        Returns True if inserted, False if duplicate.
        """
        try:
            budgeted = apply_text_byte_budget(
                content,
                settings.crawler_max_document_bytes,
            )
            safe_metadata = {
                **(metadata or {}),
                "content_budget": {
                    "limit_bytes": settings.crawler_max_document_bytes,
                    "original_bytes": budgeted.original_bytes,
                    "stored_bytes": budgeted.stored_bytes,
                    "truncated": budgeted.truncated,
                },
            }
            if budgeted.truncated:
                content_hash = hashlib.sha256(
                    budgeted.text.encode("utf-8")
                ).hexdigest()
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO raw_data (
                            competitor_id, source, content, hash, metadata, pipeline_run_id
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON CONFLICT (competitor_id, source, hash) DO NOTHING
                        RETURNING id
                        """,
                        (
                            self.competitor_id,
                            source,
                            budgeted.text,
                            content_hash,
                            Json(json_safe(safe_metadata)),
                            self.run_id,
                        )
                    )
                    result = cur.fetchone()
                    conn.commit()
                    if result:
                        logger.info(f"Saved new {source} data for {self.competitor_name}")
                        return True
                    else:
                        logger.debug(f"Duplicate {source} data for {self.competitor_name}, skipping")
                        return False
        except Exception as e:
            logger.error(f"Failed to save raw data for {self.competitor_name} ({source}): {e}")
            return False

    def save_evidence(
        self,
        source_url: str,
        title: str,
        content: str,
        content_hash: str,
        confidence: float = 0.8,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[int]:
        """Persist source evidence and return its stable ID."""
        try:
            budgeted = apply_text_byte_budget(
                content,
                settings.crawler_max_document_bytes,
            )
            safe_metadata = {
                **(metadata or {}),
                "content_budget": {
                    "limit_bytes": settings.crawler_max_document_bytes,
                    "original_bytes": budgeted.original_bytes,
                    "stored_bytes": budgeted.stored_bytes,
                    "truncated": budgeted.truncated,
                },
            }
            content = budgeted.text
            if budgeted.truncated:
                content_hash = hashlib.sha256(
                    content.encode("utf-8")
                ).hexdigest()
            evidence_hash = hashlib.sha256(
                f"{source_url}\0{content_hash}".encode("utf-8")
            ).hexdigest()
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO evidence (
                            competitor_id, source_url, title, snippet, full_text,
                            confidence, hash, metadata, pipeline_run_id
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (competitor_id, hash)
                        DO UPDATE SET
                            title = EXCLUDED.title,
                            snippet = EXCLUDED.snippet,
                            full_text = EXCLUDED.full_text,
                            confidence = EXCLUDED.confidence,
                            metadata = evidence.metadata || EXCLUDED.metadata,
                            pipeline_run_id = COALESCE(
                                EXCLUDED.pipeline_run_id,
                                evidence.pipeline_run_id
                            )
                        RETURNING id
                        """,
                        (
                            self.competitor_id,
                            source_url,
                            title[:1000] if title else None,
                            content[:1000],
                            content,
                            min(max(confidence, 0.0), 1.0),
                            evidence_hash,
                            Json(json_safe(safe_metadata)),
                            self.run_id,
                        ),
                    )
                    evidence_id = cur.fetchone()["id"]
                    conn.commit()
            document = DocumentStore(self.competitor_id).ingest(
                source_url=source_url,
                title=title,
                content=content,
                source_type=str(
                    safe_metadata.get("source_type")
                    or safe_metadata.get("kind")
                    or "source_evidence"
                ),
                source_name=safe_metadata.get("publisher")
                or safe_metadata.get("job_source"),
                media_type=str(safe_metadata.get("content_type") or "text/plain"),
                language=safe_metadata.get("language"),
                author=safe_metadata.get("author"),
                published_at=safe_metadata.get("published_at")
                or safe_metadata.get("date_posted"),
                extraction_method=str(
                    safe_metadata.get("engine")
                    or safe_metadata.get("collector")
                    or "agent"
                ),
                metadata={**safe_metadata, "evidence_id": evidence_id},
            )
            if document:
                with get_connection() as conn:
                    with conn.cursor() as cur:
                        cur.execute(
                            """
                            UPDATE evidence
                            SET document_version_id = %s
                            WHERE id = %s
                            """,
                            (document.version_id, evidence_id),
                        )
                        conn.commit()
            return evidence_id
        except Exception as e:
            logger.error(f"Failed to save evidence for {self.competitor_name}: {e}")
            return None

    async def get_last_seen(self, source: str) -> Optional[str]:
        """Get last seen content hash from Redis."""
        return await get_last_seen(self.competitor_id, source)

    async def set_last_seen(self, source: str, content_hash: str) -> bool:
        """Set last seen content hash in Redis."""
        return await set_last_seen(self.competitor_id, source, content_hash)

    async def check_and_update_diff(self, source: str, content: str) -> bool:
        """
        Check if content has changed since last seen.
        Returns True if new/changed (and updates Redis), False if unchanged.
        """
        content_hash = self._hash_content(content)
        last_hash = await self.get_last_seen(source)

        if last_hash == content_hash:
            logger.debug(f"No changes detected for {self.competitor_name} ({source})")
            return False

        await self.set_last_seen(source, content_hash)
        return True

    async def has_changed(self, source: str, content: str) -> bool:
        """Check for a content change without updating Redis state."""
        return await self.get_last_seen(source) != self._hash_content(content)

    async def mark_seen(self, source: str, content: str) -> bool:
        """Record content as seen after it has been persisted successfully."""
        return await self.set_last_seen(source, self._hash_content(content))
