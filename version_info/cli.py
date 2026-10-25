from __future__ import annotations

import argparse
import os

from . import __version__

DEFAULT_CONCURRENCY = 16


def parse_args(argv: list[str]) -> argparse.Namespace:
    allowing = bool(argv and argv[0] == "allow")
    parser = argparse.ArgumentParser(
        prog="version-info allow" if allowing else "version-info",
        epilog="Allow an installed version: version-info allow NAME VERSION "
        '--reason "three word reason"',
    )
    parser.set_defaults(
        allow=allowing, json=False, stale=False, ignore_major=False, output_file=None
    )
    if allowing:
        parser.add_argument("dependency", help="Exact installed dependency name.")
        parser.add_argument("dependency_version", help="Exact installed version.")
        parser.add_argument(
            "--reason", required=True, help="At least three words explaining the pin."
        )
        parser.add_argument(
            "--path", default=".", help="Project root (default: current directory)."
        )
    else:
        parser.add_argument(
            "path", nargs="?", default=".", help="Path to scan (default: current directory)"
        )
        parser.add_argument("--json", action="store_true", help="Output JSON instead of table.")
        parser.add_argument(
            "--stale", action="store_true", help="Show only confirmed, non-allowed updates."
        )
        parser.add_argument(
            "--ignore-major",
            action="store_true",
            help="Hide known major-update rows; do not select alternative releases.",
        )
        parser.add_argument(
            "-o",
            "--output-file",
            help="Also write the report to this file. With --stale, no file is written "
            "when no rows are stale, and an existing file is removed.",
        )
    parser.add_argument("--version", action="version", version=f"version-info {__version__}")
    parser.add_argument(
        "--timeout",
        type=float,
        default=float(os.environ.get("VERSION_INFO_TIMEOUT_S", "10")),
        help="Network/exec timeout in seconds (default: 10).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        default=os.environ.get("VERSION_INFO_VERBOSE", "0") == "1",
        help="Enable verbose diagnostics (default: env VERSION_INFO_VERBOSE=1).",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("VERSION_INFO_CONCURRENCY", str(DEFAULT_CONCURRENCY))),
        help=f"Maximum concurrent registry lookups (default: {DEFAULT_CONCURRENCY}).",
    )
    return parser.parse_args(argv[1:] if allowing else argv)
