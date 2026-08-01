from __future__ import annotations

import asyncio
import html
import re
from typing import Any
from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree

import httpx

from agents.ingestion.social.base import (
    CancelCallback,
    ProgressCallback,
    SocialConnector,
    SocialConnectorDescriptor,
    SocialConnectorError,
)
from agents.ingestion.social.models import (
    ConnectorDiagnostic,
    SocialCollectionBatch,
    SocialCollectionRequest,
    SocialCommentRecord,
    SocialPostRecord,
    SocialProfileRecord,
)


class YouTubeSocialConnector(SocialConnector):
    API_BASE = "https://www.googleapis.com/youtube/v3"
    FEED_URL = "https://www.youtube.com/feeds/videos.xml"
    OEMBED_URL = "https://www.youtube.com/oembed"
    ALLOWED_HOSTS = {
        "youtube.com",
        "www.youtube.com",
        "m.youtube.com",
        "music.youtube.com",
        "youtu.be",
    }
    CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{20,30}$")
    VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
    HANDLE_RE = re.compile(r"^@[A-Za-z0-9._-]{2,100}$")

    def __init__(
        self,
        *,
        api_key: str | None,
        request_timeout: float = 20.0,
        request_delay: float = 0.0,
    ):
        self.api_key = (api_key or "").strip() or None
        self.request_timeout = max(float(request_timeout), 5.0)
        self.request_delay = max(float(request_delay), 0.0)

    @property
    def descriptor(self) -> SocialConnectorDescriptor:
        warnings = (
            (
                "Keyword discovery, engagement metrics and comments need a "
                "YouTube Data API key."
            ),
            "Transcripts use an optional experimental public transcript provider.",
            "Commenter identities are intentionally not retained.",
        )
        return SocialConnectorDescriptor(
            platform="youtube",
            label="YouTube",
            version="1",
            capabilities=(
                "public_channel_feed",
                "direct_video_capture",
                "keyword_discovery",
                "engagement_snapshots",
                "threaded_comments",
                "optional_transcripts",
            ),
            modes=("discover", "account", "evidence"),
            public_access=True,
            api_key_configured=bool(self.api_key),
            comments_require_api_key=True,
            warnings=warnings,
        )

    def validate(self, request: SocialCollectionRequest) -> None:
        if request.mode not in {"discover", "account", "evidence"}:
            raise SocialConnectorError(
                "unsupported_mode",
                "Choose Discover, Account Monitor, or Evidence Capture.",
                recoverable=False,
            )
        target = (request.target or "").strip()
        if not target:
            raise SocialConnectorError(
                "target_required",
                "Enter a search query, channel, or video URL.",
                recoverable=True,
            )
        if not 1 <= request.max_items <= 50:
            raise SocialConnectorError(
                "invalid_item_budget",
                "Item budget must be between 1 and 50.",
                recoverable=True,
            )
        if not 0 <= request.comment_limit <= 200:
            raise SocialConnectorError(
                "invalid_comment_budget",
                "Comment budget must be between 0 and 200 per collected video.",
                recoverable=True,
            )
        if not 0 <= request.max_reply_depth <= 1:
            raise SocialConnectorError(
                "invalid_reply_depth",
                "YouTube currently supports one reply level.",
                recoverable=True,
            )

        if request.mode == "discover":
            if self._looks_like_url(target):
                self._parse_target(target)
            elif len(target) > 500:
                raise SocialConnectorError(
                    "query_too_long",
                    "Discovery queries must be 500 characters or fewer.",
                )
            if (
                not self.api_key
                and self._target_kind(target, allow_bare_video=False)[0] == "query"
            ):
                raise SocialConnectorError(
                    "youtube_api_key_required",
                    "Keyword discovery requires a YouTube Data API key.",
                    suggested_action=(
                        "Add YOUTUBE_API_KEY to your local environment, or use "
                        "Account Monitor with a channel URL."
                    ),
                )
        elif request.mode == "account":
            kind, _, _ = self._target_kind(
                target,
                allow_bare_handle=True,
                allow_bare_video=False,
            )
            if kind not in {"channel", "handle"}:
                raise SocialConnectorError(
                    "invalid_youtube_channel",
                    "Account Monitor needs a YouTube channel URL, channel ID, or @handle.",
                    suggested_action="Paste a URL such as https://www.youtube.com/@OpenAI.",
                )
        else:
            kind, _, _ = self._target_kind(target)
            if kind != "video":
                raise SocialConnectorError(
                    "invalid_youtube_video",
                    "Evidence Capture needs a YouTube video URL or video ID.",
                    suggested_action="Paste a youtube.com/watch or youtu.be URL.",
                )

        if request.include_comments and not self.api_key:
            raise SocialConnectorError(
                "youtube_api_key_required",
                "YouTube comments require a YouTube Data API key.",
                suggested_action=(
                    "Configure YOUTUBE_API_KEY locally, or turn off comment collection."
                ),
            )

    async def collect(
        self,
        request: SocialCollectionRequest,
        *,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> SocialCollectionBatch:
        self.validate(request)
        await progress("connector_started", {"platform": "youtube", "mode": request.mode})
        self.check_cancelled(cancelled)

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126.0 Safari/537.36 "
                "ScopeIntelligence/1.0"
            ),
            "Accept-Language": "en-US,en;q=0.8",
        }
        try:
            async with httpx.AsyncClient(
                timeout=self.request_timeout,
                headers=headers,
                follow_redirects=False,
            ) as client:
                if request.mode == "discover":
                    batch = await self._discover(
                        client, request, progress=progress, cancelled=cancelled
                    )
                elif request.mode == "account":
                    batch = await self._collect_account(
                        client, request, progress=progress, cancelled=cancelled
                    )
                else:
                    batch = await self._capture_video(
                        client, request, progress=progress, cancelled=cancelled
                    )
        except httpx.TimeoutException:
            raise SocialConnectorError(
                "youtube_request_timeout",
                "YouTube did not respond within the connector time limit.",
                suggested_action="Retry later or reduce the collection budget.",
            ) from None
        except httpx.RequestError:
            raise SocialConnectorError(
                "youtube_network_error",
                "Scope could not reach YouTube from this computer.",
                suggested_action="Check the network connection and retry.",
            ) from None
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            raise SocialConnectorError(
                "youtube_public_fetch_blocked",
                "YouTube blocked or rejected a public metadata request.",
                suggested_action=(
                    "Retry later, use a canonical public URL, or configure a "
                    "YouTube Data API key."
                ),
                http_status=status_code,
            ) from None

        await progress(
            "connector_completed",
            {
                "profiles": len(batch.profiles),
                "posts": len(batch.posts),
                "comments": len(batch.comments),
                "diagnostics": len(batch.diagnostics),
            },
        )
        return batch

    async def _discover(
        self,
        client: httpx.AsyncClient,
        request: SocialCollectionRequest,
        *,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> SocialCollectionBatch:
        kind, _, _ = self._target_kind(
            request.target,
            allow_bare_video=False,
        )
        if kind in {"channel", "handle"}:
            fallback = SocialCollectionRequest(
                mode="account",
                target=request.target,
                max_items=request.max_items,
                include_comments=request.include_comments,
                comment_limit=request.comment_limit,
                include_replies=request.include_replies,
                max_reply_depth=request.max_reply_depth,
                include_transcript=request.include_transcript,
            )
            batch = await self._collect_account(
                client, fallback, progress=progress, cancelled=cancelled
            )
            batch.diagnostics.append(
                ConnectorDiagnostic(
                    code="direct_target_discovery",
                    message="The discovery target was a channel, so Scope monitored it directly.",
                    severity="info",
                )
            )
            return batch
        if kind == "video":
            fallback = SocialCollectionRequest(
                mode="evidence",
                target=request.target,
                max_items=1,
                include_comments=request.include_comments,
                comment_limit=request.comment_limit,
                include_replies=request.include_replies,
                max_reply_depth=request.max_reply_depth,
                include_transcript=request.include_transcript,
            )
            return await self._capture_video(
                client, fallback, progress=progress, cancelled=cancelled
            )

        await progress("searching", {"query": request.target})
        response = await self._api_get(
            client,
            "search",
            {
                "part": "snippet",
                "type": "video",
                "q": request.target,
                "maxResults": min(request.max_items, 50),
            },
        )
        items = response.get("items") or []
        video_ids = [
            str(item.get("id", {}).get("videoId") or "")
            for item in items
        ]
        video_ids = [video_id for video_id in video_ids if self.VIDEO_ID_RE.fullmatch(video_id)]
        details = await self._video_details(client, video_ids)
        batch = SocialCollectionBatch(checkpoint={"search_complete": True})
        profiles: dict[str, SocialProfileRecord] = {}
        for index, video_id in enumerate(video_ids):
            self.check_cancelled(cancelled)
            item = details.get(video_id) or {}
            post = await self._video_record(
                video_id,
                item,
                request=request,
                api_derived=True,
            )
            batch.posts.append(post)
            channel_id = str((item.get("snippet") or {}).get("channelId") or "")
            if channel_id and channel_id not in profiles:
                snippet = item.get("snippet") or {}
                profiles[channel_id] = SocialProfileRecord(
                    platform="youtube",
                    platform_profile_id=channel_id,
                    profile_url=f"https://www.youtube.com/channel/{channel_id}",
                    display_name=str(snippet.get("channelTitle") or "") or None,
                    api_derived=True,
                    metadata={"source": "youtube_data_api"},
                )
            await progress(
                "post_collected",
                {"current": index + 1, "total": len(video_ids), "video_id": video_id},
            )
            await self._append_comments(
                client,
                batch,
                post,
                request,
                progress=progress,
                cancelled=cancelled,
            )
        batch.profiles.extend(profiles.values())
        return batch

    async def _collect_account(
        self,
        client: httpx.AsyncClient,
        request: SocialCollectionRequest,
        *,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> SocialCollectionBatch:
        kind, target_value, canonical_url = self._target_kind(
            request.target,
            allow_bare_handle=True,
            allow_bare_video=False,
        )
        self.check_cancelled(cancelled)
        await progress("resolving_channel", {"target": canonical_url})

        channel = None
        channel_id = target_value if kind == "channel" else ""
        if self.api_key:
            channel = await self._resolve_channel_api(client, kind, target_value)
            if channel:
                channel_id = str(channel.get("id") or channel_id)
        if not channel_id:
            channel_id = await self._resolve_channel_public(client, canonical_url)
        if not self.CHANNEL_ID_RE.fullmatch(channel_id):
            raise SocialConnectorError(
                "youtube_channel_not_found",
                "Scope could not resolve that YouTube channel.",
                suggested_action=(
                    "Use the channel’s full /channel/UC… URL or configure a "
                    "YouTube Data API key for handle resolution."
                ),
                http_status=404,
            )

        feed_items, feed_title = await self._channel_feed(client, channel_id)
        feed_items = feed_items[: request.max_items]
        details = (
            await self._video_details(
                client,
                [str(item["video_id"]) for item in feed_items],
            )
            if self.api_key
            else {}
        )
        profile = self._profile_record(
            channel_id,
            channel,
            canonical_url=(
                f"https://www.youtube.com/channel/{channel_id}"
                if kind == "channel"
                else canonical_url
            ),
            fallback_title=feed_title,
        )
        batch = SocialCollectionBatch(
            profiles=[profile],
            checkpoint={"channel_id": channel_id, "feed_complete": True},
        )
        await progress(
            "channel_resolved",
            {"channel_id": channel_id, "videos_found": len(feed_items)},
        )

        for index, feed_item in enumerate(feed_items):
            self.check_cancelled(cancelled)
            video_id = str(feed_item["video_id"])
            item = details.get(video_id) or {
                "snippet": {
                    "title": feed_item.get("title"),
                    "channelId": channel_id,
                    "channelTitle": feed_item.get("channel_title") or feed_title,
                    "publishedAt": feed_item.get("published_at"),
                    "description": "",
                }
            }
            post = await self._video_record(
                video_id,
                item,
                request=request,
                api_derived=bool(details),
            )
            batch.posts.append(post)
            await progress(
                "post_collected",
                {"current": index + 1, "total": len(feed_items), "video_id": video_id},
            )
            await self._append_comments(
                client,
                batch,
                post,
                request,
                progress=progress,
                cancelled=cancelled,
            )
        return batch

    async def _capture_video(
        self,
        client: httpx.AsyncClient,
        request: SocialCollectionRequest,
        *,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> SocialCollectionBatch:
        _, video_id, _ = self._target_kind(request.target)
        self.check_cancelled(cancelled)
        await progress("resolving_video", {"video_id": video_id})
        details = await self._video_details(client, [video_id]) if self.api_key else {}
        item = details.get(video_id)
        api_derived = bool(item)
        if not item:
            item = await self._video_oembed(client, video_id)
        if not item:
            raise SocialConnectorError(
                "youtube_video_not_found",
                "The YouTube video could not be found or is not publicly accessible.",
                http_status=404,
                suggested_action="Check the URL and confirm the video is public.",
            )
        post = await self._video_record(
            video_id,
            item,
            request=request,
            api_derived=api_derived,
        )
        channel_id = str((item.get("snippet") or {}).get("channelId") or "")
        channel_title = str((item.get("snippet") or {}).get("channelTitle") or "")
        profiles = []
        if channel_id:
            profiles.append(
                SocialProfileRecord(
                    platform="youtube",
                    platform_profile_id=channel_id,
                    profile_url=f"https://www.youtube.com/channel/{channel_id}",
                    display_name=channel_title or None,
                    api_derived=api_derived,
                    metadata={"source": "youtube_data_api" if api_derived else "youtube_oembed"},
                )
            )
        batch = SocialCollectionBatch(
            profiles=profiles,
            posts=[post],
            checkpoint={"video_id": video_id, "capture_complete": True},
        )
        await progress("post_collected", {"current": 1, "total": 1, "video_id": video_id})
        await self._append_comments(
            client,
            batch,
            post,
            request,
            progress=progress,
            cancelled=cancelled,
        )
        return batch

    async def _append_comments(
        self,
        client: httpx.AsyncClient,
        batch: SocialCollectionBatch,
        post: SocialPostRecord,
        request: SocialCollectionRequest,
        *,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> None:
        if not request.include_comments or request.comment_limit <= 0:
            return
        try:
            comments = await self._comments(
                client,
                post.platform_post_id,
                limit=request.comment_limit,
                include_replies=request.include_replies,
                progress=progress,
                cancelled=cancelled,
            )
            batch.comments.extend(comments)
        except SocialConnectorError as exc:
            if exc.code in {
                "youtube_comments_disabled",
                "youtube_comments_unavailable",
            }:
                batch.diagnostics.append(exc.diagnostic())
                return
            raise

    async def _comments(
        self,
        client: httpx.AsyncClient,
        video_id: str,
        *,
        limit: int,
        include_replies: bool,
        progress: ProgressCallback,
        cancelled: CancelCallback,
    ) -> list[SocialCommentRecord]:
        comments: list[SocialCommentRecord] = []
        seen_ids: set[str] = set()
        seen_tokens: set[str] = set()
        page_token: str | None = None
        while len(comments) < limit:
            self.check_cancelled(cancelled)
            params: dict[str, Any] = {
                "part": "snippet,replies",
                "videoId": video_id,
                "maxResults": min(100, max(limit - len(comments), 1)),
                "order": "relevance",
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = await self._api_get(client, "commentThreads", params)
            items = payload.get("items") or []
            for item in items:
                if len(comments) >= limit:
                    break
                top = (item.get("snippet") or {}).get("topLevelComment") or {}
                top_id = str(top.get("id") or "")
                top_snippet = top.get("snippet") or {}
                if not top_id or top_id in seen_ids:
                    continue
                text = self._plain_text(top_snippet.get("textDisplay"))
                if not text:
                    continue
                seen_ids.add(top_id)
                total_replies = int((item.get("snippet") or {}).get("totalReplyCount") or 0)
                comments.append(
                    SocialCommentRecord(
                        platform="youtube",
                        platform_comment_id=top_id,
                        platform_post_id=video_id,
                        text=text,
                        depth=0,
                        published_at=top_snippet.get("publishedAt"),
                        like_count=int(top_snippet.get("likeCount") or 0),
                        reply_count=total_replies,
                        metadata={"source": "youtube_data_api", "identity_retained": False},
                    )
                )
                if include_replies and len(comments) < limit and total_replies:
                    included = (item.get("replies") or {}).get("comments") or []
                    self._append_reply_records(
                        comments,
                        included,
                        video_id=video_id,
                        root_id=top_id,
                        limit=limit,
                        seen_ids=seen_ids,
                    )
                    if len(included) < total_replies and len(comments) < limit:
                        await self._fetch_remaining_replies(
                            client,
                            comments,
                            video_id=video_id,
                            root_id=top_id,
                            limit=limit,
                            seen_ids=seen_ids,
                            cancelled=cancelled,
                        )
            await progress(
                "comments_page_collected",
                {
                    "video_id": video_id,
                    "comments": len(comments),
                    "budget": limit,
                },
            )
            next_token = str(payload.get("nextPageToken") or "")
            if not next_token or next_token in seen_tokens:
                break
            seen_tokens.add(next_token)
            page_token = next_token
        return comments[:limit]

    async def _fetch_remaining_replies(
        self,
        client: httpx.AsyncClient,
        comments: list[SocialCommentRecord],
        *,
        video_id: str,
        root_id: str,
        limit: int,
        seen_ids: set[str],
        cancelled: CancelCallback,
    ) -> None:
        page_token: str | None = None
        seen_tokens: set[str] = set()
        while len(comments) < limit:
            self.check_cancelled(cancelled)
            params: dict[str, Any] = {
                "part": "snippet",
                "parentId": root_id,
                "maxResults": min(100, max(limit - len(comments), 1)),
                "textFormat": "plainText",
            }
            if page_token:
                params["pageToken"] = page_token
            payload = await self._api_get(client, "comments", params)
            self._append_reply_records(
                comments,
                payload.get("items") or [],
                video_id=video_id,
                root_id=root_id,
                limit=limit,
                seen_ids=seen_ids,
            )
            next_token = str(payload.get("nextPageToken") or "")
            if not next_token or next_token in seen_tokens:
                break
            seen_tokens.add(next_token)
            page_token = next_token

    @staticmethod
    def _append_reply_records(
        comments: list[SocialCommentRecord],
        items: list[dict[str, Any]],
        *,
        video_id: str,
        root_id: str,
        limit: int,
        seen_ids: set[str],
    ) -> None:
        for reply in items:
            if len(comments) >= limit:
                return
            reply_id = str(reply.get("id") or "")
            snippet = reply.get("snippet") or {}
            text = YouTubeSocialConnector._plain_text(snippet.get("textDisplay"))
            if not reply_id or reply_id in seen_ids or not text:
                continue
            seen_ids.add(reply_id)
            comments.append(
                SocialCommentRecord(
                    platform="youtube",
                    platform_comment_id=reply_id,
                    platform_post_id=video_id,
                    parent_platform_comment_id=root_id,
                    thread_root_platform_comment_id=root_id,
                    text=text,
                    depth=1,
                    published_at=snippet.get("publishedAt"),
                    like_count=int(snippet.get("likeCount") or 0),
                    metadata={"source": "youtube_data_api", "identity_retained": False},
                )
            )

    async def _resolve_channel_api(
        self,
        client: httpx.AsyncClient,
        kind: str,
        value: str,
    ) -> dict[str, Any] | None:
        params: dict[str, Any] = {"part": "snippet,contentDetails,statistics"}
        if kind == "channel":
            params["id"] = value
        else:
            params["forHandle"] = value.lstrip("@")
        payload = await self._api_get(client, "channels", params)
        items = payload.get("items") or []
        return items[0] if items else None

    async def _resolve_channel_public(
        self,
        client: httpx.AsyncClient,
        canonical_url: str,
    ) -> str:
        response = await client.get(canonical_url)
        if 300 <= response.status_code < 400:
            location = response.headers.get("location") or ""
            _, _, safe_location = self._parse_target(location)
            response = await client.get(safe_location)
        if response.status_code == 404:
            return ""
        response.raise_for_status()
        patterns = (
            r'"externalId":"(UC[A-Za-z0-9_-]{20,30})"',
            r'"channelId":"(UC[A-Za-z0-9_-]{20,30})"',
            r"/channel/(UC[A-Za-z0-9_-]{20,30})",
        )
        for pattern in patterns:
            match = re.search(pattern, response.text)
            if match:
                return match.group(1)
        return ""

    async def _channel_feed(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
    ) -> tuple[list[dict[str, Any]], str]:
        response = await client.get(self.FEED_URL, params={"channel_id": channel_id})
        if response.status_code == 404:
            raise SocialConnectorError(
                "youtube_channel_not_found",
                "The YouTube channel feed was not found.",
                http_status=404,
            )
        response.raise_for_status()
        try:
            root = ElementTree.fromstring(response.content)
        except ElementTree.ParseError as exc:
            raise SocialConnectorError(
                "youtube_feed_invalid",
                "YouTube returned an unreadable channel feed.",
                suggested_action="Retry later or configure a YouTube Data API key.",
            ) from exc
        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }
        feed_title = root.findtext("atom:title", default="", namespaces=namespace)
        videos = []
        for entry in root.findall("atom:entry", namespace):
            video_id = entry.findtext("yt:videoId", default="", namespaces=namespace)
            if not self.VIDEO_ID_RE.fullmatch(video_id):
                continue
            videos.append(
                {
                    "video_id": video_id,
                    "title": entry.findtext("atom:title", default="", namespaces=namespace),
                    "channel_title": entry.findtext(
                        "atom:author/atom:name",
                        default="",
                        namespaces=namespace,
                    ),
                    "published_at": entry.findtext(
                        "atom:published",
                        default="",
                        namespaces=namespace,
                    ),
                }
            )
        return videos, feed_title

    async def _video_details(
        self,
        client: httpx.AsyncClient,
        video_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        valid = [value for value in dict.fromkeys(video_ids) if self.VIDEO_ID_RE.fullmatch(value)]
        if not valid:
            return {}
        payload = await self._api_get(
            client,
            "videos",
            {
                "part": "snippet,contentDetails,statistics,status",
                "id": ",".join(valid[:50]),
            },
        )
        return {
            str(item.get("id")): item
            for item in payload.get("items") or []
            if item.get("id")
        }

    async def _video_oembed(
        self,
        client: httpx.AsyncClient,
        video_id: str,
    ) -> dict[str, Any] | None:
        url = f"https://www.youtube.com/watch?v={video_id}"
        response = await client.get(self.OEMBED_URL, params={"url": url, "format": "json"})
        if response.status_code == 404:
            return None
        response.raise_for_status()
        value = response.json()
        return {
            "id": video_id,
            "snippet": {
                "title": value.get("title"),
                "description": "",
                "channelTitle": value.get("author_name"),
                "channelId": "",
                "publishedAt": None,
                "thumbnails": {
                    "default": {
                        "url": value.get("thumbnail_url"),
                        "width": value.get("thumbnail_width"),
                        "height": value.get("thumbnail_height"),
                    }
                },
            },
            "statistics": {},
            "_oembed": True,
        }

    async def _video_record(
        self,
        video_id: str,
        item: dict[str, Any],
        *,
        request: SocialCollectionRequest,
        api_derived: bool,
    ) -> SocialPostRecord:
        snippet = item.get("snippet") or {}
        description = str(snippet.get("description") or "").strip()
        transcript = ""
        transcript_error = None
        if request.include_transcript:
            try:
                transcript = await self._transcript(video_id)
            except Exception as exc:
                transcript_error = type(exc).__name__
        body_parts = [description]
        if transcript:
            body_parts.append(f"Transcript:\n{transcript}")
        thumbnails = snippet.get("thumbnails") or {}
        media = [
            {
                "type": "thumbnail",
                "url": value.get("url"),
                "width": value.get("width"),
                "height": value.get("height"),
            }
            for value in thumbnails.values()
            if isinstance(value, dict) and value.get("url")
        ]
        metadata = {
            "source": "youtube_data_api" if api_derived else "youtube_public",
            "channel_title": snippet.get("channelTitle"),
            "duration": (item.get("contentDetails") or {}).get("duration"),
            "privacy_status": (item.get("status") or {}).get("privacyStatus"),
            "transcript_requested": request.include_transcript,
            "transcript_captured": bool(transcript),
            "transcript_provider": "experimental_public" if transcript else None,
        }
        if transcript_error:
            metadata["transcript_error"] = transcript_error
        return SocialPostRecord(
            platform="youtube",
            platform_post_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            content_type="video",
            title=str(snippet.get("title") or "YouTube video"),
            body="\n\n".join(part for part in body_parts if part).strip(),
            author_platform_id=str(snippet.get("channelId") or "") or None,
            published_at=snippet.get("publishedAt"),
            engagement={
                key: self._integer(value)
                for key, value in (item.get("statistics") or {}).items()
                if key in {"viewCount", "likeCount", "commentCount", "favoriteCount"}
            },
            media=media,
            metadata=metadata,
            api_derived=api_derived,
        )

    def _profile_record(
        self,
        channel_id: str,
        channel: dict[str, Any] | None,
        *,
        canonical_url: str,
        fallback_title: str,
    ) -> SocialProfileRecord:
        snippet = (channel or {}).get("snippet") or {}
        statistics = (channel or {}).get("statistics") or {}
        return SocialProfileRecord(
            platform="youtube",
            platform_profile_id=channel_id,
            profile_url=canonical_url,
            handle=None,
            display_name=str(snippet.get("title") or fallback_title or "") or None,
            biography=str(snippet.get("description") or "") or None,
            follower_count=self._optional_integer(statistics.get("subscriberCount")),
            content_count=self._optional_integer(statistics.get("videoCount")),
            verified=False,
            api_derived=bool(channel),
            metadata={
                "source": "youtube_data_api" if channel else "youtube_atom_feed",
                "view_count": self._optional_integer(statistics.get("viewCount")),
            },
        )

    async def _api_get(
        self,
        client: httpx.AsyncClient,
        resource: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        if not self.api_key:
            raise SocialConnectorError(
                "youtube_api_key_required",
                "This YouTube capability requires a Data API key.",
                suggested_action="Configure YOUTUBE_API_KEY locally.",
            )
        if self.request_delay:
            await asyncio.sleep(self.request_delay)
        response = await client.get(
            f"{self.API_BASE}/{resource}",
            params={**params, "key": self.api_key},
        )
        if response.status_code < 400:
            try:
                value = response.json()
            except ValueError:
                raise SocialConnectorError(
                    "youtube_response_invalid",
                    "YouTube returned an unreadable API response.",
                    suggested_action="Retry later and review the connector diagnostics.",
                ) from None
            return value if isinstance(value, dict) else {}
        reason = ""
        try:
            errors = (response.json().get("error") or {}).get("errors") or []
            reason = str((errors[0] if errors else {}).get("reason") or "")
        except (TypeError, ValueError):
            reason = ""
        if response.status_code == 404:
            code = "youtube_target_not_found"
            message = "YouTube could not find the requested resource."
        elif response.status_code == 429 or reason in {"quotaExceeded", "dailyLimitExceeded"}:
            code = "youtube_quota_exhausted"
            message = "The configured YouTube API quota has been exhausted."
        elif reason == "commentsDisabled":
            code = "youtube_comments_disabled"
            message = "Comments are disabled for this YouTube video."
        elif response.status_code in {401, 403}:
            code = "youtube_access_denied"
            message = "YouTube rejected the configured API credentials or access policy."
        elif response.status_code == 400:
            code = "youtube_request_invalid"
            message = "YouTube rejected the collection request."
        else:
            code = "youtube_api_error"
            message = "YouTube returned an unexpected collection error."
        raise SocialConnectorError(
            code,
            message,
            recoverable=code not in {"youtube_comments_disabled"},
            suggested_action=(
                "Check the YouTube API key, quota and API restrictions, then retry."
                if code != "youtube_comments_disabled"
                else "Continue without comments for this video."
            ),
            http_status=response.status_code,
            metadata={"provider_reason": reason or None},
        )

    async def _transcript(self, video_id: str) -> str:
        def fetch() -> str:
            from youtube_transcript_api import YouTubeTranscriptApi

            transcript = YouTubeTranscriptApi().fetch(video_id)
            return " ".join(
                str(snippet.text).strip()
                for snippet in transcript
                if str(snippet.text).strip()
            )

        return await asyncio.wait_for(asyncio.to_thread(fetch), timeout=30)

    def _target_kind(
        self,
        target: str,
        *,
        allow_bare_handle: bool = False,
        allow_bare_video: bool = True,
    ) -> tuple[str, str, str]:
        value = (target or "").strip()
        if self._looks_like_url(value):
            return self._parse_target(value)
        if self.CHANNEL_ID_RE.fullmatch(value):
            return "channel", value, f"https://www.youtube.com/channel/{value}"
        if self.HANDLE_RE.fullmatch(value):
            return "handle", value, f"https://www.youtube.com/{value}"
        if allow_bare_video and self.VIDEO_ID_RE.fullmatch(value):
            return "video", value, f"https://www.youtube.com/watch?v={value}"
        if allow_bare_handle and re.fullmatch(r"[A-Za-z0-9._-]{2,100}", value):
            handle = f"@{value}"
            return "handle", handle, f"https://www.youtube.com/{handle}"
        return "query", value, ""

    def _parse_target(self, target: str) -> tuple[str, str, str]:
        normalized = target.strip()
        if "://" not in normalized:
            normalized = f"https://{normalized}"
        parsed = urlsplit(normalized)
        if parsed.scheme.casefold() not in {"http", "https"}:
            raise self._unsafe_target()
        if parsed.username or parsed.password or parsed.port is not None:
            raise self._unsafe_target()
        host = (parsed.hostname or "").casefold().rstrip(".")
        if host not in self.ALLOWED_HOSTS:
            raise self._unsafe_target()
        parts = [part for part in parsed.path.split("/") if part]
        if host == "youtu.be" and parts and self.VIDEO_ID_RE.fullmatch(parts[0]):
            video_id = parts[0]
            return "video", video_id, f"https://www.youtube.com/watch?v={video_id}"
        if parts[:1] == ["watch"]:
            video_id = str((parse_qs(parsed.query).get("v") or [""])[0])
            if self.VIDEO_ID_RE.fullmatch(video_id):
                return "video", video_id, f"https://www.youtube.com/watch?v={video_id}"
        if len(parts) >= 2 and parts[0] in {"shorts", "live", "embed"}:
            if self.VIDEO_ID_RE.fullmatch(parts[1]):
                video_id = parts[1]
                return "video", video_id, f"https://www.youtube.com/watch?v={video_id}"
        if len(parts) >= 2 and parts[0] == "channel":
            if self.CHANNEL_ID_RE.fullmatch(parts[1]):
                channel_id = parts[1]
                return (
                    "channel",
                    channel_id,
                    f"https://www.youtube.com/channel/{channel_id}",
                )
        if parts and self.HANDLE_RE.fullmatch(parts[0]):
            handle = parts[0]
            return "handle", handle, f"https://www.youtube.com/{handle}"
        raise SocialConnectorError(
            "unsupported_youtube_url",
            "That YouTube URL is not a supported channel or video address.",
            suggested_action="Use a /channel/UC…, /@handle, /watch, /shorts, or youtu.be URL.",
        )

    @staticmethod
    def _looks_like_url(value: str) -> bool:
        return "://" in value or value.casefold().startswith(
            ("www.youtube.com/", "youtube.com/", "youtu.be/")
        )

    @staticmethod
    def _unsafe_target() -> SocialConnectorError:
        return SocialConnectorError(
            "unsafe_social_target",
            "Only canonical public YouTube URLs are accepted.",
            recoverable=False,
            suggested_action="Remove credentials, custom ports, redirects, or non-YouTube hosts.",
        )

    @staticmethod
    def _plain_text(value: object) -> str:
        return re.sub(r"\s+", " ", html.unescape(str(value or ""))).strip()

    @staticmethod
    def _integer(value: object) -> int:
        try:
            return max(int(value or 0), 0)
        except (TypeError, ValueError):
            return 0

    @classmethod
    def _optional_integer(cls, value: object) -> int | None:
        if value in {None, ""}:
            return None
        return cls._integer(value)
