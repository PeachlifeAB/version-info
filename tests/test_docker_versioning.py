from __future__ import annotations

from version_info.docker_versioning import (
    best_docker_update,
    docker_freshness,
    parse_docker_tag,
)
from version_info.model import Freshness


def test_parse_docker_tag_version_suffix() -> None:
    tag = parse_docker_tag("22-alpine")
    assert tag is not None
    assert tag.parts == (22,)
    assert tag.suffix == "-alpine"


def test_best_docker_update_major() -> None:
    assert best_docker_update("16", ["latest", "15", "16", "17"]) == "17"


def test_best_docker_update_patch() -> None:
    assert best_docker_update("7.2.1", ["7.2.0", "7.2.4", "7.3.0"]) == "7.3.0"


def test_best_docker_update_keeps_suffix_compatible() -> None:
    assert best_docker_update("22-alpine", ["23-bookworm", "23-alpine"]) == "23-alpine"


def test_best_docker_update_rejects_incompatible_suffixes() -> None:
    assert best_docker_update("22-alpine", ["23-bookworm", "latest"]) is None


def test_best_docker_update_ignores_sha_like_tags() -> None:
    assert best_docker_update("1.0", ["abcdef123456", "1.1"]) == "1.1"


def test_best_docker_update_requires_same_precision() -> None:
    assert best_docker_update("2.8", ["3.1.0", "3.1"]) == "3.1"


def test_docker_freshness_major() -> None:
    assert docker_freshness("16", "17") == Freshness.major_behind


def test_docker_freshness_minor() -> None:
    assert docker_freshness("2.8", "2.9") == Freshness.minor_behind


def test_docker_freshness_patch() -> None:
    assert docker_freshness("7.2.1", "7.2.4") == Freshness.patch_behind


def test_docker_freshness_incompatible_suffix_not_checked() -> None:
    assert docker_freshness("22-alpine", "23-bookworm") == Freshness.not_checked


def test_best_docker_update_channel_tag() -> None:
    assert best_docker_update("latest", ["latest", "1.0", "2.0"]) == "2.0"


def test_best_docker_update_branch_tag() -> None:
    assert best_docker_update("main", ["main", "1.0", "2.0"]) == "main"


def test_best_docker_update_variant_only_tag() -> None:
    assert best_docker_update("slim", ["3.11-slim", "3.12-slim", "3.12-alpine"]) == "3.12-slim"
