from __future__ import annotations

import argparse
import os
import sys
import traceback
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from . import __version__
from .model import Section
from .registry_docker import scan_docker_install_sections
from .report import ALL_LATEST_MESSAGE, filter_sections, render
from .scanners import SCANNERS, ScannerDef
from .section_merging import merge_sections as _merge_sections

DEFAULT_CONCURRENCY = 16

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
    stale_only: bool
    ignore_major: bool
    output_file: str | None
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
        "--stale",
        action="store_true",
        help="Show only confirmed available updates.",
    )
    p.add_argument(
        "--ignore-major",
        action="store_true",
        help="Hide known major-update rows; do not select alternative releases.",
    )
    p.add_argument(
        "-o",
        "--output-file",
        help="Also write the report to this file. With --stale, no file is written "
        "when no rows are stale, and an existing file is removed.",
    )
    p.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("VERSION_INFO_CONCURRENCY", str(DEFAULT_CONCURRENCY))),
        help=f"Maximum concurrent registry lookups (default: {DEFAULT_CONCURRENCY}).",
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
    scanner: ScannerDef, path: str, *, timeout_s: float, lookup_concurrency: int
) -> Section | None:
    try:
        section = scanner.scan_section(
            path,
            timeout_s=timeout_s,
            lookup_concurrency=lookup_concurrency,
        )
    except Exception as error:
        raise RuntimeError(f"{scanner.name} scan failed for {path}: {error}") from error
    if section.rows:
        return section
    return None


def _scan_path(path: str, *, timeout_s: float, concurrency: int = 4) -> list[Section]:
    detected: list[ScannerDef] = []
    for scanner in SCANNERS:
        try:
            if not scanner.detect(path):
                continue
            detected.append(scanner)
        except Exception as error:
            raise RuntimeError(f"{scanner.name} detection failed for {path}: {error}") from error

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
                lookup_concurrency=lookup_concurrency,
            )
            for scanner in detected
        ]
        return [section for future in futures if (section := future.result()) is not None]


def main(argv: list[str] | None = None) -> int:
    ns = parse_args(list(argv or sys.argv[1:]))
    root = str(Path(ns.path).resolve())

    ctx = Ctx(
        root=root,
        timeout_s=float(ns.timeout),
        verbose=bool(ns.verbose),
        json_output=bool(getattr(ns, "json", False)),
        stale_only=bool(ns.stale),
        ignore_major=bool(ns.ignore_major),
        output_file=ns.output_file,
        concurrency=max(1, int(ns.concurrency)),
    )

    # Get paths to scan (root + immediate subdirectories for monorepos)
    scan_paths = _get_scan_paths(ctx.root)

    all_sections: list[Section] = []
    try:
        for path in scan_paths:
            all_sections.extend(
                _scan_path(
                    path,
                    timeout_s=ctx.timeout_s,
                    concurrency=ctx.concurrency,
                )
            )
            all_sections.extend(
                scan_docker_install_sections(
                    path,
                    timeout_s=ctx.timeout_s,
                    lookup_concurrency=ctx.concurrency,
                )
            )
    except Exception as error:
        if ctx.verbose:
            traceback.print_exception(error)
        else:
            print(f"Scan failed: {error}", file=sys.stderr)
        return 1
    # Merge sections with the same ecosystem title
    sections = _merge_sections(all_sections)

    sections = filter_sections(sections, stale_only=ctx.stale_only, ignore_major=ctx.ignore_major)
    report = render(sections, json_output=ctx.json_output, stale_only=ctx.stale_only)
    sys.stdout.write(report)

    stale_rows_present = any(section.rows for section in sections)
    if ctx.stale_only and not stale_rows_present:
        if not ctx.json_output:
            sys.stderr.write("No matching updates.\n" if ctx.ignore_major else ALL_LATEST_MESSAGE)
        if ctx.output_file:
            Path(ctx.output_file).unlink(missing_ok=True)
    elif ctx.output_file:
        Path(ctx.output_file).write_text(report, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
