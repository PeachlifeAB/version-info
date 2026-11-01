from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from .github_auth import github_token


@dataclass(frozen=True)
class HttpResult:
    ok: bool
    status: int | None
    text: str | None
    error: str | None = None
    headers: dict[str, list[str]] | None = None


class SimpleTtlCache:
    def __init__(self, ttl_s: float) -> None:
        self._ttl_s = ttl_s
        self._store: dict[str, tuple[float, HttpResult]] = {}

    def get(self, key: str) -> HttpResult | None:
        item = self._store.get(key)
        if item is None:
            return None
        expires_at, value = item
        if time.time() >= expires_at:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key: str, value: HttpResult) -> None:
        self._store[key] = (time.time() + self._ttl_s, value)


_cache = SimpleTtlCache(ttl_s=300.0)


def _collect_headers(items: Iterable[tuple[str, str]]) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    for key, value in items:
        headers.setdefault(key.lower(), []).append(value)
    return headers


def _should_send_github_token(url: str) -> bool:
    host = urlparse(url).hostname or ""
    return host == "api.github.com" or host.endswith(".github.com")


def _cache_key(
    url: str,
    headers: dict[str, str] | None,
    *,
    github_auth_enabled: bool,
) -> str:
    header_items = tuple(sorted((headers or {}).items()))
    return repr(("GET", url, header_items, github_auth_enabled))


def get_text(
    url: str,
    *,
    timeout_s: float = 10.0,
    headers: dict[str, str] | None = None,
    cache: bool = True,
) -> HttpResult:
    github_token_value = github_token()
    github_auth_enabled = bool(github_token_value) and _should_send_github_token(url)
    key = _cache_key(url, headers, github_auth_enabled=github_auth_enabled)
    if cache:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    req = urllib.request.Request(url, method="GET")
    _add_headers(req, headers, github_token_value if github_auth_enabled else None)
    result = _send(req, timeout_s=timeout_s)
    if cache and result.status is not None:
        _cache.set(key, result)
    return result


def post_json(
    url: str,
    payload: dict[str, Any],
    *,
    timeout_s: float = 10.0,
) -> tuple[HttpResult, Any]:
    token = github_token() if _should_send_github_token(url) else None
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), method="POST")
    _add_headers(req, {"Content-Type": "application/json"}, token)
    return _parse_json(_send(req, timeout_s=timeout_s))


def _add_headers(
    req: urllib.request.Request, headers: dict[str, str] | None, token: str | None
) -> None:
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for k, v in (headers or {}).items():
        req.add_header(k, v)


def _send(req: urllib.request.Request, *, timeout_s: float) -> HttpResult:
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            status = getattr(resp, "status", None)
            body = resp.read().decode("utf-8", errors="replace")
            return HttpResult(
                ok=True,
                status=status,
                text=body,
                headers=_collect_headers(resp.headers.items()),
            )
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        headers_dict = _collect_headers(e.headers.items()) if e.headers else {}
        return HttpResult(ok=False, status=e.code, text=body, error=str(e), headers=headers_dict)
    except urllib.error.URLError as e:
        return HttpResult(ok=False, status=None, text=None, error=str(e))


def get_json(
    url: str,
    *,
    timeout_s: float = 10.0,
    headers: dict[str, str] | None = None,
    cache: bool = True,
) -> tuple[HttpResult, Any]:
    return _parse_json(get_text(url, timeout_s=timeout_s, headers=headers, cache=cache))


def _parse_json(res: HttpResult) -> tuple[HttpResult, Any]:
    if not res.ok or res.text is None:
        return res, None
    try:
        return res, json.loads(res.text)
    except Exception as e:
        return HttpResult(
            ok=False,
            status=res.status,
            text=res.text,
            error=f"json parse: {e}",
            headers=res.headers,
        ), None
