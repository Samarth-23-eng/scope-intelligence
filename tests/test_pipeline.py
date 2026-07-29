from agents.orchestrator.competitor_pipeline import CompetitorPipeline
from config.settings import settings
import pytest


def test_pipeline_uses_one_shared_model():
    pipeline = CompetitorPipeline(1, "Example", "example.com")

    assert pipeline.model == settings.llm_model


def test_full_pipeline_reports_stage_failure(monkeypatch):
    pipeline = CompetitorPipeline(1, "Example", "example.com")
    monkeypatch.setattr(
        pipeline,
        "run_ingestion",
        lambda: {
            "web_pages": 0,
            "website_changes": 0,
            "news_articles": 0,
            "errors": ["network failed"],
        },
    )
    monkeypatch.setattr(
        pipeline,
        "run_enrichment",
        lambda: {"social_posts": 0, "tech_stack": 0, "errors": []},
    )
    monkeypatch.setattr(
        pipeline,
        "run_analysis",
        lambda: {
            "summary_generated": False,
            "signals_detected": 0,
            "predictions_made": 0,
            "errors": [],
        },
    )

    result = pipeline.run_full_pipeline()

    assert result["success"] is False


def test_full_pipeline_reports_success_without_errors(monkeypatch):
    progress = []
    pipeline = CompetitorPipeline(
        1,
        "Example",
        "example.com",
        progress_callback=lambda stage, status, data: progress.append((stage, status)),
    )
    monkeypatch.setattr(
        pipeline,
        "run_ingestion",
        lambda: {"web_pages": 1, "website_changes": 1, "news_articles": 2, "errors": []},
    )
    monkeypatch.setattr(
        pipeline,
        "run_enrichment",
        lambda: {"social_posts": 0, "tech_stack": 1, "errors": []},
    )
    monkeypatch.setattr(
        pipeline,
        "run_analysis",
        lambda: {
            "summary_generated": True,
            "signals_detected": 1,
            "predictions_made": 1,
            "errors": [],
        },
    )

    result = pipeline.run_full_pipeline()

    assert result["success"] is True
    assert progress == [
        ("ingestion", "running"),
        ("ingestion", "completed"),
        ("enrichment", "running"),
        ("enrichment", "completed"),
        ("analysis", "running"),
        ("analysis", "completed"),
    ]


def test_retry_task_executes_only_the_selected_registered_task(monkeypatch):
    pipeline = CompetitorPipeline(1, "Example", "example.com", run_id=88)
    executed = []

    monkeypatch.setattr(
        pipeline,
        "_retry_operation",
        lambda task_key, source_run_id: lambda: {
            "task_key": task_key,
            "source_run_id": source_run_id,
        },
    )

    def execute_task(**kwargs):
        executed.append(kwargs)
        return kwargs["operation"]()

    monkeypatch.setattr(pipeline, "_execute_task", execute_task)

    result = pipeline.retry_task("analysis.event_fusion", source_run_id=41)

    assert result == {
        "task_key": "analysis.event_fusion",
        "source_run_id": 41,
    }
    assert len(executed) == 1
    assert executed[0]["task_key"] == "analysis.event_fusion"
    assert executed[0]["stage"] == "analysis"
    assert executed[0]["agent_name"] == "EventFusionEngine"


def test_retry_task_rejects_unregistered_work():
    pipeline = CompetitorPipeline(1, "Example", "example.com", run_id=88)

    with pytest.raises(ValueError, match="cannot be retried independently"):
        pipeline.retry_task("analysis.unknown")
