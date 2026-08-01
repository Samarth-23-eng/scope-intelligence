from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator

from agents.ingestion.social.base import SocialConnectorError
from agents.ingestion.social.models import SocialCollectionRequest
from config.settings import settings
from db.postgres import get_connection
from intelligence.security import redact_sensitive
from intelligence.social_collection import SocialCollectionService


router = APIRouter(prefix="/competitors/{competitor_id}/social", tags=["social"])


class SocialRunOptions(BaseModel):
    max_items: int = Field(default=10, ge=1, le=50)
    include_comments: bool = False
    comment_limit: int = Field(default=20, ge=0, le=200)
    include_replies: bool = False
    max_reply_depth: int = Field(default=1, ge=0, le=1)
    include_transcript: bool = False


class SocialRunCreate(BaseModel):
    platform: Literal["youtube"] = "youtube"
    mode: Literal["discover", "account", "evidence"]
    target: str = Field(min_length=1, max_length=4096)
    options: SocialRunOptions = Field(default_factory=SocialRunOptions)

    @field_validator("target")
    @classmethod
    def normalize_target(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Target cannot be empty")
        return normalized


def _ensure_competitor(competitor_id: int) -> None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM competitors WHERE id = %s", (competitor_id,))
            if not cur.fetchone():
                raise HTTPException(status_code=404, detail="Competitor not found")


def _connector_http_error(exc: SocialConnectorError) -> HTTPException:
    status_code = (
        status.HTTP_409_CONFLICT
        if exc.code == "social_run_active"
        else status.HTTP_422_UNPROCESSABLE_ENTITY
    )
    return HTTPException(
        status_code=status_code,
        detail=redact_sensitive(
            {
                "code": exc.code,
                "message": exc.message,
                "suggested_action": exc.suggested_action,
                "recoverable": exc.recoverable,
                "http_status": exc.http_status,
            }
        ),
    )


@router.get("/connectors")
async def list_social_connectors(competitor_id: int):
    _ensure_competitor(competitor_id)
    return SocialCollectionService.get_connectors()


@router.get("/overview")
async def social_overview(competitor_id: int):
    _ensure_competitor(competitor_id)
    return SocialCollectionService.get_overview(competitor_id)


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
async def create_social_run(
    competitor_id: int,
    request: SocialRunCreate,
    background_tasks: BackgroundTasks,
):
    if not settings.enable_social_collection:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "social_collection_disabled",
                "message": "Social Collection Studio is disabled in this installation.",
                "suggested_action": "Set ENABLE_SOCIAL_COLLECTION=true and restart Scope.",
                "recoverable": True,
            },
        )
    options = request.options
    if options.max_items > settings.social_max_items_per_run:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "item_budget_exceeded",
                "message": (
                    f"This installation allows at most "
                    f"{settings.social_max_items_per_run} items per social run."
                ),
                "recoverable": True,
            },
        )
    if options.comment_limit > settings.social_max_comments_per_item:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "comment_budget_exceeded",
                "message": (
                    f"This installation allows at most "
                    f"{settings.social_max_comments_per_item} comments per item."
                ),
                "recoverable": True,
            },
        )
    connector_request = SocialCollectionRequest(
        mode=request.mode,
        target=request.target,
        max_items=options.max_items,
        include_comments=options.include_comments,
        comment_limit=options.comment_limit,
        include_replies=options.include_replies,
        max_reply_depth=options.max_reply_depth,
        include_transcript=options.include_transcript,
    )
    try:
        created = SocialCollectionService.create_run(
            competitor_id,
            platform=request.platform,
            request=connector_request,
        )
    except ValueError as exc:
        if str(exc) == "Competitor not found":
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except SocialConnectorError as exc:
        raise _connector_http_error(exc) from exc
    background_tasks.add_task(
        SocialCollectionService.execute_run,
        competitor_id,
        int(created["id"]),
    )
    return created


@router.get("/runs")
async def list_social_runs(
    competitor_id: int,
    limit: int = Query(default=30, ge=1, le=100),
):
    _ensure_competitor(competitor_id)
    return SocialCollectionService.list_runs(competitor_id, limit=limit)


@router.get("/runs/{social_run_id}")
async def get_social_run(competitor_id: int, social_run_id: int):
    try:
        return SocialCollectionService.get_run(competitor_id, social_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{social_run_id}/cancel")
async def cancel_social_run(competitor_id: int, social_run_id: int):
    try:
        return SocialCollectionService.cancel_run(competitor_id, social_run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/records")
async def list_social_records(
    competitor_id: int,
    kind: Literal["profile", "post", "comment"] = "post",
    platform: str | None = Query(default=None, max_length=80),
    run_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
):
    _ensure_competitor(competitor_id)
    try:
        return SocialCollectionService.list_records(
            competitor_id,
            kind=kind,
            platform=platform,
            run_id=run_id,
            limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
