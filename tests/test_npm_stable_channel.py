from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from version_info.model import State
from version_info.registry_npm import npm_latest
from version_info.util_http import HttpResult


def test_npm_uses_higher_stable_tag_without_following_beta() -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "npm" / "latest-stable.json"
    metadata = json.loads(fixture_path.read_text(encoding="utf-8"))
    response = HttpResult(ok=True, status=200, text=None)
    with patch("version_info.registry_npm.get_json", return_value=(response, metadata)):
        artifact, state = npm_latest(metadata["name"], timeout_s=10.0, current_version="2.15.0")
    assert artifact.value == metadata["dist-tags"]["stable"]
    assert state == State.ok


@pytest.mark.parametrize("current", [None, "1.0.0"])
def test_npm_channel_comparison_fallbacks(current: str | None) -> None:
    fixture_path = Path(__file__).parent / "fixtures" / "npm" / "channel-comparison.json"
    cases = json.loads(fixture_path.read_text(encoding="utf-8"))
    for case in cases:
        tags = {key: value for key, value in case.items() if key in {"latest", "stable"}}
        metadata = {"dist-tags": tags}
        response = HttpResult(ok=True, status=200, text=None)
        with patch("version_info.registry_npm.get_json", return_value=(response, metadata)):
            artifact, state = npm_latest(case["name"], timeout_s=10.0, current_version=current)
        assert artifact.value == case["expected"], case["name"]
        assert state == State.ok, case["name"]
