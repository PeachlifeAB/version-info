from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .model import Artifact, DepRow, Section, SourceClass, State
from .parallel import map_bounded_ordered
from .util_http import get_json


@dataclass(frozen=True)
class PypiDep:
    name: str
    version: str
    local: bool = False


def _parse_requirements_txt(text: str) -> list[PypiDep]:
    """Parse a requirements.txt file and extract package names and versions.

    Supports exact pinned formats like:
    - package==1.2.3
    - # comments
    - -e git+https://... (editable installs - skipped)
    """
    deps: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()

        # Skip empty lines and comments
        if not line or line.startswith("#"):
            continue

        # Skip editable installs and other flags
        if line.startswith("-"):
            continue

        match = re.match(r"^([a-zA-Z0-9_.-]+)\s*==\s*([0-9][0-9a-zA-Z._-]*)", line)
        if match:
            name = match.group(1)
            version = match.group(2)
            if name and version:
                # Normalize package name to lowercase (PyPI convention)
                deps[name.lower()] = version

    return [PypiDep(name=n, version=v) for n, v in sorted(deps.items(), key=lambda kv: kv[0])]


def _scan_dep_array_line(stripped: str, add_dep: Callable[..., None]) -> bool:
    """Process a line that may contain dependency strings. Returns True if array closed."""
    for m in re.finditer(r'"([^"]+)"', stripped):
        _parse_pyproject_dependency_string(m.group(1), add_dep)
    return "]" in stripped


def _parse_pyproject_toml(text: str) -> list[PypiDep]:
    """Parse a pyproject.toml file and extract package names and versions.

    Handles [project.dependencies], [tool.poetry.dependencies], [dependency-groups].
    Uses regex only — no external TOML dependency.
    """
    deps: dict[str, PypiDep] = {}

    def add_dep(name: str, version: str, *, local: bool = False) -> None:
        if name and version:
            deps[name.lower()] = PypiDep(name=name.lower(), version=version, local=local)

    in_dependencies_section = False
    in_project_section = False
    in_dependency_array = False

    for line in text.splitlines():
        stripped = line.strip()

        if stripped == "[project]":
            in_project_section, in_dependencies_section, in_dependency_array = True, False, False
            continue

        is_dep_section = stripped in (
            "[project.dependencies]",
            "[tool.poetry.dependencies]",
        ) or stripped.startswith("[dependency-groups")
        if is_dep_section:
            in_project_section, in_dependencies_section = False, True
            continue

        if stripped.startswith("[") and not stripped.startswith("[["):
            in_project_section, in_dependencies_section, in_dependency_array = False, False, False
            continue

        deps_line = re.match(r"^dependencies\s*(?:=|\[|$)", stripped) and "[" in stripped
        if in_project_section and deps_line:
            in_dependency_array = True
            in_dependency_array = not _scan_dep_array_line(stripped, add_dep)
            continue

        if in_dependency_array:
            if _scan_dep_array_line(stripped, add_dep):
                in_dependency_array = False
            continue

        if not in_dependencies_section:
            continue

        m = re.match(r'^\s*"([a-zA-Z0-9_.-]+)\s*==\s*([0-9][0-9a-zA-Z._-]*)"', stripped)
        if m:
            add_dep(m.group(1), m.group(2))
            continue
        m = re.match(r'^([a-zA-Z0-9_.-]+)\s*=\s*"(?:==)?([0-9][0-9a-zA-Z._-]*)"', stripped)
        if m:
            add_dep(m.group(1), m.group(2))

    return [dep for _, dep in sorted(deps.items(), key=lambda kv: kv[0])]


def _parse_pyproject_dependency_string(
    dependency: str,
    add_dep: Callable[..., None],
) -> None:
    exact_match = re.match(r"^([a-zA-Z0-9_.-]+)\s*==\s*([0-9][0-9a-zA-Z._-]*)", dependency)
    if exact_match:
        add_dep(exact_match.group(1), exact_match.group(2))
        return

    direct_match = re.match(r"^([a-zA-Z0-9_.-]+)\s*@\s*(git\+.+)", dependency)
    if direct_match:
        add_dep(direct_match.group(1), "git", local=True)


def _parse_uv_lock(text: str) -> list[PypiDep]:
    """Parse a uv.lock file and extract package names and versions.

    uv.lock format uses TOML with [[package]] sections containing name and version.
    Example:
        [[package]]
        name = "colorama"
        version = "0.4.6"
    """
    deps: dict[str, PypiDep] = {}
    lines = text.splitlines()
    current_name: str | None = None
    current_version: str | None = None
    current_local = False

    def flush_current() -> None:
        nonlocal current_name, current_version, current_local
        if current_name and current_version:
            deps[current_name] = PypiDep(
                name=current_name,
                version=current_version,
                local=current_local,
            )
        current_name = None
        current_version = None
        current_local = False

    for line in lines:
        stripped = line.strip()

        # Start of a new package block
        if stripped == "[[package]]":
            flush_current()
            continue

        # Extract package name
        name_match = re.match(r'^name\s*=\s*"([^"]+)"', stripped)
        if name_match:
            current_name = name_match.group(1).lower()
            continue

        # Extract version (only if we have a current name)
        if current_name:
            version_match = re.match(r'^version\s*=\s*"([^"]+)"', stripped)
            if version_match:
                current_version = version_match.group(1)
                continue

            source_match = re.match(r"^source\s*=\s*\{(.+)\}", stripped)
            if source_match:
                source_body = source_match.group(1)
                source_keys = {
                    entry.split("=", 1)[0].split(":", 1)[0].strip()
                    for entry in source_body.split(",")
                    if entry.strip()
                }
                current_local = any(key in ("editable", "path", "git") for key in source_keys)

    flush_current()

    return [dep for _, dep in sorted(deps.items(), key=lambda kv: kv[0])]


def _parse_poetry_lock(text: str) -> list[PypiDep]:
    """Parse a poetry.lock file and extract package names and versions.

    poetry.lock format uses TOML with [[package]] sections containing name and version.
    Example:
        [[package]]
        name = "colorama"
        version = "0.4.6"

    This is the same format as uv.lock, so we reuse the same parser.
    """
    return _parse_uv_lock(text)


def pypi_latest(name: str, *, timeout_s: float) -> tuple[Artifact, State]:
    """Fetch the latest version of a package from PyPI.

    PyPI JSON API: https://pypi.org/pypi/{package_name}/json
    """
    # Normalize package name (PyPI is case-insensitive)
    normalized_name = name.lower()
    url = f"https://pypi.org/pypi/{normalized_name}/json"

    res, data = get_json(url, timeout_s=timeout_s)
    if res.ok and isinstance(data, dict):
        info = data.get("info")
        if isinstance(info, dict):
            version = info.get("version")
            if isinstance(version, str) and version:
                return Artifact(value=version, url=url), State.ok
        return Artifact(value=None, url=url, note="no version in response"), State.error

    if res.status == 404:
        return Artifact(value=None, url=url, note="not found"), State.not_found
    if res.status in (401, 403):
        return Artifact(value=None, url=url, note="auth required"), State.auth_required
    if res.status == 429:
        return Artifact(value=None, url=url, note="rate limited"), State.rate_limited
    return Artifact(value=None, url=url, note=res.error or "http error"), State.error


def scan_pypi(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    """Scan for Python dependencies in lockfiles and dependency files.

    Priority order (lockfile-first approach):
    1. uv.lock
    2. poetry.lock
    3. requirements.txt
    4. pyproject.toml
    """
    deps: list[PypiDep] = []
    source = None
    source_class = SourceClass.declared_manifest

    root_path = Path(root)
    candidates: list[tuple[str, Callable[[str], list[PypiDep]], SourceClass]] = [
        ("uv.lock", _parse_uv_lock, SourceClass.resolved_lockfile),
        ("poetry.lock", _parse_poetry_lock, SourceClass.resolved_lockfile),
        ("requirements.txt", _parse_requirements_txt, SourceClass.declared_manifest),
        ("pyproject.toml", _parse_pyproject_toml, SourceClass.declared_manifest),
    ]
    for filename, parser, sc in candidates:
        p = root_path / filename
        if p.exists():
            parsed = parser(p.read_text(encoding="utf-8", errors="replace"))
            if parsed:
                deps, source, source_class = parsed, filename, sc
                break

    # No Python dependency files found
    if not deps or source is None:
        return Section(title="Python (PyPI)", rows=[])

    def build_row(d: PypiDep) -> DepRow:
        if d.local:
            latest = Artifact(value=None, note="local")
            state = State.local_only
        else:
            latest, latest_state = pypi_latest(d.name, timeout_s=timeout_s)

            state = State.ok
            if latest.value is not None and latest.value != d.version:
                state = State.update_available
            elif latest_state != State.ok:
                state = latest_state

        return DepRow(
            ecosystem="pypi",
            name=d.name,
            current=Artifact(value=d.version),
            latest=latest,
            state=state,
            source=source,
            source_class=source_class,
        )

    rows = map_bounded_ordered(deps, build_row, max_workers=lookup_concurrency)
    return Section(title="Python (PyPI)", rows=rows)
