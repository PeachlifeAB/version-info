from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from version_info.model import State
from version_info.registry_go import _parse_go_mod, _parse_go_sum, go_proxy_latest, scan_go
from version_info.util_http import HttpResult


def test_parse_go_sum_basic() -> None:
    """Test parsing basic go.sum file with multiple dependencies."""
    go_sum = """
github.com/davecgh/go-spew v1.1.1 h1:vj9j/u1bqnvCEfJOwUhtlOARqs3+rkHYY13jYWTU97c=
github.com/davecgh/go-spew v1.1.1/go.mod h1:J7Y8YcW2NihsgmVo/mv3lAwl/skON4iLHjSsI+c5H38=
github.com/pmezard/go-difflib v1.0.0 h1:4DBwDE0NGyQoBHbLQYPwSUPoCMWR5BEzIk/f1lZbAQM=
github.com/pmezard/go-difflib v1.0.0/go.mod h1:iKH77koFhYxTK1pcRnkKkqfTogsbg7gZNVY4sRDYZ/4=
github.com/stretchr/testify v1.8.4 h1:CcVxjf3Q8PM0mHUKJCdn+eZZtm5yQwehR5yeSVQQcUk=
github.com/stretchr/testify v1.8.4/go.mod h1:sz/lmYIOXD/1dqDmKjjqLyZ2RngseejIcXlSw2iwfAo=
    """.strip()

    deps = _parse_go_sum(go_sum)

    assert len(deps) == 3
    # Should be sorted alphabetically
    assert deps[0].name == "github.com/davecgh/go-spew"
    assert deps[0].version == "v1.1.1"
    assert deps[1].name == "github.com/pmezard/go-difflib"
    assert deps[1].version == "v1.0.0"
    assert deps[2].name == "github.com/stretchr/testify"
    assert deps[2].version == "v1.8.4"


def test_parse_go_sum_duplicate_modules() -> None:
    """Test that go.sum handles duplicate module entries (actual module vs go.mod)."""
    go_sum = """
github.com/pkg/errors v0.9.1 h1:FEBLx1zS214owpjy7qsBeixbURkuhQAwrK5UwLGTwt4=
github.com/pkg/errors v0.9.1/go.mod h1:bwawxfHBFNV+L2hUp1rHADufV3IMtnDRdf1r5NINEl0=
    """.strip()

    deps = _parse_go_sum(go_sum)

    # Should only have one entry per module
    assert len(deps) == 1
    assert deps[0].name == "github.com/pkg/errors"
    assert deps[0].version == "v0.9.1"


def test_parse_go_sum_empty() -> None:
    """Test parsing empty go.sum file."""
    go_sum = ""

    deps = _parse_go_sum(go_sum)

    assert len(deps) == 0


def test_parse_go_sum_with_pseudo_versions() -> None:
    """Test parsing go.sum with pseudo-versions (pre-release versions)."""
    go_sum = """
github.com/user/repo v0.0.0-20230101120000-abcdef123456 h1:hash...
github.com/user/repo v0.0.0-20230101120000-abcdef123456/go.mod h1:hash...
    """.strip()

    deps = _parse_go_sum(go_sum)

    assert len(deps) == 1
    assert deps[0].name == "github.com/user/repo"
    assert deps[0].version == "v0.0.0-20230101120000-abcdef123456"


def test_parse_go_mod_basic() -> None:
    """Test parsing basic go.mod file with require block."""
    go_mod = """
module example.com/myproject

go 1.21

require (
    github.com/gin-gonic/gin v1.9.1
    github.com/stretchr/testify v1.8.4
    golang.org/x/sync v0.5.0
)
    """.strip()

    deps = _parse_go_mod(go_mod)

    assert len(deps) == 3
    assert deps[0].name == "github.com/gin-gonic/gin"
    assert deps[0].version == "v1.9.1"
    assert deps[1].name == "github.com/stretchr/testify"
    assert deps[1].version == "v1.8.4"
    assert deps[2].name == "golang.org/x/sync"
    assert deps[2].version == "v0.5.0"


def test_parse_go_mod_single_line_require() -> None:
    """Test parsing go.mod with single-line require statements."""
    go_mod = """
module example.com/myproject

go 1.21

require github.com/pkg/errors v0.9.1
require github.com/stretchr/testify v1.8.4
    """.strip()

    deps = _parse_go_mod(go_mod)

    assert len(deps) == 2
    assert deps[0].name == "github.com/pkg/errors"
    assert deps[0].version == "v0.9.1"
    assert deps[1].name == "github.com/stretchr/testify"
    assert deps[1].version == "v1.8.4"


def test_parse_go_mod_exclude_indirect() -> None:
    """Test that indirect dependencies are excluded from parsing."""
    go_mod = """
module example.com/myproject

go 1.21

require (
    github.com/direct/dep v1.0.0
    github.com/indirect/dep v2.0.0 // indirect
)
    """.strip()

    deps = _parse_go_mod(go_mod)

    # Should only include direct dependency
    assert len(deps) == 1
    assert deps[0].name == "github.com/direct/dep"
    assert deps[0].version == "v1.0.0"


def test_parse_go_mod_empty() -> None:
    """Test parsing go.mod with no dependencies."""
    go_mod = """
module example.com/myproject

go 1.21
    """.strip()

    deps = _parse_go_mod(go_mod)

    assert len(deps) == 0


def testgo_proxy_latest_success() -> None:
    """Test successful latest version fetch from Go proxy."""
    mock_response = HttpResult(
        ok=True,
        status=200,
        text=json.dumps({"Version": "v1.9.1", "Time": "2023-08-09T01:23:45Z"}),
    )
    mock_json_data = {"Version": "v1.9.1", "Time": "2023-08-09T01:23:45Z"}

    with patch("version_info.registry_go.get_json", return_value=(mock_response, mock_json_data)):
        artifact, state = go_proxy_latest("github.com/gin-gonic/gin", timeout_s=10)

    assert state == State.ok
    assert artifact.value == "v1.9.1"
    assert artifact.url == "https://proxy.golang.org/github.com%2Fgin-gonic%2Fgin/@latest"


def testgo_proxy_latest_nested_module() -> None:
    """Test URL encoding for nested module paths."""
    mock_response = HttpResult(
        ok=True,
        status=200,
        text=json.dumps({"Version": "v0.5.0"}),
    )
    mock_json_data = {"Version": "v0.5.0"}

    with patch("version_info.registry_go.get_json", return_value=(mock_response, mock_json_data)):
        artifact, state = go_proxy_latest("golang.org/x/sync", timeout_s=10)

    assert state == State.ok
    assert artifact.value == "v0.5.0"
    # Verify path encoding: / -> %2F
    assert artifact.url is not None and "golang.org%2Fx%2Fsync" in artifact.url


def testgo_proxy_latest_not_found() -> None:
    """Test 404 handling for non-existent modules."""
    mock_response = HttpResult(ok=False, status=404, text="not found", error="HTTP Error 404")

    with patch("version_info.registry_go.get_json", return_value=(mock_response, None)):
        artifact, state = go_proxy_latest("github.com/nonexistent/module", timeout_s=10)

    assert state == State.not_found
    assert artifact.value is None
    assert artifact.note == "not found"


def testgo_proxy_latest_module_removed() -> None:
    """Test 410 Gone handling for removed modules."""
    mock_response = HttpResult(ok=False, status=410, text="gone", error="HTTP Error 410")

    with patch("version_info.registry_go.get_json", return_value=(mock_response, None)):
        artifact, state = go_proxy_latest("github.com/removed/module", timeout_s=10)

    assert state == State.not_found
    assert artifact.value is None
    assert artifact.note == "module removed"


def testgo_proxy_latest_auth_required() -> None:
    """Test 401/403 handling for private modules."""
    mock_response = HttpResult(ok=False, status=403, text="forbidden", error="HTTP Error 403")

    with patch("version_info.registry_go.get_json", return_value=(mock_response, None)):
        artifact, state = go_proxy_latest("github.com/private/module", timeout_s=10)

    assert state == State.auth_required
    assert artifact.value is None
    assert artifact.note == "auth required"


def testgo_proxy_latest_rate_limited() -> None:
    """Test 429 handling for rate limiting."""
    mock_response = HttpResult(
        ok=False, status=429, text="too many requests", error="HTTP Error 429"
    )

    with patch("version_info.registry_go.get_json", return_value=(mock_response, None)):
        artifact, state = go_proxy_latest("github.com/user/repo", timeout_s=10)

    assert state == State.rate_limited
    assert artifact.value is None
    assert artifact.note == "rate limited"


def testgo_proxy_latest_no_version() -> None:
    """Test error handling when version is missing from response."""
    mock_response = HttpResult(
        ok=True, status=200, text=json.dumps({"Time": "2023-08-09T01:23:45Z"})
    )
    mock_json_data = {"Time": "2023-08-09T01:23:45Z"}  # Missing Version field

    with patch("version_info.registry_go.get_json", return_value=(mock_response, mock_json_data)):
        artifact, state = go_proxy_latest("github.com/user/repo", timeout_s=10)

    assert state == State.error
    assert artifact.value is None
    assert artifact.note == "no version in response"


def testgo_proxy_latest_generic_error() -> None:
    """Test generic HTTP error handling."""
    mock_response = HttpResult(ok=False, status=500, text="internal error", error="HTTP Error 500")

    with patch("version_info.registry_go.get_json", return_value=(mock_response, None)):
        artifact, state = go_proxy_latest("github.com/user/repo", timeout_s=10)

    assert state == State.error
    assert artifact.value is None
    assert artifact.note is not None and (
        "http error" in artifact.note or "HTTP Error 500" in artifact.note
    )


def test_scan_go_no_files(tmp_path: Path) -> None:
    """Test that empty section is returned when no Go files exist."""
    section = scan_go(str(tmp_path), timeout_s=10)

    assert section.title == "Go"
    assert len(section.rows) == 0


def test_scan_go_with_go_sum(tmp_path: Path) -> None:
    """Test full scan with go.sum file."""
    go_sum_content = """
github.com/gin-gonic/gin v1.9.0 h1:hash1...
github.com/gin-gonic/gin v1.9.0/go.mod h1:hash2...
github.com/stretchr/testify v1.8.4 h1:hash3...
github.com/stretchr/testify v1.8.4/go.mod h1:hash4...
    """.strip()

    go_sum_path = tmp_path / "go.sum"
    go_sum_path.write_text(go_sum_content)

    mock_gin_response = HttpResult(ok=True, status=200, text=json.dumps({"Version": "v1.9.1"}))
    mock_testify_response = HttpResult(ok=True, status=200, text=json.dumps({"Version": "v1.8.4"}))

    def mock_get_json(url: str, **kwargs):
        if "gin-gonic" in url:
            return (mock_gin_response, {"Version": "v1.9.1"})
        elif "testify" in url:
            return (mock_testify_response, {"Version": "v1.8.4"})
        return (HttpResult(ok=False, status=404, text="", error="not found"), None)

    with patch("version_info.registry_go.get_json", side_effect=mock_get_json):
        section = scan_go(str(tmp_path), timeout_s=10)

    assert section.title == "Go"
    assert len(section.rows) == 2

    # Check first dependency (gin - has update available)
    assert section.rows[0].ecosystem == "go"
    assert section.rows[0].name == "github.com/gin-gonic/gin"
    assert section.rows[0].current.value == "v1.9.0"
    assert section.rows[0].latest.value == "v1.9.1"
    assert section.rows[0].state == State.update_available
    assert section.rows[0].source == "go.sum"

    # Check second dependency (testify - up to date)
    assert section.rows[1].name == "github.com/stretchr/testify"
    assert section.rows[1].current.value == "v1.8.4"
    assert section.rows[1].latest.value == "v1.8.4"
    assert section.rows[1].state == State.ok
    assert section.rows[1].source == "go.sum"


def test_scan_go_with_go_mod(tmp_path: Path) -> None:
    """Test full scan with go.mod file (fallback when no go.sum)."""
    go_mod_content = """
module example.com/myproject

go 1.21

require (
    github.com/pkg/errors v0.9.1
)
    """.strip()

    go_mod_path = tmp_path / "go.mod"
    go_mod_path.write_text(go_mod_content)

    mock_response = HttpResult(ok=True, status=200, text=json.dumps({"Version": "v0.9.1"}))

    with patch(
        "version_info.registry_go.get_json", return_value=(mock_response, {"Version": "v0.9.1"})
    ):
        section = scan_go(str(tmp_path), timeout_s=10)

    assert section.title == "Go"
    assert len(section.rows) == 1
    assert section.rows[0].name == "github.com/pkg/errors"
    assert section.rows[0].current.value == "v0.9.1"
    assert section.rows[0].state == State.ok
    assert section.rows[0].source == "go.mod"


def test_scan_go_go_mod_priority(tmp_path: Path) -> None:
    """Test that go.mod is prioritized over go.sum when both exist."""
    go_sum_content = """
github.com/pkg/errors v0.9.1 h1:hash...
github.com/pkg/errors v0.9.1/go.mod h1:hash...
    """.strip()

    go_mod_content = """
module example.com/myproject
require github.com/pkg/errors v0.9.1
    """.strip()

    (tmp_path / "go.sum").write_text(go_sum_content)
    (tmp_path / "go.mod").write_text(go_mod_content)

    mock_response = HttpResult(ok=True, status=200, text=json.dumps({"Version": "v0.9.1"}))

    with patch(
        "version_info.registry_go.get_json", return_value=(mock_response, {"Version": "v0.9.1"})
    ):
        section = scan_go(str(tmp_path), timeout_s=10)

    assert section.title == "Go"
    assert len(section.rows) == 1
    # Verify source is go.mod (takes priority over go.sum for direct deps)
    assert section.rows[0].source == "go.mod"


def test_scan_go_handles_registry_errors(tmp_path: Path) -> None:
    """Test that registry errors are propagated to row state."""
    go_sum_content = """
github.com/nonexistent/module v1.0.0 h1:hash...
    """.strip()

    (tmp_path / "go.sum").write_text(go_sum_content)

    mock_response = HttpResult(ok=False, status=404, text="not found", error="HTTP Error 404")

    with patch("version_info.registry_go.get_json", return_value=(mock_response, None)):
        section = scan_go(str(tmp_path), timeout_s=10)

    assert section.title == "Go"
    assert len(section.rows) == 1
    assert section.rows[0].state == State.not_found
    assert section.rows[0].latest.value is None
    assert section.rows[0].latest.note == "not found"
