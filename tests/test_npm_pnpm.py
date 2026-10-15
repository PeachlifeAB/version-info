from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from version_info.model import Artifact, State
from version_info.registry_npm import _parse_pnpm_lock, scan_npm

PNPM_LOCK_V9 = """\
lockfileVersion: '9.0'

importers:

  .:
    dependencies:
      express:
        specifier: ^4.18.2
        version: 4.18.2
      react:
        specifier: ^18.0.0
        version: 18.3.1(@types/react@18.0.0)
    devDependencies:
      vitest:
        specifier: 'catalog:'
        version: 3.2.4(@types/node@20.0.0)
      local-helper:
        specifier: workspace:*
        version: link:../local-helper

packages:

  express@4.18.2:
    resolution: {integrity: sha512-example}
"""

PNPM_LOCK_V6 = """\
lockfileVersion: '6.0'

dependencies:
  lodash:
    specifier: ^4.17.21
    version: 4.17.21

packages:

  /lodash@4.17.21:
    resolution: {integrity: sha512-example}
"""


def test_parse_pnpm_lock_v9_root_importer_direct_dependencies() -> None:
    """Root importer deps are read; peer suffixes are stripped and link: specifiers dropped."""
    deps = _parse_pnpm_lock(PNPM_LOCK_V9)

    assert [(dep.name, dep.version) for dep in deps] == [
        ("express", "4.18.2"),
        ("react", "18.3.1"),
        ("vitest", "3.2.4"),
    ]


def test_parse_pnpm_lock_v6_top_level_dependencies() -> None:
    """Lockfiles before v9 keep direct dependencies at the top level."""
    deps = _parse_pnpm_lock(PNPM_LOCK_V6)

    assert [(dep.name, dep.version) for dep in deps] == [("lodash", "4.17.21")]


def test_scan_npm_reads_pnpm_lock_when_package_lock_absent(tmp_path: Path) -> None:
    """scan_npm falls back to pnpm-lock.yaml and reports it as the row source."""
    (tmp_path / "pnpm-lock.yaml").write_text(PNPM_LOCK_V6, encoding="utf-8")

    with patch(
        "version_info.registry_npm.npm_latest",
        return_value=(Artifact(value="4.17.21", url="https://registry.npmjs.org/lodash"), State.ok),
    ):
        section = scan_npm(str(tmp_path), timeout_s=10.0)

    assert [(row.name, row.source) for row in section.rows] == [("lodash", "pnpm-lock.yaml")]
    assert section.rows[0].state == State.ok
