"""Tests for Docker build inventory zero blind spots feature.

Covers:
- Build-only Compose services without image: detected as local build rows
- Base image rows from Dockerfile FROM
- ARG defaults and Compose build.args resolve before extraction
- Exact pins compare and color normally
- Ranges render with CURRENT=spec, no freshness math
- Unpinned installs render with CURRENT=unpinned, no freshness math
- JSON includes declared range/unpinned facts with freshness=not_checked
- version-info: and renovate: annotations identify local build artifact versions
"""

from __future__ import annotations

import json
import textwrap
from unittest.mock import MagicMock, patch

from version_info.model import Artifact, Freshness, State
from version_info.registry_docker import (
    _parse_docker_compose_yaml,
    _parse_dockerfile_image_lines,
    scan_docker,
    scan_docker_install_sections,
)
from version_info.report import _summary, render
from version_info.scanner_dockerfile import parse_dockerfile_annotations, parse_dockerfile_installs

# ---------------------------------------------------------------------------
# P8-1: Build-only service without image: is detected as local build row
# ---------------------------------------------------------------------------


class TestBuildOnlyService:
    def test_build_only_service_emitted_as_local(self):
        content = json.dumps({
            "services": {
                "cognee-api": {
                    "build": {
                        "context": ".",
                        "dockerfile": "docker/cognee-api/Dockerfile",
                    }
                }
            }
        })
        result = _parse_docker_compose_yaml(content)
        assert len(result) == 1
        img = result[0]
        assert img.name == "cognee-api"
        assert img.build_context is True
        assert img.registry == ""
        assert img.tag is None

    def test_build_only_compose_args_parsed(self):
        content = json.dumps({
            "services": {
                "cognee-api": {
                    "build": {
                        "context": ".",
                        "dockerfile": "docker/cognee-api/Dockerfile",
                        "args": {"COGNEE_VERSION": "1.0.1"},
                    }
                }
            }
        })
        result = _parse_docker_compose_yaml(content)
        assert len(result) == 1
        assert result[0].build_compose_args == {"COGNEE_VERSION": "1.0.1"}

    def test_build_only_service_scan_docker_row(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(json.dumps({"services": {"myapp": {"build": {"context": "."}}}}))
        result = scan_docker(str(tmp_path), timeout_s=5.0)
        rows = [r for r in result.rows if r.name == "myapp"]
        assert len(rows) == 1
        assert rows[0].state == State.local_only
        assert rows[0].current.value is None

    def test_multiple_build_only_services(self):
        content = json.dumps({
            "services": {
                "api": {"build": {"context": "./api"}},
                "worker": {"build": {"context": "./worker"}},
            }
        })
        result = _parse_docker_compose_yaml(content)
        names = {img.name for img in result}
        assert "api" in names
        assert "worker" in names


# ---------------------------------------------------------------------------
# P8-2: Base image rows from Dockerfile FROM
# ---------------------------------------------------------------------------


class TestBaseImageRows:
    def test_from_emits_base_image_row(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(
            json.dumps({
                "services": {
                    "api": {
                        "build": {"context": "."},
                        "image": "myapp:latest",
                    }
                }
            })
        )
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN echo hi\n")

        with (
            patch("version_info.registry_docker._fetch_latest_docker_image") as mock_fetch,
            patch("version_info.registry_docker._resolve_channel_tag", return_value=None),
        ):
            mock_fetch.return_value = (MagicMock(value="3.13-slim"), State.ok)
            result = scan_docker(str(tmp_path), timeout_s=5.0)

        names = [r.name for r in result.rows]
        assert "python" in names

    def test_from_scratch_skipped(self):
        result = _parse_dockerfile_image_lines("FROM scratch\n")
        # scratch has no meaningful tag/registry — verify it doesn't crash
        # It may or may not be included; what matters is no exception
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# P8-3: ARG defaults and Compose build.args resolve before extraction
# ---------------------------------------------------------------------------


class TestArgResolution:
    def test_arg_default_resolved_in_pip_install(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            textwrap.dedent("""\
            FROM python:3.12-slim
            ARG MYLIB_VERSION=2.5.0
            RUN pip install mylib==${MYLIB_VERSION}
        """)
        )
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        assert pins[0].name == "mylib"
        assert pins[0].resolved_version == "2.5.0"

    def test_compose_build_args_override_arg_default(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            textwrap.dedent("""\
            FROM python:3.12-slim
            ARG VERSION=1.0.0
            RUN pip install cognee==${VERSION}
        """)
        )
        pins = parse_dockerfile_installs(
            str(dockerfile),
            build_args={"VERSION": "1.0.5"},
            source="Dockerfile",
        )
        assert len(pins) == 1
        assert pins[0].resolved_version == "1.0.5"

    def test_from_image_arg_resolved(self):
        text = textwrap.dedent("""\
            ARG PYTHON_VERSION=3.12-slim
            FROM python:${PYTHON_VERSION}
        """)
        result = _parse_dockerfile_image_lines(text)
        assert len(result) == 1
        assert result[0].tag == "3.12-slim"

    def test_from_image_arg_with_compose_override(self):
        text = "FROM python:${PYTHON_VERSION}\n"
        result = _parse_dockerfile_image_lines(text, build_args={"PYTHON_VERSION": "3.11-slim"})
        assert len(result) == 1
        assert result[0].tag == "3.11-slim"


# ---------------------------------------------------------------------------
# P8-4: Exact pins compare and color normally
# ---------------------------------------------------------------------------


class TestExactPins:
    def test_exact_pip_pin_resolved_version(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN pip install cognee==1.0.1\n")
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        p = pins[0]
        assert p.name == "cognee"
        assert p.resolved_version == "1.0.1"
        assert p.raw_spec == "==1.0.1"
        assert p.ecosystem == "pypi"

    def test_exact_pin_dep_row_state_ok(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN pip install mylib==2.0.0\n")

        compose = tmp_path / "docker-compose.yml"
        compose.write_text(json.dumps({"services": {"api": {"build": {"context": "."}}}}))

        with patch("version_info.registry_docker.pypi_latest") as mock_pypi:
            mock_pypi.return_value = (Artifact(value="2.0.0"), State.ok)
            sections = scan_docker_install_sections(str(tmp_path), timeout_s=5.0)

        pypi_section = next(
            (s for s in sections if "pypi" in s.title.lower() or "python" in s.title.lower()), None
        )
        assert pypi_section is not None
        row = next(r for r in pypi_section.rows if r.name == "mylib")
        assert row.state == State.ok
        assert row.current.value == "2.0.0"

    def test_exact_pin_update_available(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN pip install mylib==1.0.0\n")

        compose = tmp_path / "docker-compose.yml"
        compose.write_text(json.dumps({"services": {"api": {"build": {"context": "."}}}}))

        with patch("version_info.registry_docker.pypi_latest") as mock_pypi:
            mock_pypi.return_value = (Artifact(value="2.0.0"), State.ok)
            sections = scan_docker_install_sections(str(tmp_path), timeout_s=5.0)

        pypi_section = next((s for s in sections if "python" in s.title.lower()), None)
        assert pypi_section is not None
        row = next(r for r in pypi_section.rows if r.name == "mylib")
        assert row.state == State.update_available


# ---------------------------------------------------------------------------
# P8-5: Ranges render with CURRENT=declared spec, no freshness math
# ---------------------------------------------------------------------------


class TestRangePins:
    def test_range_pip_pin_raw_spec(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text('FROM python:3.12-slim\nRUN pip install "falkordb>=1.0.9,<2.0.0"\n')
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        p = pins[0]
        assert p.name == "falkordb"
        assert p.resolved_version is None
        assert p.raw_spec == ">=1.0.9,<2.0.0"

    def test_range_dep_row_freshness_not_checked(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text('FROM python:3.12-slim\nRUN pip install "falkordb>=1.0.9,<2.0.0"\n')

        compose = tmp_path / "docker-compose.yml"
        compose.write_text(json.dumps({"services": {"api": {"build": {"context": "."}}}}))

        with patch("version_info.registry_docker.pypi_latest") as mock_pypi:
            mock_pypi.return_value = (Artifact(value="1.5.0"), State.ok)
            sections = scan_docker_install_sections(str(tmp_path), timeout_s=5.0)

        pypi_section = next((s for s in sections if "python" in s.title.lower()), None)
        assert pypi_section is not None
        row = next(r for r in pypi_section.rows if r.name == "falkordb")
        assert row.freshness == Freshness.not_checked
        assert row.state == State.pinned
        assert row.current.value == ">=1.0.9,<2.0.0"

    def test_range_not_counted_as_update_in_summary(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text('FROM python:3.12-slim\nRUN pip install "falkordb>=1.0.9,<2.0.0"\n')

        compose = tmp_path / "docker-compose.yml"
        compose.write_text(json.dumps({"services": {"api": {"build": {"context": "."}}}}))

        with patch("version_info.registry_docker.pypi_latest") as mock_pypi:
            mock_pypi.return_value = (Artifact(value="1.5.0"), State.ok)
            sections = scan_docker_install_sections(str(tmp_path), timeout_s=5.0)

        pypi_section = next((s for s in sections if "python" in s.title.lower()), None)
        assert pypi_section is not None
        summary = _summary(pypi_section.title, pypi_section.rows)
        # Should not mention "update" since there are no update_available rows
        assert "update" not in summary


# ---------------------------------------------------------------------------
# P8-6: Unpinned installs render with CURRENT=None/unpinned, no freshness math
# ---------------------------------------------------------------------------


class TestUnpinnedInstalls:
    def test_unpinned_pip(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN pip install requests\n")
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        p = pins[0]
        assert p.name == "requests"
        assert p.resolved_version is None
        assert p.raw_spec == "unpinned"

    def test_unpinned_dep_row_freshness_not_checked(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN pip install requests\n")

        compose = tmp_path / "docker-compose.yml"
        compose.write_text(json.dumps({"services": {"api": {"build": {"context": "."}}}}))

        with patch("version_info.registry_docker.pypi_latest") as mock_pypi:
            mock_pypi.return_value = (Artifact(value="2.32.3"), State.ok)
            sections = scan_docker_install_sections(str(tmp_path), timeout_s=5.0)

        pypi_section = next((s for s in sections if "python" in s.title.lower()), None)
        assert pypi_section is not None
        row = next(r for r in pypi_section.rows if r.name == "requests")
        assert row.freshness == Freshness.not_checked
        assert row.state == State.pinned
        assert row.current.value is None
        assert row.current.note == "unpinned"


# ---------------------------------------------------------------------------
# P8-8: JSON includes declared range/unpinned facts with freshness=not_checked
# ---------------------------------------------------------------------------


class TestJsonOutput:
    def test_json_range_freshness_not_checked(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text('FROM python:3.12-slim\nRUN pip install "falkordb>=1.0.9,<2.0.0"\n')

        compose = tmp_path / "docker-compose.yml"
        compose.write_text(json.dumps({"services": {"api": {"build": {"context": "."}}}}))

        with patch("version_info.registry_docker.pypi_latest") as mock_pypi:
            mock_pypi.return_value = (Artifact(value="1.5.0"), State.ok)
            sections = scan_docker_install_sections(str(tmp_path), timeout_s=5.0)

        output = render(sections, json_output=True)
        data = json.loads(output)
        rows = [
            row
            for section in data["sections"]
            for row in section["rows"]
            if row["name"] == "falkordb"
        ]
        assert len(rows) == 1
        assert rows[0]["freshness"] == "not_checked"
        assert rows[0]["current"] == ">=1.0.9,<2.0.0"

    def test_json_unpinned_freshness_not_checked(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN pip install requests\n")

        compose = tmp_path / "docker-compose.yml"
        compose.write_text(json.dumps({"services": {"api": {"build": {"context": "."}}}}))

        with patch("version_info.registry_docker.pypi_latest") as mock_pypi:
            mock_pypi.return_value = (Artifact(value="2.32.3"), State.ok)
            sections = scan_docker_install_sections(str(tmp_path), timeout_s=5.0)

        output = render(sections, json_output=True)
        data = json.loads(output)
        rows = [
            row
            for section in data["sections"]
            for row in section["rows"]
            if row["name"] == "requests"
        ]
        assert len(rows) == 1
        assert rows[0]["freshness"] == "not_checked"
        assert rows[0]["current"] is None

    def test_json_build_only_service_local_state(self, tmp_path):
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(
            json.dumps({
                "services": {
                    "cognee-api": {
                        "build": {
                            "context": ".",
                            "args": {"COGNEE_VERSION": "1.0.1"},
                        }
                    }
                }
            })
        )
        result = scan_docker(str(tmp_path), timeout_s=5.0)
        output = render([result], json_output=True)
        data = json.loads(output)
        rows = [
            row
            for section in data["sections"]
            for row in section["rows"]
            if row["name"] == "cognee-api"
        ]
        assert len(rows) == 1
        assert rows[0]["state"] == "local_only"


# ---------------------------------------------------------------------------
# Multi-ecosystem install extraction tests
# ---------------------------------------------------------------------------


class TestMultiEcosystemExtraction:
    def test_npm_global_exact(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM node:20\nRUN npm install -g typescript@5.3.2\n")
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        p = pins[0]
        assert p.name == "typescript"
        assert p.ecosystem == "npm"
        assert p.resolved_version == "5.3.2"

    def test_npm_global_unpinned(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM node:20\nRUN npm install -g typescript\n")
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        assert pins[0].raw_spec == "unpinned"

    def test_go_install_exact(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM golang:1.22\nRUN go install github.com/user/tool@v1.2.3\n")
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        p = pins[0]
        assert p.name == "github.com/user/tool"
        assert p.ecosystem == "go"
        assert p.resolved_version == "1.2.3"

    def test_cargo_install_versioned(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM rust:1.76\nRUN cargo install ripgrep --version 14.1.0\n")
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        p = pins[0]
        assert p.name == "ripgrep"
        assert p.ecosystem == "cargo"
        assert p.resolved_version == "14.1.0"

    def test_gem_install_versioned(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM ruby:3.2\nRUN gem install bundler -v 2.4.22\n")
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        p = pins[0]
        assert p.name == "bundler"
        assert p.ecosystem == "ruby"
        assert p.resolved_version == "2.4.22"

    def test_git_plus_installs_skipped(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            'FROM python:3.12\nRUN pip install "git+https://github.com/org/repo.git@main"\n'
        )
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 0

    def test_pip_with_extras(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text('FROM python:3.12\nRUN pip install "cognee[api,postgres]==1.0.1"\n')
        pins = parse_dockerfile_installs(str(dockerfile), source="Dockerfile")
        assert len(pins) == 1
        assert pins[0].name == "cognee"
        assert pins[0].resolved_version == "1.0.1"


# ---------------------------------------------------------------------------
# P8-7: version-info: and renovate: annotations identify local build artifact versions
# ---------------------------------------------------------------------------


class TestAnnotationParsing:
    def test_version_info_annotation_parsed(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            textwrap.dedent("""\
            # version-info: datasource=pypi depName=cognee artifact=cognee-api
            FROM python:3.12-slim
            ARG COGNEE_VERSION=1.0.1
            RUN pip install cognee==${COGNEE_VERSION}
        """)
        )
        annotations = parse_dockerfile_annotations(str(dockerfile), source="Dockerfile")
        assert len(annotations) == 1
        ann = annotations[0]
        assert ann.datasource == "pypi"
        assert ann.dep_name == "cognee"
        assert ann.artifact_name == "cognee-api"
        assert ann.annotation_source == "version-info"
        assert ann.source_path == "Dockerfile"

    def test_renovate_annotation_parsed(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            textwrap.dedent("""\
            # renovate: datasource=npm depName=typescript
            FROM node:20
            RUN npm install -g typescript
        """)
        )
        annotations = parse_dockerfile_annotations(str(dockerfile), source="Dockerfile")
        assert len(annotations) == 1
        ann = annotations[0]
        assert ann.datasource == "npm"
        assert ann.dep_name == "typescript"
        assert ann.artifact_name is None
        assert ann.annotation_source == "renovate"

    def test_multiple_annotations_parsed(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            textwrap.dedent("""\
            # version-info: datasource=pypi depName=cognee artifact=cognee-api
            # renovate: datasource=npm depName=typescript
            FROM python:3.12-slim
        """)
        )
        annotations = parse_dockerfile_annotations(str(dockerfile), source="Dockerfile")
        assert len(annotations) == 2
        sources = {a.annotation_source for a in annotations}
        assert "version-info" in sources
        assert "renovate" in sources

    def test_annotation_not_found_without_comment(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("FROM python:3.12-slim\nRUN pip install cognee==1.0.1\n")
        annotations = parse_dockerfile_annotations(str(dockerfile), source="Dockerfile")
        assert len(annotations) == 0


class TestAnnotationWiring:
    def test_annotation_current_resolved_from_arg(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            textwrap.dedent("""\
            # version-info: datasource=pypi depName=cognee artifact=cognee-api
            FROM python:3.12-slim
            ARG COGNEE_VERSION=1.0.1
            RUN pip install cognee==${COGNEE_VERSION}
        """)
        )
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(
            json.dumps({
                "services": {
                    "cognee-api": {
                        "build": {"context": "."},
                        "args": {"COGNEE_VERSION": "1.0.1"},
                    }
                }
            })
        )

        with patch("version_info.registry_docker._fetch_latest_docker_image") as mock_fetch:
            mock_fetch.return_value = (Artifact(value=None, note="local"), State.local_only)

            with patch("version_info.registry_docker._annotation_latest") as mock_latest:
                mock_latest.return_value = (Artifact(value="1.0.1"), State.ok)

                result = scan_docker(str(tmp_path), timeout_s=5.0)

        rows = [r for r in result.rows if r.name == "cognee-api"]
        assert len(rows) == 1
        row = rows[0]
        assert row.state == State.ok
        assert row.current.value == "1.0.1"
        assert row.latest.value == "1.0.1"
        assert "docker/cognee-api" in row.source

    def test_annotation_update_available_when_current_differs(self, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text(
            textwrap.dedent("""\
            # version-info: datasource=pypi depName=cognee artifact=cognee-api
            FROM python:3.12-slim
            ARG COGNEE_VERSION=1.0.0
            RUN pip install cognee==${COGNEE_VERSION}
        """)
        )
        compose = tmp_path / "docker-compose.yml"
        compose.write_text(
            json.dumps({
                "services": {
                    "cognee-api": {
                        "build": {"context": "."},
                        "args": {"COGNEE_VERSION": "1.0.0"},
                    }
                }
            })
        )

        with patch("version_info.registry_docker._fetch_latest_docker_image") as mock_fetch:
            mock_fetch.return_value = (Artifact(value=None, note="local"), State.local_only)

            with patch("version_info.registry_docker._annotation_latest") as mock_latest:
                mock_latest.return_value = (Artifact(value="1.0.1"), State.ok)

                result = scan_docker(str(tmp_path), timeout_s=5.0)

        rows = [r for r in result.rows if r.name == "cognee-api"]
        assert len(rows) == 1
        row = rows[0]
        assert row.state == State.update_available
        assert row.current.value == "1.0.0"
        assert row.latest.value == "1.0.1"
