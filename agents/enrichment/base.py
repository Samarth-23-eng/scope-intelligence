import hashlib
import logging
from typing import List, Dict, Any, Optional

from db.postgres import get_connection
from psycopg2.extras import Json
from db.redis_client import get_last_seen, set_last_seen
from intelligence.foundation import (
    DocumentStore,
    apply_text_byte_budget,
    json_safe,
)
from config.settings import settings
from intelligence.sources import SourceAdapter

logger = logging.getLogger(__name__)


class BaseEnrichmentAgent(SourceAdapter):
    """Base class for all enrichment agents."""

    def __init__(self, competitor_id: int, competitor_name: str, domain: str):
        self.competitor_id = competitor_id
        self.competitor_name = competitor_name
        self.domain = domain
        self.run_id: int | None = None

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
                        DocumentStore(self.competitor_id).ingest(
                            source_url=str(
                                safe_metadata.get("item_url")
                                or safe_metadata.get("url")
                                or safe_metadata.get("feed_url")
                                or f"osint://{source}"
                            ),
                            title=str(
                                safe_metadata.get("title")
                                or safe_metadata.get("technology")
                                or source
                            ),
                            content=budgeted.text,
                            source_type=str(
                                safe_metadata.get("source_type")
                                or safe_metadata.get("kind")
                                or source.split(":", 1)[0]
                            ),
                            source_name=source.split(":", 1)[0],
                            extraction_method=self.__class__.__name__,
                            metadata=safe_metadata,
                        )
                        return True
                    else:
                        logger.debug(f"Duplicate {source} data for {self.competitor_name}, skipping")
                        return False
        except Exception as e:
            logger.error(f"Failed to save raw data for {self.competitor_name} ({source}): {e}")
            return False

    def save_signal(
        self,
        signal_type: str,
        description: str,
        severity: str
    ) -> bool:
        """
        Insert a signal into the signals table.
        Severity must be one of: low, medium, high, critical
        """
        valid_severities = ['low', 'medium', 'high', 'critical']
        if severity not in valid_severities:
            logger.error(f"Invalid severity '{severity}'. Must be one of {valid_severities}")
            return False

        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        INSERT INTO signals (competitor_id, signal_type, description, severity)
                        VALUES (%s, %s, %s, %s)
                        RETURNING id
                        """,
                        (self.competitor_id, signal_type, description, severity)
                    )
                    result = cur.fetchone()
                    conn.commit()
                    if result:
                        logger.info(f"Saved signal: {signal_type} ({severity}) for {self.competitor_name}")
                        return True
                    return False
        except Exception as e:
            logger.error(f"Failed to save signal for {self.competitor_name}: {e}")
            return False

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
