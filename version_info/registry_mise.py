from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from .model import Artifact, DepRow, Section, SourceClass, State
from .util_exec import run_argv

logger = logging.getLogger(__name__)

_LATEST_ERROR_RE = re.compile(r"Error getting latest version for (.+?):")
_NO_VERSIONS_RE = re.compile(r"No versions found for (.+)$")


@dataclass(frozen=True)
class _MiseTool:
    name: str
    current: str
    source: str


def _parse_tool_versions(text: str) -> list[tuple[str, str]]:
    tools: dict[str, str] = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        parts = stripped.split()
        if len(parts) >= 2:
            tools[parts[0]] = parts[1]
    return sorted(tools.items())


def _parse_mise_toml(text: str) -> list[tuple[str, str]]:
    tools: dict[str, str] = {}
    in_tools = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped == "[tools]":
            in_tools = True
            continue
        if stripped.startswith("[") and stripped != "[tools]":
            in_tools = False
            continue
        if not in_tools:
            continue
        match = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*"([^"]+)"', stripped)
        if match:
            tools[match.group(1)] = match.group(2).split()[0]
            continue
        match = re.match(r'^([A-Za-z0-9_.-]+)\s*=\s*\[\s*"([^"]+)"', stripped)
        if match:
            tools[match.group(1)] = match.group(2)
    return sorted(tools.items())


def _installed_mise_versions(root: str, *, timeout_s: float) -> dict[str, _MiseTool] | None:
    result = run_argv(
        [
            "mise",
            "ls",
            "--current",
            "--installed",
            "--json",
            "--local",
            "-C",
            root,
        ],
        timeout_s=timeout_s,
    )
    if not result.ok or not result.stdout.strip():
        return None
    try:
        data = json.loads(result.stdout)
    except Exception as exc:
        logger.warning("Failed to parse mise ls output: %s", exc)
        return None
    if not isinstance(data, dict):
        return None

    versions: dict[str, _MiseTool] = {}
    for name, entries in data.items():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            version = entry.get("version")
            if isinstance(version, str) and version:
                source = entry.get("source")
                source_name = "mise.toml"
                if isinstance(source, dict):
                    path = source.get("path")
                    if isinstance(path, str) and path:
                        source_name = Path(path).name
                versions[name] = _MiseTool(name=name, current=version, source=source_name)
                break
    return versions


def _latest_mise_versions(root: str, *, timeout_s: float) -> tuple[dict[str, str] | None, set[str]]:
    result = run_argv(
        [
            "mise",
            "outdated",
            "--local",
            "--json",
            "-C",
            root,
        ],
        timeout_s=timeout_s,
    )
    failed: set[str] = set()
    for line in result.stderr.splitlines():
        match = _LATEST_ERROR_RE.search(line)
        if match:
            failed.add(match.group(1).strip())
            continue
        match = _NO_VERSIONS_RE.search(line)
        if match:
            failed.add(match.group(1).strip())

    if not result.stdout.strip():
        if result.ok:
            return {}, failed
        return None, failed

    try:
        data = json.loads(result.stdout)
    except Exception as exc:
        logger.warning("Failed to parse mise outdated output: %s", exc)
        return None, failed
    if not isinstance(data, dict):
        return None, failed

    latest: dict[str, str] = {}
    for name, entry in data.items():
        if not isinstance(entry, dict):
            continue
        latest_version = entry.get("latest")
        if isinstance(latest_version, str) and latest_version:
            latest[name] = latest_version
    return latest, failed


def scan_mise(root: str, *, timeout_s: float) -> Section:
    installed_versions = _installed_mise_versions(root, timeout_s=timeout_s)
    sources = [
        ("mise.toml", _parse_mise_toml),
        (".mise.toml", _parse_mise_toml),
        (".tool-versions", _parse_tool_versions),
    ]
    rows: list[DepRow] = []
    latest_versions: dict[str, str] | None = None
    latest_failed: set[str] = set()
    if installed_versions:
        latest_versions, latest_failed = _latest_mise_versions(root, timeout_s=timeout_s)
    for filename, parser in sources:
        file_path = Path(root) / filename
        if not file_path.exists():
            continue
        try:
            for name, version in parser(file_path.read_text(encoding="utf-8", errors="replace")):
                installed_tool = installed_versions.get(name) if installed_versions else None
                current_version = installed_tool.current if installed_tool else version
                latest_value = None
                latest_note = None
                state = State.not_applicable
                if installed_versions:
                    if latest_versions is None:
                        latest_note = "error"
                        state = State.error
                    else:
                        latest_value = latest_versions.get(name)
                        if latest_value is None:
                            if name in latest_failed:
                                latest_note = "error"
                                state = State.error
                            else:
                                latest_value = current_version
                                state = State.ok
                        else:
                            state = (
                                State.ok
                                if latest_value == current_version
                                else State.update_available
                            )
                rows.append(
                    DepRow(
                        ecosystem="mise",
                        name=name,
                        current=Artifact(value=current_version),
                        latest=Artifact(value=latest_value, note=latest_note),
                        state=state,
                        source=installed_tool.source if installed_tool else filename,
                        source_class=SourceClass.runtime_tool,
                    )
                )
        except Exception as exc:
            logger.warning("Failed to read/parse %s: %s", filename, exc)
    return Section(title="Tools (mise)", rows=rows)
