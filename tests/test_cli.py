from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from version_info import main as cli_main
from version_info.model import Artifact, DepRow, Section, State
from version_info.scanners import SCANNERS, ScannerDef

REPO_ROOT = Path(__file__).parent.parent.resolve()


def test_cli_positional_path_argument(tmp_path: Path) -> None:
    """Verify the CLI accepts a positional path argument."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    # Create a temporary test directory
    test_dir = tmp_path / "test_project"
    test_dir.mkdir()

    # Run the CLI with positional path argument
    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", str(test_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
    assert result.stdout != "", "CLI should produce output"


def test_cli_default_current_directory(tmp_path: Path) -> None:
    """Verify the CLI defaults to current directory when no path is provided."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    # Run the CLI without arguments
    result = subprocess.run(
        [sys.executable, "-m", "version_info.main"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
    assert result.stdout != "", "CLI should produce output"


def test_cli_help_shows_path_argument(tmp_path: Path) -> None:
    """Verify the CLI help shows the positional path argument."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
    assert "path" in result.stdout.lower(), "Help should mention 'path' argument"
    assert "--timeout" in result.stdout, "Help should show --timeout option"
    assert "--verbose" in result.stdout, "Help should show --verbose option"


def test_cli_with_timeout_and_path(tmp_path: Path) -> None:
    """Verify the CLI accepts both path and timeout arguments."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    test_dir = tmp_path / "test_project"
    test_dir.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", str(test_dir), "--timeout", "5"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
    assert result.stdout != "", "CLI should produce output"


def test_cli_no_sections_when_no_ecosystems(tmp_path: Path) -> None:
    """Verify the CLI outputs nothing when no ecosystem lockfiles are present."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    # Create a directory with no lockfiles
    test_dir = tmp_path / "empty_project"
    test_dir.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", str(test_dir)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
    # Should produce empty output or just whitespace when no ecosystems present
    assert result.stdout.strip() == "", (
        "CLI should produce no output when no ecosystems are present"
    )


def test_cli_shows_only_npm_section(tmp_path: Path) -> None:
    """Verify the CLI only shows npm section when only package-lock.json is present."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    test_dir = tmp_path / "npm_only_project"
    test_dir.mkdir()

    # Create a package-lock.json with a dependency
    package_lock = test_dir / "package-lock.json"
    package_lock.write_text(
        '{"lockfileVersion": 2, "packages": {"node_modules/lodash": {"version": "4.17.21"}}}'
    )

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", str(test_dir), "--timeout", "5"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
    # Should show npm section but not ruby or core sections
    assert "Node (npm)" in result.stdout, "Should show npm section"
    assert "Ruby" not in result.stdout, "Should not show Ruby section"
    assert "Core" not in result.stdout, "Should not show Core section"


def test_cli_shows_only_ruby_section(tmp_path: Path) -> None:
    """Verify the CLI only shows ruby section when only Gemfile.lock is present."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    test_dir = tmp_path / "ruby_only_project"
    test_dir.mkdir()

    # Create a Gemfile.lock with a gem dependency
    gemfile_lock = test_dir / "Gemfile.lock"
    gemfile_lock.write_text("GEM\n  remote: https://rubygems.org/\n  specs:\n    rake (13.1.0)\n")

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", str(test_dir), "--timeout", "5"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
    # Should show ruby section but not npm or core sections
    assert "Ruby (Bundler)" in result.stdout, "Should show Ruby section"
    assert "Node (npm)" not in result.stdout, "Should not show npm section"
    assert "Core" not in result.stdout, "Should not show Core section"


def test_cli_shows_multiple_ecosystems(tmp_path: Path) -> None:
    """Verify the CLI shows multiple sections when multiple lockfiles are present."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    test_dir = tmp_path / "multi_ecosystem_project"
    test_dir.mkdir()

    # Create both lockfiles with dependencies
    package_lock = test_dir / "package-lock.json"
    package_lock.write_text(
        '{"lockfileVersion": 2, "packages": {"node_modules/lodash": {"version": "4.17.21"}}}'
    )

    gemfile_lock = test_dir / "Gemfile.lock"
    gemfile_lock.write_text("GEM\n  remote: https://rubygems.org/\n  specs:\n    rake (13.1.0)\n")

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", str(test_dir), "--timeout", "5"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
    # Should show both sections
    assert "Node (npm)" in result.stdout, "Should show npm section"
    assert "Ruby (Bundler)" in result.stdout, "Should show Ruby section"
    assert "Core" not in result.stdout, "Should not show Core section"


def test_cli_json_output_flag(tmp_path: Path) -> None:
    """Verify --json flag produces valid JSON output."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    test_dir = tmp_path / "json_test_project"
    test_dir.mkdir()

    # Create a package-lock.json with a dependency
    package_lock = test_dir / "package-lock.json"
    package_lock.write_text(
        '{"lockfileVersion": 2, "packages": {"node_modules/lodash": {"version": "4.17.21"}}}'
    )

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", str(test_dir), "--json", "--timeout", "5"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"

    # Parse JSON output to verify it's valid
    data = json.loads(result.stdout)

    assert "sections" in data, "JSON output should have 'sections' key"
    assert isinstance(data["sections"], list), "sections should be a list"


def test_cli_json_structure(tmp_path: Path) -> None:
    """Verify JSON output has correct structure with sections and rows."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    test_dir = tmp_path / "json_structure_project"
    test_dir.mkdir()

    package_lock = test_dir / "package-lock.json"
    package_lock.write_text(
        '{"lockfileVersion": 2, "packages": {"node_modules/express": {"version": "4.18.2"}}}'
    )

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", str(test_dir), "--json", "--timeout", "5"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"

    data = json.loads(result.stdout)

    # Should have at least one section
    assert len(data["sections"]) >= 1, "Should have at least one section"

    # First section should have expected structure
    section = data["sections"][0]
    assert "title" in section, "Section should have title"
    assert "rows" in section, "Section should have rows"
    assert isinstance(section["rows"], list), "rows should be a list"

    # If there are rows, check their structure
    if section["rows"]:
        row = section["rows"][0]
        assert "ecosystem" in row, "Row should have ecosystem"
        assert "name" in row, "Row should have name"
        assert "current" in row, "Row should have current"
        assert "latest" in row, "Row should have latest"
        assert "state" in row, "Row should have state"
        assert "source" in row, "Row should have source"
        assert "source_class" in row, "Row should have source_class"
        assert "freshness" in row, "Row should have freshness"
    assert "\033" not in result.stdout, "JSON should not contain ANSI color codes"


def test_cli_json_empty_when_no_ecosystems(tmp_path: Path) -> None:
    """Verify --json outputs empty sections array when no ecosystems present."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    test_dir = tmp_path / "json_empty_project"
    test_dir.mkdir()

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", str(test_dir), "--json"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"

    data = json.loads(result.stdout)
    assert data["sections"] == [], "Should have empty sections array when no ecosystems"


def test_cli_help_shows_json_flag(tmp_path: Path) -> None:
    """Verify the CLI help shows the --json flag."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    result = subprocess.run(
        [sys.executable, "-m", "version_info.main", "--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONUTF8": "1"},
    )

    assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
    assert "--json" in result.stdout, "Help should show --json option"


def test_scanner_metadata_is_well_formed() -> None:
    """Verify scanner metadata entries contain the required orchestration fields."""
    assert SCANNERS, "Expected at least one registered scanner"

    for scanner in SCANNERS:
        assert isinstance(scanner, ScannerDef)
        assert scanner.name
        assert scanner.section_title
        assert scanner.markers
        assert callable(scanner.scan_fn)


def test_cli_detector_first_skips_absent_scanners(tmp_path: Path, monkeypatch) -> None:
    """Verify scanners are not called when their markers are absent."""
    calls: list[str] = []

    def scan_present(root: str, *, timeout_s: float) -> Section:
        calls.append("present")
        return Section(title="Present", rows=[])

    def scan_absent(root: str, *, timeout_s: float) -> Section:
        calls.append("absent")
        return Section(title="Absent", rows=[])

    present = ScannerDef(
        name="present",
        section_title="Present",
        markers=("package-lock.json",),
        scan_fn=scan_present,
    )
    absent = ScannerDef(
        name="absent",
        section_title="Absent",
        markers=("Dockerfile",),
        scan_fn=scan_absent,
    )

    (tmp_path / "package-lock.json").write_text(
        '{"lockfileVersion": 2, "packages": {"node_modules/lodash": {"version": "4.17.21"}}}'
    )

    monkeypatch.setattr(cli_main, "SCANNERS", (present, absent))

    exit_code = cli_main.main([str(tmp_path)])

    assert exit_code == 0
    assert calls == ["present"]


def test_cli_scanner_exception_does_not_abort_scan(tmp_path: Path, monkeypatch) -> None:
    """Verify one broken scanner does not block later scanners."""
    present_called = False

    def scan_broken(root: str, *, timeout_s: float) -> Section:
        raise ValueError("broken scanner")

    def scan_present(root: str, *, timeout_s: float) -> Section:
        nonlocal present_called
        present_called = True
        return Section(title="Present", rows=[])

    broken = ScannerDef(
        name="broken",
        section_title="Broken",
        markers=("package-lock.json",),
        scan_fn=scan_broken,
    )
    present = ScannerDef(
        name="present",
        section_title="Present",
        markers=("package-lock.json",),
        scan_fn=scan_present,
    )

    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 2, "packages": {}}')

    monkeypatch.setattr(cli_main, "SCANNERS", (broken, present))

    assert cli_main.main([str(tmp_path)]) == 0
    assert present_called


def test_cli_scan_scope_excludes_fixture_subdirectories(tmp_path: Path, monkeypatch) -> None:
    """Verify default subdir scanning skips fixture-like directories."""
    calls: list[str] = []

    def scan_rows(root: str, *, timeout_s: float) -> Section:
        calls.append(Path(root).name)
        return Section(title="Present", rows=[])

    scanner = ScannerDef(
        name="present",
        section_title="Present",
        markers=("package-lock.json",),
        scan_fn=scan_rows,
    )

    (tmp_path / "package-lock.json").write_text('{"lockfileVersion": 2, "packages": {}}')
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "package-lock.json").write_text('{"lockfileVersion": 2, "packages": {}}')

    app = tmp_path / "app"
    app.mkdir()
    (app / "package-lock.json").write_text('{"lockfileVersion": 2, "packages": {}}')

    monkeypatch.setattr(cli_main, "SCANNERS", (scanner,))

    exit_code = cli_main.main([str(tmp_path)])

    assert exit_code == 0
    assert calls == [tmp_path.name, "app"]


def test_cli_scan_scope_skips_symlink_and_worktree_dirs(tmp_path: Path, monkeypatch) -> None:
    """Verify monorepo scanning avoids symlink aliases and worktree containers."""
    calls: list[str] = []

    def scan_rows(root: str, *, timeout_s: float) -> Section:
        calls.append(Path(root).name)
        return Section(title="Present", rows=[])

    scanner = ScannerDef(
        name="present",
        section_title="Present",
        markers=("package-lock.json",),
        scan_fn=scan_rows,
    )

    main = tmp_path / "main"
    main.mkdir()
    (main / "package-lock.json").write_text('{"lockfileVersion": 2, "packages": {}}')

    worktrees = tmp_path / "worktrees"
    worktrees.mkdir()
    (worktrees / "package-lock.json").write_text('{"lockfileVersion": 2, "packages": {}}')

    try:
        (tmp_path / "active").symlink_to(main)
    except OSError:
        pytest.skip("Symlink creation not supported on this platform")

    monkeypatch.setattr(cli_main, "SCANNERS", (scanner,))

    exit_code = cli_main.main([str(tmp_path)])

    assert exit_code == 0
    assert calls == ["main"]


def test_cli_concurrent_scanners_keep_deterministic_output_order(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    """Verify scanner concurrency does not reorder rendered sections."""

    def make_scan(title: str, delay: float):
        def scan(root: str, *, timeout_s: float) -> Section:
            time.sleep(delay)
            return Section(
                title=title,
                rows=[
                    DepRow(
                        ecosystem=title.lower(),
                        name=title.lower(),
                        current=Artifact(value="1.0.0"),
                        latest=Artifact(value="1.0.0"),
                        state=State.ok,
                        source="test.lock",
                    )
                ],
            )

        return scan

    first = ScannerDef(
        name="first",
        section_title="First",
        markers=("first.lock",),
        scan_fn=make_scan("First", 0.02),
    )
    second = ScannerDef(
        name="second",
        section_title="Second",
        markers=("second.lock",),
        scan_fn=make_scan("Second", 0.0),
    )

    (tmp_path / "first.lock").write_text("")
    (tmp_path / "second.lock").write_text("")

    monkeypatch.setattr(cli_main, "SCANNERS", (first, second))

    assert cli_main.main([str(tmp_path), "--concurrency", "2"]) == 0
    output = capsys.readouterr().out

    assert output.index("First") < output.index("Second")
