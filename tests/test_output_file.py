from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from version_info.main import main
from version_info.model import Artifact, DepRow, Section, State
from version_info.report import ALL_LATEST_MESSAGE

OUTPUT_FILE_NAME = ".stale-versions"
OUTPUT_JSON_FILE_NAME = ".stale-versions.json"


def _sections(*, with_stale: bool) -> list[Section]:
    rows = [
        DepRow(
            ecosystem="pypi",
            name="current-pkg",
            current=Artifact(value="1.2.0"),
            latest=Artifact(value="1.2.0"),
            state=State.ok,
            source="uv.lock",
        ),
    ]
    if with_stale:
        rows.append(
            DepRow(
                ecosystem="pypi",
                name="minor-behind-pkg",
                current=Artifact(value="1.2.0"),
                latest=Artifact(value="1.3.0"),
                state=State.update_available,
                source="uv.lock",
            )
        )
    return [Section(title="Python (PyPI)", rows=rows)]


def _run(
    project: Path,
    argv: list[str],
    *,
    sections: list[Section],
    capsys: pytest.CaptureFixture[str],
) -> tuple[str, str]:
    with (
        patch("version_info.main._scan_path", return_value=sections),
        patch("version_info.main.scan_docker_install_sections", return_value=[]),
    ):
        exit_code = main([str(project), *argv])
    assert exit_code == 0
    captured = capsys.readouterr()
    return captured.out, captured.err


def test_full_report_written_without_stale(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / OUTPUT_FILE_NAME
    stdout, _ = _run(
        tmp_path,
        ["--output-file", str(output_path)],
        sections=_sections(with_stale=True),
        capsys=capsys,
    )

    assert output_path.read_text(encoding="utf-8") == stdout
    assert "current-pkg" in output_path.read_text(encoding="utf-8")


def test_stale_report_written_when_rows_stale(tmp_path: Path, capsys) -> None:
    output_path = tmp_path / OUTPUT_FILE_NAME
    _run(
        tmp_path,
        ["--stale", "--output-file", str(output_path)],
        sections=_sections(with_stale=True),
        capsys=capsys,
    )

    text = output_path.read_text(encoding="utf-8")
    assert "minor-behind-pkg" in text
    assert "current-pkg" not in text


def test_no_output_file_when_stale_rows_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / OUTPUT_FILE_NAME

    stdout, stderr = _run(
        tmp_path,
        ["--stale", "--output-file", str(output_path)],
        sections=_sections(with_stale=False),
        capsys=capsys,
    )

    assert not output_path.exists()
    assert stdout == ""
    assert stderr == ALL_LATEST_MESSAGE


def test_old_output_file_removed_when_stale_rows_absent(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / OUTPUT_FILE_NAME
    output_path.write_text("old stale report", encoding="utf-8")

    _run(
        tmp_path,
        ["--stale", "--output-file", str(output_path)],
        sections=_sections(with_stale=False),
        capsys=capsys,
    )

    assert not output_path.exists()


def test_json_stale_report_written_to_output_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    output_path = tmp_path / OUTPUT_JSON_FILE_NAME
    _run(
        tmp_path,
        ["--json", "--stale", "--output-file", str(output_path)],
        sections=_sections(with_stale=True),
        capsys=capsys,
    )

    names = [
        row["name"]
        for section in json.loads(output_path.read_text(encoding="utf-8"))["sections"]
        for row in section["rows"]
    ]
    assert names == ["minor-behind-pkg"]


def test_json_stale_without_rows_writes_no_file(tmp_path: Path, capsys) -> None:
    output_path = tmp_path / OUTPUT_JSON_FILE_NAME

    stdout, stderr = _run(
        tmp_path,
        ["--json", "--stale", "--output-file", str(output_path)],
        sections=_sections(with_stale=False),
        capsys=capsys,
    )

    assert not output_path.exists()
    assert json.loads(stdout) == {"sections": []}
    assert stderr == ""
