from __future__ import annotations

import pytest

from version_info.main import parse_args

DEFAULT_CONCURRENCY = 16


def test_default_concurrency_matches_lookup_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERSION_INFO_CONCURRENCY", raising=False)

    assert parse_args([]).concurrency == DEFAULT_CONCURRENCY


def test_environment_overrides_default_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VERSION_INFO_CONCURRENCY", "3")

    assert parse_args([]).concurrency == 3
