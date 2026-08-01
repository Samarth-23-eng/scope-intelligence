from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from agents.ingestion.social.models import (
    ConnectorDiagnostic,
    SocialCollectionBatch,
    SocialCollectionRequest,
)


ProgressCallback = Callable[[str, dict[str, Any]], Awaitable[None]]
CancelCallback = Callable[[], bool]


@dataclass(frozen=True)
class SocialConnectorDescriptor:
    platform: str
    label: str
    version: str
    capabilities: tuple[str, ...]
    modes: tuple[str, ...]
    public_access: bool
    api_key_configured: bool
    comments_require_api_key: bool
    warnings: tuple[str, ...] = ()


class SocialConnectorError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        recoverable: bool = True,
        suggested_action: str | None = None,
        http_status: int | None = None,
        metadata: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.suggested_action = suggested_action
        self.http_status = http_status
        self.metadata = metadata or {}

    def diagnostic(self) -> ConnectorDiagnostic:
        return ConnectorDiagnostic(
            code=self.code,
            message=self.message,
            severity="error",
            recoverable=self.recoverable,
            suggested_action=self.suggested_action,
            metadata=self.metadata,
        )


class SocialConnector(ABC):
    @property
    @abstractmethod
    def descriptor(self) -> SocialConnectorDescriptor:
        raise NotImplementedError

    @abstractmethod
    def validate(self, request: SocialCollectionRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    async def collect(
        self,
        request: SocialCollectionRequest,
        *,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> SocialCollectionBatch:
        raise NotImplementedError

    @staticmethod
    def check_cancelled(cancelled: CancelCallback) -> None:
        if cancelled():
            raise SocialConnectorError(
                "collection_cancelled",
                "Collection was cancelled by the operator.",
                recoverable=True,
            )
