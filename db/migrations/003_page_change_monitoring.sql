CREATE TABLE IF NOT EXISTS page_snapshots (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    evidence_id BIGINT NOT NULL REFERENCES evidence(id) ON DELETE RESTRICT,
    source_url VARCHAR(2048) NOT NULL,
    title VARCHAR(1000),
    normalized_content TEXT NOT NULL,
    content_hash VARCHAR(64) NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    captured_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_page_snapshots_competitor
    ON page_snapshots(competitor_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_page_snapshots_url
    ON page_snapshots(competitor_id, MD5(source_url), captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_page_snapshots_hash
    ON page_snapshots(competitor_id, content_hash);

CREATE TABLE IF NOT EXISTS page_changes (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL REFERENCES competitors(id) ON DELETE CASCADE,
    previous_snapshot_id BIGINT NOT NULL REFERENCES page_snapshots(id) ON DELETE RESTRICT,
    current_snapshot_id BIGINT NOT NULL REFERENCES page_snapshots(id) ON DELETE CASCADE,
    evidence_id BIGINT NOT NULL REFERENCES evidence(id) ON DELETE RESTRICT,
    source_url VARCHAR(2048) NOT NULL,
    change_type VARCHAR(50) NOT NULL,
    summary TEXT NOT NULL,
    before_excerpt TEXT,
    after_excerpt TEXT,
    similarity DOUBLE PRECISION NOT NULL CHECK (similarity >= 0 AND similarity <= 1),
    significance DOUBLE PRECISION NOT NULL CHECK (significance >= 0 AND significance <= 1),
    detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (current_snapshot_id)
);

CREATE INDEX IF NOT EXISTS idx_page_changes_competitor
    ON page_changes(competitor_id, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_page_changes_type
    ON page_changes(change_type);
CREATE INDEX IF NOT EXISTS idx_page_changes_significance
    ON page_changes(significance DESC);
