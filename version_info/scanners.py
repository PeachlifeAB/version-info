from __future__ import annotations

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .model import DepRow, Section, SourceClass
from .registry_cargo import scan_cargo
from .registry_docker import scan_docker
from .registry_go import scan_go
from .registry_mise import scan_mise
from .registry_nix import scan_nix
from .registry_npm import scan_npm
from .registry_pypi import scan_pypi
from .registry_ruby import scan_ruby
from .registry_swiftpm import scan_swiftpm
from .registry_terraform import scan_terraform

ScanResult = Section | list[DepRow]
ScanFn = Callable[[str], ScanResult]


def _find_xcodeproj_package_resolved(root: str) -> str | None:
    matches = list(
        Path(root).glob("*.xcodeproj/project.xcworkspace/xcshareddata/swiftpm/Package.resolved")
    )
    return str(matches[0]) if matches else None


@dataclass(frozen=True)
class ScannerDef:
    name: str
    section_title: str
    markers: tuple[str, ...]
    scan_fn: Callable[..., ScanResult]
    source_class: SourceClass = SourceClass.resolved_lockfile

    def detect(self, root: str) -> bool:
        root_path = Path(root)
        if any((root_path / rel).exists() for rel in self.markers):
            return True
        if self.name == "swiftpm":
            return _find_xcodeproj_package_resolved(root) is not None
        return False

    def scan_section(self, root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
        if "lookup_concurrency" in inspect.signature(self.scan_fn).parameters:
            result = self.scan_fn(
                root,
                timeout_s=timeout_s,
                lookup_concurrency=lookup_concurrency,
            )
        else:
            result = self.scan_fn(root, timeout_s=timeout_s)
        if isinstance(result, Section):
            return Section(title=self.section_title, rows=result.rows)
        return Section(title=self.section_title, rows=result)


SCANNERS: tuple[ScannerDef, ...] = (
    ScannerDef(
        name="npm",
        section_title="Node (npm)",
        markers=("package-lock.json",),
        scan_fn=scan_npm,
        source_class=SourceClass.resolved_lockfile,
    ),
    ScannerDef(
        name="pypi",
        section_title="Python (PyPI)",
        markers=("pyproject.toml", "requirements.txt", "uv.lock", "poetry.lock"),
        scan_fn=scan_pypi,
        source_class=SourceClass.declared_manifest,
    ),
    ScannerDef(
        name="go",
        section_title="Go",
        markers=("go.mod", "go.sum"),
        scan_fn=scan_go,
        source_class=SourceClass.resolved_lockfile,
    ),
    ScannerDef(
        name="cargo",
        section_title="Rust (Cargo)",
        markers=("Cargo.lock",),
        scan_fn=scan_cargo,
        source_class=SourceClass.resolved_lockfile,
    ),
    ScannerDef(
        name="swiftpm",
        section_title="Swift (SwiftPM)",
        markers=("Package.resolved",),
        scan_fn=scan_swiftpm,
        source_class=SourceClass.resolved_lockfile,
    ),
    ScannerDef(
        name="ruby",
        section_title="Ruby (Bundler)",
        markers=("Gemfile.lock",),
        scan_fn=scan_ruby,
        source_class=SourceClass.resolved_lockfile,
    ),
    ScannerDef(
        name="terraform",
        section_title="Terraform",
        markers=(".terraform.lock.hcl",),
        scan_fn=scan_terraform,
        source_class=SourceClass.resolved_lockfile,
    ),
    ScannerDef(
        name="nix",
        section_title="Nix (Flakes)",
        markers=("flake.lock",),
        scan_fn=scan_nix,
        source_class=SourceClass.resolved_lockfile,
    ),
    ScannerDef(
        name="mise",
        section_title="Tools (mise)",
        markers=("mise.toml", ".mise.toml", ".tool-versions"),
        scan_fn=scan_mise,
        source_class=SourceClass.runtime_tool,
    ),
    ScannerDef(
        name="docker",
        section_title="Docker",
        markers=(
            "docker-compose.yml",
            "docker-compose.yaml",
            "compose.yml",
            "compose.yaml",
            "Dockerfile",
        ),
        scan_fn=scan_docker,
        source_class=SourceClass.container_runtime,
    ),
)
