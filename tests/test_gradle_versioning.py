from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from version_info.gradle_versioning import compare_gradle, gradle_parts
from version_info.release_models import ReleaseStage
from version_info.release_policy import default_policy
from version_info.release_versions import release_stage


@dataclass(frozen=True)
class Comparison:
    left: str
    right: str
    expected: int
    valid: bool


@dataclass(frozen=True)
class Predicate:
    version: str
    expected: bool
    valid: bool = True


CAPTURED = json.loads(
    (Path(__file__).parent / "fixtures/selection/gradle-contract.json").read_text()
)
COMPARISONS = [Comparison(**row) for row in CAPTURED["comparisons"] if row["valid"]]
VALIDITY = [Predicate(**row) for row in CAPTURED["validity"]]
STABILITY = [Predicate(**row) for row in CAPTURED["stability"]]


@pytest.mark.parametrize("case", COMPARISONS)
def test_gradle_ordering_matches_native_contract(case: Comparison) -> None:
    assert compare_gradle(case.left, case.right, default_policy().gradle) == case.expected


@pytest.mark.parametrize("case", VALIDITY, ids=lambda case: case.version)
def test_gradle_single_version_validity_matches_native_contract(case: Predicate) -> None:
    if case.expected:
        assert gradle_parts(case.version, default_policy().gradle)
    else:
        with pytest.raises(ValueError):
            gradle_parts(case.version, default_policy().gradle)


@pytest.mark.parametrize("case", STABILITY, ids=lambda case: case.version)
def test_gradle_stability_matches_native_contract(case: Predicate) -> None:
    expected = ReleaseStage.stable if case.expected else ReleaseStage.preview
    if not case.valid:
        expected = ReleaseStage.unclassified
    assert release_stage(case.version, "gradle", default_policy()) == expected
