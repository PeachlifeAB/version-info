from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .util_http import get_json

PACKAGE_LOCK_FILENAME = "package-lock.json"
PNPM_LOCK_FILENAME = "pnpm-lock.yaml"


@dataclass(frozen=True)
class NpmDep:
    name: str
    version: str


def _package_name_from_lock_path(path: str) -> str | None:
    """Extract the package name from an npm package-lock packages path."""
    marker = "node_modules/"
    if marker not in path:
        return None
    candidate = path.rsplit(marker, maxsplit=1)[-1]
    parts = [part for part in candidate.split("/") if part]
    if not parts:
        return None
    if parts[0].startswith("@"):
        if len(parts) < 2:
            return None
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def _direct_deps_v2(packages: dict[str, object]) -> set[str]:
    root_meta = packages.get("") or {}
    direct: set[str] = set()
    if isinstance(root_meta, dict):
        for key in ("dependencies", "devDependencies"):
            section = root_meta.get(key)
            if isinstance(section, dict):
                direct.update(section.keys())
    return direct


def _parse_package_lock(text: str) -> list[NpmDep]:
    data = json.loads(text)
    deps: dict[str, str] = {}

    packages = data.get("packages")
    if isinstance(packages, dict):
        direct_deps = _direct_deps_v2(packages)
        for path, meta in packages.items():
            if not path or not isinstance(path, str) or not path.startswith("node_modules/"):
                continue
            if not isinstance(meta, dict):
                continue
            name = _package_name_from_lock_path(path)
            version = meta.get("version")
            if (
                isinstance(name, str)
                and isinstance(version, str)
                and name
                and version
                and (not direct_deps or name in direct_deps)
            ):
                deps[name] = version

    if not deps:
        for name, meta in (data.get("dependencies") or {}).items():
            if not isinstance(meta, dict):
                continue
            version = meta.get("version")
            if isinstance(name, str) and isinstance(version, str) and name and version:
                deps[name] = version

    return [
        NpmDep(name=n, version=v) for n, v in sorted(deps.items(), key=lambda kv: kv[0].lower())
    ]


def _pnpm_direct_dependency_sections(data: dict[str, object]) -> list[dict[str, object]]:
    importers = data.get("importers")
    if isinstance(importers, dict):
        root_importer = importers.get(".")
        return [root_importer] if isinstance(root_importer, dict) else []
    return [data]


def _parse_pnpm_lock(text: str) -> list[NpmDep]:
    """Parse direct root dependencies from pnpm-lock.yaml (v6 top-level, v9 importers)."""
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        return []

    deps: dict[str, str] = {}
    for section in _pnpm_direct_dependency_sections(data):
        for key in ("dependencies", "devDependencies"):
            entries = section.get(key)
            if not isinstance(entries, dict):
                continue
            for name, entry in entries.items():
                if not isinstance(entry, dict):
                    continue
                version = entry.get("version")
                if not isinstance(version, str):
                    continue
                resolved = version.split("(", maxsplit=1)[0]
                if not resolved or ":" in resolved:
                    continue
                deps[str(name)] = resolved

    return [
        NpmDep(name=n, version=v) for n, v in sorted(deps.items(), key=lambda kv: kv[0].lower())
    ]


def npm_latest(name: str, *, timeout_s: float) -> tuple[Artifact, State]:
    # Unscoped: https://registry.npmjs.org/lodash
    # Scoped:   https://registry.npmjs.org/@types%2Fnode
    encoded = name.replace("/", "%2F")
    url = f"https://registry.npmjs.org/{encoded}"

    res, data = get_json(url, timeout_s=timeout_s)
    if res.ok and isinstance(data, dict):
        dist_tags = data.get("dist-tags")
        if isinstance(dist_tags, dict):
            latest = dist_tags.get("latest")
            if isinstance(latest, str) and latest:
                return Artifact(value=latest, url=url), State.ok
        return Artifact(value=None, url=url, note="no dist-tag latest"), State.error

    if res.status == 404:
        return Artifact(value=None, url=url, note="not found"), State.not_found
    if res.status in (401, 403):
        return Artifact(value=None, url=url, note="auth required"), State.auth_required
    if res.status == 429:
        return Artifact(value=None, url=url, note="rate limited"), State.rate_limited
    return Artifact(value=None, url=url, note=res.error or "http error"), State.error


def _read_npm_lockfile(root: str) -> tuple[str, list[NpmDep]] | None:
    package_lock_path = Path(root) / PACKAGE_LOCK_FILENAME
    if package_lock_path.exists():
        text = package_lock_path.read_text(encoding="utf-8", errors="replace")
        return PACKAGE_LOCK_FILENAME, _parse_package_lock(text)

    pnpm_lock_path = Path(root) / PNPM_LOCK_FILENAME
    if pnpm_lock_path.exists():
        text = pnpm_lock_path.read_text(encoding="utf-8", errors="replace")
        return PNPM_LOCK_FILENAME, _parse_pnpm_lock(text)

    return None


def scan_npm(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    lockfile = _read_npm_lockfile(root)
    if lockfile is None:
        return Section(title="Node (npm)", rows=[])

    source, deps = lockfile

    def build_row(d: NpmDep) -> DepRow:
        latest, latest_state = npm_latest(d.name, timeout_s=timeout_s)

        state = State.ok
        if latest.value is not None and latest.value != d.version:
            state = State.update_available
        elif latest_state != State.ok:
            state = latest_state

        return DepRow(
            ecosystem="npm",
            name=d.name,
            current=Artifact(value=d.version),
            latest=latest,
            state=state,
            source=source,
        )

    rows = map_bounded_ordered(deps, build_row, max_workers=lookup_concurrency)
    return Section(title="Node (npm)", rows=rows)
