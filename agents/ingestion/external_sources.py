from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree

import httpx

from agents.ingestion.base import BaseIngestionAgent
from config.settings import settings
from intelligence.collection import CollectionCampaignStore, SourceProfileStore

logger = logging.getLogger(__name__)


class ExternalSourceAgent(BaseIngestionAgent):
    """Bounded collectors for first-party-confirmed public platform profiles."""

    YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
    GITHUB_API = "https://api.github.com"

    def __init__(self, competitor_id: int, competitor_name: str, domain: str):
        super().__init__(competitor_id, competitor_name, domain)
        self.registry = SourceProfileStore(competitor_id)
        self.campaign: CollectionCampaignStore | None = None
        self.last_run_stats: dict[str, Any] = {
            "profiles": 0,
            "youtube": {
                "channels": 0,
                "videos": 0,
                "transcripts": 0,
                "comment_documents": 0,
                "comments": 0,
                "errors": [],
            },
            "github": {
                "profiles": 0,
                "repositories": 0,
                "releases": 0,
                "errors": [],
            },
        }

    async def collect(self) -> list[dict[str, Any]]:
        if self.run_id is not None:
            self.campaign = CollectionCampaignStore(
                self.competitor_id,
                run_id=self.run_id,
                campaign_type="external",
            )
            self.campaign.start(
                strategy="isolated_public_adapters",
                budget={
                    "youtube_videos": settings.youtube_max_videos,
                    "youtube_comments_per_video": settings.youtube_comments_per_video,
                    "github_repositories": settings.github_max_repositories,
                },
            )
        self.registry.bootstrap_competitor_profiles()
        profiles = self.registry.list_active(("youtube", "github"))
        self.last_run_stats["profiles"] = len(profiles)
        if not profiles:
            if self.campaign:
                self.campaign.finish(status="completed", statistics=self.last_run_stats)
            return []

        headers = {"User-Agent": "OSINTPlatform/4.0"}
        async with httpx.AsyncClient(
            timeout=max(settings.crawler_request_timeout_seconds, 10.0),
            follow_redirects=True,
            headers=headers,
        ) as client:
            outcomes = await asyncio.gather(
                *(self._collect_profile(client, profile) for profile in profiles),
                return_exceptions=True,
            )

        collected: list[dict[str, Any]] = []
        for profile, outcome in zip(profiles, outcomes):
            source_type = profile["source_type"]
            if isinstance(outcome, Exception):
                message = str(outcome)[:500]
                self.last_run_stats[source_type]["errors"].append(message)
                self.registry.mark_collected(
                    int(profile["id"]),
                    success=False,
                    metadata={"last_error": message},
                )
                continue
            collected.extend(outcome)
            self.registry.mark_collected(
                int(profile["id"]),
                success=True,
                metadata={"last_items": len(outcome)},
            )
        if self.campaign:
            error_count = sum(
                len(self.last_run_stats[key]["errors"])
                for key in ("youtube", "github")
            )
            self.campaign.event(
                adapter_name="external_sources",
                event_type="campaign_completed",
                success=error_count == 0,
                items=len(collected),
                metadata=self.last_run_stats,
            )
            self.campaign.finish(
                status="partial" if error_count else "completed",
                statistics=self.last_run_stats,
            )
        return collected

    async def _collect_profile(
        self,
        client: httpx.AsyncClient,
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        source_type = profile["source_type"]
        if source_type == "youtube":
            return await self._collect_youtube(client, profile)
        if source_type == "github":
            return await self._collect_github(client, profile)
        return []

    async def _collect_youtube(
        self,
        client: httpx.AsyncClient,
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        channel_key = str(profile.get("profile_key") or "").strip()
        channel_id = channel_key if channel_key.startswith("UC") else ""
        channel: dict[str, Any] | None = None

        if settings.youtube_api_key:
            channel = await self._youtube_channel(client, channel_key)
            if channel:
                channel_id = str(channel.get("id") or channel_id)
        if not channel_id:
            channel_id = await self._channel_id_from_public_page(
                client,
                str(profile["profile_url"]),
            )
        if not channel_id:
            raise RuntimeError("Could not resolve YouTube channel ID")

        self.last_run_stats["youtube"]["channels"] += 1
        video_items = (
            await self._youtube_api_videos(client, channel)
            if settings.youtube_api_key and channel
            else await self._youtube_feed_videos(client, channel_id)
        )
        results: list[dict[str, Any]] = []
        for video in video_items[: max(settings.youtube_max_videos, 1)]:
            video_id = str(video.get("video_id") or "")
            if not video_id:
                continue
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            title = str(video.get("title") or "YouTube video")
            description = str(video.get("description") or "")
            published_at = video.get("published_at")
            parts = [
                f"Video: {title}",
                f"Channel: {video.get('channel_title') or channel_key}",
                f"Published: {published_at or 'unknown'}",
                description,
            ]
            statistics = video.get("statistics") or {}
            if statistics:
                parts.append(
                    "Public statistics: "
                    + ", ".join(f"{key}={value}" for key, value in statistics.items())
                )

            transcript = ""
            if settings.enable_youtube_transcripts:
                transcript = await self._youtube_transcript(video_id)
                if transcript:
                    parts.append(f"Transcript:\n{transcript}")
                    self.last_run_stats["youtube"]["transcripts"] += 1

            content = "\n\n".join(part for part in parts if part).strip()
            saved = self._save_external_document(
                source=f"youtube:video:{video_id}",
                source_url=video_url,
                title=title,
                content=content,
                confidence=0.82 if transcript else 0.74,
                metadata={
                    "source_type": "youtube_video",
                    "collector": "youtube_public_source",
                    "video_id": video_id,
                    "channel_id": channel_id,
                    "published_at": published_at,
                    "statistics": statistics,
                    "transcript_captured": bool(transcript),
                },
            )
            if saved:
                results.append(
                    {
                        "source_type": "youtube_video",
                        "url": video_url,
                        "title": title,
                        "persisted": True,
                    }
                )
                self.last_run_stats["youtube"]["videos"] += 1

            if settings.youtube_api_key and settings.youtube_comments_per_video > 0:
                comment_result = await self._youtube_comments(client, video_id, title)
                if comment_result:
                    results.append(comment_result)
        return results

    async def _youtube_channel(
        self,
        client: httpx.AsyncClient,
        channel_key: str,
    ) -> dict[str, Any] | None:
        params: dict[str, Any] = {
            "part": "snippet,contentDetails,statistics",
            "key": settings.youtube_api_key,
        }
        if channel_key.startswith("UC"):
            params["id"] = channel_key
        elif channel_key.startswith("@"):
            params["forHandle"] = channel_key
        else:
            params["forHandle"] = f"@{channel_key}"
        response = await client.get(f"{self.YOUTUBE_API}/channels", params=params)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        items = response.json().get("items") or []
        return items[0] if items else None

    async def _youtube_api_videos(
        self,
        client: httpx.AsyncClient,
        channel: dict[str, Any],
    ) -> list[dict[str, Any]]:
        uploads = (
            channel.get("contentDetails", {})
            .get("relatedPlaylists", {})
            .get("uploads")
        )
        if not uploads:
            return []
        response = await client.get(
            f"{self.YOUTUBE_API}/playlistItems",
            params={
                "part": "snippet,contentDetails",
                "playlistId": uploads,
                "maxResults": min(max(settings.youtube_max_videos, 1), 50),
                "key": settings.youtube_api_key,
            },
        )
        response.raise_for_status()
        items = response.json().get("items") or []
        video_ids = [
            str(item.get("contentDetails", {}).get("videoId") or "")
            for item in items
        ]
        video_ids = [video_id for video_id in video_ids if video_id]
        details_by_id: dict[str, dict[str, Any]] = {}
        if video_ids:
            detail_response = await client.get(
                f"{self.YOUTUBE_API}/videos",
                params={
                    "part": "snippet,contentDetails,statistics,status",
                    "id": ",".join(video_ids),
                    "key": settings.youtube_api_key,
                },
            )
            detail_response.raise_for_status()
            details_by_id = {
                str(item["id"]): item
                for item in detail_response.json().get("items") or []
            }
        videos = []
        for item in items:
            snippet = item.get("snippet") or {}
            video_id = str(item.get("contentDetails", {}).get("videoId") or "")
            details = details_by_id.get(video_id, {})
            detail_snippet = details.get("snippet") or snippet
            videos.append(
                {
                    "video_id": video_id,
                    "title": detail_snippet.get("title"),
                    "description": detail_snippet.get("description"),
                    "channel_title": detail_snippet.get("channelTitle"),
                    "published_at": detail_snippet.get("publishedAt"),
                    "statistics": details.get("statistics") or {},
                }
            )
        return videos

    async def _youtube_feed_videos(
        self,
        client: httpx.AsyncClient,
        channel_id: str,
    ) -> list[dict[str, Any]]:
        response = await client.get(
            "https://www.youtube.com/feeds/videos.xml",
            params={"channel_id": channel_id},
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
        namespace = {
            "atom": "http://www.w3.org/2005/Atom",
            "yt": "http://www.youtube.com/xml/schemas/2015",
        }
        videos = []
        for entry in root.findall("atom:entry", namespace):
            video_id = entry.findtext("yt:videoId", default="", namespaces=namespace)
            videos.append(
                {
                    "video_id": video_id,
                    "title": entry.findtext("atom:title", default="", namespaces=namespace),
                    "description": "",
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
                    "statistics": {},
                }
            )
        return videos

    async def _channel_id_from_public_page(
        self,
        client: httpx.AsyncClient,
        profile_url: str,
    ) -> str:
        try:
            response = await client.get(profile_url)
            response.raise_for_status()
            patterns = (
                r'"externalId":"(UC[A-Za-z0-9_-]{20,30})"',
                r'"channelId":"(UC[A-Za-z0-9_-]{20,30})"',
                r"/channel/(UC[A-Za-z0-9_-]{20,30})",
            )
            for pattern in patterns:
                matches = re.findall(pattern, response.text)
                if matches:
                    return matches[0]
            return ""
        except Exception:
            return ""

    async def _youtube_transcript(self, video_id: str) -> str:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi

            def fetch() -> str:
                transcript = YouTubeTranscriptApi().fetch(
                    video_id,
                    languages=settings.youtube_transcript_language_list,
                )
                return " ".join(
                    str(snippet.text).strip()
                    for snippet in transcript
                    if str(snippet.text).strip()
                )

            return await asyncio.wait_for(asyncio.to_thread(fetch), timeout=30)
        except Exception as exc:
            logger.info("Transcript unavailable for %s: %s", video_id, exc)
            return ""

    async def _youtube_comments(
        self,
        client: httpx.AsyncClient,
        video_id: str,
        video_title: str,
    ) -> dict[str, Any] | None:
        try:
            response = await client.get(
                f"{self.YOUTUBE_API}/commentThreads",
                params={
                    "part": "snippet,replies",
                    "videoId": video_id,
                    "maxResults": min(
                        max(settings.youtube_comments_per_video, 1),
                        100,
                    ),
                    "order": "relevance",
                    "textFormat": "plainText",
                    "key": settings.youtube_api_key,
                },
            )
            if response.status_code == 403:
                return None
            response.raise_for_status()
            comments = []
            for item in response.json().get("items") or []:
                snippet = (
                    item.get("snippet", {})
                    .get("topLevelComment", {})
                    .get("snippet", {})
                )
                text = str(snippet.get("textDisplay") or "").strip()
                if text:
                    comments.append(
                        {
                            "text": text,
                            "likes": snippet.get("likeCount", 0),
                            "published_at": snippet.get("publishedAt"),
                        }
                    )
            if not comments:
                return None
            content = "\n\n".join(
                f"Comment {index + 1} (likes: {item['likes']}): {item['text']}"
                for index, item in enumerate(comments)
            )
            url = f"https://www.youtube.com/watch?v={video_id}"
            saved = self._save_external_document(
                source=f"youtube:comments:{video_id}",
                source_url=f"{url}#comments",
                title=f"Public comments on {video_title}",
                content=content,
                confidence=0.55,
                metadata={
                    "source_type": "youtube_comments",
                    "collector": "youtube_data_api",
                    "video_id": video_id,
                    "comment_count": len(comments),
                    "published_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            if not saved:
                return None
            self.last_run_stats["youtube"]["comment_documents"] += 1
            self.last_run_stats["youtube"]["comments"] += len(comments)
            return {
                "source_type": "youtube_comments",
                "url": f"{url}#comments",
                "title": f"Comments on {video_title}",
                "persisted": True,
                "items": len(comments),
            }
        except Exception as exc:
            self.last_run_stats["youtube"]["errors"].append(str(exc)[:500])
            return None

    async def _collect_github(
        self,
        client: httpx.AsyncClient,
        profile: dict[str, Any],
    ) -> list[dict[str, Any]]:
        account = str(profile.get("profile_key") or "").strip()
        if not account:
            account = urlsplit(str(profile["profile_url"])).path.strip("/").split("/")[0]
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"

        org_response = await client.get(
            f"{self.GITHUB_API}/orgs/{account}",
            headers=headers,
        )
        account_kind = "orgs"
        if org_response.status_code == 404:
            account_kind = "users"
            org_response = await client.get(
                f"{self.GITHUB_API}/users/{account}",
                headers=headers,
            )
        org_response.raise_for_status()
        account_data = org_response.json()
        results: list[dict[str, Any]] = []
        profile_content = "\n".join(
            (
                f"GitHub account: {account_data.get('name') or account}",
                f"Description: {account_data.get('description') or account_data.get('bio') or ''}",
                f"Public repositories: {account_data.get('public_repos', 0)}",
                f"Followers: {account_data.get('followers', 0)}",
                f"Location: {account_data.get('location') or ''}",
                f"Blog: {account_data.get('blog') or ''}",
            )
        )
        if self._save_external_document(
            source=f"github:profile:{account.casefold()}",
            source_url=str(account_data.get("html_url") or profile["profile_url"]),
            title=f"{account} GitHub profile",
            content=profile_content,
            confidence=0.88,
            metadata={
                "source_type": "github_profile",
                "collector": "github_rest_api",
                "github_account": account,
                "published_at": account_data.get("updated_at"),
            },
        ):
            results.append(
                {
                    "source_type": "github_profile",
                    "url": account_data.get("html_url"),
                    "title": f"{account} GitHub profile",
                    "persisted": True,
                }
            )
            self.last_run_stats["github"]["profiles"] += 1

        repos_response = await client.get(
            f"{self.GITHUB_API}/{account_kind}/{account}/repos",
            headers=headers,
            params={
                "type": "public",
                "sort": "updated",
                "direction": "desc",
                "per_page": min(max(settings.github_max_repositories, 1), 100),
            },
        )
        repos_response.raise_for_status()
        repositories = repos_response.json() or []
        for repository in repositories[: max(settings.github_max_repositories, 1)]:
            repo_name = str(repository.get("name") or "")
            if not repo_name:
                continue
            repo_url = str(repository.get("html_url") or "")
            topics = repository.get("topics") or []
            repo_content = "\n".join(
                (
                    f"Repository: {repository.get('full_name') or repo_name}",
                    f"Description: {repository.get('description') or ''}",
                    f"Primary language: {repository.get('language') or ''}",
                    f"Topics: {', '.join(str(topic) for topic in topics)}",
                    f"Stars: {repository.get('stargazers_count', 0)}",
                    f"Forks: {repository.get('forks_count', 0)}",
                    f"Open issues: {repository.get('open_issues_count', 0)}",
                    f"Created: {repository.get('created_at') or ''}",
                    f"Updated: {repository.get('updated_at') or ''}",
                    f"Pushed: {repository.get('pushed_at') or ''}",
                )
            )
            if self._save_external_document(
                source=f"github:repo:{account.casefold()}/{repo_name.casefold()}",
                source_url=repo_url,
                title=f"{account}/{repo_name}",
                content=repo_content,
                confidence=0.86,
                metadata={
                    "source_type": "github_repository",
                    "collector": "github_rest_api",
                    "github_account": account,
                    "repository": repo_name,
                    "published_at": repository.get("updated_at"),
                    "topics": topics,
                },
            ):
                results.append(
                    {
                        "source_type": "github_repository",
                        "url": repo_url,
                        "title": f"{account}/{repo_name}",
                        "persisted": True,
                    }
                )
                self.last_run_stats["github"]["repositories"] += 1

        release_repositories = repositories[: min(len(repositories), 10)]
        for repository in release_repositories:
            repo_name = str(repository.get("name") or "")
            try:
                releases_response = await client.get(
                    f"{self.GITHUB_API}/repos/{account}/{repo_name}/releases",
                    headers=headers,
                    params={
                        "per_page": min(
                            max(settings.github_releases_per_repository, 1),
                            20,
                        )
                    },
                )
                if releases_response.status_code == 404:
                    continue
                releases_response.raise_for_status()
                releases = releases_response.json() or []
            except Exception as exc:
                self.last_run_stats["github"]["errors"].append(str(exc)[:500])
                continue
            for release in releases[: max(settings.github_releases_per_repository, 1)]:
                release_url = str(release.get("html_url") or "")
                tag = str(release.get("tag_name") or release.get("name") or "release")
                release_content = "\n".join(
                    (
                        f"Release: {release.get('name') or tag}",
                        f"Repository: {account}/{repo_name}",
                        f"Tag: {tag}",
                        f"Published: {release.get('published_at') or ''}",
                        f"Pre-release: {bool(release.get('prerelease'))}",
                        str(release.get("body") or ""),
                    )
                )
                if self._save_external_document(
                    source=f"github:release:{account.casefold()}/{repo_name.casefold()}/{tag}",
                    source_url=release_url,
                    title=f"{account}/{repo_name} {tag}",
                    content=release_content,
                    confidence=0.9,
                    metadata={
                        "source_type": "github_release",
                        "collector": "github_rest_api",
                        "github_account": account,
                        "repository": repo_name,
                        "tag": tag,
                        "published_at": release.get("published_at"),
                    },
                ):
                    results.append(
                        {
                            "source_type": "github_release",
                            "url": release_url,
                            "title": f"{account}/{repo_name} {tag}",
                            "persisted": True,
                        }
                    )
                    self.last_run_stats["github"]["releases"] += 1
        return results

    def _save_external_document(
        self,
        *,
        source: str,
        source_url: str,
        title: str,
        content: str,
        confidence: float,
        metadata: dict[str, Any],
    ) -> bool:
        content = content.strip()
        if not source_url or not content:
            return False
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if not self.save_raw_data(
            source=source,
            content=content,
            content_hash=content_hash,
            metadata=metadata,
        ):
            return False
        evidence_id = self.save_evidence(
            source_url=source_url,
            title=title,
            content=content,
            content_hash=content_hash,
            confidence=confidence,
            metadata=metadata,
        )
        return evidence_id is not None
