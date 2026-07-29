import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import RealDictCursor

from config.settings import settings

logger = logging.getLogger(__name__)

_pool: Optional[ThreadedConnectionPool] = None
MIGRATIONS_DIR = Path(__file__).with_name("migrations")


def get_pool() -> ThreadedConnectionPool:
    global _pool
    if _pool is None:
        try:
            _pool = ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                dsn=settings.postgres_url,
                cursor_factory=RealDictCursor
            )
            logger.info("PostgreSQL connection pool created successfully")
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL connection pool: {e}")
            raise
    return _pool


@contextmanager
def get_connection():
    """Synchronous context manager for database connections."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


def get_migration_files() -> list[Path]:
    """Return numbered SQL migrations in deterministic order."""
    return sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def run_migrations() -> bool:
    """Apply each pending SQL migration exactly once."""
    pool = get_pool()
    conn = pool.getconn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(255) PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
            conn.commit()

        for migration_path in get_migration_files():
            version = migration_path.name
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM schema_migrations WHERE version = %s", (version,))
                if cur.fetchone():
                    continue

                sql = migration_path.read_text(encoding="utf-8")
                cur.execute(sql)
                cur.execute(
                    "INSERT INTO schema_migrations (version) VALUES (%s)",
                    (version,),
                )
                conn.commit()
                logger.info(f"Applied database migration {version}")

        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Failed to run migrations: {e}")
        return False
    finally:
        pool.putconn(conn)


def close_pool() -> None:
    global _pool
    if _pool:
        _pool.closeall()
        _pool = None
        logger.info("PostgreSQL connection pool closed")
