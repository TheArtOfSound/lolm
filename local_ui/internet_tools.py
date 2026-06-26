"""Internet tool layer for the local LOLM-NFET workspace.

Providers are selected by environment variables:
- BRAVE_SEARCH_API_KEY: Brave Search API
- TAVILY_API_KEY: Tavily Search API
- SEARXNG_URL: self-hosted SearxNG instance

Direct URL fetch is also supported. Private/local network addresses are blocked
by default to avoid SSRF into the user's machine or LAN. Set
LOCAL_UI_ALLOW_PRIVATE_NET=1 only if you know what you are doing.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from dataclasses import dataclass
from html import unescape
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import requests


ALLOW_PRIVATE_NET = os.environ.get("LOCAL_UI_ALLOW_PRIVATE_NET", "0") == "1"
USER_AGENT = os.environ.get(
    "LOCAL_UI_USER_AGENT",
    "LOLM-NFET-LocalWorkspace/0.1 (+local research assistant)",
)
TIMEOUT = float(os.environ.get("LOCAL_UI_WEB_TIMEOUT", "12"))
MAX_CHARS = int(os.environ.get("LOCAL_UI_WEB_MAX_CHARS", "16000"))


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str = ""
    source: str = "web"

    def as_dict(self) -> Dict[str, str]:
        return {"title": self.title, "url": self.url, "snippet": self.snippet, "source": self.source}


def _host_is_private(host: str) -> bool:
    if ALLOW_PRIVATE_NET:
        return False
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved:
            return True
    return False


def _validate_public_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("Only http/https URLs are allowed")
    if not parsed.hostname:
        raise ValueError("URL has no hostname")
    if _host_is_private(parsed.hostname):
        raise ValueError("Blocked private/local network URL by default")


def _headers() -> Dict[str, str]:
    return {"User-Agent": USER_AGENT, "Accept": "text/html,application/json;q=0.9,*/*;q=0.8"}


def brave_search(query: str, limit: int) -> List[SearchResult]:
    key = os.environ.get("BRAVE_SEARCH_API_KEY")
    if not key:
        return []
    resp = requests.get(
        "https://api.search.brave.com/res/v1/web/search",
        params={"q": query, "count": min(limit, 20)},
        headers={"Accept": "application/json", "X-Subscription-Token": key, "User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    items = data.get("web", {}).get("results", [])
    return [SearchResult(title=i.get("title", ""), url=i.get("url", ""), snippet=i.get("description", ""), source="brave") for i in items[:limit]]


def tavily_search(query: str, limit: int) -> List[SearchResult]:
    key = os.environ.get("TAVILY_API_KEY")
    if not key:
        return []
    resp = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": key, "query": query, "max_results": min(limit, 10), "search_depth": "advanced"},
        headers={"User-Agent": USER_AGENT},
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    return [SearchResult(title=i.get("title", ""), url=i.get("url", ""), snippet=i.get("content", ""), source="tavily") for i in data.get("results", [])[:limit]]


def searxng_search(query: str, limit: int) -> List[SearchResult]:
    base = os.environ.get("SEARXNG_URL", "").rstrip("/")
    if not base:
        return []
    url = f"{base}/search"
    _validate_public_url(url)
    resp = requests.get(url, params={"q": query, "format": "json"}, headers=_headers(), timeout=TIMEOUT)
    resp.raise_for_status()
    data = resp.json()
    return [SearchResult(title=i.get("title", ""), url=i.get("url", ""), snippet=i.get("content", ""), source="searxng") for i in data.get("results", [])[:limit]]


def duckduckgo_lite_search(query: str, limit: int) -> List[SearchResult]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    resp = requests.get(url, headers=_headers(), timeout=TIMEOUT)
    resp.raise_for_status()
    html = resp.text
    results: List[SearchResult] = []
    blocks = re.findall(r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>.*?<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', html, flags=re.S)
    for href, title_html, snippet_html in blocks[:limit]:
        title = unescape(re.sub(r"<.*?>", "", title_html)).strip()
        snippet = unescape(re.sub(r"<.*?>", "", snippet_html)).strip()
        results.append(SearchResult(title=title, url=_resolve_ddg(unescape(href)),
                                    snippet=snippet, source="duckduckgo-lite"))
    return results


def _resolve_ddg(href: str) -> str:
    """DuckDuckGo wraps results in a redirect (//duckduckgo.com/l/?uddg=<real-url>).
    Unwrap to the real https URL so the operator can actually FETCH it."""
    if "duckduckgo.com/l/" in href and "uddg=" in href:
        try:
            real = parse_qs(urlparse(href if "://" in href else "https:" + href).query).get("uddg")
            if real:
                return unquote(real[0])
        except Exception:
            pass
    return href


def web_search(query: str, limit: int = 8) -> Dict[str, Any]:
    query = query.strip()
    if not query:
        raise ValueError("Search query is empty")
    errors: List[str] = []
    for provider in (brave_search, tavily_search, searxng_search, duckduckgo_lite_search):
        try:
            results = provider(query, limit)
            if results:
                return {"query": query, "provider": results[0].source, "results": [r.as_dict() for r in results[:limit]], "errors": errors}
        except Exception as exc:  # noqa: BLE001 - return tool errors to UI
            errors.append(f"{provider.__name__}: {exc}")
    return {"query": query, "provider": None, "results": [], "errors": errors}


def clean_html_text(html: str) -> str:
    html = re.sub(r"(?is)<(script|style|noscript|svg).*?</\1>", " ", html)
    html = re.sub(r"(?is)<br\s*/?>", "\n", html)
    html = re.sub(r"(?is)</p>", "\n", html)
    text = re.sub(r"(?is)<.*?>", " ", html)
    text = unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()[:MAX_CHARS]


def fetch_url(url: str) -> Dict[str, Any]:
    _validate_public_url(url)
    resp = requests.get(url, headers=_headers(), timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    content_type = resp.headers.get("content-type", "")
    text = resp.text if "text" in content_type or "html" in content_type or "json" in content_type else ""
    if "json" in content_type:
        try:
            text = json.dumps(resp.json(), ensure_ascii=False, indent=2)
        except Exception:
            pass
    else:
        text = clean_html_text(text)
    return {
        "url": resp.url,
        "status": resp.status_code,
        "content_type": content_type,
        "text": text[:MAX_CHARS],
        "chars": len(text),
    }
