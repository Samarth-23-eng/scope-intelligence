#!/usr/bin/env python3
"""Idempotently add demo competitors without deleting existing data."""

from db.postgres import close_pool, get_connection, run_migrations


DEMO_COMPETITORS = (
    ("HubSpot", "www.hubspot.com", "CRM software"),
    ("Freshworks", "www.freshworks.com", "Business software"),
    ("Zoho", "www.zoho.com", "Business software"),
)


def seed_demo() -> int:
    if not run_migrations():
        raise RuntimeError("Database migrations failed")

    inserted = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for name, domain, industry in DEMO_COMPETITORS:
                cur.execute(
                    """
                    INSERT INTO competitors (
                        name, domain, industry, website, discovery_status
                    )
                    VALUES (%s, %s, %s, %s, 'manual')
                    ON CONFLICT (domain) DO NOTHING
                    RETURNING id
                    """,
                    (name, domain, industry, f"https://{domain}"),
                )
                if cur.fetchone():
                    inserted += 1
            conn.commit()
    return inserted


if __name__ == "__main__":
    try:
        count = seed_demo()
        print(f"Added {count} demo competitors")
    finally:
        close_pool()
