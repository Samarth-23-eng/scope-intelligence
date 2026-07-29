from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from config.settings import settings
from db.postgres import get_connection

logger = logging.getLogger(__name__)

SUPPORTED_PROVIDERS = {
    "openai",
    "openrouter",
    "anthropic",
    "google",
    "ollama",
    "lmstudio",
    "openai_compatible",
}
SUPPORTED_AUTH_MODES = {"api_key", "bearer", "none"}
LOCAL_PROVIDERS = {"ollama", "lmstudio"}

PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "openai": {"base_url": "https://api.openai.com/v1", "label": "OpenAI"},
    "openrouter": {"base_url": "https://openrouter.ai/api/v1", "label": "OpenRouter"},
    "anthropic": {"base_url": "https://api.anthropic.com/v1", "label": "Anthropic"},
    "google": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "label": "Google Gemini",
    },
    "ollama": {"base_url": "http://localhost:11434/v1", "label": "Ollama"},
    "lmstudio": {"base_url": "http://localhost:1234/v1", "label": "LM Studio"},
    "openai_compatible": {"base_url": "http://localhost:8001/v1", "label": "Custom endpoint"},
}


@dataclass(frozen=True)
class LLMConnection:
    provider: str
    display_name: str
    base_url: str
    model: str
    auth_mode: str = "api_key"
    api_key: str | None = None
    enabled: bool = True
    source: str = "environment"
    last_status: str = "untested"
    last_error: str | None = None
    last_tested_at: str | None = None

    @property
    def requires_secret(self) -> bool:
        return self.auth_mode != "none" and self.provider not in LOCAL_PROVIDERS

    @property
    def configured(self) -> bool:
        return bool(
            self.enabled
            and self.model.strip()
            and self.base_url.strip()
            and (not self.requires_secret or self.api_key)
        )

    def public_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        secret = payload.pop("api_key", None)
        payload["has_secret"] = bool(secret)
        payload["configured"] = self.configured
        return payload


class CredentialVault:
    """Encrypt provider credentials with a key kept outside the database."""

    def __init__(self) -> None:
        self._fernet: Fernet | None = None

    def _load_key(self) -> bytes:
        configured = (settings.llm_master_key or "").strip()
        if configured:
            return configured.encode("utf-8")

        key_path = Path(settings.llm_master_key_file).expanduser().resolve()
        if key_path.exists():
            return key_path.read_bytes().strip()

        key_path.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(key_path, flags, 0o600)
        try:
            os.write(descriptor, key + b"\n")
        finally:
            os.close(descriptor)
        logger.info("Created local LLM credential encryption key at %s", key_path)
        return key

    def _cipher(self) -> Fernet:
        if self._fernet is None:
            try:
                self._fernet = Fernet(self._load_key())
            except (TypeError, ValueError) as exc:
                raise RuntimeError(
                    "LLM_MASTER_KEY is invalid. Supply a URL-safe Fernet key."
                ) from exc
        return self._fernet

    def encrypt(self, value: str) -> str:
        return self._cipher().encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str | None) -> str | None:
        if not value:
            return None
        try:
            return self._cipher().decrypt(value.encode("ascii")).decode("utf-8")
        except InvalidToken as exc:
            raise RuntimeError(
                "The saved LLM credential cannot be decrypted with this installation's master key."
            ) from exc


vault = CredentialVault()


def _normalise_provider(provider: str) -> str:
    value = (provider or "").strip().lower().replace("-", "_")
    if value not in SUPPORTED_PROVIDERS:
        raise ValueError(f"Unsupported LLM provider: {provider}")
    return value


def _normalise_auth_mode(auth_mode: str) -> str:
    value = (auth_mode or "").strip().lower()
    if value not in SUPPORTED_AUTH_MODES:
        raise ValueError(f"Unsupported authentication mode: {auth_mode}")
    return value


def _secret_hint(secret: str | None) -> str | None:
    if not secret:
        return None
    if len(secret) <= 8:
        return "••••••••"
    return f"{secret[:3]}••••{secret[-4:]}"


class LLMConnectionStore:
    def get(self) -> LLMConnection | None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT provider, display_name, base_url, model, auth_mode,
                           secret_ciphertext, enabled, last_status, last_error,
                           last_tested_at
                    FROM llm_configuration
                    WHERE id = 1
                    """
                )
                row = cur.fetchone()
        if not row:
            return None
        return LLMConnection(
            provider=row["provider"],
            display_name=row["display_name"],
            base_url=row["base_url"],
            model=row["model"],
            auth_mode=row["auth_mode"],
            api_key=vault.decrypt(row.get("secret_ciphertext")),
            enabled=bool(row["enabled"]),
            source="saved",
            last_status=row.get("last_status") or "untested",
            last_error=row.get("last_error"),
            last_tested_at=(
                row["last_tested_at"].isoformat() if row.get("last_tested_at") else None
            ),
        )

    def save(
        self,
        *,
        provider: str,
        display_name: str | None,
        base_url: str | None,
        model: str,
        auth_mode: str,
        api_key: str | None,
        enabled: bool,
        clear_secret: bool = False,
    ) -> LLMConnection:
        provider = _normalise_provider(provider)
        auth_mode = _normalise_auth_mode(auth_mode)
        model = (model or "").strip()
        if not model:
            raise ValueError("A model identifier is required.")
        resolved_url = (base_url or PROVIDER_DEFAULTS[provider]["base_url"]).strip().rstrip("/")
        if not resolved_url.startswith(("http://", "https://")):
            raise ValueError("The provider URL must start with http:// or https://.")
        name = (display_name or PROVIDER_DEFAULTS[provider]["label"]).strip()[:120]
        supplied_secret = (api_key or "").strip() or None

        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT secret_ciphertext FROM llm_configuration WHERE id = 1"
                )
                existing = cur.fetchone()
                ciphertext = existing.get("secret_ciphertext") if existing else None
                if clear_secret or auth_mode == "none":
                    ciphertext = None
                elif supplied_secret:
                    ciphertext = vault.encrypt(supplied_secret)

                cur.execute(
                    """
                    INSERT INTO llm_configuration (
                        id, provider, display_name, base_url, model, auth_mode,
                        secret_ciphertext, secret_hint, enabled, last_status,
                        last_error, last_tested_at, updated_at
                    )
                    VALUES (1, %s, %s, %s, %s, %s, %s, %s, %s, 'untested', NULL, NULL, NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        provider = EXCLUDED.provider,
                        display_name = EXCLUDED.display_name,
                        base_url = EXCLUDED.base_url,
                        model = EXCLUDED.model,
                        auth_mode = EXCLUDED.auth_mode,
                        secret_ciphertext = EXCLUDED.secret_ciphertext,
                        secret_hint = EXCLUDED.secret_hint,
                        enabled = EXCLUDED.enabled,
                        last_status = 'untested',
                        last_error = NULL,
                        last_tested_at = NULL,
                        updated_at = NOW()
                    """,
                    (
                        provider,
                        name,
                        resolved_url,
                        model,
                        auth_mode,
                        ciphertext,
                        _secret_hint(supplied_secret) if supplied_secret else None,
                        enabled,
                    ),
                )
                conn.commit()
        saved = self.get()
        if saved is None:
            raise RuntimeError("The LLM connection was not saved.")
        return saved

    def record_test(self, *, ok: bool, error: str | None = None) -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE llm_configuration
                    SET last_status = %s, last_error = %s,
                        last_tested_at = NOW(), updated_at = NOW()
                    WHERE id = 1
                    """,
                    ("connected" if ok else "error", error[:1000] if error else None),
                )
                conn.commit()

    def delete(self) -> None:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM llm_configuration WHERE id = 1")
                conn.commit()


def environment_connection() -> LLMConnection:
    provider = _normalise_provider(settings.llm_provider)
    base_url = (
        settings.llm_base_url
        or settings.nine_router_url
        or PROVIDER_DEFAULTS[provider]["base_url"]
    ).rstrip("/")
    secret = (
        settings.llm_api_key
        or settings.nine_router_api_key
        or (settings.openrouter_api_key if provider == "openrouter" else None)
    )
    auth_mode = "none" if provider in LOCAL_PROVIDERS and not secret else settings.llm_auth_mode
    return LLMConnection(
        provider=provider,
        display_name=PROVIDER_DEFAULTS[provider]["label"],
        base_url=base_url,
        model=settings.llm_model,
        auth_mode=_normalise_auth_mode(auth_mode),
        api_key=secret,
        enabled=True,
        source="environment",
    )


def get_active_llm_connection() -> LLMConnection:
    try:
        saved = LLMConnectionStore().get()
        if saved is not None and saved.enabled:
            return saved
    except Exception as exc:
        logger.debug("Saved LLM configuration unavailable; using environment: %s", exc)
    return environment_connection()
