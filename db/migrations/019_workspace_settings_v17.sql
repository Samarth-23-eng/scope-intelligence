CREATE TABLE IF NOT EXISTS workspace_configuration (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    preferences JSONB NOT NULL DEFAULT '{}'::jsonb,
    secret_ciphertexts JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON COLUMN workspace_configuration.secret_ciphertexts IS
    'Fernet-encrypted connector credentials. Plaintext credentials are never stored.';

DROP TRIGGER IF EXISTS set_workspace_configuration_updated_at
    ON workspace_configuration;
CREATE TRIGGER set_workspace_configuration_updated_at
    BEFORE UPDATE ON workspace_configuration
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
