from __future__ import annotations

import pytest

from version_info import github_auth
from version_info.util_exec import ExecResult


@pytest.fixture(autouse=True)
def _isolate_github_credential(monkeypatch: pytest.MonkeyPatch):
    github_auth._resolve.cache_clear()
    monkeypatch.setattr(github_auth, "run_argv", lambda *a, **k: ExecResult(False, "", "", 1))
    yield
    github_auth._resolve.cache_clear()
