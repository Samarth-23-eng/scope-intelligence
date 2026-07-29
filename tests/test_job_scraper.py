import asyncio
from unittest.mock import AsyncMock

from agents.ingestion.job_scraper import JobScraperAgent
from config.settings import settings


def test_linkedin_source_requires_explicit_feature_flag(monkeypatch):
    monkeypatch.setattr(settings, "job_sources", "linkedin,indeed")
    monkeypatch.setattr(settings, "enable_linkedin_scraper", False)

    agent = JobScraperAgent(1, "Example", "example.com")

    assert agent.sources == ["indeed"]


def test_job_normalization_and_competitor_matching(monkeypatch):
    monkeypatch.setattr(settings, "job_sources", "linkedin")
    monkeypatch.setattr(settings, "enable_linkedin_scraper", True)
    agent = JobScraperAgent(1, "Skyroot Aerospace", "skyroot.in")

    job = agent._normalize_job(
        {
            "title": "Propulsion Engineer",
            "company": "Skyroot Aerospace Pvt Ltd",
            "location": "Hyderabad, India",
            "job_url": "https://www.linkedin.com/jobs/view/123",
            "description": "Design rocket engines",
            "min_amount": float("nan"),
        },
        "linkedin",
    )

    assert job is not None
    assert job["min_amount"] is None
    assert agent._matches_competitor(job)
    job["company"] = "Unrelated Company"
    assert not agent._matches_competitor(job)


def test_job_normalization_preserves_long_descriptions(monkeypatch):
    monkeypatch.setattr(settings, "job_sources", "indeed")
    agent = JobScraperAgent(1, "Example", "example.com")
    description = "technical responsibility " * 3_000

    job = agent._normalize_job(
        {
            "title": "Engineer",
            "company": "Example",
            "job_url": "https://example.com/jobs/long",
            "description": description,
        },
        "indeed",
    )

    assert job is not None
    assert len(description) > 30_000
    assert job["description"] == description


def test_sources_fail_independently(monkeypatch):
    monkeypatch.setattr(settings, "enable_job_scraper", True)
    monkeypatch.setattr(settings, "job_sources", "linkedin,indeed")
    monkeypatch.setattr(settings, "enable_linkedin_scraper", True)
    agent = JobScraperAgent(1, "Example", "example.com")

    def scrape(source):
        if source == "linkedin":
            raise RuntimeError("blocked")
        return [
            {
                "title": "Engineer",
                "company": "Example",
                "job_url": "https://example.com/jobs/1",
            }
        ]

    monkeypatch.setattr(agent, "_scrape_source", scrape)
    monkeypatch.setattr(
        agent,
        "_persist_job",
        AsyncMock(return_value={"title": "Engineer", "persisted": True}),
    )

    results = asyncio.run(agent.collect())

    assert len(results) == 1
    assert agent.last_run_stats["sources"]["linkedin"]["error"] == "blocked"
    assert agent.last_run_stats["sources"]["indeed"]["persisted"] == 1
