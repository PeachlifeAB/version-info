from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path
from unittest.mock import patch

import pytest
from jsonschema import Draft202012Validator

from selection_cases import CASES, RegistryCase
from version_info.main import main
from version_info.util_http import HttpResult


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_cli_json_exposes_selection_without_losing_candidates(
    case: RegistryCase, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / case.path).write_text(case.project, encoding="utf-8")
    module = f"version_info.registry_{case.ecosystem}"
    if isinstance(case.payload, str):
        boundary = patch(
            f"{module}.get_text", return_value=HttpResult(ok=True, status=200, text=case.payload)
        )
    else:
        boundary = patch(
            f"{module}.get_json",
            return_value=(HttpResult(ok=True, status=200, text=None), case.payload),
        )
    with boundary:
        assert main([str(tmp_path), "--json", "--concurrency", "1"]) == 0
    report = json.loads(capsys.readouterr().out)
    rows = [row for section in report["sections"] for row in section["rows"]]
    assert len(rows) == 1
    assert rows[0]["latest"] == case.expected
    selection = rows[0]["selection"]
    assert len(selection["candidates"]) == case.candidate_count
    assert selection["complete"] is case.complete
    schema = json.loads(
        files("version_info").joinpath("data/release-selection.schema.json").read_text()
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(selection)


def test_cli_stale_does_not_report_a_backend_downgrade(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    case = next(case for case in CASES if case.id == "go-no-downgrade")
    (tmp_path / case.path).write_text(case.project, encoding="utf-8")
    with patch(
        "version_info.registry_go.get_json",
        return_value=(HttpResult(ok=True, status=200, text=None), case.payload),
    ):
        assert main([str(tmp_path), "--json", "--stale", "--concurrency", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["sections"] == []
