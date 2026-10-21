from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .release_models import ReleaseCandidate
from .release_policy import default_policy
from .release_selection import registry_selection
from .util_http import get_json


@dataclass(frozen=True)
class TerraformProvider:
    name: str
    namespace: str
    version: str


def _parse_terraform_lock_hcl(text: str) -> list[TerraformProvider]:
    """Parse a .terraform.lock.hcl file and extract provider information.

    .terraform.lock.hcl format:
        provider "registry.terraform.io/hashicorp/aws" {
          version     = "5.0.0"
          constraints = "~> 5.0"
          ...
        }
    """
    providers: dict[str, TerraformProvider] = {}

    # Pattern to match provider blocks
    provider_pattern = re.compile(r'provider\s+"([^"]+)"')

    # Pattern to match version assignment inside provider block
    version_pattern = re.compile(r'\s*version\s*=\s*"([^"]+)"')

    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]

        # Look for provider declaration
        provider_match = provider_pattern.match(line)
        if provider_match:
            provider_path = provider_match.group(1)

            # Extract version from the next lines until we hit a closing brace
            version = None
            j = i + 1
            while j < len(lines):
                v_match = version_pattern.match(lines[j])
                if v_match:
                    version = v_match.group(1)
                    break
                if lines[j].strip() == "}":
                    break
                j += 1

            if version and "/" in provider_path:
                parts = provider_path.split("/")
                # Full format: registry.terraform.io/namespace/name
                if len(parts) >= 3:
                    namespace = parts[1]
                    name = parts[2]
                    key = f"{namespace}/{name}"
                    if key not in providers:
                        providers[key] = TerraformProvider(
                            name=name,
                            namespace=namespace,
                            version=version,
                        )

            i = j
        i += 1

    return sorted(providers.values(), key=lambda x: x.name.lower())


def _terraform_registry_latest(
    namespace: str, provider: str, *, timeout_s: float, current_version: str | None = None
) -> tuple[Artifact, State]:
    """Fetch the latest version of a Terraform provider from the Terraform Registry."""
    url = f"https://registry.terraform.io/v1/providers/{namespace}/{provider}/versions"

    res, data = get_json(url, timeout_s=timeout_s)
    if not res.ok:
        _HTTP_ERRORS: dict[int, tuple[str, State]] = {
            404: ("provider not found", State.not_found),
            401: ("auth required", State.auth_required),
            403: ("auth required", State.auth_required),
            429: ("rate limited", State.rate_limited),
        }
        note, state = _HTTP_ERRORS.get(res.status or 0, (res.error or "http error", State.error))
        return Artifact(value=None, url=url, note=note), state

    if isinstance(data, dict):
        versions = data.get("versions")
        if isinstance(versions, list) and versions:
            candidates = [
                ReleaseCandidate(version["version"])
                for version in versions
                if isinstance(version, dict) and isinstance(version.get("version"), str)
            ]
            selection = registry_selection(
                ecosystem="terraform",
                package=f"{namespace}/{provider}",
                current=current_version,
                reported=None,
                candidates=candidates,
                complete=True,
                url=url,
                policy=default_policy(),
            )
            return selection.artifact, selection.state
    return Artifact(value=None, url=url, note="no versions in response"), State.error


def scan_terraform(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    """Scan for Terraform providers in .terraform.lock.hcl file.

    .terraform.lock.hcl is the lockfile with all resolved provider dependencies.
    """
    lock_path = Path(root) / ".terraform.lock.hcl"
    if not lock_path.exists():
        return Section(title="Terraform", rows=[])

    providers = _parse_terraform_lock_hcl(lock_path.read_text(encoding="utf-8", errors="replace"))

    def build_row(p: TerraformProvider) -> DepRow:
        latest, latest_state = _terraform_registry_latest(
            p.namespace, p.name, timeout_s=timeout_s, current_version=p.version
        )

        state = State.ok
        if latest.value is not None and latest.value != p.version:
            state = State.update_available
        elif latest_state != State.ok:
            state = latest_state

        return DepRow(
            ecosystem="terraform",
            name=f"{p.namespace}/{p.name}",
            current=Artifact(value=p.version),
            latest=latest,
            state=state,
            source=".terraform.lock.hcl",
        )

    rows = map_bounded_ordered(providers, build_row, max_workers=lookup_concurrency)
    return Section(title="Terraform", rows=rows)
