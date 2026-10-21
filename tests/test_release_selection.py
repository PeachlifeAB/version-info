from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from version_info.release_models import ReleaseCandidate
from version_info.release_policy import default_policy
from version_info.release_selection import select_release


@dataclass(frozen=True)
class PolicyCase:
    id: str
    ecosystem: str
    package: str
    current: str
    reported: str | None
    candidates: list[ReleaseCandidate]
    chosen: str | None
    reasons: list[str]


CASES = [
    PolicyCase(**{
        **case,
        "candidates": [ReleaseCandidate(**candidate) for candidate in case["candidates"]],
    })
    for case in json.loads(
        (Path(__file__).parent / "fixtures/selection/policy-cases.json").read_text()
    )["cases"]
]


@pytest.mark.parametrize("case", CASES, ids=lambda case: case.id)
def test_selection_retains_candidates_and_reports_eligibility(case: PolicyCase) -> None:
    result = select_release(
        ecosystem=case.ecosystem,
        package=case.package,
        current=case.current,
        reported=case.reported,
        candidates=case.candidates,
        complete=False,
        policy=default_policy(),
    )
    assert result.chosen == case.chosen
    assert [candidate.version for candidate in result.candidates] == [
        candidate.version for candidate in case.candidates
    ]
    assert [candidate.reason.value for candidate in result.candidates] == case.reasons
