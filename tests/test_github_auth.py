from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

import pytest

from version_info import github_auth
from version_info.util_exec import ExecResult
from version_info.util_http import HttpResult, get_text, post_json

fake_envs: list[list[dict[str, str] | None]] = []


def _gh_logged_in(token: str):
    calls: list[list[str]] = []
    envs: list[dict[str, str] | None] = []
    fake_envs.append(envs)

    def fake_run_argv(argv, **kwargs):
        calls.append(argv)
        envs.append(kwargs.get("env"))
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


def test_non_github_requests_never_invoke_gh(monkeypatch: pytest.MonkeyPatch):
    fake, calls = _gh_logged_in("from-gh")
    monkeypatch.setattr(github_auth, "run_argv", fake)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    ok = HttpResult(ok=True, status=200, text="{}")

    with patch("version_info.util_http._send", return_value=ok):
        get_text("https://pypi.org/pypi/pytest/json", cache=False)
        post_json("https://example.com/graphql", {})

    assert calls == []


def test_github_requests_invoke_gh_once(monkeypatch: pytest.MonkeyPatch):
    fake, calls = _gh_logged_in("from-gh")
    monkeypatch.setattr(github_auth, "run_argv", fake)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    ok = HttpResult(ok=True, status=200, text="{}")

    with patch("version_info.util_http._send", return_value=ok):
        get_text("https://api.github.com/repos/o/r/tags", cache=False)
        get_text("https://api.github.com/repos/o/r2/tags", cache=False)

    assert calls == [["gh", "auth", "token"]]


def test_gh_is_asked_for_its_stored_login_not_an_echoed_env_token(monkeypatch: pytest.MonkeyPatch):
    fake, _ = _gh_logged_in("from-gh")
    monkeypatch.setattr(github_auth, "run_argv", fake)
    monkeypatch.setenv("GITHUB_TOKEN", "stale")

    github_auth.github_token()

    assert fake_envs[-1] == [{"GITHUB_TOKEN": "", "GH_TOKEN": ""}]
