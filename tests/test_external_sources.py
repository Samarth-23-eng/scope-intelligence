import asyncio

from agents.ingestion.external_sources import ExternalSourceAgent


class FakeResponse:
    def __init__(self, *, text="", content=b"", status_code=200, data=None):
        self.text = text
        self.content = content
        self.status_code = status_code
        self.data = data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self.data


class FakeClient:
    def __init__(self, response):
        self.response = response
        self.requests = []

    async def get(self, url, **kwargs):
        self.requests.append((url, kwargs))
        return self.response


def test_youtube_channel_id_is_resolved_from_public_profile_metadata():
    agent = ExternalSourceAgent(1, "Example", "example.com")
    channel_id = "UC1234567890abcdefghijkl"
    client = FakeClient(
        FakeResponse(text=f'<script>{{"externalId":"{channel_id}"}}</script>')
    )

    result = asyncio.run(
        agent._channel_id_from_public_page(client, "https://youtube.com/@example")
    )

    assert result == channel_id


def test_youtube_public_feed_is_normalized_into_video_records():
    agent = ExternalSourceAgent(1, "Example", "example.com")
    feed = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom"
          xmlns:yt="http://www.youtube.com/xml/schemas/2015">
      <entry>
        <yt:videoId>video123</yt:videoId>
        <title>Factory launch</title>
        <author><name>Example Channel</name></author>
        <published>2026-07-28T10:00:00+00:00</published>
      </entry>
    </feed>"""
    client = FakeClient(FakeResponse(content=feed))

    videos = asyncio.run(agent._youtube_feed_videos(client, "UC123"))

    assert videos == [
        {
            "video_id": "video123",
            "title": "Factory launch",
            "description": "",
            "channel_title": "Example Channel",
            "published_at": "2026-07-28T10:00:00+00:00",
            "statistics": {},
        }
    ]
    assert client.requests[0][1]["params"] == {"channel_id": "UC123"}


def test_source_profile_urls_ignore_non_identity_query_parameters():
    from intelligence.collection import SourceProfileStore

    assert (
        SourceProfileStore.normalize_profile_url(
            "https://youtube.com/@example?sub_confirmation=1"
        )
        == "https://youtube.com/@example"
    )


def test_github_adapter_collects_profile_repository_and_release(monkeypatch):
    from agents.ingestion import external_sources

    class RoutedClient:
        async def get(self, url, **kwargs):
            if url.endswith("/orgs/acme"):
                return FakeResponse(
                    data={
                        "name": "Acme",
                        "description": "Industrial systems",
                        "public_repos": 1,
                        "followers": 10,
                        "html_url": "https://github.com/acme",
                        "updated_at": "2026-07-28T10:00:00Z",
                    }
                )
            if url.endswith("/orgs/acme/repos"):
                return FakeResponse(
                    data=[
                        {
                            "name": "widget",
                            "full_name": "acme/widget",
                            "html_url": "https://github.com/acme/widget",
                            "description": "Public widget",
                            "topics": ["industrial"],
                            "updated_at": "2026-07-28T09:00:00Z",
                        }
                    ]
                )
            if url.endswith("/repos/acme/widget/releases"):
                return FakeResponse(
                    data=[
                        {
                            "tag_name": "v1.0.0",
                            "name": "Version 1",
                            "html_url": "https://github.com/acme/widget/releases/tag/v1.0.0",
                            "published_at": "2026-07-28T08:00:00Z",
                            "body": "Initial release",
                        }
                    ]
                )
            return FakeResponse(status_code=404, data={})

    monkeypatch.setattr(external_sources.settings, "github_max_repositories", 1)
    monkeypatch.setattr(
        external_sources.settings,
        "github_releases_per_repository",
        1,
    )
    agent = ExternalSourceAgent(1, "Acme", "acme.example")
    monkeypatch.setattr(agent, "_save_external_document", lambda **kwargs: True)

    results = asyncio.run(
        agent._collect_github(
            RoutedClient(),
            {
                "profile_key": "acme",
                "profile_url": "https://github.com/acme",
            },
        )
    )

    assert len(results) == 3
    assert agent.last_run_stats["github"] == {
        "profiles": 1,
        "repositories": 1,
        "releases": 1,
        "errors": [],
    }


def test_external_document_preserves_content_beyond_legacy_character_cap(
    monkeypatch,
):
    agent = ExternalSourceAgent(1, "Example", "example.com")
    long_content = "timestamped transcript evidence " * 4_000
    captured = {}

    def save_raw_data(**kwargs):
        captured["raw"] = kwargs["content"]
        return True

    def save_evidence(**kwargs):
        captured["evidence"] = kwargs["content"]
        return 7

    monkeypatch.setattr(agent, "save_raw_data", save_raw_data)
    monkeypatch.setattr(agent, "save_evidence", save_evidence)

    saved = agent._save_external_document(
        source="youtube:video:long",
        source_url="https://youtube.com/watch?v=long",
        title="Long transcript",
        content=long_content,
        confidence=0.8,
        metadata={"source_type": "youtube_video"},
    )

    assert saved is True
    assert len(long_content) > 100_000
    assert captured["raw"] == long_content.strip()
    assert captured["evidence"] == long_content.strip()
