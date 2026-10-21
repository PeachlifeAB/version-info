from __future__ import annotations

import importlib
from pathlib import Path
from unittest.mock import patch

import pytest

from selection_cases import CASES, RegistryCase
from version_info.util_http import HttpResult


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_registry_selection_retains_observed_candidates(case: RegistryCase, tmp_path: Path) -> None:
    project_file = tmp_path / case.path
    project_file.write_text(case.project, encoding="utf-8")
    registry = importlib.import_module(f"version_info.registry_{case.ecosystem}")
    scanner = getattr(registry, f"scan_{case.ecosystem}")
    if isinstance(case.payload, str):
        boundary = patch.object(
            registry, "get_text", return_value=HttpResult(ok=True, status=200, text=case.payload)
        )
    else:
        boundary = patch.object(
            registry,
            "get_json",
            return_value=(HttpResult(ok=True, status=200, text=None), case.payload),
        )
    with boundary:
        section = scanner(str(tmp_path), timeout_s=1)
    assert len(section.rows) == 1
    latest = section.rows[0].latest
    assert latest.value == case.expected
    assert latest.selection is not None
    assert len(latest.selection.candidates) == case.candidate_count
    assert latest.selection.complete is case.complete
    assert all(candidate.reason for candidate in latest.selection.candidates)
