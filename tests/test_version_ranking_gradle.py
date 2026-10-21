from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch
from xml.etree import ElementTree

from version_info.registry_gradle import scan_gradle
from version_info.util_http import HttpResult

FIXTURE_ROOT = (
    Path(__file__).parent / "fixtures" / "version-ranking" / "gradle" / "activity-compose"
)


@dataclass(frozen=True)
class CapturedVersionCase:
    coordinate: str
    current: str
    reported: str
    preferred: str
    central_url: str
    google_url: str
    source_repository: str
    source_revision: str
    source_path: str
    captured_at_utc: str


def test_stable_gradle_dependency_prefers_available_stable_update() -> None:
    case = CapturedVersionCase(**json.loads((FIXTURE_ROOT / "case.json").read_text()))
    metadata = (FIXTURE_ROOT / "maven-metadata.xml").read_text(encoding="utf-8")
    published_versions = [
        version.text
        for version in ElementTree.fromstring(metadata).findall("versioning/versions/version")
    ]
    assert case.preferred in published_versions
    assert case.reported in published_versions

    def fetch_captured_metadata(url: str, *, timeout_s: float) -> HttpResult:
        if url == case.central_url:
            return HttpResult(ok=False, status=404, text=None)
        assert url == case.google_url
        return HttpResult(ok=True, status=200, text=metadata)

    with patch("version_info.registry_gradle.get_text", side_effect=fetch_captured_metadata):
        section = scan_gradle(str(FIXTURE_ROOT / "project"), timeout_s=1)

    assert len(section.rows) == 1
    dependency = section.rows[0]
    assert dependency.name == case.coordinate
    assert dependency.current.value == case.current
    assert dependency.latest.value == case.preferred
