from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

from version_info.model import Artifact, State
from version_info.registry_nix import (
    _github_latest_commit,
    _parse_flake_lock,
    scan_nix,
)


class TestParseFlakeLock:
    def test_parse_flake_lock_basic(self):
        """Test parsing a basic flake.lock file with GitHub dependencies."""
        lock_content = """{
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
    },
    "home-manager": {
      "locked": {
        "owner": "nix-community",
        "repo": "home-manager",
        "rev": "1234567890abcdef1234567890abcdef12345678",
        "type": "github"
      }
    }
  },
  "root": "test-flake",
  "version": 7
}"""
        deps = _parse_flake_lock(lock_content)

        assert len(deps) == 2
        assert deps[0].name == "home-manager"
        assert deps[0].owner == "nix-community"
        assert deps[0].repo == "home-manager"
        assert deps[0].revision == "1234567890abcdef1234567890abcdef12345678"
        assert deps[0].type == "github"

        assert deps[1].name == "nixpkgs"
        assert deps[1].owner == "NixOS"
        assert deps[1].repo == "nixpkgs"
        assert deps[1].revision == "abcdef1234567890abcdef1234567890abcdef12"
        assert deps[1].type == "github"

    def test_parse_flake_lock_empty(self):
        """Test parsing an empty flake.lock file."""
        lock_content = '{"nodes": {}, "version": 7}'
        deps = _parse_flake_lock(lock_content)
        assert deps == []

    def test_parse_flake_lock_invalid_json(self):
        """Test parsing invalid JSON."""
        deps = _parse_flake_lock("not valid json")
        assert deps == []

    def test_parse_flake_lock_non_dict(self):
        """Test parsing non-dict JSON."""
        deps = _parse_flake_lock("[]")
        assert deps == []

    def test_parse_flake_lock_skips_non_github(self):
        """Test that non-GitHub dependencies are skipped."""
        lock_content = """{
  "nodes": {
    "nixpkgs": {
      "locked": {
        "owner": "NixOS",
        "repo": "nixpkgs",
        "rev": "abcdef1234567890abcdef1234567890abcdef12",
        "type": "github"
      }
    },
    "some-gitlab-dep": {
      "locked": {
        "owner": "gitlab-owner",
        "repo": "gitlab-repo",
        "rev": "abcdef1234567890",
        "type": "gitlab"
      }
    }
  },
  "version": 7
}"""
        deps = _parse_flake_lock(lock_content)
        assert len(deps) == 1
        assert deps[0].name == "nixpkgs"

    def test_parse_flake_lock_sorts_alphabetically(self):
        """Test that dependencies are sorted alphabetically."""
        lock_content = """{
  "nodes": {
    "zstd": { "locked": { "owner": "facebook", "repo": "zstd", "rev": "aaa", "type": "github" } },
    "aaa": { "locked": { "owner": "test", "repo": "aaa", "rev": "bbb", "type": "github" } },
    "nixpkgs": { "locked": { "owner": "NixOS", "repo": "nixpkgs", "rev": "ccc", "type": "github" } }
  },
  "version": 7
}"""
        deps = _parse_flake_lock(lock_content)

        assert len(deps) == 3
        assert deps[0].name == "aaa"
        assert deps[1].name == "nixpkgs"
        assert deps[2].name == "zstd"

    def test_parse_flake_lock_handles_missing_fields(self):
        """Test that entries with missing fields are skipped."""
        lock_content = """{
  "nodes": {
    "good-dep": {
      "locked": {
        "owner": "test",
        "repo": "good",
        "rev": "abc123",
        "type": "github"
      }
    },
    "missing-owner": {
      "locked": {
        "repo": "missing-owner",
        "rev": "abc123",
        "type": "github"
      }
    },
    "missing-repo": {
      "locked": {
        "owner": "test",
        "rev": "abc123",
        "type": "github"
      }
    }
  },
  "version": 7
}"""
        deps = _parse_flake_lock(lock_content)

        assert len(deps) == 1
        assert deps[0].name == "good-dep"


class TestGithubLatestCommit:
    @patch("version_info.registry_nix.get_json")
    def test_github_latest_commit_success(self, mock_get_json):
        """Test successful latest commit fetch."""
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_response.json.return_value = {
            "sha": "newcommit7890abcdef1234567890abcdef12345678abcd",
            "commit": {"message": "Latest commit"},
        }
        mock_get_json.return_value = (mock_response, {"sha": "newcommit7890"})

        latest, state = _github_latest_commit(
            owner="NixOS",
            repo="nixpkgs",
            current_rev="oldcommit1234567890abcdef1234567890abcdef12",
            timeout_s=10.0,
        )

        assert latest.value == "newcommit7890"
        assert state == State.update_available

    @patch("version_info.registry_nix.get_json")
    def test_github_latest_commit_up_to_date(self, mock_get_json):
        """Test when commit is up to date."""
        current_rev = "samecommit1234567890abcdef1234567890abcdef12"
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_get_json.return_value = (mock_response, {"sha": current_rev})

        latest, state = _github_latest_commit(
            owner="NixOS",
            repo="nixpkgs",
            current_rev=current_rev,
            timeout_s=10.0,
        )

        assert latest.value == current_rev
        assert state == State.ok

    @patch("version_info.registry_nix.get_json")
    def test_github_latest_commit_not_found(self, mock_get_json):
        """Test 404 response handling."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status = 404
        mock_response.error = None
        mock_get_json.return_value = (mock_response, None)

        latest, state = _github_latest_commit(
            owner="nonexistent",
            repo="repo",
            current_rev="abc123",
            timeout_s=10.0,
        )

        assert latest.value is None
        assert state == State.not_found

    @patch("version_info.registry_nix.get_json")
    def test_github_latest_commit_auth_required(self, mock_get_json):
        """Test 401/403 response handling."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status = 401
        mock_response.error = None
        mock_get_json.return_value = (mock_response, None)

        latest, state = _github_latest_commit(
            owner="test",
            repo="repo",
            current_rev="abc123",
            timeout_s=10.0,
        )

        assert latest.value is None
        assert state == State.auth_required

    @patch("version_info.registry_nix.get_json")
    def test_github_latest_commit_rate_limited(self, mock_get_json):
        """Test 429 response handling."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status = 429
        mock_response.error = None
        mock_get_json.return_value = (mock_response, None)

        latest, state = _github_latest_commit(
            owner="test",
            repo="repo",
            current_rev="abc123",
            timeout_s=10.0,
        )

        assert latest.value is None
        assert state == State.rate_limited

    @patch("version_info.registry_nix.get_json")
    def test_github_latest_commit_generic_error(self, mock_get_json):
        """Test generic error handling."""
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status = 500
        mock_response.error = "Server error"
        mock_get_json.return_value = (mock_response, None)

        latest, state = _github_latest_commit(
            owner="test",
            repo="repo",
            current_rev="abc123",
            timeout_s=10.0,
        )

        assert latest.value is None
        assert state == State.error


class TestScanNix:
    def test_scan_nix_no_lockfile(self):
        """Test scanning when flake.lock doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scan_nix(tmpdir, timeout_s=10.0)

            assert result.title == "Nix (Flakes)"
            assert result.rows == []

    @patch("version_info.registry_nix._github_latest_commit")
    def test_scan_nix_with_dependencies(self, mock_latest_commit):
        """Test full scan with flake.lock integration."""
        lock_content = """{
  "nodes": {
    "nixpkgs": {
      "locked": {
        "owner": "NixOS",
        "repo": "nixpkgs",
        "rev": "oldcommit1234567890abcdef1234567890abcdef12",
        "type": "github"
      }
    }
  },
  "version": 7
}"""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "flake.lock").write_text(lock_content)

            mock_latest_commit.return_value = (
                Artifact(value="newcommit1234567890abcdef1234567890abcdef12"),
                State.update_available,
            )

            result = scan_nix(tmpdir, timeout_s=10.0)

        assert result.title == "Nix (Flakes)"
        assert len(result.rows) == 1
        assert result.rows[0].name == "nixpkgs"
        assert result.rows[0].ecosystem == "nix"
        assert result.rows[0].source == "flake.lock"
        assert result.rows[0].state == State.update_available

    @patch("version_info.registry_nix._github_latest_commit")
    def test_scan_nix_handles_registry_errors(self, mock_latest_commit):
        """Test error state propagation from registry to rows."""
        lock_content = """{
  "nodes": {
    "nixpkgs": {
      "locked": {
        "owner": "NixOS",
        "repo": "nixpkgs",
        "rev": "oldcommit1234567890",
        "type": "github"
      }
    }
  },
  "version": 7
}"""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "flake.lock").write_text(lock_content)

            mock_latest_commit.return_value = (
                Artifact(value=None, note="rate limited"),
                State.rate_limited,
            )

            result = scan_nix(tmpdir, timeout_s=10.0)

        assert len(result.rows) == 1
        assert result.rows[0].state == State.rate_limited
        assert result.rows[0].latest.note == "rate limited"

    @patch("version_info.registry_nix._github_latest_commit")
    def test_scan_nix_up_to_date(self, mock_latest_commit):
        """Test up-to-date dependency detection."""
        lock_content = """{
  "nodes": {
    "nixpkgs": {
      "locked": {
        "owner": "NixOS",
        "repo": "nixpkgs",
        "rev": "samecommit1234567890abcdef1234567890abcdef12",
        "type": "github"
      }
    }
  },
  "version": 7
}"""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "flake.lock").write_text(lock_content)

            mock_latest_commit.return_value = (
                Artifact(value="samecommit1234567890abcdef1234567890abcdef12"),
                State.ok,
            )

            result = scan_nix(tmpdir, timeout_s=10.0)

        assert len(result.rows) == 1
        assert result.rows[0].state == State.ok

    @patch("version_info.registry_nix._github_latest_commit")
    def test_scan_nix_multiple_dependencies(self, mock_latest_commit):
        """Test scanning with multiple dependencies."""
        lock_content = """{
  "nodes": {
    "nixpkgs": {
      "locked": { "owner": "NixOS", "repo": "nixpkgs", "rev": "aaa", "type": "github" }
    },
    "home-manager": {
      "locked": { "owner": "nix-community", "repo": "home-manager", "rev": "bbb", "type": "github" }
    },
    "flake-utils": {
      "locked": { "owner": "numtide", "repo": "flake-utils", "rev": "ccc", "type": "github" }
    }
  },
  "version": 7
}"""
        with tempfile.TemporaryDirectory() as tmpdir:
            (Path(tmpdir) / "flake.lock").write_text(lock_content)

            mock_latest_commit.return_value = (
                Artifact(value="newcommit"),
                State.update_available,
            )

            result = scan_nix(tmpdir, timeout_s=10.0)

        assert len(result.rows) == 3
        names = [row.name for row in result.rows]
        assert names == ["flake-utils", "home-manager", "nixpkgs"]
