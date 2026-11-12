"""A small Python client for the Context7 REST API.

Method names follow the official TypeScript SDK (@upstash/context7-sdk):
search_library, get_context and search. Standard library only.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union

__all__ = ["Context7", "Context7Error", "Library", "Docs", "RateLimit", "Transport"]

DEFAULT_BASE_URL = "https://context7.com/api"
RETRY_STATUSES = {408, 425, 429, 500, 502, 503, 504}

# A transport takes (method, url, headers, timeout) and returns (status, headers, body text).
Transport = Callable[[str, str, Dict[str, str], float], Tuple[int, Dict[str, str], str]]


@dataclass(frozen=True)
class RateLimit:
    limit: Optional[int] = None
    remaining: Optional[int] = None
    reset: Optional[int] = None  # unix seconds

    @classmethod
    def from_headers(cls, headers: Dict[str, str]) -> "RateLimit":
        low = {k.lower(): v for k, v in headers.items()}

        def num(name: str) -> Optional[int]:
            try:
                return int(low[name])
            except (KeyError, ValueError):
                return None

        return cls(num("ratelimit-limit"), num("ratelimit-remaining"), num("ratelimit-reset"))


class Context7Error(Exception):
    """Raised for any non-success answer. `code` is the API's own error code when it sends one."""

    def __init__(self, message: str, *, status: int = 0, code: str = "", rate_limit: Optional[RateLimit] = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.rate_limit = rate_limit


@dataclass(frozen=True)
class Library:
    id: str
    title: str
    description: str = ""
    total_snippets: int = 0
    total_tokens: int = 0
    trust_score: Optional[float] = None
    benchmark_score: Optional[float] = None
    stars: Optional[int] = None
    last_update: str = ""
    versions: Tuple[str, ...] = ()
    raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def from_api(cls, d: Dict[str, Any]) -> "Library":
        stars = d.get("stars")
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            total_snippets=int(d.get("totalSnippets") or 0),
            total_tokens=int(d.get("totalTokens") or 0),
            trust_score=d.get("trustScore"),
            benchmark_score=d.get("benchmarkScore"),
            stars=None if stars in (None, -1) else stars,
            last_update=d.get("lastUpdateDate", ""),
            versions=tuple(d.get("versions") or ()),
            raw=d,
        )


@dataclass(frozen=True)
class CodeSnippet:
    title: str
    description: str
    language: str
    source: str
    code: str
    tokens: int = 0

    @classmethod
    def from_api(cls, d: Dict[str, Any]) -> "CodeSnippet":
        code = "\n\n".join(x.get("code", "") for x in d.get("codeList") or [])
        return cls(d.get("codeTitle", ""), d.get("codeDescription", ""), d.get("codeLanguage", ""),
                   d.get("codeId", ""), code, int(d.get("codeTokens") or 0))


@dataclass(frozen=True)
class InfoSnippet:
    breadcrumb: str
    source: str
    content: str
    tokens: int = 0

    @classmethod
    def from_api(cls, d: Dict[str, Any]) -> "InfoSnippet":
        return cls(d.get("breadcrumb", ""), d.get("pageId", ""), d.get("content", ""), int(d.get("contentTokens") or 0))


@dataclass(frozen=True)
class Docs:
    library_id: str
    code: List[CodeSnippet]
    info: List[InfoSnippet]
    redirected_from: Optional[str] = None
    raw: Dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    @property
    def tokens(self) -> int:
        return sum(c.tokens for c in self.code) + sum(i.tokens for i in self.info)


def urllib_transport(method: str, url: str, headers: Dict[str, str], timeout: float) -> Tuple[int, Dict[str, str], str]:
    req = urllib.request.Request(url, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, dict(r.headers), r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read().decode("utf-8", "replace")


class Context7:
    """Client for https://context7.com/api.

    An API key is optional. Without one the API answers with a lower rate limit.
    The key is read from `api_key` or the CONTEXT7_API_KEY environment variable.
    """

    def __init__(self, api_key: Optional[str] = None, *, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0,
                 retries: int = 2, backoff: float = 0.5, transport: Optional[Transport] = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.api_key = api_key if api_key is not None else os.environ.get("CONTEXT7_API_KEY") or None
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._transport = transport or urllib_transport
        self._sleep = sleep
        self.last_rate_limit: Optional[RateLimit] = None

    # public API

    def search_library(self, query: str, library_name: str) -> List[Library]:
        """Find libraries by name. `query` is what you want to do, it helps ranking."""
        status, data, _ = self._get("/v2/libs/search", {"libraryName": library_name, "query": query},
                                    allow={404: "no_libraries_found"})
        if status == 404:
            return []
        return [Library.from_api(x) for x in data.get("results", [])]

    def get_context(self, query: str, library_id: str, *, type: str = "json",
                    follow_redirects: bool = True) -> Union[Docs, str]:
        """Documentation for one library. type="json" returns Docs, type="txt" returns plain text."""
        if type not in ("json", "txt"):
            raise ValueError('type must be "json" or "txt"')
        params = {"libraryId": library_id, "query": query, "type": type}
        status, data, text = self._get("/v2/context", params, allow={301: "library_redirected"}, parse=type == "json")
        redirected_from = None
        if status == 301:
            target = (data or {}).get("redirectUrl")
            if not follow_redirects or not target:
                raise Context7Error(data.get("message", "library redirected"), status=301,
                                    code="library_redirected", rate_limit=self.last_rate_limit)
            redirected_from, library_id = library_id, target
            params["libraryId"] = target
            status, data, text = self._get("/v2/context", params, parse=type == "json")
        if type == "txt":
            return text
        return Docs(library_id, [CodeSnippet.from_api(c) for c in data.get("codeSnippets", [])],
                    [InfoSnippet.from_api(i) for i in data.get("infoSnippets", [])], redirected_from, data)

    def search(self, query: str, *, libraries: Optional[Sequence[str]] = None, version: Optional[str] = None,
               language: Optional[str] = None) -> Docs:
        """One-call search, Context7 picks the library. Up to four library names or IDs as hints."""
        libs = list(libraries or [])
        if len(libs) > 4:
            raise ValueError("at most four libraries")
        if version and not libs:
            raise ValueError("version needs at least one library hint")
        params: List[Tuple[str, str]] = [("query", query), ("type", "json")]
        params += [("library", x) for x in libs]
        if version:
            params.append(("version", version))
        if language:
            params.append(("language", language))
        _, data, _ = self._get("/v3/search", params)
        return Docs(libs[0] if libs else "", [CodeSnippet.from_api(c) for c in data.get("codeSnippets", [])],
                    [InfoSnippet.from_api(i) for i in data.get("infoSnippets", [])], None, data)

    # plumbing

    def _get(self, path: str, params: Any, *, allow: Optional[Dict[int, str]] = None, parse: bool = True):
        url = f"{self.base_url}{path}?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json" if parse else "text/plain", "User-Agent": "context7-python/0.1"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        attempt = 0
        while True:
            try:
                status, rh, body = self._transport("GET", url, headers, self.timeout)
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                if attempt >= self.retries:
                    raise Context7Error(f"network error: {e}") from e
                self._wait(attempt, None)
                attempt += 1
                continue
            self.last_rate_limit = RateLimit.from_headers(rh)
            if status in RETRY_STATUSES and attempt < self.retries:
                self._wait(attempt, rh)
                attempt += 1
                continue
            break
        data: Dict[str, Any] = {}
        if parse or status >= 300:
            try:
                data = json.loads(body) if body else {}
            except ValueError:
                data = {}
        if 200 <= status < 300:
            return status, data, body
        code = data.get("error", "") if isinstance(data, dict) else ""
        if allow and allow.get(status) == code:
            return status, data, body
        message = data.get("message") if isinstance(data, dict) else None
        raise Context7Error(message or f"HTTP {status}", status=status, code=code, rate_limit=self.last_rate_limit)

    def _wait(self, attempt: int, headers: Optional[Dict[str, str]]) -> None:
        delay = self.backoff * (2 ** attempt)
        if headers:
            low = {k.lower(): v for k, v in headers.items()}
            try:
                delay = max(delay, float(low.get("retry-after", "")))
            except ValueError:
                pass
        self._sleep(min(delay, 30.0))
