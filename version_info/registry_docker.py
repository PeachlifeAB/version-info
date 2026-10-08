from __future__ import annotations

import json
import logging
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse

from .docker_versioning import (
    BRANCH_TAGS,
    CHANNEL_TAGS,
    best_docker_update,
    docker_freshness,
    parse_docker_tag,
)
from .model import (
    Artifact,
    ArtifactAnnotation,
    DepRow,
    Freshness,
    InstallPin,
    Section,
    SourceClass,
    State,
)
from .parallel import map_bounded_ordered
from .registry_cargo import crates_io_latest
from .registry_go import go_proxy_latest
from .registry_npm import npm_latest
from .registry_pypi import pypi_latest
from .registry_ruby import rubygems_org_latest
from .scanner_dockerfile import parse_dockerfile_annotations, parse_dockerfile_installs
from .util_exec import run_argv
from .util_http import get_json

_yaml: Any
try:
    import yaml as _yaml
except ImportError:
    _yaml = None

logger = logging.getLogger(__name__)

_bearer_token_cache: dict[str, str] = {}  # keyed by "registry/repository"


@dataclass(frozen=True)
class DockerImage:
    name: str
    registry: str
    repository: str
    tag: str | None
    digest: str | None
    source: str = "docker-compose.yml"
    build_context: bool = False
    build_context_path: str | None = None
    build_dockerfile: str | None = None
    service_name: str | None = None
    build_compose_args: dict[str, str] | None = None


_ENV_DEFAULT_RE = re.compile(r"^\$\{[^}:]+(?::?-)(.+)\}$")


def _resolve_image_reference(image_str: str) -> str:
    """Resolve simple compose image defaults like ${IMAGE:-repo/name:tag}."""
    match = _ENV_DEFAULT_RE.match(image_str.strip())
    if match:
        return match.group(1).strip()
    return image_str


def _parse_image_string(image_str: str) -> DockerImage | None:
    """Parse a Docker image string into components.

    Supports formats:
    - nginx
    - nginx:latest
    - nginx:1.21
    - docker.io/library/nginx:latest
    - docker.io/library/nginx@sha256:abc123
    - ghcr.io/owner/repo:v1.0
    - localhost:5000/myimage:latest
    """
    image_str = _resolve_image_reference(image_str).strip()
    if not image_str:
        return None

    digest: str | None = None
    tag: str | None = "latest"

    if "@" in image_str:
        parts = image_str.split("@", 1)
        image_str = parts[0]
        if parts[1].startswith("sha256:"):
            digest = parts[1]
            tag = None

    registry = "docker.io"
    repository = image_str

    if "/" in image_str:
        parts = image_str.split("/", 1)
        potential_registry = parts[0]
        if potential_registry.startswith("localhost") or "." in potential_registry:
            registry = potential_registry
            repository = parts[1]
        else:
            repository = image_str

    if ":" in repository and not repository.startswith(":"):
        parts = repository.rsplit(":", 1)
        potential_tag = parts[1]
        if "/" not in potential_tag:
            tag = potential_tag
            repository = parts[0]

    if repository.startswith("library/"):
        repository = repository[7:]

    repository = repository.lstrip("/")

    name = repository.split("/")[-1]
    if ":" in name:
        name = name.split(":")[0]

    return DockerImage(
        name=name,
        registry=registry,
        repository=repository,
        tag=tag,
        digest=digest,
    )


def _parse_build_args(build: dict[str, object]) -> dict[str, str]:
    """Extract static build args from a compose service build dict."""
    args = build.get("args")
    result: dict[str, str] = {}
    if isinstance(args, dict):
        for k, v in args.items():
            if isinstance(k, str) and isinstance(v, (str, int, float)):
                result[k] = str(v)
    elif isinstance(args, list):
        for item in args:
            if isinstance(item, str) and "=" in item:
                k, _, v = item.partition("=")
                result[k.strip()] = v.strip()
    return result


def _parse_compose_build(
    service: dict[str, object],
) -> tuple[bool, str | None, str | None, dict[str, str]]:
    """Return (has_build_context, context_path, dockerfile, compose_args) for a service dict."""
    build = service.get("build")
    if isinstance(build, str):
        return True, build.strip() or None, None, {}
    if isinstance(build, dict):
        ctx = build.get("context")
        ctx_path = ctx.strip() if isinstance(ctx, str) and ctx.strip() else None
        df = build.get("dockerfile")
        df_path = df.strip() if isinstance(df, str) and df.strip() else None
        return True, ctx_path, df_path, _parse_build_args(build)
    return "build" in service, None, None, {}


def _load_compose_data(text: str) -> dict[str, object] | None:
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    if _yaml is not None:
        try:
            data = _yaml.safe_load(text)
            return data if isinstance(data, dict) else None
        except Exception as exc:
            logger.debug("yaml.safe_load failed: %s", exc)
    return None


def _parse_docker_compose_yaml(text: str) -> list[DockerImage]:
    """Parse a docker-compose.yml file and extract all image references."""
    data = _load_compose_data(text)
    if data is None:
        return _parse_docker_compose_image_lines(text)

    services = data.get("services", {})
    if not isinstance(services, dict):
        return []

    images: dict[str, DockerImage] = {}
    for svc_name, service in services.items():
        if not isinstance(service, dict):
            continue

        build_context, build_context_path, build_dockerfile, compose_args = _parse_compose_build(
            service
        )

        image = service.get("image")
        if isinstance(image, str):
            parsed = _parse_image_string(image)
            if parsed:
                parsed = replace(
                    parsed,
                    build_context=build_context,
                    build_context_path=build_context_path,
                    build_dockerfile=build_dockerfile,
                    service_name=svc_name,
                    build_compose_args=compose_args if compose_args else None,
                )
                key = f"{parsed.registry}/{parsed.repository}"
                if parsed.tag:
                    key = f"{key}:{parsed.tag}"
                if key not in images:
                    images[key] = parsed
        elif build_context:
            synthetic = DockerImage(
                name=svc_name,
                registry="",
                repository="",
                tag=None,
                digest=None,
                source="docker-compose.yml",
                build_context=True,
                build_context_path=build_context_path,
                build_dockerfile=build_dockerfile,
                service_name=svc_name,
                build_compose_args=compose_args if compose_args else None,
            )
            key = f"__build__/{svc_name}"
            if key not in images:
                images[key] = synthetic

    return [images[k] for k in sorted(images.keys(), key=lambda x: x.lower())]


def _strip_yaml_scalar(value: str) -> str:
    value = value.strip()
    if " #" in value:
        value = value.split(" #", 1)[0].strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        value = value[1:-1]
    return value.strip()


def _flush_compose_line_pending(
    images: dict[str, DockerImage],
    pending_image: str | None,
    service_has_build: bool,
    service_build_context: str | None,
    service_build_dockerfile: str | None,
) -> None:
    if pending_image is None:
        return
    parsed = _parse_image_string(pending_image)
    if parsed:
        parsed = replace(
            parsed,
            build_context=service_has_build,
            build_context_path=service_build_context,
            build_dockerfile=service_build_dockerfile,
        )
        key = f"{parsed.registry}/{parsed.repository}"
        if parsed.tag:
            key = f"{key}:{parsed.tag}"
        images.setdefault(key, parsed)


@dataclass
class _ComposeSvcState:
    pending_image: str | None = None
    has_build: bool = False
    build_context: str | None = None
    build_dockerfile: str | None = None

    def flush(self, images: dict[str, DockerImage]) -> None:
        _flush_compose_line_pending(
            images, self.pending_image, self.has_build, self.build_context, self.build_dockerfile
        )
        self.pending_image = None
        self.has_build = False
        self.build_context = None
        self.build_dockerfile = None

    def apply_build_key(self, key: str, val: str) -> None:
        if key == "build":
            self.has_build = True
            if val:
                self.build_context = val
        elif self.has_build and key == "context" and val:
            self.build_context = val
        elif self.has_build and key == "dockerfile" and val:
            self.build_dockerfile = val


def _parse_docker_compose_image_lines(text: str) -> list[DockerImage]:
    """Small stdlib fallback for compose files when PyYAML is unavailable."""
    images: dict[str, DockerImage] = {}
    services_indent: int | None = None
    service_indent: int | None = None
    svc = _ComposeSvcState()

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        stripped = raw_line.strip()
        indent = len(raw_line) - len(raw_line.lstrip(" "))

        if stripped == "services:" or stripped.startswith("services: #"):
            services_indent = indent
            continue
        if services_indent is None:
            continue
        if indent <= services_indent:
            svc.flush(images)
            services_indent = None
            continue
        if indent == services_indent + 2 and stripped.endswith(":"):
            svc.flush(images)
            service_indent = indent
            continue
        if service_indent is not None and indent <= service_indent:
            svc.flush(images)

        key, _, rest = stripped.partition(":")
        val = _strip_yaml_scalar(rest)
        if key in ("build", "context", "dockerfile"):
            svc.apply_build_key(key, val)
        elif key == "image":
            svc.pending_image = val

    svc.flush(images)
    return [images[k] for k in sorted(images.keys(), key=lambda x: x.lower())]


_ARG_SUBST_RE = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?[-=][^}]*)?\}|\$([A-Za-z_][A-Za-z0-9_]*)"
)


def _resolve_arg_refs(text: str, build_args: dict[str, str]) -> str:
    """Substitute ARG variable references in a string."""

    def _sub(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        return build_args.get(name, m.group(0))

    return _ARG_SUBST_RE.sub(_sub, text)


def _annotation_current(
    ann: ArtifactAnnotation,
    dockerfile_path: str,
    build_args: dict[str, str],
) -> str | None:
    """Resolve the current version for an annotation from the Dockerfile.

    Parses the Dockerfile for install pins matching ann.dep_name, extracts
    the ARG variable name from the raw_spec (e.g., '${COGNEE_VERSION}'),
    and resolves it against build_args.
    """
    if not Path(dockerfile_path).exists():
        return None

    rel_source = dockerfile_path
    pins = parse_dockerfile_installs(dockerfile_path, build_args=build_args, source=rel_source)

    for pin in pins:
        if pin.name.lower() != ann.dep_name.lower():
            continue
        if pin.resolved_version is not None:
            return pin.resolved_version
        m = _ARG_SUBST_RE.search(pin.raw_spec)
        if m:
            arg_name = m.group(1) or m.group(2)
            return build_args.get(arg_name)
    return None


def _annotation_latest(ann: ArtifactAnnotation, *, timeout_s: float) -> tuple[Artifact, State]:
    """Look up the latest version for an annotation from its datasource registry."""
    ds = ann.datasource.lower()
    lookup_map = {
        "pypi": pypi_latest,
        "npm": npm_latest,
        "go": go_proxy_latest,
        "cargo": crates_io_latest,
        "rubygems": rubygems_org_latest,
    }
    lookup_fn = lookup_map.get(ds)
    if lookup_fn is None:
        return Artifact(value=None, note="unsupported"), State.not_applicable
    return lookup_fn(ann.dep_name, timeout_s=timeout_s)


def _parse_dockerfile_image_lines(
    text: str, build_args: dict[str, str] | None = None
) -> list[DockerImage]:
    """Parse a Dockerfile and extract FROM image references.

    build_args overlays ARG defaults for variable substitution in FROM lines.
    """
    images: dict[str, DockerImage] = {}
    resolved = dict(build_args or {})

    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        upper = stripped.upper()
        # Collect ARG defaults for later FROM resolution
        if upper.startswith("ARG "):
            arg_part = stripped[4:].strip()
            if "=" in arg_part:
                k, _, v = arg_part.partition("=")
                key_name = k.strip()
                if key_name not in resolved:
                    resolved[key_name] = v.strip()
        if upper.startswith("FROM "):
            parts = stripped.split(None, 1)
            if len(parts) >= 2:
                image_str = re.split(r"\s+[Aa][Ss]\s+", parts[1], maxsplit=1)[0].strip()
                if resolved:
                    image_str = _resolve_arg_refs(image_str, resolved)
                # Docker image references never contain whitespace; skip heredoc content
                if " " in image_str or "\t" in image_str:
                    continue
                parsed = _parse_image_string(image_str)
                if parsed:
                    parsed = replace(parsed, source="Dockerfile")
                    key = f"{parsed.registry}/{parsed.repository}"
                    if parsed.tag:
                        key = f"{key}:{parsed.tag}"
                    if key not in images:
                        images[key] = parsed

    return [images[k] for k in sorted(images.keys(), key=lambda x: x.lower())]


def _dockerfile_build_reference(text: str) -> DockerImage | None:
    """Extract the last version-like FROM reference from a Dockerfile."""
    candidate: DockerImage | None = None
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if not stripped.upper().startswith("FROM "):
            continue
        parts = stripped.split(None, 1)
        if len(parts) < 2:
            continue
        image_str = re.split(r"\s+[Aa][Ss]\s+", parts[1], maxsplit=1)[0].strip()
        # Docker image references never contain whitespace; skip heredoc content
        if " " in image_str or "\t" in image_str:
            continue
        parsed = _parse_image_string(image_str)
        if parsed is None:
            continue
        if (
            parsed.tag and (parse_docker_tag(parsed.tag) is not None or parsed.tag in BRANCH_TAGS)
        ) or (parsed.digest and parsed.tag is None):
            candidate = parsed
    return candidate


def _docker_reference(image: DockerImage) -> str:
    reference = image.repository
    if image.registry not in {"docker.io", "index.docker.io"}:
        reference = f"{image.registry}/{reference}"
    if image.tag:
        reference = f"{reference}:{image.tag}"
    elif image.digest:
        reference = f"{reference}@{image.digest}"
    return reference


def _docker_inspect(image: DockerImage, timeout_s: float) -> dict[str, object] | None:
    result = run_argv(["docker", "inspect", _docker_reference(image)], timeout_s=timeout_s)
    if not result.ok or not result.stdout.strip():
        return None
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, list) or not payload:
        return None
    first = payload[0]
    if not isinstance(first, dict):
        return None
    return first


_OCI_VERSION_LABELS = ("org.opencontainers.image.version", "org.label-schema.version")


def _version_from_labels(labels: dict[str, object]) -> str | None:
    for key in _OCI_VERSION_LABELS:
        value = labels.get(key)
        if not isinstance(value, str):
            continue
        candidate = value.strip()
        if candidate and (parse_docker_tag(candidate) is not None or candidate in BRANCH_TAGS):
            return candidate
    return None


def _best_version_from_env(env: list[object]) -> str | None:
    best_candidate: str | None = None
    best_score: tuple[int, int, int] = (-1, -1, -1)
    for entry in env:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        key, raw_value = entry.split("=", 1)
        if not key.endswith("VERSION"):
            continue
        candidate = raw_value.strip()
        if not candidate:
            continue
        parsed = parse_docker_tag(candidate)
        if parsed is None and candidate not in BRANCH_TAGS:
            continue
        score = (
            len(parsed.parts) if parsed is not None else 0,
            len(parsed.suffix) if parsed is not None else 0,
            len(candidate),
        )
        if score > best_score:
            best_score = score
            best_candidate = candidate
    return best_candidate


def _local_image_version(image: DockerImage, timeout_s: float) -> str | None:
    metadata = _docker_inspect(image, timeout_s)
    if metadata is None:
        return None
    config = metadata.get("Config")
    if not isinstance(config, dict):
        return None
    labels = config.get("Labels")
    if isinstance(labels, dict):
        result = _version_from_labels(labels)
        if result is not None:
            return result
    env = config.get("Env")
    return _best_version_from_env(env) if isinstance(env, list) else None


def _docker_build_context_path(root: str, image: DockerImage) -> str:
    if not image.build_context_path or image.build_context_path in {".", "./"}:
        return root
    return str((Path(root) / image.build_context_path).resolve())


def _docker_build_dockerfile_path(root: str, image: DockerImage) -> str:
    context_path = _docker_build_context_path(root, image)
    dockerfile = image.build_dockerfile or "Dockerfile"
    return str(Path(context_path) / dockerfile)


DOCKER_TAG_PAGE_LIMIT = 5
DOCKER_TAG_PAGE_SIZE = 100


def _short_registry_note(artifact: Artifact, state: State) -> Artifact:
    if state == State.auth_required:
        return Artifact(value=artifact.value, url=artifact.url, note="auth")
    if state == State.rate_limited:
        return Artifact(value=artifact.value, url=artifact.url, note="rate")
    if state == State.not_found:
        return Artifact(value=artifact.value, url=artifact.url, note="not found")
    if state == State.error:
        note = artifact.note or "error"
        if note in {"http error"} or note.startswith("json parse:"):
            note = "error"
        if "timed out" in note.lower() or "timeout" in note.lower():
            note = "timeout"
        return Artifact(value=artifact.value, url=artifact.url, note=note)
    return artifact


def _parse_www_authenticate(value: str | None) -> tuple[str, dict[str, str]] | None:
    if not value:
        return None
    scheme, _, rest = value.partition(" ")
    if scheme.lower() != "bearer" or not rest:
        return None
    params: dict[str, str] = {}
    for part in re.split(r',(?=(?:[^"]*"[^"]*")*[^"]*$)', rest):
        key, sep, raw_value = part.strip().partition("=")
        if not sep:
            continue
        params[key] = raw_value.strip().strip('"')
    realm = params.pop("realm", None)
    if not realm:
        return None
    return realm, params


def _registry_auth_header(res_headers: Mapping[str, str | list[str]] | None) -> str | None:
    for key, value in (res_headers or {}).items():
        if key.lower() == "www-authenticate":
            if isinstance(value, list):
                return value[0] if value else None
            return value
    return None


def _bearer_token_url(realm: str, params: dict[str, str]) -> str:
    parsed = urlparse(realm)
    existing = dict(parse_qsl(parsed.query))
    existing.update({k: v for k, v in params.items() if v})
    query = urlencode(existing)
    return parsed._replace(query=query).geturl()


_V2Result = tuple[object | None, Artifact, State, Mapping[str, str | list[str]]]


def _v2_ok(data: object, url: str, headers: Mapping[str, str | list[str]]) -> _V2Result:
    digest = _header_value(headers, "docker-content-digest")
    return data, Artifact(value=digest, url=url), State.ok, headers


def _v2_auth_err(url: str, headers: Mapping[str, str | list[str]]) -> _V2Result:
    return None, Artifact(value=None, url=url, note="auth"), State.auth_required, headers


def _try_bearer_auth(
    url: str,
    *,
    repository: str,
    timeout_s: float,
    headers: dict[str, str],
    res_headers: Mapping[str, str | list[str]],
    cache_key: str,
) -> _V2Result | None:
    """Attempt bearer token auth from WWW-Authenticate. Returns result or None to fall through."""
    challenge = _parse_www_authenticate(_registry_auth_header(res_headers))
    if challenge is None:
        return None
    realm, params = challenge
    params.setdefault("scope", f"repository:{repository}:pull")
    token_url = _bearer_token_url(realm, params)
    token_res, token_data = get_json(
        token_url, timeout_s=timeout_s, headers={"Accept": "application/json"}
    )
    if not token_res.ok or not isinstance(token_data, dict):
        return _v2_auth_err(token_url, token_res.headers or {})
    token = token_data.get("token") or token_data.get("access_token")
    if not isinstance(token, str) or not token:
        return _v2_auth_err(token_url, token_res.headers or {})
    _bearer_token_cache[cache_key] = token
    retry_res, retry_data = get_json(
        url, timeout_s=timeout_s, headers={**headers, "Authorization": f"Bearer {token}"}
    )
    if retry_res.ok:
        return _v2_ok(retry_data, url, retry_res.headers or {})
    return None  # fall through to standard error handling with updated res


def _get_registry_v2_json(
    url: str, *, repository: str, timeout_s: float, headers: dict[str, str]
) -> _V2Result:
    parsed_host = urlparse(url).netloc
    cache_key = f"{parsed_host}/{repository}"
    cached_token = _bearer_token_cache.get(cache_key)
    if cached_token:
        headers = {**headers, "Authorization": f"Bearer {cached_token}"}
    res, data = get_json(url, timeout_s=timeout_s, headers=headers)
    if res.ok:
        return _v2_ok(data, url, res.headers or {})
    if res.status == 401:
        result = _try_bearer_auth(
            url,
            repository=repository,
            timeout_s=timeout_s,
            headers=headers,
            res_headers=res.headers or {},
            cache_key=cache_key,
        )
        if result is not None:
            return result
    rh = res.headers or {}
    if res.status == 404:
        return None, Artifact(value=None, url=url, note="not found"), State.not_found, rh
    if res.status in (401, 403):
        return _v2_auth_err(url, rh)
    if res.status == 429:
        return None, Artifact(value=None, url=url, note="rate"), State.rate_limited, rh
    note = res.error or "error"
    if "timed out" in note.lower() or "timeout" in note.lower():
        note = "timeout"
    elif note.startswith("json parse:"):
        note = "error"
    return None, Artifact(value=None, url=url, note=note), State.error, res.headers or {}


def _header_value(headers: Mapping[str, str | list[str]] | None, name: str) -> str | None:
    for key, value in (headers or {}).items():
        if key.lower() == name.lower():
            if isinstance(value, list):
                return value[0] if value else None
            return value
    return None


def _registry_next_url(link_header: str | None, current_url: str) -> str | None:
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' not in part and "rel=next" not in part:
            continue
        start = part.find("<")
        end = part.find(">", start + 1)
        if start == -1 or end == -1:
            continue
        next_url = part[start + 1 : end].strip()
        if not next_url:
            continue
        return (
            next_url
            if next_url.startswith(("http://", "https://"))
            else urljoin(current_url, next_url)
        )
    return None


def _http_error_note_state(res: object) -> tuple[str | None, State]:
    """Map an HTTP response to (note, State) for registry error returns."""
    status = getattr(res, "status", 0)
    if status == 404:
        return "not found", State.not_found
    if status in (401, 403):
        return "auth", State.auth_required
    if status == 429:
        return "rate", State.rate_limited
    note = getattr(res, "error", None) or "error"
    if isinstance(note, str) and (
        note.startswith("json parse:") or "timed out" in note.lower() or "timeout" in note.lower()
    ):
        note = "timeout" if ("timed out" in note.lower() or "timeout" in note.lower()) else "error"
    return note, State.error


def _docker_hub_tags(
    *, repository: str, timeout_s: float
) -> tuple[list[str], dict[str, str], Artifact, State]:
    """Fetch Docker Hub tags for a repository.

    Docker Hub API v2: https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags
    Returns (tags, digest_map, artifact, state) where digest_map is {tag_name: index_digest}.
    """
    if "/" in repository:
        namespace, repo = repository.split("/", 1)
    else:
        namespace = "library"
        repo = repository

    url: str | None = (
        f"https://hub.docker.com/v2/repositories/{namespace}/{repo}/tags"
        f"?page_size={DOCKER_TAG_PAGE_SIZE}&ordering=last_updated"
    )

    headers = {"Accept": "application/json"}
    tags: list[str] = []
    digest_map: dict[str, str] = {}
    pages = 0

    while url and pages < DOCKER_TAG_PAGE_LIMIT:
        pages += 1
        cur_url: str = url
        res, data = get_json(cur_url, timeout_s=timeout_s, headers=headers)
        if not res.ok or not isinstance(data, dict):
            note, state = _http_error_note_state(res)
            return tags, digest_map, Artifact(value=None, url=cur_url, note=note), state

        results = data.get("results")
        if isinstance(results, list):
            for latest_tag in results:
                if not isinstance(latest_tag, dict):
                    continue
                tag_name = latest_tag.get("name")
                if isinstance(tag_name, str):
                    tags.append(tag_name)
                    tag_digest = latest_tag.get("digest")
                    if isinstance(tag_digest, str) and tag_digest:
                        digest_map[tag_name] = tag_digest
        next_url = data.get("next")
        url = next_url if isinstance(next_url, str) else None

    repo_url = f"https://hub.docker.com/r/{namespace}/{repo}/tags"
    if not tags:
        return tags, digest_map, Artifact(value=None, url=repo_url, note="error"), State.error
    note = "tag limit reached" if url else None
    return tags, digest_map, Artifact(value=None, url=repo_url, note=note), State.ok


def _registry_v2_tags(
    *, registry: str, repository: str, timeout_s: float
) -> tuple[list[str], Artifact, State]:
    """Fetch tags from a generic Registry v2 API.

    Registry API v2: https://docs.docker.com/registry/spec/api/#listing-tags
    """
    if registry == "docker.io":
        registry = "index.docker.io"

    url = f"https://{registry}/v2/{repository}/tags/list?n=10000"

    headers = {"Accept": "application/json"}

    data, artifact, state, response_headers = _get_registry_v2_json(
        url, repository=repository, timeout_s=timeout_s, headers=headers
    )
    if state == State.ok and not isinstance(data, dict):
        return [], Artifact(value=None, url=url, note="error"), State.error
    if state == State.ok and isinstance(data, dict):
        tags = data.get("tags")
        if isinstance(tags, list) and tags:
            collected = [tag for tag in tags if isinstance(tag, str)]
        else:
            collected = []
        max_pages = 5
        pages = 1
        next_url = _registry_next_url(_header_value(response_headers, "link"), url)
        while next_url and pages < max_pages:
            pages += 1
            data, page_artifact, state, response_headers = _get_registry_v2_json(
                next_url, repository=repository, timeout_s=timeout_s, headers=headers
            )
            if state != State.ok or not isinstance(data, dict):
                return collected, _short_registry_note(page_artifact, state), state
            page_tags = data.get("tags")
            if isinstance(page_tags, list):
                collected.extend(tag for tag in page_tags if isinstance(tag, str))
            next_url = _registry_next_url(_header_value(response_headers, "link"), next_url)
        if collected:
            note = "tag limit reached" if next_url else None
            return (
                collected,
                Artifact(
                    value=None, url=f"https://{registry}/v2/{repository}/tags/list", note=note
                ),
                State.ok,
            )
        return [], Artifact(value=None, url=url, note="error"), State.error
    return [], artifact, state


def _v2_registry_host(registry: str) -> str:
    if registry in {"docker.io", "index.docker.io"}:
        return "registry-1.docker.io"
    return registry


def _v2_repository(registry: str, repository: str) -> str:
    if registry in {"docker.io", "index.docker.io"} and "/" not in repository:
        return f"library/{repository}"
    return repository


def _registry_v2_manifest(
    *, registry: str, repository: str, tag: str, timeout_s: float
) -> tuple[dict[str, object] | None, Artifact, State]:
    host = _v2_registry_host(registry)
    repo = _v2_repository(registry, repository)
    url = f"https://{host}/v2/{repo}/manifests/{tag}"
    headers = {
        "Accept": (
            "application/vnd.docker.distribution.manifest.v2+json,"
            "application/vnd.oci.image.manifest.v1+json,"
            "application/vnd.docker.distribution.manifest.list.v2+json,"
            "application/vnd.oci.image.index.v1+json"
        )
    }
    data, artifact, state, _ = _get_registry_v2_json(
        url, repository=repo, timeout_s=timeout_s, headers=headers
    )
    if state != State.ok:
        return None, _short_registry_note(artifact, state), state
    if not isinstance(data, dict):
        return None, Artifact(value=None, url=url, note="error"), State.error
    return data, artifact, State.ok


def _registry_v2_manifest_digest(
    *, registry: str, repository: str, tag: str, timeout_s: float
) -> tuple[Artifact, State]:
    data, artifact, state = _registry_v2_manifest(
        registry=registry, repository=repository, tag=tag, timeout_s=timeout_s
    )
    if state != State.ok or data is None:
        return artifact, state
    host = _v2_registry_host(registry)
    repo = _v2_repository(registry, repository)
    url = f"https://{host}/v2/{repo}/manifests/{tag}"
    digest = artifact.value or data.get("digest")
    if isinstance(digest, str) and digest:
        return Artifact(value=digest, url=url), State.ok
    return Artifact(value=None, url=url, note="error"), State.error


def _fetch_latest_docker_image(*, image: DockerImage, timeout_s: float) -> tuple[Artifact, State]:
    """Fetch the best comparable Docker tag for an image."""
    if image.build_context:
        return Artifact(value=None, note="local"), State.local_only
    if image.digest is not None and image.tag is None:
        return Artifact(value=f"@{image.digest[:12]}", note="digest"), State.ok
    if image.digest is not None and image.tag is not None:
        return _registry_v2_manifest_digest(
            registry=image.registry,
            repository=image.repository,
            tag=image.tag,
            timeout_s=timeout_s,
        )
    if image.registry in {"docker.io", "index.docker.io"}:
        tags, _, artifact, state = _docker_hub_tags(
            repository=image.repository, timeout_s=timeout_s
        )
    else:
        tags, artifact, state = _registry_v2_tags(
            registry=image.registry,
            repository=image.repository,
            timeout_s=timeout_s,
        )
    if state != State.ok:
        return _short_registry_note(artifact, state), state
    latest = best_docker_update(image.tag, tags)
    if latest is None:
        note = artifact.note or "error"
        return Artifact(value=None, url=artifact.url, note=note), State.error
    return Artifact(value=latest, url=artifact.url, note=artifact.note), State.ok


def _docker_current_value(image: DockerImage, latest: Artifact, latest_state: State) -> str:
    if image.digest:
        return f"@{image.digest[:12]}"
    if image.tag and image.tag in BRANCH_TAGS:
        return image.tag
    if latest_state == State.local_only and parse_docker_tag(image.tag) is None:
        return ""
    if (
        image.tag
        and parse_docker_tag(image.tag) is None
        and latest_state == State.ok
        and parse_docker_tag(latest.value) is not None
    ):
        return latest.value or ""
    if image.tag:
        return image.tag
    return ""


def docker_hub_latest(*, repository: str, timeout_s: float) -> tuple[Artifact, State]:
    tags, _, artifact, state = _docker_hub_tags(repository=repository, timeout_s=timeout_s)
    if state != State.ok:
        return artifact, state
    latest = best_docker_update("0", tags)
    if latest is None:
        parsed = [tag for tag in tags if parse_docker_tag(tag) is not None]
        latest = parsed[0] if parsed else None
    if latest is None:
        return Artifact(value=None, url=artifact.url, note=artifact.note or "error"), State.error
    return Artifact(value=latest, url=artifact.url, note=artifact.note), State.ok


def registry_v2_latest(
    *, registry: str, repository: str, current_tag: str | None, timeout_s: float
) -> tuple[Artifact, State]:
    tags, artifact, state = _registry_v2_tags(
        registry=registry,
        repository=repository,
        timeout_s=timeout_s,
    )
    if state != State.ok:
        return artifact, state
    latest = best_docker_update(current_tag or "0", tags)
    if latest is None:
        return Artifact(value=None, url=artifact.url, note=artifact.note or "error"), State.error
    return Artifact(value=latest, url=artifact.url, note=artifact.note), State.ok


CHANNEL_RESOLVE_TAG_LIMIT = 5  # max version tags to check digests for on OCI registries


def _match_digest_in_tags(
    tags: list[str], digest_map: dict[str, str], channel_digest: str
) -> str | None:
    """Return the first version tag whose digest matches channel_digest, or a short digest."""
    version_tags = sorted(
        (t for t in tags if parse_docker_tag(t) is not None),
        key=lambda t: parse_docker_tag(t).parts,  # type: ignore[union-attr]
        reverse=True,
    )
    for vtag in version_tags:
        if digest_map.get(vtag) == channel_digest:
            return vtag
    return channel_digest[:19]


def _resolve_channel_tag_hub(repository: str, channel_tag: str, timeout_s: float) -> str | None:
    tags, digest_map, _, state = _docker_hub_tags(repository=repository, timeout_s=timeout_s)
    if state != State.ok:
        return None
    channel_digest = digest_map.get(channel_tag)
    if not channel_digest:
        return None
    return _match_digest_in_tags(tags, digest_map, channel_digest)


def _resolve_channel_tag_oci(
    registry: str, repository: str, channel_tag: str, timeout_s: float
) -> str | None:
    channel_artifact, channel_state = _registry_v2_manifest_digest(
        registry=registry, repository=repository, tag=channel_tag, timeout_s=timeout_s
    )
    if channel_state != State.ok or not channel_artifact.value:
        return None
    channel_digest = channel_artifact.value
    tags, _, tags_state = _registry_v2_tags(
        registry=registry, repository=repository, timeout_s=timeout_s
    )
    if tags_state != State.ok:
        return channel_digest[:19]
    top_tags = sorted(
        (t for t in tags if parse_docker_tag(t) is not None),
        key=lambda t: parse_docker_tag(t).parts,  # type: ignore[union-attr]
        reverse=True,
    )[:CHANNEL_RESOLVE_TAG_LIMIT]
    for vtag in top_tags:
        v_artifact, v_state = _registry_v2_manifest_digest(
            registry=registry, repository=repository, tag=vtag, timeout_s=timeout_s
        )
        if v_state == State.ok and v_artifact.value == channel_digest:
            return vtag
    return channel_digest[:19]


def _resolve_channel_tag(
    *, registry: str, repository: str, channel_tag: str, timeout_s: float
) -> str | None:
    """Resolve a channel tag (latest/main/stable) to a version tag via digest mapping."""
    if registry in ("docker.io", "index.docker.io"):
        return _resolve_channel_tag_hub(repository, channel_tag, timeout_s)
    return _resolve_channel_tag_oci(registry, repository, channel_tag, timeout_s)


_COMPOSE_NAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")


def _scan_docker_compose(
    root: str, root_path: Path
) -> tuple[list[DockerImage], set[str], dict[str, ArtifactAnnotation]]:
    """Parse all compose files and their build Dockerfiles.

    Returns (images, seen_dfs, annotations).
    """
    images: list[DockerImage] = []
    seen_dockerfile_bases: set[str] = set()
    annotation_by_service: dict[str, ArtifactAnnotation] = {}

    for compose_name in _COMPOSE_NAMES:
        compose_path = root_path / compose_name
        if not compose_path.exists():
            continue
        text = compose_path.read_text(encoding="utf-8", errors="replace")
        parsed = _parse_docker_compose_yaml(text)
        images.extend(parsed)
        for img in parsed:
            if not img.build_context:
                continue
            df_path = _docker_build_dockerfile_path(root, img)
            if df_path in seen_dockerfile_bases:
                continue
            seen_dockerfile_bases.add(df_path)
            df = Path(df_path)
            if not df.exists():
                continue
            compose_args = img.build_compose_args or {}
            df_text = df.read_text(encoding="utf-8", errors="replace")
            for base in _parse_dockerfile_image_lines(df_text, build_args=compose_args):
                key = f"{base.registry}/{base.repository}" + (f":{base.tag}" if base.tag else "")
                if not any(
                    f"{i.registry}/{i.repository}" + (f":{i.tag}" if i.tag else "") == key
                    for i in images
                ):
                    images.append(replace(base, source=df_path.replace(root + os.sep, "")))
            rel_path = df_path.replace(root + os.sep, "")
            for ann in parse_dockerfile_annotations(df_path, source=rel_path):
                key_ann = ann.artifact_name or img.service_name
                if key_ann:
                    annotation_by_service[key_ann] = ann

    return images, seen_dockerfile_bases, annotation_by_service


def _build_row_annotated(
    image: DockerImage, ann: ArtifactAnnotation, root: str, timeout_s: float
) -> DepRow:
    df_path = _docker_build_dockerfile_path(root, image)
    current_val = _annotation_current(ann, df_path, image.build_compose_args or {})
    latest, _ = _annotation_latest(ann, timeout_s=timeout_s)
    state = State.ok
    freshness = Freshness.not_checked
    if current_val is not None and latest.value is not None:
        if current_val != latest.value:
            state, freshness = State.update_available, Freshness.uncomparable
        else:
            freshness = Freshness.latest
    df_rel = df_path.replace(root + os.sep, "") if root else df_path
    return DepRow(
        ecosystem="docker",
        name=image.name,
        current=Artifact(value=current_val, note="local build"),
        latest=latest,
        state=state,
        source_class=SourceClass.container_runtime,
        freshness=freshness,
        source=f"docker/{image.service_name or image.name}/{df_rel}",
        note="local build",
    )


def _build_row_channel(image: DockerImage, resolved: str, timeout_s: float) -> DepRow:
    """Handle channel/branch tag whose resolution is a digest (sha256:...)."""
    upstream_digest = resolved
    local_meta = _docker_inspect(image, timeout_s)
    local_digest: str | None = None
    if isinstance(local_meta, dict):
        repo_digests = local_meta.get("RepoDigests")
        if isinstance(repo_digests, list):
            for rd in repo_digests:
                if isinstance(rd, str) and "@sha256:" in rd:
                    local_digest = "sha256:" + rd.split("@sha256:", 1)[1]
                    break
    channel = image.tag or "latest"
    is_stale = bool(local_digest and local_digest != upstream_digest)

    def _short(digest: str | None) -> str:
        if not digest:
            return channel
        return f"{channel} ({digest.removeprefix('sha256:')[:5]})"

    current_display = _short(local_digest) if image.tag in BRANCH_TAGS else channel
    latest_display = _short(upstream_digest) if image.tag in BRANCH_TAGS else channel
    display_name = image.name
    if image.registry not in ("docker.io", "index.docker.io"):
        display_name = f"{image.registry}/{image.repository}"
    return DepRow(
        ecosystem="docker",
        name=display_name,
        current=Artifact(value=current_display),
        latest=Artifact(value=latest_display),
        state=State.update_available if is_stale else State.ok,
        source_class=SourceClass.container_runtime,
        freshness=Freshness.minor_behind if is_stale else Freshness.latest,
        source=image.source,
    )


def _build_row_registry(
    image: DockerImage, lookup_image: DockerImage, build_current_value: str | None, timeout_s: float
) -> DepRow:
    latest, latest_state = _fetch_latest_docker_image(image=lookup_image, timeout_s=timeout_s)
    current_value = build_current_value or _docker_current_value(image, latest, latest_state)
    if image.build_context and not current_value and lookup_image is not image:
        current_value = _docker_current_value(lookup_image, latest, latest_state)
    state = State.local_only if image.build_context else State.ok
    freshness = Freshness.not_checked
    if latest.value is not None:
        freshness = docker_freshness(current_value or lookup_image.tag or image.tag, latest.value)
        outdated = not image.build_context and current_value and current_value != latest.value
        digest_stale = not image.build_context and image.digest and latest.value not in image.digest
        if outdated or digest_stale:
            state = State.update_available
    elif latest_state != State.ok and not image.build_context:
        state = latest_state
    display_name = image.name
    if image.registry and image.registry not in ("docker.io", "index.docker.io"):
        display_name = f"{image.registry}/{image.repository}"
    cur_url_img = lookup_image if image.build_context and lookup_image is not image else image
    hub_url = (
        f"https://hub.docker.com/_/{cur_url_img.repository}"
        if cur_url_img.registry == "docker.io"
        else None
    )
    return DepRow(
        ecosystem="docker",
        name=display_name,
        current=Artifact(value=current_value, url=hub_url),
        latest=latest,
        state=state,
        source_class=SourceClass.container_runtime,
        freshness=freshness,
        source=image.source,
    )


def scan_docker(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    """Scan for Docker container images in docker-compose.yml and Dockerfiles."""
    root_path = Path(root)
    images, seen_dockerfile_bases, annotation_by_service = _scan_docker_compose(root, root_path)

    dockerfile_path = root_path / "Dockerfile"
    if dockerfile_path.exists() and str(dockerfile_path) not in seen_dockerfile_bases:
        images.extend(
            _parse_dockerfile_image_lines(
                dockerfile_path.read_text(encoding="utf-8", errors="replace")
            )
        )

    def build_row(image: DockerImage) -> DepRow:
        if image.build_context and not image.registry:
            ann = annotation_by_service.get(image.name)
            if ann is not None:
                return _build_row_annotated(image, ann, root, timeout_s)
            return DepRow(
                ecosystem="docker",
                name=image.name,
                current=Artifact(value=None, note="local build"),
                latest=Artifact(value=None, note="local build"),
                state=State.local_only,
                source_class=SourceClass.container_runtime,
                freshness=Freshness.not_checked,
                source=image.source,
                note="local build",
            )

        lookup_image = image
        build_current_value: str | None = None
        if image.build_context:
            df_path = _docker_build_dockerfile_path(root, image)
            df = Path(df_path)
            if df.exists():
                ref = _dockerfile_build_reference(df.read_text(encoding="utf-8", errors="replace"))
                if ref is not None:
                    lookup_image = ref
                    build_current_value = _docker_current_value(ref, Artifact(value=None), State.ok)
            if build_current_value is None:
                build_current_value = _local_image_version(image, timeout_s)
        elif image.tag in BRANCH_TAGS or image.tag in CHANNEL_TAGS:
            resolved = _resolve_channel_tag(
                registry=image.registry,
                repository=image.repository,
                channel_tag=image.tag,
                timeout_s=timeout_s,
            )
            if resolved is not None and resolved.startswith("sha256:"):
                return _build_row_channel(image, resolved, timeout_s)
            if resolved is not None:
                build_current_value = resolved
                lookup_image = replace(image, tag=resolved)

        return _build_row_registry(image, lookup_image, build_current_value, timeout_s)

    rows = map_bounded_ordered(images, build_row, max_workers=lookup_concurrency)
    return Section(title="Docker", rows=rows)


# Section titles by ecosystem — must match SCANNERS in scanners.py
_ECOSYSTEM_TITLE = {
    "pypi": "Python (PyPI)",
    "npm": "Node (npm)",
    "go": "Go",
    "cargo": "Rust (Cargo)",
    "ruby": "Ruby (Bundler)",
}


def _pin_to_dep_row(pin: InstallPin, *, timeout_s: float) -> DepRow:
    """Convert an InstallPin into a DepRow by looking up the registry."""
    lookup_map = {
        "pypi": pypi_latest,
        "npm": npm_latest,
        "go": go_proxy_latest,
        "cargo": crates_io_latest,
        "ruby": rubygems_org_latest,
    }
    lookup_fn = lookup_map.get(pin.ecosystem)

    if lookup_fn is None:
        return DepRow(
            ecosystem=pin.ecosystem,
            name=pin.name,
            current=Artifact(value=pin.resolved_version or pin.raw_spec),
            latest=Artifact(value=None, note="unsupported ecosystem"),
            state=State.not_applicable,
            source=pin.source,
            source_class=SourceClass.declared_manifest,
            freshness=Freshness.not_checked,
        )

    latest, latest_state = lookup_fn(pin.name, timeout_s=timeout_s)

    if pin.resolved_version is not None:
        # Exact pin: enable freshness comparison
        current_val = pin.resolved_version
        state = State.ok
        if latest.value is not None and latest.value != current_val:
            state = State.update_available
        elif latest_state != State.ok:
            state = latest_state
        return DepRow(
            ecosystem=pin.ecosystem,
            name=pin.name,
            current=Artifact(value=current_val),
            latest=latest,
            state=state,
            source=pin.source,
            source_class=SourceClass.declared_manifest,
        )
    else:
        # Range or unpinned: show spec as-is, disable freshness math
        display = pin.raw_spec if pin.raw_spec != "unpinned" else None
        state = State.pinned if latest_state == State.ok else latest_state
        return DepRow(
            ecosystem=pin.ecosystem,
            name=pin.name,
            current=Artifact(value=display, note="range" if display else "unpinned"),
            latest=latest,
            state=state,
            source=pin.source,
            source_class=SourceClass.declared_manifest,
            freshness=Freshness.not_checked,
        )


def _collect_build_dockerfiles(root: str) -> list[tuple[str, dict[str, str]]]:
    """Return (dockerfile_path, compose_build_args) for all build services in compose files."""
    results: list[tuple[str, dict[str, str]]] = []
    seen: set[str] = set()
    root_path = Path(root)

    for compose_name in (
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    ):
        compose_path = root_path / compose_name
        if not compose_path.exists():
            continue
        images = _parse_docker_compose_yaml(
            compose_path.read_text(encoding="utf-8", errors="replace")
        )
        for img in images:
            if not img.build_context:
                continue
            df_path = _docker_build_dockerfile_path(root, img)
            if df_path in seen:
                continue
            seen.add(df_path)
            if Path(df_path).exists():
                results.append((df_path, img.build_compose_args or {}))

    # Also handle bare Dockerfile at root if present
    bare = root_path / "Dockerfile"
    if bare.exists() and str(bare) not in seen:
        results.append((str(bare), {}))

    return results


def scan_docker_install_sections(
    root: str, *, timeout_s: float, lookup_concurrency: int = 1
) -> list[Section]:
    """Scan Dockerfiles for package installs and return native ecosystem sections.

    Each install command (pip, npm, go, cargo, gem) in a RUN layer is parsed.
    Exact pins get freshness comparison; ranges and unpinned installs are listed
    with freshness=not_checked so they count as deps but not updates.
    """
    build_dfs = _collect_build_dockerfiles(root)
    if not build_dfs:
        return []

    all_pins: list[InstallPin] = []
    for df_path, compose_args in build_dfs:
        rel = os.path.relpath(df_path, root)
        pins = parse_dockerfile_installs(df_path, build_args=compose_args, source=rel)
        all_pins.extend(pins)

    if not all_pins:
        return []

    # Deduplicate: if same name+ecosystem appears multiple times, keep first
    seen_pins: set[tuple[str, str]] = set()
    unique_pins: list[InstallPin] = []
    for pin in all_pins:
        key = (pin.name.lower(), pin.ecosystem)
        if key not in seen_pins:
            seen_pins.add(key)
            unique_pins.append(pin)

    def build_pin_row(pin: InstallPin) -> tuple[str, DepRow]:
        return pin.ecosystem, _pin_to_dep_row(pin, timeout_s=timeout_s)

    rows_by_title: dict[str, list[DepRow]] = {}
    pin_rows = map_bounded_ordered(unique_pins, build_pin_row, max_workers=lookup_concurrency)
    for ecosystem, row in pin_rows:
        title = _ECOSYSTEM_TITLE.get(ecosystem, ecosystem)
        rows_by_title.setdefault(title, []).append(row)

    return [Section(title=title, rows=rows) for title, rows in rows_by_title.items()]
