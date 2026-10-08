from __future__ import annotations

import argparse
import os
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .model import DepRow, Section
from .registry_docker import scan_docker_install_sections
from .report import render
from .scanners import SCANNERS, ScannerDef

DEFAULT_EXCLUDED_SCAN_DIRS = {
    "__pycache__",
    "build",
    "dist",
    "docs",
    "examples",
    "fixtures",
    "node_modules",
    "references",
    "test",
    "tests",
    "vendor",
    "archived",
    "worktrees",
}


@dataclass(frozen=True)
class Ctx:
    root: str
    timeout_s: float
    verbose: bool
    json_output: bool
    concurrency: int


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="version-info")
    p.add_argument(
        "--version",
        action="version",
        version=f"version-info {__version__}",
    )
    p.add_argument(
        "path",
        nargs="?",
        default=".",
        help="Path to scan (default: current directory)",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("VERSION_INFO_TIMEOUT_S", "10")),
        help="Network/exec timeout in seconds (default: 10).",
    )
    p.add_argument(
        "--verbose",
        action="store_true",
        default=os.environ.get("VERSION_INFO_VERBOSE", "0") == "1",
        help="Enable verbose diagnostics (default: env VERSION_INFO_VERBOSE=1).",
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Output JSON instead of table.",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("VERSION_INFO_CONCURRENCY", "4")),
        help="Maximum scanner concurrency (default: 4).",
    )
    return p.parse_args(argv)


def _get_scan_paths(root: str) -> list[str]:
    """Get paths to scan: root directory plus immediate subdirectories (for monorepos)."""
    paths = [root]
    try:
        for entry in os.scandir(root):
            if (
                entry.is_dir(follow_symlinks=False)
                and not entry.name.startswith(".")
                and entry.name not in DEFAULT_EXCLUDED_SCAN_DIRS
            ):
                paths.append(entry.path)
    except OSError:
        pass
    return paths


def _scan_one(
    scanner: ScannerDef, path: str, *, timeout_s: float, verbose: bool, lookup_concurrency: int
) -> Section | None:
    try:
        section = scanner.scan_section(
            path,
            timeout_s=timeout_s,
            lookup_concurrency=lookup_concurrency,
        )
    except Exception as e:
        if verbose:
            scanner_type = scanner.__class__.__name__
            print(f"{scanner_type}({scanner.name}) failed for {path}: {e}", file=sys.stderr)
        return None
    if section.rows:
        return section
    return None


def _scan_path(
    path: str, *, timeout_s: float, verbose: bool = False, concurrency: int = 4
) -> list[Section]:
    detected: list[ScannerDef] = []
    for scanner in SCANNERS:
        try:
            if not scanner.detect(path):
                continue
            detected.append(scanner)
        except Exception as e:
            if verbose:
                scanner_type = scanner.__class__.__name__
                print(f"{scanner_type}({scanner.name}) failed for {path}: {e}", file=sys.stderr)
            continue

    if not detected:
        return []

    worker_count = max(1, min(concurrency, len(detected)))
    lookup_concurrency = max(1, concurrency // worker_count)
    if worker_count == 1:
        return [
            section
            for scanner in detected
            if (
                section := _scan_one(
                    scanner,
                    path,
                    timeout_s=timeout_s,
                    verbose=verbose,
                    lookup_concurrency=lookup_concurrency,
                )
            )
            is not None
        ]

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(
                _scan_one,
                scanner,
                path,
                timeout_s=timeout_s,
                verbose=verbose,
                lookup_concurrency=lookup_concurrency,
            )
            for scanner in detected
        ]
        return [section for future in futures if (section := future.result()) is not None]


def _merge_sections(sections: list[Section]) -> list[Section]:
    """Merge sections with the same title, combining their rows.

    Deduplicates by (ecosystem, name):
    - If current.value is identical across all instances: merge into one row with
      accumulated SOURCE (shows "path +1" format indicating additional sources).
    - If different exact versions or non-comparable: keep all rows.
    - Precedence for non-identical values: exact pin > range > unpinned.
    This ensures version drift between sources is never hidden.
    """
    by_title: dict[str, list[DepRow]] = {}
    for section in sections:
        if not section.rows:
            continue
        by_title.setdefault(section.title, []).extend(section.rows)

    merged_sections: list[Section] = []
    for title, rows in by_title.items():
        if len(rows) <= 1:
            merged_sections.append(Section(title=title, rows=rows))
            continue

        groups: dict[tuple[str, str], list[DepRow]] = {}
        for row in rows:
            key = (row.ecosystem, row.name.lower())
            groups.setdefault(key, []).append(row)

        deduped: list[DepRow] = []
        for (_ecosystem, _name), group in groups.items():
            if len(group) == 1:
                deduped.append(group[0])
                continue

            current_vals = {r.current.value for r in group}
            if len(current_vals) == 1:
                all_sources = "; ".join(r.source for r in group if r.source)
                row0 = group[0]
                extra_count = len(group) - 1
                display_source = f"{all_sources} +{extra_count}" if extra_count else all_sources
                deduped.append(
                    DepRow(
                        ecosystem=row0.ecosystem,
                        name=row0.name,
                        current=row0.current,
                        latest=row0.latest,
                        state=row0.state,
                        source=display_source,
                        source_class=row0.source_class,
                        freshness=row0.freshness,
                        note=row0.note,
                    )
                )
            else:
                exact_rows = [r for r in group if r.current.note not in ("range", "unpinned")]
                unpinned_rows = [r for r in group if r.current.note == "unpinned"]
                range_rows = [r for r in group if r.current.note == "range"]

                if len(exact_rows) >= 1:
                    deduped.extend(exact_rows)
                if range_rows:
                    deduped.extend(range_rows)
                if unpinned_rows:
                    deduped.extend(unpinned_rows)

        merged_sections.append(Section(title=title, rows=deduped))

    return merged_sections


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(list(argv or sys.argv[1:]))
    root = str(Path(ns.path).resolve())

    ctx = Ctx(
        root=root,
        timeout_s=float(ns.timeout),
        verbose=bool(ns.verbose),
        json_output=bool(getattr(ns, "json", False)),
        concurrency=max(1, int(ns.concurrency)),
    )

    # Get paths to scan (root + immediate subdirectories for monorepos)
    scan_paths = _get_scan_paths(ctx.root)

    # Collect sections from all detected scanners across all scan paths
    all_sections: list[Section] = []
    for path in scan_paths:
        all_sections.extend(
            _scan_path(
                path,
                timeout_s=ctx.timeout_s,
                verbose=ctx.verbose,
                concurrency=ctx.concurrency,
            )
        )
        # TODO(scanner-registry): scan_docker_install_sections is called outside the
        # scanner registry loop. When a --scanners filter is added, this should be moved
        # inside _scan_path or passed as a scanner to respect scanner selection.
        # Collect native ecosystem rows from Dockerfile install commands
        try:
            docker_install_sections = scan_docker_install_sections(
                path,
                timeout_s=ctx.timeout_s,
                lookup_concurrency=max(1, ctx.concurrency),
            )
            all_sections.extend(docker_install_sections)
        except Exception as e:
            if ctx.verbose:
                print(f"scan_docker_install_sections failed for {path}: {e}", file=sys.stderr)

    # Merge sections with the same ecosystem title
    sections = _merge_sections(all_sections)

    sys.stdout.write(render(sections, json_output=ctx.json_output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
