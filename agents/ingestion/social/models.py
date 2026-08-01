from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


SocialCollectionMode = Literal["discover", "account", "evidence"]


@dataclass(frozen=True)
class SocialCollectionRequest:
    mode: SocialCollectionMode
    target: str
    max_items: int = 10
    include_comments: bool = False
    comment_limit: int = 20
    include_replies: bool = False
    max_reply_depth: int = 1
    include_transcript: bool = False


@dataclass(frozen=True)
class SocialProfileRecord:
    platform: str
    platform_profile_id: str
    profile_url: str
    handle: str | None = None
    display_name: str | None = None
    biography: str | None = None
    follower_count: int | None = None
    following_count: int | None = None
    content_count: int | None = None
    verified: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)
    api_derived: bool = False


@dataclass(frozen=True)
class SocialPostRecord:
    platform: str
    platform_post_id: str
    url: str
    content_type: str = "post"
    title: str | None = None
    body: str | None = None
    author_platform_id: str | None = None
    author_handle: str | None = None
    published_at: str | None = None
    language: str | None = None
    engagement: dict[str, Any] = field(default_factory=dict)
    media: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    api_derived: bool = False


@dataclass(frozen=True)
class SocialCommentRecord:
    platform: str
    platform_comment_id: str
    platform_post_id: str
    text: str
    parent_platform_comment_id: str | None = None
    thread_root_platform_comment_id: str | None = None
    depth: int = 0
    published_at: str | None = None
    like_count: int = 0
    reply_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)
    api_derived: bool = True


@dataclass(frozen=True)
class ConnectorDiagnostic:
    code: str
    message: str
    severity: Literal["info", "warning", "error"] = "warning"
    recoverable: bool = True
    suggested_action: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class SocialCollectionBatch:
    profiles: list[SocialProfileRecord] = field(default_factory=list)
    posts: list[SocialPostRecord] = field(default_factory=list)
    comments: list[SocialCommentRecord] = field(default_factory=list)
    diagnostics: list[ConnectorDiagnostic] = field(default_factory=list)
    checkpoint: dict[str, Any] = field(default_factory=dict)

    @property
    def item_count(self) -> int:
        return len(self.profiles) + len(self.posts) + len(self.comments)
