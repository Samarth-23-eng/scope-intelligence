from __future__ import annotations

from agents.ingestion.social.base import SocialConnector, SocialConnectorError
from agents.ingestion.social.youtube import YouTubeSocialConnector
from config.settings import settings


class SocialConnectorRegistry:
    """Explicit connector allowlist. User input never controls imports."""

    @staticmethod
    def create(platform: str) -> SocialConnector:
        normalized = (platform or "").strip().casefold()
        if normalized == "youtube":
            return YouTubeSocialConnector(
                api_key=settings.youtube_api_key,
                request_timeout=max(settings.crawler_request_timeout_seconds, 10.0),
                request_delay=max(settings.social_request_delay_seconds, 0.0),
            )
        raise SocialConnectorError(
            "unsupported_platform",
            f"{platform or 'Unknown platform'} is not available in this build.",
            recoverable=False,
            suggested_action="Choose one of the connectors marked ready.",
        )

    @classmethod
    def descriptors(cls):
        return [cls.create("youtube").descriptor]
