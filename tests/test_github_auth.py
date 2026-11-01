from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest

from version_info import github_auth
from version_info.util_exec import ExecResult


def _gh_logged_in(token: str):
    calls: list[list[str]] = []

    def fake_run_argv(argv, **_):
        calls.append(argv)
        return ExecResult(True, token + "\n", "", 0)

    return fake_run_argv, calls


def test_logged_in_gh_wins_over_env_token(monkeypatch: pytest.MonkeyPatch):
    fake, calls = _gh_logged_in("from-gh")
    monkeypatch.setattr(github_auth, "run_argv", fake)
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")

    assert github_auth.github_token() == "from-gh"
    assert github_auth.github_token() == "from-gh"
    assert calls == [["gh", "auth", "token"]]


def test_env_token_is_the_fallback_when_gh_is_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GITHUB_TOKEN", "from-env")

    assert github_auth.github_token() == "from-env"


def test_concurrent_first_calls_invoke_gh_once(monkeypatch: pytest.MonkeyPatch):
    fake, calls = _gh_logged_in("from-gh")
    monkeypatch.setattr(github_auth, "run_argv", fake)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    with ThreadPoolExecutor(max_workers=8) as pool:
        tokens = list(pool.map(lambda _: github_auth.github_token(), range(16)))

    assert tokens == ["from-gh"] * 16
    assert len(calls) == 1


def test_no_credential_when_gh_missing_or_logged_out(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)

    assert github_auth.github_token() is None
