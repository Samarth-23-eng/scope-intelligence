import socket

import httpx
import pytest

from agents.discovery.company_discovery import CompanyDiscoveryAgent


def response(url: str, text: str = "", content_type: str = "text/html", status: int = 200):
    return httpx.Response(
        status,
        text=text,
        headers={"content-type": content_type},
        request=httpx.Request("GET", url),
    )


def test_discovery_combines_resolution_verification_and_feeds(monkeypatch):
    agent = CompanyDiscoveryAgent("Example")
    monkeypatch.setattr(
        agent,
        "search_official_website",
        lambda: [{"title": "Example", "url": "https://example.com", "domain": "example.com", "snippet": ""}],
    )
    monkeypatch.setattr(agent, "resolve_official_website", lambda candidates: ("https://example.com", 0.9))
    monkeypatch.setattr(agent, "verify_website", lambda website, domain: "https://example.com/")
    monkeypatch.setattr(
        agent,
        "discover_rss_feeds",
        lambda website, domain: ["https://example.com/feed.xml"],
    )

    try:
        result = agent.discover()
    finally:
        agent.close()

    assert result.domain == "example.com"
    assert result.rss_feeds == ["https://example.com/feed.xml"]
    assert result.confidence == 0.9


def test_rss_discovery_reads_link_tags_and_verifies_xml(monkeypatch):
    agent = CompanyDiscoveryAgent("Example")

    def safe_get(url: str):
        if url == "https://example.com":
            return response(
                url,
                '<html><link rel="alternate" type="application/rss+xml" href="/news.xml"></html>',
            )
        if url == "https://example.com/news.xml":
            return response(url, "<rss><channel /></rss>", "application/rss+xml")
        return response(url, status=404)

    monkeypatch.setattr(agent, "safe_get", safe_get)
    try:
        feeds = agent.discover_rss_feeds("https://example.com", "example.com")
    finally:
        agent.close()

    assert feeds == ["https://example.com/news.xml"]


def test_private_discovery_targets_are_rejected(monkeypatch):
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))],
    )

    with pytest.raises(ValueError, match="Private or reserved"):
        CompanyDiscoveryAgent.validate_public_url("http://internal.example")


def test_search_redirect_url_is_unwrapped():
    url = CompanyDiscoveryAgent.extract_search_url(
        "//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Fabout"
    )

    assert url == "https://example.com/about"


def test_enterprise_access_denied_still_verifies_public_host(monkeypatch):
    agent = CompanyDiscoveryAgent("Nestle")
    monkeypatch.setattr(
        agent,
        "safe_get",
        lambda url: response(url, status=403),
    )

    try:
        verified = agent.verify_website("https://www.nestle.com", "www.nestle.com")
    finally:
        agent.close()

    assert verified == "https://www.nestle.com"


def test_discovery_falls_back_to_name_first_identity(monkeypatch):
    agent = CompanyDiscoveryAgent("Obscure Research Unit India")
    monkeypatch.setattr(agent, "search_official_website", lambda: [])
    monkeypatch.setattr(
        agent,
        "resolve_official_website",
        lambda candidates: ("https://unreachable.invalid", 0.3),
    )
    monkeypatch.setattr(
        agent,
        "verify_website",
        lambda website, domain: (_ for _ in ()).throw(ValueError("unreachable")),
    )

    try:
        result = agent.discover()
    finally:
        agent.close()

    assert result.name == "Obscure Research Unit India"
    assert result.domain is None
    assert result.website is None
    assert result.domain_verified is False
    assert result.identity_context["resolution_mode"] == "name_first"
