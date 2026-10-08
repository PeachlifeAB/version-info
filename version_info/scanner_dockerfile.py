"""Parse Dockerfile RUN commands to extract package install pins.

Supports pip, npm (global), go install, cargo install, gem install.
ARG defaults are resolved before extraction. Compose build.args values
can be passed in as build_args to override ARG defaults.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from typing import Any

try:
    import dockerfile as _dockerfile_lib
except ImportError:
    _dockerfile_lib = None

from .model import ArtifactAnnotation, InstallPin

# Matches ${VAR}, ${VAR:-default}, ${VAR:=default}
_ARG_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::?[-=][^}]*)?\}|\$([A-Za-z_][A-Za-z0-9_]*)")

# version-info: datasource=pypi depName=cognee artifact=cognee-api
_VERSION_INFO_RE = re.compile(
    r"#\s*version-info:\s*"
    r"(?:datasource=([^\s]+))?\s*"
    r"(?:depName=([^\s]+))?\s*"
    r"(?:artifact=([^\s]+))?\s*",
    re.IGNORECASE,
)

# renovate: datasource=pypi depName=cognee
_RENOVATE_RE = re.compile(
    r"#\s*renovate:\s*"
    r"(?:datasource=([^\s]+))?\s*"
    r"(?:depName=([^\s]+))?\s*",
    re.IGNORECASE,
)

# Exact pip version pin: name==1.2.3 (possibly with extras like pkg[extra]==1.2.3)
_PIP_EXACT_RE = re.compile(r"^([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?)==([^\s,]+)$")
# Pip range/constraint (>=, <=, !=, ~=, <, >)
_PIP_RANGE_RE = re.compile(r"^([A-Za-z0-9_.\-]+(?:\[[^\]]+\])?)([><!~=][^,\s].*)$")

# npm exact: pkg@1.2.3 or pkg@v1.2.3
_NPM_EXACT_RE = re.compile(r"^(@?[A-Za-z0-9_.\-/]+)@(v?\d[^\s]*)$")
# npm channel: pkg@latest, pkg@next, etc.
_NPM_CHANNEL_RE = re.compile(r"^(@?[A-Za-z0-9_.\-/]+)@([a-z][a-z0-9_.-]*)$")

# go install: module@v1.2.3 or module@latest
_GO_INSTALL_RE = re.compile(r"^([^\s@]+)@([^\s]+)$")

# cargo install --version / -V
_CARGO_VERSION_RE = re.compile(r"(?:--version|-V)\s+([^\s]+)")

# gem install -v / --version
_GEM_VERSION_RE = re.compile(r"(?:-v|--version)\s+([^\s]+)")


def _collect_args(cmds: list[Any]) -> dict[str, str]:
    """Collect ARG default values from parsed Dockerfile commands."""
    args: dict[str, str] = {}
    for cmd in cmds:
        if cmd.cmd.upper() != "ARG":
            continue
        raw = " ".join(cmd.value)
        if "=" in raw:
            key, _, val = raw.partition("=")
            args[key.strip()] = val.strip()
    return args


def parse_dockerfile_annotations(
    path: str,
    source: str | None = None,
) -> list[ArtifactAnnotation]:
    """Parse a Dockerfile and extract version-info:/renovate: annotations.

    Reads the file directly to find comment lines, since the dockerfile
    library does not parse COMMENT commands.

    Args:
        path: Absolute path to the Dockerfile.
        source: Display path for the SOURCE column (defaults to the path).

    Returns list of ArtifactAnnotation, one per annotation found.
    """
    if source is None:
        source = path

    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines(keepends=True)
    except Exception:
        return []

    annotations: list[ArtifactAnnotation] = []
    for line in lines:
        stripped = line.strip()
        if not stripped.startswith("#"):
            continue

        m = _VERSION_INFO_RE.search(stripped)
        if m:
            annotations.append(
                ArtifactAnnotation(
                    datasource=m.group(1) or "",
                    dep_name=m.group(2) or "",
                    artifact_name=m.group(3),
                    annotation_source="version-info",
                    source_path=source,
                )
            )
            continue

        m = _RENOVATE_RE.search(stripped)
        if m:
            annotations.append(
                ArtifactAnnotation(
                    datasource=m.group(1) or "",
                    dep_name=m.group(2) or "",
                    artifact_name=None,
                    annotation_source="renovate",
                    source_path=source,
                )
            )
    return annotations


def _resolve_vars(text: str, build_args: dict[str, str]) -> str:
    """Substitute $VAR and ${VAR} references with values from build_args."""

    def replace(m: re.Match[str]) -> str:
        name = m.group(1) or m.group(2)
        return build_args.get(name, m.group(0))

    return _ARG_RE.sub(replace, text)


def _strip_pkg_extras(name: str) -> str:
    """Remove extras brackets from pip package name for canonical form."""
    bracket = name.find("[")
    if bracket != -1:
        return name[:bracket]
    return name


def _parse_pip_token(token: str, source: str, resolved: dict[str, str]) -> InstallPin | None:
    """Parse a single pip install token into an InstallPin."""
    token = token.strip().strip('"').strip("'")
    if not token:
        return None
    # Skip git/url installs
    if token.startswith(("git+", "http://", "https://", "-")):
        return None
    # Resolve any remaining $ARG references
    token = _resolve_vars(token, resolved)

    exact = _PIP_EXACT_RE.match(token)
    if exact:
        raw_name = exact.group(1)
        version = exact.group(2)
        return InstallPin(
            name=_strip_pkg_extras(raw_name),
            raw_spec=f"=={version}",
            resolved_version=version,
            ecosystem="pypi",
            source=source,
        )

    ranged = _PIP_RANGE_RE.match(token)
    if ranged:
        raw_name = ranged.group(1)
        spec = ranged.group(2)
        return InstallPin(
            name=_strip_pkg_extras(raw_name),
            raw_spec=spec,
            resolved_version=None,
            ecosystem="pypi",
            source=source,
        )

    # Bare name (unpinned), but must look like a package name
    if re.match(r"^[A-Za-z0-9_.\-]+(?:\[[^\]]+\])?$", token):
        return InstallPin(
            name=_strip_pkg_extras(token),
            raw_spec="unpinned",
            resolved_version=None,
            ecosystem="pypi",
            source=source,
        )
    return None


def _extract_pip_installs(
    run_value: str, source: str, resolved: dict[str, str]
) -> list[InstallPin]:
    """Extract pip install packages from a RUN command value."""
    pins: list[InstallPin] = []
    try:
        tokens = shlex.split(run_value)
    except ValueError:
        # Fallback: simple whitespace split
        tokens = run_value.split()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in ("pip", "pip3") and i + 1 < len(tokens) and tokens[i + 1] == "install":
            i += 2
            while i < len(tokens):
                pkg_tok = tokens[i]
                if pkg_tok.startswith("-"):
                    # Skip flags with values
                    if pkg_tok in (
                        "-r",
                        "--requirement",
                        "-c",
                        "--constraint",
                        "-t",
                        "--target",
                        "--index-url",
                        "-i",
                        "--extra-index-url",
                        "--trusted-host",
                    ):
                        i += 2
                    else:
                        i += 1
                    continue
                if pkg_tok in ("&&", "||", ";", "|"):
                    break
                pin = _parse_pip_token(pkg_tok, source, resolved)
                if pin is not None:
                    pins.append(pin)
                i += 1
            break
        i += 1
    return pins


def _npm_pkg_to_pin(pkg: str, source: str) -> InstallPin | None:
    exact = _NPM_EXACT_RE.match(pkg)
    if exact:
        ver = exact.group(2)
        return InstallPin(
            name=exact.group(1),
            raw_spec=f"@{ver}",
            resolved_version=ver.lstrip("v") if re.match(r"v?\d", ver) else None,
            ecosystem="npm",
            source=source,
        )
    channel = _NPM_CHANNEL_RE.match(pkg)
    if channel:
        return InstallPin(
            name=channel.group(1),
            raw_spec=f"@{channel.group(2)}",
            resolved_version=None,
            ecosystem="npm",
            source=source,
        )
    if re.match(r"^@?[A-Za-z0-9_.\-/]+$", pkg):
        return InstallPin(
            name=pkg, raw_spec="unpinned", resolved_version=None, ecosystem="npm", source=source
        )
    return None


def _extract_npm_installs(
    run_value: str, source: str, resolved: dict[str, str]
) -> list[InstallPin]:
    """Extract npm install -g packages from a RUN command value."""
    pins: list[InstallPin] = []
    try:
        tokens = shlex.split(run_value)
    except ValueError:
        tokens = run_value.split()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if (
            tok in ("npm", "yarn", "pnpm")
            and i + 1 < len(tokens)
            and tokens[i + 1] in ("install", "add", "i")
        ):
            i += 2
            is_global = False
            pkgs: list[str] = []
            while i < len(tokens):
                t = tokens[i]
                if t in ("-g", "--global"):
                    is_global = True
                elif t.startswith("-") or t in ("&&", "||", ";", "|"):
                    if t in ("&&", "||", ";", "|"):
                        break
                else:
                    pkgs.append(t)
                i += 1
            if is_global:
                for raw_pkg in pkgs:
                    pkg = _resolve_vars(raw_pkg.strip().strip('"').strip("'"), resolved)
                    pin = _npm_pkg_to_pin(pkg, source) if pkg else None
                    if pin:
                        pins.append(pin)
            break
        i += 1
    return pins


def _extract_go_installs(run_value: str, source: str, resolved: dict[str, str]) -> list[InstallPin]:
    """Extract go install packages from a RUN command value."""
    pins: list[InstallPin] = []
    try:
        tokens = shlex.split(run_value)
    except ValueError:
        tokens = run_value.split()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "go" and i + 1 < len(tokens) and tokens[i + 1] == "install":
            i += 2
            while i < len(tokens):
                t = tokens[i]
                if t.startswith("-"):
                    i += 1
                    continue
                if t in ("&&", "||", ";", "|"):
                    break
                pkg = _resolve_vars(t.strip().strip('"').strip("'"), resolved)
                m = _GO_INSTALL_RE.match(pkg)
                if m:
                    module = m.group(1)
                    version = m.group(2)
                    resolved_ver = version.lstrip("v") if re.match(r"v?\d", version) else None
                    raw_spec = f"@{version}"
                    pins.append(
                        InstallPin(
                            name=module,
                            raw_spec=raw_spec,
                            resolved_version=resolved_ver,
                            ecosystem="go",
                            source=source,
                        )
                    )
                i += 1
            break
        i += 1
    return pins


def _extract_cargo_installs(
    run_value: str, source: str, resolved: dict[str, str]
) -> list[InstallPin]:
    """Extract cargo install packages from a RUN command value."""
    pins: list[InstallPin] = []
    try:
        tokens = shlex.split(run_value)
    except ValueError:
        tokens = run_value.split()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "cargo" and i + 1 < len(tokens) and tokens[i + 1] == "install":
            i += 2
            pkg_name: str | None = None
            version: str | None = None
            while i < len(tokens):
                t = tokens[i]
                if t in ("&&", "||", ";", "|"):
                    break
                if t in ("--version", "-V") and i + 1 < len(tokens):
                    version = tokens[i + 1]
                    i += 2
                    continue
                if t.startswith("-"):
                    i += 1
                    continue
                if pkg_name is None:
                    pkg_name = _resolve_vars(t.strip().strip('"').strip("'"), resolved)
                i += 1
            if pkg_name:
                if version:
                    ver = _resolve_vars(version, resolved)
                    pins.append(
                        InstallPin(
                            name=pkg_name,
                            raw_spec=f"=={ver}",
                            resolved_version=ver,
                            ecosystem="cargo",
                            source=source,
                        )
                    )
                else:
                    pins.append(
                        InstallPin(
                            name=pkg_name,
                            raw_spec="unpinned",
                            resolved_version=None,
                            ecosystem="cargo",
                            source=source,
                        )
                    )
            break
        i += 1
    return pins


def _extract_gem_installs(
    run_value: str, source: str, resolved: dict[str, str]
) -> list[InstallPin]:
    """Extract gem install packages from a RUN command value."""
    pins: list[InstallPin] = []
    try:
        tokens = shlex.split(run_value)
    except ValueError:
        tokens = run_value.split()

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok == "gem" and i + 1 < len(tokens) and tokens[i + 1] == "install":
            i += 2
            pkg_name: str | None = None
            version: str | None = None
            while i < len(tokens):
                t = tokens[i]
                if t in ("&&", "||", ";", "|"):
                    break
                if t in ("-v", "--version") and i + 1 < len(tokens):
                    version = tokens[i + 1]
                    i += 2
                    continue
                if t.startswith("-"):
                    i += 1
                    continue
                if pkg_name is None:
                    pkg_name = _resolve_vars(t.strip().strip('"').strip("'"), resolved)
                i += 1
            if pkg_name:
                if version:
                    ver = _resolve_vars(version, resolved)
                    pins.append(
                        InstallPin(
                            name=pkg_name,
                            raw_spec=f"=={ver}",
                            resolved_version=ver,
                            ecosystem="ruby",
                            source=source,
                        )
                    )
                else:
                    pins.append(
                        InstallPin(
                            name=pkg_name,
                            raw_spec="unpinned",
                            resolved_version=None,
                            ecosystem="ruby",
                            source=source,
                        )
                    )
            break
        i += 1
    return pins


def parse_dockerfile_installs(
    path: str,
    build_args: dict[str, str] | None = None,
    source: str | None = None,
) -> list[InstallPin]:
    """Parse a Dockerfile and extract package installs from RUN commands.

    Args:
        path: Absolute path to the Dockerfile.
        build_args: Dict of ARG values to overlay on top of ARG defaults.
        source: Display path for the SOURCE column (defaults to the path).

    Returns list of InstallPin, one per package extracted.
    """
    if _dockerfile_lib is None:
        return []

    if source is None:
        source = path

    try:
        cmds = _dockerfile_lib.parse_file(path)
    except Exception:
        return []

    arg_defaults = _collect_args(cmds)
    resolved = {**arg_defaults, **(build_args or {})}

    pins: list[InstallPin] = []
    for cmd in cmds:
        if cmd.cmd.upper() != "RUN":
            continue
        run_value = " ".join(cmd.value)
        pins.extend(_extract_pip_installs(run_value, source, resolved))
        pins.extend(_extract_npm_installs(run_value, source, resolved))
        pins.extend(_extract_go_installs(run_value, source, resolved))
        pins.extend(_extract_cargo_installs(run_value, source, resolved))
        pins.extend(_extract_gem_installs(run_value, source, resolved))

    return pins
