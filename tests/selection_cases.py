from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from version_info.util_http import HttpResult


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


@contextmanager
def registry_boundary(case: RegistryCase) -> Iterator[None]:
    """Fake the network seam the case's ecosystem reads its registry through."""
    module = f"version_info.registry_{case.ecosystem}"
    with ExitStack() as stack:
        if case.ecosystem == "swiftpm":
            tags = {"refs": {"nodes": [{"name": tag["name"]} for tag in case.payload]}}
            stack.enter_context(patch(f"{module}.github_token", return_value="test-token"))
            stack.enter_context(
                patch(
                    f"{module}.query_repositories",
                    side_effect=lambda queries, **_: {q.key: tags for q in queries},
                )
            )
        elif isinstance(case.payload, str):
            stack.enter_context(
                patch(
                    f"{module}.get_text",
                    return_value=HttpResult(ok=True, status=200, text=case.payload),
                )
            )
        else:
            stack.enter_context(
                patch(
                    f"{module}.get_json",
                    return_value=(HttpResult(ok=True, status=200, text=None), case.payload),
                )
            )
        yield
