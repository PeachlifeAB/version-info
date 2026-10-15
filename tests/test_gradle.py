from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from version_info.model import Artifact, State
from version_info.registry_gradle import _parse_gradle_lockfile, maven_latest, scan_gradle
from version_info.util_http import HttpResult

GRADLE_LOCKFILE = """\
# This is a Gradle generated file for dependency locking.
# Manual edits can break the build and are not advised.
# This file is expected to be part of source control.
com.google.guava:guava:31.1-jre=compileClasspath,runtimeClasspath
org.jetbrains:annotations:13.0=compileClasspath
com.google.guava:guava:31.1-jre=testRuntimeClasspath
empty=annotationProcessor,testAnnotationProcessor
"""

MAVEN_METADATA_GUAVA = """\
<?xml version="1.0" encoding="UTF-8"?>
<metadata>
  <groupId>com.google.guava</groupId>
  <artifactId>guava</artifactId>
  <versioning>
    <release>33.4.0-jre</release>
    <versions>
      <version>31.1-jre</version>
      <version>33.4.0-jre</version>
    </versions>
  </versioning>
</metadata>
"""


def test_parse_gradle_lockfile_skips_comments_and_empty_configurations() -> None:
    """Comments and empty= lines drop out; a coordinate locked in many configurations collapses."""
    deps = _parse_gradle_lockfile(GRADLE_LOCKFILE)

    assert [(dep.group, dep.artifact, dep.version) for dep in deps] == [
        ("com.google.guava", "guava", "31.1-jre"),
        ("org.jetbrains", "annotations", "13.0"),
    ]


def test_maven_latest_reads_release_from_metadata() -> None:
    """Latest comes from the release element of maven-metadata.xml on Maven Central."""
    with patch("version_info.registry_gradle.get_text") as mock_get_text:
        mock_get_text.return_value = HttpResult(ok=True, status=200, text=MAVEN_METADATA_GUAVA)

        artifact, state = maven_latest("com.google.guava", "guava", timeout_s=10.0)

        assert artifact.value == "33.4.0-jre"
        assert artifact.url == (
            "https://repo1.maven.org/maven2/com/google/guava/guava/maven-metadata.xml"
        )
        assert state == State.ok
        mock_get_text.assert_called_once_with(artifact.url, timeout_s=10.0)


def test_maven_latest_not_found() -> None:
    """A 404 from Maven Central means the coordinate does not exist."""
    with patch("version_info.registry_gradle.get_text") as mock_get_text:
        mock_get_text.return_value = HttpResult(ok=False, status=404, text=None, error="not found")

        artifact, state = maven_latest("com.example", "missing", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "not found"
        assert state == State.not_found


def test_scan_gradle_reports_rows_from_gradle_lockfile(tmp_path: Path) -> None:
    """scan_gradle turns each lockfile coordinate into a gradle row with its Maven latest."""
    (tmp_path / "gradle.lockfile").write_text(GRADLE_LOCKFILE, encoding="utf-8")

    with patch(
        "version_info.registry_gradle.maven_latest",
        return_value=(Artifact(value="33.4.0-jre", url="https://repo1.maven.org/x"), State.ok),
    ):
        section = scan_gradle(str(tmp_path), timeout_s=10.0)

    assert section.title == "Java (Gradle)"
    assert [(row.ecosystem, row.name, row.current.value, row.state) for row in section.rows] == [
        ("gradle", "com.google.guava:guava", "31.1-jre", State.update_available),
        ("gradle", "org.jetbrains:annotations", "13.0", State.update_available),
    ]
    assert section.rows[0].source == "gradle.lockfile"
