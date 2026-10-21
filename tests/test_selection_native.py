from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from version_info.release_models import ReleaseCandidate, ReleaseStage
from version_info.release_policy import CompatibilityRule, default_policy
from version_info.release_selection import select_release


@dataclass(frozen=True)
class CapturedCandidate:
    version: str
    stable: bool
    compatible: bool
    eligible: bool


@dataclass(frozen=True)
class NativeCase:
    coordinate: str
    engine: str
    current: str
    highest_eligible: str | None
    eligible_versions: list[str]
    candidates: list[CapturedCandidate]


SNAPSHOT = json.loads(
    (Path(__file__).parent / "fixtures" / "selection" / "native-gradle.json").read_text()
)
CASES = [
    NativeCase(
        coordinate=case["coordinate"],
        engine=case["engine"],
        current=case["current"],
        highest_eligible=case["highest_eligible"],
        eligible_versions=case["eligible_versions"],
        candidates=[CapturedCandidate(**candidate) for candidate in case["candidates"]],
    )
    for case in SNAPSHOT["comparisons"]
]


@pytest.mark.parametrize("case", CASES, ids=lambda case: f"{case.coordinate}-{case.engine}")
def test_production_selection_agrees_with_captured_native_eligibility(case: NativeCase) -> None:
    policy = default_policy()
    if case.engine == "explicit-compatibility-regex":
        pattern = SNAPSHOT["config"]["compatibility_pattern"].replace("(?<", "(?P<")
        policy = replace(
            policy,
            compatibility=frozenset({
                CompatibilityRule("gradle", case.coordinate, re.compile(pattern))
            }),
        )
    result = select_release(
        ecosystem="gradle",
        package=case.coordinate,
        current=case.current,
        reported=None,
        candidates=[ReleaseCandidate(candidate.version) for candidate in case.candidates],
        complete=True,
        policy=policy,
    )
    assert result.chosen == case.highest_eligible
    assert [candidate.version for candidate in result.candidates] == [
        candidate.version for candidate in case.candidates
    ]
    assert sum(candidate.eligible for candidate in result.candidates) == len(case.eligible_versions)
    for decision, captured in zip(result.candidates, case.candidates, strict=True):
        assert decision.eligible is captured.eligible
        assert (decision.stage == ReleaseStage.stable) is captured.stable
