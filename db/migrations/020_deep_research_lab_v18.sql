CREATE TABLE IF NOT EXISTS deep_research_runs (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    query TEXT NOT NULL,
    status VARCHAR(30) NOT NULL DEFAULT 'queued'
        CHECK (status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled')),
    options JSONB NOT NULL DEFAULT '{}'::jsonb,
    checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    cancel_requested_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_deep_research_one_active_run
    ON deep_research_runs(competitor_id)
    WHERE status IN ('queued', 'running');
CREATE INDEX IF NOT EXISTS idx_deep_research_runs_competitor
    ON deep_research_runs(competitor_id, created_at DESC);

CREATE TABLE IF NOT EXISTS deep_research_results (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES deep_research_runs(id) ON DELETE CASCADE,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    engine VARCHAR(120) NOT NULL,
    source_url VARCHAR(4096) NOT NULL,
    title VARCHAR(2000),
    excerpt TEXT,
    content_hash VARCHAR(128),
    fetch_status VARCHAR(30) NOT NULL DEFAULT 'discovered'
        CHECK (fetch_status IN ('discovered', 'collected', 'skipped', 'failed')),
    http_status INTEGER,
    evidence_id BIGINT REFERENCES evidence(id) ON DELETE SET NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    collected_at TIMESTAMPTZ,
    UNIQUE (run_id, source_url)
);

CREATE INDEX IF NOT EXISTS idx_deep_research_results_competitor
    ON deep_research_results(competitor_id, discovered_at DESC);
CREATE INDEX IF NOT EXISTS idx_deep_research_results_run
    ON deep_research_results(run_id, fetch_status);

DROP TRIGGER IF EXISTS set_deep_research_runs_updated_at ON deep_research_runs;
CREATE TRIGGER set_deep_research_runs_updated_at
    BEFORE UPDATE ON deep_research_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

COMMENT ON TABLE deep_research_runs IS
    'Opt-in, bounded research runs over publicly reachable Tor hidden services.';
COMMENT ON COLUMN deep_research_results.metadata IS
    'Provenance and diagnostics only; authentication material must never be stored.';
