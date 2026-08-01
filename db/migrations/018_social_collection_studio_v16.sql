CREATE TABLE IF NOT EXISTS social_collection_runs (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL
        REFERENCES competitors(id) ON DELETE CASCADE,
    pipeline_run_id BIGINT NOT NULL,
    campaign_id BIGINT NOT NULL,
    platform VARCHAR(80) NOT NULL,
    mode VARCHAR(30) NOT NULL,
    query TEXT,
    target_url TEXT,
    connector_version VARCHAR(40) NOT NULL DEFAULT '1',
    options JSONB NOT NULL DEFAULT '{}'::jsonb,
    checkpoint JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (pipeline_run_id),
    UNIQUE (campaign_id)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_pipeline_runs_id_competitor
    ON pipeline_runs(id, competitor_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_collection_campaigns_id_competitor
    ON collection_campaigns(id, competitor_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'social_collection_runs_mode_check'
    ) THEN
        ALTER TABLE social_collection_runs
            ADD CONSTRAINT social_collection_runs_mode_check
            CHECK (mode IN ('discover', 'account', 'evidence'));
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'social_collection_runs_pipeline_owner_fk'
    ) THEN
        ALTER TABLE social_collection_runs
            ADD CONSTRAINT social_collection_runs_pipeline_owner_fk
            FOREIGN KEY (pipeline_run_id, competitor_id)
            REFERENCES pipeline_runs(id, competitor_id)
            ON DELETE CASCADE;
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'social_collection_runs_campaign_owner_fk'
    ) THEN
        ALTER TABLE social_collection_runs
            ADD CONSTRAINT social_collection_runs_campaign_owner_fk
            FOREIGN KEY (campaign_id, competitor_id)
            REFERENCES collection_campaigns(id, competitor_id)
            ON DELETE CASCADE;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_social_collection_runs_competitor
    ON social_collection_runs(competitor_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_social_collection_runs_id_competitor
    ON social_collection_runs(id, competitor_id);

CREATE TABLE IF NOT EXISTS social_profiles (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL
        REFERENCES competitors(id) ON DELETE CASCADE,
    platform VARCHAR(80) NOT NULL,
    platform_profile_id VARCHAR(500) NOT NULL,
    handle VARCHAR(500),
    display_name VARCHAR(1000),
    profile_url VARCHAR(4096) NOT NULL,
    biography TEXT,
    follower_count BIGINT,
    following_count BIGINT,
    content_count BIGINT,
    verified BOOLEAN NOT NULL DEFAULT FALSE,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_id BIGINT REFERENCES evidence(id) ON DELETE SET NULL,
    document_version_id BIGINT
        REFERENCES document_versions(id) ON DELETE SET NULL,
    refresh_due_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, platform, platform_profile_id)
);

CREATE INDEX IF NOT EXISTS idx_social_profiles_competitor
    ON social_profiles(competitor_id, platform, last_seen_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_profiles_handle
    ON social_profiles(platform, handle);
CREATE UNIQUE INDEX IF NOT EXISTS idx_social_profiles_id_competitor
    ON social_profiles(id, competitor_id);

CREATE TABLE IF NOT EXISTS social_posts (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL
        REFERENCES competitors(id) ON DELETE CASCADE,
    profile_id BIGINT,
    first_seen_run_id BIGINT,
    latest_seen_run_id BIGINT,
    platform VARCHAR(80) NOT NULL,
    platform_post_id VARCHAR(500) NOT NULL,
    content_type VARCHAR(80) NOT NULL DEFAULT 'post',
    url VARCHAR(4096) NOT NULL,
    title VARCHAR(2000),
    body TEXT,
    author_platform_id VARCHAR(500),
    author_handle VARCHAR(500),
    published_at TIMESTAMPTZ,
    language VARCHAR(20),
    engagement JSONB NOT NULL DEFAULT '{}'::jsonb,
    media JSONB NOT NULL DEFAULT '[]'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_id BIGINT REFERENCES evidence(id) ON DELETE SET NULL,
    document_version_id BIGINT
        REFERENCES document_versions(id) ON DELETE SET NULL,
    refresh_due_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, platform, platform_post_id),
    FOREIGN KEY (profile_id, competitor_id)
        REFERENCES social_profiles(id, competitor_id)
        ON DELETE SET NULL (profile_id),
    FOREIGN KEY (first_seen_run_id, competitor_id)
        REFERENCES social_collection_runs(id, competitor_id)
        ON DELETE SET NULL (first_seen_run_id),
    FOREIGN KEY (latest_seen_run_id, competitor_id)
        REFERENCES social_collection_runs(id, competitor_id)
        ON DELETE SET NULL (latest_seen_run_id)
);

CREATE INDEX IF NOT EXISTS idx_social_posts_competitor
    ON social_posts(competitor_id, platform, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_posts_profile
    ON social_posts(profile_id, published_at DESC);
CREATE INDEX IF NOT EXISTS idx_social_posts_latest_run
    ON social_posts(latest_seen_run_id);
CREATE INDEX IF NOT EXISTS idx_social_posts_metadata_gin
    ON social_posts USING GIN(metadata);
CREATE UNIQUE INDEX IF NOT EXISTS idx_social_posts_id_competitor
    ON social_posts(id, competitor_id);

CREATE TABLE IF NOT EXISTS social_comments (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL
        REFERENCES competitors(id) ON DELETE CASCADE,
    post_id BIGINT NOT NULL,
    first_seen_run_id BIGINT,
    latest_seen_run_id BIGINT,
    platform VARCHAR(80) NOT NULL,
    platform_comment_id VARCHAR(500) NOT NULL,
    parent_platform_comment_id VARCHAR(500),
    thread_root_platform_comment_id VARCHAR(500),
    depth INTEGER NOT NULL DEFAULT 0 CHECK (depth >= 0),
    author_platform_id VARCHAR(500),
    author_handle VARCHAR(500),
    author_display_name VARCHAR(1000),
    text TEXT NOT NULL,
    like_count BIGINT NOT NULL DEFAULT 0,
    reply_count BIGINT NOT NULL DEFAULT 0,
    published_at TIMESTAMPTZ,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    evidence_id BIGINT REFERENCES evidence(id) ON DELETE SET NULL,
    document_version_id BIGINT
        REFERENCES document_versions(id) ON DELETE SET NULL,
    refresh_due_at TIMESTAMPTZ,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (competitor_id, platform, platform_comment_id),
    FOREIGN KEY (post_id, competitor_id)
        REFERENCES social_posts(id, competitor_id) ON DELETE CASCADE,
    FOREIGN KEY (first_seen_run_id, competitor_id)
        REFERENCES social_collection_runs(id, competitor_id)
        ON DELETE SET NULL (first_seen_run_id),
    FOREIGN KEY (latest_seen_run_id, competitor_id)
        REFERENCES social_collection_runs(id, competitor_id)
        ON DELETE SET NULL (latest_seen_run_id)
);

CREATE INDEX IF NOT EXISTS idx_social_comments_post
    ON social_comments(post_id, depth, published_at);
CREATE INDEX IF NOT EXISTS idx_social_comments_latest_run
    ON social_comments(latest_seen_run_id);
CREATE INDEX IF NOT EXISTS idx_social_comments_metadata_gin
    ON social_comments USING GIN(metadata);
CREATE UNIQUE INDEX IF NOT EXISTS idx_social_comments_id_competitor
    ON social_comments(id, competitor_id);

CREATE TABLE IF NOT EXISTS social_observations (
    id BIGSERIAL PRIMARY KEY,
    competitor_id INTEGER NOT NULL
        REFERENCES competitors(id) ON DELETE CASCADE,
    run_id BIGINT NOT NULL,
    resource_type VARCHAR(20) NOT NULL,
    profile_id BIGINT,
    post_id BIGINT,
    comment_id BIGINT,
    metrics JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (resource_type IN ('profile', 'post', 'comment')),
    CHECK (num_nonnulls(profile_id, post_id, comment_id) = 1),
    FOREIGN KEY (run_id, competitor_id)
        REFERENCES social_collection_runs(id, competitor_id) ON DELETE CASCADE,
    FOREIGN KEY (profile_id, competitor_id)
        REFERENCES social_profiles(id, competitor_id) ON DELETE CASCADE,
    FOREIGN KEY (post_id, competitor_id)
        REFERENCES social_posts(id, competitor_id) ON DELETE CASCADE,
    FOREIGN KEY (comment_id, competitor_id)
        REFERENCES social_comments(id, competitor_id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_social_observations_profile_run
    ON social_observations(run_id, profile_id)
    WHERE profile_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_social_observations_post_run
    ON social_observations(run_id, post_id)
    WHERE post_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_social_observations_comment_run
    ON social_observations(run_id, comment_id)
    WHERE comment_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_social_observations_competitor
    ON social_observations(competitor_id, observed_at DESC);

DROP TRIGGER IF EXISTS set_social_collection_runs_updated_at
    ON social_collection_runs;
CREATE TRIGGER set_social_collection_runs_updated_at
    BEFORE UPDATE ON social_collection_runs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_social_profiles_updated_at ON social_profiles;
CREATE TRIGGER set_social_profiles_updated_at
    BEFORE UPDATE ON social_profiles
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_social_posts_updated_at ON social_posts;
CREATE TRIGGER set_social_posts_updated_at
    BEFORE UPDATE ON social_posts
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_social_comments_updated_at ON social_comments;
CREATE TRIGGER set_social_comments_updated_at
    BEFORE UPDATE ON social_comments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
