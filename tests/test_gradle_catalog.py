from __future__ import annotations

from pathlib import Path
from shutil import copyfile
from unittest.mock import patch

from version_info.model import Artifact, SourceClass, State
from version_info.registry_gradle import maven_latest, scan_gradle
from version_info.scanners import SCANNERS
from version_info.util_http import HttpResult

CATALOG = "gradle/libs.versions.toml"
FIXTURE = Path(__file__).parent / "fixtures" / CATALOG


def test_catalog_discovery_and_library_versions(tmp_path: Path) -> None:
    catalog = tmp_path / CATALOG
    catalog.parent.mkdir()
    copyfile(FIXTURE, catalog)
    scanner = next(scanner for scanner in SCANNERS if scanner.name == "gradle")
    assert scanner.detect(str(tmp_path))
    with patch(
        "version_info.registry_gradle.maven_latest",
        return_value=(Artifact(value="99.0.0"), State.ok),
    ):
        section = scanner.scan_section(str(tmp_path), timeout_s=1)
    assert {row.name: row.current.value for row in section.rows} == {
        "androidx.core:core-ktx": "1.17.0",
        "junit:junit": "4.13.2",
        "org.jetbrains:annotations": "26.0.2",
    }
    assert all(row.source == CATALOG for row in section.rows)
    assert all(row.source_class == SourceClass.declared_manifest for row in section.rows)


def test_lockfile_and_catalog_preserve_distinct_sources(tmp_path: Path) -> None:
    catalog = tmp_path / CATALOG
    catalog.parent.mkdir()
    copyfile(FIXTURE, catalog)
    (tmp_path / "gradle.lockfile").write_text("junit:junit:4.13.1=runtime\n")
    with patch(
        "version_info.registry_gradle.maven_latest",
        return_value=(Artifact(value="99.0.0"), State.ok),
    ):
        section = scan_gradle(str(tmp_path), timeout_s=1)
    junit_rows = [row for row in section.rows if row.name == "junit:junit"]
    assert {row.source: row.current.value for row in junit_rows} == {
        "gradle.lockfile": "4.13.1",
        CATALOG: "4.13.2",
    }
    assert {row.source_class for row in junit_rows} == {
        SourceClass.resolved_lockfile,
        SourceClass.declared_manifest,
    }


def test_google_maven_fallback_after_central_not_found() -> None:
    metadata = "<metadata><versioning><release>1.17.0</release></versioning></metadata>"
    with patch("version_info.registry_gradle.get_text") as fetch:
        fetch.side_effect = [
            HttpResult(ok=False, status=404, text=None),
            HttpResult(ok=True, status=200, text=metadata),
        ]
        artifact, state = maven_latest("androidx.core", "core-ktx", timeout_s=1)
    assert state == State.ok
    assert artifact.value == "1.17.0"
    assert artifact.url == (
        "https://dl.google.com/dl/android/maven2/androidx/core/core-ktx/maven-metadata.xml"
    )
    assert fetch.call_count == 2
