ALTER TABLE raw_data
    ADD COLUMN IF NOT EXISTS metadata JSONB NOT NULL DEFAULT '{}'::jsonb;

CREATE INDEX IF NOT EXISTS idx_raw_data_metadata_gin
    ON raw_data USING GIN(metadata);

ALTER TABLE relationships
    ADD COLUMN IF NOT EXISTS rationale TEXT,
    ADD COLUMN IF NOT EXISTS extraction_method VARCHAR(50) NOT NULL DEFAULT 'legacy',
    ADD COLUMN IF NOT EXISTS evidence_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationships_evidence_count_check'
    ) THEN
        ALTER TABLE relationships
            ADD CONSTRAINT relationships_evidence_count_check
            CHECK (evidence_count >= 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationships_status_check'
    ) THEN
        ALTER TABLE relationships
            ADD CONSTRAINT relationships_status_check
            CHECK (status IN ('active', 'stale', 'disputed'));
    END IF;
END $$;

UPDATE relationships
SET extraction_method = CASE
        WHEN metadata->>'source' = 'llm_evidence_extraction' THEN 'llm'
        ELSE extraction_method
    END,
    first_seen_at = created_at,
    last_seen_at = created_at;

CREATE TABLE IF NOT EXISTS relationship_evidence (
    relationship_id BIGINT NOT NULL REFERENCES relationships(id) ON DELETE CASCADE,
    evidence_id BIGINT NOT NULL REFERENCES evidence(id) ON DELETE CASCADE,
    support_excerpt TEXT,
    confidence DOUBLE PRECISION NOT NULL DEFAULT 0.5
        CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (relationship_id, evidence_id)
);

CREATE INDEX IF NOT EXISTS idx_relationship_evidence_evidence
    ON relationship_evidence(evidence_id);
CREATE INDEX IF NOT EXISTS idx_relationships_status
    ON relationships(status);
CREATE INDEX IF NOT EXISTS idx_relationships_last_seen
    ON relationships(last_seen_at DESC);
