from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from version_info.model import Artifact, State
from version_info.registry_docker import (
    _docker_hub_tags,
    _fetch_latest_docker_image,
    _parse_docker_compose_image_lines,
    _parse_docker_compose_yaml,
    _parse_dockerfile_image_lines,
    _parse_image_string,
    _registry_v2_tags,
    docker_hub_latest,
    registry_v2_latest,
    scan_docker,
)
from version_info.util_exec import ExecResult
from version_info.util_http import HttpResult


class TestParseImageString:
    def test_simple_image(self):
        result = _parse_image_string("nginx")
        assert result is not None
        assert result.name == "nginx"
        assert result.registry == "docker.io"
        assert result.repository == "nginx"
        assert result.tag == "latest"
        assert result.digest is None

    def test_image_with_tag(self):
        result = _parse_image_string("nginx:1.21")
        assert result is not None
        assert result.name == "nginx"
        assert result.tag == "1.21"

    def test_image_with_digest(self):
        result = _parse_image_string("nginx@sha256:abc123def456")
        assert result is not None
        assert result.name == "nginx"
        assert result.tag is None
        assert result.digest == "sha256:abc123def456"

    def test_docker_io_library_image(self):
        result = _parse_image_string("docker.io/library/nginx:latest")
        assert result is not None
        assert result.registry == "docker.io"
        assert result.repository == "nginx"
        assert result.tag == "latest"

    def test_ghcr_image(self):
        result = _parse_image_string("ghcr.io/owner/repo:v1.0")
        assert result is not None
        assert result.registry == "ghcr.io"
        assert result.repository == "owner/repo"
        assert result.tag == "v1.0"

    def test_localhost_image(self):
        result = _parse_image_string("localhost:5000/myimage:latest")
        assert result is not None
        assert result.registry == "localhost:5000"
        assert result.repository == "myimage"
        assert result.tag == "latest"

    def test_empty_string(self):
        result = _parse_image_string("")
        assert result is None

    def test_whitespace_only(self):
        result = _parse_image_string("   ")
        assert result is None

    def test_compose_env_default_image(self):
        result = _parse_image_string(
            "${COMFYUI_MCP_IMAGE:-ghcr.io/dabvid/comfyui-mcp-server:v0.1.1}"
        )
        assert result is not None
        assert result.registry == "ghcr.io"
        assert result.repository == "dabvid/comfyui-mcp-server"
        assert result.tag == "v0.1.1"


class TestParseDockerComposeYaml:
    def test_parse_json_compose(self):
        json_content = json.dumps({
            "version": "3.8",
            "services": {"web": {"image": "nginx:latest"}, "redis": {"image": "redis:alpine"}},
        })
        result = _parse_docker_compose_yaml(json_content)
        assert len(result) == 2
        names = {img.name for img in result}
        assert "nginx" in names
        assert "redis" in names

    def test_parse_json_compose_with_multiple(self):
        json_content = json.dumps({
            "services": {
                "web": {"image": "nginx:1.21"},
                "db": {"image": "postgres:15"},
                "cache": {"image": "redis:alpine"},
            }
        })
        result = _parse_docker_compose_yaml(json_content)
        assert len(result) == 3

    def test_parse_ghcr_image_json(self):
        json_content = json.dumps({"services": {"app": {"image": "ghcr.io/owner/repo:v1.0"}}})
        result = _parse_docker_compose_yaml(json_content)
        assert len(result) == 1
        assert result[0].registry == "ghcr.io"
        assert result[0].repository == "owner/repo"

    def test_parse_empty_services(self):
        json_content = json.dumps({"services": {}})
        result = _parse_docker_compose_yaml(json_content)
        assert len(result) == 0

    def test_parse_compose_with_build_only(self):
        json_content = json.dumps({"services": {"web": {"build": {"context": "."}}}})
        result = _parse_docker_compose_yaml(json_content)
        # Build-only services without image: are now emitted as local build entries
        assert len(result) == 1
        assert result[0].name == "web"
        assert result[0].build_context is True
        assert result[0].registry == ""

    def test_parse_compose_image_with_build_marks_local_context(self):
        json_content = json.dumps({
            "services": {"web": {"build": {"context": "."}, "image": "local-web:latest"}}
        })
        result = _parse_docker_compose_yaml(json_content)
        assert len(result) == 1
        assert result[0].build_context is True

    def test_parse_yaml_compose_without_pyyaml_fallback(self):
        yaml_content = """
name: ai
services:
  tailscale:
    image: tailscale/tailscale:latest
  qdrant:
    image: "qdrant/qdrant:v1.13.6"
  falkordb:
    image: 'falkordb/falkordb-server:v4.18.1' # pinned runtime image
"""
        result = _parse_docker_compose_image_lines(yaml_content)
        assert len(result) == 3
        names = {img.name for img in result}
        assert names == {"tailscale", "qdrant", "falkordb-server"}


class TestParseDockerfileImageLines:
    def test_parse_simple_dockerfile(self):
        dockerfile = """
FROM nginx:latest
RUN apt-get update
FROM python:3.11-slim
"""
        result = _parse_dockerfile_image_lines(dockerfile)
        assert len(result) == 2
        names = {img.name for img in result}
        assert "nginx" in names
        assert "python" in names

    def test_parse_dockerfile_with_as(self):
        dockerfile = """
FROM node:18 AS builder
RUN npm run build
FROM nginx:alpine
"""
        result = _parse_dockerfile_image_lines(dockerfile)
        assert len(result) == 2
        names = {img.name for img in result}
        assert "node" in names
        assert "nginx" in names


class TestDockerHubLatest:
    @patch("version_info.registry_docker.get_json")
    def test_success(self, mock_get_json):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_get_json.return_value = (
            mock_response,
            {"results": [{"name": "1.21"}]},
        )

        artifact, state = docker_hub_latest(repository="nginx", timeout_s=5.0)

        assert state == State.ok
        assert artifact.value == "1.21"

    @patch("version_info.registry_docker.get_json")
    def test_not_found(self, mock_get_json):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status = 404
        mock_response.error = None
        mock_get_json.return_value = (mock_response, None)

        _, state = docker_hub_latest(repository="nonexistent", timeout_s=5.0)

        assert state == State.not_found

    @patch("version_info.registry_docker.get_json")
    def test_rate_limited(self, mock_get_json):
        mock_response = MagicMock()
        mock_response.ok = False
        mock_response.status = 429
        mock_response.error = "rate limited"
        mock_get_json.return_value = (mock_response, None)

        _, state = docker_hub_latest(repository="nginx", timeout_s=5.0)

        assert state == State.rate_limited

    @patch("version_info.registry_docker.get_json")
    def test_no_tags_uses_repository_landing_url(self, mock_get_json):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_get_json.return_value = (mock_response, {"results": [], "next": None})

        tags, _, artifact, state = _docker_hub_tags(repository="library/nginx", timeout_s=5.0)

        assert tags == []
        assert state == State.error
        assert artifact.url == "https://hub.docker.com/r/library/nginx/tags"
        assert artifact.note == "error"


class TestRegistryV2Latest:
    @patch("version_info.registry_docker.get_json")
    def test_success(self, mock_get_json):
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.status = 200
        mock_get_json.return_value = (
            mock_response,
            {"tags": ["v1.0", "v1.1", "latest"]},
        )

        artifact, state = registry_v2_latest(
            registry="ghcr.io",
            repository="owner/repo",
            current_tag="v1.0",
            timeout_s=5.0,
        )

        assert state == State.ok
        assert artifact.value == "v1.1"

    @patch("version_info.registry_docker.get_json")
    def test_ghcr_bearer_auth_challenge(self, mock_get_json):
        challenge = 'Bearer realm="https://ghcr.io/token",service="ghcr.io"'
        mock_get_json.side_effect = [
            (
                HttpResult(
                    ok=False,
                    status=401,
                    text="",
                    error="unauthorized",
                    headers={"Www-Authenticate": challenge},
                ),
                None,
            ),
            (
                HttpResult(ok=True, status=200, text='{"token":"abc"}'),
                {"token": "abc"},
            ),
            (
                HttpResult(ok=True, status=200, text='{"tags":["v1.0","v1.1"]}'),
                {"tags": ["v1.0", "v1.1"]},
            ),
        ]

        tags, artifact, state = _registry_v2_tags(
            registry="ghcr.io",
            repository="owner/repo",
            timeout_s=5.0,
        )

        assert state == State.ok
        assert tags == ["v1.0", "v1.1"]
        assert artifact.url == "https://ghcr.io/v2/owner/repo/tags/list"
        retry_headers = mock_get_json.call_args_list[2].kwargs["headers"]
        assert retry_headers["Authorization"] == "Bearer abc"

    @patch("version_info.registry_docker._get_registry_v2_json")
    def test_ghcr_paginates_next_link_headers(self, mock_get_registry_json):
        mock_get_registry_json.side_effect = [
            (
                {"tags": ["sha-1"]},
                Artifact(
                    value=None,
                    url="https://ghcr.io/v2/open-webui/open-terminal/tags/list",
                ),
                State.ok,
                {
                    "Link": (
                        "<https://ghcr.io/v2/open-webui/open-terminal/tags/list?last=sha-1>"
                        '; rel="next"'
                    )
                },
            ),
            (
                {"tags": ["v0.11.34-slim", "slim"]},
                Artifact(
                    value=None,
                    url="https://ghcr.io/v2/open-webui/open-terminal/tags/list",
                ),
                State.ok,
                {},
            ),
        ]

        tags, artifact, state = _registry_v2_tags(
            registry="ghcr.io",
            repository="open-webui/open-terminal",
            timeout_s=5.0,
        )

        assert state == State.ok
        assert tags == ["sha-1", "v0.11.34-slim", "slim"]
        assert artifact.url == "https://ghcr.io/v2/open-webui/open-terminal/tags/list"
        assert mock_get_registry_json.call_count == 2

    @patch("version_info.registry_docker.get_json")
    def test_auth_challenge_token_failure(self, mock_get_json):
        challenge = 'Bearer realm="https://ghcr.io/token",service="ghcr.io"'
        mock_get_json.side_effect = [
            (
                HttpResult(
                    ok=False,
                    status=401,
                    text="",
                    error="unauthorized",
                    headers={"Www-Authenticate": challenge},
                ),
                None,
            ),
            (
                HttpResult(ok=False, status=403, text="", error="forbidden"),
                None,
            ),
        ]

        tags, artifact, state = _registry_v2_tags(
            registry="ghcr.io",
            repository="owner/repo",
            timeout_s=5.0,
        )

        assert tags == []
        assert state == State.auth_required
        assert artifact.note == "auth"

    @patch("version_info.registry_docker.get_json")
    def test_malformed_response_is_error(self, mock_get_json):
        mock_get_json.return_value = (
            HttpResult(ok=True, status=200, text="[]"),
            [],
        )

        tags, artifact, state = _registry_v2_tags(
            registry="quay.io",
            repository="owner/repo",
            timeout_s=5.0,
        )

        assert tags == []
        assert state == State.error
        assert artifact.note == "error"


class TestScanDocker:
    def test_no_docker_files(self, tmp_path):
        result = scan_docker(str(tmp_path), timeout_s=5.0)
        assert result.title == "Docker"
        assert len(result.rows) == 0

    @patch("version_info.registry_docker._resolve_channel_tag", return_value=None)
    @patch("version_info.registry_docker._fetch_latest_docker_image")
    def test_with_docker_compose(self, mock_fetch, _mock_resolve, tmp_path):
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(json.dumps({"services": {"web": {"image": "nginx:latest"}}}))

        mock_fetch.return_value = (
            MagicMock(value="1.22"),
            State.ok,
        )

        result = scan_docker(str(tmp_path), timeout_s=5.0)
        assert len(result.rows) == 1
        assert result.rows[0].name == "nginx"

    @patch("version_info.registry_docker._resolve_channel_tag", return_value=None)
    @patch("version_info.registry_docker._fetch_latest_docker_image")
    def test_with_compose_yml(self, mock_fetch, _mock_resolve, tmp_path):
        compose_file = tmp_path / "compose.yml"
        compose_file.write_text("services:\n  web:\n    image: nginx:latest\n")

        mock_fetch.return_value = (
            MagicMock(value="1.22"),
            State.ok,
        )

        result = scan_docker(str(tmp_path), timeout_s=5.0)
        assert len(result.rows) == 1
        assert result.rows[0].name == "nginx"

    @patch("version_info.registry_docker._fetch_latest_docker_image")
    def test_with_dockerfile(self, mock_fetch, tmp_path):
        dockerfile = tmp_path / "Dockerfile"
        dockerfile.write_text("""
FROM python:3.11-slim
RUN pip install -r requirements.txt
""")

        mock_fetch.return_value = (
            MagicMock(value="3.12"),
            State.update_available,
        )

        result = scan_docker(str(tmp_path), timeout_s=5.0)
        assert len(result.rows) == 1
        assert result.rows[0].name == "python"
        assert result.rows[0].state == State.update_available

    @patch("version_info.registry_docker._resolve_channel_tag", return_value=None)
    @patch("version_info.registry_docker._fetch_latest_docker_image")
    def test_multiple_images(self, mock_fetch, _mock_resolve, tmp_path):
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            json.dumps({
                "services": {
                    "web": {"image": "nginx:latest"},
                    "db": {"image": "postgres:15"},
                    "cache": {"image": "redis:alpine"},
                }
            })
        )

        def mock_fetch_image(image, timeout_s):
            if image.name == "nginx":
                return MagicMock(value="1.22"), State.ok
            elif image.name == "postgres":
                return MagicMock(value="16"), State.update_available
            else:
                return MagicMock(value="7.2"), State.ok

        mock_fetch.side_effect = mock_fetch_image

        result = scan_docker(str(tmp_path), timeout_s=5.0)
        assert len(result.rows) == 3

    @patch("version_info.registry_docker._fetch_latest_docker_image")
    def test_ghcr_image_in_compose(self, mock_fetch, tmp_path):
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            json.dumps({"services": {"app": {"image": "ghcr.io/owner/repo:v1.0"}}})
        )

        mock_fetch.return_value = (
            MagicMock(value="v2.0"),
            State.update_available,
        )

        result = scan_docker(str(tmp_path), timeout_s=5.0)
        assert len(result.rows) == 1
        assert result.rows[0].name == "ghcr.io/owner/repo"

    @patch("version_info.registry_docker._resolve_channel_tag", return_value=None)
    @patch("version_info.registry_docker._fetch_latest_docker_image")
    def test_error_state_propagation(self, mock_fetch, _mock_resolve, tmp_path):
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(json.dumps({"services": {"web": {"image": "nginx:latest"}}}))

        mock_fetch.return_value = (
            MagicMock(value=None),
            State.rate_limited,
        )

        result = scan_docker(str(tmp_path), timeout_s=5.0)
        assert len(result.rows) == 1
        assert result.rows[0].state == State.rate_limited

    @patch("version_info.registry_docker.run_argv")
    @patch("version_info.registry_docker._docker_hub_tags")
    def test_compose_build_image_is_local_without_registry_lookup(
        self, mock_tags, mock_run_argv, tmp_path
    ):
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            json.dumps({
                "services": {"web": {"build": {"context": "."}, "image": "local-web:latest"}}
            })
        )

        mock_run_argv.return_value = ExecResult(ok=False, stdout="", stderr="missing", exit_code=1)

        result = scan_docker(str(tmp_path), timeout_s=5.0)

        assert len(result.rows) == 1
        assert result.rows[0].state == State.local_only
        assert result.rows[0].current.value == ""
        assert result.rows[0].latest.value is None
        assert result.rows[0].latest.note == "local"
        mock_tags.assert_not_called()

    @patch("version_info.registry_docker.run_argv")
    @patch("version_info.registry_docker._fetch_latest_docker_image")
    def test_compose_build_image_prefers_dockerfile_version_over_inspect(
        self, mock_fetch, mock_run_argv, tmp_path
    ):
        build_dir = tmp_path / "web"
        build_dir.mkdir()
        (build_dir / "Dockerfile").write_text("FROM python:3.11-slim\n")
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            json.dumps({
                "services": {
                    "web": {
                        "build": {"context": "./web"},
                        "image": "ai-deepwiki:latest",
                    }
                }
            })
        )

        mock_run_argv.return_value = ExecResult(
            ok=True,
            stdout=json.dumps([
                {
                    "Config": {
                        "Labels": {},
                        "Env": ["PYTHON_VERSION=3.11.15", "PORT=8001"],
                    }
                }
            ]),
            stderr="",
            exit_code=0,
        )

        def fake_fetch(image, timeout_s):
            assert image.repository == "python"
            assert image.tag == "3.11-slim"
            return MagicMock(value="3.14.0-slim"), State.ok

        mock_fetch.side_effect = fake_fetch

        result = scan_docker(str(tmp_path), timeout_s=5.0)

        # Compose image row + base image row from Dockerfile FROM
        web_rows = [r for r in result.rows if r.name == "ai-deepwiki"]
        assert len(web_rows) == 1
        row = web_rows[0]
        assert row.state == State.local_only
        assert row.current.value == "3.11-slim"
        assert row.latest.value == "3.14.0-slim"
        assert mock_fetch.call_count >= 1

    @patch("version_info.registry_docker.run_argv")
    @patch("version_info.registry_docker._fetch_latest_docker_image")
    def test_compose_build_image_falls_back_to_local_image_metadata_when_dockerfile_is_silent(
        self, mock_fetch, mock_run_argv, tmp_path
    ):
        build_dir = tmp_path / "web"
        build_dir.mkdir()
        (build_dir / "Dockerfile").write_text("FROM python\n")
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            json.dumps({
                "services": {
                    "web": {
                        "build": {"context": "./web"},
                        "image": "ai-deepwiki:latest",
                    }
                }
            })
        )

        mock_run_argv.return_value = ExecResult(
            ok=True,
            stdout=json.dumps([
                {
                    "Config": {
                        "Labels": {},
                        "Env": ["PYTHON_VERSION=3.11.15", "PORT=8001"],
                    }
                }
            ]),
            stderr="",
            exit_code=0,
        )
        mock_fetch.return_value = (MagicMock(value=None, note="local"), State.local_only)

        result = scan_docker(str(tmp_path), timeout_s=5.0)

        # Compose image row + base image row from Dockerfile FROM
        web_rows = [r for r in result.rows if r.name == "ai-deepwiki"]
        assert len(web_rows) == 1
        row = web_rows[0]
        assert row.state == State.local_only
        assert row.current.value == "3.11.15"
        assert row.latest.value is None
        assert row.latest.note == "local"
        assert mock_fetch.call_count >= 1

    def test_fetch_latest_never_returns_uncomparable_note_for_channel(self):
        image = _parse_image_string("nginx:latest")
        assert image is not None
        with patch("version_info.registry_docker._docker_hub_tags") as mock_tags:
            mock_tags.return_value = (
                ["latest", "1.27"],
                {},
                MagicMock(value=None, url="https://hub.docker.com/r/library/nginx/tags", note=None),
                State.ok,
            )
            artifact, state = _fetch_latest_docker_image(image=image, timeout_s=5.0)

        assert state == State.ok
        assert artifact.value == "1.27"
        assert artifact.note != "uncomparable"

    @patch("version_info.registry_docker._docker_hub_tags")
    def test_scan_channel_tag_uses_resolved_version_in_current_and_latest(
        self, mock_tags, tmp_path
    ):
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(json.dumps({"services": {"web": {"image": "nginx:latest"}}}))
        mock_tags.return_value = (
            ["latest", "1.26", "1.27"],
            {},
            MagicMock(value=None, url="https://hub.docker.com/r/library/nginx/tags", note=None),
            State.ok,
        )

        result = scan_docker(str(tmp_path), timeout_s=5.0)

        assert len(result.rows) == 1
        row = result.rows[0]
        assert row.current.value == "1.27"
        assert row.latest.value == "1.27"
        assert row.state == State.ok

    @patch("version_info.registry_docker._docker_hub_tags")
    def test_scan_variant_only_tag_uses_resolved_version_in_current_and_latest(
        self, mock_tags, tmp_path
    ):
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(json.dumps({"services": {"web": {"image": "python:slim"}}}))
        mock_tags.return_value = (
            ["3.11-slim", "3.12-slim", "3.12-alpine"],
            {},
            MagicMock(value=None, url="https://hub.docker.com/r/library/python/tags", note=None),
            State.ok,
        )

        result = scan_docker(str(tmp_path), timeout_s=5.0)

        assert len(result.rows) == 1
        row = result.rows[0]
        assert row.current.value == "3.12-slim"
        assert row.latest.value == "3.12-slim"
        assert row.state == State.ok

    @patch("version_info.registry_docker.get_json")
    def test_digest_pinned_tag_uses_manifest_digest(self, mock_get_json):
        image = _parse_image_string("nginx:1.27@sha256:old123")
        assert image is not None
        mock_get_json.return_value = (
            HttpResult(
                ok=True,
                status=200,
                text="{}",
                headers={"Docker-Content-Digest": "sha256:new456"},
            ),
            {},
        )

        artifact, state = _fetch_latest_docker_image(image=image, timeout_s=5.0)

        assert state == State.ok
        assert artifact.value == "sha256:new456"
        assert mock_get_json.call_args.args[0] == (
            "https://registry-1.docker.io/v2/library/nginx/manifests/1.27"
        )


class TestIntegration:
    @pytest.fixture
    def sample_project(self, tmp_path):
        compose_file = tmp_path / "docker-compose.yml"
        compose_file.write_text(
            json.dumps({
                "version": "3.8",
                "services": {
                    "frontend": {"image": "nginx:1.21"},
                    "backend": {"image": "python:3.11"},
                    "database": {"image": "postgres:15"},
                },
            })
        )
        return tmp_path

    @patch("version_info.registry_docker._fetch_latest_docker_image")
    def test_full_scan_integration(self, mock_fetch, sample_project):
        def mock_fetch_image(image, timeout_s):
            states = {
                "nginx": (State.ok, "1.21"),
                "python": (State.update_available, "3.12"),
                "postgres": (State.update_available, "16"),
            }
            if image.name in states:
                state, value = states[image.name]
                return MagicMock(value=value), state
            return MagicMock(value=None), State.error

        mock_fetch.side_effect = mock_fetch_image

        result = scan_docker(str(sample_project), timeout_s=5.0)

        assert result.title == "Docker"
        assert len(result.rows) == 3

        nginx_row = next(r for r in result.rows if r.name == "nginx")
        assert nginx_row.state == State.ok

        python_row = next(r for r in result.rows if r.name == "python")
        assert python_row.state == State.update_available

        postgres_row = next(r for r in result.rows if r.name == "postgres")
        assert postgres_row.state == State.update_available
