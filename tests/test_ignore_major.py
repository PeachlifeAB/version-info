from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from version_info.main import main, parse_args
from version_info.model import Artifact, DepRow, Section, State
from version_info.report import render


def sections() -> list[Section]:
    return [
        Section(
            title="Python (PyPI)",
            rows=[
                DepRow(
                    ecosystem="pypi",
                    name=name,
                    current=Artifact(value="1.0.0"),
                    latest=Artifact(value=latest),
                    state=State.update_available,
                    source="uv.lock",
                )
                for name, latest in [
                    ("major", "2.0.0"),
                    ("minor", "1.1.0"),
                    ("patch", "1.0.1"),
                    ("unknown", "commit-ref"),
                ]
            ],
        )
    ]


def test_flag_defaults_off() -> None:
    assert parse_args([]).ignore_major is False
    assert parse_args(["--ignore-major"]).ignore_major is True


@pytest.mark.parametrize("stale_only", [False, True])
def test_ignore_major_filters_only_known_major_updates(stale_only: bool) -> None:
    report = json.loads(
        render(sections(), json_output=True, stale_only=stale_only, ignore_major=True)
    )
    assert [row["name"] for row in report["sections"][0]["rows"]] == ["minor", "patch", "unknown"]
    table = render(sections(), stale_only=stale_only, ignore_major=True)
    assert "major" not in table
    for name in ["minor", "patch", "unknown"]:
        assert name in table
    assert "major" in render(sections(), stale_only=stale_only)


@pytest.mark.parametrize("json_output", [False, True])
def test_major_only_stale_report_removes_existing_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], json_output: bool
) -> None:
    output = tmp_path / "stale.json"
    output.write_text("previous report", encoding="utf-8")
    major_only = sections()
    major_only[0].rows[:] = major_only[0].rows[:1]
    argv = [str(tmp_path), "--stale", "--ignore-major", "--output-file", str(output)]
    if json_output:
        argv.append("--json")
    with (
        patch("version_info.main._scan_path", return_value=major_only),
        patch("version_info.main.scan_docker_install_sections", return_value=[]),
    ):
        assert main(argv) == 0
    assert not output.exists()
    captured = capsys.readouterr()
    if json_output:
        assert json.loads(captured.out)["sections"] == []
    else:
        assert captured.out == ""
        assert captured.err == "No matching updates.\n"
