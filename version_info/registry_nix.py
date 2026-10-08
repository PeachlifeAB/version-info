from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .util_http import get_json


@dataclass(frozen=True)
class NixFlakeDep:
    name: str
    revision: str
    owner: str
    repo: str
    type: str


def _parse_flake_lock(text: str) -> list[NixFlakeDep]:
    """Parse a flake.lock file and extract dependency information.

    flake.lock format (JSON):
    {
      "nodes": {
        "nixpkgs": {
          "locked": {
            "owner": "NixOS",
            "repo": "nixpkgs",
            "rev": "abcdef1234567890abcdef1234567890abcdef12",
            "type": "github"
          },
          "original": {
            "owner": "NixOS",
            "repo": "nixpkgs",
            "type": "github"
          }
        }
      },
      "root": "...",
      "version": 7
    }

    We extract all nodes that have a locked field with github type.
    """
    deps: dict[str, NixFlakeDep] = {}

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []

    if not isinstance(data, dict):
        return []

    nodes = data.get("nodes", {})
    if not isinstance(nodes, dict):
        return []

    for name, node in nodes.items():
        if not isinstance(node, dict):
            continue

        locked = node.get("locked", {})
        if not isinstance(locked, dict):
            continue

        dep_type = locked.get("type")
        if dep_type != "github":
            continue

        owner = locked.get("owner")
        repo = locked.get("repo")
        revision = locked.get("rev")

        if not isinstance(owner, str) or not owner:
            continue
        if not isinstance(repo, str) or not repo:
            continue
        if not isinstance(revision, str) or not revision:
            continue

        deps[name] = NixFlakeDep(
            name=name,
            revision=revision,
            owner=owner,
            repo=repo,
            type=dep_type,
        )

    return [deps[name] for name in sorted(deps.keys(), key=lambda k: k.lower())]


def _make_commit_result(
    sha: str, *, owner: str, repo: str, current_rev: str
) -> tuple[Artifact, State]:
    state = State.update_available if sha != current_rev else State.ok
    return Artifact(value=sha, url=f"https://github.com/{owner}/{repo}/commit/{sha}"), state


def _github_latest_commit(
    *, owner: str, repo: str, current_rev: str, timeout_s: float
) -> tuple[Artifact, State]:
    """Fetch the latest commit from a GitHub repository via the commits API."""
    url = f"https://api.github.com/repos/{owner}/{repo}/commits/{current_rev}"

    res, data = get_json(url, timeout_s=timeout_s)
    if res.ok and isinstance(data, dict):
        sha = data.get("sha")
        if isinstance(sha, str):
            return _make_commit_result(sha, owner=owner, repo=repo, current_rev=current_rev)
        return Artifact(value=None, url=url, note="no commit info"), State.error

    if res.status == 404:
        return Artifact(value=None, url=url, note="not found"), State.not_found
    if res.status in (401, 403):
        return Artifact(value=None, url=url, note="auth required"), State.auth_required
    if res.status == 429:
        return Artifact(value=None, url=url, note="rate limited"), State.rate_limited
    return Artifact(value=None, url=url, note=res.error or "http error"), State.error


def scan_nix(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    """Scan for Nix flake dependencies in flake.lock file.

    flake.lock is the lockfile with all resolved dependencies.
    """
    lock_path = Path(root) / "flake.lock"
    if not lock_path.exists():
        return Section(title="Nix (Flakes)", rows=[])

    if not os.environ.get("GITHUB_TOKEN"):
        print("warning: GITHUB_TOKEN not set — GitHub API limited to 60 req/hr", file=sys.stderr)

    deps = _parse_flake_lock(lock_path.read_text(encoding="utf-8", errors="replace"))

    def build_row(d: NixFlakeDep) -> DepRow:
        latest, latest_state = _github_latest_commit(
            owner=d.owner,
            repo=d.repo,
            current_rev=d.revision,
            timeout_s=timeout_s,
        )

        state = State.ok
        if latest.value is not None and latest.value != d.revision:
            state = State.update_available
        elif latest_state != State.ok:
            state = latest_state

        return DepRow(
            ecosystem="nix",
            name=d.name,
            current=Artifact(
                value=d.revision[:7],
                url=f"https://github.com/{d.owner}/{d.repo}/commit/{d.revision}",
            ),
            latest=latest,
            state=state,
            source="flake.lock",
        )

    rows = map_bounded_ordered(deps, build_row, max_workers=lookup_concurrency)
    return Section(title="Nix (Flakes)", rows=rows)
