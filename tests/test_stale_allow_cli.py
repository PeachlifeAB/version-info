from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from version_info.main import main
from version_info.util_http import HttpResult

FIXTURE = json.loads((Path(__file__).parent / "fixtures/stale-allow/case.json").read_text())
ALLOW_FILE = ".stale-versions-allow"


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "uv.lock").write_text(FIXTURE["project"], encoding="utf-8")
    return tmp_path


def _run(project: Path, arguments: list[str]) -> int:
    with patch(
        "version_info.registry_pypi.get_json",
        return_value=(HttpResult(ok=True, status=200, text=None), FIXTURE["payload"]),
    ):
        return main(arguments)


def _allow_arguments(project: Path) -> list[str]:
    record = FIXTURE["allowance"]
    return [
        "allow",
        record["dependency"],
        record["version"],
        "--reason",
        record["reason"],
        "--path",
        str(project),
    ]


def test_allow_command_generates_exact_record(project: Path) -> None:
    assert _run(project, _allow_arguments(project)) == 0
    assert json.loads((project / ALLOW_FILE).read_text()) == [FIXTURE["allowance"]]


@pytest.mark.parametrize("json_output", [False, True], ids=["table", "json"])
@pytest.mark.parametrize("existing_report", [False, True], ids=["new-report", "old-report"])
def test_allowed_only_update_has_no_report(
    project: Path, capsys: pytest.CaptureFixture[str], json_output: bool, existing_report: bool
) -> None:
    (project / ALLOW_FILE).write_text(json.dumps([FIXTURE["allowance"]]), encoding="utf-8")
    output = project / "stale-report.json"
    if existing_report:
        output.write_text("previous report", encoding="utf-8")
    arguments = [str(project), "--stale", "--output-file", str(output)]
    if json_output:
        arguments.append("--json")
    assert _run(project, arguments) == 0
    captured = capsys.readouterr()
    assert not output.exists()
    if json_output:
        assert json.loads(captured.out) == {"sections": []}
    else:
        assert captured.out == ""
        assert "All dependencies are latest" not in captured.err


@pytest.mark.parametrize("mismatch", FIXTURE["mismatches"])
@pytest.mark.parametrize("existing_policy", [False, True])
def test_nonmatching_request_suggests_without_writing(
    project: Path,
    capsys: pytest.CaptureFixture[str],
    mismatch: dict[str, str],
    existing_policy: bool,
) -> None:
    path = project / ALLOW_FILE
    original = json.dumps([FIXTURE["other_allowance"]])
    if existing_policy:
        path.write_text(original, encoding="utf-8")
    arguments = _allow_arguments(project)
    arguments[1:3] = [mismatch["dependency"], mismatch["version"]]
    assert _run(project, arguments) == 1
    captured = capsys.readouterr()
    assert "No matches found, did you mean coverage 7.16.2?" in captured.err
    assert captured.out == ""
    if existing_policy:
        assert path.read_text() == original
    else:
        assert not path.exists()


def test_allow_updates_reason_without_duplicates_or_lost_records(project: Path) -> None:
    path = project / ALLOW_FILE
    path.write_text(json.dumps([FIXTURE["allowance"], FIXTURE["other_allowance"]]))
    arguments = _allow_arguments(project)
    arguments[4] = FIXTURE["updated_reason"]
    assert _run(project, arguments) == 0
    assert _run(project, arguments) == 0
    expected = dict(FIXTURE["allowance"], reason=FIXTURE["updated_reason"])
    assert json.loads(path.read_text()) == [FIXTURE["other_allowance"], expected]


@pytest.mark.parametrize("reason", FIXTURE["short_reasons"])
def test_short_reason_rejected_before_lookup(project: Path, reason: str, capsys) -> None:
    arguments = _allow_arguments(project)
    arguments[4] = reason
    with patch("version_info.registry_pypi.get_json") as lookup:
        assert main(arguments) == 1
        lookup.assert_not_called()
    assert not (project / ALLOW_FILE).exists()
    assert "three" in capsys.readouterr().err


@pytest.mark.parametrize("entry", FIXTURE["invalid_entries"])
def test_invalid_entry_preserves_report(project: Path, entry: dict[str, object], capsys) -> None:
    (project / ALLOW_FILE).write_text(json.dumps([entry]), encoding="utf-8")
    output = project / "stale-report.json"
    output.write_text("previous report", encoding="utf-8")
    assert _run(project, [str(project), "--stale", "-o", str(output)]) == 1
    assert output.read_text() == "previous report"
    captured = capsys.readouterr()
    assert ALLOW_FILE in captured.err
    assert captured.out == ""


@pytest.mark.parametrize("document", FIXTURE["invalid_documents"])
def test_invalid_document_preserves_report(project: Path, document: str, capsys) -> None:
    (project / ALLOW_FILE).write_text(document, encoding="utf-8")
    output = project / "stale-report.json"
    output.write_text("previous report", encoding="utf-8")
    assert _run(project, [str(project), "--stale", "--json", "-o", str(output)]) == 1
    assert output.read_text() == "previous report"
    assert ALLOW_FILE in capsys.readouterr().err


@pytest.mark.parametrize("changed_version", [False, True])
def test_allowance_does_not_match_different_identity(
    project: Path, changed_version: bool, capsys
) -> None:
    allowance = FIXTURE["allowance"] if changed_version else FIXTURE["other_allowance"]
    (project / ALLOW_FILE).write_text(json.dumps([allowance]))
    if changed_version:
        (project / "uv.lock").write_text(FIXTURE["changed_project"])
    assert _run(project, [str(project), "--stale", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["sections"][0]["rows"][0]["name"] == "coverage"


@pytest.mark.parametrize("policy", [None, "valid", "invalid"])
def test_full_inventory_is_unaffected(project: Path, policy: str | None, capsys) -> None:
    if policy is not None:
        contents = json.dumps([FIXTURE["allowance"]]) if policy == "valid" else "{}"
        (project / ALLOW_FILE).write_text(contents)
    assert _run(project, [str(project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["sections"][0]["rows"][0]["name"] == "coverage"


def test_allow_uses_default_working_directory(
    project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(project)
    assert _run(project, _allow_arguments(project)[:-2]) == 0
    assert json.loads((project / ALLOW_FILE).read_text()) == [FIXTURE["allowance"]]


def test_root_allowance_covers_child_project(project: Path, capsys) -> None:
    child = project / "application"
    child.mkdir()
    (project / "uv.lock").rename(child / "uv.lock")
    assert _run(project, _allow_arguments(project)) == 0
    assert (project / ALLOW_FILE).exists()
    assert not (child / ALLOW_FILE).exists()
    assert _run(project, [str(project), "--stale", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == {"sections": []}


def test_allow_without_installed_dependencies_has_no_suggestion(tmp_path: Path, capsys) -> None:
    assert _run(tmp_path, _allow_arguments(tmp_path)) == 1
    assert "No matches found." in capsys.readouterr().err
    assert not (tmp_path / ALLOW_FILE).exists()


def test_other_stale_dependencies_remain_in_output(project: Path, capsys) -> None:
    child = project / "application"
    child.mkdir()
    (child / "uv.lock").write_text(FIXTURE["other_project"])
    (project / ALLOW_FILE).write_text(json.dumps([FIXTURE["allowance"]]))
    output = project / "stale-report.json"
    response = HttpResult(ok=True, status=200, text=None)
    with patch(
        "version_info.registry_pypi.get_json",
        side_effect=[(response, FIXTURE["payload"]), (response, FIXTURE["other_payload"])],
    ):
        assert main([str(project), "--stale", "--json", "-o", str(output)]) == 0
    captured = capsys.readouterr()
    assert json.loads(output.read_text()) == json.loads(captured.out)
    rows = json.loads(captured.out)["sections"][0]["rows"]
    assert [row["name"] for row in rows] == ["ruff"]
