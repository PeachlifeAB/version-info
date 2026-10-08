from __future__ import annotations

import json

from version_info.model import Artifact, DepRow, Freshness, Section, SourceClass, State
from version_info.report import _format_current, _format_latest, format_version, render


def testformat_version_update_available() -> None:
    """Test spot updates format shows 'current -> latest' when update available."""
    row = DepRow(
        ecosystem="npm",
        name="lodash",
        current=Artifact(value="2.8.1"),
        latest=Artifact(value="4.19.2"),
        state=State.update_available,
        source="package-lock.json",
    )
    assert format_version(row) == "\033[31m2.8.1 -> 4.19.2\033[0m"


def testformat_version_ok() -> None:
    """Test version display shows current in green when state is ok."""
    row = DepRow(
        ecosystem="npm",
        name="express",
        current=Artifact(value="4.18.2"),
        latest=Artifact(value="4.18.2"),
        state=State.ok,
        source="package-lock.json",
    )
    # When state is ok, version should be displayed in green (ANSI color codes)
    assert format_version(row) == "\033[32m4.18.2\033[0m"


def test_format_current_colors_only_current() -> None:
    ok_row = DepRow(
        ecosystem="npm",
        name="express",
        current=Artifact(value="4.18.2"),
        latest=Artifact(value="4.18.2"),
        state=State.ok,
        source="package-lock.json",
    )
    minor_row = DepRow(
        ecosystem="npm",
        name="express",
        current=Artifact(value="4.18.2"),
        latest=Artifact(value="4.18.3"),
        state=State.update_available,
        source="package-lock.json",
        freshness=Freshness.minor_behind,
    )
    major_row = DepRow(
        ecosystem="npm",
        name="express",
        current=Artifact(value="4.18.2"),
        latest=Artifact(value="5.0.0"),
        state=State.update_available,
        source="package-lock.json",
        freshness=Freshness.major_behind,
    )

    assert _format_current(ok_row) == "\033[32m4.18.2\033[0m"
    assert _format_current(minor_row) == "\033[33m4.18.2\033[0m"
    assert _format_current(major_row) == "\033[31m4.18.2\033[0m"
    assert _format_latest(minor_row) == "4.18.3"


def test_format_current_colors_local_rows_too() -> None:
    local_row = DepRow(
        ecosystem="docker",
        name="ai-deepwiki",
        current=Artifact(value="3.11-slim"),
        latest=Artifact(value="3.14-slim"),
        state=State.local_only,
        source="docker-compose.yml",
        source_class=SourceClass.container_runtime,
    )

    assert _format_current(local_row) == "\033[33m3.11-slim\033[0m"


def testformat_version_not_applicable() -> None:
    """Test version display for not_applicable state."""
    row = DepRow(
        ecosystem="core",
        name="repo",
        current=Artifact(value="my-project"),
        latest=Artifact(value=None, note="(n/a)"),
        state=State.not_applicable,
        source=".",
    )
    assert format_version(row) == "my-project (n/a)"


def testformat_version_local_only() -> None:
    """Test version display for local_only state."""
    row = DepRow(
        ecosystem="npm",
        name="my-local-package",
        current=Artifact(value="1.0.0"),
        latest=Artifact(value=None, note="(local)"),
        state=State.local_only,
        source="package-lock.json",
    )
    assert format_version(row) == "1.0.0 (local)"


def testformat_version_error() -> None:
    """Test version display for error state."""
    row = DepRow(
        ecosystem="npm",
        name="broken-package",
        current=Artifact(value="1.2.3"),
        latest=Artifact(value=None, note="(error)"),
        state=State.error,
        source="package-lock.json",
    )
    assert format_version(row) == "1.2.3 (error)"


def testformat_version_with_note_current() -> None:
    """Test version display avoids literal unknown when current value is absent."""
    row = DepRow(
        ecosystem="npm",
        name="unknown-package",
        current=Artifact(value=None, note="(unknown)"),
        latest=Artifact(value=None, note="(n/a)"),
        state=State.not_found,
        source="package-lock.json",
    )
    assert format_version(row) == "(n/a) (n/a)"


def testformat_version_ok_with_note() -> None:
    """Test green color is applied even when using note instead of value."""
    row = DepRow(
        ecosystem="npm",
        name="special-package",
        current=Artifact(value=None, note="(custom)"),
        latest=Artifact(value=None, note="(custom)"),
        state=State.ok,
        source="package-lock.json",
    )
    # Green color should still be applied even with notes
    assert format_version(row) == "\033[32mcustom\033[0m"


def testformat_version_pinned_no_green() -> None:
    """Test pinned state does not get green color."""
    row = DepRow(
        ecosystem="npm",
        name="pinned-package",
        current=Artifact(value="1.0.0"),
        latest=Artifact(value="2.0.0"),
        state=State.pinned,
        source="package-lock.json",
    )
    # Pinned should not have green color, just the version
    assert format_version(row) == "1.0.0"


def testformat_version_auth_required() -> None:
    """Test version display for auth_required state."""
    row = DepRow(
        ecosystem="npm",
        name="private-package",
        current=Artifact(value="1.0.0"),
        latest=Artifact(value=None, note="(auth)"),
        state=State.auth_required,
        source="package-lock.json",
    )
    assert format_version(row) == "1.0.0 (auth)"


def testformat_version_rate_limited() -> None:
    """Test version display for rate_limited state."""
    row = DepRow(
        ecosystem="npm",
        name="popular-package",
        current=Artifact(value="2.0.0"),
        latest=Artifact(value=None, note="(rate limited)"),
        state=State.rate_limited,
        source="package-lock.json",
    )
    assert format_version(row) == "2.0.0 (rate limited)"


def test_render_table_shows_plus_suffix_versions() -> None:
    sections = [
        Section(
            title="Docker",
            rows=[
                DepRow(
                    ecosystem="docker",
                    name="ai-db-pgbackrest",
                    current=Artifact(value="18.3-1.pgdg12+1"),
                    latest=Artifact(value="18.4-1.pgdg12+1"),
                    state=State.local_only,
                    source="docker-compose.yml",
                )
            ],
        )
    ]

    output = render(sections)

    assert "18.3-1.pgdg12+1" in output
    assert "18.4-1.pgdg12+1" in output


def testformat_version_not_found() -> None:
    """Test version display for not_found state."""
    row = DepRow(
        ecosystem="npm",
        name="deleted-package",
        current=Artifact(value="1.5.0"),
        latest=Artifact(value=None, note="(not found)"),
        state=State.not_found,
        source="package-lock.json",
    )
    assert format_version(row) == "1.5.0 (not found)"


def test_render_table_with_mixed_states() -> None:
    """Test full table rendering with various states."""
    sections = [
        Section(
            title="npm",
            rows=[
                DepRow(
                    ecosystem="npm",
                    name="lodash",
                    current=Artifact(value="2.8.1"),
                    latest=Artifact(value="4.19.2"),
                    state=State.update_available,
                    source="package-lock.json",
                ),
                DepRow(
                    ecosystem="npm",
                    name="express",
                    current=Artifact(value="4.18.2"),
                    latest=Artifact(value="4.18.2"),
                    state=State.ok,
                    source="package-lock.json",
                ),
            ],
        )
    ]

    output = render(sections)

    assert output.startswith("npm  2 deps, 1 update")

    # Check headers
    assert "NAME" in output
    assert "CURRENT" in output
    assert "LATEST" in output
    assert "STATUS" not in output
    assert "SOURCE" in output

    assert "VERSION" not in output

    # Check current/latest split for update_available
    assert "2.8.1" in output
    assert "4.19.2" in output

    # Latest column stays plain; only current carries color
    assert "\033[32m4.19.2\033[0m" not in output
    assert "\033[33m4.19.2\033[0m" not in output
    assert "\033[31m4.19.2\033[0m" not in output
    assert "\033[33m2.8.1\033[0m" in output or "\033[31m2.8.1\033[0m" in output

    # Check that ok state shows current and latest in green
    lines = output.split("\n")
    express_line = next(line for line in lines if "express" in line)
    assert "\033[32m4.18.2\033[0m" in express_line
    assert "->" not in express_line


def test_render_table_omits_status_when_section_has_no_operational_states() -> None:
    sections = [
        Section(
            title="Tools (mise)",
            rows=[
                DepRow(
                    ecosystem="mise",
                    name="gh",
                    current=Artifact(value="2.90.0"),
                    latest=Artifact(value="2.92.0"),
                    state=State.update_available,
                    source="mise.toml",
                ),
                DepRow(
                    ecosystem="mise",
                    name="yq",
                    current=Artifact(value="4.53.2"),
                    latest=Artifact(value="4.53.2"),
                    state=State.ok,
                    source="mise.toml",
                ),
            ],
        )
    ]

    output = render(sections)

    assert "STATUS" not in output
    assert "CURRENT" in output
    assert "LATEST" in output
    assert "SOURCE" in output


def test_render_table_shows_raw_docker_tags_and_status_notes() -> None:
    sections = [
        Section(
            title="Docker",
            rows=[
                DepRow(
                    ecosystem="docker",
                    name="floating-image",
                    current=Artifact(value="latest"),
                    latest=Artifact(value="latest"),
                    state=State.ok,
                    source="docker-compose.yml",
                    source_class=SourceClass.container_runtime,
                ),
                DepRow(
                    ecosystem="docker",
                    name="local-image",
                    current=Artifact(value="1.0.0"),
                    latest=Artifact(value=None, note="local"),
                    state=State.local_only,
                    source="docker-compose.yml",
                    source_class=SourceClass.container_runtime,
                ),
                DepRow(
                    ecosystem="docker",
                    name="private-image",
                    current=Artifact(value="v1.0.0"),
                    latest=Artifact(value=None, note="auth"),
                    state=State.auth_required,
                    source="docker-compose.yml",
                    source_class=SourceClass.container_runtime,
                ),
                DepRow(
                    ecosystem="docker",
                    name="branch-image",
                    current=Artifact(value="main"),
                    latest=Artifact(value="main"),
                    state=State.ok,
                    source="docker-compose.yml",
                    source_class=SourceClass.container_runtime,
                ),
                DepRow(
                    ecosystem="docker",
                    name="variant-image",
                    current=Artifact(value="slim"),
                    latest=Artifact(value=None, note="error"),
                    state=State.error,
                    source="docker-compose.yml",
                    source_class=SourceClass.container_runtime,
                ),
            ],
        )
    ]

    output = render(sections)
    rows = {line.split()[0]: line for line in output.splitlines() if "-image" in line}

    assert "public" in rows["floating-image"]
    assert "1.0.0" in rows["local-image"]
    assert "local" in rows["local-image"]
    assert "private" in rows["private-image"]
    assert "v1.0.0" in rows["private-image"]
    assert "public" in rows["branch-image"]
    assert "main" in rows["branch-image"]
    assert "slim" in rows["variant-image"]
    assert "error" in rows["variant-image"]


def test_summary_uses_domain_nouns_and_pluralization() -> None:
    sections = [
        Section(
            title="Tools (mise)",
            rows=[
                DepRow(
                    ecosystem="mise",
                    name="gh",
                    current=Artifact(value="latest"),
                    latest=Artifact(value=None, note="not checked"),
                    state=State.not_applicable,
                    source="mise.toml",
                ),
                DepRow(
                    ecosystem="mise",
                    name="yq",
                    current=Artifact(value="latest"),
                    latest=Artifact(value=None, note="not checked"),
                    state=State.not_applicable,
                    source="mise.toml",
                ),
            ],
        ),
        Section(
            title="Docker",
            rows=[
                DepRow(
                    ecosystem="docker",
                    name="qdrant",
                    current=Artifact(value="v1.13.6"),
                    latest=Artifact(value="v1.17.1"),
                    state=State.update_available,
                    source="docker-compose.yml",
                )
            ],
        ),
    ]

    output = render(sections)

    assert "Tools (mise)  2 tools" in output
    assert "Docker  1 image, 1 update" in output
    assert "1 updates" not in output


def test_render_empty_sections() -> None:
    """Test rendering with empty sections."""
    sections = [
        Section(title="npm", rows=[]),
        Section(
            title="Ruby",
            rows=[
                DepRow(
                    ecosystem="ruby",
                    name="rails",
                    current=Artifact(value="6.1.0"),
                    latest=Artifact(value="7.0.0"),
                    state=State.update_available,
                    source="Gemfile.lock",
                ),
            ],
        ),
    ]

    output = render(sections)

    # Empty sections should not appear
    assert "npm" not in output

    # Ruby section should appear
    assert "Ruby" in output
    assert "6.1.0" in output
    assert "7.0.0" in output


def test_render_multiple_sections() -> None:
    """Test rendering multiple sections."""
    sections = [
        Section(
            title="npm",
            rows=[
                DepRow(
                    ecosystem="npm",
                    name="react",
                    current=Artifact(value="17.0.0"),
                    latest=Artifact(value="18.2.0"),
                    state=State.update_available,
                    source="package-lock.json",
                ),
            ],
        ),
        Section(
            title="Python",
            rows=[
                DepRow(
                    ecosystem="python",
                    name="django",
                    current=Artifact(value="3.2.0"),
                    latest=Artifact(value="4.2.0"),
                    state=State.update_available,
                    source="requirements.txt",
                ),
            ],
        ),
    ]

    output = render(sections)

    # Both sections should appear
    assert "npm" in output
    assert "Python" in output

    # Current and latest values should appear
    assert "17.0.0" in output
    assert "18.2.0" in output
    assert "3.2.0" in output
    assert "4.2.0" in output


def test_render_json_basic() -> None:
    """Test JSON output format with basic dependencies."""
    sections = [
        Section(
            title="Node (npm)",
            rows=[
                DepRow(
                    ecosystem="npm",
                    name="lodash",
                    current=Artifact(value="4.17.21"),
                    latest=Artifact(value="4.17.21"),
                    state=State.ok,
                    source="package-lock.json",
                ),
                DepRow(
                    ecosystem="npm",
                    name="express",
                    current=Artifact(value="2.8.1"),
                    latest=Artifact(value="4.19.2"),
                    state=State.update_available,
                    source="package-lock.json",
                ),
            ],
        )
    ]

    output = render(sections, json_output=True)
    data = json.loads(output)

    assert "sections" in data
    assert len(data["sections"]) == 1

    section = data["sections"][0]
    assert section["title"] == "Node (npm)"
    assert len(section["rows"]) == 2

    # Check first row (lodash)
    lodash = section["rows"][0]
    assert lodash["ecosystem"] == "npm"
    assert lodash["name"] == "lodash"
    assert lodash["current"] == "4.17.21"
    assert lodash["latest"] == "4.17.21"
    assert lodash["state"] == "ok"
    assert lodash["source"] == "package-lock.json"
    assert lodash["source_class"] == "resolved_lockfile"
    assert lodash["freshness"] == "latest"

    # Check second row (express)
    express = section["rows"][1]
    assert express["ecosystem"] == "npm"
    assert express["name"] == "express"
    assert express["current"] == "2.8.1"
    assert express["latest"] == "4.19.2"
    assert express["state"] == "update_available"
    assert express["source"] == "package-lock.json"
    assert express["source_class"] == "resolved_lockfile"
    assert express["freshness"] == "major_behind"


def test_render_json_multiple_sections() -> None:
    """Test JSON output with multiple ecosystem sections."""
    sections = [
        Section(
            title="Node (npm)",
            rows=[
                DepRow(
                    ecosystem="npm",
                    name="react",
                    current=Artifact(value="17.0.0"),
                    latest=Artifact(value="18.2.0"),
                    state=State.update_available,
                    source="package-lock.json",
                ),
            ],
        ),
        Section(
            title="Ruby (Bundler)",
            rows=[
                DepRow(
                    ecosystem="ruby",
                    name="rails",
                    current=Artifact(value="6.1.0"),
                    latest=Artifact(value="7.0.0"),
                    state=State.update_available,
                    source="Gemfile.lock",
                ),
            ],
        ),
    ]

    output = render(sections, json_output=True)
    data = json.loads(output)

    assert len(data["sections"]) == 2
    assert data["sections"][0]["title"] == "Node (npm)"
    assert data["sections"][1]["title"] == "Ruby (Bundler)"
    assert data["sections"][0]["rows"][0]["name"] == "react"
    assert data["sections"][1]["rows"][0]["name"] == "rails"


def test_render_json_empty_sections() -> None:
    """Test JSON output skips empty sections."""
    sections = [
        Section(title="npm", rows=[]),
        Section(
            title="Ruby (Bundler)",
            rows=[
                DepRow(
                    ecosystem="ruby",
                    name="rake",
                    current=Artifact(value="13.1.0"),
                    latest=Artifact(value="13.1.0"),
                    state=State.ok,
                    source="Gemfile.lock",
                ),
            ],
        ),
    ]

    output = render(sections, json_output=True)
    data = json.loads(output)

    # Empty section should not appear
    assert len(data["sections"]) == 1
    assert data["sections"][0]["title"] == "Ruby (Bundler)"


def test_render_json_null_values() -> None:
    """Test JSON output handles None values correctly."""
    sections = [
        Section(
            title="Node (npm)",
            rows=[
                DepRow(
                    ecosystem="npm",
                    name="private-pkg",
                    current=Artifact(value="1.0.0"),
                    latest=Artifact(value=None, note="(auth)"),
                    state=State.auth_required,
                    source="package-lock.json",
                ),
            ],
        )
    ]

    output = render(sections, json_output=True)
    data = json.loads(output)

    row = data["sections"][0]["rows"][0]
    assert row["current"] == "1.0.0"
    assert row["latest"] is None
    assert row["state"] == "auth_required"
    assert row["source_class"] == "resolved_lockfile"
    assert row["freshness"] == "not_checked"
    assert "\033" not in output


def test_render_json_does_not_reintroduce_unknown_notes() -> None:
    sections = [
        Section(
            title="Test",
            rows=[
                DepRow(
                    ecosystem="npm",
                    name="pkg",
                    current=Artifact(value=None, note="(unknown)"),
                    latest=Artifact(value=None, note="(unknown)"),
                    state=State.error,
                    source="test",
                )
            ],
        )
    ]

    output = render(sections, json_output=True)

    assert "unknown" not in output


def test_render_json_all_states() -> None:
    """Test JSON output handles all state values correctly."""
    sections = [
        Section(
            title="Test",
            rows=[
                DepRow(
                    ecosystem="npm",
                    name="pkg-ok",
                    current=Artifact(value="1.0.0"),
                    latest=Artifact(value="1.0.0"),
                    state=State.ok,
                    source="test",
                ),
                DepRow(
                    ecosystem="npm",
                    name="pkg-update",
                    current=Artifact(value="1.0.0"),
                    latest=Artifact(value="2.0.0"),
                    state=State.update_available,
                    source="test",
                ),
                DepRow(
                    ecosystem="npm",
                    name="pkg-local",
                    current=Artifact(value="1.0.0"),
                    latest=Artifact(value=None),
                    state=State.local_only,
                    source="test",
                ),
                DepRow(
                    ecosystem="npm",
                    name="pkg-error",
                    current=Artifact(value="1.0.0"),
                    latest=Artifact(value=None),
                    state=State.error,
                    source="test",
                ),
            ],
        )
    ]

    output = render(sections, json_output=True)
    data = json.loads(output)

    rows = data["sections"][0]["rows"]
    assert rows[0]["state"] == "ok"
    assert rows[1]["state"] == "update_available"
    assert rows[2]["state"] == "local_only"
    assert rows[3]["state"] == "error"


def test_render_json_no_sections() -> None:
    """Test JSON output with no sections."""
    sections = []

    output = render(sections, json_output=True)
    data = json.loads(output)

    assert data["sections"] == []
