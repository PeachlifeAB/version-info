from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .model import Artifact, DepRow, Section, State
from .parallel import map_bounded_ordered
from .util_http import get_json


@dataclass(frozen=True)
class RubyGem:
    name: str
    version: str


def _parse_gemfile_lock(text: str) -> list[RubyGem]:
    """Parse a Gemfile.lock file and extract gem names and versions.

    Gemfile.lock format:
        GEM
          remote: https://rubygems.org/
          specs:
            actionpack (7.0.4)
              actionview (= 7.0.4)
              ...
            activerecord (7.0.4)
              activemodel (= 7.0.4)
              ...

    We extract all gems from the GEM section.
    """
    gems: dict[str, str] = {}
    in_gem_section = False
    in_specs_section = False

    for line in text.splitlines():
        # Check for GEM section
        if line.strip() == "GEM":
            in_gem_section = True
            continue

        # Check for end of GEM section (new section starts)
        if in_gem_section and line and not line[0].isspace():
            in_gem_section = False
            in_specs_section = False
            continue

        # Check for specs: subsection
        if in_gem_section and line.strip() == "specs:":
            in_specs_section = True
            continue

        # Parse gem entries in specs section (4-space indent: "    gemname (version)")
        if in_gem_section and in_specs_section:
            # Gem entries have 4 spaces of indentation
            match = re.match(r"    ([a-zA-Z0-9_.\-]+) \(([^)]+)\)", line)
            if match:
                name = match.group(1)
                version = match.group(2)
                gems[name] = version

    return [
        RubyGem(name=n, version=v) for n, v in sorted(gems.items(), key=lambda kv: kv[0].lower())
    ]


def rubygems_org_latest(gem: str, *, timeout_s: float) -> tuple[Artifact, State]:
    """Fetch the latest version of a gem from rubygems.org.

    RubyGems API: https://rubygems.org/api/v1/gems/{gem}.json
    Returns JSON with version information.
    """
    url = f"https://rubygems.org/api/v1/gems/{gem}.json"

    res, data = get_json(url, timeout_s=timeout_s)
    if res.ok and isinstance(data, dict):
        version = data.get("version")
        if isinstance(version, str) and version:
            return Artifact(value=version, url=url), State.ok
        return Artifact(value=None, url=url, note="no version in response"), State.error

    if res.status == 404:
        return Artifact(value=None, url=url, note="not found"), State.not_found
    if res.status in (401, 403):
        return Artifact(value=None, url=url, note="auth required"), State.auth_required
    if res.status == 429:
        return Artifact(value=None, url=url, note="rate limited"), State.rate_limited
    return Artifact(value=None, url=url, note=res.error or "http error"), State.error


def scan_ruby(root: str, *, timeout_s: float, lookup_concurrency: int = 1) -> Section:
    """Scan for Ruby dependencies in Gemfile.lock file.

    Gemfile.lock is the lockfile with all resolved dependencies.
    """
    lock_path = Path(root) / "Gemfile.lock"
    if not lock_path.exists():
        return Section(title="Ruby (Bundler)", rows=[])

    gems = _parse_gemfile_lock(lock_path.read_text(encoding="utf-8", errors="replace"))

    def build_row(g: RubyGem) -> DepRow:
        latest, latest_state = rubygems_org_latest(g.name, timeout_s=timeout_s)

        state = State.ok
        if latest.value is not None and latest.value != g.version:
            state = State.update_available
        elif latest_state != State.ok:
            state = latest_state

        return DepRow(
            ecosystem="ruby",
            name=g.name,
            current=Artifact(value=g.version),
            latest=latest,
            state=state,
            source="Gemfile.lock",
        )

    rows = map_bounded_ordered(gems, build_row, max_workers=lookup_concurrency)
    return Section(title="Ruby (Bundler)", rows=rows)
