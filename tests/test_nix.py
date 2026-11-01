from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import patch

from version_info.model import Artifact, State
from version_info.registry_nix import (
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


class TestScanNix:
    def test_scan_nix_no_lockfile(self):
        """Test scanning when flake.lock doesn't exist."""
        with tempfile.TemporaryDirectory() as tmpdir:
            result = scan_nix(tmpdir, timeout_s=10.0)

            assert result.title == "Nix (Flakes)"
            assert result.rows == []

    @patch("version_info.registry_nix._branch_heads")
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

            result_for_head = (
                Artifact(value="newcommit1234567890abcdef1234567890abcdef12"),
                State.update_available,
            )
            mock_latest_commit.side_effect = lambda deps, **_: {
                d.name: result_for_head for d in deps
            }

            result = scan_nix(tmpdir, timeout_s=10.0)

        assert result.title == "Nix (Flakes)"
        assert len(result.rows) == 1
        assert result.rows[0].name == "nixpkgs"
        assert result.rows[0].ecosystem == "nix"
        assert result.rows[0].source == "flake.lock"
        assert result.rows[0].state == State.update_available

    @patch("version_info.registry_nix._branch_heads")
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

            result_for_head = (Artifact(value=None, note="rate limited"), State.rate_limited)
            mock_latest_commit.side_effect = lambda deps, **_: {
                d.name: result_for_head for d in deps
            }

            result = scan_nix(tmpdir, timeout_s=10.0)

        assert len(result.rows) == 1
        assert result.rows[0].state == State.rate_limited
        assert result.rows[0].latest.note == "rate limited"

    @patch("version_info.registry_nix._branch_heads")
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

            result_for_head = (
                Artifact(value="samecommit1234567890abcdef1234567890abcdef12"),
                State.ok,
            )
            mock_latest_commit.side_effect = lambda deps, **_: {
                d.name: result_for_head for d in deps
            }

            result = scan_nix(tmpdir, timeout_s=10.0)

        assert len(result.rows) == 1
        assert result.rows[0].state == State.ok

    @patch("version_info.registry_nix._branch_heads")
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

            result_for_head = (Artifact(value="newcommit"), State.update_available)
            mock_latest_commit.side_effect = lambda deps, **_: {
                d.name: result_for_head for d in deps
            }

            result = scan_nix(tmpdir, timeout_s=10.0)

        assert len(result.rows) == 3
        names = [row.name for row in result.rows]
        assert names == ["flake-utils", "home-manager", "nixpkgs"]
