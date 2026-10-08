from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import patch

from version_info.model import Artifact, State
from version_info.registry_npm import _parse_package_lock, npm_latest, scan_npm


def test_parse_package_lock_v2_format() -> None:
    """Test parsing npm v2 lockfile format with node_modules entries."""
    lockfile_v2 = json.dumps({
        "lockfileVersion": 2,
        "packages": {
            "": {"name": "test-project", "version": "1.0.0"},
            "node_modules/lodash": {"version": "4.17.21"},
            "node_modules/@types/node": {"version": "18.11.9"},
            "node_modules/express": {"version": "4.18.2"},
        },
    })

    deps = _parse_package_lock(lockfile_v2)

    assert len(deps) == 3
    # Should be sorted alphabetically
    assert deps[0].name == "@types/node"
    assert deps[0].version == "18.11.9"
    assert deps[1].name == "express"
    assert deps[1].version == "4.18.2"
    assert deps[2].name == "lodash"
    assert deps[2].version == "4.17.21"


def test_parse_package_lock_v1_format() -> None:
    """Test parsing npm v1 lockfile format with dependencies."""
    lockfile_v1 = json.dumps({
        "lockfileVersion": 1,
        "dependencies": {
            "lodash": {"version": "4.17.21"},
            "express": {"version": "4.18.2"},
        },
    })

    deps = _parse_package_lock(lockfile_v1)

    assert len(deps) == 2
    assert deps[0].name == "express"
    assert deps[0].version == "4.18.2"
    assert deps[1].name == "lodash"
    assert deps[1].version == "4.17.21"


def test_parse_package_lock_empty() -> None:
    """Test parsing empty lockfile."""
    lockfile_empty = json.dumps({"lockfileVersion": 2, "packages": {}})

    deps = _parse_package_lock(lockfile_empty)

    assert len(deps) == 0


def test_parse_package_lock_scoped_packages() -> None:
    """Test parsing lockfile with scoped packages like @types/node."""
    lockfile = json.dumps({
        "lockfileVersion": 2,
        "packages": {
            "node_modules/@types/node": {"version": "18.11.9"},
            "node_modules/@babel/core": {"version": "7.20.0"},
        },
    })

    deps = _parse_package_lock(lockfile)

    assert len(deps) == 2
    assert deps[0].name == "@babel/core"
    assert deps[0].version == "7.20.0"
    assert deps[1].name == "@types/node"
    assert deps[1].version == "18.11.9"


def test_parse_package_lock_nested_node_modules() -> None:
    """Test nested npm paths use the actual nested package name."""
    lockfile = json.dumps({
        "lockfileVersion": 2,
        "packages": {
            "node_modules/fastify/node_modules/process-warning": {"version": "5.0.0"},
            "node_modules/ajv/node_modules/fast-uri": {"version": "3.1.0"},
            "node_modules/foo/node_modules/@scope/pkg": {"version": "1.2.3"},
        },
    })

    deps = _parse_package_lock(lockfile)

    assert len(deps) == 3
    assert deps[0].name == "@scope/pkg"
    assert deps[1].name == "fast-uri"
    assert deps[2].name == "process-warning"


def test_parse_package_lock_malformed_entries() -> None:
    """Test parsing lockfile with malformed entries that should be skipped."""
    lockfile = json.dumps({
        "lockfileVersion": 2,
        "packages": {
            "": {"name": "root"},  # Should be skipped (empty path)
            "node_modules/valid": {"version": "1.0.0"},  # Valid
            "node_modules/no-version": {},  # Should be skipped (no version)
            "invalid-path": {"version": "1.0.0"},  # Should be skipped (not node_modules)
        },
    })

    deps = _parse_package_lock(lockfile)

    assert len(deps) == 1
    assert deps[0].name == "valid"
    assert deps[0].version == "1.0.0"


def testnpm_latest_success() -> None:
    """Test successful latest version fetch from npm registry."""
    mock_response_data = {"dist-tags": {"latest": "4.17.21"}}

    with patch("version_info.registry_npm.get_json") as mock_get_json:
        # Mock successful response
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        mock_get_json.return_value = (mock_result, mock_response_data)

        artifact, state = npm_latest("lodash", timeout_s=10.0)

        assert artifact.value == "4.17.21"
        assert artifact.url == "https://registry.npmjs.org/lodash"
        assert state == State.ok
        mock_get_json.assert_called_once_with("https://registry.npmjs.org/lodash", timeout_s=10.0)


def testnpm_latest_scoped_package() -> None:
    """Test latest version fetch for scoped package (URL encoding)."""
    mock_response_data = {"dist-tags": {"latest": "18.11.9"}}

    with patch("version_info.registry_npm.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        mock_get_json.return_value = (mock_result, mock_response_data)

        artifact, state = npm_latest("@types/node", timeout_s=10.0)

        assert artifact.value == "18.11.9"
        # Should encode / as %2F
        assert artifact.url == "https://registry.npmjs.org/@types%2Fnode"
        assert state == State.ok
        mock_get_json.assert_called_once_with(
            "https://registry.npmjs.org/@types%2Fnode", timeout_s=10.0
        )


def testnpm_latest_not_found() -> None:
    """Test handling of 404 not found response."""
    with patch("version_info.registry_npm.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": False, "status": 404, "error": "not found"})()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = npm_latest("nonexistent-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "not found"
        assert state == State.not_found


def testnpm_latest_auth_required() -> None:
    """Test handling of 401/403 auth required responses."""
    with patch("version_info.registry_npm.get_json") as mock_get_json:
        # Test 401
        mock_result = type("Result", (), {"ok": False, "status": 401, "error": "unauthorized"})()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = npm_latest("private-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "auth required"
        assert state == State.auth_required

        # Test 403
        mock_result = type("Result", (), {"ok": False, "status": 403, "error": "forbidden"})()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = npm_latest("private-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "auth required"
        assert state == State.auth_required


def testnpm_latest_rate_limited() -> None:
    """Test handling of 429 rate limited response."""
    with patch("version_info.registry_npm.get_json") as mock_get_json:
        mock_result = type(
            "Result", (), {"ok": False, "status": 429, "error": "too many requests"}
        )()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = npm_latest("some-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "rate limited"
        assert state == State.rate_limited


def testnpm_latest_no_dist_tags() -> None:
    """Test handling of response without dist-tags."""
    with patch("version_info.registry_npm.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        # Response without dist-tags
        mock_get_json.return_value = (mock_result, {"name": "some-package"})

        artifact, state = npm_latest("some-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "no dist-tag latest"
        assert state == State.error


def testnpm_latest_empty_latest_tag() -> None:
    """Test handling of empty latest dist-tag."""
    with patch("version_info.registry_npm.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        # dist-tags exists but latest is empty
        mock_get_json.return_value = (mock_result, {"dist-tags": {"latest": ""}})

        artifact, state = npm_latest("some-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "no dist-tag latest"
        assert state == State.error


def testnpm_latest_generic_error() -> None:
    """Test handling of generic HTTP errors."""
    with patch("version_info.registry_npm.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": False, "status": 500, "error": "server error"})()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = npm_latest("some-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "server error"
        assert state == State.error


def test_scan_npm_no_lockfile(tmp_path: Path) -> None:
    """Test scan_npm returns empty section when package-lock.json doesn't exist."""
    section = scan_npm(str(tmp_path), timeout_s=10.0)

    assert section.title == "Node (npm)"
    assert len(section.rows) == 0


def test_scan_npm_with_dependencies(tmp_path: Path) -> None:
    """Test scan_npm parses lockfile and fetches latest versions."""
    # Create package-lock.json
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps({
            "lockfileVersion": 2,
            "packages": {
                "node_modules/lodash": {"version": "4.17.20"},
                "node_modules/express": {"version": "4.18.2"},
            },
        })
    )

    with patch("version_info.registry_npm.get_json") as mock_get_json:

        def mock_get_json_side_effect(url: str, timeout_s: float):
            mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
            if "lodash" in url:
                return (mock_result, {"dist-tags": {"latest": "4.17.21"}})
            elif "express" in url:
                return (mock_result, {"dist-tags": {"latest": "4.18.2"}})
            return (mock_result, {})

        mock_get_json.side_effect = mock_get_json_side_effect

        section = scan_npm(str(tmp_path), timeout_s=10.0)

        assert section.title == "Node (npm)"
        assert len(section.rows) == 2

        # First row (express - alphabetically sorted)
        assert section.rows[0].ecosystem == "npm"
        assert section.rows[0].name == "express"
        assert section.rows[0].current.value == "4.18.2"
        assert section.rows[0].latest.value == "4.18.2"
        assert section.rows[0].state == State.ok  # Same version
        assert section.rows[0].source == "package-lock.json"

        # Second row (lodash)
        assert section.rows[1].ecosystem == "npm"
        assert section.rows[1].name == "lodash"
        assert section.rows[1].current.value == "4.17.20"
        assert section.rows[1].latest.value == "4.17.21"
        assert section.rows[1].state == State.update_available
        assert section.rows[1].source == "package-lock.json"


def test_scan_npm_handles_registry_errors(tmp_path: Path) -> None:
    """Test scan_npm propagates registry error states to rows."""
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps({
            "lockfileVersion": 2,
            "packages": {
                "node_modules/not-found": {"version": "1.0.0"},
                "node_modules/rate-limited": {"version": "2.0.0"},
            },
        })
    )

    with patch("version_info.registry_npm.get_json") as mock_get_json:

        def mock_get_json_side_effect(url: str, timeout_s: float):
            if "not-found" in url:
                mock_result = type(
                    "Result", (), {"ok": False, "status": 404, "error": "not found"}
                )()
                return (mock_result, None)
            elif "rate-limited" in url:
                mock_result = type(
                    "Result", (), {"ok": False, "status": 429, "error": "too many requests"}
                )()
                return (mock_result, None)
            return (None, None)

        mock_get_json.side_effect = mock_get_json_side_effect

        section = scan_npm(str(tmp_path), timeout_s=10.0)

        assert len(section.rows) == 2

        # not-found package
        assert section.rows[0].name == "not-found"
        assert section.rows[0].state == State.not_found

        # rate-limited package
        assert section.rows[1].name == "rate-limited"
        assert section.rows[1].state == State.rate_limited


def test_scan_npm_uses_bounded_parallel_lookup_and_preserves_order(tmp_path: Path) -> None:
    lockfile = tmp_path / "package-lock.json"
    lockfile.write_text(
        json.dumps({
            "lockfileVersion": 2,
            "packages": {
                "node_modules/a": {"version": "1.0.0"},
                "node_modules/b": {"version": "1.0.0"},
                "node_modules/c": {"version": "1.0.0"},
            },
        })
    )
    active = 0
    max_active = 0
    lock = threading.Lock()

    def fake_latest(name: str, *, timeout_s: float) -> tuple[Artifact, State]:
        del timeout_s
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return Artifact(value="1.0.0", url=f"https://registry.npmjs.org/{name}"), State.ok

    with patch("version_info.registry_npm.npm_latest", side_effect=fake_latest):
        section = scan_npm(str(tmp_path), timeout_s=10.0, lookup_concurrency=2)

    assert [row.name for row in section.rows] == ["a", "b", "c"]
    assert max_active == 2
