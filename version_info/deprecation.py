from __future__ import annotations

from dataclasses import replace
from urllib.parse import quote

from .github_auth import github_token
from .github_graphql import RepositoryQuery, query_repositories
from .model import DepRow, Freshness, State
from .parallel import map_bounded_ordered
from .util_http import get_json

DEPS_DEV_VERSION_URL = (
    "https://api.deps.dev/v3/systems/{system}/packages/{package}/versions/{version}"
)
DEPS_DEV_SYSTEMS = {
    "cargo": "cargo",
    "go": "go",
    "gradle": "maven",
    "npm": "npm",
    "pypi": "pypi",
    "ruby": "rubygems",
}
UNSPECIFIED_NOTICE = "deprecated"
ARCHIVED_NOTICE = "repository archived"
ARCHIVED_SELECTION = "isArchived"


def deps_dev_deprecation(row: DepRow, *, timeout_s: float) -> str | None:
    """Return the deprecation notice deps.dev holds for the row's pinned version, if any.

    Any failure (network, status, shape) means "no signal", never an error row.
    """
    system = DEPS_DEV_SYSTEMS.get(row.ecosystem)
    version = row.current.value
    if system is None or not version:
        return None
    url = DEPS_DEV_VERSION_URL.format(
        system=system, package=quote(row.name, safe=""), version=quote(version, safe="")
    )
    result, data = get_json(url, timeout_s=timeout_s)
    if not result.ok or not isinstance(data, dict) or data.get("isDeprecated") is not True:
        return None
    reason = data.get("deprecatedReason")
    return reason.strip() if isinstance(reason, str) and reason.strip() else UNSPECIFIED_NOTICE


def with_deprecation(row: DepRow, notice: str | None) -> DepRow:
    if notice is None:
        return row
    state = State.deprecated if row.state == State.ok else row.state
    note = f"{row.note}; deprecated: {notice}" if row.note else f"deprecated: {notice}"
    return replace(row, state=state, note=note, freshness=Freshness.not_checked)


def archived_repositories(rows: list[DepRow], *, timeout_s: float) -> set[str]:
    """Names of rows whose GitHub repository is archived; unverifiable without a credential."""
    queries = [
        RepositoryQuery(row.name, row.repository.owner, row.repository.repo, ARCHIVED_SELECTION)
        for row in rows
        if row.repository is not None
    ]
    if not queries or not github_token():
        return set()
    nodes = query_repositories(queries, timeout_s=timeout_s)
    return {name for name, node in nodes.items() if node.get("isArchived") is True}


def apply_deprecation(
    rows: list[DepRow], *, timeout_s: float, lookup_concurrency: int
) -> list[DepRow]:
    notices = map_bounded_ordered(
        rows,
        lambda row: deps_dev_deprecation(row, timeout_s=timeout_s),
        max_workers=lookup_concurrency,
    )
    archived = archived_repositories(rows, timeout_s=timeout_s)
    return [
        with_deprecation(row, notice or (ARCHIVED_NOTICE if row.name in archived else None))
        for row, notice in zip(rows, notices, strict=True)
    ]
