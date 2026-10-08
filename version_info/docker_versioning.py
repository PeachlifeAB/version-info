from __future__ import annotations

import re
from dataclasses import dataclass

from .model import Freshness

_HEX_RE = re.compile(r"^[a-f0-9]{7,40}$")
_VERSION_PREFIX_RE = re.compile(r"^v?(\d+(?:[._]\d+)*)(.*)$")
BRANCH_TAGS = {"main", "master"}
CHANNEL_TAGS = {"latest", "stable", "edge", "nightly"}


@dataclass(frozen=True)
class DockerTag:
    name: str
    parts: tuple[int, ...]
    suffix: str


def parse_docker_tag(tag: str | None) -> DockerTag | None:
    if not tag:
        return None
    value = tag.strip()
    if not value or value == "latest" or _HEX_RE.match(value):
        return None
    match = _VERSION_PREFIX_RE.match(value)
    if not match:
        return None
    version_text = match.group(1).replace("_", ".")
    suffix = match.group(2) or ""
    if suffix and not suffix.startswith("-"):
        return None
    try:
        parts = tuple(int(part) for part in version_text.lstrip("v").split("."))
    except ValueError:
        return None
    return DockerTag(name=value, parts=parts, suffix=suffix)


def is_comparable_to(candidate: DockerTag, current: DockerTag) -> bool:
    return candidate.suffix == current.suffix and len(candidate.parts) == len(current.parts)


def best_docker_update(current_tag: str | None, upstream_tags: list[str]) -> str | None:
    current = parse_docker_tag(current_tag)
    if current is None:
        return best_docker_nonversion_update(current_tag, upstream_tags)
    candidates = [
        candidate
        for raw in upstream_tags
        if (candidate := parse_docker_tag(raw)) is not None
        and is_comparable_to(candidate, current)
        and candidate.parts >= current.parts
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda tag: tag.parts).name


def best_docker_nonversion_update(current_tag: str | None, upstream_tags: list[str]) -> str | None:
    current = (current_tag or "").strip()
    if not current:
        return None
    if current in BRANCH_TAGS and current in upstream_tags:
        return current
    suffix = f"-{current}"
    parsed = [c for raw in upstream_tags if (c := parse_docker_tag(raw)) is not None]
    variant_candidates = [c for c in parsed if c.suffix == suffix]
    if variant_candidates:
        return max(variant_candidates, key=lambda tag: tag.parts).name
    if current in CHANNEL_TAGS:
        version_candidates = parsed
        if version_candidates:
            unsuffixed = [c for c in version_candidates if not c.suffix]
            pool = unsuffixed or version_candidates
            return max(pool, key=lambda tag: tag.parts).name
    return current if current in upstream_tags else None


def docker_freshness(current_tag: str | None, latest_tag: str | None) -> Freshness:
    current = parse_docker_tag(current_tag)
    latest = parse_docker_tag(latest_tag)
    if current_tag and latest_tag and current_tag == latest_tag:
        return Freshness.latest
    if current is None or latest is None or not is_comparable_to(latest, current):
        return Freshness.not_checked
    if latest.parts <= current.parts:
        return Freshness.latest
    current_parts = current.parts + (0,) * (3 - len(current.parts))
    latest_parts = latest.parts + (0,) * (3 - len(latest.parts))
    if latest_parts[0] > current_parts[0]:
        return Freshness.major_behind
    if latest_parts[1] > current_parts[1]:
        return Freshness.minor_behind
    return Freshness.patch_behind
