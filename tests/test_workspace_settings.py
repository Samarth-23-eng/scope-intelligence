from __future__ import annotations

from datetime import UTC, datetime

from pydantic import SecretStr

from api.settings_routes import WorkspaceSettingsUpdate
from intelligence import workspace_settings as workspace_module
from intelligence.workspace_settings import PREFERENCE_FIELDS, WorkspaceSettingsStore


def test_workspace_settings_update_normalizes_job_sources():
    update = WorkspaceSettingsUpdate(job_sources="Google, linkedin, google")

    assert update.job_sources == "google,linkedin"


def test_workspace_settings_update_keeps_credentials_secret():
    update = WorkspaceSettingsUpdate(github_token="private-test-value")

    assert isinstance(update.github_token, SecretStr)
    assert "private-test-value" not in repr(update)
    assert "private-test-value" not in str(update.model_dump())


def test_workspace_settings_public_contract_never_returns_ciphertexts(monkeypatch):
    now = datetime.now(UTC)
    row = {
        "preferences": {"crawler_max_pages": 91},
        "secret_ciphertexts": {"github_token": "encrypted-private-value"},
        "created_at": now,
        "updated_at": now,
    }
    monkeypatch.setattr(WorkspaceSettingsStore, "_row", staticmethod(lambda: row))
    monkeypatch.setattr(
        workspace_module,
        "_ENVIRONMENT_SECRETS",
        {"youtube_api_key": None, "github_token": None, "newsapi_key": None},
    )

    public = WorkspaceSettingsStore.public_dict()

    assert public["preferences"]["crawler_max_pages"] == 91
    assert set(public["preferences"]) == set(PREFERENCE_FIELDS)
    assert public["secrets"]["github_token"] == {
        "configured": True,
        "source": "saved",
    }
    assert "encrypted-private-value" not in str(public)
