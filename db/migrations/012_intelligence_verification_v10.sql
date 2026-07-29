CREATE TABLE IF NOT EXISTS source_reliability_profiles (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    source_domain VARCHAR(500) NOT NULL,
    source_type VARCHAR(100) NOT NULL DEFAULT 'unknown',
    reliability DOUBLE PRECISION NOT NULL DEFAULT 0.55
        CHECK (reliability >= 0 AND reliability <= 1),
    tier VARCHAR(30) NOT NULL DEFAULT 'contextual'
        CHECK (tier IN ('primary', 'reliable', 'contextual', 'low')),
    basis TEXT NOT NULL,
    is_override BOOLEAN NOT NULL DEFAULT FALSE,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    last_seen_at TIMESTAMPTZ,
    assessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, source_domain, source_type)
);

CREATE INDEX IF NOT EXISTS idx_source_reliability_competitor
    ON source_reliability_profiles(competitor_id, reliability DESC);

CREATE TABLE IF NOT EXISTS claim_verifications (
    id BIGSERIAL PRIMARY KEY,
    claim_id BIGINT NOT NULL UNIQUE REFERENCES claims(id) ON DELETE CASCADE,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    support_count INTEGER NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    independent_sources INTEGER NOT NULL DEFAULT 0,
    corroboration_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    contradiction_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    freshness_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    source_quality DOUBLE PRECISION NOT NULL DEFAULT 0,
    final_confidence DOUBLE PRECISION NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL,
    risk_flags JSONB NOT NULL DEFAULT '[]'::jsonb,
    rationale TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    assessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('proposed', 'supported', 'confirmed', 'disputed', 'stale')),
    CHECK (final_confidence >= 0 AND final_confidence <= 1)
);

CREATE INDEX IF NOT EXISTS idx_claim_verifications_queue
    ON claim_verifications(competitor_id, status, final_confidence, assessed_at DESC);

CREATE TABLE IF NOT EXISTS claim_reviews (
    id BIGSERIAL PRIMARY KEY,
    claim_id BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    decision VARCHAR(20) NOT NULL
        CHECK (decision IN ('supported', 'confirmed', 'disputed', 'stale')),
    previous_status VARCHAR(20) NOT NULL,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_claim_reviews_competitor
    ON claim_reviews(competitor_id, created_at DESC);

DROP TRIGGER IF EXISTS set_source_reliability_updated_at
    ON source_reliability_profiles;
CREATE TRIGGER set_source_reliability_updated_at
    BEFORE UPDATE ON source_reliability_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
