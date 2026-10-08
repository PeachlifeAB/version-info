from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from version_info.model import State
from version_info.registry_ruby import _parse_gemfile_lock, rubygems_org_latest, scan_ruby
from version_info.util_http import HttpResult


def test_parse_gemfile_lock_basic() -> None:
    """Test parsing basic Gemfile.lock file with multiple dependencies."""
    gemfile_lock = """
GEM
  remote: https://rubygems.org/
  specs:
    actionpack (7.0.4)
      actionview (= 7.0.4)
      activesupport (= 7.0.4)
    activerecord (7.0.4)
      activemodel (= 7.0.4)
      activesupport (= 7.0.4)
    rails (7.0.4)
      actionpack (= 7.0.4)
      activerecord (= 7.0.4)

PLATFORMS
  ruby

DEPENDENCIES
  rails (~> 7.0.4)
    """.strip()

    gems = _parse_gemfile_lock(gemfile_lock)

    assert len(gems) == 3
    # Should be sorted alphabetically
    assert gems[0].name == "actionpack"
    assert gems[0].version == "7.0.4"
    assert gems[1].name == "activerecord"
    assert gems[1].version == "7.0.4"
    assert gems[2].name == "rails"
    assert gems[2].version == "7.0.4"


def test_parse_gemfile_lock_empty() -> None:
    """Test parsing empty Gemfile.lock file."""
    gemfile_lock = """
GEM
  remote: https://rubygems.org/
  specs:

PLATFORMS
  ruby

DEPENDENCIES
    """.strip()

    gems = _parse_gemfile_lock(gemfile_lock)

    assert len(gems) == 0


def test_parse_gemfile_lock_complex() -> None:
    """Test parsing Gemfile.lock with complex dependencies and versions."""
    gemfile_lock = """
GEM
  remote: https://rubygems.org/
  specs:
    nokogiri (1.13.10)
      mini_portile2 (~> 2.8.0)
      racc (~> 1.4)
    racc (1.6.2)
    rspec (3.12.0)
      rspec-core (~> 3.12.0)
      rspec-expectations (~> 3.12.0)
    rspec-core (3.12.1)

PLATFORMS
  ruby
  x86_64-darwin-21

DEPENDENCIES
  nokogiri
  rspec
    """.strip()

    gems = _parse_gemfile_lock(gemfile_lock)

    assert len(gems) == 4
    assert gems[0].name == "nokogiri"
    assert gems[0].version == "1.13.10"
    assert gems[1].name == "racc"
    assert gems[1].version == "1.6.2"
    assert gems[2].name == "rspec"
    assert gems[2].version == "3.12.0"
    assert gems[3].name == "rspec-core"
    assert gems[3].version == "3.12.1"


def test_parse_gemfile_lock_with_hyphens_underscores() -> None:
    """Test parsing gem names with hyphens and underscores."""
    gemfile_lock = """
GEM
  remote: https://rubygems.org/
  specs:
    mini_portile2 (2.8.1)
    rake-compiler (1.2.0)

PLATFORMS
  ruby
    """.strip()

    gems = _parse_gemfile_lock(gemfile_lock)

    assert len(gems) == 2
    assert gems[0].name == "mini_portile2"
    assert gems[0].version == "2.8.1"
    assert gems[1].name == "rake-compiler"
    assert gems[1].version == "1.2.0"


def test_parse_gemfile_lock_no_gem_section() -> None:
    """Test parsing Gemfile.lock without GEM section."""
    gemfile_lock = """
PLATFORMS
  ruby

DEPENDENCIES
  rails
    """.strip()

    gems = _parse_gemfile_lock(gemfile_lock)

    assert len(gems) == 0


def testrubygems_org_latest_success() -> None:
    """Test successful latest version fetch from rubygems.org."""
    mock_response = HttpResult(
        ok=True,
        status=200,
        text=json.dumps({"version": "7.0.8"}),
    )
    mock_json_data = {"version": "7.0.8"}

    with patch("version_info.registry_ruby.get_json", return_value=(mock_response, mock_json_data)):
        artifact, state = rubygems_org_latest("rails", timeout_s=10.0)

    assert state == State.ok
    assert artifact.value == "7.0.8"
    assert artifact.url == "https://rubygems.org/api/v1/gems/rails.json"


def testrubygems_org_latest_not_found() -> None:
    """Test 404 handling for rubygems.org API."""
    mock_response = HttpResult(ok=False, status=404, text="not found", error="HTTP Error 404")

    with patch("version_info.registry_ruby.get_json", return_value=(mock_response, None)):
        artifact, state = rubygems_org_latest("nonexistent-gem", timeout_s=10.0)

    assert state == State.not_found
    assert artifact.value is None
    assert artifact.note == "not found"


def testrubygems_org_latest_auth_required() -> None:
    """Test 401/403 handling for rubygems.org API."""
    mock_response = HttpResult(ok=False, status=403, text="forbidden", error="HTTP Error 403")

    with patch("version_info.registry_ruby.get_json", return_value=(mock_response, None)):
        artifact, state = rubygems_org_latest("some-gem", timeout_s=10.0)

    assert state == State.auth_required
    assert artifact.value is None
    assert artifact.note == "auth required"


def testrubygems_org_latest_rate_limited() -> None:
    """Test 429 handling for rubygems.org API."""
    mock_response = HttpResult(
        ok=False, status=429, text="too many requests", error="HTTP Error 429"
    )

    with patch("version_info.registry_ruby.get_json", return_value=(mock_response, None)):
        artifact, state = rubygems_org_latest("some-gem", timeout_s=10.0)

    assert state == State.rate_limited
    assert artifact.value is None
    assert artifact.note == "rate limited"


def testrubygems_org_latest_no_version() -> None:
    """Test error handling when version is missing from rubygems.org response."""
    mock_response = HttpResult(
        ok=True,
        status=200,
        text=json.dumps({"name": "rails", "downloads": 1000000}),
    )
    mock_json_data = {"name": "rails", "downloads": 1000000}

    with patch("version_info.registry_ruby.get_json", return_value=(mock_response, mock_json_data)):
        artifact, state = rubygems_org_latest("rails", timeout_s=10.0)

    assert state == State.error
    assert artifact.value is None
    assert artifact.note == "no version in response"


def testrubygems_org_latest_generic_error() -> None:
    """Test generic HTTP error handling for rubygems.org API."""
    mock_response = HttpResult(ok=False, status=500, text="server error", error="HTTP Error 500")

    with patch("version_info.registry_ruby.get_json", return_value=(mock_response, None)):
        artifact, state = rubygems_org_latest("some-gem", timeout_s=10.0)

    assert state == State.error
    assert artifact.value is None
    assert artifact.note == "HTTP Error 500"


def test_scan_ruby_no_lockfile(tmp_path: Path) -> None:
    """Test scan_ruby when Gemfile.lock doesn't exist."""
    section = scan_ruby(str(tmp_path), timeout_s=10.0)

    assert section.title == "Ruby (Bundler)"
    assert len(section.rows) == 0


def test_scan_ruby_with_dependencies(tmp_path: Path) -> None:
    """Test full scan with Gemfile.lock integration and version comparison."""
    gemfile_lock = """
GEM
  remote: https://rubygems.org/
  specs:
    rails (7.0.4)
    rspec (3.12.0)

PLATFORMS
  ruby
    """.strip()

    gemfile_lock_path = tmp_path / "Gemfile.lock"
    gemfile_lock_path.write_text(gemfile_lock)

    # Mock rubygems.org responses
    def mock_get_json(url: str, timeout_s: float):
        if "rails" in url:
            return (
                HttpResult(ok=True, status=200, text=json.dumps({"version": "7.0.8"})),
                {"version": "7.0.8"},
            )
        elif "rspec" in url:
            return (
                HttpResult(ok=True, status=200, text=json.dumps({"version": "3.12.0"})),
                {"version": "3.12.0"},
            )
        return (HttpResult(ok=False, status=404, text="not found", error="not found"), None)

    with patch("version_info.registry_ruby.get_json", side_effect=mock_get_json):
        section = scan_ruby(str(tmp_path), timeout_s=10.0)

    assert section.title == "Ruby (Bundler)"
    assert len(section.rows) == 2

    # rails should show update available
    rails_row = section.rows[0]
    assert rails_row.name == "rails"
    assert rails_row.current.value == "7.0.4"
    assert rails_row.latest.value == "7.0.8"
    assert rails_row.state == State.update_available
    assert rails_row.source == "Gemfile.lock"

    # rspec should be up-to-date
    rspec_row = section.rows[1]
    assert rspec_row.name == "rspec"
    assert rspec_row.current.value == "3.12.0"
    assert rspec_row.latest.value == "3.12.0"
    assert rspec_row.state == State.ok
    assert rspec_row.source == "Gemfile.lock"


def test_scan_ruby_handles_registry_errors(tmp_path: Path) -> None:
    """Test that registry errors are properly propagated to row state."""
    gemfile_lock = """
GEM
  remote: https://rubygems.org/
  specs:
    unknown-gem (0.1.0)

PLATFORMS
  ruby
    """.strip()

    gemfile_lock_path = tmp_path / "Gemfile.lock"
    gemfile_lock_path.write_text(gemfile_lock)

    mock_response = HttpResult(ok=False, status=404, text="not found", error="not found")

    with patch("version_info.registry_ruby.get_json", return_value=(mock_response, None)):
        section = scan_ruby(str(tmp_path), timeout_s=10.0)

    assert len(section.rows) == 1
    row = section.rows[0]
    assert row.name == "unknown-gem"
    assert row.state == State.not_found
    assert row.latest.value is None
