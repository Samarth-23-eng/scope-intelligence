ALTER TABLE entities
    ADD COLUMN IF NOT EXISTS canonical_key VARCHAR(500);

UPDATE entities
SET canonical_key = LOWER(REGEXP_REPLACE(name, '[^a-zA-Z0-9]+', '', 'g'))
WHERE canonical_key IS NULL;

CREATE INDEX IF NOT EXISTS idx_entities_canonical_key
    ON entities(competitor_id, canonical_key);

ALTER TABLE relationships
    ADD COLUMN IF NOT EXISTS corroboration_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS source_diversity INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS freshness_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS contradiction_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS risk_level VARCHAR(20) NOT NULL DEFAULT 'unassessed';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationships_corroboration_score_check'
    ) THEN
        ALTER TABLE relationships
            ADD CONSTRAINT relationships_corroboration_score_check
            CHECK (corroboration_score >= 0 AND corroboration_score <= 1);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationships_source_diversity_check'
    ) THEN
        ALTER TABLE relationships
            ADD CONSTRAINT relationships_source_diversity_check
            CHECK (source_diversity >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationships_freshness_score_check'
    ) THEN
        ALTER TABLE relationships
            ADD CONSTRAINT relationships_freshness_score_check
            CHECK (freshness_score >= 0 AND freshness_score <= 1);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationships_contradiction_count_check'
    ) THEN
        ALTER TABLE relationships
            ADD CONSTRAINT relationships_contradiction_count_check
            CHECK (contradiction_count >= 0);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationships_risk_level_check'
    ) THEN
        ALTER TABLE relationships
            ADD CONSTRAINT relationships_risk_level_check
            CHECK (risk_level IN ('unassessed', 'low', 'medium', 'high', 'critical'));
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS entity_aliases (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    entity_id BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    alias VARCHAR(500) NOT NULL,
    normalized_alias VARCHAR(500) NOT NULL,
    alias_type VARCHAR(40) NOT NULL DEFAULT 'normalized',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.8
        CHECK (confidence >= 0 AND confidence <= 1),
    source VARCHAR(100) NOT NULL DEFAULT 'relationship_fusion',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, entity_id, normalized_alias)
);

CREATE INDEX IF NOT EXISTS idx_entity_aliases_lookup
    ON entity_aliases(competitor_id, normalized_alias);

CREATE TABLE IF NOT EXISTS relationship_observations (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    relationship_id BIGINT NOT NULL REFERENCES relationships(id) ON DELETE CASCADE,
    evidence_id BIGINT REFERENCES evidence(id) ON DELETE CASCADE,
    stance VARCHAR(20) NOT NULL DEFAULT 'supports',
    source_type VARCHAR(100) NOT NULL DEFAULT 'unknown',
    source_key VARCHAR(500) NOT NULL DEFAULT 'unknown',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0 AND confidence <= 1),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationship_observations_stance_check'
    ) THEN
        ALTER TABLE relationship_observations
            ADD CONSTRAINT relationship_observations_stance_check
            CHECK (stance IN ('supports', 'contradicts', 'context'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_relationship_observations_unique
    ON relationship_observations(
        relationship_id,
        COALESCE(evidence_id, 0),
        stance,
        source_key
    );
CREATE INDEX IF NOT EXISTS idx_relationship_observations_relationship
    ON relationship_observations(relationship_id, observed_at DESC);
CREATE INDEX IF NOT EXISTS idx_relationship_observations_competitor
    ON relationship_observations(competitor_id, stance, observed_at DESC);

CREATE TABLE IF NOT EXISTS graph_snapshots (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    pipeline_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    entity_count INTEGER NOT NULL DEFAULT 0,
    relationship_count INTEGER NOT NULL DEFAULT 0,
    component_count INTEGER NOT NULL DEFAULT 0,
    disputed_relationships INTEGER NOT NULL DEFAULT 0,
    weak_relationships INTEGER NOT NULL DEFAULT 0,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_snapshots_competitor
    ON graph_snapshots(competitor_id, created_at DESC);
