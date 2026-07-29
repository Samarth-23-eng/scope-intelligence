"""Durable continuous-intelligence scheduling and operator audit trail."""

from __future__ import annotations

from typing import Any, Iterable

from psycopg2.extras import Json

from db.postgres import get_connection


class MonitoringStore:
    ALLOWED_SEVERITIES = {"low", "medium", "high", "critical"}

    @staticmethod
    def _ensure_profile(competitor_id: int) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO monitoring_profiles (competitor_id)
                    VALUES (%s)
                    ON CONFLICT (competitor_id) DO UPDATE
                    SET competitor_id = EXCLUDED.competitor_id
                    RETURNING *
                    """,
                    (competitor_id,),
                )
                row = dict(cur.fetchone())
                conn.commit()
        return row

    @classmethod
    def get_overview(cls, competitor_id: int) -> dict[str, Any]:
        profile = cls._ensure_profile(competitor_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM page_changes
                         WHERE competitor_id = %s
                           AND detected_at >= NOW() - INTERVAL '7 days') AS changes_7d,
                        (SELECT COUNT(*) FROM signals
                         WHERE competitor_id = %s
                           AND detected_at >= NOW() - INTERVAL '7 days') AS signals_7d,
                        (SELECT COUNT(*) FROM signals
                         WHERE competitor_id = %s
                           AND severity = ANY(%s)
                           AND detected_at >= NOW() - INTERVAL '7 days') AS priority_signals_7d,
                        (SELECT COUNT(*) FROM documents
                         WHERE competitor_id = %s
                           AND first_seen_at >= NOW() - INTERVAL '7 days') AS documents_7d,
                        (SELECT COUNT(*) FROM collection_errors
                         WHERE competitor_id = %s
                           AND resolved_at IS NULL) AS open_collection_errors
                    """,
                    (
                        competitor_id,
                        competitor_id,
                        competitor_id,
                        profile.get("alert_severities") or ["high", "critical"],
                        competitor_id,
                        competitor_id,
                    ),
                )
                metrics = dict(cur.fetchone())
                cur.execute(
                    """
                    SELECT id, monitoring_profile_id, competitor_id, pipeline_run_id,
                           event_type, status, message, metadata, created_at
                    FROM monitoring_activity
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    LIMIT 30
                    """,
                    (competitor_id,),
                )
                activity = [dict(row) for row in cur.fetchall()]
                cur.execute(
                    """
                    SELECT id, status, trigger_type, started_at, completed_at, created_at
                    FROM pipeline_runs
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (competitor_id,),
                )
                latest_run = cur.fetchone()
        return {
            "profile": profile,
            "metrics": metrics,
            "activity": activity,
            "latest_run": dict(latest_run) if latest_run else None,
        }

    @classmethod
    def update_profile(
        cls,
        competitor_id: int,
        *,
        enabled: bool,
        cadence_minutes: int,
        focus_topics: Iterable[str],
        alert_severities: Iterable[str],
    ) -> dict[str, Any]:
        topics = list(
            dict.fromkeys(
                topic.strip()[:80]
                for topic in focus_topics
                if isinstance(topic, str) and topic.strip()
            )
        )[:12]
        severities = [
            value
            for value in dict.fromkeys(alert_severities)
            if value in cls.ALLOWED_SEVERITIES
        ]
        if not severities:
            severities = ["high", "critical"]
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO monitoring_profiles (
                        competitor_id, enabled, cadence_minutes,
                        focus_topics, alert_severities, next_run_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s,
                        CASE WHEN %s
                            THEN NOW() + (%s || ' minutes')::interval
                            ELSE NULL
                        END
                    )
                    ON CONFLICT (competitor_id) DO UPDATE SET
                        enabled = EXCLUDED.enabled,
                        cadence_minutes = EXCLUDED.cadence_minutes,
                        focus_topics = EXCLUDED.focus_topics,
                        alert_severities = EXCLUDED.alert_severities,
                        next_run_at = CASE
                            WHEN EXCLUDED.enabled = FALSE THEN NULL
                            WHEN monitoring_profiles.enabled = FALSE
                              OR monitoring_profiles.cadence_minutes
                                 <> EXCLUDED.cadence_minutes
                              OR monitoring_profiles.next_run_at IS NULL
                            THEN NOW() + (
                                EXCLUDED.cadence_minutes || ' minutes'
                            )::interval
                            ELSE monitoring_profiles.next_run_at
                        END,
                        updated_at = NOW()
                    RETURNING *
                    """,
                    (
                        competitor_id,
                        enabled,
                        cadence_minutes,
                        Json(topics),
                        Json(severities),
                        enabled,
                        cadence_minutes,
                    ),
                )
                row = dict(cur.fetchone())
                cur.execute(
                    """
                    INSERT INTO monitoring_activity (
                        monitoring_profile_id, competitor_id,
                        event_type, status, message, metadata
                    )
                    VALUES (%s, %s, 'configuration', 'completed', %s, %s)
                    """,
                    (
                        row["id"],
                        competitor_id,
                        (
                            "Continuous monitoring enabled"
                            if enabled
                            else "Continuous monitoring paused"
                        ),
                        Json(
                            {
                                "cadence_minutes": cadence_minutes,
                                "focus_topics": topics,
                                "alert_severities": severities,
                            }
                        ),
                    ),
                )
                conn.commit()
        return row

    @staticmethod
    def prepare_run(
        competitor_id: int,
        *,
        event_type: str,
        message: str,
    ) -> dict[str, Any]:
        profile = MonitoringStore._ensure_profile(competitor_id)
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE monitoring_profiles
                    SET last_status = 'queued', last_error = NULL,
                        updated_at = NOW()
                    WHERE id = %s
                    RETURNING *
                    """,
                    (profile["id"],),
                )
                profile = dict(cur.fetchone())
                cur.execute(
                    """
                    INSERT INTO monitoring_activity (
                        monitoring_profile_id, competitor_id,
                        event_type, status, message
                    )
                    VALUES (%s, %s, %s, 'queued', %s)
                    RETURNING id
                    """,
                    (profile["id"], competitor_id, event_type, message),
                )
                activity_id = int(cur.fetchone()["id"])
                conn.commit()
        return {"profile": profile, "activity_id": activity_id}

    @staticmethod
    def attach_run(profile_id: int, activity_id: int, run_id: int) -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE monitoring_profiles
                    SET last_run_id = %s, last_status = 'running',
                        last_scheduled_at = NOW(), updated_at = NOW()
                    WHERE id = %s
                    """,
                    (run_id, profile_id),
                )
                cur.execute(
                    """
                    UPDATE monitoring_activity
                    SET pipeline_run_id = %s, status = 'running'
                    WHERE id = %s
                    """,
                    (run_id, activity_id),
                )
                conn.commit()

    @staticmethod
    def finish_run(
        profile_id: int,
        activity_id: int,
        run_id: int,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        message = (
            f"Monitoring pipeline finished with status: {status}"
            if not error
            else f"Monitoring pipeline failed: {error}"
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE monitoring_profiles
                    SET last_run_id = %s, last_status = %s, last_error = %s,
                        updated_at = NOW()
                    WHERE id = %s
                    """,
                    (run_id, status, error, profile_id),
                )
                cur.execute(
                    """
                    UPDATE monitoring_activity
                    SET status = %s, message = %s
                    WHERE id = %s
                    """,
                    (status, message, activity_id),
                )
                conn.commit()

    @staticmethod
    def claim_due_profiles(limit: int = 3) -> list[dict[str, Any]]:
        """Atomically move due profiles forward and return scheduler work."""
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT profile.id, profile.competitor_id
                    FROM monitoring_profiles profile
                    WHERE profile.enabled = TRUE
                      AND profile.next_run_at <= NOW()
                    ORDER BY profile.next_run_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT %s
                    """,
                    (limit,),
                )
                due = [dict(row) for row in cur.fetchall()]
                claimed: list[dict[str, Any]] = []
                for item in due:
                    cur.execute(
                        """
                        UPDATE monitoring_profiles
                        SET next_run_at = NOW()
                            + (cadence_minutes || ' minutes')::interval,
                            last_status = 'queued',
                            last_error = NULL,
                            updated_at = NOW()
                        WHERE id = %s
                        RETURNING *
                        """,
                        (item["id"],),
                    )
                    profile = dict(cur.fetchone())
                    cur.execute(
                        """
                        INSERT INTO monitoring_activity (
                            monitoring_profile_id, competitor_id,
                            event_type, status, message
                        )
                        VALUES (%s, %s, 'scheduled_run', 'queued',
                                'Scheduled monitoring window reached')
                        RETURNING id
                        """,
                        (profile["id"], profile["competitor_id"]),
                    )
                    claimed.append(
                        {
                            "profile": profile,
                            "activity_id": int(cur.fetchone()["id"]),
                        }
                    )
                conn.commit()
        return claimed

    @staticmethod
    def mark_skipped(
        profile_id: int,
        activity_id: int,
        message: str,
    ) -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE monitoring_profiles
                    SET last_status = 'skipped', last_error = %s, updated_at = NOW()
                    WHERE id = %s
                    """,
                    (message, profile_id),
                )
                cur.execute(
                    """
                    UPDATE monitoring_activity
                    SET status = 'skipped', message = %s
                    WHERE id = %s
                    """,
                    (message, activity_id),
                )
                conn.commit()
