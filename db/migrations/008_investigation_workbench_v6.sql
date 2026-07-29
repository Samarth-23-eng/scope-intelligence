CREATE TABLE IF NOT EXISTS investigations (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    pipeline_run_id BIGINT REFERENCES pipeline_runs(id) ON DELETE SET NULL,
    title VARCHAR(500) NOT NULL,
    question TEXT NOT NULL,
    scope JSONB NOT NULL DEFAULT '{}'::jsonb,
    status VARCHAR(20) NOT NULL DEFAULT 'draft',
    model VARCHAR(255),
    max_steps INTEGER NOT NULL DEFAULT 6,
    completed_steps INTEGER NOT NULL DEFAULT 0,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    source_diversity INTEGER NOT NULL DEFAULT 0,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0
        CHECK (confidence >= 0 AND confidence <= 1),
    executive_summary TEXT,
    answer TEXT,
    gaps JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    cancel_requested_at TIMESTAMPTZ,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'investigations_status_check'
    ) THEN
        ALTER TABLE investigations
            ADD CONSTRAINT investigations_status_check
            CHECK (status IN (
                'draft', 'queued', 'running', 'completed',
                'partial', 'failed', 'cancelled'
            ));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'investigations_max_steps_check'
    ) THEN
        ALTER TABLE investigations
            ADD CONSTRAINT investigations_max_steps_check
            CHECK (max_steps BETWEEN 1 AND 12);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_investigations_competitor
    ON investigations(competitor_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_investigations_status
    ON investigations(status, updated_at DESC);

CREATE TABLE IF NOT EXISTS investigation_steps (
    id BIGSERIAL PRIMARY KEY,
    investigation_id BIGINT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    step_index INTEGER NOT NULL,
    question TEXT NOT NULL,
    rationale TEXT,
    search_query TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'pending',
    answer TEXT,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    source_diversity INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    error TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (investigation_id, step_index)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'investigation_steps_status_check'
    ) THEN
        ALTER TABLE investigation_steps
            ADD CONSTRAINT investigation_steps_status_check
            CHECK (status IN (
                'pending', 'running', 'completed', 'failed', 'skipped'
            ));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_investigation_steps_investigation
    ON investigation_steps(investigation_id, step_index);

CREATE TABLE IF NOT EXISTS investigation_findings (
    id BIGSERIAL PRIMARY KEY,
    investigation_id BIGINT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    step_id BIGINT REFERENCES investigation_steps(id) ON DELETE SET NULL,
    finding_type VARCHAR(40) NOT NULL DEFAULT 'fact',
    statement TEXT NOT NULL,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0 AND confidence <= 1),
    status VARCHAR(20) NOT NULL DEFAULT 'supported',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'investigation_findings_status_check'
    ) THEN
        ALTER TABLE investigation_findings
            ADD CONSTRAINT investigation_findings_status_check
            CHECK (status IN ('supported', 'provisional', 'disputed'));
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_investigation_findings_investigation
    ON investigation_findings(investigation_id, confidence DESC, id);

CREATE TABLE IF NOT EXISTS investigation_citations (
    id BIGSERIAL PRIMARY KEY,
    investigation_id BIGINT NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    step_id BIGINT REFERENCES investigation_steps(id) ON DELETE CASCADE,
    finding_id BIGINT REFERENCES investigation_findings(id) ON DELETE CASCADE,
    evidence_id BIGINT REFERENCES evidence(id) ON DELETE SET NULL,
    document_chunk_id BIGINT REFERENCES document_chunks(id) ON DELETE SET NULL,
    stance VARCHAR(20) NOT NULL DEFAULT 'supports',
    excerpt TEXT,
    source_url VARCHAR(2048) NOT NULL,
    title VARCHAR(1000),
    source_type VARCHAR(100) NOT NULL DEFAULT 'unknown',
    relevance DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (relevance >= 0 AND relevance <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (evidence_id IS NOT NULL OR document_chunk_id IS NOT NULL)
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'investigation_citations_stance_check'
    ) THEN
        ALTER TABLE investigation_citations
            ADD CONSTRAINT investigation_citations_stance_check
            CHECK (stance IN ('supports', 'contradicts', 'context'));
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_investigation_citations_unique
    ON investigation_citations(
        investigation_id,
        COALESCE(step_id, 0),
        COALESCE(finding_id, 0),
        COALESCE(evidence_id, 0),
        COALESCE(document_chunk_id, 0),
        stance
    );
CREATE INDEX IF NOT EXISTS idx_investigation_citations_investigation
    ON investigation_citations(investigation_id, step_id, finding_id);

DROP TRIGGER IF EXISTS set_investigations_updated_at ON investigations;
CREATE TRIGGER set_investigations_updated_at
    BEFORE UPDATE ON investigations
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
