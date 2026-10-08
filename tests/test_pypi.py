from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from version_info.model import SourceClass, State
from version_info.registry_pypi import (
    _parse_poetry_lock,
    _parse_pyproject_toml,
    _parse_requirements_txt,
    _parse_uv_lock,
    pypi_latest,
    scan_pypi,
)


def test_parse_requirements_txt_basic() -> None:
    """Test parsing basic requirements.txt with == operator."""
    requirements = """
requests==2.28.1
flask==2.3.0
django==4.2.0
"""
    deps = _parse_requirements_txt(requirements)

    assert len(deps) == 3
    # Should be sorted alphabetically
    assert deps[0].name == "django"
    assert deps[0].version == "4.2.0"
    assert deps[1].name == "flask"
    assert deps[1].version == "2.3.0"
    assert deps[2].name == "requests"
    assert deps[2].version == "2.28.1"


def test_parse_requirements_txt_operators() -> None:
    """Test parsing requirements.txt only treats exact pins as inventory."""
    requirements = """
package1==1.0.0
package2>=2.0.0
package3~=3.0.0
package4<=4.0.0
"""
    deps = _parse_requirements_txt(requirements)

    assert len(deps) == 1
    assert deps[0].name == "package1"
    assert deps[0].version == "1.0.0"


def test_parse_requirements_txt_with_comments() -> None:
    """Test parsing requirements.txt with comments and empty lines."""
    requirements = """
# This is a comment
requests==2.28.1

# Another comment
flask==2.3.0
    """
    deps = _parse_requirements_txt(requirements)

    assert len(deps) == 2
    assert deps[0].name == "flask"
    assert deps[1].name == "requests"


def test_parse_requirements_txt_skip_editable() -> None:
    """Test that editable installs are skipped."""
    requirements = """
requests==2.28.1
-e git+https://github.com/user/repo.git@main#egg=mypackage
flask==2.3.0
-e .
"""
    deps = _parse_requirements_txt(requirements)

    assert len(deps) == 2
    assert deps[0].name == "flask"
    assert deps[1].name == "requests"


def test_parse_requirements_txt_normalization() -> None:
    """Test that package names are normalized to lowercase."""
    requirements = """
Django==4.2.0
Flask==2.3.0
REQUESTS==2.28.1
"""
    deps = _parse_requirements_txt(requirements)

    assert len(deps) == 3
    assert deps[0].name == "django"
    assert deps[1].name == "flask"
    assert deps[2].name == "requests"


def test_parse_requirements_txt_empty() -> None:
    """Test parsing empty requirements.txt."""
    requirements = """
# Just comments

    """
    deps = _parse_requirements_txt(requirements)

    assert len(deps) == 0


def test_parse_pyproject_toml_project_dependencies() -> None:
    """Test parsing pyproject.toml with [project.dependencies]."""
    pyproject = """
[project]
name = "myproject"
version = "1.0.0"

[project.dependencies]
requests = "==2.28.0"
flask = "2.3.0"
"""
    deps = _parse_pyproject_toml(pyproject)

    assert len(deps) == 2
    assert deps[0].name == "flask"
    assert deps[0].version == "2.3.0"
    assert deps[1].name == "requests"
    assert deps[1].version == "2.28.0"


def test_parse_pyproject_toml_dependency_groups() -> None:
    """Test parsing pyproject.toml with [dependency-groups]."""
    pyproject = """
[dependency-groups]
dev = [
    "pytest==8.0.0",
    "ruff==0.1.0",
]
"""
    deps = _parse_pyproject_toml(pyproject)

    assert len(deps) == 2
    assert deps[0].name == "pytest"
    assert deps[0].version == "8.0.0"
    assert deps[1].name == "ruff"
    assert deps[1].version == "0.1.0"


def test_parse_pyproject_toml_project_dependency_array() -> None:
    """Test parsing PEP 621 [project] dependency arrays."""
    pyproject = """
[project]
name = "myproject"
dependencies = [
    "requests==2.28.1",
    "flask>=2.0",
    "localpkg @ git+https://github.com/example/localpkg.git",
]
"""
    deps = _parse_pyproject_toml(pyproject)

    assert len(deps) == 2
    assert deps[0].name == "localpkg"
    assert deps[0].version == "git"
    assert deps[0].local is True
    assert deps[1].name == "requests"
    assert deps[1].version == "2.28.1"
    assert deps[1].local is False


def test_parse_pyproject_toml_does_not_treat_dependencies_dev_as_dependencies() -> None:
    pyproject = """
[project]
name = "myproject"
dependencies-dev = [
    "pytest==8.0.0",
]
dependencies = [
    "requests==2.28.1",
]
"""
    deps = _parse_pyproject_toml(pyproject)

    assert [(dep.name, dep.version) for dep in deps] == [("requests", "2.28.1")]


def test_parse_pyproject_toml_poetry_format() -> None:
    """Test parsing pyproject.toml with [tool.poetry.dependencies]."""
    pyproject = """
[tool.poetry]
name = "myproject"

[tool.poetry.dependencies]
requests = "2.28.1"
flask = "2.3.0"
"""
    deps = _parse_pyproject_toml(pyproject)

    assert len(deps) == 2
    assert deps[0].name == "flask"
    assert deps[0].version == "2.3.0"
    assert deps[1].name == "requests"
    assert deps[1].version == "2.28.1"


def test_parse_pyproject_toml_empty() -> None:
    """Test parsing pyproject.toml without dependencies."""
    pyproject = """
[project]
name = "myproject"
version = "1.0.0"
"""
    deps = _parse_pyproject_toml(pyproject)

    assert len(deps) == 0


def test_parse_pyproject_toml_multiple_sections() -> None:
    """Test parsing pyproject.toml stops at new sections."""
    pyproject = """
[project.dependencies]
requests = "==2.28.0"

[build-system]
requires = ["hatchling"]

[tool.ruff]
line-length = 100
"""
    deps = _parse_pyproject_toml(pyproject)

    # Should only get requests from project.dependencies
    # hatchling should be skipped (not in dependencies section)
    assert len(deps) == 1
    assert deps[0].name == "requests"


def test_parse_uv_lock_source_values_do_not_mark_dependency_local() -> None:
    uv_lock = """
[[package]]
name = "requests"
version = "2.32.0"
source = { registry = "https://github.example/simple" }
"""
    deps = _parse_uv_lock(uv_lock)

    assert len(deps) == 1
    assert deps[0].name == "requests"
    assert deps[0].version == "2.32.0"
    assert deps[0].local is False


def testpypi_latest_success() -> None:
    """Test successful latest version fetch from PyPI."""
    mock_response_data = {"info": {"version": "2.28.1"}}

    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        mock_get_json.return_value = (mock_result, mock_response_data)

        artifact, state = pypi_latest("requests", timeout_s=10.0)

        assert artifact.value == "2.28.1"
        assert artifact.url == "https://pypi.org/pypi/requests/json"
        assert state == State.ok
        mock_get_json.assert_called_once_with("https://pypi.org/pypi/requests/json", timeout_s=10.0)


def testpypi_latest_case_normalization() -> None:
    """Test that package names are normalized to lowercase for PyPI."""
    mock_response_data = {"info": {"version": "4.2.0"}}

    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        mock_get_json.return_value = (mock_result, mock_response_data)

        artifact, state = pypi_latest("Django", timeout_s=10.0)

        assert artifact.value == "4.2.0"
        # Should normalize to lowercase
        assert artifact.url == "https://pypi.org/pypi/django/json"
        assert state == State.ok
        mock_get_json.assert_called_once_with("https://pypi.org/pypi/django/json", timeout_s=10.0)


def testpypi_latest_not_found() -> None:
    """Test handling of 404 not found response."""
    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": False, "status": 404, "error": "not found"})()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = pypi_latest("nonexistent-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "not found"
        assert state == State.not_found


def testpypi_latest_auth_required() -> None:
    """Test handling of 401/403 auth required responses."""
    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        # Test 401
        mock_result = type("Result", (), {"ok": False, "status": 401, "error": "unauthorized"})()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = pypi_latest("private-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "auth required"
        assert state == State.auth_required

        # Test 403
        mock_result = type("Result", (), {"ok": False, "status": 403, "error": "forbidden"})()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = pypi_latest("private-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "auth required"
        assert state == State.auth_required


def testpypi_latest_rate_limited() -> None:
    """Test handling of 429 rate limited response."""
    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        mock_result = type(
            "Result", (), {"ok": False, "status": 429, "error": "too many requests"}
        )()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = pypi_latest("some-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "rate limited"
        assert state == State.rate_limited


def testpypi_latest_no_version() -> None:
    """Test handling of response without version info."""
    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        # Response without version
        mock_get_json.return_value = (mock_result, {"info": {}})

        artifact, state = pypi_latest("some-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "no version in response"
        assert state == State.error


def testpypi_latest_generic_error() -> None:
    """Test handling of generic HTTP errors."""
    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": False, "status": 500, "error": "server error"})()
        mock_get_json.return_value = (mock_result, None)

        artifact, state = pypi_latest("some-package", timeout_s=10.0)

        assert artifact.value is None
        assert artifact.note == "server error"
        assert state == State.error


def test_scan_pypi_no_files(tmp_path: Path) -> None:
    """Test scan_pypi returns empty section when no requirements files exist."""
    section = scan_pypi(str(tmp_path), timeout_s=10.0)

    assert section.title == "Python (PyPI)"
    assert len(section.rows) == 0


def test_scan_pypi_requirements_txt(tmp_path: Path) -> None:
    """Test scan_pypi with requirements.txt file."""
    # Create requirements.txt
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests==2.28.0\nflask==2.3.0\n")

    with patch("version_info.registry_pypi.get_json") as mock_get_json:

        def mock_get_json_side_effect(url: str, timeout_s: float):
            mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
            if "requests" in url:
                return (mock_result, {"info": {"version": "2.28.1"}})
            elif "flask" in url:
                return (mock_result, {"info": {"version": "2.3.0"}})
            return (mock_result, {})

        mock_get_json.side_effect = mock_get_json_side_effect

        section = scan_pypi(str(tmp_path), timeout_s=10.0)

        assert section.title == "Python (PyPI)"
        assert len(section.rows) == 2

        # First row (flask - alphabetically sorted)
        assert section.rows[0].ecosystem == "pypi"
        assert section.rows[0].name == "flask"
        assert section.rows[0].current.value == "2.3.0"
        assert section.rows[0].latest.value == "2.3.0"
        assert section.rows[0].state == State.ok  # Same version
        assert section.rows[0].source == "requirements.txt"

        # Second row (requests)
        assert section.rows[1].ecosystem == "pypi"
        assert section.rows[1].name == "requests"
        assert section.rows[1].current.value == "2.28.0"
        assert section.rows[1].latest.value == "2.28.1"
        assert section.rows[1].state == State.update_available
        assert section.rows[1].source == "requirements.txt"


def test_scan_pypi_pyproject_toml(tmp_path: Path) -> None:
    """Test scan_pypi with pyproject.toml file."""
    # Create pyproject.toml
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[dependency-groups]
dev = [
    "pytest==8.0.0",
    "ruff==0.1.0",
]
"""
    )

    with patch("version_info.registry_pypi.get_json") as mock_get_json:

        def mock_get_json_side_effect(url: str, timeout_s: float):
            mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
            if "pytest" in url:
                return (mock_result, {"info": {"version": "8.0.1"}})
            elif "ruff" in url:
                return (mock_result, {"info": {"version": "0.1.0"}})
            return (mock_result, {})

        mock_get_json.side_effect = mock_get_json_side_effect

        section = scan_pypi(str(tmp_path), timeout_s=10.0)

        assert section.title == "Python (PyPI)"
        assert len(section.rows) == 2

        # First row (pytest)
        assert section.rows[0].ecosystem == "pypi"
        assert section.rows[0].name == "pytest"
        assert section.rows[0].current.value == "8.0.0"
        assert section.rows[0].latest.value == "8.0.1"
        assert section.rows[0].state == State.update_available
        assert section.rows[0].source == "pyproject.toml"
        assert section.rows[0].source_class == SourceClass.declared_manifest

        # Second row (ruff)
        assert section.rows[1].ecosystem == "pypi"
        assert section.rows[1].name == "ruff"
        assert section.rows[1].current.value == "0.1.0"
        assert section.rows[1].latest.value == "0.1.0"
        assert section.rows[1].state == State.ok
        assert section.rows[1].source == "pyproject.toml"
        assert section.rows[1].source_class == SourceClass.declared_manifest


def test_scan_pypi_requirements_txt_priority(tmp_path: Path) -> None:
    """Test that requirements.txt is prioritized over pyproject.toml."""
    # Create both files
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("requests==2.28.0\n")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[dependency-groups]
dev = ["pytest>=8.0.0"]
"""
    )

    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        mock_get_json.return_value = (mock_result, {"info": {"version": "2.28.1"}})

        section = scan_pypi(str(tmp_path), timeout_s=10.0)

        # Should use requirements.txt, not pyproject.toml
        assert len(section.rows) == 1
        assert section.rows[0].name == "requests"
        assert section.rows[0].source == "requirements.txt"


def test_scan_pypi_handles_registry_errors(tmp_path: Path) -> None:
    """Test scan_pypi propagates registry error states to rows."""
    requirements = tmp_path / "requirements.txt"
    requirements.write_text("not-found==1.0.0\nrate-limited==2.0.0\n")

    with patch("version_info.registry_pypi.get_json") as mock_get_json:

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

        section = scan_pypi(str(tmp_path), timeout_s=10.0)

        assert len(section.rows) == 2

        # not-found package
        assert section.rows[0].name == "not-found"
        assert section.rows[0].state == State.not_found

        # rate-limited package
        assert section.rows[1].name == "rate-limited"
        assert section.rows[1].state == State.rate_limited


def test_parse_uv_lock_basic() -> None:
    """Test parsing basic uv.lock file."""
    uv_lock = """
version = 1
requires-python = ">=3.10"

[[package]]
name = "colorama"
version = "0.4.6"
source = { registry = "https://pypi.org/simple" }

[[package]]
name = "pytest"
version = "9.0.2"
source = { registry = "https://pypi.org/simple" }
"""
    deps = _parse_uv_lock(uv_lock)

    assert len(deps) == 2
    # Should be sorted alphabetically
    assert deps[0].name == "colorama"
    assert deps[0].version == "0.4.6"
    assert deps[1].name == "pytest"
    assert deps[1].version == "9.0.2"


def test_parse_uv_lock_with_dependencies() -> None:
    """Test parsing uv.lock with packages that have dependencies."""
    uv_lock = """
[[package]]
name = "exceptiongroup"
version = "1.3.1"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "typing-extensions", marker = "python_full_version < '3.13'" },
]

[[package]]
name = "typing-extensions"
version = "4.15.0"
source = { registry = "https://pypi.org/simple" }
"""
    deps = _parse_uv_lock(uv_lock)

    assert len(deps) == 2
    assert deps[0].name == "exceptiongroup"
    assert deps[0].version == "1.3.1"
    assert deps[1].name == "typing-extensions"
    assert deps[1].version == "4.15.0"


def test_parse_uv_lock_empty() -> None:
    """Test parsing empty uv.lock file."""
    uv_lock = """
version = 1
requires-python = ">=3.10"
"""
    deps = _parse_uv_lock(uv_lock)

    assert len(deps) == 0


def test_parse_uv_lock_case_normalization() -> None:
    """Test that package names are normalized to lowercase."""
    uv_lock = """
[[package]]
name = "Django"
version = "4.2.0"

[[package]]
name = "Flask"
version = "2.3.0"
"""
    deps = _parse_uv_lock(uv_lock)

    assert len(deps) == 2
    assert deps[0].name == "django"
    assert deps[1].name == "flask"


def test_parse_uv_lock_with_wheels_and_sdist() -> None:
    """Test parsing uv.lock with wheels and sdist metadata (should be ignored)."""
    uv_lock = """
[[package]]
name = "colorama"
version = "0.4.6"
source = { registry = "https://pypi.org/simple" }
sdist = { url = "https://files.pythonhosted.org/packages/d8/53/colorama-0.4.6.tar.gz" }
wheels = [
    { url = "https://files.pythonhosted.org/packages/d1/d6/colorama-0.4.6-py2.py3-none-any.whl" },
]
"""
    deps = _parse_uv_lock(uv_lock)

    assert len(deps) == 1
    assert deps[0].name == "colorama"
    assert deps[0].version == "0.4.6"


def test_parse_uv_lock_marks_editable_local() -> None:
    """Test uv.lock editable packages are marked local."""
    uv_lock = """
[[package]]
name = "myproject"
version = "1.2.3"
source = { editable = "." }

[[package]]
name = "requests"
version = "2.28.0"
source = { registry = "https://pypi.org/simple" }
"""
    deps = _parse_uv_lock(uv_lock)

    assert len(deps) == 2
    local_dep = next(dep for dep in deps if dep.name == "myproject")
    registry_dep = next(dep for dep in deps if dep.name == "requests")
    assert local_dep.local is True
    assert registry_dep.local is False


def test_parse_poetry_lock_basic() -> None:
    """Test parsing basic poetry.lock file."""
    poetry_lock = """
[[package]]
name = "colorama"
version = "0.4.6"
description = "Cross-platform colored terminal text."
category = "main"
optional = false
python-versions = "!=3.0.*,!=3.1.*,!=3.2.*,!=3.3.*,!=3.4.*,!=3.5.*,!=3.6.*,>=2.7"

[[package]]
name = "pytest"
version = "9.0.2"
description = "pytest: simple powerful testing with Python"
category = "dev"
optional = false
python-versions = ">=3.8"
"""
    deps = _parse_poetry_lock(poetry_lock)

    assert len(deps) == 2
    # Should be sorted alphabetically
    assert deps[0].name == "colorama"
    assert deps[0].version == "0.4.6"
    assert deps[1].name == "pytest"
    assert deps[1].version == "9.0.2"


def test_parse_poetry_lock_empty() -> None:
    """Test parsing empty poetry.lock file."""
    poetry_lock = """
# This file is automatically @generated by Poetry 1.8.3 and should not be changed by hand.
"""
    deps = _parse_poetry_lock(poetry_lock)

    assert len(deps) == 0


def test_parse_poetry_lock_case_normalization() -> None:
    """Test that package names are normalized to lowercase in poetry.lock."""
    poetry_lock = """
[[package]]
name = "Django"
version = "4.2.0"

[[package]]
name = "Flask"
version = "2.3.0"
"""
    deps = _parse_poetry_lock(poetry_lock)

    assert len(deps) == 2
    assert deps[0].name == "django"
    assert deps[1].name == "flask"


def test_scan_pypi_uv_lock(tmp_path: Path) -> None:
    """Test scan_pypi with uv.lock file."""
    # Create uv.lock
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text(
        """
[[package]]
name = "requests"
version = "2.28.0"

[[package]]
name = "flask"
version = "2.3.0"
"""
    )

    with patch("version_info.registry_pypi.get_json") as mock_get_json:

        def mock_get_json_side_effect(url: str, timeout_s: float):
            mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
            if "requests" in url:
                return (mock_result, {"info": {"version": "2.28.1"}})
            elif "flask" in url:
                return (mock_result, {"info": {"version": "2.3.0"}})
            return (mock_result, {})

        mock_get_json.side_effect = mock_get_json_side_effect

        section = scan_pypi(str(tmp_path), timeout_s=10.0)

        assert section.title == "Python (PyPI)"
        assert len(section.rows) == 2

        # First row (flask - alphabetically sorted)
        assert section.rows[0].name == "flask"
        assert section.rows[0].current.value == "2.3.0"
        assert section.rows[0].latest.value == "2.3.0"
        assert section.rows[0].state == State.ok
        assert section.rows[0].source == "uv.lock"

        # Second row (requests)
        assert section.rows[1].name == "requests"
        assert section.rows[1].current.value == "2.28.0"
        assert section.rows[1].latest.value == "2.28.1"
        assert section.rows[1].state == State.update_available
        assert section.rows[1].source == "uv.lock"


def test_scan_pypi_uv_lock_local_package(tmp_path: Path) -> None:
    """Test scan_pypi marks editable uv packages local without PyPI lookup."""
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text(
        """
[[package]]
name = "myproject"
version = "1.2.3"
source = { editable = "." }
"""
    )

    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        section = scan_pypi(str(tmp_path), timeout_s=10.0)

    assert len(section.rows) == 1
    assert section.rows[0].name == "myproject"
    assert section.rows[0].current.value == "1.2.3"
    assert section.rows[0].latest.note == "local"
    assert section.rows[0].state == State.local_only
    mock_get_json.assert_not_called()


def test_scan_pypi_poetry_lock(tmp_path: Path) -> None:
    """Test scan_pypi with poetry.lock file."""
    # Create poetry.lock
    poetry_lock = tmp_path / "poetry.lock"
    poetry_lock.write_text(
        """
[[package]]
name = "pytest"
version = "8.0.0"

[[package]]
name = "ruff"
version = "0.1.0"
"""
    )

    with patch("version_info.registry_pypi.get_json") as mock_get_json:

        def mock_get_json_side_effect(url: str, timeout_s: float):
            mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
            if "pytest" in url:
                return (mock_result, {"info": {"version": "8.0.1"}})
            elif "ruff" in url:
                return (mock_result, {"info": {"version": "0.1.0"}})
            return (mock_result, {})

        mock_get_json.side_effect = mock_get_json_side_effect

        section = scan_pypi(str(tmp_path), timeout_s=10.0)

        assert section.title == "Python (PyPI)"
        assert len(section.rows) == 2

        # First row (pytest)
        assert section.rows[0].name == "pytest"
        assert section.rows[0].current.value == "8.0.0"
        assert section.rows[0].latest.value == "8.0.1"
        assert section.rows[0].state == State.update_available
        assert section.rows[0].source == "poetry.lock"

        # Second row (ruff)
        assert section.rows[1].name == "ruff"
        assert section.rows[1].current.value == "0.1.0"
        assert section.rows[1].latest.value == "0.1.0"
        assert section.rows[1].state == State.ok
        assert section.rows[1].source == "poetry.lock"


def test_scan_pypi_uv_lock_priority(tmp_path: Path) -> None:
    """Test that uv.lock is prioritized over poetry.lock and requirements.txt."""
    # Create all three files
    uv_lock = tmp_path / "uv.lock"
    uv_lock.write_text(
        """
[[package]]
name = "requests"
version = "2.28.0"
"""
    )

    poetry_lock = tmp_path / "poetry.lock"
    poetry_lock.write_text(
        """
[[package]]
name = "flask"
version = "2.3.0"
"""
    )

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("django==4.2.0\n")

    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        mock_get_json.return_value = (mock_result, {"info": {"version": "2.28.1"}})

        section = scan_pypi(str(tmp_path), timeout_s=10.0)

        # Should use uv.lock, not poetry.lock or requirements.txt
        assert len(section.rows) == 1
        assert section.rows[0].name == "requests"
        assert section.rows[0].source == "uv.lock"


def test_scan_pypi_poetry_lock_priority(tmp_path: Path) -> None:
    """Test that poetry.lock is prioritized over requirements.txt and pyproject.toml."""
    # Create poetry.lock, requirements.txt, and pyproject.toml
    poetry_lock = tmp_path / "poetry.lock"
    poetry_lock.write_text(
        """
[[package]]
name = "flask"
version = "2.3.0"
"""
    )

    requirements = tmp_path / "requirements.txt"
    requirements.write_text("django==4.2.0\n")

    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(
        """
[dependency-groups]
dev = ["pytest>=8.0.0"]
"""
    )

    with patch("version_info.registry_pypi.get_json") as mock_get_json:
        mock_result = type("Result", (), {"ok": True, "status": 200, "error": None})()
        mock_get_json.return_value = (mock_result, {"info": {"version": "2.3.1"}})

        section = scan_pypi(str(tmp_path), timeout_s=10.0)

        # Should use poetry.lock, not requirements.txt or pyproject.toml
        assert len(section.rows) == 1
        assert section.rows[0].name == "flask"
        assert section.rows[0].source == "poetry.lock"
