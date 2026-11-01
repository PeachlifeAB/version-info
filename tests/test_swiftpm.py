from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from version_info import github_graphql, github_refs
from version_info.model import State
from version_info.registry_swiftpm import _github_latest_tag, _parse_package_resolved, scan_swiftpm
from version_info.util_exec import ExecResult
from version_info.util_http import HttpResult

TWO_PACKAGES = json.dumps({
    "version": 2,
    "pins": [
        {
            "identity": "swift-argument-parser",
            "kind": "remoteSourceControl",
            "location": "https://github.com/apple/swift-argument-parser.git",
            "state": {"version": "1.2.2"},
        },
        {
            "identity": "swift-log",
            "kind": "remoteSourceControl",
            "location": "https://github.com/apple/swift-log.git",
            "state": {"version": "1.5.3"},
        },
    ],
})


def _tags_node(*names: str) -> dict[str, object]:
    return {"refs": {"nodes": [{"name": name} for name in names]}}


def test_parse_package_resolved_basic() -> None:
    """Test parsing basic Package.resolved file with multiple dependencies."""
    package_resolved = """
{
  "pins": [
    {
      "identity": "swift-argument-parser",
      "kind": "remoteSourceControl",
      "location": "https://github.com/apple/swift-argument-parser.git",
      "state": {
        "revision": "fee6933f37fde9a5e12a1e4aeaa93fe60116ff2a",
        "version": "1.2.2"
      }
    },
    {
      "identity": "swift-log",
      "kind": "remoteSourceControl",
      "location": "https://github.com/apple/swift-log.git",
      "state": {
        "revision": "532d8b529501fb73a2455b179e0bbb6d49b652ed",
        "version": "1.5.3"
      }
    }
  ],
  "version": 2
}
    """.strip()

    deps = _parse_package_resolved(package_resolved)

    assert len(deps) == 2
    # Should be sorted alphabetically
    assert deps[0].name == "swift-argument-parser"
    assert deps[0].version == "1.2.2"
    assert deps[0].location == "https://github.com/apple/swift-argument-parser.git"
    assert deps[1].name == "swift-log"
    assert deps[1].version == "1.5.3"
    assert deps[1].location == "https://github.com/apple/swift-log.git"


def test_parse_package_resolved_revision_only() -> None:
    """Test parsing Package.resolved when only revision is available (no version tag)."""
    package_resolved = """
{
  "pins": [
    {
      "identity": "my-package",
      "kind": "remoteSourceControl",
      "location": "https://github.com/user/my-package.git",
      "state": {
        "revision": "abc1234567890def1234567890"
      }
    }
  ],
  "version": 2
}
    """.strip()

    deps = _parse_package_resolved(package_resolved)

    assert len(deps) == 1
    assert deps[0].name == "my-package"
    # Should use short revision (first 7 chars)
    assert deps[0].version == "abc1234"
    assert deps[0].location == "https://github.com/user/my-package.git"


def test_parse_package_resolved_empty() -> None:
    """Test parsing empty Package.resolved file."""
    package_resolved = """
{
  "pins": [],
  "version": 2
}
    """.strip()

    deps = _parse_package_resolved(package_resolved)

    assert len(deps) == 0


def test_parse_package_resolved_invalid_json() -> None:
    """Test parsing malformed Package.resolved file."""
    package_resolved = "not valid json"

    deps = _parse_package_resolved(package_resolved)

    assert len(deps) == 0


def test_parse_package_resolved_missing_fields() -> None:
    """Test parsing Package.resolved with missing required fields."""
    package_resolved = """
{
  "pins": [
    {
      "identity": "incomplete-package",
      "kind": "remoteSourceControl"
    },
    {
      "location": "https://github.com/user/no-identity.git",
      "state": {
        "version": "1.0.0"
      }
    },
    {
      "identity": "valid-package",
      "kind": "remoteSourceControl",
      "location": "https://github.com/user/valid.git",
      "state": {
        "version": "1.0.0"
      }
    }
  ],
  "version": 2
}
    """.strip()

    deps = _parse_package_resolved(package_resolved)

    # Only the valid package should be included
    assert len(deps) == 1
    assert deps[0].name == "valid-package"
    assert deps[0].version == "1.0.0"


def test_latest_tag_strips_v_prefix_and_picks_highest() -> None:
    artifact, state = _github_latest_tag(
        "https://github.com/apple/swift-argument-parser.git",
        tag_names=["v1.2.2", "v1.3.0", "v1.2.3"],
    )

    assert state == State.ok
    assert artifact.value == "1.3.0"
    assert artifact.url == "https://github.com/apple/swift-argument-parser/tags"


def test_latest_tag_accepts_ssh_urls() -> None:
    artifact, state = _github_latest_tag("git@github.com:apple/swift-nio.git", tag_names=["v2.0.0"])

    assert state == State.ok
    assert artifact.value == "2.0.0"


def test_latest_tag_ignores_non_version_tags() -> None:
    artifact, state = _github_latest_tag(
        "https://github.com/user/no-versions.git", tag_names=["release-candidate", "beta"]
    )

    assert state == State.error
    assert artifact.value is None
    assert artifact.note == "no version tags found"


def test_latest_tag_rejects_non_github_urls() -> None:
    artifact, state = _github_latest_tag("https://gitlab.com/user/repo.git", tag_names=["1.0.0"])

    assert state == State.error
    assert artifact.note == "not a github url"


def test_scan_with_credential_resolves_every_package_in_one_graphql_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Package.resolved").write_text(TWO_PACKAGES)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    graphql = {
        "data": {"r0": _tags_node("v1.3.0", "v1.2.2"), "r1": _tags_node("v1.5.3")},
    }
    ok = HttpResult(ok=True, status=200, text=None)

    with patch.object(github_graphql, "post_json", return_value=(ok, graphql)) as post:
        section = scan_swiftpm(str(tmp_path), timeout_s=10.0)

    assert post.call_count == 1
    assert [(row.name, row.latest.value, row.state) for row in section.rows] == [
        ("swift-argument-parser", "1.3.0", State.update_available),
        ("swift-log", "1.5.3", State.ok),
    ]


def test_scan_without_credential_resolves_tags_with_git_ls_remote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Package.resolved").write_text(TWO_PACKAGES)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    tags = {"swift-argument-parser": ("1.2.2", "1.10.0", "1.9.0"), "swift-log": ("1.5.3",)}

    def fake_run_argv(argv, **_):
        repo = argv[2].removeprefix("https://github.com/apple/")
        return ExecResult(True, "\n".join(f"{'a' * 40}\trefs/tags/{t}" for t in tags[repo]), "", 0)

    monkeypatch.setattr(github_refs, "run_argv", fake_run_argv)
    with patch.object(github_graphql, "post_json") as post:
        section = scan_swiftpm(str(tmp_path), timeout_s=10.0)

    post.assert_not_called()
    assert [(row.name, row.latest.value, row.state) for row in section.rows] == [
        ("swift-argument-parser", "1.10.0", State.update_available),
        ("swift-log", "1.5.3", State.ok),
    ]


def test_scan_reports_a_repository_without_resolvable_tags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "Package.resolved").write_text(TWO_PACKAGES)
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setattr(
        github_refs, "run_argv", lambda *a, **k: ExecResult(False, "", "not found", 128)
    )

    section = scan_swiftpm(str(tmp_path), timeout_s=10.0)

    assert [row.state for row in section.rows] == [State.error, State.error]
    assert section.rows[0].latest.note == "no version tags found"


def test_scan_swiftpm_no_package_resolved(tmp_path: Path) -> None:
    """Test scan_swiftpm when Package.resolved doesn't exist."""
    section = scan_swiftpm(str(tmp_path), timeout_s=10.0)

    assert section.title == "Swift (SwiftPM)"
    assert len(section.rows) == 0
