from __future__ import annotations

import json
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .util_http import get_json


@dataclass(frozen=True)
class SwiftPMDep:
    name: str
    version: str
    location: str  # URL for the repository


def _parse_package_resolved(text: str) -> list[SwiftPMDep]:
    """Parse a Package.resolved file and extract package names and versions.

    Package.resolved format (JSON):
    {
      "pins": [
        {
          "identity": "swift-argument-parser",
          "kind": "remoteSourceControl",
          "location": "https://github.com/apple/swift-argument-parser.git",
          "state": {
            "revision": "abc123...",
            "version": "1.2.3"
          }
        }
      ],
      "version": 2
    }

    Note: SwiftPM v1 format has different structure, but v2 is standard now.
    """
    deps: dict[str, SwiftPMDep] = {}

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, dict):
        return []

    pins = data.get("pins", [])
    if not isinstance(pins, list):
        return []

    for pin in pins:
        if not isinstance(pin, dict):
            continue

        # Extract identity (package name)
        identity = pin.get("identity")
        if not isinstance(identity, str) or not identity:
            continue

        # Extract location (repository URL)
        location = pin.get("location")
        if not isinstance(location, str) or not location:
            continue

        # Extract state
        state = pin.get("state", {})
        if not isinstance(state, dict):
            continue

        # Extract version (prefer version over revision)
        version = state.get("version")
        if not isinstance(version, str) or not version:
            # Fallback to revision if version is not available
            revision = state.get("revision")
            if isinstance(revision, str) and revision:
                # Use short revision (first 7 chars)
                version = revision[:7]
            else:
                continue

        deps[identity] = SwiftPMDep(
            name=identity,
            version=version,
            location=location,
        )

    return [deps[name] for name in sorted(deps.keys(), key=lambda k: k.lower())]


def _github_latest_tag(repo_url: str, *, timeout_s: float) -> tuple[Artifact, State]:
    """Fetch the latest semver tag from a GitHub repository via the tags API."""
    match = re.search(r"github\.com[:/]([^/]+)/([^/.]+)", repo_url)
    if not match:
        return Artifact(value=None, url=repo_url, note="not a github url"), State.error

    owner, repo = match.group(1), match.group(2)
    url = f"https://api.github.com/repos/{quote(owner)}/{quote(repo)}/tags"

    res, data = get_json(url, timeout_s=timeout_s)
    if not res.ok:
        note, state = {
            404: ("not found", State.not_found),
            429: ("rate limited", State.rate_limited),
        }.get(res.status or 0, (res.error or "http error", State.error))
        if res.status in (401, 403):
            note, state = "auth required", State.auth_required
        return Artifact(value=None, url=url, note=note), state

    tags_url = f"https://github.com/{owner}/{repo}/tags"
    for tag in data if isinstance(data, list) else []:
        if not isinstance(tag, dict):
            continue
        tag_name = tag.get("name")
        if isinstance(tag_name, str) and re.match(r"^v?\d+\.\d+", tag_name):
            return Artifact(value=tag_name.lstrip("v"), url=tags_url), State.ok
    return Artifact(value=None, url=url, note="no version tags found"), State.error


def scan_swiftpm(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    """Scan for Swift Package Manager dependencies in Package.resolved file.

    Package.resolved is the lockfile with all resolved dependencies.
    """
    root_path = Path(root)
    resolved_path = root_path / "Package.resolved"
    if not resolved_path.exists():
        xcodeproj_matches = list(
            root_path.glob("*.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved")
        )
        if not xcodeproj_matches:
            return Section(title="Swift (SwiftPM)", rows=[])
        resolved_path = xcodeproj_matches[0]

    if not os.environ.get("GITHUB_TOKEN"):
        print("warning: GITHUB_TOKEN not set — GitHub API limited to 60 req/hr", file=sys.stderr)

    deps = _parse_package_resolved(resolved_path.read_text(encoding="utf-8", errors="replace"))

    def build_row(d: SwiftPMDep) -> DepRow:
        latest, latest_state = _github_latest_tag(d.location, timeout_s=timeout_s)

        state = State.ok
        if latest.value is not None and latest.value != d.version:
            state = State.update_available
        elif latest_state != State.ok:
            state = latest_state

        return DepRow(
            ecosystem="swiftpm",
            name=d.name,
            current=Artifact(value=d.version),
            latest=latest,
            state=state,
            source="Package.resolved",
        )

    rows = map_bounded_ordered(deps, build_row, max_workers=lookup_concurrency)
    return Section(title="Swift (SwiftPM)", rows=rows)
