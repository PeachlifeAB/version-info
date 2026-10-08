from __future__ import annotations

import json
from unittest.mock import patch

from version_info.model import Freshness, SourceClass, State
from version_info.registry_mise import _parse_mise_toml, _parse_tool_versions, scan_mise
from version_info.util_exec import ExecResult


def test_parse_tool_versions() -> None:
    tools = _parse_tool_versions("python 3.12.7\nnode 22.11.0\n")
    assert tools == [("node", "22.11.0"), ("python", "3.12.7")]


def test_parse_mise_toml_tools() -> None:
    tools = _parse_mise_toml('[tools]\npython = "3.12.7"\nnode = ["22.11.0"]\n')
    assert tools == [("node", "22.11.0"), ("python", "3.12.7")]


@patch("version_info.registry_mise.run_argv")
def test_scan_mise_runtime_tool_rows_use_batched_current_and_latest(
    mock_run_argv, tmp_path
) -> None:
    (tmp_path / "mise.toml").write_text('[tools]\ngh = "latest"\nyq = "latest"\n')
    mock_run_argv.side_effect = [
        ExecResult(
            ok=True,
            stdout=json.dumps({
                "gh": [
                    {
                        "version": "2.90.0",
                        "requested_version": "latest",
                        "install_path": "/Users/davidaberg/.local/share/mise/installs/gh/2.90.0",
                        "source": {
                            "type": "mise.toml",
                            "path": f"{tmp_path}/mise.toml",
                        },
                        "installed": True,
                        "active": True,
                    }
                ],
                "yq": [
                    {
                        "version": "4.53.2",
                        "requested_version": "latest",
                        "install_path": "/Users/davidaberg/.local/share/mise/installs/yq/4.53.2",
                        "source": {
                            "type": "mise.toml",
                            "path": f"{tmp_path}/mise.toml",
                        },
                        "installed": True,
                        "active": True,
                    }
                ],
            }),
            stderr="",
            exit_code=0,
        ),
        ExecResult(
            ok=True,
            stdout=json.dumps({
                "gh": {
                    "name": "gh",
                    "requested": "latest",
                    "current": "2.90.0",
                    "bump": None,
                    "latest": "2.92.0",
                    "source": {
                        "type": "mise.toml",
                        "path": f"{tmp_path}/mise.toml",
                    },
                }
            }),
            stderr="mise WARN  Error getting latest version for yq: no versions found for yq\n",
            exit_code=0,
        ),
    ]
    section = scan_mise(str(tmp_path), timeout_s=10.0)

    assert section.title == "Tools (mise)"
    assert len(section.rows) == 2
    gh = section.rows[0]
    assert gh.ecosystem == "mise"
    assert gh.name == "gh"
    assert gh.current.value == "2.90.0"
    assert gh.latest.value == "2.92.0"
    assert gh.state == State.update_available
    assert gh.freshness == Freshness.minor_behind
    assert gh.source == "mise.toml"
    assert gh.source_class == SourceClass.runtime_tool

    yq = section.rows[1]
    assert yq.ecosystem == "mise"
    assert yq.name == "yq"
    assert yq.current.value == "4.53.2"
    assert yq.latest.value is None
    assert yq.latest.note == "error"
    assert yq.state == State.error
    assert yq.source == "mise.toml"
    assert yq.source_class == SourceClass.runtime_tool
    assert mock_run_argv.call_count == 2


@patch("version_info.registry_mise.run_argv")
def test_scan_mise_falls_back_to_declared_version_when_mise_is_unavailable(
    mock_run_argv, tmp_path
) -> None:
    (tmp_path / "mise.toml").write_text('[tools]\npython = "3.12.7"\n')
    mock_run_argv.return_value = ExecResult(ok=False, stdout="", stderr="missing", exit_code=1)

    section = scan_mise(str(tmp_path), timeout_s=10.0)

    assert len(section.rows) == 1
    row = section.rows[0]
    assert row.current.value == "3.12.7"
    assert row.latest.value is None
    assert row.state == State.not_applicable
    assert row.freshness == Freshness.not_checked
    assert mock_run_argv.call_count == 1
