from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .util_http import get_text

GRADLE_LOCKFILE_FILENAME = "gradle.lockfile"
MAVEN_CENTRAL_BASE_URL = "https://repo1.maven.org/maven2"
MAVEN_METADATA_FILENAME = "maven-metadata.xml"
EMPTY_CONFIGURATIONS_PREFIX = "empty="


@dataclass(frozen=True)
class GradleDep:
    group: str
    artifact: str
    version: str

    @property
    def coordinate(self) -> str:
        return f"{self.group}:{self.artifact}"


def _parse_gradle_lockfile(text: str) -> list[GradleDep]:
    """Parse gradle.lockfile lines of the form group:artifact:version=configuration,...

    Comment lines and the empty= line are skipped. The same coordinate locked in
    several configurations is reported once.
    """
    deps: dict[str, GradleDep] = {}
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or line.startswith(EMPTY_CONFIGURATIONS_PREFIX):
            continue
        coordinate = line.split("=", maxsplit=1)[0]
        parts = coordinate.split(":")
        if len(parts) != 3 or not all(parts):
            continue
        group, artifact, version = parts
        deps.setdefault(f"{group}:{artifact}", GradleDep(group, artifact, version))

    return sorted(deps.values(), key=lambda dep: dep.coordinate.lower())


def maven_latest(group: str, artifact: str, *, timeout_s: float) -> tuple[Artifact, State]:
    # Example: https://repo1.maven.org/maven2/com/google/guava/guava/maven-metadata.xml
    url = f"{MAVEN_CENTRAL_BASE_URL}/{group.replace('.', '/')}/{artifact}/{MAVEN_METADATA_FILENAME}"

    res = get_text(url, timeout_s=timeout_s)
    if res.ok and res.text:
        release = ElementTree.fromstring(res.text).findtext("versioning/release")  # noqa: S314
        if release:
            return Artifact(value=release, url=url), State.ok
        return Artifact(value=None, url=url, note="no release element"), State.error

    if res.status == 404:
        return Artifact(value=None, url=url, note="not found"), State.not_found
    if res.status == 429:
        return Artifact(value=None, url=url, note="rate limited"), State.rate_limited
    return Artifact(value=None, url=url, note=res.error or "http error"), State.error


def scan_gradle(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    lock_path = Path(root) / GRADLE_LOCKFILE_FILENAME
    if not lock_path.exists():
        return Section(title="Java (Gradle)", rows=[])

    deps = _parse_gradle_lockfile(lock_path.read_text(encoding="utf-8", errors="replace"))

    def build_row(dep: GradleDep) -> DepRow:
        latest, latest_state = maven_latest(dep.group, dep.artifact, timeout_s=timeout_s)

        state = State.ok
        if latest.value is not None and latest.value != dep.version:
            state = State.update_available
        elif latest_state != State.ok:
            state = latest_state

        return DepRow(
            ecosystem="gradle",
            name=dep.coordinate,
            current=Artifact(value=dep.version),
            latest=latest,
            state=state,
            source=GRADLE_LOCKFILE_FILENAME,
        )

    rows = map_bounded_ordered(deps, build_row, max_workers=lookup_concurrency)
    return Section(title="Java (Gradle)", rows=rows)
