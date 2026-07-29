CREATE TABLE IF NOT EXISTS intelligence_events (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    event_key VARCHAR(64) NOT NULL,
    event_type VARCHAR(100) NOT NULL,
    title VARCHAR(1000) NOT NULL,
    summary TEXT NOT NULL,
    impact_level VARCHAR(20) NOT NULL DEFAULT 'medium'
        CHECK (impact_level IN ('low', 'medium', 'high', 'critical')),
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0 AND confidence <= 1),
    verification_status VARCHAR(20) NOT NULL DEFAULT 'supported'
        CHECK (verification_status IN (
            'proposed', 'supported', 'confirmed', 'disputed', 'stale'
        )),
    status VARCHAR(20) NOT NULL DEFAULT 'active'
        CHECK (status IN ('active', 'developing', 'disputed', 'stale')),
    source_count INTEGER NOT NULL DEFAULT 0,
    occurred_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, event_key)
);

CREATE INDEX IF NOT EXISTS idx_intelligence_events_timeline
    ON intelligence_events(competitor_id, occurred_at DESC, impact_level);
CREATE INDEX IF NOT EXISTS idx_intelligence_events_status
    ON intelligence_events(competitor_id, status, verification_status);
CREATE INDEX IF NOT EXISTS idx_intelligence_events_metadata
    ON intelligence_events USING GIN(metadata);

CREATE TABLE IF NOT EXISTS intelligence_event_links (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL REFERENCES intelligence_events(id) ON DELETE CASCADE,
    claim_id BIGINT REFERENCES claims(id) ON DELETE CASCADE,
    page_change_id BIGINT REFERENCES page_changes(id) ON DELETE CASCADE,
    signal_id BIGINT REFERENCES signals(id) ON DELETE CASCADE,
    evidence_id BIGINT REFERENCES evidence(id) ON DELETE SET NULL,
    link_type VARCHAR(30) NOT NULL,
    contribution DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (contribution >= 0 AND contribution <= 1),
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (
        claim_id IS NOT NULL OR page_change_id IS NOT NULL
        OR signal_id IS NOT NULL OR evidence_id IS NOT NULL
    )
);

CREATE INDEX IF NOT EXISTS idx_intelligence_event_links_event
    ON intelligence_event_links(event_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_intelligence_event_link_claim
    ON intelligence_event_links(event_id, claim_id)
    WHERE claim_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_intelligence_event_link_change
    ON intelligence_event_links(event_id, page_change_id)
    WHERE page_change_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_intelligence_event_link_signal
    ON intelligence_event_links(event_id, signal_id)
    WHERE signal_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS intelligence_event_correlations (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    source_event_id BIGINT NOT NULL
        REFERENCES intelligence_events(id) ON DELETE CASCADE,
    target_event_id BIGINT NOT NULL
        REFERENCES intelligence_events(id) ON DELETE CASCADE,
    correlation_type VARCHAR(40) NOT NULL DEFAULT 'shared_theme',
    score DOUBLE PRECISION NOT NULL
        CHECK (score >= 0 AND score <= 1),
    rationale TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (source_event_id < target_event_id),
    UNIQUE (source_event_id, target_event_id, correlation_type)
);

CREATE INDEX IF NOT EXISTS idx_event_correlations_competitor
    ON intelligence_event_correlations(competitor_id, score DESC);

DROP TRIGGER IF EXISTS set_intelligence_events_updated_at
    ON intelligence_events;
CREATE TRIGGER set_intelligence_events_updated_at
    BEFORE UPDATE ON intelligence_events
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
