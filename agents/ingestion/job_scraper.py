import asyncio
import hashlib
import json
import logging
import math
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Dict, List
from urllib.parse import urlparse

from agents.ingestion.base import BaseIngestionAgent
from config.settings import settings

logger = logging.getLogger(__name__)


class JobScraperAgent(BaseIngestionAgent):
    """
    Multi-source job-intelligence collector backed by JobSpy.

    Each source runs independently so a LinkedIn block cannot prevent Indeed or
    Google Jobs data from being collected. LinkedIn remains an explicit feature
    flag and this collector does not automate accounts, solve CAPTCHAs, or evade
    access controls.
    """

    def __init__(self, competitor_id: int, competitor_name: str, domain: str):
        super().__init__(competitor_id, competitor_name, domain)
        sources = settings.job_source_list
        if not settings.enable_linkedin_scraper:
            sources = [source for source in sources if source != "linkedin"]
        self.sources = list(dict.fromkeys(sources))
        self.max_jobs = max(settings.job_results_wanted, 1)
        self.location = settings.job_search_location.strip()
        self.last_run_stats: Dict[str, Any] = {}

    async def collect(self) -> List[Dict[str, Any]]:
        if not settings.enable_job_scraper or not self.sources:
            self.last_run_stats = {"enabled": False, "sources": {}, "persisted": 0}
            return []

        if "linkedin" in self.sources:
            logger.warning(
                "Experimental LinkedIn jobs collection is enabled. "
                "It may be blocked and must remain limited to authorized local testing."
            )

        all_results: List[Dict[str, Any]] = []
        source_stats: Dict[str, Dict[str, Any]] = {}
        for source in self.sources:
            stats = {"fetched": 0, "matched": 0, "persisted": 0, "error": None}
            source_stats[source] = stats
            try:
                rows = await asyncio.to_thread(self._scrape_source, source)
                stats["fetched"] = len(rows)
                for row in rows:
                    normalized = self._normalize_job(row, source)
                    if not normalized or not self._matches_competitor(normalized):
                        continue
                    stats["matched"] += 1
                    saved = await self._persist_job(normalized)
                    if saved:
                        stats["persisted"] += 1
                        all_results.append(saved)
            except Exception as exc:
                stats["error"] = str(exc)[:500]
                logger.warning("Job source %s failed for %s: %s", source, self.competitor_name, exc)

        self.last_run_stats = {
            "enabled": True,
            "experimental_linkedin": "linkedin" in self.sources,
            "sources": source_stats,
            "persisted": len(all_results),
        }
        logger.info(
            "JobScraper collected %s new jobs for %s (%s)",
            len(all_results),
            self.competitor_name,
            source_stats,
        )
        return all_results

    def _scrape_source(self, source: str) -> List[Dict[str, Any]]:
        """Run one JobSpy source synchronously inside a worker thread."""
        from jobspy import scrape_jobs

        kwargs: Dict[str, Any] = {
            "site_name": [source],
            "search_term": f'"{self.competitor_name}"',
            "results_wanted": self.max_jobs,
            "hours_old": max(settings.job_hours_old, 1),
            "verbose": 1,
        }
        if self.location:
            kwargs["location"] = self.location
        if source == "google":
            location = f" in {self.location}" if self.location else ""
            kwargs["google_search_term"] = (
                f'"{self.competitor_name}" jobs{location} posted in the last month'
            )
        if source in {"indeed", "glassdoor"}:
            country = self._country_from_location(self.location)
            if country:
                kwargs["country_indeed"] = country
        if source == "linkedin":
            kwargs["linkedin_fetch_description"] = True

        frame = scrape_jobs(**kwargs)
        if frame is None or getattr(frame, "empty", False):
            return []
        return frame.to_dict(orient="records")

    async def _persist_job(self, job: Dict[str, Any]) -> Dict[str, Any] | None:
        url = str(job.get("job_url") or job.get("job_url_direct") or "").strip()
        if not url:
            return None
        source_name = str(job.get("source") or "unknown").lower()
        content = json.dumps(job, sort_keys=True, ensure_ascii=False)
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        source = f"job:{source_name}:{url}"
        if not await self.has_changed(source, content):
            return None

        metadata = {
            **job,
            "kind": "job_posting",
            "collector": "jobspy",
            "experimental": source_name == "linkedin",
        }
        if not self.save_raw_data(
            source=source,
            content=content,
            content_hash=content_hash,
            metadata=metadata,
        ):
            return None

        evidence_id = self.save_evidence(
            source_url=url,
            title=str(job.get("title") or "Job posting"),
            content=content,
            content_hash=content_hash,
            confidence=0.72 if source_name == "linkedin" else 0.8,
            metadata={
                "source_type": "job_board",
                "kind": "job_posting",
                "job_source": source_name,
                "company": job.get("company"),
                "location": job.get("location"),
                "date_posted": job.get("date_posted"),
                "collector": "jobspy",
                "experimental": source_name == "linkedin",
            },
        )
        await self.mark_seen(source, content)
        result = {
            key: value
            for key, value in job.items()
            if key != "description"
        }
        return {
            **result,
            "url": url,
            "description_chars": len(str(job.get("description") or "")),
            "evidence_id": evidence_id,
            "persisted": True,
            "scraped_at": datetime.now(timezone.utc).isoformat(),
        }

    def _normalize_job(self, row: Dict[str, Any], source: str) -> Dict[str, Any] | None:
        cleaned = {key: self._json_safe(value) for key, value in row.items()}
        title = str(cleaned.get("title") or "").strip()
        company = str(cleaned.get("company") or "").strip()
        job_url = str(
            cleaned.get("job_url_direct") or cleaned.get("job_url") or ""
        ).strip()
        if not title or not company or not job_url:
            return None

        return {
            "source": source,
            "title": title,
            "company": company,
            "location": str(cleaned.get("location") or "").strip(),
            "date_posted": cleaned.get("date_posted"),
            "job_type": cleaned.get("job_type"),
            "job_level": cleaned.get("job_level"),
            "job_function": cleaned.get("job_function"),
            "is_remote": cleaned.get("is_remote"),
            "description": str(cleaned.get("description") or ""),
            "job_url": job_url,
            "job_url_direct": str(cleaned.get("job_url_direct") or "").strip(),
            "company_url": str(cleaned.get("company_url") or "").strip(),
            "company_industry": cleaned.get("company_industry"),
            "min_amount": cleaned.get("min_amount"),
            "max_amount": cleaned.get("max_amount"),
            "currency": cleaned.get("currency"),
            "interval": cleaned.get("interval"),
        }

    def _matches_competitor(self, job: Dict[str, Any]) -> bool:
        expected = self._identity_tokens(self.competitor_name)
        actual = self._identity_tokens(str(job.get("company") or ""))
        if expected and actual and expected.intersection(actual):
            return True

        company_url = str(job.get("company_url") or "")
        hostname = (urlparse(company_url).hostname or "").lower().removeprefix("www.")
        domain = self.domain.lower().removeprefix("www.")
        return bool(hostname and (hostname == domain or hostname.endswith(f".{domain}")))

    @staticmethod
    def _identity_tokens(value: str) -> set[str]:
        ignored = {
            "aerospace",
            "company",
            "corporation",
            "corp",
            "inc",
            "india",
            "limited",
            "ltd",
            "llc",
            "private",
            "pvt",
            "technologies",
            "technology",
        }
        tokens = set(re.findall(r"[a-z0-9]+", value.casefold()))
        return {token for token in tokens if len(token) > 2 and token not in ignored}

    @staticmethod
    def _country_from_location(location: str) -> str:
        if not location:
            return ""
        return location.rsplit(",", 1)[-1].strip()

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, Enum):
            return cls._json_safe(value.value)
        if isinstance(value, (datetime, date)):
            return value.isoformat()
        if isinstance(value, float) and math.isnan(value):
            return None
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        if hasattr(value, "item"):
            try:
                return cls._json_safe(value.item())
            except (TypeError, ValueError):
                pass
        if isinstance(value, (str, int, float, bool)):
            return value
        return str(value)
