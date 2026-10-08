from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+][0-9A-Za-z.-]+)?$")
_HEX_RE = re.compile(r"^(?:sha256:)?(?=[a-f0-9]*[a-f])[a-f0-9]{7,}$")


def _parse_semver(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped or _HEX_RE.match(stripped):
        return None
    match = _VERSION_RE.match(stripped)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2) or 0), int(match.group(3) or 0)


class State(str, Enum):
    ok = "ok"
    update_available = "update_available"
    pinned = "pinned"
    not_applicable = "not_applicable"
    auth_required = "auth_required"
    rate_limited = "rate_limited"
    not_found = "not_found"
    local_only = "local_only"
    error = "error"


class SourceClass(str, Enum):
    resolved_lockfile = "resolved_lockfile"
    declared_manifest = "declared_manifest"
    runtime_tool = "runtime_tool"
    container_runtime = "container_runtime"


class Freshness(str, Enum):
    latest = "latest"
    major_behind = "major_behind"
    minor_behind = "minor_behind"
    patch_behind = "patch_behind"
    uncomparable = "uncomparable"
    not_checked = "not_checked"


@dataclass(frozen=True)
class Artifact:
    """A resolved artifact representation.

    "value" is the thing we compare and display (version, rev, digest).
    "url" is where it comes from (package page, git remote, registry endpoint).
    "note" is a short reason context when value is not present.

    Constraint: We avoid printing literal "unknown". If a value cannot be
    determined, represent that with note+state.
    """

    value: str | None
    url: str | None = None
    note: str | None = None


@dataclass(frozen=True)
class DepRow:
    ecosystem: str
    name: str
    current: Artifact
    latest: Artifact
    state: State
    source: str
    source_class: SourceClass = SourceClass.resolved_lockfile
    freshness: Freshness = Freshness.not_checked
    note: str | None = None

    def __post_init__(self) -> None:
        if self.freshness != Freshness.not_checked:
            return
        if self.state == State.ok:
            object.__setattr__(self, "freshness", Freshness.latest)
        elif self.state == State.update_available:
            if self.current.value is None or self.latest.value is None:
                object.__setattr__(self, "freshness", Freshness.uncomparable)
                return
            cur = _parse_semver(self.current.value)
            lat = _parse_semver(self.latest.value)
            if cur is None or lat is None:
                freshness = Freshness.uncomparable
            elif lat[0] > cur[0]:
                freshness = Freshness.major_behind
            elif lat[1] > cur[1]:
                freshness = Freshness.minor_behind
            else:
                freshness = Freshness.patch_behind
            object.__setattr__(self, "freshness", freshness)


@dataclass(frozen=True)
class Section:
    title: str
    rows: list[DepRow]


@dataclass(frozen=True)
class InstallPin:
    """A package install extracted from a Dockerfile RUN command.

    raw_spec is the version constraint exactly as written (e.g. ">=1.0.9,<2.0.0").
    resolved_version is set only when raw_spec is an exact pin (e.g. "==1.0.1" -> "1.0.1").
    ecosystem is the native ecosystem (pypi, npm, go, cargo, ruby).
    source is the relative Dockerfile path for SOURCE column display.
    """

    name: str
    raw_spec: str
    resolved_version: str | None
    ecosystem: str
    source: str


@dataclass(frozen=True)
class ArtifactAnnotation:
    """A Dockerfile comment annotation identifying a local build artifact dependency.

    Supports:
    - # version-info: datasource=pypi depName=cognee artifact=cognee-api
    - # renovate: datasource=pypi depName=cognee ...
    """

    datasource: str
    dep_name: str
    artifact_name: str | None
    annotation_source: str  # "version-info" or "renovate"
    source_path: str
