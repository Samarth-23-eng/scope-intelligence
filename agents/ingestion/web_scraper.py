import asyncio
import hashlib
import heapq
import io
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser
from xml.etree import ElementTree

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from pypdf import PdfReader

from agents.ingestion.base import BaseIngestionAgent
from agents.ingestion.change_detector import PageChangeMonitor
from config.settings import settings
from intelligence.foundation import apply_text_byte_budget
from intelligence.collection import (
    CollectionAccessPolicyStore,
    CollectionCampaignStore,
    CollectionErrorStore,
    SourceProfileStore,
)

logger = logging.getLogger(__name__)


@dataclass(order=True)
class CrawlTarget:
    """Priority-queue item. Higher business value is crawled first."""

    sort_key: int
    sequence: int
    url: str = field(compare=False)
    depth: int = field(compare=False, default=0)
    discovered_from: str = field(compare=False, default="seed")


@dataclass
class ExtractedPage:
    url: str
    title: str
    description: str
    headings: List[str]
    body_text: str
    links: List[str]
    external_links: List[str]
    page_type: str
    content_type: str = "text/html"
    structured_data: List[Dict[str, Any]] = field(default_factory=list)
    feed_urls: List[str] = field(default_factory=list)
    engine: str = "http"
    status_code: int = 200
    response_headers: Dict[str, str] = field(default_factory=dict)


class WebScraperAgent(BaseIngestionAgent):
    """
    Hybrid first-party crawler.

    Static pages are downloaded concurrently with HTTPX. Pages that contain too
    little readable content are rendered with Playwright. Sitemap, robots, feed,
    document, and internal-link discovery all feed one priority queue so engines
    cooperate instead of producing duplicate crawl runs.
    """

    USER_AGENT = "OSINTPlatformBot/2.0 (+local competitive-intelligence research)"
    TARGET_PATHS = (
        "/",
        "/about",
        "/company",
        "/team",
        "/leadership",
        "/products",
        "/solutions",
        "/pricing",
        "/integrations",
        "/partners",
        "/customers",
        "/case-studies",
        "/careers",
        "/jobs",
        "/blog",
        "/news",
        "/press",
        "/resources",
        "/investors",
    )
    HIGH_VALUE_KEYWORDS = {
        "leadership": 45,
        "executive": 45,
        "partner": 42,
        "alliance": 42,
        "customer": 40,
        "case-stud": 40,
        "integration": 38,
        "career": 38,
        "jobs": 38,
        "investor": 38,
        "acquisition": 36,
        "product": 34,
        "solution": 32,
        "pricing": 32,
        "press": 30,
        "news": 28,
        "blog": 24,
        "resource": 20,
        "about": 20,
    }
    SKIP_EXTENSIONS = {
        ".7z",
        ".avi",
        ".css",
        ".csv",
        ".doc",
        ".docx",
        ".exe",
        ".gif",
        ".gz",
        ".ico",
        ".jpeg",
        ".jpg",
        ".js",
        ".json",
        ".mov",
        ".mp3",
        ".mp4",
        ".png",
        ".ppt",
        ".pptx",
        ".rar",
        ".svg",
        ".tar",
        ".webp",
        ".xls",
        ".xlsx",
        ".xml",
        ".zip",
    }
    ATS_HOSTS = (
        "boards.greenhouse.io",
        "job-boards.greenhouse.io",
        "jobs.lever.co",
        "jobs.ashbyhq.com",
        "apply.workable.com",
        "jobs.smartrecruiters.com",
    )

    def __init__(self, competitor_id: int, competitor_name: str, domain: str):
        super().__init__(competitor_id, competitor_name, domain)
        self.base_url = f"https://{domain}" if not domain.startswith("http") else domain
        self.max_pages = max(settings.crawler_max_pages, 1)
        self.max_depth = max(settings.crawler_max_depth, 0)
        self.concurrency = max(settings.crawler_concurrency, 1)
        self.max_browser_fallbacks = max(settings.crawler_max_browser_fallbacks, 0)
        self.request_timeout = max(settings.crawler_request_timeout_seconds, 1.0)
        self.min_content_chars = max(settings.crawler_min_content_chars, 0)
        self.change_monitor = PageChangeMonitor(competitor_id, competitor_name)
        self.last_run_stats: Dict[str, Any] = {}
        self.discovered_feeds: set[str] = set()
        self.discovered_job_boards: set[str] = set()
        self.discovered_profiles: Dict[str, int] = {}
        self._profile_identities_seen: set[tuple[str, str]] = set()
        self._robots: Optional[RobotFileParser] = None
        self._sequence = 0
        self.campaign: CollectionCampaignStore | None = None
        self._access_recovery_enabled: bool | None = None
        self._access_recovery_attempts = 0
        self._last_browser_failure: Dict[str, Any] | None = None
        self.error_store = CollectionErrorStore(competitor_id)

    async def collect(self) -> List[Dict[str, Any]]:
        """Run a bounded, prioritized, hybrid crawl."""
        started_at = datetime.now(timezone.utc)
        self.discovered_feeds.clear()
        self.discovered_job_boards.clear()
        self.discovered_profiles.clear()
        self._profile_identities_seen.clear()
        results: List[Dict[str, Any]] = []
        visited: set[str] = set()
        completed_urls: set[str] = set()
        enqueued: set[str] = set()
        queue: List[CrawlTarget] = []
        stats: Dict[str, Any] = {
            "engine": "hybrid-http-playwright",
            "max_pages": self.max_pages,
            "max_depth": self.max_depth,
            "http_pages": 0,
            "browser_pages": 0,
            "browser_attempts": 0,
            "browser_budget_skips": 0,
            "access_recovery_enabled": False,
            "access_recovery_attempts": 0,
            "access_recovery_successes": 0,
            "access_recovery_failures": 0,
            "pdf_documents": 0,
            "sitemap_urls": 0,
            "feed_urls": 0,
            "job_board_urls": 0,
            "blocked_by_robots": 0,
            "rate_limited": 0,
            "access_denied": 0,
            "not_found": 0,
            "client_errors": 0,
            "failed": 0,
            "unchanged": 0,
            "persisted": 0,
            "resumed": 0,
            "profiles_discovered": {},
        }
        if not self.domain:
            stats.update(
                {
                    "skipped": True,
                    "skip_reason": "No verified website; name-based collectors remain active",
                    "duration_seconds": 0.0,
                }
            )
            self.last_run_stats = stats
            return []
        if self.run_id is not None and settings.crawler_access_recovery_available:
            try:
                self._access_recovery_enabled = (
                    CollectionAccessPolicyStore.is_enabled(self.competitor_id)
                )
            except Exception as exc:
                logger.warning("Could not load access-recovery policy: %s", exc)
                self._access_recovery_enabled = False
        else:
            self._access_recovery_enabled = False
        stats["access_recovery_enabled"] = bool(self._access_recovery_enabled)

        if self.run_id is not None and settings.crawler_resume_campaigns:
            self.campaign = CollectionCampaignStore(
                self.competitor_id,
                run_id=self.run_id,
                campaign_type="web",
            )
            self.campaign.start(
                budget={
                    "max_pages": self.max_pages,
                    "max_depth": self.max_depth,
                    "concurrency": self.concurrency,
                    "browser_fallbacks": self.max_browser_fallbacks,
                }
            )
            self.error_store.run_id = self.run_id
            self.error_store.campaign_id = self.campaign.campaign_id
            for target in self.campaign.resume_targets(self.max_pages):
                if target.url in enqueued or target.depth > self.max_depth:
                    continue
                enqueued.add(target.url)
                self._sequence += 1
                heapq.heappush(
                    queue,
                    CrawlTarget(
                        -target.priority,
                        self._sequence,
                        target.url,
                        target.depth,
                        target.discovered_from,
                    ),
                )
                stats["resumed"] += 1

        limits = httpx.Limits(
            max_connections=self.concurrency,
            max_keepalive_connections=self.concurrency,
        )
        headers = {
            "User-Agent": self.USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/pdf;q=0.9,*/*;q=0.5",
        }

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=self.request_timeout,
            limits=limits,
            headers=headers,
        ) as client:
            sitemap_urls = await self._load_discovery_sources(client)
            stats["sitemap_urls"] = len(sitemap_urls)

            for path in self.TARGET_PATHS:
                self._enqueue(
                    queue,
                    enqueued,
                    urljoin(self.base_url, path),
                    depth=0,
                    discovered_from="seed",
                )
            for url in sitemap_urls:
                self._enqueue(
                    queue,
                    enqueued,
                    url,
                    depth=0,
                    discovered_from="sitemap",
                )

            playwright = None
            browser = None
            browser_context = None
            browser_page = None
            try:
                while queue and len(visited) < self.max_pages:
                    batch: List[CrawlTarget] = []
                    while (
                        queue
                        and len(batch) < self.concurrency
                        and len(visited) < self.max_pages
                    ):
                        target = heapq.heappop(queue)
                        if target.url in visited:
                            continue
                        if not self._allowed_by_robots(target.url):
                            visited.add(target.url)
                            stats["blocked_by_robots"] += 1
                            self._mark_campaign_outcome(
                                target.url,
                                state="blocked",
                                metadata={"reason": "robots"},
                            )
                            self._record_collection_error(
                                url=target.url,
                                error_code="robots_disallowed",
                                category="policy",
                                attempts=["robots_policy"],
                                technical_message=(
                                    "robots.txt disallows collection for this URL"
                                ),
                                user_message=(
                                    "Collection was skipped because the website's robots.txt "
                                    "policy disallows this page."
                                ),
                                suggested_action=(
                                    "Use an allowed public source. Access recovery is never used "
                                    "to override robots.txt."
                                ),
                                recoverable=False,
                            )
                            continue
                        visited.add(target.url)
                        if self.campaign:
                            self.campaign.mark_fetching(target.url)
                        batch.append(target)

                    if not batch:
                        continue

                    fetched = await asyncio.gather(
                        *(self._fetch_http_page(client, target.url) for target in batch),
                        return_exceptions=True,
                    )

                    for target, outcome in zip(batch, fetched):
                        extracted: Optional[ExtractedPage] = None
                        needs_browser = False
                        attempted_engines = ["httpx"]
                        failure_status: int | None = None
                        technical_error: str | None = None

                        if isinstance(outcome, Exception):
                            logger.warning("HTTP crawl failed for %s: %s", target.url, outcome)
                            technical_error = str(outcome)
                            self._mark_campaign_outcome(
                                target.url,
                                state="failed",
                                error=technical_error,
                            )
                            needs_browser = stats["browser_attempts"] < self.max_browser_fallbacks
                        elif outcome is None:
                            stats["failed"] += 1
                            technical_error = "HTTP collector returned no usable response"
                            self._mark_campaign_outcome(
                                target.url,
                                state="failed",
                                error="empty response",
                            )
                            self._record_collection_error(
                                url=target.url,
                                error_code="empty_response",
                                category="extraction",
                                attempts=attempted_engines,
                                technical_message=technical_error,
                                user_message=(
                                    "The website responded, but no supported HTML or PDF "
                                    "content could be extracted."
                                ),
                                suggested_action=(
                                    "Check whether this URL is a downloadable file, API response, "
                                    "or unsupported media type."
                                ),
                            )
                        else:
                            extracted = outcome
                            challenge_detected = self._looks_like_access_challenge(extracted)
                            if challenge_detected and self._can_attempt_access_recovery():
                                attempted_engines.append("curl_cffi")
                                stats["access_recovery_attempts"] += 1
                                try:
                                    recovered = await self._fetch_access_recovery(target.url)
                                    if (
                                        recovered
                                        and recovered.status_code < 400
                                        and not self._looks_like_access_challenge(recovered)
                                    ):
                                        extracted = recovered
                                        stats["access_recovery_successes"] += 1
                                    else:
                                        if recovered:
                                            extracted = recovered
                                        stats["access_recovery_failures"] += 1
                                except Exception as exc:
                                    technical_error = str(exc)
                                    stats["access_recovery_failures"] += 1
                                    logger.warning(
                                        "Advanced access recovery failed for %s: %s",
                                        target.url,
                                        exc,
                                    )

                            if extracted.status_code == 429:
                                stats["rate_limited"] += 1
                                self._mark_campaign_outcome(
                                    target.url,
                                    state="failed",
                                    status_code=429,
                                    error="rate limited",
                                )
                                self._record_http_error(
                                    target.url,
                                    429,
                                    attempted_engines,
                                )
                                extracted = None
                            elif extracted.status_code in {401, 403, 405}:
                                stats["access_denied"] += 1
                                failure_status = extracted.status_code
                                self._mark_campaign_outcome(
                                    target.url,
                                    state="blocked",
                                    status_code=extracted.status_code,
                                    error="access denied",
                                )
                                extracted = None
                                needs_browser = (
                                    stats["browser_attempts"] < self.max_browser_fallbacks
                                )
                            elif extracted.status_code in {404, 410}:
                                stats["not_found"] += 1
                                self._mark_campaign_outcome(
                                    target.url,
                                    state="skipped",
                                    status_code=extracted.status_code,
                                    error="not found",
                                )
                                self._record_http_error(
                                    target.url,
                                    extracted.status_code,
                                    attempted_engines,
                                )
                                extracted = None
                            elif 400 <= extracted.status_code < 500:
                                stats["client_errors"] += 1
                                self._mark_campaign_outcome(
                                    target.url,
                                    state="skipped",
                                    status_code=extracted.status_code,
                                    error="client error",
                                )
                                self._record_http_error(
                                    target.url,
                                    extracted.status_code,
                                    attempted_engines,
                                )
                                extracted = None
                            elif extracted.status_code >= 500:
                                failure_status = extracted.status_code
                                if self._looks_like_access_challenge(extracted):
                                    needs_browser = (
                                        stats["browser_attempts"] < self.max_browser_fallbacks
                                    )
                                else:
                                    stats["failed"] += 1
                                    self._record_http_error(
                                        target.url,
                                        extracted.status_code,
                                        attempted_engines,
                                    )
                                extracted = None
                            elif extracted.content_type == "application/pdf":
                                stats["pdf_documents"] += 1
                            else:
                                stats["http_pages"] += 1
                                needs_browser = (
                                    self._looks_like_access_challenge(extracted)
                                    or self._needs_browser(extracted)
                                )

                        if needs_browser and extracted is not None:
                            if stats["browser_attempts"] < self.max_browser_fallbacks:
                                # Keep HTTP metadata only if the browser cannot be attempted.
                                extracted = None
                            else:
                                needs_browser = False
                                stats["browser_budget_skips"] += 1

                        if needs_browser:
                            stats["browser_attempts"] += 1
                            attempted_engines.append("playwright")
                            try:
                                if playwright is None:
                                    playwright = await async_playwright().start()
                                    browser = await playwright.chromium.launch(headless=True)
                                    browser_context = await browser.new_context(
                                        user_agent=self.USER_AGENT,
                                        viewport={"width": 1440, "height": 1000},
                                    )
                                    browser_page = await browser_context.new_page()
                                browser_result = await self._scrape_page(browser_page, target.url)
                                if browser_result:
                                    self._resolve_collection_error(target.url)
                                    result_url = browser_result.get("url", target.url)
                                    if result_url in completed_urls:
                                        self._mark_campaign_outcome(
                                            target.url,
                                            state="skipped",
                                            status_code=200,
                                            metadata={
                                                "engine": "playwright",
                                                "result_url": result_url,
                                                "reason": "duplicate_redirect_target",
                                            },
                                        )
                                        self._enqueue_discovered(
                                            queue,
                                            enqueued,
                                            browser_result.get("links", []),
                                            target.depth + 1,
                                            target.url,
                                        )
                                        continue
                                    completed_urls.add(result_url)
                                    stats["browser_pages"] += 1
                                    self._track_discoveries(browser_result)
                                    results.append(browser_result)
                                    if browser_result.get("persisted"):
                                        stats["persisted"] += 1
                                        campaign_state = "completed"
                                    else:
                                        stats["unchanged"] += 1
                                        campaign_state = "unchanged"
                                    self._mark_campaign_outcome(
                                        target.url,
                                        state=campaign_state,
                                        status_code=200,
                                        metadata={
                                            "engine": "playwright",
                                            "result_url": result_url,
                                        },
                                    )
                                    self._enqueue_discovered(
                                        queue,
                                        enqueued,
                                        browser_result.get("links", []),
                                        target.depth + 1,
                                        target.url,
                                    )
                                else:
                                    stats["failed"] += 1
                                    browser_failure = self._last_browser_failure or {}
                                    self._mark_campaign_outcome(
                                        target.url,
                                        state="failed",
                                        status_code=browser_failure.get("http_status"),
                                        error=browser_failure.get(
                                            "technical_message",
                                            "browser extraction returned no content",
                                        ),
                                    )
                                    browser_status = browser_failure.get("http_status")
                                    if browser_status and browser_status >= 400:
                                        self._record_http_error(
                                            target.url,
                                            browser_status,
                                            attempted_engines,
                                        )
                                    elif browser_failure:
                                        self._record_collection_error(
                                            url=target.url,
                                            error_code=browser_failure.get(
                                                "error_code",
                                                "browser_access_challenge",
                                            ),
                                            category=browser_failure.get(
                                                "category",
                                                "access_denied",
                                            ),
                                            attempts=attempted_engines,
                                            technical_message=browser_failure.get(
                                                "technical_message",
                                                "Browser renderer encountered an access challenge",
                                            ),
                                            user_message=browser_failure.get(
                                                "user_message",
                                                "The browser renderer reached a verification or "
                                                "access-challenge page instead of public content.",
                                            ),
                                            suggested_action=browser_failure.get(
                                                "suggested_action",
                                                "Try another official source or retry later. "
                                                "CAPTCHA and login barriers are not bypassed.",
                                            ),
                                            severity="error",
                                        )
                                    elif failure_status:
                                        self._record_http_error(
                                            target.url,
                                            failure_status,
                                            attempted_engines,
                                        )
                                    else:
                                        self._record_collection_error(
                                            url=target.url,
                                            error_code="browser_empty_response",
                                            category="extraction",
                                            attempts=attempted_engines,
                                            technical_message=(
                                                "Playwright returned no extractable page content"
                                            ),
                                            user_message=(
                                                "The normal and browser collectors could not "
                                                "extract usable content from this page."
                                            ),
                                            suggested_action=(
                                                "Open the URL manually and check for a login, "
                                                "CAPTCHA, unsupported media, or an unavailable page."
                                            ),
                                            severity="error",
                                        )
                            except Exception as exc:
                                logger.warning("Browser fallback failed for %s: %s", target.url, exc)
                                stats["failed"] += 1
                                self._mark_campaign_outcome(
                                    target.url,
                                    state="failed",
                                    error=str(exc),
                                )
                                self._record_collection_error(
                                    url=target.url,
                                    error_code="browser_fallback_failed",
                                    category="browser",
                                    attempts=attempted_engines,
                                    technical_message=str(exc),
                                    user_message=(
                                        "The browser fallback failed while trying to render "
                                        "this page."
                                    ),
                                    suggested_action=(
                                        "Retry later and review the technical message. "
                                        "CAPTCHA and login barriers require a different source."
                                    ),
                                    severity="error",
                                )
                            continue

                        if not extracted:
                            if failure_status:
                                stats["failed"] += 1
                                self._record_http_error(
                                    target.url,
                                    failure_status,
                                    attempted_engines,
                                )
                            elif technical_error:
                                stats["failed"] += 1
                                self._record_collection_error(
                                    url=target.url,
                                    error_code="network_failure",
                                    category="network",
                                    attempts=attempted_engines,
                                    technical_message=technical_error,
                                    user_message=(
                                        "The crawler could not establish a reliable connection "
                                        "to this page."
                                    ),
                                    suggested_action=(
                                        "Check DNS and network availability, then retry the "
                                        "collection later."
                                    ),
                                    severity="error",
                                )
                            continue

                        if extracted.url in completed_urls:
                            self._mark_campaign_outcome(
                                target.url,
                                state="skipped",
                                status_code=extracted.status_code,
                                metadata={
                                    "engine": extracted.engine,
                                    "result_url": extracted.url,
                                    "reason": "duplicate_redirect_target",
                                },
                            )
                            self._enqueue_discovered(
                                queue,
                                enqueued,
                                extracted.links,
                                target.depth + 1,
                                target.url,
                            )
                            continue
                        completed_urls.add(extracted.url)
                        self._resolve_collection_error(target.url)
                        result = await self._persist_extracted_page(extracted)
                        if result:
                            self._track_discoveries(result)
                            results.append(result)
                            if result.get("persisted"):
                                stats["persisted"] += 1
                                campaign_state = "completed"
                            else:
                                stats["unchanged"] += 1
                                campaign_state = "unchanged"
                            self._mark_campaign_outcome(
                                target.url,
                                state=campaign_state,
                                status_code=extracted.status_code,
                                content_hash=hashlib.sha256(
                                    (
                                        extracted.title
                                        + extracted.description
                                        + extracted.body_text
                                    ).encode("utf-8")
                                ).hexdigest(),
                                metadata={
                                    "engine": extracted.engine,
                                    "page_type": extracted.page_type,
                                    "result_url": extracted.url,
                                },
                            )
                            self._enqueue_discovered(
                                queue,
                                enqueued,
                                extracted.links,
                                target.depth + 1,
                                target.url,
                            )
            finally:
                if browser_context:
                    await browser_context.close()
                if browser:
                    await browser.close()
                if playwright:
                    await playwright.stop()

        stats["visited"] = len(visited)
        stats["returned"] = len(results)
        stats["feed_urls"] = len(self.discovered_feeds)
        stats["job_board_urls"] = len(self.discovered_job_boards)
        stats["profiles_discovered"] = self.discovered_profiles
        stats["duration_seconds"] = round(
            (datetime.now(timezone.utc) - started_at).total_seconds(),
            2,
        )
        self.last_run_stats = stats
        if self.campaign:
            self.campaign.event(
                adapter_name="web_crawler",
                event_type="campaign_completed",
                success=stats["failed"] == 0,
                items=stats["persisted"],
                metadata={
                    "visited": stats["visited"],
                    "unchanged": stats["unchanged"],
                    "profiles_discovered": stats["profiles_discovered"],
                },
            )
            self.campaign.finish(
                status="partial" if stats["failed"] else "completed",
                statistics=stats,
            )
        logger.info(
            "CrawlerV2 collected %s pages for %s (%s)",
            len(results),
            self.competitor_name,
            stats,
        )
        return results

    async def _load_discovery_sources(self, client: httpx.AsyncClient) -> List[str]:
        """Load robots.txt plus sitemap indexes before the main crawl."""
        sitemap_locations = {urljoin(self.base_url, "/sitemap.xml")}
        robots_url = urljoin(self.base_url, "/robots.txt")

        if settings.crawler_respect_robots:
            try:
                response = await client.get(robots_url)
                if response.status_code < 400:
                    self._robots = RobotFileParser()
                    self._robots.set_url(robots_url)
                    self._robots.parse(response.text.splitlines())
                    for line in response.text.splitlines():
                        if line.lower().startswith("sitemap:"):
                            sitemap_locations.add(line.split(":", 1)[1].strip())
            except Exception as exc:
                logger.info("robots.txt unavailable for %s: %s", self.domain, exc)

        discovered: List[str] = []
        pending = list(sitemap_locations)
        seen_sitemaps: set[str] = set()
        while pending and len(seen_sitemaps) < settings.crawler_max_sitemaps:
            sitemap_url = pending.pop(0)
            if sitemap_url in seen_sitemaps:
                continue
            seen_sitemaps.add(sitemap_url)
            try:
                response = await client.get(sitemap_url)
                if response.status_code >= 400 or len(response.content) > 5_000_000:
                    continue
                root = ElementTree.fromstring(response.content)
                for element in root.iter():
                    if not element.tag.lower().endswith("loc") or not element.text:
                        continue
                    location = element.text.strip()
                    if location.lower().endswith((".xml", ".xml.gz")):
                        if location not in seen_sitemaps:
                            pending.append(location)
                        continue
                    canonical = self._canonical_url(location)
                    if canonical and canonical not in discovered:
                        discovered.append(canonical)
                        if len(discovered) >= settings.crawler_max_sitemap_urls:
                            return discovered
            except Exception as exc:
                logger.debug("Sitemap unavailable at %s: %s", sitemap_url, exc)
        return discovered

    def _can_attempt_access_recovery(self) -> bool:
        return bool(
            self._access_recovery_enabled
            and self._access_recovery_attempts
            < max(settings.crawler_access_recovery_max_attempts, 0)
        )

    @staticmethod
    def _looks_like_access_challenge(page: ExtractedPage) -> bool:
        if page.status_code in {401, 403, 405}:
            return True
        challenge_text = f"{page.title} {page.body_text[:2000]}".casefold()
        markers = (
            "just a moment",
            "checking your browser",
            "verify you are human",
            "access denied",
            "attention required",
            "security challenge",
            "enable javascript and cookies",
        )
        has_challenge_marker = any(marker in challenge_text for marker in markers)
        return (
            page.status_code == 503 and has_challenge_marker
        ) or (
            page.status_code < 400 and has_challenge_marker
        )

    async def _fetch_access_recovery(self, url: str) -> ExtractedPage | None:
        """Make one browser-compatible public request without solving challenges."""
        if not self._can_attempt_access_recovery():
            return None
        self._access_recovery_attempts += 1

        def request():
            from curl_cffi import requests as curl_requests

            return curl_requests.get(
                url,
                impersonate=settings.crawler_access_recovery_impersonate,
                timeout=self.request_timeout,
                allow_redirects=True,
            )

        response = await asyncio.to_thread(request)
        final_url = self._canonical_url(str(response.url)) or url
        headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
        content_type = headers.get("content-type", "").split(";", 1)[0].lower()
        if response.status_code >= 400:
            return ExtractedPage(
                url=final_url,
                title="",
                description="",
                headings=[],
                body_text=str(response.text or "")[:4000],
                links=[],
                external_links=[],
                page_type="blocked" if response.status_code in {401, 403, 405} else "http_error",
                status_code=int(response.status_code),
                engine="curl_cffi",
                response_headers=headers,
            )
        if len(response.content) > settings.crawler_max_document_bytes:
            return None
        if content_type == "application/pdf" or final_url.lower().endswith(".pdf"):
            page = self._extract_pdf(final_url, bytes(response.content))
            if page:
                page.engine = "curl_cffi-pdf"
                page.response_headers = headers
            return page
        if "html" not in content_type and content_type not in {"", "text/plain"}:
            return None
        page = self._extract_html(final_url, str(response.text), int(response.status_code))
        page.engine = "curl_cffi"
        page.response_headers = headers
        return page

    def _record_collection_error(
        self,
        *,
        url: str,
        error_code: str,
        category: str,
        technical_message: str,
        user_message: str,
        attempts: List[str],
        suggested_action: str,
        http_status: int | None = None,
        severity: str = "warning",
        recoverable: bool = True,
    ) -> None:
        try:
            self.error_store.record(
                url=url,
                error_code=error_code,
                category=category,
                http_status=http_status,
                severity=severity,
                engine=attempts[-1] if attempts else None,
                attempts=attempts,
                technical_message=technical_message,
                user_message=user_message,
                suggested_action=suggested_action,
                recoverable=recoverable,
            )
        except Exception as exc:
            logger.warning("Could not persist collection error for %s: %s", url, exc)

    def _resolve_collection_error(self, url: str) -> None:
        try:
            self.error_store.resolve_url(url)
        except Exception as exc:
            logger.debug("Could not resolve collection error for %s: %s", url, exc)

    def _record_http_error(
        self,
        url: str,
        status_code: int,
        attempts: List[str],
    ) -> None:
        if status_code in {404, 410}:
            self._record_collection_error(
                url=url,
                error_code=f"http_{status_code}",
                category="not_found",
                http_status=status_code,
                attempts=attempts,
                technical_message=f"HTTP {status_code} returned for {url}",
                user_message=(
                    f"Could not fetch this page because the website returned HTTP "
                    f"{status_code} (Not Found)."
                ),
                suggested_action=(
                    "Check whether the page moved. The crawler will continue with sitemaps, "
                    "canonical links, parent domains, and other public sources."
                ),
            )
            return
        if status_code == 429:
            self._record_collection_error(
                url=url,
                error_code="http_429",
                category="rate_limited",
                http_status=429,
                attempts=attempts,
                technical_message=f"HTTP 429 rate limit returned for {url}",
                user_message=(
                    "The website rate-limited collection with HTTP 429. "
                    "No access-recovery retry was attempted."
                ),
                suggested_action=(
                    "Wait for the website cooldown. A later pipeline run can retry this URL."
                ),
            )
            return
        if status_code in {401, 403, 405}:
            self._record_collection_error(
                url=url,
                error_code=f"http_{status_code}_access_denied",
                category="access_denied",
                http_status=status_code,
                attempts=attempts,
                severity="error",
                technical_message=(
                    f"HTTP {status_code} remained after collection engines: "
                    f"{', '.join(attempts)}"
                ),
                user_message=(
                    f"The website denied automated access with HTTP {status_code}. "
                    f"Attempted: {', '.join(attempts)}."
                ),
                suggested_action=(
                    "Confirm the source is public, try again later, or use another official "
                    "source. CAPTCHA and login barriers are not bypassed."
                ),
            )
            return
        self._record_collection_error(
            url=url,
            error_code=f"http_{status_code}",
            category="http_error",
            http_status=status_code,
            attempts=attempts,
            technical_message=f"HTTP {status_code} returned for {url}",
            user_message=f"Could not fetch this page because it returned HTTP {status_code}.",
            suggested_action="Check the URL and retry during a later collection run.",
            severity="error" if status_code >= 500 else "warning",
        )

    async def _fetch_http_page(
        self,
        client: httpx.AsyncClient,
        url: str,
    ) -> Optional[ExtractedPage]:
        """Fetch with bounded retries. Do not retry access-control responses."""
        response: Optional[httpx.Response] = None
        for attempt in range(settings.crawler_retry_attempts + 1):
            try:
                response = await client.get(url)
                if response.status_code in {403, 401, 429}:
                    logger.info("Crawler access response %s for %s", response.status_code, url)
                    return ExtractedPage(
                        url=url,
                        title="",
                        description="",
                        headings=[],
                        body_text=response.text[:4000],
                        links=[],
                        external_links=[],
                        page_type="blocked",
                        status_code=response.status_code,
                        response_headers={
                            str(key).lower(): str(value)
                            for key, value in response.headers.items()
                        },
                    )
                if response.status_code >= 500 and attempt < settings.crawler_retry_attempts:
                    await asyncio.sleep(0.5 * (2**attempt))
                    continue
                if response.status_code >= 500:
                    return ExtractedPage(
                        url=url,
                        title="",
                        description="",
                        headings=[],
                        body_text=response.text[:4000],
                        links=[],
                        external_links=[],
                        page_type="server_error",
                        status_code=response.status_code,
                        response_headers={
                            str(key).lower(): str(value)
                            for key, value in response.headers.items()
                        },
                    )
                if 400 <= response.status_code < 500:
                    logger.debug("Skipping HTTP %s at %s", response.status_code, url)
                    return ExtractedPage(
                        url=url,
                        title="",
                        description="",
                        headings=[],
                        body_text="",
                        links=[],
                        external_links=[],
                        page_type="http_error",
                        status_code=response.status_code,
                        response_headers={
                            str(key).lower(): str(value)
                            for key, value in response.headers.items()
                        },
                    )
                response.raise_for_status()
                break
            except (httpx.TimeoutException, httpx.TransportError):
                if attempt >= settings.crawler_retry_attempts:
                    raise
                await asyncio.sleep(0.5 * (2**attempt))

        if response is None:
            return None

        final_url = self._canonical_url(str(response.url)) or url
        content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
        if content_type == "application/pdf" or final_url.lower().endswith(".pdf"):
            if len(response.content) > settings.crawler_max_document_bytes:
                logger.info("Skipping oversized PDF %s", final_url)
                return None
            return self._extract_pdf(final_url, response.content)
        if "html" not in content_type and content_type not in {"", "text/plain"}:
            return None
        if len(response.content) > settings.crawler_max_document_bytes:
            logger.info("Skipping oversized page %s", final_url)
            return None
        page = self._extract_html(final_url, response.text, response.status_code)
        page.response_headers = {
            str(key).lower(): str(value) for key, value in response.headers.items()
        }
        return page

    def _extract_html(self, url: str, html: str, status_code: int) -> ExtractedPage:
        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        description_tag = soup.select_one('meta[name="description"]')
        description = (
            str(description_tag.get("content", "")).strip() if description_tag else ""
        )
        headings = [
            element.get_text(" ", strip=True)
            for element in soup.select("h1, h2, h3")
            if element.get_text(" ", strip=True)
        ][:100]

        links: List[str] = []
        external_links: List[str] = []
        feed_urls: List[str] = []
        for link in soup.select("a[href], link[href]"):
            href = str(link.get("href", "")).strip()
            if not href:
                continue
            full_url = urljoin(url, href)
            rel = " ".join(link.get("rel", []))
            link_type = str(link.get("type", "")).lower()
            if "alternate" in rel and ("rss" in link_type or "atom" in link_type):
                feed_urls.append(full_url)
            canonical = self._canonical_url(full_url)
            if canonical:
                if self._crawlable_url(canonical):
                    links.append(canonical)
            elif full_url.startswith(("http://", "https://")):
                external_links.append(full_url.split("#", 1)[0])

        structured_data: List[Dict[str, Any]] = []
        for script in soup.select('script[type="application/ld+json"]'):
            try:
                value = json.loads(script.get_text(strip=True))
                values = value if isinstance(value, list) else [value]
                structured_data.extend(item for item in values if isinstance(item, dict))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue

        for element in soup.select(
            "script, style, noscript, template, svg, nav, footer, header, form"
        ):
            element.decompose()
        main = soup.select_one("main, article, [role=main]") or soup.body or soup
        body_text = re.sub(r"\s+", " ", main.get_text(" ", strip=True)).strip()
        page_type = self._classify_page(url, title, headings)
        return ExtractedPage(
            url=url,
            title=title,
            description=description,
            headings=headings,
            body_text=body_text,
            links=list(dict.fromkeys(links))[:250],
            external_links=list(dict.fromkeys(external_links))[:250],
            page_type=page_type,
            structured_data=structured_data[:25],
            feed_urls=list(dict.fromkeys(feed_urls))[:25],
            engine="http",
            status_code=status_code,
        )

    def _extract_pdf(self, url: str, content: bytes) -> Optional[ExtractedPage]:
        try:
            reader = PdfReader(io.BytesIO(content))
            pages = []
            for page in reader.pages[: settings.crawler_max_pdf_pages]:
                pages.append(page.extract_text() or "")
            body_text = re.sub(r"\s+", " ", " ".join(pages)).strip()
            if not body_text:
                return None
            title = str(reader.metadata.title or "") if reader.metadata else ""
            return ExtractedPage(
                url=url,
                title=title or url.rsplit("/", 1)[-1],
                description="",
                headings=[],
                body_text=body_text,
                links=[],
                external_links=[],
                page_type="document",
                content_type="application/pdf",
                engine="http-pdf",
            )
        except Exception as exc:
            logger.warning("Could not extract PDF %s: %s", url, exc)
            return None

    async def _persist_extracted_page(
        self,
        page: ExtractedPage,
    ) -> Optional[Dict[str, Any]]:
        collected_content = "\n".join(
            part
            for part in (
                page.title,
                page.description,
                "\n".join(page.headings),
                page.body_text,
            )
            if part
        )
        budgeted = apply_text_byte_budget(
            collected_content,
            settings.crawler_max_document_bytes,
        )
        content_for_hash = budgeted.text
        if not content_for_hash.strip():
            return None
        content_hash = hashlib.sha256(content_for_hash.encode("utf-8")).hexdigest()
        source = f"web:{page.url}"
        metadata = {
            "url": page.url,
            "title": page.title,
            "description": page.description,
            "headings": page.headings[:100],
            "page_type": page.page_type,
            "content_type": page.content_type,
            "discovered_links": page.links[:100],
            "external_links": page.external_links[:100],
            "structured_data": page.structured_data,
            "feed_urls": page.feed_urls,
            "collector": "crawler_v2",
            "engine": page.engine,
            "status_code": page.status_code,
            "content_budget": {
                "limit_bytes": settings.crawler_max_document_bytes,
                "original_bytes": budgeted.original_bytes,
                "stored_bytes": budgeted.stored_bytes,
                "truncated": budgeted.truncated,
            },
        }
        snapshot = self.change_monitor.record_snapshot(
            source_url=page.url,
            title=page.title,
            content=content_for_hash,
            metadata=metadata,
        )
        result = {
            "url": page.url,
            "title": page.title,
            "description": page.description,
            "headings": page.headings,
            "body_preview": page.body_text[:1000],
            "content_bytes": budgeted.stored_bytes,
            "content_truncated": budgeted.truncated,
            "links": page.links,
            "external_links": page.external_links,
            "structured_data": page.structured_data,
            "feed_urls": page.feed_urls,
            "page_type": page.page_type,
            "content_type": page.content_type,
            "engine": page.engine,
            "persisted": False,
            "snapshot_saved": snapshot.snapshot_saved,
            "change_detected": snapshot.change_detected,
            "change_type": snapshot.change_type,
            "change_significance": snapshot.significance,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }
        if not await self.has_changed(source, content_for_hash):
            return result

        saved = self.save_raw_data(
            source=source,
            content=content_for_hash,
            content_hash=content_hash,
            metadata=metadata,
        )
        if not saved:
            return None
        evidence_id = self.save_evidence(
            source_url=page.url,
            title=page.title,
            content=content_for_hash,
            content_hash=content_hash,
            confidence=0.92 if page.content_type == "text/html" else 0.88,
            metadata={
                "source_type": "first_party_website",
                "page_type": page.page_type,
                "content_type": page.content_type,
                "collector": "crawler_v2",
                "engine": page.engine,
            },
        )
        await self.mark_seen(source, content_for_hash)
        result["persisted"] = True
        result["evidence_id"] = evidence_id
        return result

    async def _scrape_page(self, page, url: str) -> Optional[Dict[str, Any]]:
        """Playwright fallback retained as a separately testable engine."""
        self._last_browser_failure = None
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=25000,
            )
            response_status = getattr(response, "status", 200)
            if not isinstance(response_status, int):
                response_status = 200
            try:
                await page.wait_for_function(
                    "() => document.body && document.body.innerText.trim().length > 150",
                    timeout=4000,
                )
            except Exception:
                pass
            title = await page.title()
            description = await self._get_meta_description(page)
            headings = await self._get_headings(page)
            links = await self._get_relevant_links(page)
            external_links = await self._get_external_links(page)
            structured_data = await self._get_structured_data(page)
            body_text = await self._get_body_text(page)
            page_type = self._classify_page(str(page.url), title, headings)
            extracted = ExtractedPage(
                url=self._canonical_url(str(page.url)) or url,
                title=title,
                description=description,
                headings=headings,
                body_text=body_text,
                links=links,
                external_links=external_links,
                page_type=page_type,
                structured_data=structured_data,
                status_code=response_status,
                engine="playwright",
            )
            if response_status >= 400 or self._looks_like_access_challenge(extracted):
                self._last_browser_failure = {
                    "error_code": (
                        f"http_{response_status}_browser"
                        if response_status >= 400
                        else "browser_access_challenge"
                    ),
                    "http_status": response_status,
                    "category": "access_denied",
                    "technical_message": (
                        f"Playwright received HTTP {response_status} and rendered "
                        f"'{title or 'an untitled access page'}' for {url}"
                    ),
                    "user_message": (
                        "The browser renderer reached a verification or "
                        "access-challenge page instead of public content."
                    ),
                    "suggested_action": (
                        "Try another official source or retry later. "
                        "CAPTCHA and login barriers are not bypassed."
                    ),
                }
                return None
            return await self._persist_extracted_page(extracted)
        except Exception as exc:
            logger.error("Error rendering %s: %s", url, exc)
            self._last_browser_failure = {
                "error_code": "browser_fallback_failed",
                "http_status": None,
                "category": "browser",
                "technical_message": str(exc),
                "user_message": (
                    "The browser fallback failed while trying to render this page."
                ),
                "suggested_action": (
                    "Retry later and review the technical message. CAPTCHA and "
                    "login barriers require a different source."
                ),
            }
            return None

    def _needs_browser(self, page: ExtractedPage) -> bool:
        if page.status_code >= 400:
            return False
        return page.content_type == "text/html" and len(page.body_text) < self.min_content_chars

    def _enqueue(
        self,
        queue: List[CrawlTarget],
        enqueued: set[str],
        url: str,
        depth: int,
        discovered_from: str,
    ) -> None:
        canonical = self._canonical_url(url)
        if not canonical or canonical in enqueued or depth > self.max_depth:
            return
        if not self._crawlable_url(canonical):
            return
        enqueued.add(canonical)
        self._sequence += 1
        score = self._score_url(canonical, depth)
        if self.campaign:
            self.campaign.enqueue(
                canonical,
                depth=depth,
                priority=score,
                discovered_from=discovered_from,
                max_attempts=max(settings.crawler_retry_attempts + 1, 1),
            )
        heapq.heappush(
            queue,
            CrawlTarget(-score, self._sequence, canonical, depth, discovered_from),
        )

    def _enqueue_discovered(
        self,
        queue: List[CrawlTarget],
        enqueued: set[str],
        links: List[str],
        depth: int,
        discovered_from: str,
    ) -> None:
        for url in links:
            self._enqueue(queue, enqueued, url, depth, discovered_from)

    def _track_discoveries(self, result: Dict[str, Any]) -> None:
        self.discovered_feeds.update(result.get("feed_urls", []))
        for url in result.get("external_links", []):
            hostname = (urlparse(url).hostname or "").lower()
            if any(hostname == host or hostname.endswith(f".{host}") for host in self.ATS_HOSTS):
                self.discovered_job_boards.add(url)
        if self.run_id is None:
            return
        try:
            registry = SourceProfileStore(self.competitor_id)
            origin = str(result.get("url") or self.base_url)
            external_links = result.get("external_links", [])
            registry.discover_urls(
                external_links,
                discovered_from=origin,
                confidence=0.9,
                limit=settings.crawler_max_external_profiles,
            )
            for url in external_links:
                classified = registry.classify(url)
                if classified:
                    self._profile_identities_seen.add(classified)
            for feed_url in result.get("feed_urls", []):
                registry.discover(
                    source_type="rss",
                    profile_url=feed_url,
                    profile_key=feed_url,
                    confidence=0.95,
                    discovered_from=origin,
                )
                self._profile_identities_seen.add(
                    ("rss", registry.normalize_profile_url(feed_url))
                )
            counts: dict[str, int] = {}
            for source_type, _ in self._profile_identities_seen:
                counts[source_type] = counts.get(source_type, 0) + 1
            self.discovered_profiles = counts
        except Exception as exc:
            logger.warning("Could not persist source discoveries: %s", exc)

    def _mark_campaign_outcome(
        self,
        url: str,
        *,
        state: str,
        status_code: int | None = None,
        content_hash: str | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if not self.campaign:
            return
        try:
            self.campaign.mark_outcome(
                url,
                state=state,
                status_code=status_code,
                content_hash=content_hash,
                error=error,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("Could not update crawl frontier for %s: %s", url, exc)

    def finish_campaign_with_error(self, error: Exception | str) -> None:
        if self.campaign:
            self.campaign.finish(
                status="failed",
                statistics=self.last_run_stats,
                error=str(error),
            )

    def _allowed_by_robots(self, url: str) -> bool:
        if not settings.crawler_respect_robots or self._robots is None:
            return True
        return self._robots.can_fetch(self.USER_AGENT, url)

    def _crawlable_url(self, url: str) -> bool:
        path = urlparse(url).path.lower()
        if path.endswith(".pdf"):
            return True
        return not any(path.endswith(extension) for extension in self.SKIP_EXTENSIONS)

    def _score_url(self, url: str, depth: int) -> int:
        text = urlparse(url).path.casefold()
        score = 100 - (depth * 12)
        for keyword, bonus in self.HIGH_VALUE_KEYWORDS.items():
            if keyword in text:
                score += bonus
        if text.endswith(".pdf"):
            score += 25
        return score

    async def _get_meta_description(self, page) -> str:
        try:
            return await page.get_attribute('meta[name="description"]', "content") or ""
        except Exception:
            return ""

    async def _get_headings(self, page) -> List[str]:
        headings = []
        try:
            for element in await page.query_selector_all("h1, h2, h3"):
                text = await element.inner_text()
                if text.strip():
                    headings.append(text.strip())
        except Exception:
            pass
        return headings[:100]

    async def _get_body_text(self, page) -> str:
        try:
            body_text = await page.locator("body").inner_text()
            return re.sub(r"\s+", " ", body_text).strip()
        except Exception:
            return ""

    async def _get_relevant_links(self, page) -> List[str]:
        links = []
        try:
            for anchor in await page.query_selector_all("a[href]"):
                href = await anchor.get_attribute("href")
                canonical = self._canonical_url(urljoin(page.url, href or ""))
                if canonical and self._crawlable_url(canonical):
                    links.append(canonical)
        except Exception:
            pass
        return list(dict.fromkeys(links))[:250]

    async def _get_external_links(self, page) -> List[str]:
        links = []
        try:
            for anchor in await page.query_selector_all("a[href]"):
                href = await anchor.get_attribute("href")
                full_url = urljoin(page.url, href or "")
                parsed = urlparse(full_url)
                if parsed.scheme in {"http", "https"} and not self._same_domain(parsed.hostname):
                    links.append(full_url.split("#", 1)[0])
        except Exception:
            pass
        return list(dict.fromkeys(links))[:250]

    async def _get_structured_data(self, page) -> List[Dict[str, Any]]:
        try:
            values = await page.locator('script[type="application/ld+json"]').all_text_contents()
        except Exception:
            return []
        structured: List[Dict[str, Any]] = []
        for value in values:
            try:
                parsed = json.loads(value)
                items = parsed if isinstance(parsed, list) else [parsed]
                structured.extend(item for item in items if isinstance(item, dict))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
        return structured[:25]

    def _same_domain(self, hostname: str | None) -> bool:
        base_hostname = (urlparse(self.base_url).hostname or "").lower().removeprefix("www.")
        candidate = (hostname or "").lower().removeprefix("www.")
        return bool(candidate and (candidate == base_hostname or candidate.endswith(f".{base_hostname}")))

    def _canonical_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not self._same_domain(parsed.hostname):
            return ""
        path = re.sub(r"/{2,}", "/", parsed.path or "/")
        path = path.rstrip("/") or "/"
        base_hostname = (urlparse(self.base_url).hostname or "").lower().removeprefix("www.")
        candidate = (parsed.hostname or "").lower()
        # Treat the bare host and its www alias as one crawl identity while
        # preserving meaningful subdomains such as docs.example.com.
        netloc = base_hostname if candidate in {base_hostname, f"www.{base_hostname}"} else parsed.netloc
        return parsed._replace(netloc=netloc, path=path, query="", fragment="").geturl()

    @staticmethod
    def _classify_page(url: str, title: str, headings: List[str]) -> str:
        text = f"{url} {title} {' '.join(headings)}".casefold()
        categories = (
            ("document", (".pdf", "annual report", "whitepaper")),
            ("pricing", ("pricing", "plans", "subscription")),
            ("leadership", ("leadership", "executive", "our team", "management")),
            ("partners", ("partner", "alliance", "ecosystem")),
            ("integrations", ("integration", "marketplace", "connectors")),
            ("customers", ("customer", "case study", "case studies", "success stor")),
            ("careers", ("career", "jobs", "join our team", "open roles")),
            ("products", ("product", "solutions", "platform", "features")),
            ("investors", ("investor", "funding", "annual report")),
            ("news", ("blog", "news", "press", "resources", "insights")),
            ("company", ("about", "company")),
        )
        for category, keywords in categories:
            if any(keyword in text for keyword in keywords):
                return category
        return "general"
