ALTER TABLE raw_data ALTER COLUMN source TYPE VARCHAR(512);
ALTER TABLE raw_data ALTER COLUMN hash TYPE VARCHAR(512);

ALTER TABLE competitors ADD COLUMN IF NOT EXISTS website VARCHAR(512);
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS description TEXT;
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS hq VARCHAR(255);
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS founded SMALLINT;
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS executives JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS subsidiaries JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS key_products JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS technologies JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS social_media JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS careers_url VARCHAR(2048);
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS blog_url VARCHAR(2048);
ALTER TABLE competitors ADD COLUMN IF NOT EXISTS discovery_status VARCHAR(30) NOT NULL DEFAULT 'manual';

UPDATE competitors SET website = 'https://' || domain WHERE website IS NULL;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'competitors_founded_check') THEN
        ALTER TABLE competitors
            ADD CONSTRAINT competitors_founded_check
            CHECK (founded IS NULL OR founded BETWEEN 1000 AND 9999);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'competitors_discovery_status_check') THEN
        ALTER TABLE competitors
            ADD CONSTRAINT competitors_discovery_status_check
            CHECK (discovery_status IN ('manual', 'discovered', 'enriched', 'failed'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_competitors_discovery_status ON competitors(discovery_status);
CREATE INDEX IF NOT EXISTS idx_competitors_executives_gin ON competitors USING GIN(executives);
CREATE INDEX IF NOT EXISTS idx_competitors_technologies_gin ON competitors USING GIN(technologies);

CREATE TABLE IF NOT EXISTS entities (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    name VARCHAR(500) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, name, entity_type)
);

CREATE INDEX IF NOT EXISTS idx_entities_competitor_id ON entities(competitor_id);
CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type);
CREATE INDEX IF NOT EXISTS idx_entities_name_lower ON entities(LOWER(name));
CREATE INDEX IF NOT EXISTS idx_entities_metadata_gin ON entities USING GIN(metadata);

CREATE TABLE IF NOT EXISTS relationships (
    id BIGSERIAL PRIMARY KEY,
    source_entity_id BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    target_entity_id BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    relationship_type VARCHAR(100) NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 1.0 CHECK (weight >= 0 AND weight <= 1),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (source_entity_id <> target_entity_id),
    UNIQUE (source_entity_id, target_entity_id, relationship_type)
);

CREATE INDEX IF NOT EXISTS idx_relationships_source ON relationships(source_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_target ON relationships(target_entity_id);
CREATE INDEX IF NOT EXISTS idx_relationships_type ON relationships(relationship_type);
CREATE INDEX IF NOT EXISTS idx_relationships_metadata_gin ON relationships USING GIN(metadata);

CREATE TABLE IF NOT EXISTS evidence (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    source_url VARCHAR(2048) NOT NULL,
    title VARCHAR(1000),
    snippet TEXT,
    full_text TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5 CHECK (confidence >= 0 AND confidence <= 1),
    hash VARCHAR(512) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    collected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, hash)
);

CREATE INDEX IF NOT EXISTS idx_evidence_competitor_id ON evidence(competitor_id);
CREATE INDEX IF NOT EXISTS idx_evidence_collected_at ON evidence(collected_at DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_confidence ON evidence(confidence DESC);
CREATE INDEX IF NOT EXISTS idx_evidence_metadata_gin ON evidence USING GIN(metadata);
CREATE INDEX IF NOT EXISTS idx_evidence_full_text_search ON evidence
    USING GIN(to_tsvector('english', COALESCE(title, '') || ' ' || COALESCE(snippet, '') || ' ' || COALESCE(full_text, '')));

CREATE TABLE IF NOT EXISTS sources (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    url VARCHAR(2048) NOT NULL,
    source_type VARCHAR(100) NOT NULL,
    priority SMALLINT NOT NULL DEFAULT 50 CHECK (priority BETWEEN 1 AND 100),
    monitoring_status VARCHAR(30) NOT NULL DEFAULT 'active'
        CHECK (monitoring_status IN ('active', 'paused', 'error', 'discovered')),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_sources_competitor_url_unique
    ON sources(competitor_id, MD5(url));
CREATE INDEX IF NOT EXISTS idx_sources_competitor_id ON sources(competitor_id);
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(source_type);
CREATE INDEX IF NOT EXISTS idx_sources_monitoring_status ON sources(monitoring_status);
CREATE INDEX IF NOT EXISTS idx_sources_priority ON sources(priority DESC);
CREATE INDEX IF NOT EXISTS idx_sources_metadata_gin ON sources USING GIN(metadata);

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS set_competitors_updated_at ON competitors;
CREATE TRIGGER set_competitors_updated_at
    BEFORE UPDATE ON competitors
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_entities_updated_at ON entities;
CREATE TRIGGER set_entities_updated_at
    BEFORE UPDATE ON entities
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_sources_updated_at ON sources;
CREATE TRIGGER set_sources_updated_at
    BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
