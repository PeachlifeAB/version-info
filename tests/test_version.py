from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.resolve()


def test_editable_install_version_format(tmp_path: Path) -> None:
    """Verify the installed version has correct format: version-info X.Y.devN+gHHHHHHH.dYYYYMMDD."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    tool_bin = Path(subprocess.check_output(["uv", "tool", "dir", "--bin"]).decode().strip())
    tool_path = tool_bin / "version-info"

    backup_path = None
    if tool_path.exists() or tool_path.is_symlink():
        backup_path = tmp_path / "version-info.backup"
        tool_path.replace(backup_path)

    try:
        subprocess.check_call(["uv", "tool", "install", "--force", "--editable", str(REPO_ROOT)])

        out = (
            subprocess
            .check_output(
                [str(tool_path), "--version"],
                cwd=REPO_ROOT,
                env={**os.environ, "PYTHONUTF8": "1"},
            )
            .decode()
            .strip()
        )

        assert out.startswith("version-info "), f"Version should start with 'version-info ': {out}"
        vcs_marker = "+g" if "+g" in out else "+j"
        assert vcs_marker in out, f"Version should contain '+g' or '+j' for VCS hash: {out}"

        hash_part = out.split(vcs_marker)[1][:7]
        assert len(hash_part) == 7, f"VCS hash should be 7 chars: {hash_part}"
        assert all(c in "0123456789abcdef" for c in hash_part), (
            f"Git hash should be hex: {hash_part}"
        )

        assert ".d20" in out, f"Version should contain '.d20' for timestamp: {out}"
        timestamp = out.rsplit(".d", 1)[1]
        assert len(timestamp) == 14, f"Timestamp should be 14 chars: {timestamp}"
        assert timestamp.isdigit(), f"Timestamp should be all digits: {timestamp}"
    finally:
        if backup_path is not None:
            backup_path.replace(tool_path)


def test_editable_install_cli_help(tmp_path: Path) -> None:
    """Verify the installed CLI shows help."""
    if sys.platform.startswith("win"):
        raise RuntimeError("Windows not supported by this test")

    tool_bin = Path(subprocess.check_output(["uv", "tool", "dir", "--bin"]).decode().strip())
    tool_path = tool_bin / "version-info"

    backup_path = None
    if tool_path.exists() or tool_path.is_symlink():
        backup_path = tmp_path / "version-info.backup"
        tool_path.replace(backup_path)

    try:
        subprocess.check_call(["uv", "tool", "install", "--force", "--editable", str(REPO_ROOT)])

        result = subprocess.run(
            [str(tool_path), "--help"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            env={**os.environ, "PYTHONUTF8": "1"},
        )

        assert result.returncode == 0, f"CLI returned code {result.returncode}: {result.stderr}"
        assert "--version" in result.stdout
        assert "path" in result.stdout
        assert "--timeout" in result.stdout
    finally:
        if backup_path is not None:
            backup_path.replace(tool_path)
