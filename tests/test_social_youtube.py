import asyncio
from dataclasses import asdict

import httpx
import pytest

from agents.ingestion.social.base import SocialConnectorError
from agents.ingestion.social.models import SocialCollectionRequest
from agents.ingestion.social.youtube import YouTubeSocialConnector


VIDEO_ID = "abcdefghijk"


async def _ignore_progress(_event, _payload):
    return None


def _request(*, mode="evidence", target=None, **overrides):
    values = {
        "mode": mode,
        "target": target or f"https://www.youtube.com/watch?v={VIDEO_ID}",
        "max_items": 10,
        "include_comments": False,
        "comment_limit": 20,
        "include_replies": False,
        "max_reply_depth": 1,
        "include_transcript": False,
    }
    values.update(overrides)
    return SocialCollectionRequest(**values)


@pytest.mark.parametrize(
    "target",
    [
        f"https://youtube.com.evil.test/watch?v={VIDEO_ID}",
        f"https://user:password@youtube.com/watch?v={VIDEO_ID}",
        f"https://youtube.com:444/watch?v={VIDEO_ID}",
        f"ftp://youtube.com/watch?v={VIDEO_ID}",
    ],
)
def test_validation_rejects_noncanonical_or_credentialed_youtube_hosts(target):
    connector = YouTubeSocialConnector(api_key=None)

    with pytest.raises(SocialConnectorError) as raised:
        connector.validate(_request(target=target))

    error = raised.value
    assert error.code == "unsafe_social_target"
    assert error.recoverable is False
    assert error.suggested_action


def test_validation_accepts_supported_canonical_youtube_hosts():
    connector = YouTubeSocialConnector(api_key=None)

    connector.validate(_request(target=f"https://youtu.be/{VIDEO_ID}"))
    connector.validate(
        _request(target=f"https://www.youtube.com/shorts/{VIDEO_ID}")
    )


def test_plain_single_term_discover_target_is_a_keyword_query():
    connector = YouTubeSocialConnector(api_key=None)

    with pytest.raises(SocialConnectorError) as raised:
        connector.validate(_request(mode="discover", target="Acme"))

    assert raised.value.code == "youtube_api_key_required"
    assert "Keyword discovery" in raised.value.message


def test_eleven_character_discover_term_is_not_assumed_to_be_a_video_id():
    connector = YouTubeSocialConnector(api_key=None)

    with pytest.raises(SocialConnectorError) as raised:
        connector.validate(_request(mode="discover", target=VIDEO_ID))

    assert raised.value.code == "youtube_api_key_required"


def test_plain_single_term_discover_target_uses_keyword_search_endpoint():
    requested_resources = []

    def handler(request):
        requested_resources.append(request.url.path)
        assert request.url.params["q"] == "Acme"
        return httpx.Response(200, json={"items": []})

    async def discover():
        connector = YouTubeSocialConnector(api_key="test-key")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await connector._discover(
                client,
                _request(mode="discover", target="Acme"),
                progress=_ignore_progress,
                cancelled=lambda: False,
            )

    batch = asyncio.run(discover())

    assert requested_resources == ["/youtube/v3/search"]
    assert batch.posts == []
    assert batch.checkpoint == {"search_complete": True}


def test_duplicate_comment_page_token_stops_pagination():
    page_tokens = []

    def handler(request):
        page_tokens.append(request.url.params.get("pageToken"))
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "snippet": {
                            "topLevelComment": {
                                "id": "comment-1",
                                "snippet": {"textDisplay": "Public comment"},
                            },
                            "totalReplyCount": 0,
                        }
                    }
                ],
                "nextPageToken": "repeated-page",
            },
        )

    async def collect_comments():
        connector = YouTubeSocialConnector(api_key="test-key")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await connector._comments(
                client,
                VIDEO_ID,
                limit=10,
                include_replies=False,
                progress=_ignore_progress,
                cancelled=lambda: False,
            )

    comments = asyncio.run(collect_comments())

    assert page_tokens == [None, "repeated-page"]
    assert [comment.platform_comment_id for comment in comments] == ["comment-1"]


def test_comments_do_not_retain_top_level_or_reply_author_identity():
    author_values = {
        "Top Level Author",
        "Reply Author",
        "UCtop-level-author",
        "UCreply-author",
        "https://www.youtube.com/channel/UCtop-level-author",
        "https://example.test/top-level-author.jpg",
    }

    def handler(_request):
        return httpx.Response(
            200,
            json={
                "items": [
                    {
                        "snippet": {
                            "topLevelComment": {
                                "id": "comment-1",
                                "snippet": {
                                    "textDisplay": "Top-level text",
                                    "authorDisplayName": "Top Level Author",
                                    "authorChannelId": {"value": "UCtop-level-author"},
                                    "authorChannelUrl": (
                                        "https://www.youtube.com/channel/"
                                        "UCtop-level-author"
                                    ),
                                    "authorProfileImageUrl": (
                                        "https://example.test/top-level-author.jpg"
                                    ),
                                },
                            },
                            "totalReplyCount": 1,
                        },
                        "replies": {
                            "comments": [
                                {
                                    "id": "reply-1",
                                    "snippet": {
                                        "textDisplay": "Reply text",
                                        "authorDisplayName": "Reply Author",
                                        "authorChannelId": {
                                            "value": "UCreply-author"
                                        },
                                    },
                                }
                            ]
                        },
                    }
                ]
            },
        )

    async def collect_comments():
        connector = YouTubeSocialConnector(api_key="test-key")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await connector._comments(
                client,
                VIDEO_ID,
                limit=5,
                include_replies=True,
                progress=_ignore_progress,
                cancelled=lambda: False,
            )

    serialized = [asdict(comment) for comment in asyncio.run(collect_comments())]
    flattened = repr(serialized)

    assert len(serialized) == 2
    assert all(record["metadata"]["identity_retained"] is False for record in serialized)
    assert all("author" not in key.casefold() for record in serialized for key in record)
    assert "author" not in flattened.casefold()
    for author_value in author_values:
        assert author_value not in flattened


def test_api_failures_expose_structured_connector_diagnostic():
    def handler(request):
        assert request.url.params["key"] == "test-key"
        return httpx.Response(
            403,
            json={
                "error": {
                    "errors": [{"reason": "keyInvalid"}],
                    "message": "The supplied credential was rejected.",
                }
            },
        )

    async def request_api():
        connector = YouTubeSocialConnector(api_key="test-key")
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await connector._api_get(
                client,
                "videos",
                {"part": "snippet", "id": VIDEO_ID},
            )

    with pytest.raises(SocialConnectorError) as raised:
        asyncio.run(request_api())

    error = raised.value
    diagnostic = error.diagnostic()
    assert error.code == "youtube_access_denied"
    assert error.http_status == 403
    assert error.metadata == {"provider_reason": "keyInvalid"}
    assert "test-key" not in str(error)
    assert diagnostic.code == error.code
    assert diagnostic.severity == "error"
    assert diagnostic.recoverable is True
    assert diagnostic.suggested_action
    assert diagnostic.metadata == error.metadata
