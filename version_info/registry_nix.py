from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .github_auth import github_token
from .github_refs import ls_remote
from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .util_http import post_json


@dataclass(frozen=True)
class NixFlakeDep:
    name: str
    revision: str
    owner: str
    repo: str
    type: str
    ref: str | None = None


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

        original = node.get("original", {})
        ref = original.get("ref") if isinstance(original, dict) else None

        deps[name] = NixFlakeDep(
            name=name,
            revision=revision,
            owner=owner,
            repo=repo,
            type=dep_type,
            ref=ref if isinstance(ref, str) and ref else None,
        )

    return [deps[name] for name in sorted(deps.keys(), key=lambda k: k.lower())]


GRAPHQL_URL = "https://api.github.com/graphql"
GRAPHQL_CHUNK_SIZE = 50

BranchHeads = dict[str, tuple[Artifact, State]]


def _make_commit_result(
    sha: str, *, owner: str, repo: str, current_rev: str
) -> tuple[Artifact, State]:
    state = State.update_available if sha != current_rev else State.ok
    return Artifact(value=sha, url=f"https://github.com/{owner}/{repo}/commit/{sha}"), state


def _head_unavailable(note: str, state: State = State.error) -> tuple[Artifact, State]:
    return Artifact(value=None, note=note), state


def _graphql_repository_field(alias: str, dep: NixFlakeDep) -> str:
    owner, repo = json.dumps(dep.owner), json.dumps(dep.repo)
    if dep.ref is None:
        selection = "defaultBranchRef { target { oid } }"
    else:
        selection = (
            f"ref(qualifiedName: {json.dumps(f'refs/heads/{dep.ref}')}) {{ target {{ oid }} }}"
        )
    return f"{alias}: repository(owner: {owner}, name: {repo}) {{ {selection} }}"


def _graphql_chunk_heads(chunk: list[NixFlakeDep], *, timeout_s: float) -> dict[str, str]:
    fields = [_graphql_repository_field(f"r{i}", dep) for i, dep in enumerate(chunk)]
    res, data = post_json(
        GRAPHQL_URL, {"query": "{ " + " ".join(fields) + " }"}, timeout_s=timeout_s
    )
    nodes = data.get("data") if res.ok and isinstance(data, dict) else None
    if not isinstance(nodes, dict):
        return {}
    heads: dict[str, str] = {}
    for i, dep in enumerate(chunk):
        node = nodes.get(f"r{i}")
        branch = (
            (node.get("ref") or node.get("defaultBranchRef")) if isinstance(node, dict) else None
        )
        target = branch.get("target") if isinstance(branch, dict) else None
        oid = target.get("oid") if isinstance(target, dict) else None
        if isinstance(oid, str) and oid:
            heads[dep.name] = oid
    return heads


def _graphql_heads(deps: list[NixFlakeDep], *, timeout_s: float) -> dict[str, str]:
    heads: dict[str, str] = {}
    for start in range(0, len(deps), GRAPHQL_CHUNK_SIZE):
        heads.update(
            _graphql_chunk_heads(deps[start : start + GRAPHQL_CHUNK_SIZE], timeout_s=timeout_s)
        )
    return heads


def _ls_remote_head(dep: NixFlakeDep, *, timeout_s: float) -> str | None:
    """Resolve the tracked ref with git, which needs no API credential or quota."""
    ref = dep.ref
    patterns = (
        ["HEAD"]
        if ref is None
        else [f"refs/heads/{ref}", f"refs/tags/{ref}^{{}}", f"refs/tags/{ref}"]
    )
    shas = ls_remote(dep.owner, dep.repo, patterns, timeout_s=timeout_s) or {}
    for pattern in patterns:
        if pattern in shas:
            return shas[pattern]
    return None


def _branch_heads(
    deps: list[NixFlakeDep], *, timeout_s: float, lookup_concurrency: int
) -> BranchHeads:
    """Latest head of the branch each flake input tracks."""
    heads = _graphql_heads(deps, timeout_s=timeout_s) if github_token() else {}
    unresolved = [dep for dep in deps if dep.name not in heads]
    fallback = map_bounded_ordered(
        unresolved,
        lambda dep: _ls_remote_head(dep, timeout_s=timeout_s),
        max_workers=lookup_concurrency,
    )
    heads.update({dep.name: sha for dep, sha in zip(unresolved, fallback, strict=True) if sha})
    results: BranchHeads = {}
    for dep in deps:
        sha = heads.get(dep.name)
        results[dep.name] = (
            _make_commit_result(sha, owner=dep.owner, repo=dep.repo, current_rev=dep.revision)
            if sha
            else _head_unavailable("branch head not found", State.not_found)
        )
    return results


def scan_nix(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    """Scan for Nix flake dependencies in flake.lock file.

    flake.lock is the lockfile with all resolved dependencies.
    """
    lock_path = Path(root) / "flake.lock"
    if not lock_path.exists():
        return Section(title="Nix (Flakes)", rows=[])

    deps = _parse_flake_lock(lock_path.read_text(encoding="utf-8", errors="replace"))
    heads = _branch_heads(deps, timeout_s=timeout_s, lookup_concurrency=lookup_concurrency)

    def build_row(d: NixFlakeDep) -> DepRow:
        latest, state = heads[d.name]
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

    return Section(title="Nix (Flakes)", rows=[build_row(d) for d in deps])
