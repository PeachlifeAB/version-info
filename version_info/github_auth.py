from __future__ import annotations

import os
from functools import cache

from .util_exec import run_argv

GH_AUTH_TOKEN_TIMEOUT_S = 5.0


def github_token() -> str | None:
    """GitHub credential: GITHUB_TOKEN, else the logged-in gh account, else None."""
    return _resolve(os.environ.get("GITHUB_TOKEN") or None)


@cache
def _resolve(env_token: str | None) -> str | None:
    if env_token:
        return env_token
    result = run_argv(["gh", "auth", "token"], timeout_s=GH_AUTH_TOKEN_TIMEOUT_S)
    token = result.stdout.strip()
    return token if result.ok and token else None
