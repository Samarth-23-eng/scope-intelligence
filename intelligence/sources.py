from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SourceDescriptor:
    """Stable identity and policy metadata for one collection adapter."""

    adapter_name: str
    source_key: str
    source_type: str
    capabilities: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


class SourceAdapter(ABC):
    """Common contract implemented by every Phase 1+ collection adapter."""

    @property
    def descriptor(self) -> SourceDescriptor:
        name = self.__class__.__name__.removesuffix("Agent").casefold()
        domain = str(getattr(self, "domain", "") or "")
        return SourceDescriptor(
            adapter_name=name,
            source_key=domain or name,
            source_type="unknown",
            capabilities=("collect",),
        )

    async def discover(self) -> list[dict[str, Any]]:
        """Return newly discovered source descriptors, when supported."""
        return []

    @abstractmethod
    async def collect(self) -> list[dict[str, Any]]:
        """Collect and normalize records from the source."""
        raise NotImplementedError

    async def health_check(self) -> dict[str, Any]:
        """Return a lightweight adapter health description."""
        return {
            "status": "healthy",
            "adapter_name": self.descriptor.adapter_name,
            "source_key": self.descriptor.source_key,
        }
