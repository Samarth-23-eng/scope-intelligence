from __future__ import annotations

from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, SecretStr, field_validator

from config.settings import settings
from intelligence.security import redact_sensitive_text
from intelligence.workspace_settings import (
    PREFERENCE_FIELDS,
    WorkspaceSettingsStore,
)


router = APIRouter(prefix="/settings/workspace", tags=["settings"])


class WorkspaceSettingsUpdate(BaseModel):
    crawler_max_pages: int | None = Field(default=None, ge=1, le=500)
    crawler_max_depth: int | None = Field(default=None, ge=0, le=10)
    crawler_concurrency: int | None = Field(default=None, ge=1, le=20)
    crawler_max_browser_fallbacks: int | None = Field(default=None, ge=0, le=50)
    crawler_request_timeout_seconds: float | None = Field(default=None, ge=5, le=180)
    crawler_retry_attempts: int | None = Field(default=None, ge=0, le=6)
    crawler_respect_robots: bool | None = None
    crawler_max_pdf_pages: int | None = Field(default=None, ge=1, le=500)
    crawler_max_external_profiles: int | None = Field(default=None, ge=1, le=500)

    enable_external_sources: bool | None = None
    enable_job_scraper: bool | None = None
    enable_linkedin_scraper: bool | None = None
    job_sources: str | None = Field(default=None, max_length=200)
    job_results_wanted: int | None = Field(default=None, ge=1, le=200)
    job_search_location: str | None = Field(default=None, max_length=200)
    job_hours_old: int | None = Field(default=None, ge=1, le=8760)
    youtube_max_videos: int | None = Field(default=None, ge=1, le=50)
    youtube_comments_per_video: int | None = Field(default=None, ge=0, le=200)
    enable_youtube_transcripts: bool | None = None
    github_max_repositories: int | None = Field(default=None, ge=1, le=100)
    github_releases_per_repository: int | None = Field(default=None, ge=0, le=20)

    enable_social_collection: bool | None = None
    social_max_items_per_run: int | None = Field(default=None, ge=1, le=50)
    social_max_comments_per_item: int | None = Field(default=None, ge=0, le=200)
    social_request_delay_seconds: float | None = Field(default=None, ge=0, le=10)
    social_run_timeout_seconds: float | None = Field(default=None, ge=30, le=3600)
    social_youtube_retention_days: int | None = Field(default=None, ge=1, le=30)
    enable_deep_research: bool | None = None
    deep_research_max_results: int | None = Field(default=None, ge=1, le=100)
    deep_research_max_pages: int | None = Field(default=None, ge=1, le=50)
    deep_research_request_delay_seconds: float | None = Field(default=None, ge=0.25, le=15)
    deep_research_timeout_seconds: float | None = Field(default=None, ge=60, le=3600)

    youtube_api_key: SecretStr | None = Field(default=None, max_length=500)
    github_token: SecretStr | None = Field(default=None, max_length=500)
    newsapi_key: SecretStr | None = Field(default=None, max_length=500)
    clear_youtube_api_key: bool = False
    clear_github_token: bool = False
    clear_newsapi_key: bool = False

    @field_validator("job_sources")
    @classmethod
    def normalize_job_sources(cls, value: str | None) -> str | None:
        if value is None:
            return None
        sources = [item.strip().lower() for item in value.split(",") if item.strip()]
        allowed = {"indeed", "google", "linkedin", "glassdoor", "zip_recruiter"}
        unknown = set(sources) - allowed
        if unknown:
            raise ValueError(f"Unsupported job sources: {', '.join(sorted(unknown))}")
        if not sources:
            raise ValueError("At least one job source is required")
        return ",".join(dict.fromkeys(sources))


@router.get("")
def get_workspace_settings():
    return WorkspaceSettingsStore.public_dict()


@router.put("")
def update_workspace_settings(request: WorkspaceSettingsUpdate):
    payload = request.model_dump(exclude_none=True)
    preferences = {
        name: payload[name] for name in PREFERENCE_FIELDS if name in payload
    }
    secrets = {
        name: secret.get_secret_value()
        for name in ("youtube_api_key", "github_token", "newsapi_key")
        if (secret := getattr(request, name)) is not None
    }
    clear_secrets = {
        name
        for name in ("youtube_api_key", "github_token", "newsapi_key")
        if getattr(request, f"clear_{name}")
    }
    try:
        return WorkspaceSettingsStore.save(
            preferences=preferences,
            secrets=secrets,
            clear_secrets=clear_secrets,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Workspace settings could not be saved securely.",
        ) from exc


@router.delete("")
def reset_workspace_settings():
    try:
        return {
            "status": "reset",
            "settings": WorkspaceSettingsStore.reset(),
        }
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail="Workspace settings could not be reset.",
        ) from exc


@router.post("/integrations/{integration}/test")
async def test_workspace_integration(
    integration: Literal["youtube", "github", "newsapi"],
):
    secret_name = {
        "youtube": "youtube_api_key",
        "github": "github_token",
        "newsapi": "newsapi_key",
    }[integration]
    secret = WorkspaceSettingsStore.active_secret(secret_name)
    if not secret:
        raise HTTPException(
            status_code=422,
            detail={
                "code": f"{integration}_credential_missing",
                "message": f"No {integration} credential is configured.",
                "suggested_action": "Save the credential before testing it.",
                "recoverable": True,
            },
        )

    timeout = max(min(settings.crawler_request_timeout_seconds, 30.0), 5.0)
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False) as client:
            if integration == "youtube":
                response = await client.get(
                    "https://www.googleapis.com/youtube/v3/channels",
                    params={
                        "part": "id",
                        "id": "UCXZCJLdBC09xxGZ6gcdrc6A",
                        "key": secret,
                    },
                )
            elif integration == "github":
                response = await client.get(
                    "https://api.github.com/rate_limit",
                    headers={
                        "Accept": "application/vnd.github+json",
                        "Authorization": f"Bearer {secret}",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "Scope-Intelligence",
                    },
                )
            else:
                response = await client.get(
                    "https://newsapi.org/v2/top-headlines",
                    params={"country": "us", "pageSize": 1},
                    headers={"X-Api-Key": secret},
                )
    except httpx.TimeoutException:
        raise HTTPException(
            status_code=504,
            detail={
                "code": f"{integration}_test_timeout",
                "message": f"{integration} did not respond before the timeout.",
                "recoverable": True,
            },
        ) from None
    except httpx.RequestError:
        raise HTTPException(
            status_code=502,
            detail={
                "code": f"{integration}_network_error",
                "message": f"Scope could not reach {integration} from this computer.",
                "recoverable": True,
            },
        ) from None

    if response.status_code >= 400:
        raise HTTPException(
            status_code=502,
            detail={
                "code": f"{integration}_credential_rejected",
                "message": f"{integration} rejected the saved credential.",
                "suggested_action": "Check the credential, permissions, and provider restrictions.",
                "recoverable": True,
                "provider_status": response.status_code,
            },
        )
    return {
        "ok": True,
        "integration": integration,
        "message": redact_sensitive_text(
            f"{integration.title()} connection verified successfully."
        ),
    }
