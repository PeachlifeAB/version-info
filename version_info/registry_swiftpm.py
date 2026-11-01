from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .github_auth import github_token
from .github_graphql import RepositoryQuery, query_repositories
from .github_refs import ls_remote
from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .release_models import ReleaseCandidate
from .release_policy import default_policy
from .release_selection import registry_selection
from .versioning import version_sort_key


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


GITHUB_REPOSITORY_PATTERN = re.compile(r"github\.com[:/]([^/]+)/([^/.]+)")
TAGS_SELECTION = (
    'refs(refPrefix: "refs/tags/", first: 100, orderBy: {field: TAG_COMMIT_DATE, direction: DESC})'
    " { nodes { name } }"
)


def _graphql_tag_names(node: dict[str, object]) -> list[str]:
    refs = node.get("refs")
    nodes = refs.get("nodes") if isinstance(refs, dict) else None
    return [
        tag["name"]
        for tag in nodes or []
        if isinstance(tag, dict) and isinstance(tag.get("name"), str)
    ]


def _ls_remote_tag_names(owner: str, repo: str, *, timeout_s: float) -> list[str]:
    shas = ls_remote(owner, repo, ["refs/tags/*"], timeout_s=timeout_s) or {}
    return [ref.removeprefix("refs/tags/").removesuffix("^{}") for ref in shas]


def _tag_names_by_location(
    deps: list[SwiftPMDep], *, timeout_s: float, lookup_concurrency: int
) -> dict[str, list[str]]:
    """Tag names per package: batched GraphQL with a credential, git ls-remote for the rest."""
    repositories = {
        dep.location: match.groups()
        for dep in deps
        if (match := GITHUB_REPOSITORY_PATTERN.search(dep.location))
    }
    tags: dict[str, list[str]] = {}
    if github_token():
        queries = [
            RepositoryQuery(location, owner, repo, TAGS_SELECTION)
            for location, (owner, repo) in repositories.items()
        ]
        for location, node in query_repositories(queries, timeout_s=timeout_s).items():
            tags[location] = _graphql_tag_names(node)
    missing = [location for location in repositories if not tags.get(location)]
    fetched = map_bounded_ordered(
        missing,
        lambda location: _ls_remote_tag_names(*repositories[location], timeout_s=timeout_s),
        max_workers=lookup_concurrency,
    )
    tags.update(zip(missing, fetched, strict=True))
    return tags


def _github_latest_tag(
    repo_url: str, *, tag_names: list[str], current_version: str | None = None
) -> tuple[Artifact, State]:
    """Select the latest semver tag among a GitHub repository's tags."""
    match = GITHUB_REPOSITORY_PATTERN.search(repo_url)
    if not match:
        return Artifact(value=None, url=repo_url, note="not a github url"), State.error

    owner, repo = match.group(1), match.group(2)
    tags_url = f"https://github.com/{owner}/{repo}/tags"
    candidates = [
        ReleaseCandidate(name)
        for name in sorted(set(tag_names), key=version_sort_key, reverse=True)
    ]
    missing_tags_note = "no version tags found"
    if not candidates:
        return Artifact(value=None, url=tags_url, note=missing_tags_note), State.error
    selection = registry_selection(
        ecosystem="swiftpm",
        package=repo_url,
        current=current_version,
        reported=candidates[0].version,
        candidates=candidates,
        complete=False,
        url=tags_url,
        policy=default_policy(),
    )
    artifact = selection.artifact
    if artifact.value is None:
        return Artifact(
            value=None, url=tags_url, note=missing_tags_note, selection=artifact.selection
        ), selection.state
    if artifact.value != current_version:
        artifact = Artifact(
            value=artifact.value.removeprefix("v"), url=tags_url, selection=artifact.selection
        )
    return artifact, selection.state


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

    deps = _parse_package_resolved(resolved_path.read_text(encoding="utf-8", errors="replace"))

    tags = _tag_names_by_location(deps, timeout_s=timeout_s, lookup_concurrency=lookup_concurrency)

    def build_row(d: SwiftPMDep) -> DepRow:
        latest, latest_state = _github_latest_tag(
            d.location, tag_names=tags.get(d.location, []), current_version=d.version
        )

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
