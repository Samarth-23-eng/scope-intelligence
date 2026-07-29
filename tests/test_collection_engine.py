from intelligence.collection import CollectionCampaignStore, SourceProfileStore


def test_collection_url_canonicalization_removes_tracking_but_keeps_identity_query():
    canonical = CollectionCampaignStore.canonicalize_url(
        "HTTPS://Example.COM:443/news/?utm_source=test&page=2&b=1#comments"
    )

    assert canonical == "https://example.com/news?b=1&page=2"


def test_source_profile_classification_accepts_supported_public_profiles():
    assert SourceProfileStore.classify("https://www.youtube.com/@Acme") == (
        "youtube",
        "@Acme",
    )
    assert SourceProfileStore.classify("https://github.com/acme/repository") == (
        "github",
        "acme",
    )
    assert SourceProfileStore.classify(
        "https://www.linkedin.com/company/acme-corp/posts/"
    ) == ("linkedin", "acme-corp")
    assert SourceProfileStore.classify("https://x.com/acme") == ("x", "acme")
    assert SourceProfileStore.classify("https://reddit.com/r/acme") == (
        "reddit",
        "acme",
    )


def test_source_profile_classification_rejects_content_and_reserved_github_paths():
    assert SourceProfileStore.classify("https://youtu.be/video-id") is None
    assert SourceProfileStore.classify("https://github.com/search?q=acme") is None
    assert SourceProfileStore.classify("https://example.com/github/acme") is None
