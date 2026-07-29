ALTER TABLE competitors
    ALTER COLUMN domain DROP NOT NULL;

ALTER TABLE competitors
    DROP CONSTRAINT IF EXISTS competitors_domain_key;

ALTER TABLE competitors
    ADD COLUMN IF NOT EXISTS domain_verified BOOLEAN NOT NULL DEFAULT FALSE,
    ADD COLUMN IF NOT EXISTS identity_context JSONB NOT NULL DEFAULT '{}'::jsonb;

UPDATE competitors
SET domain_verified = TRUE
WHERE domain IS NOT NULL
  AND discovery_status IN ('manual', 'discovered', 'enriched');

DROP INDEX IF EXISTS idx_competitors_domain;
CREATE INDEX IF NOT EXISTS idx_competitors_domain
    ON competitors(domain)
    WHERE domain IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_competitors_name_lower
    ON competitors(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_competitors_identity_context_gin
    ON competitors USING GIN(identity_context);
