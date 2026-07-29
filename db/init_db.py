#!/usr/bin/env python3
"""
Database initialization script.
Run with: python db/init_db.py
"""

import asyncio
import sys
import logging

from db.postgres import run_migrations, close_pool
from db.qdrant import create_collections, close_client as close_qdrant
from db.redis_client import get_client as get_redis_client, close_client as close_redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def check_postgres() -> bool:
    try:
        result = run_migrations()
        if result:
            logger.info("[OK] PostgreSQL: Migrations applied successfully")
        else:
            logger.error("[FAILED] PostgreSQL: Migration failed")
        return result
    except Exception as e:
        logger.error(f"[FAILED] PostgreSQL: {e}")
        return False


async def check_qdrant() -> bool:
    try:
        result = await create_collections()
        if result:
            logger.info("[OK] Qdrant: Collections created/verified successfully")
        else:
            logger.error("[FAILED] Qdrant: Collection creation failed")
        return result
    except Exception as e:
        logger.error(f"[FAILED] Qdrant: {e}")
        return False


async def check_redis() -> bool:
    try:
        client = get_redis_client()
        client.ping()
        logger.info("[OK] Redis: Connection successful")
        return True
    except Exception as e:
        logger.error(f"[FAILED] Redis: {e}")
        return False


async def main() -> int:
    logger.info("=" * 50)
    logger.info("Scope Intelligence - Database Initialization")
    logger.info("=" * 50)

    results = {}

    logger.info("\n[1/3] Checking PostgreSQL...")
    results["postgres"] = check_postgres()

    logger.info("\n[2/3] Checking Qdrant...")
    results["qdrant"] = await check_qdrant()

    logger.info("\n[3/3] Checking Redis...")
    results["redis"] = await check_redis()

    logger.info("\n" + "=" * 50)
    logger.info("INITIALIZATION SUMMARY")
    logger.info("=" * 50)

    all_ok = True
    for service, ok in results.items():
        status = "OK" if ok else "FAILED"
        logger.info(f"  {service.upper():12} : {status}")
        if not ok:
            all_ok = False

    logger.info("=" * 50)

    close_pool()
    await close_qdrant()
    await close_redis()

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
