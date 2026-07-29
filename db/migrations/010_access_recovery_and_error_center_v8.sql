ALTER TABLE competitors
    ADD COLUMN IF NOT EXISTS access_recovery_enabled BOOLEAN NOT NULL DEFAULT FALSE;

CREATE TABLE IF NOT EXISTS collection_errors (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    pipeline_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    campaign_id BIGINT REFERENCES collection_campaigns(id) ON DELETE SET NULL,
    url VARCHAR(4096),
    url_hash VARCHAR(64),
    error_code VARCHAR(100) NOT NULL,
    category VARCHAR(80) NOT NULL,
    http_status INTEGER,
    severity VARCHAR(20) NOT NULL DEFAULT 'warning',
    engine VARCHAR(80),
    attempts JSONB NOT NULL DEFAULT '[]'::jsonb,
    technical_message TEXT NOT NULL,
    user_message TEXT NOT NULL,
    suggested_action TEXT,
    recoverable BOOLEAN NOT NULL DEFAULT TRUE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    fingerprint VARCHAR(64) NOT NULL,
    occurrences INTEGER NOT NULL DEFAULT 1,
    first_occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'collection_errors_severity_check'
    ) THEN
        ALTER TABLE collection_errors
            ADD CONSTRAINT collection_errors_severity_check
            CHECK (severity IN ('info', 'warning', 'error', 'critical'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_collection_errors_active_fingerprint
    ON collection_errors(competitor_id, fingerprint)
    WHERE resolved_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_collection_errors_competitor
    ON collection_errors(competitor_id, resolved_at, last_occurred_at DESC);
CREATE INDEX IF NOT EXISTS idx_collection_errors_run
    ON collection_errors(pipeline_run_id, last_occurred_at DESC)
    WHERE pipeline_run_id IS NOT NULL;
