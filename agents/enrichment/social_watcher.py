import asyncio
import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import List, Dict, Any, Optional
from datetime import datetime

import httpx

from agents.enrichment.base import BaseEnrichmentAgent
from config.settings import settings

logger = logging.getLogger(__name__)


class SocialWatcherAgent(BaseEnrichmentAgent):
    """Social media post watcher via RSS feeds."""

    def __init__(
        self,
        competitor_id: int,
        competitor_name: str,
        domain: str,
        rss_feeds: List[str]
    ):
        super().__init__(competitor_id, competitor_name, domain)
        self.rss_feeds = rss_feeds

    async def collect(self) -> List[Dict[str, Any]]:
        """Fetch and parse RSS feeds, detect new posts."""
        new_items = []

        async with httpx.AsyncClient(timeout=30.0) as client:
            for feed_url in self.rss_feeds:
                try:
                    items = await self._process_feed(client, feed_url)
                    new_items.extend(items)
                except Exception as e:
                    logger.warning(f"Failed to process feed {feed_url}: {e}")
                    continue

        logger.info(f"SocialWatcherAgent: Found {len(new_items)} new posts across {len(self.rss_feeds)} feeds")
        return new_items

    async def _process_feed(self, client: httpx.AsyncClient, feed_url: str) -> List[Dict[str, Any]]:
        """Fetch and parse a single RSS feed."""
        new_items = []

        try:
            response = await client.get(feed_url, follow_redirects=True)
            response.raise_for_status()
            content = response.text

            # Parse XML
            root = ET.fromstring(content)

            # Handle both RSS 2.0 and Atom formats
            items = self._extract_items(root)

            for item in items:
                link = item.get("link", "")
                if not link:
                    continue

                # Hash by link for deduplication
                content_hash = hashlib.md5(link.encode()).hexdigest()

                diff_key = f"rss:{feed_url}:{link}"
                has_changed = await self.has_changed(diff_key, link)
                if not has_changed:
                    continue

                # Save raw RSS item to raw_data
                raw_content = f"{item.get('title', '')}. {item.get('summary', '')}"
                saved = self.save_raw_data(
                    source=f"rss:{feed_url}",
                    content=raw_content,
                    content_hash=content_hash,
                    metadata={
                        "feed_url": feed_url,
                        "item_url": link,
                        "title": item.get("title", ""),
                        "published": item.get("published", "")
                    }
                )
                if not saved:
                    continue

                await self.mark_seen(diff_key, link)

                # Save as signal
                title = item.get("title", "Untitled")
                desc = f"New post detected: {title} ({feed_url})"
                self.save_signal(
                    signal_type="new_content",
                    description=desc,
                    severity="medium"
                )

                new_items.append({
                    "title": title,
                    "link": link,
                    "published": item.get("published", ""),
                    "summary": item.get("summary", ""),
                    "feed_url": feed_url,
                    "detected_at": datetime.utcnow().isoformat()
                })

        except ET.ParseError as e:
            logger.error(f"Failed to parse XML from {feed_url}: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching {feed_url}: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error processing feed {feed_url}: {e}")

        return new_items

    def _extract_items(self, root: ET.Element) -> List[Dict[str, str]]:
        """Extract items from RSS 2.0 or Atom feed."""
        items = []

        # Try RSS 2.0 format
        for item in root.findall(".//item"):
            items.append({
                "title": self._get_text(item, "title"),
                "link": self._get_text(item, "link"),
                "published": self._get_text(item, "pubDate") or self._get_text(item, "pubdate"),
                "summary": self._get_text(item, "description")
            })

        # Try Atom format
        if not items:
            for entry in root.findall(".//{http://www.w3.org/2005/Atom}entry"):
                link = ""
                for link_elem in entry.findall("{http://www.w3.org/2005/Atom}link"):
                    href = link_elem.get("href")
                    if href and link_elem.get("rel") in (None, "alternate"):
                        link = href
                        break

                items.append({
                    "title": self._get_text(entry, "{http://www.w3.org/2005/Atom}title"),
                    "link": link,
                    "published": self._get_text(entry, "{http://www.w3.org/2005/Atom}published") or
                                self._get_text(entry, "{http://www.w3.org/2005/Atom}updated"),
                    "summary": self._get_text(entry, "{http://www.w3.org/2005/Atom}summary") or
                              self._get_text(entry, "{http://www.w3.org/2005/Atom}content")
                })

        return items

    def _get_text(self, element: ET.Element, tag: str) -> str:
        """Safely get text from an XML element."""
        child = element.find(tag)
        return child.text.strip() if child is not None and child.text else ""
