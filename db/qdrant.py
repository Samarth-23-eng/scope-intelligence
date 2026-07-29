import logging
from typing import Optional

from qdrant_client import QdrantClient
from qdrant_client.http import models

from config.settings import settings

logger = logging.getLogger(__name__)

_client: Optional[QdrantClient] = None

COLLECTION_CONTENT = "competitor_content"
COLLECTION_SIGNALS = "competitor_signals"
COLLECTION_EVIDENCE_CHUNKS = "evidence_chunks_v3"
VECTOR_SIZE = 1536
DISTANCE = models.Distance.COSINE


def get_client() -> QdrantClient:
    global _client
    if _client is None:
        try:
            _client = QdrantClient(url=settings.qdrant_url)
            logger.info("Qdrant client connected successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Qdrant: {e}")
            raise
    return _client


async def create_collections() -> bool:
    client = get_client()
    try:
        collections = client.get_collections().collections
        existing_names = {c.name for c in collections}

        if COLLECTION_CONTENT not in existing_names:
            client.create_collection(
                collection_name=COLLECTION_CONTENT,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=DISTANCE
                )
            )
            logger.info(f"Created collection: {COLLECTION_CONTENT}")

        if COLLECTION_SIGNALS not in existing_names:
            client.create_collection(
                collection_name=COLLECTION_SIGNALS,
                vectors_config=models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=DISTANCE
                )
            )
            logger.info(f"Created collection: {COLLECTION_SIGNALS}")

        return True
    except Exception as e:
        logger.error(f"Failed to create Qdrant collections: {e}")
        return False


async def close_client() -> None:
    global _client
    if _client:
        _client.close()
        _client = None
        logger.info("Qdrant client closed")
