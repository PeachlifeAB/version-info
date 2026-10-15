from __future__ import annotations

import json

from version_info.main import parse_args
from version_info.model import Artifact, DepRow, Freshness, Section, State
from version_info.report import render


def _sections() -> list[Section]:
    return [
        Section(
            title="Python (PyPI)",
            rows=[
                DepRow(
                    ecosystem="pypi",
                    name="current-pkg",
                    current=Artifact(value="1.2.0"),
                    latest=Artifact(value="1.2.0"),
                    state=State.ok,
                    source="uv.lock",
                ),
                DepRow(
                    ecosystem="pypi",
                    name="minor-behind-pkg",
                    current=Artifact(value="1.2.0"),
                    latest=Artifact(value="1.3.0"),
                    state=State.update_available,
                    source="uv.lock",
                ),
                DepRow(
                    ecosystem="pypi",
                    name="unchecked-pkg",
                    current=Artifact(value="2.0.0"),
                    latest=Artifact(value=None, note="not found"),
                    state=State.not_found,
                    source="uv.lock",
                ),
            ],
        ),
    ]


def test_parse_args_stale_flag_defaults_off_and_turns_on() -> None:
    assert parse_args([]).stale is False
    assert parse_args(["--stale"]).stale is True


def test_render_json_stale_only_keeps_rows_not_confirmed_latest() -> None:
    """--stale keeps every row whose freshness is not latest, including unchecked rows."""
    output = json.loads(render(_sections(), json_output=True, stale_only=True))

    names = [row["name"] for section in output["sections"] for row in section["rows"]]
    freshness = [row["freshness"] for section in output["sections"] for row in section["rows"]]

    assert names == ["minor-behind-pkg", "unchecked-pkg"]
    assert freshness == [Freshness.minor_behind.value, Freshness.not_checked.value]


def test_render_table_stale_only_hides_confirmed_latest_rows() -> None:
    output = render(_sections(), stale_only=True)

    assert "minor-behind-pkg" in output
    assert "unchecked-pkg" in output
    assert "current-pkg" not in output


def test_render_without_stale_only_keeps_all_rows() -> None:
    output = json.loads(render(_sections(), json_output=True))

    names = [row["name"] for section in output["sections"] for row in section["rows"]]

    assert names == ["current-pkg", "minor-behind-pkg", "unchecked-pkg"]


def test_render_stale_only_says_when_everything_is_latest() -> None:
    latest_only = [
        Section(
            title="Python (PyPI)",
            rows=[
                DepRow(
                    ecosystem="pypi",
                    name="current-pkg",
                    current=Artifact(value="1.2.0"),
                    latest=Artifact(value="1.2.0"),
                    state=State.ok,
                    source="uv.lock",
                ),
            ],
        ),
    ]

    assert render(latest_only, stale_only=True) == "All dependencies are latest.\n"
