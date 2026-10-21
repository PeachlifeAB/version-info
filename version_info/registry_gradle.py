from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree

from .model import Artifact, DepRow, Section, SourceClass, State
from .parallel import map_bounded_ordered
from .release_models import ReleaseCandidate
from .release_policy import default_policy
from .release_selection import registry_selection
from .util_http import get_text

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

GRADLE_CATALOG_FILENAME = "gradle/libs.versions.toml"
GOOGLE_MAVEN_BASE_URL = "https://dl.google.com/dl/android/maven2"
GRADLE_LOCKFILE_FILENAME = "gradle.lockfile"
MAVEN_CENTRAL_BASE_URL = "https://repo1.maven.org/maven2"
MAVEN_METADATA_FILENAME = "maven-metadata.xml"
EMPTY_CONFIGURATIONS_PREFIX = "empty="


@dataclass(frozen=True)
class GradleDep:
    group: str
    artifact: str
    version: str
    source: str = GRADLE_LOCKFILE_FILENAME
    source_class: SourceClass = SourceClass.resolved_lockfile

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


def _parse_catalog(text: str) -> list[GradleDep]:
    catalog = tomllib.loads(text)
    versions = catalog.get("versions", {})
    deps: dict[str, GradleDep] = {}
    group: str | None
    artifact: str | None
    version: str | dict[str, str] | None
    for library in catalog.get("libraries", {}).values():
        if isinstance(library, str):
            parts = library.split(":")
            if len(parts) != 3:
                continue
            group, artifact, version = parts
        elif isinstance(library, dict):
            module = library.get("module")
            if isinstance(module, str):
                parts = module.split(":")
                if len(parts) != 2:
                    continue
                group, artifact = parts
            else:
                group, artifact = library.get("group"), library.get("name")
            version = library.get("version")
            if isinstance(version, dict):
                reference = version.get("ref")
                version = versions.get(reference) if isinstance(reference, str) else None
        else:
            continue
        if not all(isinstance(value, str) and value for value in (group, artifact, version)):
            continue
        if isinstance(group, str) and isinstance(artifact, str) and isinstance(version, str):
            dep = GradleDep(
                group, artifact, version, GRADLE_CATALOG_FILENAME, SourceClass.declared_manifest
            )
            deps.setdefault(dep.coordinate, dep)
    return sorted(deps.values(), key=lambda dep: dep.coordinate.lower())


def maven_latest(
    group: str, artifact: str, *, timeout_s: float, current_version: str | None = None
) -> tuple[Artifact, State]:
    # Example: https://repo1.maven.org/maven2/com/google/guava/guava/maven-metadata.xml
    url = f"{MAVEN_CENTRAL_BASE_URL}/{group.replace('.', '/')}/{artifact}/{MAVEN_METADATA_FILENAME}"

    res = get_text(url, timeout_s=timeout_s)
    if res.status == 404:
        url = (
            f"{GOOGLE_MAVEN_BASE_URL}/{group.replace('.', '/')}/{artifact}/"
            f"{MAVEN_METADATA_FILENAME}"
        )
        res = get_text(url, timeout_s=timeout_s)
    if res.ok and res.text:
        metadata = ElementTree.fromstring(res.text)  # noqa: S314
        release = metadata.findtext("versioning/release")
        candidates = [
            ReleaseCandidate(version.text)
            for version in metadata.findall("versioning/versions/version")
            if version.text is not None
        ]
        if release or candidates:
            selection = registry_selection(
                ecosystem="gradle",
                package=f"{group}:{artifact}",
                current=current_version,
                reported=release,
                candidates=candidates or [ReleaseCandidate(release or "")],
                complete=bool(candidates),
                url=url,
                policy=default_policy(),
            )
            return selection.artifact, selection.state
        return Artifact(value=None, url=url, note="no release element"), State.error

    if res.status == 404:
        return Artifact(value=None, url=url, note="not found"), State.not_found
    if res.status == 429:
        return Artifact(value=None, url=url, note="rate limited"), State.rate_limited
    return Artifact(value=None, url=url, note=res.error or "http error"), State.error


def scan_gradle(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    lock_path = Path(root) / GRADLE_LOCKFILE_FILENAME
    catalog_path = Path(root) / GRADLE_CATALOG_FILENAME
    deps: list[GradleDep] = []
    if lock_path.is_file():
        deps.extend(_parse_gradle_lockfile(lock_path.read_text(encoding="utf-8", errors="replace")))
    if catalog_path.is_file():
        deps.extend(_parse_catalog(catalog_path.read_text(encoding="utf-8")))

    def build_row(dep: GradleDep) -> DepRow:
        latest, latest_state = maven_latest(
            dep.group, dep.artifact, timeout_s=timeout_s, current_version=dep.version
        )

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
            source=dep.source,
            source_class=dep.source_class,
        )

    rows = map_bounded_ordered(deps, build_row, max_workers=lookup_concurrency)
    return Section(title="Java (Gradle)", rows=rows)
