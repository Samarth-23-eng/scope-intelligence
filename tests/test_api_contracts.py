import asyncio

import pytest
from fastapi import HTTPException

from api import main
from reports import pdf_generator


class FakeCursor:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, params=None):
        return None

    def fetchone(self):
        return None


class FakeConnection:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def cursor(self):
        return FakeCursor()


def test_summary_returns_nullable_200_contract(monkeypatch):
    monkeypatch.setattr(main, "get_connection", FakeConnection)

    result = asyncio.run(main.get_competitor_summary(42))

    assert result.summary is None
    assert result.message == "No summary yet"


def test_competitor_rejects_invalid_rss_url():
    with pytest.raises(ValueError):
        main.CompetitorCreate(
            name="Example",
            domain="example.com",
            rss_feeds=["file:///etc/passwd"],
        )


def test_competitor_normalizes_website_to_domain():
    competitor = main.CompetitorCreate(
        name=" Example ",
        domain="https://WWW.Example.com/products?ref=test",
    )

    assert competitor.name == "Example"
    assert competitor.domain == "www.example.com"


def test_page_change_contract_requires_evidence():
    change = main.PageChangeResponse(
        id=1,
        competitor_id=42,
        source_url="https://example.com/pricing",
        title="Pricing",
        change_type="pricing",
        summary="Pricing changed.",
        before_excerpt="$19 per month",
        after_excerpt="$29 per month",
        similarity=0.9,
        significance=0.2,
        detected_at="2026-07-27T12:00:00",
        evidence_id=5,
        evidence_snippet="The new plan costs $29 per month.",
        evidence_confidence=1.0,
        evidence_collected_at="2026-07-27T12:00:00",
    )

    assert change.evidence_id == 5
    assert change.source_url.endswith("/pricing")


def test_relationship_contract_exposes_provenance():
    relationship = main.RelationshipResponse(
        id=3,
        source_entity_id=1,
        source_name="Example",
        source_type="company",
        target_entity_id=2,
        target_name="Stripe",
        target_type="integration",
        relationship_type="integrates_with",
        weight=0.87,
        rationale="Listed on the official integrations page.",
        extraction_method="llm",
        evidence_count=1,
        status="active",
        metadata={},
        created_at="2026-07-27T12:00:00",
        first_seen_at="2026-07-27T12:00:00",
        last_seen_at="2026-07-27T12:00:00",
        evidence=[
            {
                "id": 10,
                "source_url": "https://example.com/integrations",
                "title": "Integrations",
                "snippet": "Connect Example with Stripe.",
                "confidence": 1.0,
                "collected_at": "2026-07-27T12:00:00",
            }
        ],
    )

    assert relationship.evidence_count == 1
    assert relationship.risk_level == "unassessed"
    assert relationship.evidence[0].id == 10


def test_pipeline_request_uses_single_shared_model():
    request = main.PipelineRunRequest()

    assert request.model == main.active_llm_model()
    assert not hasattr(request, "models")


def test_settings_repr_does_not_expose_secret_values():
    representation = repr(main.settings)

    for secret in (
        main.settings.github_token,
        main.settings.newsapi_key,
        main.settings.llm_api_key,
        main.settings.nine_router_api_key,
    ):
        if secret:
            assert secret not in representation


def test_task_retry_background_preserves_parent_linkage(monkeypatch):
    lifecycle = []

    class FakeTracker:
        def __init__(self, run_id):
            self.run_id = run_id

        def start_run(self):
            lifecycle.append(("started", self.run_id))

        def finish_run(self, status, *, summary=None, error=None):
            lifecycle.append((status, self.run_id, summary, error))

    from agents.orchestrator.competitor_pipeline import CompetitorPipeline

    monkeypatch.setattr(main, "RunTracker", FakeTracker)
    monkeypatch.setattr(
        CompetitorPipeline,
        "retry_task",
        lambda self, task_key, source_run_id=None: lifecycle.append(
            ("task", task_key, source_run_id, self.run_id)
        ),
    )

    main.run_competitor_task_retry(
        competitor_id=42,
        competitor_name="Example",
        domain="example.com",
        rss_feeds=[],
        model="shared-model",
        focus_topics=[],
        source_run_id=12,
        source_task_id=13,
        retry_run_id=14,
        task_key="analysis.event_fusion",
    )

    assert lifecycle[0] == ("started", 14)
    assert lifecycle[1] == ("task", "analysis.event_fusion", 12, 14)
    assert lifecycle[2][0:2] == ("completed", 14)
    assert lifecycle[2][2]["retry"] == {
        "source_run_id": 12,
        "source_task_id": 13,
        "task_key": "analysis.event_fusion",
    }


def test_investigation_request_is_bounded_and_uses_shared_model():
    request = main.InvestigationCreate(
        question="What evidence supports the expansion strategy?",
        max_steps=4,
    )

    assert request.max_steps == 4
    assert main.settings.llm_model


def test_monitoring_policy_is_bounded_and_normalized():
    request = main.MonitoringProfileUpdate(
        enabled=True,
        cadence_minutes=60,
        focus_topics=[" India hiring ", "partnerships", "India hiring"],
        alert_severities=["high", "critical", "high"],
    )

    assert request.cadence_minutes == 60
    assert request.focus_topics == ["India hiring", "partnerships"]
    assert request.alert_severities == ["high", "critical"]


def test_monitoring_policy_rejects_unsafe_cadence():
    with pytest.raises(ValueError):
        main.MonitoringProfileUpdate(
            enabled=True,
            cadence_minutes=5,
            focus_topics=[],
            alert_severities=["high"],
        )


def test_claim_review_and_source_reliability_inputs_are_bounded():
    review = main.ClaimReviewRequest(
        decision="confirmed",
        note="Reviewed against the filing.",
    )
    source = main.SourceReliabilityUpdate(
        reliability=0.92,
        basis="Official regulatory publication",
    )

    assert review.decision == "confirmed"
    assert source.reliability == 0.92


def test_claim_review_rejects_unknown_decision():
    with pytest.raises(ValueError):
        main.ClaimReviewRequest(decision="delete", note=None)


def test_pipeline_data_delete_is_blocked_while_running(monkeypatch):
    monkeypatch.setattr(main, "load_pipeline_status", lambda competitor_id: {"status": "running"})

    with pytest.raises(HTTPException) as exc:
        asyncio.run(main.delete_competitor_pipeline_data(42))

    assert exc.value.status_code == 409


def test_pipeline_data_delete_clears_generated_records(monkeypatch):
    class DeleteCursor(FakeCursor):
        rowcount = 0

        def __init__(self):
            self.query = ""

        def execute(self, query, params=None):
            self.query = " ".join(query.split())
            self.rowcount = 2 if self.query.startswith("DELETE FROM") else 0

        def fetchone(self):
            if self.query.startswith("SELECT id FROM competitors"):
                return {"id": 42}
            if self.query.startswith("SELECT COUNT(*)"):
                return {"count": 3}
            return None

    class DeleteConnection(FakeConnection):
        def __init__(self):
            self.committed = False

        def cursor(self):
            return DeleteCursor()

        def commit(self):
            self.committed = True

    class FakeRedis:
        def __init__(self):
            self.deleted = []

        def scan_iter(self, match):
            return [f"last_seen:42:web:https://example.com"]

        def delete(self, *keys):
            self.deleted.extend(keys)

    connection = DeleteConnection()
    cache = FakeRedis()
    monkeypatch.setattr(main, "load_pipeline_status", lambda competitor_id: None)
    monkeypatch.setattr(main, "get_connection", lambda: connection)
    monkeypatch.setattr(main, "get_redis_client", lambda: cache)
    monkeypatch.setattr(main.ChunkIndexer, "delete_competitor", lambda competitor_id: 4)
    monkeypatch.setattr(pdf_generator, "delete_reports", lambda competitor_id: 1)

    result = asyncio.run(main.delete_competitor_pipeline_data(42))

    assert connection.committed
    assert result.status == "deleted"
    assert result.deleted["relationships"] == 3
    assert result.deleted["raw_data"] == 2
    assert result.deleted["qdrant_points"] == 4
    assert result.reports_deleted == 1
    assert main.pipeline_status_key(42) in cache.deleted
