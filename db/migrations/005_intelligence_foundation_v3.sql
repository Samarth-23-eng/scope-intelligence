CREATE TABLE IF NOT EXISTS pipeline_runs (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    parent_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    run_type VARCHAR(40) NOT NULL DEFAULT 'full',
    trigger_type VARCHAR(40) NOT NULL DEFAULT 'manual',
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    model VARCHAR(255),
    configuration JSONB NOT NULL DEFAULT '{}'::jsonb,
    summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    cancel_requested_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pipeline_runs_status_check'
    ) THEN
        ALTER TABLE pipeline_runs
            ADD CONSTRAINT pipeline_runs_status_check
            CHECK (status IN (
                'queued', 'running', 'completed', 'partial', 'failed', 'cancelled'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_pipeline_runs_competitor
    ON pipeline_runs(competitor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_pipeline_runs_status
    ON pipeline_runs(status, created_at DESC);

CREATE TABLE IF NOT EXISTS pipeline_tasks (
    id BIGSERIAL PRIMARY KEY,
    run_id BIGINT NOT NULL REFERENCES pipeline_runs(id) ON DELETE CASCADE,
    task_key VARCHAR(160) NOT NULL,
    stage VARCHAR(60) NOT NULL,
    agent_name VARCHAR(120) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    attempt INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    input JSONB NOT NULL DEFAULT '{}'::jsonb,
    output JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    heartbeat_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (run_id, task_key)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pipeline_tasks_status_check'
    ) THEN
        ALTER TABLE pipeline_tasks
            ADD CONSTRAINT pipeline_tasks_status_check
            CHECK (status IN (
                'pending', 'running', 'retrying', 'completed',
                'failed', 'skipped', 'cancelled'
            ));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pipeline_tasks_attempt_check'
    ) THEN
        ALTER TABLE pipeline_tasks
            ADD CONSTRAINT pipeline_tasks_attempt_check
            CHECK (attempt >= 0 AND max_attempts >= 1);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_pipeline_tasks_run
    ON pipeline_tasks(run_id, stage, created_at);
CREATE INDEX IF NOT EXISTS idx_pipeline_tasks_status
    ON pipeline_tasks(status, heartbeat_at DESC);

CREATE TABLE IF NOT EXISTS documents (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    canonical_key VARCHAR(64) NOT NULL,
    canonical_url VARCHAR(2048) NOT NULL,
    source_type VARCHAR(100) NOT NULL,
    source_name VARCHAR(255),
    media_type VARCHAR(255) NOT NULL DEFAULT 'text/plain',
    language VARCHAR(20),
    title VARCHAR(1000),
    author VARCHAR(500),
    published_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, canonical_key)
);

CREATE INDEX IF NOT EXISTS idx_documents_competitor
    ON documents(competitor_id, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_source_type
    ON documents(competitor_id, source_type);
CREATE INDEX IF NOT EXISTS idx_documents_published
    ON documents(competitor_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_documents_metadata_gin
    ON documents USING GIN(metadata);

CREATE TABLE IF NOT EXISTS document_versions (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    content_hash VARCHAR(64) NOT NULL,
    normalized_text TEXT NOT NULL,
    raw_text TEXT,
    byte_size BIGINT NOT NULL DEFAULT 0,
    extraction_method VARCHAR(100) NOT NULL DEFAULT 'legacy',
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_document_versions_document
    ON document_versions(document_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_document_versions_hash
    ON document_versions(content_hash);

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS current_version_id BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'documents_current_version_fk'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT documents_current_version_fk
            FOREIGN KEY (current_version_id)
            REFERENCES document_versions(id)
            ON DELETE SET NULL;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS document_artifacts (
    id BIGSERIAL PRIMARY KEY,
    document_version_id BIGINT NOT NULL
        REFERENCES document_versions(id) ON DELETE CASCADE,
    artifact_type VARCHAR(80) NOT NULL,
    media_type VARCHAR(255) NOT NULL,
    storage_uri VARCHAR(2048),
    content BYTEA,
    byte_size BIGINT NOT NULL DEFAULT 0,
    sha256 VARCHAR(64) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_version_id, artifact_type, sha256)
);

CREATE INDEX IF NOT EXISTS idx_document_artifacts_version
    ON document_artifacts(document_version_id);

CREATE TABLE IF NOT EXISTS document_chunks (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    document_version_id BIGINT NOT NULL
        REFERENCES document_versions(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    qdrant_point_id VARCHAR(100),
    indexed_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (document_version_id, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_document_chunks_competitor
    ON document_chunks(competitor_id, document_version_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_document_chunks_pending
    ON document_chunks(competitor_id, id)
    WHERE indexed_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_document_chunks_full_text
    ON document_chunks USING GIN(
        to_tsvector('english', COALESCE(content, ''))
    );

CREATE TABLE IF NOT EXISTS claims (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    pipeline_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    claim_type VARCHAR(100) NOT NULL,
    subject VARCHAR(1000),
    predicate VARCHAR(255),
    object_text TEXT,
    statement TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0 AND confidence <= 1),
    status VARCHAR(20) NOT NULL DEFAULT 'supported',
    occurred_at TIMESTAMPTZ,
    valid_from TIMESTAMPTZ,
    valid_to TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'claims_status_check'
    ) THEN
        ALTER TABLE claims
            ADD CONSTRAINT claims_status_check
            CHECK (status IN (
                'proposed', 'supported', 'confirmed', 'disputed', 'stale'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_claims_competitor
    ON claims(competitor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_claims_run
    ON claims(pipeline_run_id);
CREATE INDEX IF NOT EXISTS idx_claims_status
    ON claims(competitor_id, status);
CREATE INDEX IF NOT EXISTS idx_claims_metadata_gin
    ON claims USING GIN(metadata);

CREATE TABLE IF NOT EXISTS claim_evidence (
    id BIGSERIAL PRIMARY KEY,
    claim_id BIGINT NOT NULL REFERENCES claims(id) ON DELETE CASCADE,
    evidence_id BIGINT REFERENCES evidence(id) ON DELETE CASCADE,
    document_chunk_id BIGINT REFERENCES document_chunks(id) ON DELETE CASCADE,
    stance VARCHAR(20) NOT NULL DEFAULT 'supports',
    excerpt TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (evidence_id IS NOT NULL OR document_chunk_id IS NOT NULL)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'claim_evidence_stance_check'
    ) THEN
        ALTER TABLE claim_evidence
            ADD CONSTRAINT claim_evidence_stance_check
            CHECK (stance IN ('supports', 'contradicts', 'context'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_evidence_evidence_unique
    ON claim_evidence(claim_id, evidence_id, stance)
    WHERE evidence_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_claim_evidence_chunk_unique
    ON claim_evidence(claim_id, document_chunk_id, stance)
    WHERE document_chunk_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_claim_evidence_claim
    ON claim_evidence(claim_id);
CREATE INDEX IF NOT EXISTS idx_claim_evidence_evidence
    ON claim_evidence(evidence_id);

CREATE TABLE IF NOT EXISTS source_health (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    adapter_name VARCHAR(120) NOT NULL,
    source_key VARCHAR(2048) NOT NULL,
    source_key_hash VARCHAR(64) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'healthy',
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    total_attempts BIGINT NOT NULL DEFAULT 0,
    total_items BIGINT NOT NULL DEFAULT 0,
    last_latency_ms INTEGER,
    last_error TEXT,
    last_attempt_at TIMESTAMPTZ,
    last_success_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, adapter_name, source_key_hash)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'source_health_status_check'
    ) THEN
        ALTER TABLE source_health
            ADD CONSTRAINT source_health_status_check
            CHECK (status IN ('healthy', 'degraded', 'error', 'disabled'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_source_health_competitor
    ON source_health(competitor_id, status, updated_at DESC);

ALTER TABLE evidence
    ADD COLUMN IF NOT EXISTS document_version_id BIGINT
        REFERENCES document_versions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS pipeline_run_id BIGINT
        REFERENCES pipeline_runs(id) ON DELETE SET NULL;

ALTER TABLE raw_data
    ADD COLUMN IF NOT EXISTS document_version_id BIGINT
        REFERENCES document_versions(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS pipeline_run_id BIGINT
        REFERENCES pipeline_runs(id) ON DELETE SET NULL;

ALTER TABLE insights
    ADD COLUMN IF NOT EXISTS pipeline_run_id BIGINT
        REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS claim_id BIGINT
        REFERENCES claims(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE signals
    ADD COLUMN IF NOT EXISTS pipeline_run_id BIGINT
        REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS claim_id BIGINT
        REFERENCES claims(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE predictions
    ADD COLUMN IF NOT EXISTS pipeline_run_id BIGINT
        REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS claim_id BIGINT
        REFERENCES claims(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE relationships
    ADD COLUMN IF NOT EXISTS pipeline_run_id BIGINT
        REFERENCES pipeline_runs(id) ON DELETE SET NULL;

DROP TRIGGER IF EXISTS set_claims_updated_at ON claims;
CREATE TRIGGER set_claims_updated_at
    BEFORE UPDATE ON claims
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_source_health_updated_at ON source_health;
CREATE TRIGGER set_source_health_updated_at
    BEFORE UPDATE ON source_health
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
