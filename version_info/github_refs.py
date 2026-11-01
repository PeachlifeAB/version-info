from __future__ import annotations

from .util_exec import run_argv

GIT_LS_REMOTE_ENV = {"GIT_TERMINAL_PROMPT": "0"}


def ls_remote(
    owner: str, repo: str, patterns: list[str], *, timeout_s: float
) -> dict[str, str] | None:
    """Resolve refs with git, which needs no API credential and has no API rate limit."""
    result = run_argv(
        ["git", "ls-remote", f"https://github.com/{owner}/{repo}", *patterns],
        timeout_s=timeout_s,
        env=GIT_LS_REMOTE_ENV,
    )
    if not result.ok:
        return None
    shas: dict[str, str] = {}
    for line in result.stdout.splitlines():
        sha, _, refname = line.partition("\t")
        shas.setdefault(refname, sha)
    return shas
