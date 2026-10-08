from __future__ import annotations

import re

from .model import Freshness, State

_VERSION_RE = re.compile(r"^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+][0-9A-Za-z.-]+)?$")
_HEX_RE = re.compile(r"^(?:sha256:)?(?=[a-f0-9]*[a-f])[a-f0-9]{7,}$")


def _parse_version(value: str | None) -> tuple[int, int, int] | None:
    if not value:
        return None
    stripped = value.strip()
    if not stripped or _HEX_RE.match(stripped):
        return None
    match = _VERSION_RE.match(stripped)
    if not match:
        return None
    major = int(match.group(1))
    minor = int(match.group(2) or 0)
    patch = int(match.group(3) or 0)
    return major, minor, patch


def version_sort_key(value: str) -> tuple[int, int, int]:
    return _parse_version(value) or (0, 0, 0)


def compare_versions(current: str | None, latest: str | None) -> Freshness:
    current_parts = _parse_version(current)
    latest_parts = _parse_version(latest)
    if current_parts is None or latest_parts is None:
        return Freshness.uncomparable
    if latest_parts <= current_parts:
        return Freshness.latest
    if latest_parts[0] > current_parts[0]:
        return Freshness.major_behind
    if latest_parts[1] > current_parts[1]:
        return Freshness.minor_behind
    return Freshness.patch_behind


def state_from_latest(current: str, latest: str | None, latest_state: State) -> State:
    if latest is None:
        return latest_state if latest_state != State.ok else State.error
    freshness = compare_versions(current, latest)
    if freshness == Freshness.latest:
        return State.ok
    if freshness == Freshness.uncomparable:
        return State.error
    return State.update_available
