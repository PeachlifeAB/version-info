from __future__ import annotations

import os
import threading
from functools import cache

from .util_exec import run_argv

GH_AUTH_TOKEN_TIMEOUT_S = 5.0

STORED_LOGIN_ENV = {"GITHUB_TOKEN": "", "GH_TOKEN": ""}

_resolution_lock = threading.Lock()


def github_token() -> str | None:
    """GitHub credential: the logged-in gh account, else GITHUB_TOKEN, else None."""
    with _resolution_lock:
        return _resolve(os.environ.get("GITHUB_TOKEN") or None)


@cache
def _resolve(env_token: str | None) -> str | None:
    # gh echoes these variables back, which would hide the stored login behind a stale token.
    result = run_argv(
        ["gh", "auth", "token"], timeout_s=GH_AUTH_TOKEN_TIMEOUT_S, env=STORED_LOGIN_ENV
    )
    token = result.stdout.strip()
    return token if result.ok and token else env_token
