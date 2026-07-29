import asyncio
import logging
import time
from typing import Dict, Any, Callable, List, Optional

from agents.ingestion.web_scraper import WebScraperAgent
from agents.ingestion.news_agent import NewsAgent
from agents.ingestion.job_scraper import JobScraperAgent
from agents.ingestion.external_sources import ExternalSourceAgent
from agents.enrichment.social_watcher import SocialWatcherAgent
from agents.enrichment.tech_stack import TechStackAgent
from agents.analysis.summariser import SummariserAgent
from agents.analysis.signal_detector import SignalDetectorAgent
from agents.analysis.predictor import PredictorAgent
from agents.discovery.entity_resolver import EntityResolverAgent
from config.settings import settings
from llm_gateway import get_active_llm_connection
from db.postgres import get_connection
from intelligence.foundation import PipelineCancelled, RunTracker, SourceHealthStore
from intelligence.events import EventFusionEngine
from intelligence.graph import RelationshipIntelligenceEngine
from intelligence.retrieval import EvidenceRetriever
from intelligence.verification import ClaimVerificationEngine

logger = logging.getLogger(__name__)


class CompetitorPipeline:
    """Full monitoring pipeline for a single competitor."""

    RETRYABLE_TASKS: Dict[str, Dict[str, Any]] = {
        "ingestion.web_crawler": {
            "stage": "ingestion",
            "agent_name": "WebScraperAgent",
            "max_attempts": 2,
        },
        "ingestion.news.collect": {
            "stage": "ingestion",
            "agent_name": "NewsAgent",
            "max_attempts": 2,
        },
        "ingestion.news.persist": {
            "stage": "ingestion",
            "agent_name": "NewsAgent",
            "max_attempts": 2,
        },
        "ingestion.jobs": {
            "stage": "ingestion",
            "agent_name": "JobScraperAgent",
            "max_attempts": 2,
        },
        "ingestion.external_sources": {
            "stage": "ingestion",
            "agent_name": "ExternalSourceAgent",
            "max_attempts": 2,
        },
        "ingestion.evidence_index": {
            "stage": "ingestion",
            "agent_name": "EvidenceRetriever",
            "max_attempts": 1,
        },
        "enrichment.social_feeds": {
            "stage": "enrichment",
            "agent_name": "SocialWatcherAgent",
            "max_attempts": 2,
        },
        "enrichment.tech_stack": {
            "stage": "enrichment",
            "agent_name": "TechStackAgent",
            "max_attempts": 2,
        },
        "analysis.summary": {
            "stage": "analysis",
            "agent_name": "SummariserAgent",
            "max_attempts": 2,
        },
        "analysis.entity_resolution": {
            "stage": "analysis",
            "agent_name": "EntityResolverAgent",
            "max_attempts": 2,
        },
        "analysis.relationship_fusion": {
            "stage": "analysis",
            "agent_name": "RelationshipIntelligenceEngine",
            "max_attempts": 1,
        },
        "analysis.signals": {
            "stage": "analysis",
            "agent_name": "SignalDetectorAgent",
            "max_attempts": 2,
        },
        "analysis.predictions": {
            "stage": "analysis",
            "agent_name": "PredictorAgent",
            "max_attempts": 2,
        },
        "analysis.claim_verification": {
            "stage": "analysis",
            "agent_name": "ClaimVerificationEngine",
            "max_attempts": 2,
        },
        "analysis.event_fusion": {
            "stage": "analysis",
            "agent_name": "EventFusionEngine",
            "max_attempts": 1,
        },
    }

    def __init__(
        self,
        competitor_id: int,
        competitor_name: str,
        domain: str | None,
        rss_feeds: List[str] = None,
        progress_callback: Optional[Callable[[str, str, Optional[Dict[str, Any]]], None]] = None,
        model: Optional[str] = None,
        run_id: Optional[int] = None,
        focus_topics: Optional[List[str]] = None,
    ):
        self.competitor_id = competitor_id
        self.competitor_name = competitor_name
        self.domain = domain or ""
        self.rss_feeds = rss_feeds or []
        self.progress_callback = progress_callback
        self.model = model or get_active_llm_connection().model
        self.run_id = run_id
        self.focus_topics = list(focus_topics or [])
        self.run_tracker = RunTracker(run_id)

    def _report_progress(
        self,
        stage: str,
        status: str,
        data: Optional[Dict[str, Any]] = None,
    ) -> None:
        if self.progress_callback:
            self.progress_callback(stage, status, data)

    def _run_async(self, coro):
        """Run async coroutine from sync context."""
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(asyncio.run, coro).result()
            else:
                return loop.run_until_complete(coro)
        except RuntimeError:
            return asyncio.run(coro)

    def _wait_for_analysis_rate_limit(self) -> None:
        """Throttle configured LLM calls without delaying keyless local runs."""
        delay = max(settings.analysis_rate_limit_seconds, 0)
        if get_active_llm_connection().configured and delay:
            logger.info(
                f"[{self.competitor_name}] Waiting {delay:g}s for analysis rate limit..."
            )
            time.sleep(delay)

    def _attach_run(self, agent):
        agent.run_id = self.run_id
        return agent

    def _execute_task(
        self,
        *,
        task_key: str,
        stage: str,
        agent_name: str,
        operation: Callable[[], Any],
        max_attempts: int = 2,
    ) -> Any:
        return self.run_tracker.execute(
            task_key=task_key,
            stage=stage,
            agent_name=agent_name,
            operation=operation,
            max_attempts=max_attempts,
            input_data={
                "competitor_id": self.competitor_id,
                "competitor_name": self.competitor_name,
            },
        )

    @classmethod
    def retryable_task_keys(cls) -> set[str]:
        """Return task identifiers that can be safely replayed in isolation."""
        return set(cls.RETRYABLE_TASKS)

    def _load_collected_news(self, source_run_id: int | None) -> List[Dict[str, Any]]:
        if source_run_id is None:
            raise ValueError("The original run is required to retry news persistence")
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT output
                    FROM pipeline_tasks
                    WHERE run_id = %s
                      AND task_key = 'ingestion.news.collect'
                      AND status = 'completed'
                    """,
                    (source_run_id,),
                )
                row = cur.fetchone()
        output = (row or {}).get("output") or {}
        articles = output.get("result") if isinstance(output, dict) else None
        if not isinstance(articles, list):
            raise ValueError(
                "The original news collection output is unavailable; retry news collection first"
            )
        return articles

    def _retry_operation(
        self,
        task_key: str,
        source_run_id: int | None,
    ) -> Callable[[], Any]:
        if task_key == "ingestion.web_crawler":
            agent = self._attach_run(
                WebScraperAgent(self.competitor_id, self.competitor_name, self.domain)
            )

            def retry_web() -> Any:
                result = self._run_async(agent.collect())
                self._register_discovered_feeds(sorted(agent.discovered_feeds))
                return result

            return retry_web

        if task_key == "ingestion.news.collect":
            agent = self._attach_run(
                NewsAgent(self.competitor_id, self.competitor_name, self.domain)
            )

            def retry_news_collection() -> Dict[str, Any]:
                articles = self._run_async(agent.collect())
                persisted = self._run_async(agent.save_articles(articles))
                return {"collected": len(articles or []), "persisted": persisted}

            return retry_news_collection

        if task_key == "ingestion.news.persist":
            agent = self._attach_run(
                NewsAgent(self.competitor_id, self.competitor_name, self.domain)
            )
            articles = self._load_collected_news(source_run_id)
            return lambda: self._run_async(agent.save_articles(articles))

        if task_key == "ingestion.jobs":
            agent = self._attach_run(
                JobScraperAgent(self.competitor_id, self.competitor_name, self.domain)
            )
            return lambda: self._run_async(agent.collect())

        if task_key == "ingestion.external_sources":
            agent = self._attach_run(
                ExternalSourceAgent(self.competitor_id, self.competitor_name, self.domain)
            )
            return lambda: self._run_async(agent.collect())

        if task_key == "ingestion.evidence_index":
            return lambda: EvidenceRetriever(self.competitor_id).prepare()

        if task_key == "enrichment.social_feeds":
            agent = self._attach_run(
                SocialWatcherAgent(
                    self.competitor_id,
                    self.competitor_name,
                    self.domain,
                    self.rss_feeds,
                )
            )
            return lambda: self._run_async(agent.collect())

        if task_key == "enrichment.tech_stack":
            agent = self._attach_run(
                TechStackAgent(self.competitor_id, self.competitor_name, self.domain)
            )
            return lambda: self._run_async(agent.collect())

        if task_key == "analysis.summary":
            agent = SummariserAgent(
                self.competitor_id,
                self.competitor_name,
                self.model,
                self.run_id,
                self.focus_topics,
            )
            return agent.collect

        if task_key == "analysis.entity_resolution":
            agent = EntityResolverAgent(
                self.competitor_id,
                self.competitor_name,
                self.model,
                self.run_id,
            )
            return agent.collect

        if task_key == "analysis.relationship_fusion":
            return lambda: RelationshipIntelligenceEngine(
                self.competitor_id,
                self.run_id,
            ).analyze()

        if task_key == "analysis.signals":
            agent = SignalDetectorAgent(
                self.competitor_id,
                self.competitor_name,
                self.model,
                self.run_id,
                self.focus_topics,
            )
            return agent.collect

        if task_key == "analysis.predictions":
            agent = PredictorAgent(
                self.competitor_id,
                self.competitor_name,
                self.model,
                self.run_id,
                self.focus_topics,
            )
            return agent.collect

        if task_key == "analysis.claim_verification":
            return lambda: ClaimVerificationEngine(self.competitor_id).verify_all()

        if task_key == "analysis.event_fusion":
            return lambda: EventFusionEngine(self.competitor_id).rebuild()

        raise ValueError(f"Task '{task_key}' cannot be retried independently")

    def retry_task(
        self,
        task_key: str,
        *,
        source_run_id: int | None = None,
    ) -> Any:
        """Execute one registered task without replaying the surrounding stages."""
        definition = self.RETRYABLE_TASKS.get(task_key)
        if definition is None:
            raise ValueError(f"Task '{task_key}' cannot be retried independently")
        operation = self._retry_operation(task_key, source_run_id)
        return self._execute_task(
            task_key=task_key,
            stage=definition["stage"],
            agent_name=definition["agent_name"],
            operation=operation,
            max_attempts=definition["max_attempts"],
        )

    def _record_source_health(
        self,
        *,
        adapter_name: str,
        source_key: str,
        started: float,
        success: bool,
        items: int = 0,
        error: Exception | str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.run_id is None:
            return
        try:
            SourceHealthStore.record(
                self.competitor_id,
                adapter_name=adapter_name,
                source_key=source_key,
                success=success,
                items=items,
                latency_ms=int((time.perf_counter() - started) * 1000),
                error=str(error) if error else None,
                metadata=metadata,
            )
        except Exception as exc:
            logger.warning("Could not persist source health for %s: %s", adapter_name, exc)

    def _register_discovered_feeds(self, feed_urls: List[str]) -> None:
        feeds = list(dict.fromkeys(feed for feed in feed_urls if feed))
        if not feeds:
            return
        self.rss_feeds = list(dict.fromkeys([*self.rss_feeds, *feeds]))
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.executemany(
                        """
                        INSERT INTO competitor_rss_feeds (competitor_id, feed_url)
                        VALUES (%s, %s)
                        ON CONFLICT (competitor_id, feed_url) DO NOTHING
                        """,
                        [(self.competitor_id, feed) for feed in feeds],
                    )
                    cur.executemany(
                        """
                        INSERT INTO sources (
                            competitor_id, url, source_type, priority,
                            monitoring_status, metadata
                        )
                        VALUES (%s, %s, 'rss', 75, 'active', '{}'::jsonb)
                        ON CONFLICT DO NOTHING
                        """,
                        [(self.competitor_id, feed) for feed in feeds],
                    )
                    conn.commit()
        except Exception as exc:
            logger.warning("Could not register discovered RSS feeds: %s", exc)

    def _finish_cancelled(
        self,
        summary: Dict[str, Any],
        started_at: float,
    ) -> Dict[str, Any]:
        summary["cancelled"] = True
        summary["success"] = False
        summary["end_time"] = time.time()
        summary["duration_seconds"] = summary["end_time"] - started_at
        self.run_tracker.finish_run("cancelled", summary=summary)
        self._report_progress("cancelled", "cancelled", summary)
        logger.info("[%s] Pipeline cancelled", self.competitor_name)
        return summary

    def run_ingestion(self) -> Dict[str, Any]:
        """Run hybrid web, news, and multi-source job ingestion agents."""
        logger.info(f"[{self.competitor_name}] Running ingestion agents...")
        results = {
            "web_pages": 0,
            "web_pages_scanned": 0,
            "website_changes": 0,
            "news_articles": 0,
            "job_postings": 0,
            "job_postings_fetched": 0,
            "job_postings_matched": 0,
            "external_documents": 0,
            "external_stats": {},
            "crawl_stats": {},
            "job_stats": {},
            "foundation": {},
            "errors": [],
        }

        # Run web scraper
        try:
            source_started = time.perf_counter()
            web_agent = self._attach_run(WebScraperAgent(
                self.competitor_id,
                self.competitor_name,
                self.domain
            ))
            web_results = self._execute_task(
                task_key="ingestion.web_crawler",
                stage="ingestion",
                agent_name="WebScraperAgent",
                operation=lambda: self._run_async(web_agent.collect()),
            )
            results["web_pages_scanned"] = len(web_results or [])
            results["web_pages"] = sum(
                1 for page in (web_results or []) if page.get("persisted", True)
            )
            results["website_changes"] = sum(
                1 for page in (web_results or []) if page.get("change_detected")
            )
            results["crawl_stats"] = web_agent.last_run_stats
            self._register_discovered_feeds(sorted(web_agent.discovered_feeds))
            self._record_source_health(
                adapter_name="web_crawler",
                source_key=self.domain,
                started=source_started,
                success=True,
                items=len(web_results or []),
                metadata=web_agent.last_run_stats,
            )
            logger.info(f"[{self.competitor_name}] Web scraper: {results['web_pages']} pages")
        except Exception as e:
            if "web_agent" in locals():
                web_agent.finish_campaign_with_error(e)
            self._record_source_health(
                adapter_name="web_crawler",
                source_key=self.domain,
                started=locals().get("source_started", time.perf_counter()),
                success=False,
                error=e,
            )
            logger.error(f"[{self.competitor_name}] Web scraper failed: {e}")
            results["errors"].append(f"web_scraper: {e}")

        # Run news agent
        try:
            source_started = time.perf_counter()
            news_agent = self._attach_run(NewsAgent(
                self.competitor_id,
                self.competitor_name,
                self.domain
            ))
            news_results = self._execute_task(
                task_key="ingestion.news.collect",
                stage="ingestion",
                agent_name="NewsAgent",
                operation=lambda: self._run_async(news_agent.collect()),
            )
            results["news_articles"] = self._execute_task(
                task_key="ingestion.news.persist",
                stage="ingestion",
                agent_name="NewsAgent",
                operation=lambda: self._run_async(news_agent.save_articles(news_results)),
            )
            self._record_source_health(
                adapter_name="newsapi",
                source_key=self.competitor_name,
                started=source_started,
                success=True,
                items=results["news_articles"],
            )
            logger.info(f"[{self.competitor_name}] News agent: {results['news_articles']} new articles")
        except Exception as e:
            self._record_source_health(
                adapter_name="newsapi",
                source_key=self.competitor_name,
                started=locals().get("source_started", time.perf_counter()),
                success=False,
                error=e,
            )
            logger.error(f"[{self.competitor_name}] News agent failed: {e}")
            results["errors"].append(f"news_agent: {e}")

        # Run job sources independently so their failures do not stop web/news.
        if settings.enable_job_scraper:
            try:
                source_started = time.perf_counter()
                job_agent = self._attach_run(JobScraperAgent(
                    self.competitor_id,
                    self.competitor_name,
                    self.domain,
                ))
                job_results = self._execute_task(
                    task_key="ingestion.jobs",
                    stage="ingestion",
                    agent_name="JobScraperAgent",
                    operation=lambda: self._run_async(job_agent.collect()),
                )
                results["job_postings"] = len(job_results or [])
                results["job_stats"] = job_agent.last_run_stats
                source_stats = job_agent.last_run_stats.get("sources", {})
                results["job_postings_fetched"] = sum(
                    int(source.get("fetched", 0)) for source in source_stats.values()
                )
                results["job_postings_matched"] = sum(
                    int(source.get("matched", 0)) for source in source_stats.values()
                )
                self._record_source_health(
                    adapter_name="job_intelligence",
                    source_key=",".join(job_agent.sources),
                    started=source_started,
                    success=not any(
                        source.get("error") for source in source_stats.values()
                    ),
                    items=len(job_results or []),
                    metadata=job_agent.last_run_stats,
                )
                logger.info(
                    f"[{self.competitor_name}] Job scraper: "
                    f"{results['job_postings']} new postings"
                )
            except Exception as e:
                self._record_source_health(
                    adapter_name="job_intelligence",
                    source_key="configured_sources",
                    started=locals().get("source_started", time.perf_counter()),
                    success=False,
                    error=e,
                )
                logger.error(f"[{self.competitor_name}] Job scraper failed: {e}")
                results["errors"].append(f"job_scraper: {e}")

        if settings.enable_external_sources:
            try:
                source_started = time.perf_counter()
                external_agent = self._attach_run(
                    ExternalSourceAgent(
                        self.competitor_id,
                        self.competitor_name,
                        self.domain,
                    )
                )
                external_results = self._execute_task(
                    task_key="ingestion.external_sources",
                    stage="ingestion",
                    agent_name="ExternalSourceAgent",
                    operation=lambda: self._run_async(external_agent.collect()),
                )
                results["external_documents"] = len(external_results or [])
                results["external_stats"] = external_agent.last_run_stats
                external_errors = sum(
                    len(value.get("errors", []))
                    for key, value in external_agent.last_run_stats.items()
                    if key in {"youtube", "github"} and isinstance(value, dict)
                )
                self._record_source_health(
                    adapter_name="external_sources",
                    source_key="youtube,github",
                    started=source_started,
                    success=external_errors == 0,
                    items=len(external_results or []),
                    metadata=external_agent.last_run_stats,
                )
            except Exception as e:
                self._record_source_health(
                    adapter_name="external_sources",
                    source_key="youtube,github",
                    started=locals().get("source_started", time.perf_counter()),
                    success=False,
                    error=e,
                )
                logger.error("[%s] External source collection failed: %s", self.competitor_name, e)
                results["errors"].append(f"external_sources: {e}")

        try:
            results["foundation"] = self._execute_task(
                task_key="ingestion.evidence_index",
                stage="ingestion",
                agent_name="EvidenceRetriever",
                operation=lambda: EvidenceRetriever(self.competitor_id).prepare(),
                max_attempts=1,
            )
        except Exception as e:
            logger.warning("[%s] Evidence indexing deferred: %s", self.competitor_name, e)
            results["foundation"] = {"semantic": False, "error": str(e)}
            results["errors"].append(f"evidence_index: {e}")

        return results

    def run_enrichment(self) -> Dict[str, Any]:
        """Run enrichment agents (social watcher + tech stack)."""
        logger.info(f"[{self.competitor_name}] Running enrichment agents...")
        results = {"social_posts": 0, "tech_stack": 0, "errors": []}

        # Run social watcher
        try:
            source_started = time.perf_counter()
            social_agent = self._attach_run(SocialWatcherAgent(
                self.competitor_id,
                self.competitor_name,
                self.domain,
                self.rss_feeds
            ))
            social_results = self._execute_task(
                task_key="enrichment.social_feeds",
                stage="enrichment",
                agent_name="SocialWatcherAgent",
                operation=lambda: self._run_async(social_agent.collect()),
            )
            results["social_posts"] = len(social_results) if social_results else 0
            self._record_source_health(
                adapter_name="social_feeds",
                source_key=",".join(self.rss_feeds) or self.domain,
                started=source_started,
                success=True,
                items=results["social_posts"],
            )
            logger.info(f"[{self.competitor_name}] Social watcher: {results['social_posts']} posts")
        except Exception as e:
            self._record_source_health(
                adapter_name="social_feeds",
                source_key=",".join(self.rss_feeds) or self.domain,
                started=locals().get("source_started", time.perf_counter()),
                success=False,
                error=e,
            )
            logger.error(f"[{self.competitor_name}] Social watcher failed: {e}")
            results["errors"].append(f"social_watcher: {e}")

        # Run tech stack
        try:
            source_started = time.perf_counter()
            tech_agent = self._attach_run(TechStackAgent(
                self.competitor_id,
                self.competitor_name,
                self.domain
            ))
            tech_result = self._execute_task(
                task_key="enrichment.tech_stack",
                stage="enrichment",
                agent_name="TechStackAgent",
                operation=lambda: self._run_async(tech_agent.collect()),
            )
            results["tech_stack"] = len(tech_result.get("technologies", [])) if tech_result else 0
            if tech_result and tech_result.get("error"):
                results["errors"].append(f"tech_stack: {tech_result['error']}")
            self._record_source_health(
                adapter_name="tech_stack",
                source_key=self.domain,
                started=source_started,
                success=not bool(tech_result and tech_result.get("error")),
                items=results["tech_stack"],
                metadata=tech_result or {},
            )
            logger.info(f"[{self.competitor_name}] Tech stack: detected {results['tech_stack']}")
        except Exception as e:
            self._record_source_health(
                adapter_name="tech_stack",
                source_key=self.domain,
                started=locals().get("source_started", time.perf_counter()),
                success=False,
                error=e,
            )
            logger.error(f"[{self.competitor_name}] Tech stack failed: {e}")
            results["errors"].append(f"tech_stack: {e}")

        return results

    def run_analysis(self) -> Dict[str, Any]:
        """Run analysis agents with 15s sleep between each for rate limits."""
        logger.info(f"[{self.competitor_name}] Running analysis agents...")
        results = {
            "summary_generated": False,
            "entities_resolved": 0,
            "relationships_built": 0,
            "relationship_evidence_links": 0,
            "relationship_intelligence": {},
            "signals_detected": 0,
            "predictions_made": 0,
            "errors": [],
        }

        # Run summariser
        try:
            summariser = SummariserAgent(
                self.competitor_id,
                self.competitor_name,
                self.model,
                self.run_id,
                self.focus_topics,
            )
            summary = self._execute_task(
                task_key="analysis.summary",
                stage="analysis",
                agent_name="SummariserAgent",
                operation=summariser.collect,
            )
            results["summary_generated"] = bool(summary)
            logger.info(f"[{self.competitor_name}] Summariser: {'success' if results['summary_generated'] else 'no data'}")
        except Exception as e:
            logger.error(f"[{self.competitor_name}] Summariser failed: {e}")
            results["errors"].append(f"summariser: {e}")

        self._wait_for_analysis_rate_limit()

        # Resolve profile entities and graph relationships
        try:
            resolver = EntityResolverAgent(
                self.competitor_id,
                self.competitor_name,
                self.model,
                self.run_id,
            )
            resolution = self._execute_task(
                task_key="analysis.entity_resolution",
                stage="analysis",
                agent_name="EntityResolverAgent",
                operation=resolver.collect,
            )
            results["entities_resolved"] = resolution["entities_resolved"]
            results["relationships_built"] = resolution["relationships_built"]
            results["relationship_evidence_links"] = resolution.get("evidence_links", 0)
            logger.info(
                f"[{self.competitor_name}] Entity resolver: "
                f"{results['entities_resolved']} entities, "
                f"{results['relationships_built']} relationships"
            )
        except Exception as e:
            logger.error(f"[{self.competitor_name}] Entity resolver failed: {e}")
            results["errors"].append(f"entity_resolver: {e}")

        try:
            fusion = self._execute_task(
                task_key="analysis.relationship_fusion",
                stage="analysis",
                agent_name="RelationshipIntelligenceEngine",
                operation=lambda: RelationshipIntelligenceEngine(
                    self.competitor_id,
                    self.run_id,
                ).analyze(),
                max_attempts=1,
            )
            results["relationship_intelligence"] = fusion
        except Exception as e:
            logger.error("[%s] Relationship fusion failed: %s", self.competitor_name, e)
            results["errors"].append(f"relationship_fusion: {e}")

        self._wait_for_analysis_rate_limit()

        # Run signal detector
        try:
            signal_detector = SignalDetectorAgent(
                self.competitor_id,
                self.competitor_name,
                self.model,
                self.run_id,
                self.focus_topics,
            )
            signals = self._execute_task(
                task_key="analysis.signals",
                stage="analysis",
                agent_name="SignalDetectorAgent",
                operation=signal_detector.collect,
            )
            results["signals_detected"] = len(signals) if signals else 0
            logger.info(f"[{self.competitor_name}] Signal detector: {results['signals_detected']} signals")
        except Exception as e:
            logger.error(f"[{self.competitor_name}] Signal detector failed: {e}")
            results["errors"].append(f"signal_detector: {e}")

        self._wait_for_analysis_rate_limit()

        # Run predictor
        try:
            predictor = PredictorAgent(
                self.competitor_id,
                self.competitor_name,
                self.model,
                self.run_id,
                self.focus_topics,
            )
            predictions = self._execute_task(
                task_key="analysis.predictions",
                stage="analysis",
                agent_name="PredictorAgent",
                operation=predictor.collect,
            )
            results["predictions_made"] = len(predictions) if predictions else 0
            logger.info(f"[{self.competitor_name}] Predictor: {results['predictions_made']} predictions")
        except Exception as e:
            logger.error(f"[{self.competitor_name}] Predictor failed: {e}")
            results["errors"].append(f"predictor: {e}")

        try:
            verification = self._execute_task(
                task_key="analysis.claim_verification",
                stage="analysis",
                agent_name="ClaimVerificationEngine",
                operation=lambda: ClaimVerificationEngine(
                    self.competitor_id
                ).verify_all(),
            )
            results["verification"] = verification
        except Exception as e:
            logger.error("[%s] Claim verification failed: %s", self.competitor_name, e)
            results["errors"].append(f"claim_verification: {e}")

        try:
            event_fusion = self._execute_task(
                task_key="analysis.event_fusion",
                stage="analysis",
                agent_name="EventFusionEngine",
                operation=lambda: EventFusionEngine(
                    self.competitor_id
                ).rebuild(),
                max_attempts=1,
            )
            results["event_fusion"] = event_fusion
        except Exception as e:
            logger.error("[%s] Event fusion failed: %s", self.competitor_name, e)
            results["errors"].append(f"event_fusion: {e}")

        return results

    def run_full_pipeline(self) -> Dict[str, Any]:
        """Run the complete pipeline: ingestion -> enrichment -> analysis."""
        start_time = time.time()
        logger.info(f"[{self.competitor_name}] Starting full pipeline...")

        summary = {
            "run_id": self.run_id,
            "competitor_id": self.competitor_id,
            "competitor_name": self.competitor_name,
            "start_time": start_time,
            "ingestion": {},
            "enrichment": {},
            "analysis": {},
            "success": False
        }

        try:
            self.run_tracker.start_run()
            # Stage 1: Ingestion
            logger.info(f"[{self.competitor_name}] Stage 1: Ingestion")
            self._report_progress("ingestion", "running")
            summary["ingestion"] = self.run_ingestion()
            status = "failed" if summary["ingestion"].get("errors") else "completed"
            self._report_progress("ingestion", status, summary["ingestion"])
        except Exception as e:
            logger.error(f"[{self.competitor_name}] Ingestion stage failed: {e}")
            summary["ingestion"] = {"errors": [str(e)]}
            self._report_progress("ingestion", "failed", summary["ingestion"])

        if self.run_tracker.is_cancel_requested():
            return self._finish_cancelled(summary, start_time)

        try:
            self.run_tracker.check_cancelled()
            # Stage 2: Enrichment
            logger.info(f"[{self.competitor_name}] Stage 2: Enrichment")
            self._report_progress("enrichment", "running")
            summary["enrichment"] = self.run_enrichment()
            status = "failed" if summary["enrichment"].get("errors") else "completed"
            self._report_progress("enrichment", status, summary["enrichment"])
        except Exception as e:
            logger.error(f"[{self.competitor_name}] Enrichment stage failed: {e}")
            summary["enrichment"] = {"errors": [str(e)]}
            self._report_progress("enrichment", "failed", summary["enrichment"])

        if self.run_tracker.is_cancel_requested():
            return self._finish_cancelled(summary, start_time)

        try:
            self.run_tracker.check_cancelled()
            # Stage 3: Analysis
            logger.info(f"[{self.competitor_name}] Stage 3: Analysis")
            self._report_progress("analysis", "running")
            summary["analysis"] = self.run_analysis()
            status = "failed" if summary["analysis"].get("errors") else "completed"
            self._report_progress("analysis", status, summary["analysis"])
        except Exception as e:
            logger.error(f"[{self.competitor_name}] Analysis stage failed: {e}")
            summary["analysis"] = {"errors": [str(e)]}
            self._report_progress("analysis", "failed", summary["analysis"])

        end_time = time.time()
        duration = end_time - start_time
        summary["end_time"] = end_time
        summary["duration_seconds"] = duration
        summary["success"] = not any(
            stage.get("errors")
            for stage in (summary["ingestion"], summary["enrichment"], summary["analysis"])
        )

        final_status = "completed" if summary["success"] else "partial"
        self.run_tracker.finish_run(final_status, summary=summary)

        logger.info(
            f"[{self.competitor_name}] Pipeline completed in {duration:.1f}s | "
            f"Web: {summary['ingestion'].get('web_pages', 0)} | "
            f"News: {summary['ingestion'].get('news_articles', 0)} | "
            f"Jobs: {summary['ingestion'].get('job_postings', 0)} | "
            f"Signals: {summary['analysis'].get('signals_detected', 0)} | "
            f"Predictions: {summary['analysis'].get('predictions_made', 0)}"
        )

        return summary

    def run_quick_check(self) -> Dict[str, Any]:
        """Run quick check: ingestion + enrichment only (no LLM analysis)."""
        start_time = time.time()
        logger.info(f"[{self.competitor_name}] Starting quick check (ingestion + enrichment only)...")

        summary = {
            "competitor_id": self.competitor_id,
            "competitor_name": self.competitor_name,
            "start_time": start_time,
            "ingestion": {},
            "enrichment": {},
            "success": False
        }

        try:
            summary["ingestion"] = self.run_ingestion()
        except Exception as e:
            logger.error(f"[{self.competitor_name}] Quick check ingestion failed: {e}")
            summary["ingestion"] = {"errors": [str(e)]}

        try:
            summary["enrichment"] = self.run_enrichment()
        except Exception as e:
            logger.error(f"[{self.competitor_name}] Quick check enrichment failed: {e}")
            summary["enrichment"] = {"errors": [str(e)]}

        end_time = time.time()
        summary["end_time"] = end_time
        summary["duration_seconds"] = end_time - start_time
        summary["success"] = not any(
            stage.get("errors")
            for stage in (summary["ingestion"], summary["enrichment"])
        )

        logger.info(
            f"[{self.competitor_name}] Quick check completed in {summary['duration_seconds']:.1f}s | "
            f"Web: {summary['ingestion'].get('web_pages', 0)} | "
            f"News: {summary['ingestion'].get('news_articles', 0)} | "
            f"Jobs: {summary['ingestion'].get('job_postings', 0)}"
        )

        return summary
