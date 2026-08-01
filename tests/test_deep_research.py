import pytest
from pydantic import ValidationError

from agents.ingestion.deep_research import (
    DeepSearchHit,
    OnionResearchClient,
    extract_onion_url,
    is_safe_onion_url,
)
from api.deep_research_routes import DeepResearchCreate


ONION = "a" * 56 + ".onion"


def test_deep_research_accepts_only_safe_v3_onion_urls():
    assert is_safe_onion_url(f"http://{ONION}/public/page")
    assert not is_safe_onion_url("https://example.com")
    assert not is_safe_onion_url(f"http://user:pass@{ONION}/")
    assert not is_safe_onion_url(f"http://{ONION}:8080/")
    assert not is_safe_onion_url("file:///etc/passwd")


def test_search_redirect_parser_extracts_only_onion_targets():
    wrapped = f"/redirect?url=https%3A%2F%2F{ONION}%2Fresearch%3Fx%3D1"

    assert extract_onion_url(wrapped) == f"https://{ONION}/research?x=1"
    assert extract_onion_url("https://example.com") is None


def test_deep_research_requires_explicit_authorized_use_acknowledgement():
    with pytest.raises(ValidationError):
        DeepResearchCreate(acknowledge_authorized_use=False)

    request = DeepResearchCreate(
        query="Example Company",
        acknowledge_authorized_use=True,
    )
    assert request.query == "Example Company"
    assert request.max_pages == 8


def test_collector_removes_active_elements_and_redacts_credentials(monkeypatch):
    credential = "ghp_" + "ABCDEFGHIJKLMNOPQRSTUVWXYZ12345"
    html = f"""
        <html><head><title>Example research</title><script>ignore()</script></head>
        <body><form><input value='secret'><button>submit</button></form>
        Public company intelligence with token {credential}
        and enough additional evidence text to pass the minimum content boundary safely.
        </body></html>
    """.encode()

    class Response:
        status_code = 200
        headers = {"Content-Type": "text/html; charset=utf-8"}

        def iter_content(self, _size):
            yield html

        def close(self):
            return None

    client = OnionResearchClient("socks5h://127.0.0.1:9050")
    monkeypatch.setattr(client.session, "get", lambda *args, **kwargs: Response())
    page = client.fetch(DeepSearchHit("Test", f"http://{ONION}/page", "Fallback"))

    assert page.title == "Example research"
    assert "submit" not in page.text
    assert "ghp_" not in page.text
    assert "[REDACTED]" in page.text
