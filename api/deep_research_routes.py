from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from psycopg2.errors import UniqueViolation

from agents.ingestion.deep_research import OnionResearchClient, TorResearchError
from config.settings import settings
from intelligence.deep_research import DeepResearchService


router = APIRouter(prefix="/competitors/{competitor_id}/deep-research", tags=["deep-research"])


class DeepResearchCreate(BaseModel):
    query: str | None = Field(default=None, max_length=500)
    max_results: int = Field(default=20, ge=1, le=100)
    max_pages: int = Field(default=8, ge=1, le=50)
    acknowledge_authorized_use: bool

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.strip().split())
        return normalized or None

    @field_validator("acknowledge_authorized_use")
    @classmethod
    def require_acknowledgement(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Authorized-use acknowledgement is required")
        return value


def _ensure_enabled() -> None:
    if not settings.enable_deep_research:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "deep_research_disabled",
                "message": "Deep Research Lab is disabled in this workspace.",
                "suggested_action": "Enable it from Settings > Collection, then start the optional Tor service.",
                "recoverable": True,
            },
        )


@router.get("/overview")
def overview(competitor_id: int):
    try:
        return DeepResearchService.overview(competitor_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail="Competitor not found") from exc


@router.post("/tor/test")
def test_tor(competitor_id: int):
    _ensure_enabled()
    DeepResearchService.overview(competitor_id)
    try:
        result = OnionResearchClient().test_tor()
    except TorResearchError as exc:
        raise HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message, "suggested_action": exc.suggested_action, "recoverable": True}) from exc
    if not result["reachable"] or not result["is_tor"]:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "tor_unavailable",
                "message": "The Tor service is not reachable or is not routing through Tor.",
                "suggested_action": "Run: docker compose --profile deep-research up -d tor",
                "recoverable": True,
            },
        )
    return {"ok": True, "message": "Tor routing verified.", "tor": {"verified": True}}


@router.post("/runs", status_code=status.HTTP_202_ACCEPTED)
def create_run(competitor_id: int, request: DeepResearchCreate, background_tasks: BackgroundTasks):
    _ensure_enabled()
    if request.max_results > settings.deep_research_max_results or request.max_pages > settings.deep_research_max_pages:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "deep_research_budget_exceeded",
                "message": "This run exceeds the workspace Deep Research budget.",
                "suggested_action": "Lower the run budget or change the workspace limit in Settings.",
                "recoverable": True,
            },
        )
    try:
        created = DeepResearchService.create_run(
            competitor_id,
            query=request.query,
            max_results=request.max_results,
            max_pages=request.max_pages,
        )
    except UniqueViolation as exc:
        raise HTTPException(status_code=409, detail={"code": "deep_research_run_active", "message": "A Deep Research run is already active for this company.", "recoverable": True}) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404 if "Competitor" in str(exc) else 422, detail=str(exc)) from exc
    background_tasks.add_task(DeepResearchService.execute_run, competitor_id, int(created["id"]))
    return created


@router.get("/runs")
def list_runs(competitor_id: int, limit: int = Query(default=30, ge=1, le=100)):
    return DeepResearchService.list_runs(competitor_id, limit=limit)


@router.get("/runs/{run_id}")
def get_run(competitor_id: int, run_id: int):
    try:
        return DeepResearchService.get_run(competitor_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/cancel")
def cancel_run(competitor_id: int, run_id: int):
    try:
        return DeepResearchService.cancel_run(competitor_id, run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
