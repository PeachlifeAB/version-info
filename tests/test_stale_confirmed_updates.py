from __future__ import annotations

import json

from version_info.model import Artifact, DepRow, Section, State
from version_info.report import STALE_STATES, render


def test_stale_output_requires_a_confirmed_newer_version() -> None:
    sections = [
        Section(
            title="Python (PyPI)",
            rows=[
                DepRow(
                    ecosystem="pypi",
                    name=state.value,
                    current=Artifact(value="1.0.0"),
                    latest=Artifact(value="1.1.0" if state == State.update_available else None),
                    state=state,
                    source="uv.lock",
                )
                for state in State
            ],
        )
    ]
    report = json.loads(render(sections, json_output=True, stale_only=True))
    names = [row["name"] for section in report["sections"] for row in section["rows"]]
    assert sorted(names) == sorted(state.value for state in STALE_STATES)
    table = render(sections, stale_only=True)
    for state in State:
        assert (state.value in table) == (state in STALE_STATES)
