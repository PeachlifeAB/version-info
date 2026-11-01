from __future__ import annotations

from unittest.mock import patch

import pytest

from version_info.deprecation import apply_deprecation, deps_dev_deprecation
from version_info.model import Artifact, DepRow, Section, State
from version_info.scanners import ScannerDef
from version_info.util_http import HttpResult


def _row(ecosystem: str = "npm", name: str = "request", version: str | None = "2.88.2") -> DepRow:
    return DepRow(
        ecosystem=ecosystem,
        name=name,
        current=Artifact(value=version),
        latest=Artifact(value=version),
        state=State.ok,
        source="lock",
    )


def _deps_dev(payload: dict | None, *, ok: bool = True):
    def fake_get_json(url: str, *, timeout_s: float):
        fake_get_json.urls.append(url)
        return HttpResult(ok=ok, status=200 if ok else 500, text=""), payload

    fake_get_json.urls = []
    return fake_get_json


def test_deprecated_version_yields_the_registry_reason() -> None:
    fake = _deps_dev({"isDeprecated": True, "deprecatedReason": "use got instead"})
    with patch("version_info.deprecation.get_json", side_effect=fake):
        assert deps_dev_deprecation(_row(), timeout_s=1) == "use got instead"


def test_deprecated_without_reason_still_reports() -> None:
    fake = _deps_dev({"isDeprecated": True})
    with patch("version_info.deprecation.get_json", side_effect=fake):
        assert deps_dev_deprecation(_row(), timeout_s=1) == "deprecated"


@pytest.mark.parametrize(
    ("ecosystem", "name", "system", "encoded"),
    [
        ("gradle", "com.google.guava:guava", "maven", "com.google.guava%3Aguava"),
        ("ruby", "rails", "rubygems", "rails"),
    ],
)
def test_ecosystems_map_to_their_deps_dev_system(
    ecosystem: str, name: str, system: str, encoded: str
) -> None:
    fake = _deps_dev({"isDeprecated": False})
    with patch("version_info.deprecation.get_json", side_effect=fake):
        deps_dev_deprecation(_row(ecosystem, name, "1.0"), timeout_s=1)
    assert fake.urls == [
        f"https://api.deps.dev/v3/systems/{system}/packages/{encoded}/versions/1.0"
    ]


def test_supported_package_name_is_url_encoded() -> None:
    fake = _deps_dev({"isDeprecated": False})
    with patch("version_info.deprecation.get_json", side_effect=fake):
        deps_dev_deprecation(_row("go", "gopkg.in/yaml.v3", "v3.0.1"), timeout_s=1)
    assert fake.urls == [
        "https://api.deps.dev/v3/systems/go/packages/gopkg.in%2Fyaml.v3/versions/v3.0.1"
    ]


@pytest.mark.parametrize(
    "row",
    [_row("docker", "nginx"), _row("nix", "nixpkgs"), _row(version=None)],
    ids=["unsupported-ecosystem", "unsupported-nix", "no-pinned-version"],
)
def test_rows_deps_dev_cannot_answer_are_not_queried(row: DepRow) -> None:
    fake = _deps_dev({"isDeprecated": True})
    with patch("version_info.deprecation.get_json", side_effect=fake):
        assert deps_dev_deprecation(row, timeout_s=1) is None
    assert fake.urls == []


def test_service_failure_is_no_signal_not_an_error() -> None:
    with patch("version_info.deprecation.get_json", side_effect=_deps_dev(None, ok=False)):
        assert deps_dev_deprecation(_row(), timeout_s=1) is None


def test_ok_row_becomes_deprecated_and_update_row_keeps_its_state() -> None:
    update = DepRow(
        ecosystem="npm",
        name="request",
        current=Artifact(value="2.88.2"),
        latest=Artifact(value="2.88.3"),
        state=State.update_available,
        source="lock",
    )
    fake = _deps_dev({"isDeprecated": True, "deprecatedReason": "gone"})
    with patch("version_info.deprecation.get_json", side_effect=fake):
        rows = apply_deprecation([_row(), update], timeout_s=1, lookup_concurrency=2)
    assert [row.state for row in rows] == [State.deprecated, State.update_available]
    assert all(row.note and "deprecated: gone" in row.note for row in rows)


def test_every_scanner_gets_the_deprecation_check() -> None:
    scanner = ScannerDef(
        name="x", section_title="X", markers=("x",), scan_fn=lambda root, timeout_s: [_row()]
    )
    fake = _deps_dev({"isDeprecated": True, "deprecatedReason": "gone"})
    with patch("version_info.deprecation.get_json", side_effect=fake):
        section = scanner.scan_section(".", timeout_s=1)
    assert isinstance(section, Section)
    assert section.rows[0].state == State.deprecated
