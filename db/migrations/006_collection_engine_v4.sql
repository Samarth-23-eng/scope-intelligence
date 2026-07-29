CREATE TABLE IF NOT EXISTS collection_campaigns (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    pipeline_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    campaign_type VARCHAR(60) NOT NULL DEFAULT 'web',
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    strategy VARCHAR(100) NOT NULL DEFAULT 'adaptive_priority',
    budget JSONB NOT NULL DEFAULT '{}'::jsonb,
    statistics JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'collection_campaigns_status_check'
    ) THEN
        ALTER TABLE collection_campaigns
            ADD CONSTRAINT collection_campaigns_status_check
            CHECK (status IN (
                'queued', 'running', 'completed', 'partial', 'failed', 'cancelled'
            ));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_collection_campaigns_run_type
    ON collection_campaigns(pipeline_run_id, campaign_type)
    WHERE pipeline_run_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_collection_campaigns_competitor
    ON collection_campaigns(competitor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS crawl_frontier (
    id BIGSERIAL PRIMARY KEY,
    campaign_id BIGINT NOT NULL
        REFERENCES collection_campaigns(id) ON DELETE CASCADE,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    url VARCHAR(4096) NOT NULL,
    url_hash VARCHAR(64) NOT NULL,
    source_type VARCHAR(80) NOT NULL DEFAULT 'web',
    depth INTEGER NOT NULL DEFAULT 0,
    priority INTEGER NOT NULL DEFAULT 0,
    discovered_from VARCHAR(4096),
    state VARCHAR(20) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    last_http_status INTEGER,
    content_hash VARCHAR(64),
    last_error TEXT,
    next_retry_at TIMESTAMPTZ,
    claimed_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (campaign_id, url_hash)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'crawl_frontier_state_check'
    ) THEN
        ALTER TABLE crawl_frontier
            ADD CONSTRAINT crawl_frontier_state_check
            CHECK (state IN (
                'queued', 'fetching', 'completed', 'unchanged',
                'failed', 'blocked', 'skipped'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_crawl_frontier_ready
    ON crawl_frontier(campaign_id, state, priority DESC, id)
    WHERE state IN ('queued', 'fetching', 'failed');
CREATE INDEX IF NOT EXISTS idx_crawl_frontier_competitor
    ON crawl_frontier(competitor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS source_profiles (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    source_type VARCHAR(80) NOT NULL,
    profile_url VARCHAR(4096) NOT NULL,
    profile_key VARCHAR(500),
    profile_hash VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'discovered',
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0 AND confidence <= 1),
    discovered_from VARCHAR(4096),
    last_collected_at TIMESTAMPTZ,
    verified_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, source_type, profile_hash)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'source_profiles_status_check'
    ) THEN
        ALTER TABLE source_profiles
            ADD CONSTRAINT source_profiles_status_check
            CHECK (status IN ('discovered', 'verified', 'active', 'error', 'disabled'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_source_profiles_competitor
    ON source_profiles(competitor_id, source_type, status);

CREATE TABLE IF NOT EXISTS collection_events (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    campaign_id BIGINT REFERENCES collection_campaigns(id) ON DELETE CASCADE,
    frontier_id BIGINT REFERENCES crawl_frontier(id) ON DELETE SET NULL,
    pipeline_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    adapter_name VARCHAR(120) NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    success BOOLEAN NOT NULL DEFAULT TRUE,
    items INTEGER NOT NULL DEFAULT 0,
    bytes_collected BIGINT NOT NULL DEFAULT 0,
    latency_ms INTEGER,
    error TEXT,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_collection_events_campaign
    ON collection_events(campaign_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_collection_events_competitor
    ON collection_events(competitor_id, adapter_name, created_at DESC);

DROP TRIGGER IF EXISTS set_collection_campaigns_updated_at ON collection_campaigns;
CREATE TRIGGER set_collection_campaigns_updated_at
    BEFORE UPDATE ON collection_campaigns
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_crawl_frontier_updated_at ON crawl_frontier;
CREATE TRIGGER set_crawl_frontier_updated_at
    BEFORE UPDATE ON crawl_frontier
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_source_profiles_updated_at ON source_profiles;
CREATE TRIGGER set_source_profiles_updated_at
    BEFORE UPDATE ON source_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
