from __future__ import annotations

from copy import deepcopy
from typing import Any

from psycopg2.extras import Json

from config.settings import settings
from db.postgres import get_connection
from intelligence.foundation import json_safe
from llm_gateway.configuration import vault


PREFERENCE_FIELDS = (
    "crawler_max_pages",
    "crawler_max_depth",
    "crawler_concurrency",
    "crawler_max_browser_fallbacks",
    "crawler_request_timeout_seconds",
    "crawler_retry_attempts",
    "crawler_respect_robots",
    "crawler_max_pdf_pages",
    "crawler_max_external_profiles",
    "enable_external_sources",
    "enable_job_scraper",
    "enable_linkedin_scraper",
    "job_sources",
    "job_results_wanted",
    "job_search_location",
    "job_hours_old",
    "youtube_max_videos",
    "youtube_comments_per_video",
    "enable_youtube_transcripts",
    "github_max_repositories",
    "github_releases_per_repository",
    "enable_social_collection",
    "social_max_items_per_run",
    "social_max_comments_per_item",
    "social_request_delay_seconds",
    "social_run_timeout_seconds",
    "social_youtube_retention_days",
    "enable_deep_research",
    "deep_research_max_results",
    "deep_research_max_pages",
    "deep_research_request_delay_seconds",
    "deep_research_timeout_seconds",
)

SECRET_FIELDS = (
    "youtube_api_key",
    "github_token",
    "newsapi_key",
)

_ENVIRONMENT_PREFERENCES = {
    name: deepcopy(getattr(settings, name)) for name in PREFERENCE_FIELDS
}
_ENVIRONMENT_SECRETS = {
    name: getattr(settings, name) for name in SECRET_FIELDS
}


class WorkspaceSettingsStore:
    """Persist operator settings while keeping connector secrets write-only."""

    @staticmethod
    def _row() -> dict[str, Any] | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT preferences, secret_ciphertexts, created_at, updated_at
                    FROM workspace_configuration
                    WHERE id = 1
                    """
                )
                row = cur.fetchone()
        return dict(row) if row else None

    @classmethod
    def active_values(cls) -> dict[str, Any]:
        row = cls._row()
        saved = dict(row.get("preferences") or {}) if row else {}
        return {
            name: deepcopy(saved.get(name, _ENVIRONMENT_PREFERENCES[name]))
            for name in PREFERENCE_FIELDS
        }

    @classmethod
    def active_secret(cls, name: str) -> str | None:
        if name not in SECRET_FIELDS:
            raise ValueError(f"Unsupported connector credential: {name}")
        row = cls._row()
        encrypted = dict(row.get("secret_ciphertexts") or {}) if row else {}
        ciphertext = encrypted.get(name)
        if ciphertext:
            return vault.decrypt(str(ciphertext))
        return _ENVIRONMENT_SECRETS[name]

    @classmethod
    def public_dict(cls) -> dict[str, Any]:
        row = cls._row()
        encrypted = dict(row.get("secret_ciphertexts") or {}) if row else {}
        secret_state = {}
        for name in SECRET_FIELDS:
            saved = bool(encrypted.get(name))
            environment = bool(_ENVIRONMENT_SECRETS[name])
            secret_state[name] = {
                "configured": saved or environment,
                "source": "saved" if saved else "environment" if environment else "missing",
            }
        return {
            "preferences": cls.active_values(),
            "secrets": secret_state,
            "source": "saved" if row else "environment",
            "updated_at": row.get("updated_at") if row else None,
            "requires_restart": [],
        }

    @classmethod
    def save(
        cls,
        *,
        preferences: dict[str, Any],
        secrets: dict[str, str | None],
        clear_secrets: set[str],
    ) -> dict[str, Any]:
        unknown = set(preferences) - set(PREFERENCE_FIELDS)
        if unknown:
            raise ValueError(f"Unsupported workspace settings: {', '.join(sorted(unknown))}")
        unknown_secrets = (set(secrets) | clear_secrets) - set(SECRET_FIELDS)
        if unknown_secrets:
            raise ValueError(
                f"Unsupported connector credentials: {', '.join(sorted(unknown_secrets))}"
            )

        row = cls._row()
        saved_preferences = dict(row.get("preferences") or {}) if row else {}
        ciphertexts = dict(row.get("secret_ciphertexts") or {}) if row else {}
        saved_preferences.update(json_safe(preferences))
        for name in clear_secrets:
            ciphertexts.pop(name, None)
        for name, secret in secrets.items():
            normalized = (secret or "").strip()
            if normalized:
                ciphertexts[name] = vault.encrypt(normalized)

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO workspace_configuration (
                        id, preferences, secret_ciphertexts, updated_at
                    )
                    VALUES (1, %s, %s, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        preferences = EXCLUDED.preferences,
                        secret_ciphertexts = EXCLUDED.secret_ciphertexts,
                        updated_at = NOW()
                    """,
                    (Json(saved_preferences), Json(ciphertexts)),
                )
                conn.commit()
        cls.apply_to_runtime()
        return cls.public_dict()

    @classmethod
    def reset(cls) -> dict[str, Any]:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM workspace_configuration WHERE id = 1")
                conn.commit()
        cls.apply_to_runtime()
        return cls.public_dict()

    @classmethod
    def apply_to_runtime(cls) -> None:
        values = cls.active_values()
        for name, value in values.items():
            setattr(settings, name, value)
        for name in SECRET_FIELDS:
            setattr(settings, name, cls.active_secret(name))
