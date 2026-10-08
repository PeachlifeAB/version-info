from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from version_info.model import State
from version_info.registry_swiftpm import _github_latest_tag, _parse_package_resolved, scan_swiftpm
from version_info.util_http import HttpResult


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


def test_github_latest_tag_success() -> None:
    """Test successful latest version fetch from GitHub tags."""
    mock_response = HttpResult(
        ok=True,
        status=200,
        text=json.dumps([
            {"name": "v1.3.0", "commit": {"sha": "abc123"}},
            {"name": "v1.2.3", "commit": {"sha": "def456"}},
            {"name": "v1.2.2", "commit": {"sha": "ghi789"}},
        ]),
    )
    mock_json_data = [
        {"name": "v1.3.0", "commit": {"sha": "abc123"}},
        {"name": "v1.2.3", "commit": {"sha": "def456"}},
        {"name": "v1.2.2", "commit": {"sha": "ghi789"}},
    ]

    with patch(
        "version_info.registry_swiftpm.get_json", return_value=(mock_response, mock_json_data)
    ):
        artifact, state = _github_latest_tag(
            "https://github.com/apple/swift-argument-parser.git", timeout_s=10.0
        )

    assert state == State.ok
    assert artifact.value == "1.3.0"  # Should strip leading 'v'
    assert artifact.url == "https://github.com/apple/swift-argument-parser/tags"


def test_github_latest_tag_without_v_prefix() -> None:
    """Test GitHub tag parsing when version tags don't have 'v' prefix."""
    mock_response = HttpResult(
        ok=True,
        status=200,
        text=json.dumps([
            {"name": "1.5.4", "commit": {"sha": "abc123"}},
            {"name": "1.5.3", "commit": {"sha": "def456"}},
        ]),
    )
    mock_json_data = [
        {"name": "1.5.4", "commit": {"sha": "abc123"}},
        {"name": "1.5.3", "commit": {"sha": "def456"}},
    ]

    with patch(
        "version_info.registry_swiftpm.get_json", return_value=(mock_response, mock_json_data)
    ):
        artifact, state = _github_latest_tag(
            "https://github.com/apple/swift-log.git", timeout_s=10.0
        )

    assert state == State.ok
    assert artifact.value == "1.5.4"
    assert artifact.url == "https://github.com/apple/swift-log/tags"


def test_github_latest_tag_ssh_url() -> None:
    """Test GitHub tag fetching with SSH URL format."""
    mock_response = HttpResult(
        ok=True,
        status=200,
        text=json.dumps([
            {"name": "v2.0.0", "commit": {"sha": "abc123"}},
        ]),
    )
    mock_json_data = [
        {"name": "v2.0.0", "commit": {"sha": "abc123"}},
    ]

    with patch(
        "version_info.registry_swiftpm.get_json", return_value=(mock_response, mock_json_data)
    ):
        artifact, state = _github_latest_tag("git@github.com:apple/swift-nio.git", timeout_s=10.0)

    assert state == State.ok
    assert artifact.value == "2.0.0"


def test_github_latest_tag_not_found() -> None:
    """Test 404 handling for GitHub API."""
    mock_response = HttpResult(ok=False, status=404, text="not found", error="HTTP Error 404")

    with patch("version_info.registry_swiftpm.get_json", return_value=(mock_response, None)):
        artifact, state = _github_latest_tag(
            "https://github.com/user/nonexistent.git", timeout_s=10.0
        )

    assert state == State.not_found
    assert artifact.value is None
    assert artifact.note == "not found"


def test_github_latest_tag_auth_required() -> None:
    """Test 401/403 handling for GitHub API."""
    mock_response = HttpResult(ok=False, status=403, text="forbidden", error="HTTP Error 403")

    with patch("version_info.registry_swiftpm.get_json", return_value=(mock_response, None)):
        artifact, state = _github_latest_tag(
            "https://github.com/user/private-repo.git", timeout_s=10.0
        )

    assert state == State.auth_required
    assert artifact.value is None
    assert artifact.note == "auth required"


def test_github_latest_tag_rate_limited() -> None:
    """Test 429 handling for GitHub API."""
    mock_response = HttpResult(
        ok=False, status=429, text="too many requests", error="HTTP Error 429"
    )

    with patch("version_info.registry_swiftpm.get_json", return_value=(mock_response, None)):
        artifact, state = _github_latest_tag(
            "https://github.com/apple/swift-package-manager.git", timeout_s=10.0
        )

    assert state == State.rate_limited
    assert artifact.value is None
    assert artifact.note == "rate limited"


def test_github_latest_tag_no_version_tags() -> None:
    """Test error handling when repository has no version tags."""
    mock_response = HttpResult(
        ok=True,
        status=200,
        text=json.dumps([
            {"name": "release-candidate", "commit": {"sha": "abc123"}},
            {"name": "beta", "commit": {"sha": "def456"}},
        ]),
    )
    mock_json_data = [
        {"name": "release-candidate", "commit": {"sha": "abc123"}},
        {"name": "beta", "commit": {"sha": "def456"}},
    ]

    with patch(
        "version_info.registry_swiftpm.get_json", return_value=(mock_response, mock_json_data)
    ):
        artifact, state = _github_latest_tag(
            "https://github.com/user/no-versions.git", timeout_s=10.0
        )

    assert state == State.error
    assert artifact.value is None
    assert artifact.note == "no version tags found"


def test_github_latest_tag_non_github_url() -> None:
    """Test error handling for non-GitHub URLs."""
    artifact, state = _github_latest_tag("https://gitlab.com/user/repo.git", timeout_s=10.0)

    assert state == State.error
    assert artifact.value is None
    assert artifact.note == "not a github url"


def test_github_latest_tag_generic_error() -> None:
    """Test generic HTTP error handling for GitHub API."""
    mock_response = HttpResult(ok=False, status=500, text="server error", error="HTTP Error 500")

    with patch("version_info.registry_swiftpm.get_json", return_value=(mock_response, None)):
        artifact, state = _github_latest_tag("https://github.com/apple/swift.git", timeout_s=10.0)

    assert state == State.error
    assert artifact.value is None
    assert artifact.note == "HTTP Error 500"


def test_scan_swiftpm_no_package_resolved(tmp_path: Path) -> None:
    """Test scan_swiftpm when Package.resolved doesn't exist."""
    section = scan_swiftpm(str(tmp_path), timeout_s=10.0)

    assert section.title == "Swift (SwiftPM)"
    assert len(section.rows) == 0


def test_scan_swiftpm_with_dependencies(tmp_path: Path) -> None:
    """Test full scan with Package.resolved integration and version comparison."""
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

    package_resolved_path = tmp_path / "Package.resolved"
    package_resolved_path.write_text(package_resolved)

    # Mock GitHub responses
    def mock_get_json(url: str, timeout_s: float):
        if "swift-argument-parser" in url:
            return (
                HttpResult(ok=True, status=200, text=json.dumps([{"name": "v1.3.0"}])),
                [{"name": "v1.3.0"}],
            )
        elif "swift-log" in url:
            return (
                HttpResult(ok=True, status=200, text=json.dumps([{"name": "v1.5.3"}])),
                [{"name": "v1.5.3"}],
            )
        return (HttpResult(ok=False, status=404, text="not found", error="not found"), None)

    with patch("version_info.registry_swiftpm.get_json", side_effect=mock_get_json):
        section = scan_swiftpm(str(tmp_path), timeout_s=10.0)

    assert section.title == "Swift (SwiftPM)"
    assert len(section.rows) == 2

    # swift-argument-parser should show update available
    arg_parser_row = section.rows[0]
    assert arg_parser_row.name == "swift-argument-parser"
    assert arg_parser_row.current.value == "1.2.2"
    assert arg_parser_row.latest.value == "1.3.0"
    assert arg_parser_row.state == State.update_available
    assert arg_parser_row.source == "Package.resolved"

    # swift-log should be up-to-date
    log_row = section.rows[1]
    assert log_row.name == "swift-log"
    assert log_row.current.value == "1.5.3"
    assert log_row.latest.value == "1.5.3"
    assert log_row.state == State.ok
    assert log_row.source == "Package.resolved"


def test_scan_swiftpm_handles_registry_errors(tmp_path: Path) -> None:
    """Test that GitHub API errors are properly propagated to row state."""
    package_resolved = """
{
  "pins": [
    {
      "identity": "private-package",
      "kind": "remoteSourceControl",
      "location": "https://github.com/user/private-package.git",
      "state": {
        "version": "1.0.0"
      }
    }
  ],
  "version": 2
}
    """.strip()

    package_resolved_path = tmp_path / "Package.resolved"
    package_resolved_path.write_text(package_resolved)

    mock_response = HttpResult(ok=False, status=403, text="forbidden", error="forbidden")

    with patch("version_info.registry_swiftpm.get_json", return_value=(mock_response, None)):
        section = scan_swiftpm(str(tmp_path), timeout_s=10.0)

    assert len(section.rows) == 1
    row = section.rows[0]
    assert row.name == "private-package"
    assert row.state == State.auth_required
    assert row.latest.value is None
