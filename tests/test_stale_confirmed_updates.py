from __future__ import annotations

import json

from version_info.model import Artifact, DepRow, Section, State
from version_info.report import render


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
    assert names == [State.update_available.value]
    table = render(sections, stale_only=True)
    assert State.update_available.value in table
    for state in State:
        if state != State.update_available:
            assert state.value not in table
