from __future__ import annotations

from unittest.mock import patch

from version_info.model import State
from version_info.registry_terraform import (
    _parse_terraform_lock_hcl,
    _terraform_registry_latest,
    scan_terraform,
)


class TestParseTerraformLockHcl:
    def test_parse_basic(self) -> None:
        hcl = """# provider "registry.terraform.io/hashicorp/aws"
provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.0.0"
  constraints = "~> 5.0"
}

provider "registry.terraform.io/hashicorp/azurerm" {
  version     = "3.0.0"
  constraints = "~> 3.0"
}
"""
        providers = _parse_terraform_lock_hcl(hcl)
        assert len(providers) == 2
        assert providers[0].name == "aws"
        assert providers[0].namespace == "hashicorp"
        assert providers[0].version == "5.0.0"
        assert providers[1].name == "azurerm"
        assert providers[1].namespace == "hashicorp"
        assert providers[1].version == "3.0.0"

    def test_parse_empty(self) -> None:
        providers = _parse_terraform_lock_hcl("")
        assert providers == []

    def test_parse_no_providers(self) -> None:
        hcl = """# This is a comment
variable "test" {
  type = string
}
"""
        providers = _parse_terraform_lock_hcl(hcl)
        assert providers == []

    def test_parse_with_comments(self) -> None:
        hcl = """# This is a comment about AWS provider
provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.0.0"
  constraints = "~> 5.0"
}

# Comment about GCP provider
provider "registry.terraform.io/hashicorp/google" {
  version     = "4.0.0"
}
"""
        providers = _parse_terraform_lock_hcl(hcl)
        assert len(providers) == 2
        assert providers[0].name == "aws"
        assert providers[0].version == "5.0.0"
        assert providers[1].name == "google"
        assert providers[1].version == "4.0.0"

    def test_parse_version_constraints_only(self) -> None:
        hcl = """provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.0.0"
}
"""
        providers = _parse_terraform_lock_hcl(hcl)
        assert len(providers) == 1
        assert providers[0].name == "aws"
        assert providers[0].version == "5.0.0"

    def test_parse_multiple_providers_sorted(self) -> None:
        hcl = """provider "registry.terraform.io/hashicorp/azurerm" {
  version     = "3.0.0"
}

provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.0.0"
}
"""
        providers = _parse_terraform_lock_hcl(hcl)
        assert len(providers) == 2
        # Should be sorted alphabetically by name (aws before azurerm)
        assert providers[0].name == "aws"
        assert providers[1].name == "azurerm"


class TestTerraformRegistryLatest:
    def test_success(self) -> None:
        mock_response = {
            "id": "hashicorp/aws",
            "versions": [
                {"version": "5.0.0"},
                {"version": "5.1.0"},
                {"version": "5.2.0"},
            ],
        }

        with patch("version_info.registry_terraform.get_json") as mock_get:
            mock_get.return_value = (
                type("MockResult", (), {"ok": True, "status": 200, "error": None})(),
                mock_response,
            )

            artifact, state = _terraform_registry_latest("hashicorp", "aws", timeout_s=10.0)
            assert artifact.value == "5.2.0"
            assert state == State.ok

    def test_prerelease_skipped(self) -> None:
        mock_response = {
            "id": "hashicorp/aws",
            "versions": [
                {"version": "5.0.0"},
                {"version": "5.1.0-alpha"},
                {"version": "5.2.0"},
            ],
        }

        with patch("version_info.registry_terraform.get_json") as mock_get:
            mock_get.return_value = (
                type("MockResult", (), {"ok": True, "status": 200, "error": None})(),
                mock_response,
            )

            artifact, state = _terraform_registry_latest("hashicorp", "aws", timeout_s=10.0)
            # Should skip 5.1.0-alpha and get 5.2.0
            assert artifact.value == "5.2.0"
            assert state == State.ok

    def test_all_prereleases(self) -> None:
        mock_response = {
            "id": "hashicorp/aws",
            "versions": [
                {"version": "5.0.0-alpha"},
                {"version": "5.1.0-beta"},
            ],
        }

        with patch("version_info.registry_terraform.get_json") as mock_get:
            mock_get.return_value = (
                type("MockResult", (), {"ok": True, "status": 200, "error": None})(),
                mock_response,
            )

            artifact, state = _terraform_registry_latest("hashicorp", "aws", timeout_s=10.0)
            # Should use first prerelease as fallback
            assert artifact.value == "5.0.0-alpha"
            assert state == State.ok

    def test_not_found(self) -> None:
        with patch("version_info.registry_terraform.get_json") as mock_get:
            mock_get.return_value = (
                type("MockResult", (), {"ok": False, "status": 404, "error": None})(),
                None,
            )

            artifact, state = _terraform_registry_latest("unknown", "provider", timeout_s=10.0)
            assert artifact.value is None
            assert artifact.note == "provider not found"
            assert state == State.not_found

    def test_auth_required(self) -> None:
        with patch("version_info.registry_terraform.get_json") as mock_get:
            mock_get.return_value = (
                type("MockResult", (), {"ok": False, "status": 401, "error": None})(),
                None,
            )

            artifact, state = _terraform_registry_latest("private", "provider", timeout_s=10.0)
            assert artifact.value is None
            assert artifact.note == "auth required"
            assert state == State.auth_required

    def test_rate_limited(self) -> None:
        with patch("version_info.registry_terraform.get_json") as mock_get:
            mock_get.return_value = (
                type("MockResult", (), {"ok": False, "status": 429, "error": "rate limited"})(),
                None,
            )

            artifact, state = _terraform_registry_latest("hashicorp", "aws", timeout_s=10.0)
            assert artifact.value is None
            assert artifact.note == "rate limited"
            assert state == State.rate_limited

    def test_no_versions_in_response(self) -> None:
        with patch("version_info.registry_terraform.get_json") as mock_get:
            mock_get.return_value = (
                type("MockResult", (), {"ok": True, "status": 200, "error": None})(),
                {},
            )

            artifact, state = _terraform_registry_latest("hashicorp", "aws", timeout_s=10.0)
            assert artifact.value is None
            assert artifact.note == "no versions in response"
            assert state == State.error

    def test_forbidden(self) -> None:
        with patch("version_info.registry_terraform.get_json") as mock_get:
            mock_get.return_value = (
                type("MockResult", (), {"ok": False, "status": 403, "error": None})(),
                None,
            )

            artifact, state = _terraform_registry_latest("hashicorp", "aws", timeout_s=10.0)
            assert artifact.value is None
            assert artifact.note == "auth required"
            assert state == State.auth_required


class TestScanTerraform:
    def test_no_lockfile(self, tmp_path) -> None:
        section = scan_terraform(str(tmp_path), timeout_s=10.0)
        assert section.title == "Terraform"
        assert section.rows == []

    def test_with_providers(self, tmp_path) -> None:
        lockfile = tmp_path / ".terraform.lock.hcl"
        lockfile.write_text("""provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.0.0"
}

provider "registry.terraform.io/hashicorp/azurerm" {
  version     = "3.0.0"
}
""")

        def mock_get_json(url, *, timeout_s, headers=None, cache=True):
            if "hashicorp/aws" in url:
                return (
                    type("MockResult", (), {"ok": True, "status": 200, "error": None})(),
                    {
                        "id": "hashicorp/aws",
                        "versions": [{"version": "5.1.0"}, {"version": "5.2.0"}],
                    },
                )
            elif "hashicorp/azurerm" in url:
                return (
                    type("MockResult", (), {"ok": True, "status": 200, "error": None})(),
                    {
                        "id": "hashicorp/azurerm",
                        "versions": [{"version": "3.0.0"}, {"version": "3.1.0"}],
                    },
                )
            return (
                type("MockResult", (), {"ok": False, "status": 404, "error": None})(),
                None,
            )

        with patch("version_info.registry_terraform.get_json", side_effect=mock_get_json):
            section = scan_terraform(str(tmp_path), timeout_s=10.0)

            assert section.title == "Terraform"
            assert len(section.rows) == 2

            # Providers are sorted alphabetically, so aws comes before azurerm
            assert section.rows[0].ecosystem == "terraform"
            assert section.rows[0].name == "hashicorp/aws"
            assert section.rows[0].current.value == "5.0.0"
            assert section.rows[0].latest.value == "5.2.0"
            assert section.rows[0].state == State.update_available
            assert section.rows[0].source == ".terraform.lock.hcl"

            assert section.rows[1].ecosystem == "terraform"
            assert section.rows[1].name == "hashicorp/azurerm"
            assert section.rows[1].current.value == "3.0.0"
            assert section.rows[1].latest.value == "3.1.0"
            assert section.rows[1].state == State.update_available
            assert section.rows[1].source == ".terraform.lock.hcl"

    def test_up_to_date(self, tmp_path) -> None:
        lockfile = tmp_path / ".terraform.lock.hcl"
        lockfile.write_text("""provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.2.0"
}
""")

        def mock_get_json(url, *, timeout_s, headers=None, cache=True):
            if "hashicorp/aws" in url:
                return (
                    type("MockResult", (), {"ok": True, "status": 200, "error": None})(),
                    {
                        "id": "hashicorp/aws",
                        "versions": [{"version": "5.1.0"}, {"version": "5.2.0"}],
                    },
                )
            return (
                type("MockResult", (), {"ok": False, "status": 404, "error": None})(),
                None,
            )

        with patch("version_info.registry_terraform.get_json", side_effect=mock_get_json):
            section = scan_terraform(str(tmp_path), timeout_s=10.0)

        assert len(section.rows) == 1
        assert section.rows[0].current.value == "5.2.0"
        assert section.rows[0].latest.value == "5.2.0"
        assert section.rows[0].state == State.ok

    def test_registry_error_propagates(self, tmp_path) -> None:
        lockfile = tmp_path / ".terraform.lock.hcl"
        lockfile.write_text("""provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.0.0"
}
""")

        def mock_get_json(url, *, timeout_s, headers=None, cache=True):
            return (
                type("MockResult", (), {"ok": False, "status": 429, "error": "rate limited"})(),
                None,
            )

        with patch("version_info.registry_terraform.get_json", side_effect=mock_get_json):
            section = scan_terraform(str(tmp_path), timeout_s=10.0)

        assert len(section.rows) == 1
        assert section.rows[0].state == State.rate_limited
        assert section.rows[0].latest.note == "rate limited"

    def test_handles_registry_errors(self, tmp_path) -> None:
        lockfile = tmp_path / ".terraform.lock.hcl"
        lockfile.write_text("""provider "registry.terraform.io/hashicorp/aws" {
  version     = "5.0.0"
}

provider "registry.terraform.io/hashicorp/azurerm" {
  version     = "3.0.0"
}
""")

        def mock_get_json(url, *, timeout_s, headers=None, cache=True):
            if "hashicorp/aws" in url:
                return (
                    type("MockResult", (), {"ok": True, "status": 200, "error": None})(),
                    {
                        "id": "hashicorp/aws",
                        "versions": [{"version": "5.1.0"}],
                    },
                )
            elif "hashicorp/azurerm" in url:
                return (
                    type("MockResult", (), {"ok": False, "status": 500, "error": "server error"})(),
                    None,
                )
            return (
                type("MockResult", (), {"ok": False, "status": 404, "error": None})(),
                None,
            )

        with patch("version_info.registry_terraform.get_json", side_effect=mock_get_json):
            section = scan_terraform(str(tmp_path), timeout_s=10.0)

        assert len(section.rows) == 2

        aws_row = next(r for r in section.rows if r.name == "hashicorp/aws")
        assert aws_row.state == State.update_available

        azurerm_row = next(r for r in section.rows if r.name == "hashicorp/azurerm")
        assert azurerm_row.state == State.error
