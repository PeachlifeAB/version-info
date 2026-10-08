from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .model import Artifact, DepRow, Section, SourceClass, State
from .parallel import map_bounded_ordered
from .util_http import get_json


@dataclass(frozen=True)
class GoDep:
    name: str
    version: str


def _parse_go_sum(text: str) -> list[GoDep]:
    """Parse a go.sum file and extract module names and versions.

    go.sum format:
        github.com/user/repo v1.2.3 h1:hash...
        github.com/user/repo v1.2.3/go.mod h1:hash...

    We extract unique module@version pairs, preferring the actual module line
    over the go.mod line.
    """
    deps: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Parse: module_path version hash
        # Example: github.com/user/repo v1.2.3 h1:abc...
        parts = line.split()
        if len(parts) < 3:
            continue

        module_path = parts[0]
        version = parts[1]

        # Skip /go.mod lines - we prefer the actual module entry
        if line.endswith("/go.mod h1:" + parts[-1].split(":")[-1]):
            # Only add if we don't already have this module
            if module_path not in deps:
                deps[module_path] = version
        else:
            # Actual module entry - always use this
            deps[module_path] = version

    return [GoDep(name=n, version=v) for n, v in sorted(deps.items(), key=lambda kv: kv[0].lower())]


def _parse_go_mod(text: str) -> list[GoDep]:
    """Parse a go.mod file and extract direct dependencies.

    go.mod format:
        require (
            github.com/user/repo v1.2.3
            github.com/another/pkg v2.3.4
        )

    Or single-line:
        require github.com/user/repo v1.2.3

    We only parse direct dependencies, not indirect ones.
    """
    deps: dict[str, str] = {}
    in_require_block = False

    for line in text.splitlines():
        stripped = line.strip()

        # Detect start of require block
        if stripped.startswith("require ("):
            in_require_block = True
            continue

        # Detect end of require block
        if in_require_block and stripped == ")":
            in_require_block = False
            continue

        # Single-line require statement
        if stripped.startswith("require "):
            match = re.match(r"require\s+([^\s]+)\s+(v[^\s]+)", stripped)
            if match:
                module_path = match.group(1)
                version = match.group(2)
                # Only add if not marked as indirect
                if "// indirect" not in stripped:
                    deps[module_path] = version
            continue

        # Multi-line require block entries
        if in_require_block:
            # Parse: module_path version [// indirect]
            match = re.match(r"([^\s]+)\s+(v[^\s]+)", stripped)
            if match:
                module_path = match.group(1)
                version = match.group(2)
                # Only add if not marked as indirect
                if "// indirect" not in stripped:
                    deps[module_path] = version

    return [GoDep(name=n, version=v) for n, v in sorted(deps.items(), key=lambda kv: kv[0].lower())]


def go_proxy_latest(module: str, *, timeout_s: float) -> tuple[Artifact, State]:
    """Fetch the latest version of a Go module from proxy.golang.org."""
    url = f"https://proxy.golang.org/{module.replace('/', '%2F')}/@latest"

    _HTTP_ERRORS: dict[int, tuple[str, State]] = {
        404: ("not found", State.not_found),
        410: ("module removed", State.not_found),
        401: ("auth required", State.auth_required),
        403: ("auth required", State.auth_required),
        429: ("rate limited", State.rate_limited),
    }
    res, data = get_json(url, timeout_s=timeout_s)
    if not res.ok:
        note, state = _HTTP_ERRORS.get(res.status or 0, (res.error or "http error", State.error))
        return Artifact(value=None, url=url, note=note), state
    if isinstance(data, dict):
        version = data.get("Version")
        if isinstance(version, str) and version:
            return Artifact(value=version, url=url), State.ok
    return Artifact(value=None, url=url, note="no version in response"), State.error


def scan_go(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    """Scan for Go dependencies in go.mod and go.sum files.

    Priority order (direct-deps-first approach):
    1. go.mod (direct dependencies only, no indirect)
    2. go.sum (fallback if go.mod doesn't exist)
    """
    deps: list[GoDep] = []
    source = None
    source_class = SourceClass.declared_manifest

    root_path = Path(root)
    go_mod_path = root_path / "go.mod"
    if go_mod_path.exists():
        deps = _parse_go_mod(go_mod_path.read_text(encoding="utf-8", errors="replace"))
        source = "go.mod"
        source_class = SourceClass.declared_manifest

    if not deps:
        go_sum_path = root_path / "go.sum"
        if go_sum_path.exists():
            deps = _parse_go_sum(go_sum_path.read_text(encoding="utf-8", errors="replace"))
            source = "go.sum"
            source_class = SourceClass.resolved_lockfile

    # No Go dependency files found
    if not deps or source is None:
        return Section(title="Go", rows=[])

    def build_row(d: GoDep) -> DepRow:
        latest, latest_state = go_proxy_latest(d.name, timeout_s=timeout_s)

        state = State.ok
        if latest.value is not None and latest.value != d.version:
            state = State.update_available
        elif latest_state != State.ok:
            state = latest_state

        return DepRow(
            ecosystem="go",
            name=d.name,
            current=Artifact(value=d.version),
            latest=latest,
            state=state,
            source=source,
            source_class=source_class,
        )

    rows = map_bounded_ordered(deps, build_row, max_workers=lookup_concurrency)
    return Section(title="Go", rows=rows)
