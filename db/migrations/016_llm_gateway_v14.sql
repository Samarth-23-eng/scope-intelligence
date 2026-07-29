CREATE TABLE IF NOT EXISTS llm_configuration (
    id SMALLINT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    provider VARCHAR(40) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    base_url TEXT NOT NULL,
    model VARCHAR(255) NOT NULL,
    auth_mode VARCHAR(30) NOT NULL DEFAULT 'api_key',
    secret_ciphertext TEXT,
    secret_hint VARCHAR(32),
    enabled BOOLEAN NOT NULL DEFAULT TRUE,
    last_status VARCHAR(30) NOT NULL DEFAULT 'untested',
    last_error TEXT,
    last_tested_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (provider IN (
        'openai', 'openrouter', 'anthropic', 'google',
        'ollama', 'lmstudio', 'openai_compatible'
    )),
    CHECK (auth_mode IN ('api_key', 'bearer', 'none')),
    CHECK (last_status IN ('untested', 'connected', 'error'))
);

COMMENT ON COLUMN llm_configuration.secret_ciphertext IS
    'Fernet-encrypted API key or bearer token. Plaintext credentials are never stored.';
