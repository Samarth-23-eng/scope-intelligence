CREATE TABLE IF NOT EXISTS monitoring_profiles (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL UNIQUE
        REFERENCES competitors(id) ON DELETE CASCADE,
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    cadence_minutes INTEGER NOT NULL DEFAULT 1440,
    focus_topics JSONB NOT NULL DEFAULT '[]'::jsonb,
    alert_severities JSONB NOT NULL DEFAULT '["high", "critical"]'::jsonb,
    last_scheduled_at TIMESTAMPTZ,
    next_run_at TIMESTAMPTZ,
    last_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    last_status VARCHAR(30) NOT NULL DEFAULT 'idle',
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (cadence_minutes BETWEEN 15 AND 10080),
    CHECK (last_status IN (
        'idle', 'queued', 'running', 'completed', 'partial',
        'failed', 'cancelled', 'skipped'
    ))
);

CREATE INDEX IF NOT EXISTS idx_monitoring_profiles_due
    ON monitoring_profiles(enabled, next_run_at)
    WHERE enabled = TRUE;

CREATE TABLE IF NOT EXISTS monitoring_activity (
    id BIGSERIAL PRIMARY KEY,
    monitoring_profile_id BIGINT NOT NULL
        REFERENCES monitoring_profiles(id) ON DELETE CASCADE,
    competitor_id INTEGER NOT NULL
        REFERENCES competitors(id) ON DELETE CASCADE,
    pipeline_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    event_type VARCHAR(40) NOT NULL,
    status VARCHAR(30) NOT NULL,
    message TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_monitoring_activity_competitor
    ON monitoring_activity(competitor_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_monitoring_activity_profile
    ON monitoring_activity(monitoring_profile_id, created_at DESC);
