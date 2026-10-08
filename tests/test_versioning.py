from __future__ import annotations

from version_info.docker_versioning import best_docker_nonversion_update
from version_info.model import Freshness, State
from version_info.versioning import compare_versions, state_from_latest


def test_compare_versions_latest() -> None:
    assert compare_versions("1.2.3", "1.2.3") == Freshness.latest


def test_compare_versions_major_behind() -> None:
    assert compare_versions("1.2.3", "2.0.0") == Freshness.major_behind


def test_compare_versions_minor_behind() -> None:
    assert compare_versions("1.2.3", "1.3.0") == Freshness.minor_behind


def test_compare_versions_patch_behind() -> None:
    assert compare_versions("1.2.3", "1.2.4") == Freshness.patch_behind


def test_compare_versions_v_prefix() -> None:
    assert compare_versions("v1.2.3", "v1.2.4") == Freshness.patch_behind


def test_compare_versions_uncomparable_digest() -> None:
    assert compare_versions("sha256:abc123def456", "sha256:def456abc123") == Freshness.uncomparable


def test_compare_versions_uncomparable_git_hash() -> None:
    assert compare_versions("abc123def", "def456abc") == Freshness.uncomparable


def test_compare_versions_numeric_only_version_is_comparable() -> None:
    assert compare_versions("1234567", "1234568") == Freshness.major_behind


def test_compare_versions_uncomparable_malformed() -> None:
    assert compare_versions("bookworm", "trixie") == Freshness.uncomparable


def test_state_from_latest_uncomparable_is_not_update() -> None:
    assert state_from_latest("bookworm", "trixie", State.ok) == State.error


def test_best_docker_nonversion_update_prefers_unsuffixed_channel_tags() -> None:
    upstream_tags = ["3.11-slim", "3.12", "3.13-slim"]

    assert best_docker_nonversion_update("latest", upstream_tags) == "3.12"


def test_best_docker_nonversion_update_falls_back_to_variant_when_needed() -> None:
    upstream_tags = ["3.11-slim", "3.13-slim"]

    assert best_docker_nonversion_update("latest", upstream_tags) == "3.13-slim"
