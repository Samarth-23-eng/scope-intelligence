import logging
from typing import Optional

import redis
from redis import Redis

from config.settings import settings

logger = logging.getLogger(__name__)

_client: Optional[Redis] = None


def get_client() -> Redis:
    global _client
    if _client is None:
        try:
            _client = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True
            )
            logger.info("Redis client connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            raise
    return _client


async def get_last_seen(competitor_id: int, source: str) -> Optional[str]:
    client = get_client()
    key = f"last_seen:{competitor_id}:{source}"
    try:
        return client.get(key)
    except Exception as e:
        logger.error(f"Failed to get last_seen for {key}: {e}")
        return None


async def set_last_seen(competitor_id: int, source: str, content_hash: str) -> bool:
    client = get_client()
    key = f"last_seen:{competitor_id}:{source}"
    try:
        client.set(key, content_hash)
        return True
    except Exception as e:
        logger.error(f"Failed to set last_seen for {key}: {e}")
        return False


async def close_client() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("Redis client closed")
