import hashlib
import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta

import httpx

from agents.ingestion.base import BaseIngestionAgent
from config.settings import settings

logger = logging.getLogger(__name__)


class NewsAgent(BaseIngestionAgent):
    """Fetches news articles about a competitor using NewsAPI."""

    BASE_URL = "https://newsapi.org/v2/everything"

    def __init__(self, competitor_id: int, competitor_name: str, domain: str):
        super().__init__(competitor_id, competitor_name, domain)
        self.api_key = settings.newsapi_key

    async def collect(self) -> List[Dict[str, Any]]:
        """Fetch news articles from the last 30 days."""
        if not self.api_key or self.api_key == "your_key_here":
            logger.warning("NEWSAPI_KEY not configured, skipping news collection")
            return []

        results = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                params = {
                    "q": self.competitor_name,
                    "language": "en",
                    "sortBy": "publishedAt",
                    "from": (datetime.utcnow() - timedelta(days=30)).strftime("%Y-%m-%d"),
                    "pageSize": 50,
                    "apiKey": self.api_key
                }

                response = await client.get(self.BASE_URL, params=params)
                response.raise_for_status()
                data = response.json()

                if data.get("status") != "ok":
                    logger.error(f"NewsAPI error: {data.get('message', 'Unknown error')}")
                    return []

                articles = data.get("articles", [])

                for article in articles:
                    try:
                        processed = self._process_article(article)
                        if processed:
                            results.append(processed)
                    except Exception as e:
                        logger.warning(f"Failed to process article: {e}")
                        continue

            except httpx.HTTPStatusError as e:
                logger.error(f"NewsAPI HTTP error: {e.response.status_code} - {e.response.text}")
            except Exception as e:
                logger.error(f"NewsAgent collection failed: {e}")

        logger.info(f"NewsAgent: collected {len(results)} articles for {self.competitor_name}")
        return results

    def _process_article(self, article: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Process a single article into our format."""
        url = article.get("url")
        if not url:
            return None

        title = article.get("title") or ""
        description = article.get("description") or ""
        source_name = article.get("source", {}).get("name") or "unknown"
        published_at = article.get("publishedAt") or datetime.utcnow().isoformat()

        content_for_hash = f"{url}{title}"
        content_hash = hashlib.md5(content_for_hash.encode()).hexdigest()

        return {
            "title": title,
            "description": description,
            "url": url,
            "source": source_name,
            "published_at": published_at,
            "content_hash": content_hash,
            "raw_content": f"{title}. {description}"
        }

    async def save_articles(self, articles: List[Dict[str, Any]]) -> int:
        """Save articles to database with deduplication."""
        saved = 0
        for article in articles:
            content_hash = article["content_hash"]
            source = f"news:{article['url']}"
            has_changed = await self.has_changed(source, article["raw_content"])
            if has_changed:
                inserted = self.save_raw_data(
                    source=source,
                    content=article["raw_content"],
                    content_hash=content_hash,
                    metadata={
                        "url": article["url"],
                        "title": article["title"],
                        "source": article["source"],
                        "published_at": article["published_at"]
                    }
                )
                if inserted:
                    self.save_evidence(
                        source_url=article["url"],
                        title=article["title"],
                        content=article["raw_content"],
                        content_hash=content_hash,
                        confidence=0.75,
                        metadata={
                            "kind": "news_article",
                            "publisher": article["source"],
                            "published_at": article["published_at"],
                        },
                    )
                    await self.mark_seen(source, article["raw_content"])
                    saved += 1
        return saved
