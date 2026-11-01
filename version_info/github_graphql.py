from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .util_http import post_json

GRAPHQL_URL = "https://api.github.com/graphql"
CHUNK_SIZE = 50


@dataclass(frozen=True)
class RepositoryQuery:
    key: str
    owner: str
    repo: str
    selection: str


def query_repositories(
    queries: list[RepositoryQuery], *, timeout_s: float
) -> dict[str, dict[str, Any]]:
    """Resolve repository selections in batched requests, CHUNK_SIZE repositories each.

    Repositories GitHub could not resolve are omitted from the result.
    """
    unique = list({query.key: query for query in queries}.values())
    nodes: dict[str, dict[str, Any]] = {}
    for start in range(0, len(unique), CHUNK_SIZE):
        chunk = unique[start : start + CHUNK_SIZE]
        fields = [
            f"r{i}: repository(owner: {json.dumps(query.owner)}, name: {json.dumps(query.repo)})"
            f" {{ {query.selection} }}"
            for i, query in enumerate(chunk)
        ]
        res, data = post_json(
            GRAPHQL_URL, {"query": "{ " + " ".join(fields) + " }"}, timeout_s=timeout_s
        )
        payload = data.get("data") if res.ok and isinstance(data, dict) else None
        if not isinstance(payload, dict):
            continue
        for i, query in enumerate(chunk):
            node = payload.get(f"r{i}")
            if isinstance(node, dict):
                nodes[query.key] = node
    return nodes
