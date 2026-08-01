from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import unquote, urlsplit

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from config.settings import settings
from intelligence.security import redact_sensitive_text


logger = logging.getLogger(__name__)

# Search endpoints are sourced from Robin's public MIT-licensed engine catalog.
# Scope uses its own parser, validation, diagnostics, and evidence workflow.
SEARCH_ENGINES = (
    ("Ahmia", "http://juhanurmihxlp77nkq76byazcldy2hlmovfu2epvl5ankdibsot4csyd.onion/search/?q={query}"),
    ("OnionLand", "http://3bbad7fauom4d6sgppalyqddsqbf5u5p56b5k5uk2zxsy3d6ey2jobad.onion/search?q={query}"),
    ("Amnesia", "http://amnesia7u5odx5xbwtpnqk3edybgud5bmiagu75bnqx2crntw5kry7ad.onion/search?query={query}"),
    ("Torland", "http://torlbmqwtudkorme6prgfpmsnile7ug2zm4u3ejpcncxuhpu4k2j4kyd.onion/index.php?a=search&q={query}"),
)

_ONION_HOST_RE = re.compile(r"^[a-z2-7]{56}\.onion$")
_ONION_URL_RE = re.compile(r"https?://[a-z2-7]{56}\.onion[^\s\"'<>]*", re.IGNORECASE)
_ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml", "text/plain")


class TorResearchError(RuntimeError):
    def __init__(self, code: str, message: str, suggested_action: str | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.suggested_action = suggested_action


@dataclass(frozen=True)
class DeepSearchHit:
    engine: str
    url: str
    title: str


@dataclass(frozen=True)
class DeepPage:
    url: str
    title: str
    text: str
    content_hash: str
    http_status: int
    content_type: str


def is_safe_onion_url(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return False
    hostname = (parsed.hostname or "").lower()
    return (
        parsed.scheme in {"http", "https"}
        and parsed.username is None
        and parsed.password is None
        and port in {None, 80, 443}
        and bool(_ONION_HOST_RE.fullmatch(hostname))
    )


def extract_onion_url(href: str) -> str | None:
    decoded = unquote(str(href or ""))
    match = _ONION_URL_RE.search(decoded)
    if not match:
        return None
    candidate = match.group(0).rstrip(".,);]")
    return candidate if is_safe_onion_url(candidate) else None


class OnionResearchClient:
    """Bounded, GET-only Tor client for public hidden-service research."""

    def __init__(self, proxy_url: str | None = None):
        proxy = (proxy_url or settings.tor_socks_proxy_url).strip()
        if not proxy.startswith("socks5h://"):
            raise TorResearchError(
                "invalid_tor_proxy",
                "Deep Research requires a socks5h Tor proxy.",
                "Use the optional Scope Tor service or configure an authorized Tor proxy.",
            )
        self.proxy = proxy
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.proxies = {"http": proxy, "https": proxy}
        retry = Retry(
            total=2,
            connect=2,
            read=1,
            backoff_factor=0.6,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=4)
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self.headers = {
            "User-Agent": "ScopeIntelligence-DeepResearch/0.1 (+local OSINT research)",
            "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9",
        }

    def test_tor(self) -> dict[str, Any]:
        try:
            response = self.session.get(
                "https://check.torproject.org/api/ip",
                headers=self.headers,
                timeout=(12, 35),
                allow_redirects=False,
            )
            payload = response.json() if response.status_code == 200 else {}
            return {
                "reachable": response.status_code == 200,
                "is_tor": bool(payload.get("IsTor")),
                "status": response.status_code,
            }
        except requests.RequestException:
            return {"reachable": False, "is_tor": False, "status": None}

    def search(self, engine: str, endpoint: str, query: str) -> tuple[list[DeepSearchHit], dict[str, Any]]:
        from urllib.parse import quote_plus

        url = endpoint.format(query=quote_plus(query[:240]))
        try:
            response = self.session.get(
                url,
                headers=self.headers,
                timeout=(12, 45),
                allow_redirects=False,
            )
        except requests.RequestException:
            return [], {"engine": engine, "ok": False, "code": "engine_unreachable"}
        if response.status_code != 200:
            return [], {"engine": engine, "ok": False, "code": "engine_http_error", "http_status": response.status_code}
        content_type = (response.headers.get("Content-Type") or "").lower()
        if content_type and not any(item in content_type for item in _ALLOWED_CONTENT_TYPES):
            return [], {"engine": engine, "ok": False, "code": "engine_content_rejected"}
        soup = BeautifulSoup(response.content[:750_000], "html.parser")
        hits: list[DeepSearchHit] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            found = extract_onion_url(str(anchor.get("href") or ""))
            if not found or found in seen or urlsplit(found).hostname == urlsplit(url).hostname:
                continue
            title = " ".join(anchor.get_text(" ", strip=True).split())[:1000]
            if len(title) < 3:
                continue
            seen.add(found)
            hits.append(DeepSearchHit(engine=engine, url=found, title=title))
        return hits, {"engine": engine, "ok": True, "results": len(hits)}

    def fetch(self, hit: DeepSearchHit) -> DeepPage:
        if not is_safe_onion_url(hit.url):
            raise TorResearchError("unsafe_target_rejected", "A non-onion or unsafe target was rejected.")
        response = None
        try:
            response = self.session.get(
                hit.url,
                headers=self.headers,
                timeout=(12, 50),
                allow_redirects=False,
                stream=True,
            )
            if response.status_code != 200:
                raise TorResearchError("page_http_error", f"The hidden service returned HTTP {response.status_code}.")
            content_type = (response.headers.get("Content-Type") or "").lower()
            if content_type and not any(item in content_type for item in _ALLOWED_CONTENT_TYPES):
                raise TorResearchError("content_type_rejected", "Only HTML and plain-text pages are collected.")
            chunks: list[bytes] = []
            size = 0
            limit = max(50_000, min(settings.deep_research_max_content_bytes, 2_000_000))
            for chunk in response.iter_content(8192):
                if not chunk:
                    continue
                size += len(chunk)
                if size > limit:
                    break
                chunks.append(chunk)
            raw = b"".join(chunks)
            soup = BeautifulSoup(raw, "html.parser")
            for element in soup(["script", "style", "form", "input", "button", "iframe", "object", "embed"]):
                element.decompose()
            title = " ".join((soup.title.get_text(" ", strip=True) if soup.title else hit.title).split())[:1000]
            text = " ".join(soup.get_text(" ", strip=True).split())
            text = redact_sensitive_text(text)[:250_000]
            if len(text) < 80:
                raise TorResearchError("insufficient_content", "The page did not contain enough readable text.")
            return DeepPage(
                url=hit.url,
                title=title or hit.title,
                text=text,
                content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest(),
                http_status=response.status_code,
                content_type=content_type or "text/html",
            )
        except requests.RequestException as exc:
            logger.debug("Tor page request failed: %s", type(exc).__name__)
            raise TorResearchError("page_unreachable", "The hidden service could not be reached.") from None
        finally:
            if response is not None:
                response.close()

    @staticmethod
    def delay() -> None:
        time.sleep(max(0.25, min(settings.deep_research_request_delay_seconds, 15.0)))
