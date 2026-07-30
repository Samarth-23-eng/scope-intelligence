CREATE TABLE IF NOT EXISTS graph_snapshot_entities (
    snapshot_id BIGINT NOT NULL
        REFERENCES graph_snapshots(id) ON DELETE CASCADE,
    entity_id BIGINT NOT NULL,
    name VARCHAR(500) NOT NULL,
    entity_type VARCHAR(100) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, entity_id)
);

CREATE INDEX IF NOT EXISTS idx_graph_snapshot_entities_entity
    ON graph_snapshot_entities(entity_id, snapshot_id DESC);

CREATE TABLE IF NOT EXISTS graph_snapshot_relationships (
    snapshot_id BIGINT NOT NULL
        REFERENCES graph_snapshots(id) ON DELETE CASCADE,
    relationship_id BIGINT NOT NULL,
    source_entity_id BIGINT NOT NULL,
    target_entity_id BIGINT NOT NULL,
    relationship_type VARCHAR(100) NOT NULL,
    weight DOUBLE PRECISION NOT NULL DEFAULT 0,
    status VARCHAR(20) NOT NULL DEFAULT 'active',
    risk_level VARCHAR(20) NOT NULL DEFAULT 'unassessed',
    evidence_count INTEGER NOT NULL DEFAULT 0,
    source_diversity INTEGER NOT NULL DEFAULT 0,
    freshness_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    contradiction_count INTEGER NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ,
    last_seen_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    PRIMARY KEY (snapshot_id, relationship_id)
);

CREATE INDEX IF NOT EXISTS idx_graph_snapshot_relationships_edge
    ON graph_snapshot_relationships(
        source_entity_id,
        target_entity_id,
        relationship_type,
        snapshot_id DESC
    );

CREATE TABLE IF NOT EXISTS graph_operator_actions (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL
        REFERENCES competitors(id) ON DELETE CASCADE,
    entity_id BIGINT REFERENCES entities(id) ON DELETE SET NULL,
    relationship_id BIGINT REFERENCES relationships(id) ON DELETE SET NULL,
    action_type VARCHAR(60) NOT NULL,
    before_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    after_state JSONB NOT NULL DEFAULT '{}'::jsonb,
    note TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_graph_operator_actions_competitor
    ON graph_operator_actions(competitor_id, created_at DESC);

ALTER TABLE relationships
    ADD COLUMN IF NOT EXISTS operator_status VARCHAR(20),
    ADD COLUMN IF NOT EXISTS operator_note TEXT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'relationships_operator_status_check'
    ) THEN
        ALTER TABLE relationships
            ADD CONSTRAINT relationships_operator_status_check
            CHECK (
                operator_status IS NULL
                OR operator_status IN ('accepted', 'dismissed', 'corrected')
            );
    END IF;
END $$;
