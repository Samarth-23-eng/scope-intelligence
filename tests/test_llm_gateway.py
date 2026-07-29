from config.settings import settings
from llm_gateway.configuration import CredentialVault, LLMConnection


def test_public_connection_never_returns_plaintext_secret():
    connection = LLMConnection(
        provider="openrouter",
        display_name="OpenRouter",
        base_url="https://openrouter.ai/api/v1",
        model="example/model",
        api_key="not-a-real-key",
    )

    payload = connection.public_dict()

    assert "api_key" not in payload
    assert "not-a-real-key" not in repr(payload)
    assert payload["has_secret"] is True
    assert payload["configured"] is True


def test_local_model_can_run_without_a_credential():
    connection = LLMConnection(
        provider="ollama",
        display_name="Ollama",
        base_url="http://localhost:11434/v1",
        model="llama3.2",
        auth_mode="none",
    )

    assert connection.configured is True
    assert connection.requires_secret is False


def test_cloud_model_requires_a_credential():
    connection = LLMConnection(
        provider="anthropic",
        display_name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        model="claude-example",
        auth_mode="api_key",
    )

    assert connection.configured is False
    assert connection.requires_secret is True


def test_credential_vault_encrypts_with_a_private_local_key(monkeypatch, tmp_path):
    key_file = tmp_path / "llm.key"
    monkeypatch.setattr(settings, "llm_master_key", None)
    monkeypatch.setattr(settings, "llm_master_key_file", str(key_file))
    vault = CredentialVault()

    ciphertext = vault.encrypt("provider-secret")

    assert ciphertext != "provider-secret"
    assert vault.decrypt(ciphertext) == "provider-secret"
    assert key_file.exists()
