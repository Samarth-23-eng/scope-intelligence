import asyncio
from unittest.mock import AsyncMock, MagicMock

from agents.ingestion.change_detector import SnapshotResult
from agents.ingestion import web_scraper
from agents.ingestion.web_scraper import ExtractedPage, WebScraperAgent


class FakePage:
    url = "https://example.com"
    goto = AsyncMock()
    wait_for_load_state = AsyncMock()
    title = AsyncMock(return_value="Example")


class FakeBlockedResponse:
    status = 403


class FakeBlockedPage(FakePage):
    goto = AsyncMock(return_value=FakeBlockedResponse())
    title = AsyncMock(return_value="Verifying your browser…")


def test_scraper_only_counts_persisted_pages(monkeypatch):
    agent = WebScraperAgent(1, "Example", "example.com")
    monkeypatch.setattr(agent, "_get_meta_description", AsyncMock(return_value="Description"))
    monkeypatch.setattr(agent, "_get_headings", AsyncMock(return_value=["Heading"]))
    monkeypatch.setattr(agent, "_get_body_text", AsyncMock(return_value="Body"))
    monkeypatch.setattr(agent, "_get_relevant_links", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        agent.change_monitor,
        "record_snapshot",
        lambda **kwargs: SnapshotResult(snapshot_saved=True, change_detected=False),
    )
    monkeypatch.setattr(agent, "has_changed", AsyncMock(return_value=True))
    mark_seen = AsyncMock(return_value=True)
    monkeypatch.setattr(agent, "mark_seen", mark_seen)
    monkeypatch.setattr(agent, "save_raw_data", lambda **kwargs: False)

    result = asyncio.run(agent._scrape_page(FakePage(), "https://example.com"))

    assert result is None
    mark_seen.assert_not_awaited()


def test_unchanged_page_still_returns_discovered_links(monkeypatch):
    agent = WebScraperAgent(1, "Example", "example.com")
    discovered = ["https://example.com/partners/acme"]
    monkeypatch.setattr(agent, "_get_meta_description", AsyncMock(return_value="Description"))
    monkeypatch.setattr(agent, "_get_headings", AsyncMock(return_value=["Heading"]))
    monkeypatch.setattr(agent, "_get_body_text", AsyncMock(return_value="Body"))
    monkeypatch.setattr(agent, "_get_relevant_links", AsyncMock(return_value=discovered))
    monkeypatch.setattr(
        agent.change_monitor,
        "record_snapshot",
        lambda **kwargs: SnapshotResult(snapshot_saved=True, change_detected=False),
    )
    monkeypatch.setattr(agent, "has_changed", AsyncMock(return_value=False))
    save_raw_data = AsyncMock()
    monkeypatch.setattr(agent, "save_raw_data", save_raw_data)

    result = asyncio.run(agent._scrape_page(FakePage(), "https://example.com"))

    assert result["persisted"] is False
    assert result["links"] == discovered
    save_raw_data.assert_not_called()


def test_changed_page_becomes_first_party_evidence(monkeypatch):
    agent = WebScraperAgent(1, "Example", "example.com")
    monkeypatch.setattr(agent, "_get_meta_description", AsyncMock(return_value="Description"))
    monkeypatch.setattr(agent, "_get_headings", AsyncMock(return_value=["Partners"]))
    monkeypatch.setattr(agent, "_get_body_text", AsyncMock(return_value="We partner with Acme."))
    monkeypatch.setattr(agent, "_get_relevant_links", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        agent.change_monitor,
        "record_snapshot",
        lambda **kwargs: SnapshotResult(snapshot_saved=True, change_detected=True),
    )
    monkeypatch.setattr(agent, "has_changed", AsyncMock(return_value=True))
    monkeypatch.setattr(agent, "save_raw_data", lambda **kwargs: True)
    save_evidence = MagicMock(return_value=42)
    monkeypatch.setattr(agent, "save_evidence", save_evidence)
    monkeypatch.setattr(agent, "mark_seen", AsyncMock(return_value=True))

    result = asyncio.run(agent._scrape_page(FakePage(), "https://example.com/partners"))

    assert result["persisted"] is True
    assert result["evidence_id"] == 42
    assert save_evidence.call_args.kwargs["metadata"]["source_type"] == "first_party_website"


def test_browser_challenge_is_not_persisted_as_evidence(monkeypatch):
    agent = WebScraperAgent(1, "Example", "example.com")
    monkeypatch.setattr(agent, "_get_meta_description", AsyncMock(return_value=""))
    monkeypatch.setattr(agent, "_get_headings", AsyncMock(return_value=[]))
    monkeypatch.setattr(
        agent,
        "_get_body_text",
        AsyncMock(return_value="Verifying your browser before accessing this website."),
    )
    monkeypatch.setattr(agent, "_get_relevant_links", AsyncMock(return_value=[]))
    save_raw_data = MagicMock()
    monkeypatch.setattr(agent, "save_raw_data", save_raw_data)

    result = asyncio.run(
        agent._scrape_page(FakeBlockedPage(), "https://example.com")
    )

    assert result is None
    assert agent._last_browser_failure["http_status"] == 403
    assert agent._last_browser_failure["error_code"] == "http_403_browser"
    save_raw_data.assert_not_called()


def test_scraper_classifies_relationship_rich_pages():
    agent = WebScraperAgent(1, "Example", "example.com")

    assert agent._classify_page(
        "https://example.com/integrations",
        "App marketplace",
        ["Connect your tools"],
    ) == "integrations"
    assert agent._classify_page(
        "https://example.com/about",
        "Meet our executive team",
        ["Leadership"],
    ) == "leadership"


def test_scraper_keeps_only_canonical_same_domain_urls():
    agent = WebScraperAgent(1, "Example", "example.com")

    assert agent._canonical_url("https://www.example.com/partners/?ref=nav#top") == (
        "https://example.com/partners"
    )
    assert agent._canonical_url("https://unrelated.example/partners") == ""


def test_crawler_v2_extracts_structured_data_and_discovers_job_board():
    agent = WebScraperAgent(1, "Example", "example.com")
    page = agent._extract_html(
        "https://example.com/careers",
        """
        <html>
          <head>
            <title>Careers at Example</title>
            <meta name="description" content="Join the team">
            <script type="application/ld+json">
              {"@type":"Organization","name":"Example"}
            </script>
          </head>
          <body>
            <nav>Navigation noise</nav>
            <main>
              <h1>Open roles</h1>
              <p>Build useful products with us.</p>
              <a href="/about">About us</a>
              <a href="https://jobs.lever.co/example">All jobs</a>
            </main>
          </body>
        </html>
        """,
        200,
    )

    assert page.engine == "http"
    assert page.page_type == "careers"
    assert page.links == ["https://example.com/about"]
    assert page.external_links == ["https://jobs.lever.co/example"]
    assert page.structured_data[0]["@type"] == "Organization"
    assert "Navigation noise" not in page.body_text

    agent._track_discoveries(
        {
            "external_links": page.external_links,
            "feed_urls": ["https://example.com/feed.xml"],
        }
    )
    assert agent.discovered_job_boards == {"https://jobs.lever.co/example"}
    assert agent.discovered_feeds == {"https://example.com/feed.xml"}


def test_html_extraction_preserves_content_beyond_legacy_character_cap():
    agent = WebScraperAgent(1, "Example", "example.com")
    long_text = "strategic evidence " * 8_000

    page = agent._extract_html(
        "https://example.com/research",
        f"<html><body><main>{long_text}</main></body></html>",
        200,
    )

    assert len(page.body_text) > 100_000
    assert page.body_text.endswith("strategic evidence")


def test_page_persistence_uses_explicit_byte_budget_and_lightweight_task_result(
    monkeypatch,
):
    from config.settings import settings

    monkeypatch.setattr(settings, "crawler_max_document_bytes", 20_000)
    agent = WebScraperAgent(1, "Example", "example.com")
    page = ExtractedPage(
        url="https://example.com/long",
        title="Long evidence",
        description="",
        headings=[],
        body_text="evidence detail " * 5_000,
        links=[],
        external_links=[],
        page_type="research",
    )
    captured = {}

    monkeypatch.setattr(
        agent.change_monitor,
        "record_snapshot",
        lambda **kwargs: SnapshotResult(
            snapshot_saved=True,
            change_detected=False,
        ),
    )
    monkeypatch.setattr(agent, "has_changed", AsyncMock(return_value=True))
    monkeypatch.setattr(agent, "mark_seen", AsyncMock(return_value=True))

    def save_raw_data(**kwargs):
        captured["content"] = kwargs["content"]
        captured["metadata"] = kwargs["metadata"]
        return True

    monkeypatch.setattr(agent, "save_raw_data", save_raw_data)
    monkeypatch.setattr(agent, "save_evidence", lambda **kwargs: 9)

    result = asyncio.run(agent._persist_extracted_page(page))

    assert result is not None
    assert len(captured["content"].encode("utf-8")) <= 20_000
    assert captured["metadata"]["content_budget"]["truncated"] is True
    assert captured["metadata"]["content_budget"]["original_bytes"] > 20_000
    assert result["content_truncated"] is True
    assert "body_text" not in result
    assert len(result["body_preview"]) <= 1_000


def test_crawler_v2_prioritizes_relationship_pages_and_browser_fallback():
    agent = WebScraperAgent(1, "Example", "example.com")

    assert agent._score_url("https://example.com/partners", 1) > agent._score_url(
        "https://example.com/legal",
        1,
    )
    assert agent._needs_browser(
        ExtractedPage(
            url="https://example.com/app",
            title="App",
            description="",
            headings=[],
            body_text="Loading",
            links=[],
            external_links=[],
            page_type="general",
        )
    )


def test_crawler_v2_never_exceeds_page_budget(monkeypatch):
    agent = WebScraperAgent(1, "Example", "example.com")
    agent.max_pages = 3
    agent.concurrency = 2
    agent.min_content_chars = 0
    agent.max_browser_fallbacks = 0
    monkeypatch.setattr(agent, "_load_discovery_sources", AsyncMock(return_value=[]))
    monkeypatch.setattr(agent, "_track_discoveries", lambda result: None)

    async def fetch_page(client, url):
        return ExtractedPage(
            url=url,
            title="Example",
            description="",
            headings=[],
            body_text="Collected content",
            links=[],
            external_links=[],
            page_type="general",
        )

    async def persist(page):
        return {
            "url": page.url,
            "links": [],
            "external_links": [],
            "feed_urls": [],
            "persisted": True,
        }

    monkeypatch.setattr(agent, "_fetch_http_page", fetch_page)
    monkeypatch.setattr(agent, "_persist_extracted_page", persist)

    results = asyncio.run(agent.collect())

    assert len(results) == 3
    assert agent.last_run_stats["visited"] == 3


def test_crawler_skips_cleanly_when_identity_has_no_website():
    agent = WebScraperAgent(1, "Obscure Research Unit", "")

    results = asyncio.run(agent.collect())

    assert results == []
    assert agent.last_run_stats["skipped"] is True
    assert "name-based collectors remain active" in agent.last_run_stats["skip_reason"]


def test_access_challenge_classifier_does_not_treat_404_as_blocking():
    blocked = ExtractedPage(
        url="https://example.com/restricted",
        title="Access denied",
        description="",
        headings=[],
        body_text="",
        links=[],
        external_links=[],
        page_type="blocked",
        status_code=403,
    )
    missing = ExtractedPage(
        url="https://example.com/missing",
        title="Not found",
        description="",
        headings=[],
        body_text="",
        links=[],
        external_links=[],
        page_type="http_error",
        status_code=404,
    )

    assert WebScraperAgent._looks_like_access_challenge(blocked) is True
    assert WebScraperAgent._looks_like_access_challenge(missing) is False


def test_error_center_explains_404_without_access_recovery(monkeypatch):
    agent = WebScraperAgent(1, "Example", "example.com")
    recorded = []
    monkeypatch.setattr(
        agent.error_store,
        "record",
        lambda **kwargs: recorded.append(kwargs) or 1,
    )

    agent._record_http_error("https://example.com/missing", 404, ["httpx"])

    assert recorded[0]["error_code"] == "http_404"
    assert recorded[0]["attempts"] == ["httpx"]
    assert "HTTP 404" in recorded[0]["user_message"]


def test_error_center_lists_every_engine_used_for_access_denial(monkeypatch):
    agent = WebScraperAgent(1, "Example", "example.com")
    recorded = []
    monkeypatch.setattr(
        agent.error_store,
        "record",
        lambda **kwargs: recorded.append(kwargs) or 1,
    )

    agent._record_http_error(
        "https://example.com/restricted",
        403,
        ["httpx", "curl_cffi", "playwright"],
    )

    assert recorded[0]["category"] == "access_denied"
    assert recorded[0]["severity"] == "error"
    assert "httpx, curl_cffi, playwright" in recorded[0]["user_message"]


def test_crawler_v2_counts_unique_source_profiles(monkeypatch):
    class FakeRegistry:
        def __init__(self, competitor_id):
            self.competitor_id = competitor_id

        @staticmethod
        def classify(url):
            return ("youtube", "@example") if "youtube.com" in url else None

        @staticmethod
        def normalize_profile_url(url):
            return url

        def discover_urls(self, *args, **kwargs):
            return {"youtube": 1}

        def discover(self, **kwargs):
            return 1

    monkeypatch.setattr(web_scraper, "SourceProfileStore", FakeRegistry)
    agent = WebScraperAgent(1, "Example", "example.com")
    agent.run_id = 4
    result = {
        "url": "https://example.com",
        "external_links": ["https://youtube.com/@example"],
        "feed_urls": ["https://example.com/feed.xml"],
    }

    agent._track_discoveries(result)
    agent._track_discoveries(result)

    assert agent.discovered_profiles == {"youtube": 1, "rss": 1}
