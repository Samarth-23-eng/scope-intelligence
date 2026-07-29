from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from psycopg2.extras import Json

from db.postgres import get_connection
from intelligence.foundation import json_safe


@dataclass(frozen=True)
class FrontierTarget:
    frontier_id: int
    url: str
    depth: int
    priority: int
    discovered_from: str
    attempts: int
    max_attempts: int


class CollectionAccessPolicyStore:
    """Per-company switch for the experimental public-access recovery adapter."""

    @staticmethod
    def is_enabled(competitor_id: int) -> bool:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT access_recovery_enabled
                    FROM competitors
                    WHERE id = %s
                    """,
                    (competitor_id,),
                )
                row = cur.fetchone()
        return bool(row and row["access_recovery_enabled"])

    @staticmethod
    def set_enabled(competitor_id: int, enabled: bool) -> bool:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE competitors
                    SET access_recovery_enabled = %s
                    WHERE id = %s
                    RETURNING access_recovery_enabled
                    """,
                    (enabled, competitor_id),
                )
                row = cur.fetchone()
                conn.commit()
        if not row:
            raise ValueError("Competitor not found")
        return bool(row["access_recovery_enabled"])


class CollectionErrorStore:
    """Durable, user-facing collection failures with automatic deduplication."""

    def __init__(
        self,
        competitor_id: int,
        *,
        run_id: int | None = None,
        campaign_id: int | None = None,
    ):
        self.competitor_id = competitor_id
        self.run_id = run_id
        self.campaign_id = campaign_id

    @staticmethod
    def _hash(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def record(
        self,
        *,
        error_code: str,
        category: str,
        technical_message: str,
        user_message: str,
        url: str | None = None,
        http_status: int | None = None,
        severity: str = "warning",
        engine: str | None = None,
        attempts: Iterable[str] = (),
        suggested_action: str | None = None,
        recoverable: bool = True,
        metadata: dict[str, Any] | None = None,
    ) -> int:
        canonical_url = CollectionCampaignStore.canonicalize_url(url or "") or (url or "")
        if canonical_url:
            parsed_url = urlsplit(canonical_url)
            canonical_url = urlunsplit(
                (parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", "")
            )
        fingerprint = self._hash(
            "|".join(
                (
                    canonical_url.casefold(),
                    error_code.casefold(),
                    str(http_status or ""),
                )
            )
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO collection_errors (
                        competitor_id, pipeline_run_id, campaign_id, url, url_hash,
                        error_code, category, http_status, severity, engine, attempts,
                        technical_message, user_message, suggested_action, recoverable,
                        metadata, fingerprint
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (competitor_id, fingerprint)
                        WHERE resolved_at IS NULL
                    DO UPDATE SET
                        pipeline_run_id = COALESCE(
                            EXCLUDED.pipeline_run_id,
                            collection_errors.pipeline_run_id
                        ),
                        campaign_id = COALESCE(
                            EXCLUDED.campaign_id,
                            collection_errors.campaign_id
                        ),
                        severity = EXCLUDED.severity,
                        engine = EXCLUDED.engine,
                        attempts = EXCLUDED.attempts,
                        technical_message = EXCLUDED.technical_message,
                        user_message = EXCLUDED.user_message,
                        suggested_action = EXCLUDED.suggested_action,
                        recoverable = EXCLUDED.recoverable,
                        metadata = collection_errors.metadata || EXCLUDED.metadata,
                        occurrences = collection_errors.occurrences + 1,
                        last_occurred_at = NOW()
                    RETURNING id
                    """,
                    (
                        self.competitor_id,
                        self.run_id,
                        self.campaign_id,
                        canonical_url[:4096] or None,
                        self._hash(canonical_url) if canonical_url else None,
                        error_code[:100],
                        category[:80],
                        http_status,
                        severity,
                        engine[:80] if engine else None,
                        Json(list(dict.fromkeys(attempts))),
                        technical_message[:20000],
                        user_message[:20000],
                        suggested_action[:20000] if suggested_action else None,
                        recoverable,
                        Json(json_safe(metadata or {})),
                        fingerprint,
                    ),
                )
                error_id = int(cur.fetchone()["id"])
                conn.commit()
        return error_id

    def resolve_url(self, url: str) -> int:
        canonical_url = CollectionCampaignStore.canonicalize_url(url) or url
        parsed_url = urlsplit(canonical_url)
        canonical_url = urlunsplit(
            (parsed_url.scheme, parsed_url.netloc, parsed_url.path, "", "")
        )
        url_hash = self._hash(canonical_url)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE collection_errors
                    SET resolved_at = NOW()
                    WHERE competitor_id = %s
                      AND url_hash = %s
                      AND resolved_at IS NULL
                    """,
                    (self.competitor_id, url_hash),
                )
                resolved = max(cur.rowcount, 0)
                conn.commit()
        return resolved


class CollectionCampaignStore:
    """Durable crawl frontier and collection telemetry for one campaign."""

    def __init__(
        self,
        competitor_id: int,
        *,
        run_id: int | None = None,
        campaign_type: str = "web",
    ):
        self.competitor_id = competitor_id
        self.run_id = run_id
        self.campaign_type = campaign_type
        self.campaign_id: int | None = None

    def start(
        self,
        *,
        strategy: str = "adaptive_priority",
        budget: dict[str, Any] | None = None,
    ) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if self.run_id is not None:
                    cur.execute(
                        """
                        SELECT id
                        FROM collection_campaigns
                        WHERE pipeline_run_id = %s AND campaign_type = %s
                        """,
                        (self.run_id, self.campaign_type),
                    )
                    row = cur.fetchone()
                    if row:
                        self.campaign_id = int(row["id"])
                        cur.execute(
                            """
                            UPDATE collection_campaigns
                            SET status = 'running',
                                strategy = %s,
                                budget = budget || %s,
                                error = NULL,
                                started_at = COALESCE(started_at, NOW()),
                                completed_at = NULL
                            WHERE id = %s
                            """,
                            (strategy[:100], Json(json_safe(budget or {})), self.campaign_id),
                        )
                        conn.commit()
                        return self.campaign_id
                cur.execute(
                    """
                    INSERT INTO collection_campaigns (
                        competitor_id, pipeline_run_id, campaign_type, status,
                        strategy, budget, started_at
                    )
                    VALUES (%s, %s, %s, 'running', %s, %s, NOW())
                    RETURNING id
                    """,
                    (
                        self.competitor_id,
                        self.run_id,
                        self.campaign_type[:60],
                        strategy[:100],
                        Json(json_safe(budget or {})),
                    ),
                )
                self.campaign_id = int(cur.fetchone()["id"])
                conn.commit()
        return self.campaign_id

    @staticmethod
    def canonicalize_url(url: str) -> str:
        parsed = urlsplit((url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            return ""
        host = (parsed.hostname or "").casefold()
        port = parsed.port
        netloc = host
        if port and not (
            (parsed.scheme == "http" and port == 80)
            or (parsed.scheme == "https" and port == 443)
        ):
            netloc = f"{host}:{port}"
        path = parsed.path or "/"
        path = path.rstrip("/") or "/"
        query = [
            (key, value)
            for key, value in parse_qsl(parsed.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
            and key.casefold() not in {"fbclid", "gclid", "ref", "source"}
        ]
        return urlunsplit(
            (parsed.scheme.casefold(), netloc, path, urlencode(sorted(query)), "")
        )

    def enqueue(
        self,
        url: str,
        *,
        depth: int,
        priority: int,
        discovered_from: str,
        source_type: str = "web",
        max_attempts: int = 2,
        metadata: dict[str, Any] | None = None,
    ) -> int | None:
        if self.campaign_id is None:
            return None
        canonical = self.canonicalize_url(url)
        if not canonical:
            return None
        url_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO crawl_frontier (
                        campaign_id, competitor_id, url, url_hash, source_type,
                        depth, priority, discovered_from, max_attempts, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (campaign_id, url_hash)
                    DO UPDATE SET
                        priority = GREATEST(crawl_frontier.priority, EXCLUDED.priority),
                        depth = LEAST(crawl_frontier.depth, EXCLUDED.depth),
                        metadata = crawl_frontier.metadata || EXCLUDED.metadata
                    RETURNING id
                    """,
                    (
                        self.campaign_id,
                        self.competitor_id,
                        canonical[:4096],
                        url_hash,
                        source_type[:80],
                        max(depth, 0),
                        priority,
                        discovered_from[:4096],
                        max(max_attempts, 1),
                        Json(json_safe(metadata or {})),
                    ),
                )
                frontier_id = int(cur.fetchone()["id"])
                conn.commit()
        return frontier_id

    def resume_targets(self, limit: int) -> list[FrontierTarget]:
        if self.campaign_id is None:
            return []
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE crawl_frontier
                    SET state = 'queued', claimed_at = NULL
                    WHERE campaign_id = %s AND state = 'fetching'
                    """,
                    (self.campaign_id,),
                )
                cur.execute(
                    """
                    SELECT id, url, depth, priority,
                           COALESCE(discovered_from, 'resume') AS discovered_from,
                           attempts, max_attempts
                    FROM crawl_frontier
                    WHERE campaign_id = %s
                      AND state IN ('queued', 'failed')
                      AND attempts < max_attempts
                      AND (next_retry_at IS NULL OR next_retry_at <= NOW())
                    ORDER BY priority DESC, id
                    LIMIT %s
                    """,
                    (self.campaign_id, max(limit, 1)),
                )
                rows = cur.fetchall() or []
                conn.commit()
        return [
            FrontierTarget(
                frontier_id=int(row["id"]),
                url=row["url"],
                depth=int(row["depth"]),
                priority=int(row["priority"]),
                discovered_from=row["discovered_from"],
                attempts=int(row["attempts"]),
                max_attempts=int(row["max_attempts"]),
            )
            for row in rows
        ]

    def mark_fetching(self, url: str) -> int | None:
        if self.campaign_id is None:
            return None
        canonical = self.canonicalize_url(url)
        url_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE crawl_frontier
                    SET state = 'fetching', attempts = attempts + 1,
                        claimed_at = NOW(), last_error = NULL
                    WHERE campaign_id = %s AND url_hash = %s
                    RETURNING id
                    """,
                    (self.campaign_id, url_hash),
                )
                row = cur.fetchone()
                conn.commit()
        return int(row["id"]) if row else None

    def mark_outcome(
        self,
        url: str,
        *,
        state: str,
        status_code: int | None = None,
        content_hash: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.campaign_id is None:
            return
        canonical = self.canonicalize_url(url)
        url_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        terminal = state in {"completed", "unchanged", "blocked", "skipped"}
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE crawl_frontier
                    SET state = %s,
                        last_http_status = %s,
                        content_hash = COALESCE(%s, content_hash),
                        last_error = %s,
                        metadata = metadata || %s,
                        completed_at = CASE WHEN %s THEN NOW() ELSE NULL END,
                        next_retry_at = CASE
                            WHEN %s = 'failed' AND attempts < max_attempts
                            THEN NOW() + (LEAST(attempts, 6) * INTERVAL '30 seconds')
                            ELSE NULL
                        END
                    WHERE campaign_id = %s AND url_hash = %s
                    """,
                    (
                        state,
                        status_code,
                        content_hash,
                        error[:5000] if error else None,
                        Json(json_safe(metadata or {})),
                        terminal,
                        state,
                        self.campaign_id,
                        url_hash,
                    ),
                )
                conn.commit()

    def finish(
        self,
        *,
        status: str,
        statistics: dict[str, Any],
        error: str | None = None,
    ) -> None:
        if self.campaign_id is None:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE collection_campaigns
                    SET status = %s, statistics = %s, error = %s,
                        completed_at = NOW()
                    WHERE id = %s
                    """,
                    (
                        status,
                        Json(json_safe(statistics)),
                        error[:10000] if error else None,
                        self.campaign_id,
                    ),
                )
                conn.commit()

    def event(
        self,
        *,
        adapter_name: str,
        event_type: str,
        success: bool,
        items: int = 0,
        bytes_collected: int = 0,
        latency_ms: int | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        frontier_id: int | None = None,
    ) -> None:
        if self.campaign_id is None:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO collection_events (
                        competitor_id, campaign_id, frontier_id, pipeline_run_id,
                        adapter_name, event_type, success, items,
                        bytes_collected, latency_ms, error, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        self.competitor_id,
                        self.campaign_id,
                        frontier_id,
                        self.run_id,
                        adapter_name[:120],
                        event_type[:80],
                        success,
                        max(items, 0),
                        max(bytes_collected, 0),
                        latency_ms,
                        error[:5000] if error else None,
                        Json(json_safe(metadata or {})),
                    ),
                )
                conn.commit()


class SourceProfileStore:
    """Registry of first-party-confirmed external profiles and feeds."""

    RESERVED_GITHUB_PATHS = {
        "about",
        "apps",
        "collections",
        "contact",
        "enterprise",
        "events",
        "explore",
        "features",
        "issues",
        "marketplace",
        "new",
        "notifications",
        "orgs",
        "pricing",
        "pulls",
        "search",
        "settings",
        "sponsors",
        "topics",
        "trending",
    }

    def __init__(self, competitor_id: int):
        self.competitor_id = competitor_id

    @staticmethod
    def normalize_profile_url(profile_url: str) -> str:
        canonical = (
            CollectionCampaignStore.canonicalize_url(profile_url)
            or profile_url.strip()
        )
        parsed = urlsplit(canonical)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            # Profile identity lives in the path; tracking and subscription
            # parameters otherwise create duplicate collection targets.
            return urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path.rstrip("/") or "/", "", "")
            )
        return canonical

    @classmethod
    def classify(cls, url: str) -> tuple[str, str] | None:
        parsed = urlsplit((url or "").strip())
        host = (parsed.hostname or "").casefold().removeprefix("www.")
        parts = [part for part in parsed.path.split("/") if part]
        if host in {"youtube.com", "m.youtube.com", "youtu.be"}:
            if host == "youtu.be":
                return None
            if parts and (
                parts[0].startswith("@")
                or parts[0] in {"channel", "c", "user"}
            ):
                key = parts[1] if parts[0] in {"channel", "c", "user"} and len(parts) > 1 else parts[0]
                return "youtube", key
        if host == "github.com" and parts:
            key = parts[0]
            if key.casefold() not in cls.RESERVED_GITHUB_PATHS:
                return "github", key
        if host.endswith("linkedin.com") and len(parts) > 1 and parts[0] == "company":
            return "linkedin", parts[1]
        if host in {"x.com", "twitter.com"} and parts:
            return "x", parts[0]
        if host == "reddit.com" and len(parts) > 1 and parts[0] == "r":
            return "reddit", parts[1]
        return None

    def discover(
        self,
        *,
        source_type: str,
        profile_url: str,
        profile_key: str | None = None,
        confidence: float = 0.8,
        discovered_from: str | None = None,
        status: str = "discovered",
        metadata: dict[str, Any] | None = None,
    ) -> int:
        canonical = self.normalize_profile_url(profile_url)
        profile_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        with get_connection() as conn:
            with conn.cursor() as cur:
                if profile_key:
                    cur.execute(
                        """
                        SELECT id
                        FROM source_profiles
                        WHERE competitor_id = %s
                          AND source_type = %s
                          AND LOWER(profile_key) = LOWER(%s)
                        ORDER BY confidence DESC, id
                        LIMIT 1
                        """,
                        (self.competitor_id, source_type[:80], profile_key[:500]),
                    )
                    existing = cur.fetchone()
                    if existing:
                        cur.execute(
                            """
                            UPDATE source_profiles
                            SET profile_url = %s,
                                profile_hash = %s,
                                confidence = GREATEST(confidence, %s),
                                discovered_from = COALESCE(discovered_from, %s),
                                metadata = metadata || %s
                            WHERE id = %s
                            """,
                            (
                                canonical[:4096],
                                profile_hash,
                                min(max(confidence, 0.0), 1.0),
                                discovered_from[:4096] if discovered_from else None,
                                Json(json_safe(metadata or {})),
                                int(existing["id"]),
                            ),
                        )
                        conn.commit()
                        return int(existing["id"])
                cur.execute(
                    """
                    INSERT INTO source_profiles (
                        competitor_id, source_type, profile_url, profile_key,
                        profile_hash, status, confidence, discovered_from, metadata
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (competitor_id, source_type, profile_hash)
                    DO UPDATE SET
                        profile_key = COALESCE(EXCLUDED.profile_key, source_profiles.profile_key),
                        confidence = GREATEST(source_profiles.confidence, EXCLUDED.confidence),
                        discovered_from = COALESCE(
                            source_profiles.discovered_from,
                            EXCLUDED.discovered_from
                        ),
                        metadata = source_profiles.metadata || EXCLUDED.metadata
                    RETURNING id
                    """,
                    (
                        self.competitor_id,
                        source_type[:80],
                        canonical[:4096],
                        profile_key[:500] if profile_key else None,
                        profile_hash,
                        status,
                        min(max(confidence, 0.0), 1.0),
                        discovered_from[:4096] if discovered_from else None,
                        Json(json_safe(metadata or {})),
                    ),
                )
                profile_id = int(cur.fetchone()["id"])
                conn.commit()
        return profile_id

    def discover_urls(
        self,
        urls: Iterable[str],
        *,
        discovered_from: str,
        confidence: float = 0.85,
        limit: int = 80,
    ) -> dict[str, int]:
        counts: dict[str, int] = {}
        seen: set[tuple[str, str]] = set()
        for url in urls:
            classified = self.classify(url)
            if not classified or classified in seen:
                continue
            source_type, profile_key = classified
            self.discover(
                source_type=source_type,
                profile_url=url,
                profile_key=profile_key,
                confidence=confidence,
                discovered_from=discovered_from,
            )
            seen.add(classified)
            counts[source_type] = counts.get(source_type, 0) + 1
            if len(seen) >= max(limit, 1):
                break
        return counts

    def list_active(self, source_types: Iterable[str] | None = None) -> list[dict[str, Any]]:
        filters = list(source_types or [])
        with get_connection() as conn:
            with conn.cursor() as cur:
                if filters:
                    cur.execute(
                        """
                        SELECT *
                        FROM source_profiles
                        WHERE competitor_id = %s
                          AND source_type = ANY(%s)
                          AND status != 'disabled'
                        ORDER BY confidence DESC, id
                        """,
                        (self.competitor_id, filters),
                    )
                else:
                    cur.execute(
                        """
                        SELECT *
                        FROM source_profiles
                        WHERE competitor_id = %s AND status != 'disabled'
                        ORDER BY confidence DESC, id
                        """,
                        (self.competitor_id,),
                    )
                return cur.fetchall() or []

    def mark_collected(
        self,
        profile_id: int,
        *,
        success: bool,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE source_profiles
                    SET status = %s,
                        verified_at = COALESCE(verified_at, CASE WHEN %s THEN NOW() END),
                        last_collected_at = NOW(),
                        metadata = (
                            CASE WHEN %s THEN metadata - 'last_error' ELSE metadata END
                        ) || %s
                    WHERE id = %s AND competitor_id = %s
                    """,
                    (
                        "active" if success else "error",
                        success,
                        success,
                        Json(json_safe(metadata or {})),
                        profile_id,
                        self.competitor_id,
                    ),
                )
                conn.commit()

    def bootstrap_competitor_profiles(self) -> int:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT social_media FROM competitors WHERE id = %s",
                    (self.competitor_id,),
                )
                row = cur.fetchone()
        if not row:
            return 0
        value = row.get("social_media")
        urls: list[str] = []
        if isinstance(value, dict):
            urls.extend(str(item) for item in value.values())
        elif isinstance(value, list):
            urls.extend(str(item) for item in value)
        elif isinstance(value, str):
            try:
                parsed = json.loads(value)
            except (TypeError, ValueError, json.JSONDecodeError):
                parsed = value
            if isinstance(parsed, dict):
                urls.extend(str(item) for item in parsed.values())
            elif isinstance(parsed, list):
                urls.extend(str(item) for item in parsed)
            else:
                urls.append(str(parsed))
        return sum(
            self.discover_urls(
                urls,
                discovered_from="competitor_profile",
                confidence=0.95,
            ).values()
        )
