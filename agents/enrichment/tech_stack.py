import json
import logging
from typing import List, Dict, Any, Optional

import builtwith

from agents.enrichment.base import BaseEnrichmentAgent
from config.settings import settings

logger = logging.getLogger(__name__)


class TechStackAgent(BaseEnrichmentAgent):
    """Tech stack fingerprinter using builtwith."""

    def __init__(self, competitor_id: int, competitor_name: str, domain: str):
        super().__init__(competitor_id, competitor_name, domain)
        self.target_url = f"https://{domain}" if not domain.startswith("http") else domain

    async def collect(self) -> Dict[str, Any]:
        """Run builtwith and extract technologies."""
        if not self.domain:
            return {
                "technologies": [],
                "raw": {},
                "skipped": True,
                "skip_reason": "No verified website",
            }
        logger.info(f"TechStackAgent: Running builtwith on {self.target_url}")

        try:
            # Run builtwith.parse - it's synchronous, so run in thread pool
            import asyncio
            loop = asyncio.get_event_loop()
            technologies = await loop.run_in_executor(
                None,
                lambda: builtwith.parse(self.target_url)
            )

            if not technologies:
                logger.warning("builtwith returned empty result")
                return {"technologies": [], "raw": {}}

            # Normalize technologies into list of dicts
            tech_list = []
            for tech_name, tech_info in technologies.items():
                tech_list.append({
                    "name": tech_name,
                    "version": tech_info.get("version", "") if isinstance(tech_info, dict) else "",
                    "categories": tech_info.get("categories", []) if isinstance(tech_info, dict) else [],
                    "confidence": tech_info.get("confidence", 0) if isinstance(tech_info, dict) else 0
                })

            # Save raw JSON to raw_data table
            raw_json = json.dumps(technologies, default=str)
            content_hash = self._hash_content(raw_json)
            self.save_raw_data(
                source=f"tech_stack:{self.target_url}",
                content=raw_json,
                content_hash=content_hash,
                metadata={"url": self.target_url}
            )

            # Save as signal
            tech_names = [t["name"] for t in tech_list]
            desc = f"Detected technologies: {', '.join(tech_names[:10])}"
            if len(tech_names) > 10:
                desc += f" and {len(tech_names) - 10} more"
            self.save_signal(
                signal_type="tech_stack",
                description=desc,
                severity="low"
            )

            logger.info(f"TechStackAgent: Found {len(tech_list)} technologies")

            return {
                "technologies": tech_list,
                "raw": technologies
            }

        except Exception as e:
            logger.error(f"TechStackAgent failed: {e}")
            return {"technologies": [], "raw": {}, "error": str(e)}
