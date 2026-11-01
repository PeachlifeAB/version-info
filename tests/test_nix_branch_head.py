from __future__ import annotations

import io
import json
import urllib.request
from pathlib import Path
from typing import ClassVar

import pytest

from version_info import github_auth, github_graphql, github_refs
from version_info.model import State
from version_info.registry_nix import scan_nix
from version_info.util_exec import ExecResult

LOCKED_REV = "a" * 40
BRANCH_HEAD = "b" * 40
FLAKE_LOCK = {
    "nodes": {
        "nixpkgs": {
            "locked": {"owner": "NixOS", "repo": "nixpkgs", "rev": LOCKED_REV, "type": "github"},
            "original": {
                "owner": "NixOS",
                "repo": "nixpkgs",
                "ref": "nixos-unstable",
                "type": "github",
            },
        },
        "home-manager": {
            "locked": {
                "owner": "nix-community",
                "repo": "home-manager",
                "rev": LOCKED_REV,
                "type": "github",
            },
            "original": {"owner": "nix-community", "repo": "home-manager", "type": "github"},
        },
    },
    "version": 7,
}


class _Response(io.BytesIO):
    status = 200
    headers: ClassVar[dict[str, str]] = {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def _scan_with_fake_github(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, token: str | None):
    (tmp_path / "flake.lock").write_text(json.dumps(FLAKE_LOCK), encoding="utf-8")
    requests: list[urllib.request.Request] = []

    def fake_urlopen(req: urllib.request.Request, timeout: float | None = None) -> _Response:
        requests.append(req)
        if req.full_url == "https://api.github.com/graphql":
            heads = {
                "r0": {"target": {"oid": BRANCH_HEAD}},
                "r1": {"target": {"oid": BRANCH_HEAD}},
            }
            body = {
                "data": {
                    "r0": {"defaultBranchRef": heads["r0"], "ref": heads["r0"]},
                    "r1": {"defaultBranchRef": heads["r1"], "ref": heads["r1"]},
                }
            }
            return _Response(json.dumps(body).encode())
        return _Response(json.dumps({"sha": LOCKED_REV}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    if token:
        monkeypatch.setenv("GITHUB_TOKEN", token)
    else:
        monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    section = scan_nix(str(tmp_path), timeout_s=5)
    return section, requests


def test_token_set_resolves_every_flake_input_in_one_graphql_request(tmp_path, monkeypatch):
    section, requests = _scan_with_fake_github(tmp_path, monkeypatch, token="t")

    assert [row.state for row in section.rows] == [State.update_available] * 2
    assert [row.latest.value for row in section.rows] == [BRANCH_HEAD] * 2
    assert [r.full_url for r in requests] == ["https://api.github.com/graphql"]


def test_logged_in_gh_replaces_github_token(tmp_path, monkeypatch):

    monkeypatch.setattr(
        github_auth, "run_argv", lambda *a, **k: ExecResult(True, "gh-token\n", "", 0)
    )
    section, requests = _scan_with_fake_github(tmp_path, monkeypatch, token=None)

    assert [row.state for row in section.rows] == [State.update_available] * 2
    assert [r.full_url for r in requests] == ["https://api.github.com/graphql"]
    assert requests[0].get_header("Authorization") == "Bearer gh-token"


def test_without_credential_branch_heads_come_from_git_ls_remote(tmp_path, monkeypatch, capsys):

    argvs: list[list[str]] = []

    def fake_run_argv(argv, **_):
        argvs.append(argv)
        return ExecResult(True, f"{BRANCH_HEAD}\t{argv[3]}\n", "", 0)

    monkeypatch.setattr(github_refs, "run_argv", fake_run_argv)
    section, requests = _scan_with_fake_github(tmp_path, monkeypatch, token=None)

    assert [row.state for row in section.rows] == [State.update_available] * 2
    assert requests == []
    assert [a[:2] for a in argvs] == [["git", "ls-remote"]] * 2
    assert "GITHUB_TOKEN" not in capsys.readouterr().err


def test_graphql_requests_are_chunked(tmp_path, monkeypatch):

    nodes = {
        f"dep{i}": {
            "locked": {"owner": "o", "repo": f"r{i}", "rev": LOCKED_REV, "type": "github"},
            "original": {"owner": "o", "repo": f"r{i}", "type": "github"},
        }
        for i in range(github_graphql.CHUNK_SIZE + 1)
    }
    (tmp_path / "flake.lock").write_text(json.dumps({"nodes": nodes, "version": 7}))
    sizes: list[int] = []

    def fake_post_json(url, payload, **_):
        sizes.append(payload["query"].count("repository("))
        return type("R", (), {"ok": True})(), {"data": {}}

    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setattr(github_graphql, "post_json", fake_post_json)
    monkeypatch.setattr(github_refs, "run_argv", lambda *a, **k: type("E", (), {"ok": False})())
    scan_nix(str(tmp_path), timeout_s=5)

    assert sizes == [github_graphql.CHUNK_SIZE, 1]
