from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .util_http import get_json


@dataclass(frozen=True)
class CargoDep:
    name: str
    version: str


def _parse_cargo_lock(text: str) -> list[CargoDep]:
    """Parse a Cargo.lock file and extract package names and versions.

    Cargo.lock format (TOML):
        [[package]]
        name = "anyhow"
        version = "1.0.75"
        source = "registry+https://github.com/rust-lang/crates.io-index"
        ...

    We skip packages without a source field (workspace-local crates, not registry deps).
    """
    deps: dict[str, str] = {}
    current_package: dict[str, str] = {}
    current_has_source = False

    for raw_line in text.splitlines():
        line = raw_line.strip()

        # Start of a new package block
        if line == "[[package]]":
            # Save the previous package if it had name, version, and a source field
            if "name" in current_package and "version" in current_package and current_has_source:
                name = current_package["name"]
                version = current_package["version"]
                deps[name] = version
            # Reset for new package
            current_package = {}
            current_has_source = False
            continue

        # Parse name = "value"
        if line.startswith("name = "):
            match = re.match(r'name = "([^"]+)"', line)
            if match:
                current_package["name"] = match.group(1)
            continue

        # Parse version = "value"
        if line.startswith("version = "):
            match = re.match(r'version = "([^"]+)"', line)
            if match:
                current_package["version"] = match.group(1)
            continue

        # Detect source field (registry deps have this, workspace members don't)
        if line.startswith("source = "):
            current_has_source = True
            continue

    # Don't forget the last package
    if "name" in current_package and "version" in current_package and current_has_source:
        name = current_package["name"]
        version = current_package["version"]
        deps[name] = version

    return [
        CargoDep(name=n, version=v) for n, v in sorted(deps.items(), key=lambda kv: kv[0].lower())
    ]


def _parse_cargo_toml_direct(text: str) -> set[str]:
    """Extract direct dependency names from Cargo.toml.

    Parses [dependencies], [dev-dependencies], and [build-dependencies] sections.
    """
    direct: set[str] = set()
    in_dep_section = False

    for line in text.splitlines():
        stripped = line.strip()

        # Detect dependency sections
        if stripped in ("[dependencies]", "[dev-dependencies]", "[build-dependencies]"):
            in_dep_section = True
            continue

        # Any other section header ends the dependency section
        if stripped.startswith("[") and not stripped.startswith("[["):
            in_dep_section = False
            continue

        if not in_dep_section:
            continue

        # Skip empty lines and comments
        if not stripped or stripped.startswith("#"):
            continue

        # Parse "name = ..." or "name.version = ..." or "name = { version = ... }"
        match = re.match(r"^([A-Za-z0-9_\-]+)", stripped)
        if match:
            dep_name = match.group(1)
            direct.add(dep_name)

    return direct


def crates_io_latest(crate: str, *, timeout_s: float) -> tuple[Artifact, State]:
    """Fetch the latest version of a crate from crates.io.

    crates.io API: https://crates.io/api/v1/crates/{crate}
    Returns JSON with version information.
    """
    url = f"https://crates.io/api/v1/crates/{crate}"

    res, data = get_json(url, timeout_s=timeout_s)
    if res.ok and isinstance(data, dict):
        crate_info = data.get("crate")
        if isinstance(crate_info, dict):
            max_version = crate_info.get("max_version")
            if isinstance(max_version, str) and max_version:
                return Artifact(value=max_version, url=url), State.ok
        return Artifact(value=None, url=url, note="no max_version in response"), State.error

    if res.status == 404:
        return Artifact(value=None, url=url, note="not found"), State.not_found
    if res.status in (401, 403):
        return Artifact(value=None, url=url, note="auth required"), State.auth_required
    if res.status == 429:
        return Artifact(value=None, url=url, note="rate limited"), State.rate_limited
    return Artifact(value=None, url=url, note=res.error or "http error"), State.error


def scan_cargo(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    """Scan for Rust dependencies in Cargo.lock file.

    Uses Cargo.toml to filter to direct dependencies when available.
    """
    lock_path = Path(root) / "Cargo.lock"
    if not lock_path.exists():
        return Section(title="Rust (Cargo)", rows=[])

    deps = _parse_cargo_lock(lock_path.read_text(encoding="utf-8", errors="replace"))

    # Filter to direct deps if Cargo.toml is present
    toml_path = Path(root) / "Cargo.toml"
    if toml_path.exists():
        direct = _parse_cargo_toml_direct(toml_path.read_text(encoding="utf-8", errors="replace"))
        if direct:
            deps = [d for d in deps if d.name in direct]

    def build_row(d: CargoDep) -> DepRow:
        latest, latest_state = crates_io_latest(d.name, timeout_s=timeout_s)

        state = State.ok
        if latest.value is not None and latest.value != d.version:
            state = State.update_available
        elif latest_state != State.ok:
            state = latest_state

        return DepRow(
            ecosystem="cargo",
            name=d.name,
            current=Artifact(value=d.version),
            latest=latest,
            state=state,
            source="Cargo.lock",
        )

    rows = map_bounded_ordered(deps, build_row, max_workers=lookup_concurrency)
    return Section(title="Rust (Cargo)", rows=rows)
