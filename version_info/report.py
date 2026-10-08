from __future__ import annotations

import json
import re

from tabulate import tabulate

from .model import DepRow, Freshness, Section, SourceClass, State
from .versioning import compare_versions

GREEN = "\033[32m"
YELLOW = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
_VERSION_FACT_RE = re.compile(r"^@?v?\d+(?:[._]\d+)*(?:[-+][0-9A-Za-z._+-]+)?$")
_BRANCH_FACTS = {"main", "master", "latest", "stable", "edge", "nightly"}


def _clean_note(note: str | None) -> str | None:
    if note is None:
        return None
    cleaned = note.strip()
    if len(cleaned) >= 2 and cleaned[0] == "(" and cleaned[-1] == ")":
        cleaned = cleaned[1:-1].strip()
    if cleaned.lower() == "unknown":
        return None
    if cleaned == "auth required":
        return "auth"
    if cleaned == "rate limited":
        return "rate"
    if cleaned in {"http error", "json parse"} or cleaned.startswith("json parse:"):
        return "error"
    return cleaned or None


def format_display_value(value: str | None, note: str | None) -> str:
    if value is not None and value != "":
        return value
    return _clean_note(note) or "(n/a)"


def format_version(row: DepRow) -> str:
    """Format version display as 'current -> latest' (update) or colored current (ok/other)."""
    current_val = format_display_value(row.current.value, row.current.note)
    latest_val = format_display_value(row.latest.value, row.latest.note)
    if row.state == State.update_available:
        value = f"{current_val} -> {latest_val}"
        if row.freshness == Freshness.major_behind:
            return f"{RED}{value}{RESET}"
        if row.freshness in (Freshness.minor_behind, Freshness.patch_behind):
            return f"{YELLOW}{value}{RESET}"
        return value
    if row.state == State.ok:
        return f"{GREEN}{current_val}{RESET}"
    suffix = row.latest.note or row.note
    if suffix:
        normalized = suffix if suffix.startswith("(") else f"({suffix})"
        return f"{current_val} {normalized}"
    return current_val


def _is_version_fact(value: str | None) -> bool:
    if value is None:
        return False
    stripped = value.strip()
    # "main (a91de)" — branch tag with short sha suffix
    base = stripped.split(" (")[0]
    if base in _BRANCH_FACTS:
        return True
    return bool(_VERSION_FACT_RE.match(stripped))


def _format_current(row: DepRow) -> str:
    value = row.current.value or ""
    if not value or not _is_version_fact(value):
        return value
    latest = row.latest.value
    if not latest or not _is_version_fact(latest):
        return value
    freshness = row.freshness
    if freshness == Freshness.not_checked:
        freshness = compare_versions(value, latest)
    if freshness == Freshness.latest:
        return f"{GREEN}{value}{RESET}"
    if freshness == Freshness.major_behind:
        return f"{RED}{value}{RESET}"
    if freshness in (Freshness.minor_behind, Freshness.patch_behind):
        return f"{YELLOW}{value}{RESET}"
    return value


def _format_latest(row: DepRow) -> str:
    return row.latest.value or ""


_RUNTIME_STATUS: dict[State, str] = {
    State.local_only: "local",
    State.auth_required: "private",
    State.rate_limited: "rate",
    State.not_found: "not found",
    State.ok: "public",
    State.update_available: "public",
}

_DEP_STATUS: dict[State, str] = {
    State.local_only: "local",
    State.auth_required: "auth",
    State.rate_limited: "rate",
    State.not_found: "not found",
    State.pinned: "pinned",
}


def _format_status(row: DepRow) -> str:
    note_fallback = _clean_note(row.latest.note) or _clean_note(row.note)
    if row.source_class == SourceClass.container_runtime:
        if row.state in (State.error, State.not_applicable):
            return note_fallback or ("error" if row.state == State.error else "not checked")
        return _RUNTIME_STATUS.get(row.state, "")
    if row.state in (State.error, State.not_applicable):
        return note_fallback or ("error" if row.state == State.error else "not checked")
    return _DEP_STATUS.get(row.state, "")


def _is_registry_issue(row: DepRow) -> bool:
    return row.state in {State.auth_required, State.rate_limited, State.not_found, State.error}


def _summary(title: str, rows: list[DepRow]) -> str:
    count = len(rows)
    title_lower = title.lower()
    if title_lower == "docker":
        noun = "image"
    elif "mise" in title_lower or "tool" in title_lower:
        noun = "tool"
    else:
        noun = "dep"
    noun_text = noun if count == 1 else f"{noun}s"
    updates = sum(1 for row in rows if row.state == State.update_available)
    issues = sum(1 for row in rows if _is_registry_issue(row))
    local = sum(1 for row in rows if row.state == State.local_only)
    parts = [f"{title}  {count} {noun_text}"]
    if updates:
        update_text = "update" if updates == 1 else "updates"
        parts.append(f"{updates} {update_text}")
    if local:
        parts.append(f"{local} local")
    if issues:
        parts.append(f"{issues} registry issues")
    return ", ".join(parts)


def _render_current_latest_table(rows: list[DepRow]) -> str:
    data_with_status = [
        [r.name, _format_current(r), _format_latest(r), _format_status(r), r.source] for r in rows
    ]
    show_status = any(row[3] for row in data_with_status)
    colalign: tuple[str, ...]
    if show_status:
        headers = ["NAME", "CURRENT", "LATEST", "STATUS", "SOURCE"]
        data = data_with_status
        colalign = ("left", "left", "left", "left", "left")
    else:
        headers = ["NAME", "CURRENT", "LATEST", "SOURCE"]
        data = [
            [name, current, latest, source] for name, current, latest, _, source in data_with_status
        ]
        colalign = ("left", "left", "left", "left")

    return tabulate(
        data,
        headers=headers,
        tablefmt="simple",
        disable_numparse=True,
        colalign=colalign,
    )


def _render_json(sections: list[Section]) -> str:
    """Render sections as JSON output."""
    out_sections: list[dict[str, object]] = []

    for section in sections:
        if not section.rows:
            continue

        out_rows: list[dict[str, object]] = []
        for row in section.rows:
            current_val = row.current.value if row.current.value is not None else None
            latest_val = row.latest.value if row.latest.value is not None else None
            row_data: dict[str, object] = {
                "ecosystem": row.ecosystem,
                "name": row.name,
                "current": current_val,
                "latest": latest_val,
                "state": row.state.value,
                "source": row.source,
                "source_class": row.source_class.value,
                "freshness": row.freshness.value,
            }
            if row.note:
                row_data["note"] = row.note
            if row.current.note and (current_note := _clean_note(row.current.note)):
                row_data["current_note"] = current_note
            if row.latest.note and (latest_note := _clean_note(row.latest.note)):
                row_data["latest_note"] = latest_note
            out_rows.append(row_data)

        out_sections.append({"title": section.title, "rows": out_rows})

    return json.dumps({"sections": out_sections}, indent=2) + "\n"


def render(sections: list[Section], json_output: bool = False) -> str:
    if json_output:
        return _render_json(sections)

    printed: list[str] = []
    for section in sections:
        if not section.rows:
            continue
        printed.append(_summary(section.title, section.rows))
        printed.append(_render_current_latest_table(section.rows))
        printed.append("")

    return "\n".join(printed).rstrip() + "\n"
