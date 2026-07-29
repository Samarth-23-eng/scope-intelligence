from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from openai import OpenAI

from config.settings import settings
from llm_gateway.configuration import LLMConnection


class LLMProviderError(RuntimeError):
    pass


class ChatProvider(ABC):
    def __init__(self, connection: LLMConnection):
        self.connection = connection

    @abstractmethod
    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        raise NotImplementedError


class OpenAICompatibleProvider(ChatProvider):
    def __init__(self, connection: LLMConnection):
        super().__init__(connection)
        self.client = OpenAI(
            base_url=_reachable_base_url(connection.base_url),
            api_key=connection.api_key or "local-no-key-required",
            timeout=settings.llm_request_timeout_seconds,
        )

    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        response = self.client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return response.choices[0].message.content or ""


class AnthropicProvider(ChatProvider):
    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        headers = {
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        if self.connection.auth_mode == "bearer":
            headers["authorization"] = f"Bearer {self.connection.api_key}"
        else:
            headers["x-api-key"] = self.connection.api_key or ""
        response = httpx.post(
            f"{_reachable_base_url(self.connection.base_url).rstrip('/')}/messages",
            headers=headers,
            json={
                "model": model,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            },
            timeout=settings.llm_request_timeout_seconds,
        )
        _raise_provider_error(response)
        payload = response.json()
        return "".join(
            item.get("text", "")
            for item in payload.get("content", [])
            if isinstance(item, dict) and item.get("type") == "text"
        )


class GoogleProvider(ChatProvider):
    def complete(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> str:
        model_id = model.removeprefix("models/")
        url = f"{_reachable_base_url(self.connection.base_url).rstrip('/')}/models/{quote(model_id, safe='')}:generateContent"
        headers = {"content-type": "application/json"}
        params: dict[str, str] = {}
        if self.connection.auth_mode == "bearer":
            headers["authorization"] = f"Bearer {self.connection.api_key}"
        else:
            params["key"] = self.connection.api_key or ""
        response = httpx.post(
            url,
            headers=headers,
            params=params,
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {
                    "temperature": temperature,
                    "maxOutputTokens": max_tokens,
                },
            },
            timeout=settings.llm_request_timeout_seconds,
        )
        _raise_provider_error(response)
        payload = response.json()
        candidates = payload.get("candidates") or []
        if not candidates:
            return ""
        parts = candidates[0].get("content", {}).get("parts", [])
        return "".join(item.get("text", "") for item in parts if isinstance(item, dict))


def _raise_provider_error(response: httpx.Response) -> None:
    if response.is_success:
        return
    try:
        payload: Any = response.json()
        if isinstance(payload, dict):
            detail = payload.get("error") or payload.get("message") or payload.get("detail")
            if isinstance(detail, dict):
                detail = detail.get("message") or json.dumps(detail)
            if detail:
                raise LLMProviderError(
                    f"Provider returned HTTP {response.status_code}: {str(detail)[:500]}"
                )
    except (ValueError, TypeError):
        pass
    raise LLMProviderError(
        f"Provider returned HTTP {response.status_code}: {response.text[:500]}"
    )


def _reachable_base_url(base_url: str) -> str:
    """Route host-local model servers correctly from the Docker API container."""
    if not settings.running_in_docker:
        return base_url
    parsed = urlsplit(base_url)
    if parsed.hostname not in {"localhost", "127.0.0.1"}:
        return base_url
    port = f":{parsed.port}" if parsed.port else ""
    netloc = f"host.docker.internal{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))


def build_provider(connection: LLMConnection) -> ChatProvider:
    if not connection.configured:
        raise LLMProviderError(
            "No working LLM connection is configured. Open Model Connections and add a provider."
        )
    if connection.provider == "anthropic":
        return AnthropicProvider(connection)
    if connection.provider == "google":
        return GoogleProvider(connection)
    return OpenAICompatibleProvider(connection)


def test_provider_connection(connection: LLMConnection) -> dict[str, Any]:
    try:
        provider = build_provider(connection)
        content = provider.complete(
            system_prompt="You are a connection diagnostic. Follow the user instruction exactly.",
            user_prompt='Reply with only this JSON object: {"status":"ok"}',
            model=connection.model,
            temperature=0,
            max_tokens=40,
        )
        if not content.strip():
            raise LLMProviderError("The provider connected but returned an empty response.")
        return {"ok": True, "message": "Connection successful.", "response": content[:200]}
    except LLMProviderError:
        raise
    except Exception as exc:
        raise LLMProviderError(_friendly_provider_error(exc)) from exc


def list_provider_models(connection: LLMConnection) -> list[str]:
    if connection.provider in {"anthropic"}:
        return [connection.model]

    headers: dict[str, str] = {}
    params: dict[str, str] = {}
    if connection.auth_mode == "bearer" and connection.api_key:
        headers["Authorization"] = f"Bearer {connection.api_key}"
    elif connection.provider == "google" and connection.api_key:
        params["key"] = connection.api_key
    elif connection.api_key:
        headers["Authorization"] = f"Bearer {connection.api_key}"

    url = f"{_reachable_base_url(connection.base_url).rstrip('/')}/models"
    try:
        response = httpx.get(
            url,
            headers=headers,
            params=params,
            timeout=min(settings.llm_request_timeout_seconds, 10),
        )
        _raise_provider_error(response)
        payload = response.json()
        items = payload.get("data", payload.get("models", []))
        models = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict):
                continue
            model_id = item.get("id") or item.get("name")
            if isinstance(model_id, str):
                models.append(model_id.removeprefix("models/"))
        return sorted(set(models)) or [connection.model]
    except Exception:
        return [connection.model]


def _friendly_provider_error(exc: Exception) -> str:
    message = str(exc).strip()
    lowered = message.lower()
    if "401" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        return "Authentication failed. Check the API key or access token."
    if "403" in lowered or "forbidden" in lowered:
        return "The provider denied access. Check the key permissions and selected model."
    if "404" in lowered or "not found" in lowered:
        return "The provider or model endpoint was not found. Check the base URL and model ID."
    if "429" in lowered or "rate limit" in lowered:
        return "The provider rate limit or account quota was exceeded."
    if "connection" in lowered or "timed out" in lowered or "timeout" in lowered:
        return "Could not reach the provider. Check the URL, network, and whether the local model server is running."
    return message[:800] or exc.__class__.__name__
