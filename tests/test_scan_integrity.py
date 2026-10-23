from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

import pytest

from version_info.main import main
from version_info.model import Artifact, State
from version_info.registry_npm import scan_npm
from version_info.scanners import SCANNERS


def test_pnpm_stream_includes_dependencies_from_application_document(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "pnpm" / "multi-document.yaml"
    shutil.copyfile(fixture, tmp_path / "pnpm-lock.yaml")
    with patch(
        "version_info.registry_npm.npm_latest",
        return_value=(Artifact(value="4.6.7"), State.ok),
    ):
        section = scan_npm(str(tmp_path), timeout_s=1.0)
    assert [(row.name, row.current.value, row.latest.value) for row in section.rows] == [
        ("zod", "4.6.5", "4.6.7")
    ]
    assert section.rows[0].state == State.update_available


def test_failed_scanner_cannot_claim_all_latest_or_remove_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text("{", encoding="utf-8")
    output = tmp_path / "stale.json"
    previous_report = '{"sections": []}\n'
    output.write_text(previous_report, encoding="utf-8")
    npm_scanners = tuple(scanner for scanner in SCANNERS if scanner.name == "npm")
    with patch("version_info.main.SCANNERS", npm_scanners):
        result = main([str(tmp_path), "--stale", "--output-file", str(output)])
    captured = capsys.readouterr()
    assert result != 0
    assert "All dependencies are latest" not in captured.err + captured.out
    assert captured.err
    assert output.read_text(encoding="utf-8") == previous_report


def test_pnpm_workspace_stream_preserves_distinct_dependency_versions(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "pnpm" / "workspace-stream.yaml"
    shutil.copyfile(fixture, tmp_path / "pnpm-lock.yaml")
    with patch(
        "version_info.registry_npm.npm_latest",
        return_value=(Artifact(value="4.6.7"), State.ok),
    ):
        section = scan_npm(str(tmp_path), timeout_s=1.0)
    assert [(row.name, row.current.value) for row in section.rows] == [
        ("zod", "4.4.3"),
        ("zod", "4.6.5"),
    ]


@pytest.mark.parametrize("failure_boundary", ["detection", "docker"])
@pytest.mark.parametrize("argv", [[], ["--stale"], ["--stale", "--json"]])
def test_other_scan_failures_preserve_output(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    failure_boundary: str,
    argv: list[str],
) -> None:
    output = tmp_path / "report.json"
    previous_report = '{"sections": []}\n'
    output.write_text(previous_report, encoding="utf-8")
    target = (
        "version_info.scanners.ScannerDef.detect"
        if failure_boundary == "detection"
        else "version_info.main.scan_docker_install_sections"
    )
    with patch(target, side_effect=OSError("scan input unavailable")):
        result = main([str(tmp_path), *argv, "--output-file", str(output)])
    captured = capsys.readouterr()
    assert result != 0
    assert captured.out == ""
    assert "scan input unavailable" in captured.err
    assert "All dependencies are latest" not in captured.err
    assert output.read_text(encoding="utf-8") == previous_report
