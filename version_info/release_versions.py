from __future__ import annotations

from packaging.version import Version as PythonVersion
from semver import Version as SemverVersion
from univers.gem import GemVersion

from .gradle_versioning import compare_gradle, gradle_parts, gradle_release_line
from .release_models import ReleaseStage
from .release_policy import SelectionPolicy, VersionScheme


def release_stage(version: str, ecosystem: str, policy: SelectionPolicy) -> ReleaseStage:
    try:
        scheme = policy.schemes[ecosystem]
        if scheme == VersionScheme.pypi:
            python_version = PythonVersion(version)
            preview = python_version.is_prerelease or python_version.is_devrelease
        elif scheme == VersionScheme.semver:
            preview = bool(SemverVersion.parse(version.removeprefix("v")).prerelease)
        elif scheme == VersionScheme.ruby:
            preview = GemVersion(version).prerelease()
        else:
            preview = any(
                part.lower() in policy.gradle.unstable
                for part in gradle_parts(version, policy.gradle)
            )
    except (ValueError, KeyError):
        return ReleaseStage.unclassified
    return ReleaseStage.preview if preview else ReleaseStage.stable


def compare_releases(left: str, right: str, ecosystem: str, policy: SelectionPolicy) -> int:
    scheme = policy.schemes[ecosystem]
    if scheme == VersionScheme.pypi:
        return int(PythonVersion(left) > PythonVersion(right)) - int(
            PythonVersion(left) < PythonVersion(right)
        )
    if scheme == VersionScheme.semver:
        return SemverVersion.parse(left.removeprefix("v")).compare(right.removeprefix("v"))
    if scheme == VersionScheme.ruby:
        return int(GemVersion(left) > GemVersion(right)) - int(GemVersion(left) < GemVersion(right))
    return compare_gradle(left, right, policy.gradle)


def same_preview_line(left: str, right: str, ecosystem: str, policy: SelectionPolicy) -> bool:
    if ecosystem not in policy.same_release_preview:
        return True
    return gradle_release_line(left, policy.gradle) == gradle_release_line(right, policy.gradle)
