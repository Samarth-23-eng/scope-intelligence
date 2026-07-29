CREATE TABLE IF NOT EXISTS agent_quality_events (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    pipeline_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    agent_name VARCHAR(120) NOT NULL,
    model VARCHAR(255) NOT NULL,
    status VARCHAR(30) NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 1 CHECK (attempts >= 1),
    parse_valid BOOLEAN NOT NULL DEFAULT FALSE,
    schema_valid BOOLEAN NOT NULL DEFAULT FALSE,
    repaired BOOLEAN NOT NULL DEFAULT FALSE,
    grounded_items INTEGER NOT NULL DEFAULT 0 CHECK (grounded_items >= 0),
    rejected_items INTEGER NOT NULL DEFAULT 0 CHECK (rejected_items >= 0),
    latency_ms INTEGER NOT NULL DEFAULT 0 CHECK (latency_ms >= 0),
    validation_errors JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'agent_quality_events_status_check'
    ) THEN
        ALTER TABLE agent_quality_events
            ADD CONSTRAINT agent_quality_events_status_check
            CHECK (status IN ('valid', 'repaired', 'rejected', 'empty', 'error'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_agent_quality_events_run
    ON agent_quality_events(pipeline_run_id, agent_name, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_quality_events_competitor
    ON agent_quality_events(competitor_id, created_at DESC);
