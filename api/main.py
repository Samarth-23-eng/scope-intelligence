#!/usr/bin/env python3
"""
Scope Intelligence - FastAPI backend
REST API for competitor intelligence data.
"""

import asyncio
import logging
import json
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional, List, Union
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, SecretStr, field_validator
from psycopg2.extras import Json

from config.settings import settings
from db.postgres import get_connection, run_migrations, close_pool, get_pool
from db.redis_client import get_client as get_redis_client, close_client as close_redis_client
from api.graph_routes import router as graph_router
from api.report_routes import router as report_router
from api.social_routes import router as social_router
from api.settings_routes import router as settings_router
from api.deep_research_routes import router as deep_research_router
from intelligence.foundation import RunTracker
from intelligence.retrieval import ChunkIndexer, EvidenceRetriever
from intelligence.collection import CollectionAccessPolicyStore, SourceProfileStore
from intelligence.events import EventFusionEngine
from intelligence.monitoring import MonitoringStore
from intelligence.verification import ClaimVerificationEngine
from intelligence.workspace_settings import WorkspaceSettingsStore
from llm_gateway import (
    LLMConnectionStore,
    LLMProviderError,
    get_active_llm_connection,
    list_provider_models,
    test_provider_connection,
)
from llm_gateway.configuration import PROVIDER_DEFAULTS

logger = logging.getLogger(__name__)


def active_llm_model() -> str:
    return get_active_llm_connection().model


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize and close shared application resources."""
    logger.info("Starting Scope Intelligence API...")
    if not run_migrations():
        raise RuntimeError("Database migrations failed")
    WorkspaceSettingsStore.apply_to_runtime()
    get_pool()
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE investigations
                SET status = 'partial',
                    error = COALESCE(error, 'Interrupted by API restart'),
                    completed_at = COALESCE(completed_at, NOW())
                WHERE status IN ('queued', 'running')
                """
            )
            cur.execute(
                """
                UPDATE pipeline_tasks
                SET status = 'cancelled',
                    error = COALESCE(error, 'Interrupted by API restart'),
                    completed_at = COALESCE(completed_at, NOW())
                WHERE status IN ('pending', 'running', 'retrying')
                  AND run_id IN (
                      SELECT id
                      FROM pipeline_runs
                      WHERE status IN ('queued', 'running')
                  )
                """
            )
            cur.execute(
                """
                UPDATE collection_campaigns
                SET status = 'partial',
                    error = COALESCE(error, 'Interrupted by API restart'),
                    completed_at = COALESCE(completed_at, NOW())
                WHERE status IN ('queued', 'running')
                  AND pipeline_run_id IN (
                      SELECT id
                      FROM pipeline_runs
                      WHERE status IN ('queued', 'running')
                  )
                """
            )
            cur.execute(
                """
                UPDATE pipeline_runs
                SET status = 'partial',
                    error = COALESCE(error, 'Interrupted by API restart'),
                    completed_at = COALESCE(completed_at, NOW())
                WHERE status IN ('queued', 'running')
                """
            )
            conn.commit()
    get_redis_client()
    scheduler_task = None
    app.state.monitoring_jobs = set()
    if settings.monitoring_scheduler_enabled:
        scheduler_task = asyncio.create_task(monitoring_scheduler_loop(app))
    logger.info("API startup complete")
    try:
        yield
    finally:
        logger.info("Shutting down Scope Intelligence API...")
        if scheduler_task:
            scheduler_task.cancel()
            try:
                await scheduler_task
            except asyncio.CancelledError:
                pass
        await close_redis_client()
        close_pool()
        logger.info("API shutdown complete")


app = FastAPI(
    title="Scope Intelligence API",
    version="0.1.0",
    description="Evidence-first, self-hosted company intelligence workspace",
    lifespan=lifespan,
)

# Include report routes
app.include_router(report_router)
app.include_router(graph_router)
app.include_router(social_router)
app.include_router(settings_router)
app.include_router(deep_research_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Pydantic Models
# ============================================================

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    competitors_count: int
    services: dict[str, str]


class CompetitorCreate(BaseModel):
    name: str
    domain: str
    industry: Optional[str] = None
    rss_feeds: List[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        name = name.strip()
        if not name:
            raise ValueError("Company name is required")
        return name

    @field_validator("domain")
    @classmethod
    def normalize_domain(cls, domain: str) -> str:
        value = domain.strip()
        parsed = urlparse(value if "://" in value else f"//{value}")
        if not parsed.hostname:
            raise ValueError("A valid website or domain is required")
        return parsed.hostname.lower().rstrip(".")

    @field_validator("rss_feeds")
    @classmethod
    def validate_rss_feeds(cls, feeds: List[str]) -> List[str]:
        for feed in feeds:
            parsed = urlparse(feed)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError("RSS feeds must use an http or https URL")
        return list(dict.fromkeys(feeds))


class CompetitorResponse(BaseModel):
    id: int
    name: str
    domain: Optional[str]
    industry: Optional[str]
    created_at: str
    updated_at: Optional[str]
    website: Optional[str] = None
    description: Optional[str] = None
    hq: Optional[str] = None
    founded: Optional[int] = None
    executives: list = Field(default_factory=list)
    subsidiaries: list = Field(default_factory=list)
    key_products: list = Field(default_factory=list)
    technologies: list = Field(default_factory=list)
    social_media: dict = Field(default_factory=dict)
    careers_url: Optional[str] = None
    blog_url: Optional[str] = None
    discovery_status: str = "manual"
    domain_verified: bool = False
    identity_context: dict = Field(default_factory=dict)
    access_recovery_enabled: bool = False


class DiscoverRequest(BaseModel):
    name: str = Field(min_length=2, max_length=255)

    @field_validator("name")
    @classmethod
    def validate_discovery_name(cls, name: str) -> str:
        name = name.strip()
        if len(name) < 2:
            raise ValueError("Company name must contain at least two characters")
        return name


class DiscoverResponse(BaseModel):
    competitor: CompetitorResponse
    website: Optional[str]
    rss_feeds: List[str]
    confidence: float
    search_candidates: int
    existing: bool
    resolution_mode: str = "website_assisted"


class InsightResponse(BaseModel):
    id: int
    competitor_id: int
    insight_type: str
    summary: str
    confidence: float
    created_at: str


class EmptySummaryResponse(BaseModel):
    summary: None = None
    message: str = "No summary yet"


class SignalResponse(BaseModel):
    id: int
    competitor_id: int
    signal_type: str
    description: str
    severity: str
    detected_at: str


class PredictionResponse(BaseModel):
    id: int
    competitor_id: int
    prediction: str
    confidence: float
    timeframe: str
    created_at: str


class RawDataResponse(BaseModel):
    id: int
    competitor_id: int
    source: str
    content: str
    collected_at: str
    hash: str
    metadata: dict = Field(default_factory=dict)


class PageChangeResponse(BaseModel):
    id: int
    competitor_id: int
    source_url: str
    title: Optional[str]
    change_type: str
    summary: str
    before_excerpt: Optional[str]
    after_excerpt: Optional[str]
    similarity: float
    significance: float
    detected_at: str
    evidence_id: int
    evidence_snippet: Optional[str]
    evidence_confidence: float
    evidence_collected_at: str


class EntityResponse(BaseModel):
    id: int
    competitor_id: int
    name: str
    entity_type: str
    metadata: dict
    created_at: str
    updated_at: str


class RelationshipEvidenceResponse(BaseModel):
    id: int
    source_url: str
    title: Optional[str]
    snippet: Optional[str]
    confidence: float
    collected_at: str


class RelationshipResponse(BaseModel):
    id: int
    source_entity_id: int
    source_name: str
    source_type: str
    target_entity_id: int
    target_name: str
    target_type: str
    relationship_type: str
    weight: float
    rationale: Optional[str]
    extraction_method: str
    evidence_count: int
    corroboration_score: float = 0
    source_diversity: int = 0
    freshness_score: float = 0
    contradiction_count: int = 0
    risk_level: str = "unassessed"
    status: str
    metadata: dict
    created_at: str
    first_seen_at: str
    last_seen_at: str
    evidence: List[RelationshipEvidenceResponse] = Field(default_factory=list)


class SourceResponse(BaseModel):
    id: int
    competitor_id: int
    url: str
    source_type: str
    priority: int
    monitoring_status: str
    metadata: dict


class PipelineResponse(BaseModel):
    status: str
    competitor_id: int
    run_id: Optional[int] = None


class PipelineStatusResponse(BaseModel):
    status: str
    competitor_id: int
    stage: Optional[str] = None
    stage_status: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    results: dict = Field(default_factory=dict)
    models: dict[str, str] = Field(default_factory=dict)
    error: Optional[str] = None
    run_id: Optional[int] = None


class PipelineDataDeleteResponse(BaseModel):
    status: str
    competitor_id: int
    deleted: dict[str, int] = Field(default_factory=dict)
    reports_deleted: int = 0


class PipelineRunRequest(BaseModel):
    model: Optional[str] = Field(default_factory=active_llm_model)

    @field_validator("model")
    @classmethod
    def validate_model_id(cls, model: Optional[str]) -> Optional[str]:
        if model is None:
            return None
        model = model.strip()
        if not model or len(model) > 200:
            raise ValueError("Invalid model identifier")
        return model


class ModelCatalogResponse(BaseModel):
    models: List[str]
    default: str = Field(default_factory=active_llm_model)


class LLMConnectionUpdate(BaseModel):
    provider: str = Field(min_length=2, max_length=40)
    display_name: Optional[str] = Field(default=None, max_length=120)
    base_url: Optional[str] = Field(default=None, max_length=1000)
    model: str = Field(min_length=1, max_length=255)
    auth_mode: str = Field(default="api_key", max_length=30)
    api_key: Optional[SecretStr] = None
    enabled: bool = True
    clear_secret: bool = False


class LLMConnectionResponse(BaseModel):
    provider: str
    display_name: str
    base_url: str
    model: str
    auth_mode: str
    enabled: bool
    source: str
    last_status: str
    last_error: Optional[str] = None
    last_tested_at: Optional[str] = None
    has_secret: bool
    configured: bool


class LLMConnectionTestResponse(BaseModel):
    ok: bool
    message: str
    response: Optional[str] = None


class DashboardCompetitor(BaseModel):
    id: int
    name: str
    domain: Optional[str]
    industry: Optional[str]
    latest_summary: Optional[str]
    signal_count: int
    prediction_count: int
    last_updated: Optional[str]


class DashboardResponse(BaseModel):
    competitors: List[DashboardCompetitor]
    total_count: int


class PipelineTaskResponse(BaseModel):
    id: int
    run_id: int
    task_key: str
    stage: str
    agent_name: str
    status: str
    attempt: int
    max_attempts: int
    output: dict = Field(default_factory=dict)
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    quality: dict = Field(default_factory=dict)


class PipelineRunDetailResponse(BaseModel):
    id: int
    competitor_id: int
    parent_run_id: Optional[int] = None
    run_type: str
    trigger_type: str
    status: str
    model: Optional[str] = None
    configuration: dict = Field(default_factory=dict)
    summary: dict = Field(default_factory=dict)
    error: Optional[str] = None
    cancel_requested_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str
    tasks: List[PipelineTaskResponse] = Field(default_factory=list)


class PipelineTaskRetryResponse(BaseModel):
    status: str
    competitor_id: int
    source_run_id: int
    source_task_id: int
    retry_run_id: int
    task_key: str


class DocumentResponse(BaseModel):
    id: int
    competitor_id: int
    canonical_url: str
    source_type: str
    source_name: Optional[str] = None
    media_type: str
    title: Optional[str] = None
    author: Optional[str] = None
    published_at: Optional[str] = None
    first_seen_at: str
    last_seen_at: str
    current_version_id: Optional[int] = None
    version_count: int = 0
    chunk_count: int = 0
    indexed_chunk_count: int = 0
    metadata: dict = Field(default_factory=dict)


class ClaimEvidenceItemResponse(BaseModel):
    evidence_id: Optional[int] = None
    document_chunk_id: Optional[int] = None
    stance: str
    excerpt: Optional[str] = None
    confidence: float
    source_url: Optional[str] = None
    title: Optional[str] = None


class ClaimResponse(BaseModel):
    id: int
    competitor_id: int
    pipeline_run_id: Optional[int] = None
    claim_type: str
    subject: Optional[str] = None
    predicate: Optional[str] = None
    object_text: Optional[str] = None
    statement: str
    confidence: float
    status: str
    occurred_at: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    created_at: str
    evidence: List[ClaimEvidenceItemResponse] = Field(default_factory=list)


class EvidenceSearchHitResponse(BaseModel):
    chunk_id: int
    evidence_id: Optional[int] = None
    document_id: int
    document_version_id: int
    source_url: str
    title: Optional[str] = None
    source_type: str
    content: str
    published_at: Optional[str] = None
    collected_at: Optional[str] = None
    score: float
    retrieval_methods: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class SourceHealthResponse(BaseModel):
    id: int
    competitor_id: int
    adapter_name: str
    source_key: str
    status: str
    consecutive_failures: int
    total_attempts: int
    total_items: int
    last_latency_ms: Optional[int] = None
    last_error: Optional[str] = None
    last_attempt_at: Optional[str] = None
    last_success_at: Optional[str] = None
    metadata: dict = Field(default_factory=dict)


class EvidenceOverviewResponse(BaseModel):
    competitor_id: int
    documents: int
    document_versions: int
    chunks: int
    indexed_chunks: int
    claims: int
    cited_claims: int
    citation_coverage: float
    source_adapters: int
    healthy_sources: int


class CollectionCampaignResponse(BaseModel):
    id: int
    competitor_id: int
    pipeline_run_id: Optional[int] = None
    campaign_type: str
    status: str
    strategy: str
    budget: dict = Field(default_factory=dict)
    statistics: dict = Field(default_factory=dict)
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    created_at: str
    frontier: dict[str, int] = Field(default_factory=dict)


class InvestigationCreate(BaseModel):
    title: Optional[str] = None
    question: str
    max_steps: int = Field(default=6, ge=1, le=12)
    scope: dict = Field(default_factory=dict)

    @field_validator("question")
    @classmethod
    def validate_question(cls, question: str) -> str:
        question = question.strip()
        if len(question) < 8 or len(question) > 10000:
            raise ValueError("Research question must be between 8 and 10,000 characters")
        return question

    @field_validator("title")
    @classmethod
    def validate_title(cls, title: Optional[str]) -> Optional[str]:
        if title is None:
            return None
        title = title.strip()
        return title[:500] or None


class SourceProfileResponse(BaseModel):
    id: int
    competitor_id: int
    source_type: str
    profile_url: str
    profile_key: Optional[str] = None
    status: str
    confidence: float
    discovered_from: Optional[str] = None
    last_collected_at: Optional[str] = None
    verified_at: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str


class SourceProfileCreate(BaseModel):
    profile_url: str
    source_type: Optional[str] = None
    profile_key: Optional[str] = None

    @field_validator("profile_url")
    @classmethod
    def validate_profile_url(cls, value: str) -> str:
        parsed = urlparse(value.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Source profile must use an http or https URL")
        return value.strip()


class CollectionErrorResponse(BaseModel):
    id: int
    competitor_id: int
    pipeline_run_id: Optional[int] = None
    campaign_id: Optional[int] = None
    url: Optional[str] = None
    error_code: str
    category: str
    http_status: Optional[int] = None
    severity: str
    engine: Optional[str] = None
    attempts: list = Field(default_factory=list)
    technical_message: str
    user_message: str
    suggested_action: Optional[str] = None
    recoverable: bool
    metadata: dict = Field(default_factory=dict)
    occurrences: int
    first_occurred_at: str
    last_occurred_at: str
    resolved_at: Optional[str] = None
    created_at: str


class AccessRecoveryUpdate(BaseModel):
    enabled: bool


class AccessRecoveryConfigResponse(BaseModel):
    available: bool
    enabled: bool
    experimental: bool = True
    max_attempts_per_campaign: int
    label: str = "Advanced Access Recovery"


class MonitoringProfileUpdate(BaseModel):
    enabled: bool
    cadence_minutes: int = Field(default=1440, ge=15, le=10080)
    focus_topics: List[str] = Field(default_factory=list, max_length=12)
    alert_severities: List[str] = Field(
        default_factory=lambda: ["high", "critical"]
    )

    @field_validator("focus_topics")
    @classmethod
    def validate_focus_topics(cls, values: List[str]) -> List[str]:
        cleaned = list(
            dict.fromkeys(
                value.strip() for value in values
                if isinstance(value, str) and value.strip()
            )
        )
        if any(len(value) > 80 for value in cleaned):
            raise ValueError("Focus topics must be 80 characters or fewer")
        return cleaned[:12]

    @field_validator("alert_severities")
    @classmethod
    def validate_alert_severities(cls, values: List[str]) -> List[str]:
        allowed = {"low", "medium", "high", "critical"}
        cleaned = list(dict.fromkeys(value for value in values if value in allowed))
        if not cleaned:
            raise ValueError("Select at least one alert severity")
        return cleaned


class MonitoringProfileResponse(BaseModel):
    id: int
    competitor_id: int
    enabled: bool
    cadence_minutes: int
    focus_topics: list = Field(default_factory=list)
    alert_severities: list = Field(default_factory=list)
    last_scheduled_at: Optional[str] = None
    next_run_at: Optional[str] = None
    last_run_id: Optional[int] = None
    last_status: str
    last_error: Optional[str] = None
    created_at: str
    updated_at: str


class MonitoringActivityResponse(BaseModel):
    id: int
    monitoring_profile_id: int
    competitor_id: int
    pipeline_run_id: Optional[int] = None
    event_type: str
    status: str
    message: str
    metadata: dict = Field(default_factory=dict)
    created_at: str


class MonitoringOverviewResponse(BaseModel):
    profile: MonitoringProfileResponse
    metrics: dict[str, int]
    activity: List[MonitoringActivityResponse] = Field(default_factory=list)
    latest_run: Optional[dict] = None
    scheduler_online: bool


class ClaimReviewRequest(BaseModel):
    decision: str
    note: Optional[str] = None

    @field_validator("decision")
    @classmethod
    def validate_decision(cls, value: str) -> str:
        if value not in {"supported", "confirmed", "disputed", "stale"}:
            raise ValueError("Invalid review decision")
        return value

    @field_validator("note")
    @classmethod
    def validate_note(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return value.strip()[:5000] or None


class SourceReliabilityUpdate(BaseModel):
    reliability: float = Field(ge=0, le=1)
    basis: str = Field(min_length=3, max_length=2000)


class SourceProfileUpdate(BaseModel):
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, value: str) -> str:
        if value not in {"active", "disabled"}:
            raise ValueError("Status must be active or disabled")
        return value


# ============================================================
# Helper Functions
# ============================================================

def serialize_row(row) -> dict:
    """Convert a database row to a JSON-serializable dict."""
    if row is None:
        return None
    result = dict(row)
    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
    return result


def serialize_rows(rows) -> list:
    """Convert a list of database rows to JSON-serializable dicts."""
    return [serialize_row(row) for row in rows]


def pipeline_status_key(competitor_id: int) -> str:
    return f"pipeline_status:{competitor_id}"


def save_pipeline_status(competitor_id: int, status: dict) -> None:
    get_redis_client().setex(
        pipeline_status_key(competitor_id),
        86400,
        json.dumps(status, default=str),
    )


def load_pipeline_status(competitor_id: int) -> Optional[dict]:
    value = get_redis_client().get(pipeline_status_key(competitor_id))
    return json.loads(value) if value else None


# ============================================================
# Endpoints
# ============================================================

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    services = {"postgres": "down", "redis": "down", "qdrant": "down"}
    count = 0

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) as count FROM competitors")
                result = cur.fetchone()
                count = result["count"] if result else 0
                services["postgres"] = "up"
    except Exception as e:
        logger.error(f"Health check failed: {e}")

    try:
        get_redis_client().ping()
        services["redis"] = "up"
    except Exception as e:
        logger.error(f"Redis health check failed: {e}")

    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            response = await client.get(f"{settings.qdrant_url.rstrip('/')}/healthz")
            response.raise_for_status()
            services["qdrant"] = "up"
    except Exception as e:
        logger.error(f"Qdrant health check failed: {e}")

    return HealthResponse(
        status="ok" if all(state == "up" for state in services.values()) else "degraded",
        timestamp=datetime.utcnow().isoformat(),
        competitors_count=count,
        services=services,
    )


@app.get("/competitors", response_model=List[CompetitorResponse])
async def list_competitors():
    """List all competitors."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, domain, industry, created_at, updated_at,
                           website, description, hq, founded, executives, subsidiaries,
                           key_products, technologies, social_media, careers_url, blog_url,
                           discovery_status, domain_verified, identity_context,
                           access_recovery_enabled
                    FROM competitors
                    ORDER BY id
                """)
                rows = cur.fetchall()
                return serialize_rows(rows)
    except Exception as e:
        logger.error(f"Failed to list competitors: {e}")
        raise HTTPException(status_code=500, detail="Failed to list competitors")


@app.post("/competitors", response_model=CompetitorResponse, status_code=201)
async def create_competitor(competitor: CompetitorCreate):
    """Create a new competitor."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO competitors (name, domain, industry, website, discovery_status)
                    VALUES (%s, %s, %s, %s, 'manual')
                    RETURNING id, name, domain, industry, created_at, updated_at,
                              website, description, hq, founded, executives, subsidiaries,
                              key_products, technologies, social_media, careers_url, blog_url,
                              discovery_status
                """, (
                    competitor.name,
                    competitor.domain,
                    competitor.industry,
                    f"https://{competitor.domain}",
                ))
                row = cur.fetchone()
                if competitor.rss_feeds:
                    cur.executemany(
                        """
                        INSERT INTO competitor_rss_feeds (competitor_id, feed_url)
                        VALUES (%s, %s)
                        ON CONFLICT (competitor_id, feed_url) DO NOTHING
                        """,
                        [(row["id"], feed) for feed in competitor.rss_feeds],
                    )
                    cur.executemany(
                        """
                        INSERT INTO sources (competitor_id, url, source_type, priority, monitoring_status)
                        VALUES (%s, %s, 'rss', 70, 'active')
                        ON CONFLICT DO NOTHING
                        """,
                        [(row["id"], feed) for feed in competitor.rss_feeds],
                    )
                conn.commit()
                return serialize_row(row)
    except Exception as e:
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Competitor with this domain already exists")
        logger.error(f"Failed to create competitor: {e}")
        raise HTTPException(status_code=500, detail="Failed to create competitor")


@app.post("/discover", response_model=DiscoverResponse)
def discover_company(request: DiscoverRequest):
    """Discover and persist a competitor from only its company name."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, domain, industry, created_at, updated_at,
                           website, description, hq, founded, executives, subsidiaries,
                           key_products, technologies, social_media, careers_url, blog_url,
                           discovery_status, domain_verified, identity_context,
                           access_recovery_enabled
                    FROM competitors
                    WHERE LOWER(name) = LOWER(%s)
                    LIMIT 1
                    """,
                    (request.name,),
                )
                existing = cur.fetchone()
                if existing:
                    cur.execute(
                        "SELECT feed_url FROM competitor_rss_feeds WHERE competitor_id = %s ORDER BY id",
                        (existing["id"],),
                    )
                    feeds = [row["feed_url"] for row in cur.fetchall()]
                    website = existing["website"]
                    if website:
                        cur.execute(
                            """
                            INSERT INTO sources (
                                competitor_id, url, source_type, priority,
                                monitoring_status
                            )
                            VALUES (%s, %s, 'website', 100, 'active')
                            ON CONFLICT DO NOTHING
                            """,
                            (existing["id"], website),
                        )
                    conn.commit()
                    return DiscoverResponse(
                        competitor=serialize_row(existing),
                        website=website,
                        rss_feeds=feeds,
                        confidence=1.0,
                        search_candidates=0,
                        existing=True,
                        resolution_mode=(
                            existing.get("identity_context", {}).get("resolution_mode")
                            or "website_assisted"
                        ),
                    )

        from agents.discovery import CompanyDiscoveryAgent

        agent = CompanyDiscoveryAgent(request.name)
        try:
            result = agent.discover()
        finally:
            agent.close()

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO competitors (
                        name, domain, website, discovery_status,
                        domain_verified, identity_context
                    )
                    VALUES (%s, %s, %s, 'discovered', %s, %s)
                    RETURNING id, name, domain, industry, created_at, updated_at,
                              website, description, hq, founded, executives, subsidiaries,
                              key_products, technologies, social_media, careers_url, blog_url,
                              discovery_status, domain_verified, identity_context,
                              access_recovery_enabled
                    """,
                    (
                        result.name,
                        result.domain,
                        result.website,
                        result.domain_verified,
                        Json(result.identity_context),
                    ),
                )
                competitor = cur.fetchone()
                if result.website:
                    cur.execute(
                        """
                        INSERT INTO sources (
                            competitor_id, url, source_type, priority,
                            monitoring_status
                        )
                        VALUES (%s, %s, 'website', 100, 'active')
                        ON CONFLICT DO NOTHING
                        """,
                        (competitor["id"], result.website),
                    )
                if result.rss_feeds:
                    cur.executemany(
                        """
                        INSERT INTO competitor_rss_feeds (competitor_id, feed_url)
                        VALUES (%s, %s)
                        ON CONFLICT (competitor_id, feed_url) DO NOTHING
                        """,
                        [(competitor["id"], feed) for feed in result.rss_feeds],
                    )
                    cur.executemany(
                        """
                        INSERT INTO sources (competitor_id, url, source_type, priority, monitoring_status)
                        VALUES (%s, %s, 'rss', 70, 'active')
                        ON CONFLICT DO NOTHING
                        """,
                        [(competitor["id"], feed) for feed in result.rss_feeds],
                    )
                conn.commit()

        if result.source_urls:
            from intelligence.collection import SourceProfileStore

            SourceProfileStore(competitor["id"]).discover_urls(
                result.source_urls,
                discovered_from="name_discovery",
                confidence=0.6,
            )

        return DiscoverResponse(
            competitor=serialize_row(competitor),
            website=result.website,
            rss_feeds=result.rss_feeds,
            confidence=result.confidence,
            search_candidates=result.search_candidates,
            existing=False,
            resolution_mode=result.identity_context["resolution_mode"],
        )
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Company discovery failed for {request.name}: {e}")
        raise HTTPException(status_code=502, detail="Company discovery failed")


@app.get("/competitors/{competitor_id}", response_model=CompetitorResponse)
async def get_competitor(competitor_id: int):
    """Get a single competitor by ID."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, domain, industry, created_at, updated_at,
                           website, description, hq, founded, executives, subsidiaries,
                           key_products, technologies, social_media, careers_url, blog_url,
                           discovery_status, domain_verified, identity_context,
                           access_recovery_enabled
                    FROM competitors
                    WHERE id = %s
                """, (competitor_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Competitor not found")
                return serialize_row(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get competitor")


@app.get("/competitors/{competitor_id}/insights", response_model=List[InsightResponse])
async def get_competitor_insights(competitor_id: int):
    """Get last 10 insights for a competitor."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, competitor_id, insight_type, summary, confidence, created_at
                    FROM insights
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    LIMIT 10
                """, (competitor_id,))
                rows = cur.fetchall()
                return serialize_rows(rows)
    except Exception as e:
        logger.error(f"Failed to get insights for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get insights")


@app.get("/competitors/{competitor_id}/signals", response_model=List[SignalResponse])
async def get_competitor_signals(
    competitor_id: int,
    severity: Optional[str] = None
):
    """Get last 20 signals for a competitor, optionally filtered by severity."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if severity:
                    cur.execute("""
                        SELECT id, competitor_id, signal_type, description, severity, detected_at
                        FROM signals
                        WHERE competitor_id = %s AND severity = %s
                        ORDER BY detected_at DESC
                        LIMIT 20
                    """, (competitor_id, severity))
                else:
                    cur.execute("""
                        SELECT id, competitor_id, signal_type, description, severity, detected_at
                        FROM signals
                        WHERE competitor_id = %s
                        ORDER BY detected_at DESC
                        LIMIT 20
                    """, (competitor_id,))
                rows = cur.fetchall()
                return serialize_rows(rows)
    except Exception as e:
        logger.error(f"Failed to get signals for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get signals")


@app.get("/competitors/{competitor_id}/predictions", response_model=List[PredictionResponse])
async def get_competitor_predictions(competitor_id: int):
    """Get last 10 predictions for a competitor."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, competitor_id, prediction, confidence, timeframe, created_at
                    FROM predictions
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    LIMIT 10
                """, (competitor_id,))
                rows = cur.fetchall()
                return serialize_rows(rows)
    except Exception as e:
        logger.error(f"Failed to get predictions for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get predictions")


@app.get("/competitors/{competitor_id}/raw_data", response_model=List[RawDataResponse])
async def get_competitor_raw_data(
    competitor_id: int,
    source: Optional[str] = None
):
    """Get last 20 raw data records for a competitor, optionally filtered by source prefix."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if source:
                    cur.execute("""
                        SELECT id, competitor_id, source, content, collected_at, hash, metadata
                        FROM raw_data
                        WHERE competitor_id = %s AND source LIKE %s
                        ORDER BY collected_at DESC
                        LIMIT 20
                    """, (competitor_id, f"{source}%"))
                else:
                    cur.execute("""
                        SELECT id, competitor_id, source, content, collected_at, hash, metadata
                        FROM raw_data
                        WHERE competitor_id = %s
                        ORDER BY collected_at DESC
                        LIMIT 20
                    """, (competitor_id,))
                rows = cur.fetchall()
                return serialize_rows(rows)
    except Exception as e:
        logger.error(f"Failed to get raw data for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get raw data")


@app.get(
    "/competitors/{competitor_id}/changes",
    response_model=List[PageChangeResponse],
)
async def get_competitor_changes(
    competitor_id: int,
    change_type: Optional[str] = None,
):
    """Return recent meaningful website changes with their supporting evidence."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT changes.id,
                           changes.competitor_id,
                           changes.source_url,
                           snapshots.title,
                           changes.change_type,
                           changes.summary,
                           changes.before_excerpt,
                           changes.after_excerpt,
                           changes.similarity,
                           changes.significance,
                           changes.detected_at,
                           evidence.id AS evidence_id,
                           evidence.snippet AS evidence_snippet,
                           evidence.confidence AS evidence_confidence,
                           evidence.collected_at AS evidence_collected_at
                    FROM page_changes AS changes
                    JOIN page_snapshots AS snapshots
                      ON snapshots.id = changes.current_snapshot_id
                    JOIN evidence
                      ON evidence.id = changes.evidence_id
                    WHERE changes.competitor_id = %s
                      AND (%s IS NULL OR changes.change_type = %s)
                    ORDER BY changes.detected_at DESC, changes.id DESC
                    LIMIT 100
                    """,
                    (competitor_id, change_type, change_type),
                )
                return serialize_rows(cur.fetchall())
    except Exception as e:
        logger.error(f"Failed to get changes for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get competitor changes")


@app.get("/competitors/{competitor_id}/entities", response_model=List[EntityResponse])
async def get_competitor_entities(competitor_id: int):
    """Return all resolved entities for a competitor."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, competitor_id, name, entity_type, metadata, created_at, updated_at
                    FROM entities
                    WHERE competitor_id = %s
                    ORDER BY entity_type, name
                    """,
                    (competitor_id,),
                )
                return serialize_rows(cur.fetchall())
    except Exception as e:
        logger.error(f"Failed to get entities for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get entities")


@app.get(
    "/competitors/{competitor_id}/relationships",
    response_model=List[RelationshipResponse],
)
async def get_competitor_relationships(competitor_id: int):
    """Return named graph edges for a competitor."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT r.id,
                           r.source_entity_id, source.name AS source_name,
                           source.entity_type AS source_type,
                           r.target_entity_id, target.name AS target_name,
                           target.entity_type AS target_type,
                           r.relationship_type, r.weight, r.rationale,
                           r.extraction_method, r.evidence_count,
                           r.corroboration_score, r.source_diversity,
                           r.freshness_score, r.contradiction_count,
                           r.risk_level,
                           CASE
                               WHEN r.status = 'active'
                                AND r.last_seen_at < NOW() - INTERVAL '90 days'
                               THEN 'stale'
                               ELSE r.status
                           END AS status,
                           r.metadata, r.created_at, r.first_seen_at, r.last_seen_at,
                           COALESCE(
                               (
                                   SELECT JSONB_AGG(
                                       JSONB_BUILD_OBJECT(
                                           'id', evidence.id,
                                           'source_url', evidence.source_url,
                                           'title', evidence.title,
                                           'snippet', relationship_evidence.support_excerpt,
                                           'confidence', relationship_evidence.confidence,
                                           'collected_at', evidence.collected_at
                                       )
                                       ORDER BY evidence.collected_at DESC
                                   )
                                   FROM relationship_evidence
                                   JOIN evidence
                                     ON evidence.id = relationship_evidence.evidence_id
                                   WHERE relationship_evidence.relationship_id = r.id
                               ),
                               '[]'::jsonb
                           ) AS evidence
                    FROM relationships r
                    JOIN entities source ON source.id = r.source_entity_id
                    JOIN entities target ON target.id = r.target_entity_id
                    WHERE source.competitor_id = %s AND target.competitor_id = %s
                    ORDER BY
                        CASE
                            WHEN r.status = 'active'
                             AND r.last_seen_at < NOW() - INTERVAL '90 days'
                            THEN 'stale'
                            ELSE r.status
                        END,
                        r.weight DESC, r.relationship_type, target.name
                    """,
                    (competitor_id, competitor_id),
                )
                return serialize_rows(cur.fetchall())
    except Exception as e:
        logger.error(f"Failed to get relationships for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get relationships")


@app.get("/competitors/{competitor_id}/sources", response_model=List[SourceResponse])
async def get_competitor_sources(competitor_id: int):
    """Return configured monitoring sources for a competitor."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, competitor_id, url, source_type, priority, monitoring_status, metadata
                    FROM sources
                    WHERE competitor_id = %s
                    ORDER BY priority DESC, id
                    """,
                    (competitor_id,),
                )
                return cur.fetchall()
    except Exception as e:
        logger.error(f"Failed to get sources for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get sources")


@app.post("/competitors/{competitor_id}/resolve_entities")
def resolve_competitor_entities(competitor_id: int):
    """Run entity and relationship extraction against already collected evidence."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT name FROM competitors WHERE id = %s", (competitor_id,))
                competitor = cur.fetchone()
                if not competitor:
                    raise HTTPException(status_code=404, detail="Competitor not found")

        from agents.discovery.entity_resolver import EntityResolverAgent
        from intelligence.graph import RelationshipIntelligenceEngine

        resolver = EntityResolverAgent(competitor_id, competitor["name"])
        resolution = resolver.collect()
        fusion = RelationshipIntelligenceEngine(competitor_id).analyze()
        return {"resolution": resolution, "relationship_intelligence": fusion}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Entity resolution failed for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Entity resolution failed")


@app.get("/competitors/{competitor_id}/relationship_intelligence")
async def get_relationship_intelligence(competitor_id: int):
    try:
        from intelligence.graph import RelationshipIntelligenceEngine

        result = RelationshipIntelligenceEngine(competitor_id).latest()
        if result:
            return result
        return {
            "snapshot_id": None,
            "competitor_id": competitor_id,
            "entity_count": 0,
            "relationship_count": 0,
            "component_count": 0,
            "disputed_relationships": 0,
            "weak_relationships": 0,
            "metrics": {
                "strategic_nodes": [],
                "duplicate_candidates": [],
                "risk_distribution": {
                    "low": 0,
                    "medium": 0,
                    "high": 0,
                    "critical": 0,
                },
            },
            "created_at": None,
        }
    except Exception as exc:
        logger.error("Failed to load relationship intelligence: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to load relationship intelligence",
        )


@app.post("/competitors/{competitor_id}/relationships/analyze")
def analyze_competitor_relationships(competitor_id: int):
    try:
        from intelligence.graph import RelationshipIntelligenceEngine

        return RelationshipIntelligenceEngine(competitor_id).analyze()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Relationship intelligence analysis failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Relationship intelligence analysis failed",
        )


def load_investigation_detail(
    competitor_id: int,
    investigation_id: int,
) -> dict | None:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT *
                FROM investigations
                WHERE id = %s AND competitor_id = %s
                """,
                (investigation_id, competitor_id),
            )
            investigation = cur.fetchone()
            if not investigation:
                return None
            cur.execute(
                """
                SELECT *
                FROM investigation_steps
                WHERE investigation_id = %s
                ORDER BY step_index
                """,
                (investigation_id,),
            )
            steps = serialize_rows(cur.fetchall() or [])
            cur.execute(
                """
                SELECT *
                FROM investigation_findings
                WHERE investigation_id = %s
                ORDER BY confidence DESC, id
                """,
                (investigation_id,),
            )
            findings = serialize_rows(cur.fetchall() or [])
            cur.execute(
                """
                SELECT *
                FROM investigation_citations
                WHERE investigation_id = %s
                ORDER BY step_id, finding_id, relevance DESC, id
                """,
                (investigation_id,),
            )
            citations = serialize_rows(cur.fetchall() or [])
    result = serialize_row(investigation)
    result["steps"] = steps
    result["findings"] = findings
    result["citations"] = citations
    return result


@app.get("/competitors/{competitor_id}/investigations")
async def list_investigations(competitor_id: int, limit: int = 50):
    investigation_limit = min(max(limit, 1), 200)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM investigations
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (competitor_id, investigation_limit),
                )
                return serialize_rows(cur.fetchall() or [])
    except Exception as exc:
        logger.error("Failed to list investigations: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to list investigations")


@app.post("/competitors/{competitor_id}/investigations")
async def create_investigation(
    competitor_id: int,
    request: InvestigationCreate,
):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, name FROM competitors WHERE id = %s",
                    (competitor_id,),
                )
                competitor = cur.fetchone()
                if not competitor:
                    raise HTTPException(status_code=404, detail="Competitor not found")
                title = request.title or request.question[:120]
                cur.execute(
                    """
                    INSERT INTO investigations (
                        competitor_id, title, question, scope,
                        status, model, max_steps
                    )
                    VALUES (%s, %s, %s, %s, 'draft', %s, %s)
                    RETURNING id
                    """,
                    (
                        competitor_id,
                        title,
                        request.question,
                        Json(request.scope),
                        active_llm_model(),
                        request.max_steps,
                    ),
                )
                investigation_id = int(cur.fetchone()["id"])
                conn.commit()
        return load_investigation_detail(competitor_id, investigation_id)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to create investigation: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create investigation")


@app.get("/competitors/{competitor_id}/investigations/{investigation_id}")
async def get_investigation(competitor_id: int, investigation_id: int):
    try:
        result = load_investigation_detail(competitor_id, investigation_id)
        if not result:
            raise HTTPException(status_code=404, detail="Investigation not found")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to load investigation: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load investigation")


def execute_investigation(
    competitor_id: int,
    competitor_name: str,
    investigation_id: int,
):
    from agents.analysis.investigator import InvestigationAgent

    try:
        InvestigationAgent(
            competitor_id,
            competitor_name,
            active_llm_model(),
        ).run(investigation_id)
    except Exception as exc:
        logger.exception("Investigation %s failed: %s", investigation_id, exc)


@app.post("/competitors/{competitor_id}/investigations/{investigation_id}/run")
def run_investigation(
    competitor_id: int,
    investigation_id: int,
    background_tasks: BackgroundTasks,
):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT investigation.status, competitor.name
                    FROM investigations investigation
                    JOIN competitors competitor
                      ON competitor.id = investigation.competitor_id
                    WHERE investigation.id = %s
                      AND investigation.competitor_id = %s
                    """,
                    (investigation_id, competitor_id),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Investigation not found")
                if row["status"] in {"queued", "running"}:
                    raise HTTPException(
                        status_code=409,
                        detail="Investigation is already running",
                    )
                cur.execute(
                    """
                    UPDATE investigations
                    SET status = 'queued', error = NULL,
                        cancel_requested_at = NULL
                    WHERE id = %s
                    """,
                    (investigation_id,),
                )
                conn.commit()
        background_tasks.add_task(
            execute_investigation,
            competitor_id,
            row["name"],
            investigation_id,
        )
        return {
            "status": "queued",
            "competitor_id": competitor_id,
            "investigation_id": investigation_id,
            "model": active_llm_model(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to queue investigation: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to queue investigation")


@app.post("/competitors/{competitor_id}/investigations/{investigation_id}/cancel")
def cancel_investigation(competitor_id: int, investigation_id: int):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE investigations
                    SET cancel_requested_at = NOW()
                    WHERE id = %s AND competitor_id = %s
                      AND status IN ('queued', 'running')
                    RETURNING id
                    """,
                    (investigation_id, competitor_id),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(
                        status_code=409,
                        detail="Investigation is not currently running",
                    )
                conn.commit()
        return {
            "status": "cancellation_requested",
            "competitor_id": competitor_id,
            "investigation_id": investigation_id,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to cancel investigation: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to cancel investigation")


@app.get(
    "/competitors/{competitor_id}/summary",
    response_model=Union[InsightResponse, EmptySummaryResponse],
)
async def get_competitor_summary(competitor_id: int):
    """Get the latest weekly_summary insight for a competitor."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, competitor_id, insight_type, summary, confidence, created_at
                    FROM insights
                    WHERE competitor_id = %s AND insight_type = 'weekly_summary'
                    ORDER BY created_at DESC
                    LIMIT 1
                """, (competitor_id,))
                row = cur.fetchone()
                if not row:
                    return EmptySummaryResponse()
                return serialize_row(row)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get summary for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to get summary")


def run_competitor_pipeline(
    competitor_id: int,
    competitor_name: str,
    domain: Optional[str],
    rss_feeds: List[str],
    started_at: str,
    model: str,
    run_id: int,
    focus_topics: Optional[List[str]] = None,
):
    """Background task to run the full pipeline for a competitor."""
    try:
        from agents.orchestrator.competitor_pipeline import CompetitorPipeline
        partial_results = {}

        def report_progress(stage: str, stage_status: str, data: Optional[dict]) -> None:
            if data is not None:
                partial_results[stage] = data
            save_pipeline_status(
                competitor_id,
                {
                    "status": "running",
                    "competitor_id": competitor_id,
                    "stage": stage,
                    "stage_status": stage_status,
                    "started_at": started_at,
                    "results": partial_results,
                    "models": {"all_agents": model},
                    "run_id": run_id,
                },
            )

        pipeline = CompetitorPipeline(
            competitor_id=competitor_id,
            competitor_name=competitor_name,
            domain=domain,
            rss_feeds=rss_feeds,
            progress_callback=report_progress,
            model=model,
            run_id=run_id,
            focus_topics=focus_topics,
        )
        result = pipeline.run_full_pipeline()
        final_status = (
            "cancelled"
            if result.get("cancelled")
            else "completed" if result["success"] else "partial"
        )
        save_pipeline_status(
            competitor_id,
            {
                "status": final_status,
                "competitor_id": competitor_id,
                "stage": "complete",
                "stage_status": final_status,
                "started_at": started_at,
                "finished_at": datetime.utcnow().isoformat(),
                "results": result,
                "models": {"all_agents": model},
                "run_id": run_id,
            },
        )
        logger.info(f"Pipeline completed for {competitor_name}")
    except Exception as e:
        save_pipeline_status(
            competitor_id,
            {
                "status": "failed",
                "competitor_id": competitor_id,
                "stage": "failed",
                "stage_status": "failed",
                "started_at": started_at,
                "finished_at": datetime.utcnow().isoformat(),
                "results": {},
                "models": {"all_agents": model},
                "error": str(e),
                "run_id": run_id,
            },
        )
        RunTracker(run_id).finish_run("failed", error=str(e))
        logger.error(f"Pipeline failed for {competitor_name}: {e}")


def run_competitor_task_retry(
    *,
    competitor_id: int,
    competitor_name: str,
    domain: Optional[str],
    rss_feeds: List[str],
    model: str,
    focus_topics: List[str],
    source_run_id: int,
    source_task_id: int,
    retry_run_id: int,
    task_key: str,
) -> None:
    """Execute one failed task in an auditable child run."""
    tracker = RunTracker(retry_run_id)
    tracker.start_run()
    try:
        from agents.orchestrator.competitor_pipeline import CompetitorPipeline

        pipeline = CompetitorPipeline(
            competitor_id=competitor_id,
            competitor_name=competitor_name,
            domain=domain,
            rss_feeds=rss_feeds,
            model=model,
            run_id=retry_run_id,
            focus_topics=focus_topics,
        )
        pipeline.retry_task(task_key, source_run_id=source_run_id)
        tracker.finish_run(
            "completed",
            summary={
                "retry": {
                    "source_run_id": source_run_id,
                    "source_task_id": source_task_id,
                    "task_key": task_key,
                }
            },
        )
        logger.info(
            "Retried task %s from run %s in child run %s",
            task_key,
            source_run_id,
            retry_run_id,
        )
    except Exception as exc:
        tracker.finish_run(
            "failed",
            error=str(exc),
            summary={
                "retry": {
                    "source_run_id": source_run_id,
                    "source_task_id": source_task_id,
                    "task_key": task_key,
                }
            },
        )
        logger.exception(
            "Task retry %s failed in child run %s: %s",
            task_key,
            retry_run_id,
            exc,
        )


def execute_monitoring_run(
    profile: dict,
    activity_id: int,
    *,
    trigger_type: str,
) -> None:
    """Create and execute a full pipeline from a monitoring event."""
    profile_id = int(profile["id"])
    competitor_id = int(profile["competitor_id"])
    try:
        current_status = load_pipeline_status(competitor_id)
        if current_status and current_status.get("status") == "running":
            MonitoringStore.mark_skipped(
                profile_id,
                activity_id,
                "Monitoring window skipped because a pipeline is already running",
            )
            return

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, name, domain
                    FROM competitors
                    WHERE id = %s
                    """,
                    (competitor_id,),
                )
                competitor = cur.fetchone()
                if not competitor:
                    MonitoringStore.mark_skipped(
                        profile_id,
                        activity_id,
                        "Monitoring target no longer exists",
                    )
                    return
                cur.execute(
                    """
                    SELECT feed_url
                    FROM competitor_rss_feeds
                    WHERE competitor_id = %s
                    ORDER BY id
                    """,
                    (competitor_id,),
                )
                rss_feeds = [row["feed_url"] for row in cur.fetchall()]

        run_tracker = RunTracker()
        model = active_llm_model()
        run_id = run_tracker.create_run(
            competitor_id,
            run_type="full",
            trigger_type=trigger_type,
            model=model,
            configuration={
                "rss_feeds": rss_feeds,
                "shared_model": model,
                "monitoring_profile_id": profile_id,
                "focus_topics": profile.get("focus_topics", []),
                "alert_severities": profile.get("alert_severities", []),
            },
        )
        MonitoringStore.attach_run(profile_id, activity_id, run_id)
        started_at = datetime.utcnow().isoformat()
        save_pipeline_status(
            competitor_id,
            {
                "status": "running",
                "competitor_id": competitor_id,
                "stage": "queued",
                "stage_status": "waiting",
                "started_at": started_at,
                "results": {},
                "models": {"all_agents": model},
                "run_id": run_id,
            },
        )
        run_competitor_pipeline(
            competitor_id=competitor_id,
            competitor_name=competitor["name"],
            domain=competitor["domain"],
            rss_feeds=rss_feeds,
            started_at=started_at,
            model=model,
            run_id=run_id,
            focus_topics=profile.get("focus_topics", []),
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT status, error FROM pipeline_runs WHERE id = %s",
                    (run_id,),
                )
                final_run = cur.fetchone()
        final_status = final_run["status"] if final_run else "failed"
        final_error = final_run["error"] if final_run else "Pipeline status unavailable"
        MonitoringStore.finish_run(
            profile_id,
            activity_id,
            run_id,
            status=final_status,
            error=final_error,
        )
    except Exception as exc:
        logger.exception(
            "Monitoring run failed for competitor %s: %s",
            competitor_id,
            exc,
        )
        MonitoringStore.mark_skipped(profile_id, activity_id, str(exc))


async def monitoring_scheduler_loop(app: FastAPI) -> None:
    """Claim due profiles and run them without blocking API requests."""
    poll_seconds = max(settings.monitoring_scheduler_poll_seconds, 10)
    while True:
        try:
            await asyncio.sleep(poll_seconds)
            claimed = await asyncio.to_thread(MonitoringStore.claim_due_profiles)
            for item in claimed:
                task = asyncio.create_task(
                    asyncio.to_thread(
                        execute_monitoring_run,
                        item["profile"],
                        item["activity_id"],
                        trigger_type="scheduled_monitor",
                    )
                )
                app.state.monitoring_jobs.add(task)
                task.add_done_callback(app.state.monitoring_jobs.discard)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.exception("Monitoring scheduler iteration failed: %s", exc)


@app.post("/competitors/{competitor_id}/run_pipeline", response_model=PipelineResponse)
async def run_pipeline(
    competitor_id: int,
    background_tasks: BackgroundTasks,
    request: Optional[PipelineRunRequest] = None,
):
    """Trigger immediate full pipeline run for a competitor."""
    try:
        current_status = load_pipeline_status(competitor_id)
        if current_status and current_status.get("status") == "running":
            return PipelineResponse(
                status="already_running",
                competitor_id=competitor_id,
                run_id=current_status.get("run_id"),
            )

        # First, get the competitor details
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, domain
                    FROM competitors
                    WHERE id = %s
                """, (competitor_id,))
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Competitor not found")

                cur.execute(
                    "SELECT feed_url FROM competitor_rss_feeds WHERE competitor_id = %s ORDER BY id",
                    (competitor_id,),
                )
                rss_feeds = [feed["feed_url"] for feed in cur.fetchall()]

        model = (request or PipelineRunRequest()).model or active_llm_model()
        run_tracker = RunTracker()
        run_id = run_tracker.create_run(
            competitor_id,
            run_type="full",
            trigger_type="manual",
            model=model,
            configuration={"rss_feeds": rss_feeds, "shared_model": model},
        )
        started_at = datetime.utcnow().isoformat()
        save_pipeline_status(
            competitor_id,
            {
                "status": "running",
                "competitor_id": competitor_id,
                "stage": "queued",
                "stage_status": "waiting",
                "started_at": started_at,
                "results": {},
                "models": {"all_agents": model},
                "run_id": run_id,
            },
        )

        background_tasks.add_task(
            run_competitor_pipeline,
            competitor_id=row["id"],
            competitor_name=row["name"],
            domain=row["domain"],
            rss_feeds=rss_feeds,
            started_at=started_at,
            model=model,
            run_id=run_id,
        )

        return PipelineResponse(
            status="started",
            competitor_id=competitor_id,
            run_id=run_id,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to trigger pipeline for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to trigger pipeline")


@app.get("/settings/llm")
def get_llm_connection():
    """Return the active model connection without exposing its credential."""
    return get_active_llm_connection().public_dict()


@app.get("/settings/llm/providers")
def get_llm_provider_presets():
    return {
        "providers": [
            {
                "id": provider,
                "label": values["label"],
                "base_url": values["base_url"],
                "default_auth_mode": (
                    "none" if provider in {"ollama", "lmstudio"} else "api_key"
                ),
            }
            for provider, values in PROVIDER_DEFAULTS.items()
        ],
        "auth_modes": [
            {
                "id": "api_key",
                "label": "API key",
                "description": "Bring your own provider key.",
            },
            {
                "id": "bearer",
                "label": "Bearer / OAuth token",
                "description": "Use an existing access token issued by your provider.",
            },
            {
                "id": "none",
                "label": "No authentication",
                "description": "For a trusted local model server only.",
            },
        ],
    }


@app.put("/settings/llm", response_model=LLMConnectionResponse)
def update_llm_connection(request: LLMConnectionUpdate):
    """Encrypt and save the single model connection shared by all agents."""
    try:
        saved = LLMConnectionStore().save(
            provider=request.provider,
            display_name=request.display_name,
            base_url=request.base_url,
            model=request.model,
            auth_mode=request.auth_mode,
            api_key=request.api_key.get_secret_value() if request.api_key else None,
            enabled=request.enabled,
            clear_secret=request.clear_secret,
        )
        return LLMConnectionResponse(**saved.public_dict())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Could not save LLM connection: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="The model connection could not be saved securely.",
        ) from exc


@app.post("/settings/llm/test", response_model=LLMConnectionTestResponse)
async def test_llm_connection():
    """Run a minimal real completion against the active provider."""
    connection = get_active_llm_connection()
    try:
        result = await asyncio.to_thread(test_provider_connection, connection)
        if connection.source == "saved":
            LLMConnectionStore().record_test(ok=True)
        return LLMConnectionTestResponse(**result)
    except LLMProviderError as exc:
        message = str(exc)
        if connection.source == "saved":
            LLMConnectionStore().record_test(ok=False, error=message)
        raise HTTPException(status_code=502, detail=message) from exc
    except Exception as exc:
        logger.exception("LLM connection test failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="The model connection test failed unexpectedly.",
        ) from exc


@app.delete("/settings/llm")
def reset_llm_connection():
    """Remove the saved connection and return to environment-based configuration."""
    try:
        LLMConnectionStore().delete()
        return {
            "status": "reset",
            "connection": get_active_llm_connection().public_dict(),
        }
    except Exception as exc:
        logger.exception("Could not reset LLM connection: %s", exc)
        raise HTTPException(status_code=500, detail="Could not reset the model connection.") from exc


@app.get("/models", response_model=ModelCatalogResponse)
async def get_model_catalog():
    """Return models exposed by the active shared provider."""
    connection = get_active_llm_connection()
    model_ids = await asyncio.to_thread(list_provider_models, connection)
    if connection.model not in model_ids:
        model_ids.insert(0, connection.model)
    return ModelCatalogResponse(models=model_ids, default=connection.model)


@app.get(
    "/competitors/{competitor_id}/pipeline_status",
    response_model=PipelineStatusResponse,
)
async def get_pipeline_status(competitor_id: int):
    """Return the latest pipeline state and per-stage results."""
    status = load_pipeline_status(competitor_id)
    if status:
        return status
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT id, status, started_at, completed_at, summary, error
                    FROM pipeline_runs
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (competitor_id,),
                )
                row = cur.fetchone()
        if row:
            summary = row.get("summary") or {}
            return PipelineStatusResponse(
                status=row["status"],
                competitor_id=competitor_id,
                stage="complete" if row["status"] not in {"queued", "running"} else "queued",
                stage_status=row["status"],
                started_at=row["started_at"].isoformat() if row.get("started_at") else None,
                finished_at=row["completed_at"].isoformat() if row.get("completed_at") else None,
                results=summary,
                models={"all_agents": summary.get("model", active_llm_model())},
                error=row.get("error"),
                run_id=row["id"],
            )
    except Exception as exc:
        logger.warning("Could not load durable pipeline status: %s", exc)
    return PipelineStatusResponse(status="idle", competitor_id=competitor_id)


@app.get(
    "/competitors/{competitor_id}/pipeline_runs",
    response_model=List[PipelineRunDetailResponse],
)
async def list_pipeline_runs(competitor_id: int, limit: int = 20):
    """Return durable investigation history with task attempts."""
    run_limit = min(max(limit, 1), 100)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM pipeline_runs
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (competitor_id, run_limit),
                )
                runs = cur.fetchall() or []
                if not runs:
                    return []
                run_ids = [row["id"] for row in runs]
                cur.execute(
                    """
                    SELECT *
                    FROM pipeline_tasks
                    WHERE run_id = ANY(%s)
                    ORDER BY run_id DESC, created_at, id
                    """,
                    (run_ids,),
                )
                tasks = cur.fetchall() or []
                cur.execute(
                    """
                    SELECT DISTINCT ON (pipeline_run_id, agent_name)
                           pipeline_run_id, agent_name, status, attempts,
                           parse_valid, schema_valid, repaired, grounded_items,
                           rejected_items, latency_ms, validation_errors,
                           metadata, created_at
                    FROM agent_quality_events
                    WHERE pipeline_run_id = ANY(%s)
                    ORDER BY pipeline_run_id, agent_name, created_at DESC, id DESC
                    """,
                    (run_ids,),
                )
                quality_events = cur.fetchall() or []
        quality_by_task = {
            (int(item["pipeline_run_id"]), item["agent_name"]): item
            for item in serialize_rows(quality_events)
        }
        tasks_by_run: dict[int, list[dict]] = {}
        for task in serialize_rows(tasks):
            task["quality"] = quality_by_task.get(
                (int(task["run_id"]), task["agent_name"]),
                {},
            )
            tasks_by_run.setdefault(task["run_id"], []).append(task)
        result = []
        for row in serialize_rows(runs):
            row["tasks"] = tasks_by_run.get(row["id"], [])
            result.append(row)
        return result
    except Exception as exc:
        logger.error("Failed to list pipeline runs for %s: %s", competitor_id, exc)
        raise HTTPException(status_code=500, detail="Failed to load pipeline run history")


@app.post("/competitors/{competitor_id}/pipeline_runs/{run_id}/cancel")
async def cancel_pipeline_run(competitor_id: int, run_id: int):
    """Request cooperative cancellation between durable tasks."""
    if not RunTracker.request_cancel(run_id, competitor_id):
        raise HTTPException(
            status_code=409,
            detail="The run is not active or does not belong to this company",
        )
    status = load_pipeline_status(competitor_id)
    if status and status.get("run_id") == run_id:
        status["stage_status"] = "cancellation_requested"
        save_pipeline_status(competitor_id, status)
    return {"status": "cancellation_requested", "competitor_id": competitor_id, "run_id": run_id}


@app.post(
    "/competitors/{competitor_id}/pipeline_runs/{run_id}/tasks/{task_id}/retry",
    response_model=PipelineTaskRetryResponse,
    status_code=202,
)
async def retry_pipeline_task(
    competitor_id: int,
    run_id: int,
    task_id: int,
    background_tasks: BackgroundTasks,
):
    """Retry exactly one failed durable task in a linked child run."""
    from agents.orchestrator.competitor_pipeline import CompetitorPipeline

    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT competitor.id,
                           competitor.name,
                           competitor.domain,
                           run.model,
                           run.configuration,
                           task.task_key,
                           task.status AS task_status
                    FROM competitors competitor
                    JOIN pipeline_runs run
                      ON run.competitor_id = competitor.id
                    JOIN pipeline_tasks task
                      ON task.run_id = run.id
                    WHERE competitor.id = %s
                      AND run.id = %s
                      AND task.id = %s
                    """,
                    (competitor_id, run_id, task_id),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(
                        status_code=404,
                        detail="The pipeline task was not found for this company and run",
                    )
                if row["task_status"] != "failed":
                    raise HTTPException(
                        status_code=409,
                        detail="Only failed tasks can be retried",
                    )
                if row["task_key"] not in CompetitorPipeline.retryable_task_keys():
                    raise HTTPException(
                        status_code=409,
                        detail=f"Task '{row['task_key']}' cannot be retried independently",
                    )

                cur.execute(
                    """
                    SELECT id
                    FROM pipeline_runs
                    WHERE competitor_id = %s
                      AND status IN ('queued', 'running')
                    LIMIT 1
                    """,
                    (competitor_id,),
                )
                active_run = cur.fetchone()
                if active_run:
                    raise HTTPException(
                        status_code=409,
                        detail=(
                            f"Run #{active_run['id']} is already active. "
                            "Wait for it to finish before retrying a task."
                        ),
                    )

                cur.execute(
                    """
                    SELECT feed_url
                    FROM competitor_rss_feeds
                    WHERE competitor_id = %s
                    ORDER BY id
                    """,
                    (competitor_id,),
                )
                rss_feeds = [feed["feed_url"] for feed in cur.fetchall()]
                configuration = row.get("configuration") or {}
                model = row.get("model") or active_llm_model()
                focus_topics = configuration.get("focus_topics") or []

        tracker = RunTracker()
        retry_run_id = tracker.create_run(
            competitor_id,
            run_type="task_retry",
            trigger_type="manual_retry",
            model=model,
            parent_run_id=run_id,
            configuration={
                "rss_feeds": rss_feeds,
                "shared_model": model,
                "focus_topics": focus_topics,
                "retry": {
                    "source_run_id": run_id,
                    "source_task_id": task_id,
                    "task_key": row["task_key"],
                },
            },
        )
        background_tasks.add_task(
            run_competitor_task_retry,
            competitor_id=competitor_id,
            competitor_name=row["name"],
            domain=row["domain"],
            rss_feeds=rss_feeds,
            model=model,
            focus_topics=focus_topics,
            source_run_id=run_id,
            source_task_id=task_id,
            retry_run_id=retry_run_id,
            task_key=row["task_key"],
        )
        return PipelineTaskRetryResponse(
            status="queued",
            competitor_id=competitor_id,
            source_run_id=run_id,
            source_task_id=task_id,
            retry_run_id=retry_run_id,
            task_key=row["task_key"],
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "Failed to retry task %s from run %s for competitor %s: %s",
            task_id,
            run_id,
            competitor_id,
            exc,
        )
        raise HTTPException(status_code=500, detail="Failed to queue task retry")


@app.get(
    "/competitors/{competitor_id}/documents",
    response_model=List[DocumentResponse],
)
async def list_documents(
    competitor_id: int,
    source_type: Optional[str] = None,
    limit: int = 100,
):
    document_limit = min(max(limit, 1), 500)
    params: list = [competitor_id]
    source_clause = ""
    if source_type:
        source_clause = "AND document.source_type = %s"
        params.append(source_type)
    params.append(document_limit)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT document.*,
                           COUNT(DISTINCT version.id) AS version_count,
                           COUNT(DISTINCT chunk.id) AS chunk_count,
                           COUNT(DISTINCT chunk.id) FILTER (
                               WHERE chunk.indexed_at IS NOT NULL
                           ) AS indexed_chunk_count
                    FROM documents document
                    LEFT JOIN document_versions version
                      ON version.document_id = document.id
                    LEFT JOIN document_chunks chunk
                      ON chunk.document_version_id = version.id
                    WHERE document.competitor_id = %s
                      {source_clause}
                    GROUP BY document.id
                    ORDER BY document.last_seen_at DESC
                    LIMIT %s
                    """,
                    tuple(params),
                )
                return serialize_rows(cur.fetchall() or [])
    except Exception as exc:
        logger.error("Failed to list evidence documents: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load evidence documents")


@app.get(
    "/competitors/{competitor_id}/claims",
    response_model=List[ClaimResponse],
)
async def list_claims(competitor_id: int, limit: int = 100):
    claim_limit = min(max(limit, 1), 500)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM claims
                    WHERE competitor_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (competitor_id, claim_limit),
                )
                claims = cur.fetchall() or []
                if not claims:
                    return []
                claim_ids = [row["id"] for row in claims]
                cur.execute(
                    """
                    SELECT claim_evidence.claim_id,
                           claim_evidence.evidence_id,
                           claim_evidence.document_chunk_id,
                           claim_evidence.stance,
                           claim_evidence.excerpt,
                           claim_evidence.confidence,
                           COALESCE(evidence.source_url, document.canonical_url) AS source_url,
                           COALESCE(evidence.title, document.title) AS title
                    FROM claim_evidence
                    LEFT JOIN evidence
                      ON evidence.id = claim_evidence.evidence_id
                    LEFT JOIN document_chunks chunk
                      ON chunk.id = claim_evidence.document_chunk_id
                    LEFT JOIN document_versions version
                      ON version.id = chunk.document_version_id
                    LEFT JOIN documents document
                      ON document.id = version.document_id
                    WHERE claim_evidence.claim_id = ANY(%s)
                    ORDER BY claim_evidence.claim_id, claim_evidence.id
                    """,
                    (claim_ids,),
                )
                evidence_rows = cur.fetchall() or []
        evidence_by_claim: dict[int, list[dict]] = {}
        for row in serialize_rows(evidence_rows):
            evidence_by_claim.setdefault(row.pop("claim_id"), []).append(row)
        result = []
        for row in serialize_rows(claims):
            row["evidence"] = evidence_by_claim.get(row["id"], [])
            result.append(row)
        return result
    except Exception as exc:
        logger.error("Failed to list evidence claims: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load evidence claims")


def serialize_verification_overview(overview: dict) -> dict:
    return {
        "summary": overview["summary"],
        "queue": serialize_rows(overview["queue"]),
        "verifications": serialize_rows(overview["verifications"]),
        "sources": serialize_rows(overview["sources"]),
        "reviews": serialize_rows(overview["reviews"]),
    }


def serialize_timeline_overview(overview: dict) -> dict:
    return {
        "summary": overview["summary"],
        "events": serialize_rows(overview["events"]),
        "correlations": serialize_rows(overview["correlations"]),
        "weekly_activity": serialize_rows(overview["weekly_activity"]),
        "event_types": overview["event_types"],
    }


@app.get("/competitors/{competitor_id}/timeline")
async def get_intelligence_timeline(competitor_id: int):
    try:
        return serialize_timeline_overview(
            EventFusionEngine(competitor_id).overview()
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to load intelligence timeline: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to load intelligence timeline",
        )


@app.post("/competitors/{competitor_id}/timeline/rebuild")
async def rebuild_intelligence_timeline(competitor_id: int):
    try:
        engine = EventFusionEngine(competitor_id)
        result = engine.rebuild()
        return {
            "result": result,
            "overview": serialize_timeline_overview(engine.overview()),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Intelligence timeline rebuild failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Intelligence timeline rebuild failed",
        )


@app.get("/competitors/{competitor_id}/verification")
async def get_verification_overview(competitor_id: int):
    try:
        return serialize_verification_overview(
            ClaimVerificationEngine(competitor_id).overview()
        )
    except Exception as exc:
        logger.error("Failed to load claim verification: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to load intelligence verification",
        )


@app.post("/competitors/{competitor_id}/verification/run")
async def run_claim_verification(competitor_id: int):
    try:
        result = ClaimVerificationEngine(competitor_id).verify_all()
        return {
            "result": result,
            "overview": serialize_verification_overview(
                ClaimVerificationEngine(competitor_id).overview()
            ),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Claim verification failed: %s", exc)
        raise HTTPException(status_code=500, detail="Claim verification failed")


@app.post("/competitors/{competitor_id}/claims/{claim_id}/review")
async def review_claim(
    competitor_id: int,
    claim_id: int,
    request: ClaimReviewRequest,
):
    try:
        review = ClaimVerificationEngine(competitor_id).review_claim(
            claim_id,
            request.decision,
            request.note,
        )
        return serialize_row(review)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Claim review failed: %s", exc)
        raise HTTPException(status_code=500, detail="Claim review failed")


@app.put(
    "/competitors/{competitor_id}/verification/sources/{source_profile_id}"
)
async def update_source_reliability(
    competitor_id: int,
    source_profile_id: int,
    request: SourceReliabilityUpdate,
):
    try:
        engine = ClaimVerificationEngine(competitor_id)
        source = engine.override_source(
            source_profile_id,
            request.reliability,
            request.basis,
        )
        result = engine.verify_all()
        return {
            "source": serialize_row(source),
            "verification": result,
            "overview": serialize_verification_overview(engine.overview()),
        }
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Source reliability update failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to update source reliability",
        )


@app.get(
    "/competitors/{competitor_id}/evidence/search",
    response_model=List[EvidenceSearchHitResponse],
)
def search_evidence(competitor_id: int, q: str, limit: int = 20):
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="Search query must contain at least two characters")
    try:
        hits = EvidenceRetriever(competitor_id).search(query, min(max(limit, 1), 50))
        rows = []
        for hit in hits:
            row = hit.as_dict()
            for key in ("published_at", "collected_at"):
                value = row.get(key)
                if isinstance(value, datetime):
                    row[key] = value.isoformat()
            rows.append(row)
        return rows
    except Exception as exc:
        logger.error("Evidence search failed for %s: %s", competitor_id, exc)
        raise HTTPException(status_code=500, detail="Evidence search failed")


@app.post("/competitors/{competitor_id}/evidence/reindex")
def reindex_evidence(competitor_id: int):
    try:
        return EvidenceRetriever(competitor_id).prepare()
    except Exception as exc:
        logger.error("Evidence reindex failed for %s: %s", competitor_id, exc)
        raise HTTPException(status_code=500, detail="Evidence reindex failed")


@app.get(
    "/competitors/{competitor_id}/source_health",
    response_model=List[SourceHealthResponse],
)
async def get_source_health(competitor_id: int):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM source_health
                    WHERE competitor_id = %s
                    ORDER BY
                        CASE status
                            WHEN 'error' THEN 0
                            WHEN 'degraded' THEN 1
                            WHEN 'healthy' THEN 2
                            ELSE 3
                        END,
                        updated_at DESC
                    """,
                    (competitor_id,),
                )
                return serialize_rows(cur.fetchall() or [])
    except Exception as exc:
        logger.error("Failed to load source health: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load source health")


@app.get(
    "/competitors/{competitor_id}/evidence/overview",
    response_model=EvidenceOverviewResponse,
)
async def get_evidence_overview(competitor_id: int):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM documents WHERE competitor_id = %s) AS documents,
                        (
                            SELECT COUNT(*)
                            FROM document_versions version
                            JOIN documents document ON document.id = version.document_id
                            WHERE document.competitor_id = %s
                        ) AS document_versions,
                        (SELECT COUNT(*) FROM document_chunks WHERE competitor_id = %s) AS chunks,
                        (
                            SELECT COUNT(*)
                            FROM document_chunks
                            WHERE competitor_id = %s AND indexed_at IS NOT NULL
                        ) AS indexed_chunks,
                        (SELECT COUNT(*) FROM claims WHERE competitor_id = %s) AS claims,
                        (
                            SELECT COUNT(DISTINCT claim.id)
                            FROM claims claim
                            JOIN claim_evidence ON claim_evidence.claim_id = claim.id
                            WHERE claim.competitor_id = %s
                        ) AS cited_claims,
                        (
                            SELECT COUNT(DISTINCT adapter_name)
                            FROM source_health
                            WHERE competitor_id = %s
                        ) AS source_adapters,
                        (
                            SELECT COUNT(*)
                            FROM source_health
                            WHERE competitor_id = %s AND status = 'healthy'
                        ) AS healthy_sources
                    """,
                    (competitor_id,) * 8,
                )
                row = cur.fetchone()
        claims = int(row["claims"])
        cited = int(row["cited_claims"])
        return EvidenceOverviewResponse(
            competitor_id=competitor_id,
            documents=int(row["documents"]),
            document_versions=int(row["document_versions"]),
            chunks=int(row["chunks"]),
            indexed_chunks=int(row["indexed_chunks"]),
            claims=claims,
            cited_claims=cited,
            citation_coverage=round(cited / claims, 4) if claims else 1.0,
            source_adapters=int(row["source_adapters"]),
            healthy_sources=int(row["healthy_sources"]),
        )
    except Exception as exc:
        logger.error("Failed to load evidence overview: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load evidence overview")


@app.get(
    "/competitors/{competitor_id}/collection/campaigns",
    response_model=List[CollectionCampaignResponse],
)
async def list_collection_campaigns(competitor_id: int, limit: int = 20):
    campaign_limit = min(max(limit, 1), 100)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT campaign.*,
                           COALESCE(
                               (
                                   SELECT jsonb_object_agg(summary.state, summary.count)
                                   FROM (
                                       SELECT frontier.state, COUNT(*)::integer AS count
                                       FROM crawl_frontier frontier
                                       WHERE frontier.campaign_id = campaign.id
                                       GROUP BY frontier.state
                                   ) summary
                               ),
                               '{}'::jsonb
                           ) AS frontier
                    FROM collection_campaigns campaign
                    WHERE campaign.competitor_id = %s
                    ORDER BY campaign.created_at DESC
                    LIMIT %s
                    """,
                    (competitor_id, campaign_limit),
                )
                return serialize_rows(cur.fetchall() or [])
    except Exception as exc:
        logger.error("Failed to load collection campaigns: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load collection campaigns")


@app.get(
    "/competitors/{competitor_id}/source_profiles",
    response_model=List[SourceProfileResponse],
)
async def list_source_profiles(competitor_id: int):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM source_profiles
                    WHERE competitor_id = %s
                    ORDER BY status = 'disabled', confidence DESC, id
                    """,
                    (competitor_id,),
                )
                return serialize_rows(cur.fetchall() or [])
    except Exception as exc:
        logger.error("Failed to load source profiles: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load source profiles")


@app.post(
    "/competitors/{competitor_id}/source_profiles",
    response_model=SourceProfileResponse,
)
async def register_source_profile(
    competitor_id: int,
    request: SourceProfileCreate,
):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM competitors WHERE id = %s", (competitor_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Competitor not found")
        classified = SourceProfileStore.classify(request.profile_url)
        source_type = request.source_type or (classified[0] if classified else None)
        profile_key = request.profile_key or (classified[1] if classified else None)
        if not source_type:
            raise HTTPException(
                status_code=422,
                detail="Choose a source type for this URL",
            )
        provider_types = {"youtube", "github", "linkedin", "x", "reddit"}
        if source_type in provider_types and (
            not classified or classified[0] != source_type
        ):
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "source_url_mismatch",
                    "message": (
                        f"The supplied URL is not a canonical {source_type} profile."
                    ),
                    "suggested_action": (
                        "Use the public profile URL from the selected platform "
                        "without credentials or a custom port."
                    ),
                    "recoverable": True,
                },
            )
        profile_id = SourceProfileStore(competitor_id).discover(
            source_type=source_type,
            profile_url=request.profile_url,
            profile_key=profile_key,
            confidence=1.0,
            discovered_from="manual",
            status="active",
        )
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM source_profiles WHERE id = %s AND competitor_id = %s",
                    (profile_id, competitor_id),
                )
                return serialize_row(cur.fetchone())
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to register source profile: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to register source profile")


@app.patch(
    "/competitors/{competitor_id}/source_profiles/{profile_id}",
    response_model=SourceProfileResponse,
)
async def update_source_profile(
    competitor_id: int,
    profile_id: int,
    request: SourceProfileUpdate,
):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE source_profiles
                    SET status = %s
                    WHERE id = %s AND competitor_id = %s
                    RETURNING *
                    """,
                    (request.status, profile_id, competitor_id),
                )
                row = cur.fetchone()
                if not row:
                    raise HTTPException(status_code=404, detail="Source profile not found")
                conn.commit()
        return serialize_row(row)
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update source profile: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update source profile")


@app.get("/competitors/{competitor_id}/collection/coverage")
async def get_collection_coverage(competitor_id: int):
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT source_type, COUNT(*)::integer AS documents,
                           COUNT(*) FILTER (
                               WHERE last_seen_at >= NOW() - INTERVAL '30 days'
                           )::integer AS recent
                    FROM documents
                    WHERE competitor_id = %s
                    GROUP BY source_type
                    ORDER BY documents DESC, source_type
                    """,
                    (competitor_id,),
                )
                documents = serialize_rows(cur.fetchall() or [])
                cur.execute(
                    """
                    SELECT source_type, status, COUNT(*)::integer AS count
                    FROM source_profiles
                    WHERE competitor_id = %s
                    GROUP BY source_type, status
                    ORDER BY source_type, status
                    """,
                    (competitor_id,),
                )
                profiles = serialize_rows(cur.fetchall() or [])
                cur.execute(
                    """
                    SELECT adapter_name,
                           COUNT(*)::integer AS events,
                           COUNT(*) FILTER (WHERE success)::integer AS successful_events,
                           COALESCE(SUM(items), 0)::integer AS items,
                           COALESCE(SUM(bytes_collected), 0)::bigint AS bytes_collected,
                           MAX(created_at) AS last_event_at
                    FROM collection_events
                    WHERE competitor_id = %s
                    GROUP BY adapter_name
                    ORDER BY items DESC, adapter_name
                    """,
                    (competitor_id,),
                )
                adapters = serialize_rows(cur.fetchall() or [])
                cur.execute(
                    """
                    SELECT COUNT(*)::integer AS campaigns,
                           COUNT(*) FILTER (WHERE status = 'completed')::integer AS completed,
                           COUNT(*) FILTER (WHERE status = 'partial')::integer AS partial,
                           MAX(completed_at) AS last_completed_at
                    FROM collection_campaigns
                    WHERE competitor_id = %s
                    """,
                    (competitor_id,),
                )
                campaign_summary = serialize_row(cur.fetchone())
        return {
            "competitor_id": competitor_id,
            "documents_by_source": documents,
            "profiles": profiles,
            "adapters": adapters,
            "campaigns": campaign_summary,
        }
    except Exception as exc:
        logger.error("Failed to load collection coverage: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load collection coverage")


@app.get(
    "/competitors/{competitor_id}/collection/errors",
    response_model=List[CollectionErrorResponse],
)
async def get_collection_errors(
    competitor_id: int,
    limit: int = 100,
    include_resolved: bool = False,
):
    error_limit = min(max(limit, 1), 500)
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM competitors WHERE id = %s", (competitor_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Competitor not found")
                cur.execute(
                    """
                    SELECT id, competitor_id, pipeline_run_id, campaign_id, url,
                           error_code, category, http_status, severity, engine,
                           attempts, technical_message, user_message,
                           suggested_action, recoverable, metadata, occurrences,
                           first_occurred_at, last_occurred_at, resolved_at, created_at
                    FROM collection_errors
                    WHERE competitor_id = %s
                      AND (%s OR resolved_at IS NULL)
                    ORDER BY resolved_at NULLS FIRST, last_occurred_at DESC
                    LIMIT %s
                    """,
                    (competitor_id, include_resolved, error_limit),
                )
                return serialize_rows(cur.fetchall() or [])
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to load collection errors: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load collection errors")


@app.get(
    "/competitors/{competitor_id}/monitoring",
    response_model=MonitoringOverviewResponse,
)
async def get_monitoring_overview(competitor_id: int):
    """Return continuous-monitoring configuration, pulse, and audit activity."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM competitors WHERE id = %s",
                    (competitor_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Competitor not found")
        overview = MonitoringStore.get_overview(competitor_id)
        return {
            "profile": serialize_row(overview["profile"]),
            "metrics": overview["metrics"],
            "activity": serialize_rows(overview["activity"]),
            "latest_run": serialize_row(overview["latest_run"]),
            "scheduler_online": settings.monitoring_scheduler_enabled,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to load monitoring overview: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to load continuous monitoring",
        )


@app.put(
    "/competitors/{competitor_id}/monitoring",
    response_model=MonitoringOverviewResponse,
)
async def update_monitoring_profile(
    competitor_id: int,
    request: MonitoringProfileUpdate,
):
    """Enable, pause, or retune continuous intelligence for one company."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM competitors WHERE id = %s",
                    (competitor_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Competitor not found")
        MonitoringStore.update_profile(
            competitor_id,
            enabled=request.enabled,
            cadence_minutes=request.cadence_minutes,
            focus_topics=request.focus_topics,
            alert_severities=request.alert_severities,
        )
        overview = MonitoringStore.get_overview(competitor_id)
        return {
            "profile": serialize_row(overview["profile"]),
            "metrics": overview["metrics"],
            "activity": serialize_rows(overview["activity"]),
            "latest_run": serialize_row(overview["latest_run"]),
            "scheduler_online": settings.monitoring_scheduler_enabled,
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to update monitoring profile: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to update continuous monitoring",
        )


@app.post("/competitors/{competitor_id}/monitoring/run-now")
async def run_monitoring_now(
    competitor_id: int,
    background_tasks: BackgroundTasks,
):
    """Queue an operator-requested monitoring run using the shared model."""
    current_status = load_pipeline_status(competitor_id)
    if current_status and current_status.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="A pipeline is already running for this company",
        )
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM competitors WHERE id = %s",
                    (competitor_id,),
                )
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Competitor not found")
        prepared = MonitoringStore.prepare_run(
            competitor_id,
            event_type="manual_monitor",
            message="Operator requested an immediate monitoring run",
        )
        background_tasks.add_task(
            execute_monitoring_run,
            prepared["profile"],
            prepared["activity_id"],
            trigger_type="manual_monitor",
        )
        return {
            "status": "queued",
            "competitor_id": competitor_id,
            "monitoring_profile_id": prepared["profile"]["id"],
            "activity_id": prepared["activity_id"],
            "model": active_llm_model(),
        }
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Failed to queue monitoring run: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to queue monitoring run")


@app.get(
    "/competitors/{competitor_id}/collection/access-recovery",
    response_model=AccessRecoveryConfigResponse,
)
async def get_access_recovery_config(competitor_id: int):
    try:
        enabled = CollectionAccessPolicyStore.is_enabled(competitor_id)
        return AccessRecoveryConfigResponse(
            available=settings.crawler_access_recovery_available,
            enabled=enabled and settings.crawler_access_recovery_available,
            max_attempts_per_campaign=max(
                settings.crawler_access_recovery_max_attempts,
                0,
            ),
        )
    except Exception as exc:
        logger.error("Failed to load access-recovery configuration: %s", exc)
        raise HTTPException(status_code=404, detail="Competitor not found")


@app.post(
    "/competitors/{competitor_id}/collection/access-recovery",
    response_model=AccessRecoveryConfigResponse,
)
async def update_access_recovery_config(
    competitor_id: int,
    request: AccessRecoveryUpdate,
):
    if request.enabled and not settings.crawler_access_recovery_available:
        raise HTTPException(
            status_code=409,
            detail="Advanced Access Recovery is disabled by the server administrator",
        )
    try:
        enabled = CollectionAccessPolicyStore.set_enabled(
            competitor_id,
            request.enabled,
        )
        return AccessRecoveryConfigResponse(
            available=settings.crawler_access_recovery_available,
            enabled=enabled and settings.crawler_access_recovery_available,
            max_attempts_per_campaign=max(
                settings.crawler_access_recovery_max_attempts,
                0,
            ),
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        logger.error("Failed to update access-recovery configuration: %s", exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to update Advanced Access Recovery",
        )


@app.delete(
    "/competitors/{competitor_id}/pipeline_data",
    response_model=PipelineDataDeleteResponse,
)
async def delete_competitor_pipeline_data(competitor_id: int):
    """Clear generated intelligence while preserving the monitored company."""
    current_status = load_pipeline_status(competitor_id)
    if current_status and current_status.get("status") == "running":
        raise HTTPException(
            status_code=409,
            detail="Wait for the active pipeline before deleting its data",
        )

    deleted: dict[str, int] = {}
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM competitors WHERE id = %s", (competitor_id,))
                if not cur.fetchone():
                    raise HTTPException(status_code=404, detail="Competitor not found")

                cur.execute(
                    """
                    SELECT id
                    FROM pipeline_runs
                    WHERE competitor_id = %s
                      AND status IN ('queued', 'running')
                    LIMIT 1
                    """,
                    (competitor_id,),
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail="Wait for the active pipeline before deleting its data",
                    )

                cur.execute(
                    """
                    SELECT id
                    FROM deep_research_runs
                    WHERE competitor_id = %s
                      AND status IN ('queued', 'running')
                    LIMIT 1
                    """,
                    (competitor_id,),
                )
                if cur.fetchone():
                    raise HTTPException(
                        status_code=409,
                        detail="Cancel the active Deep Research run before deleting its data",
                    )

                deleted["qdrant_points"] = ChunkIndexer.delete_competitor(competitor_id)

                cur.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM relationships relationship
                    JOIN entities source_entity
                      ON source_entity.id = relationship.source_entity_id
                    WHERE source_entity.competitor_id = %s
                    """,
                    (competitor_id,),
                )
                deleted["relationships"] = int(cur.fetchone()["count"])

                for table in (
                    "deep_research_results",
                    "deep_research_runs",
                    "social_observations",
                    "social_comments",
                    "social_posts",
                    "social_profiles",
                    "social_collection_runs",
                    "intelligence_events",
                    "page_changes",
                    "page_snapshots",
                    "claims",
                    "relationship_observations",
                    "entity_aliases",
                    "graph_snapshots",
                    "entities",
                    "evidence",
                    "raw_data",
                    "insights",
                    "signals",
                    "predictions",
                    "source_health",
                    "source_reliability_profiles",
                    "source_profiles",
                    "collection_errors",
                    "collection_campaigns",
                    "investigations",
                    "pipeline_runs",
                    "documents",
                ):
                    cur.execute(
                        f"DELETE FROM {table} WHERE competitor_id = %s",
                        (competitor_id,),
                    )
                    deleted[table] = max(cur.rowcount, 0)

                cur.execute(
                    """
                    UPDATE competitors
                    SET description = NULL,
                        hq = NULL,
                        founded = NULL,
                        executives = '[]'::jsonb,
                        subsidiaries = '[]'::jsonb,
                        key_products = '[]'::jsonb,
                        technologies = '[]'::jsonb,
                        social_media = '{}'::jsonb,
                        careers_url = NULL,
                        blog_url = NULL,
                        discovery_status = CASE
                            WHEN discovery_status = 'manual' THEN 'manual'
                            ELSE 'discovered'
                        END
                    WHERE id = %s
                    """,
                    (competitor_id,),
                )
                conn.commit()
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete pipeline data for competitor {competitor_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to delete pipeline data")

    try:
        redis_client = get_redis_client()
        cache_keys = list(redis_client.scan_iter(match=f"last_seen:{competitor_id}:*"))
        cache_keys.append(pipeline_status_key(competitor_id))
        redis_client.delete(*cache_keys)
    except Exception as e:
        logger.warning("Pipeline data cleared but cache cleanup failed: %s", e)

    from reports.pdf_generator import delete_reports

    reports_deleted = delete_reports(competitor_id)
    return PipelineDataDeleteResponse(
        status="deleted",
        competitor_id=competitor_id,
        deleted=deleted,
        reports_deleted=reports_deleted,
    )


@app.get("/dashboard", response_model=DashboardResponse)
async def get_dashboard():
    """Get aggregated dashboard data for all competitors."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                # Get all competitors
                cur.execute("""
                    SELECT id, name, domain, industry
                    FROM competitors
                    ORDER BY id
                """)
                competitors = cur.fetchall()

                dashboard_competitors = []

                for comp in competitors:
                    comp_id = comp["id"]

                    # Get latest summary
                    cur.execute("""
                        SELECT summary
                        FROM insights
                        WHERE competitor_id = %s AND insight_type = 'weekly_summary'
                        ORDER BY created_at DESC
                        LIMIT 1
                    """, (comp_id,))
                    summary_row = cur.fetchone()
                    latest_summary = summary_row["summary"] if summary_row else None

                    # Get signal count
                    cur.execute("""
                        SELECT COUNT(*) as count
                        FROM signals
                        WHERE competitor_id = %s
                    """, (comp_id,))
                    signal_count = cur.fetchone()["count"]

                    # Get prediction count
                    cur.execute("""
                        SELECT COUNT(*) as count
                        FROM predictions
                        WHERE competitor_id = %s
                    """, (comp_id,))
                    prediction_count = cur.fetchone()["count"]

                    # Get last updated (most recent activity)
                    cur.execute("""
                        SELECT MAX(last_update) as last_updated
                        FROM (
                            SELECT MAX(created_at) as last_update FROM insights WHERE competitor_id = %s
                            UNION ALL
                            SELECT MAX(detected_at) as last_update FROM signals WHERE competitor_id = %s
                            UNION ALL
                            SELECT MAX(created_at) as last_update FROM predictions WHERE competitor_id = %s
                        ) updates
                    """, (comp_id, comp_id, comp_id))
                    last_updated_row = cur.fetchone()
                    last_updated = last_updated_row["last_updated"] if last_updated_row else None

                    dashboard_competitors.append(DashboardCompetitor(
                        id=comp_id,
                        name=comp["name"],
                        domain=comp["domain"],
                        industry=comp["industry"],
                        latest_summary=latest_summary,
                        signal_count=signal_count,
                        prediction_count=prediction_count,
                        last_updated=last_updated.isoformat() if isinstance(last_updated, datetime) else last_updated
                    ))

                return DashboardResponse(
                    competitors=dashboard_competitors,
                    total_count=len(dashboard_competitors)
                )
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {e}")
        raise HTTPException(status_code=500, detail="Failed to get dashboard data")


# ============================================================
# Main entry point
# ============================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
