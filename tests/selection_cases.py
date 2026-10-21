from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RegistryCase:
    id: str
    ecosystem: str
    path: str
    project: str
    payload: dict[str, object] | list[dict[str, object]] | str
    expected: str
    candidate_count: int
    complete: bool


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "selection" / "cases.json"
CASES = [RegistryCase(**case) for case in json.loads(FIXTURE_PATH.read_text())["cases"]]
