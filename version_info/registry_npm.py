from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .util_http import get_json


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


def scan_npm(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    lock_path = Path(root) / "package-lock.json"
    if not lock_path.exists():
        return Section(title="Node (npm)", rows=[])

    deps = _parse_package_lock(lock_path.read_text(encoding="utf-8", errors="replace"))

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
            source="package-lock.json",
        )

    rows = map_bounded_ordered(deps, build_row, max_workers=lookup_concurrency)
    return Section(title="Node (npm)", rows=rows)
