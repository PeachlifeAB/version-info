from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from functools import lru_cache
from importlib.resources import files
from types import MappingProxyType

from jsonschema import Draft202012Validator


class VersionScheme(str, Enum):
    pypi = "pypi"
    semver = "semver"
    ruby = "ruby"
    gradle = "gradle"


@dataclass(frozen=True)
class GradleRules:
    valid_pattern: re.Pattern[str]
    part_pattern: re.Pattern[str]
    unstable: frozenset[str]
    qualifier_order: Mapping[str, int]
    version_prefix: str


@dataclass(frozen=True)
class CompatibilityRule:
    ecosystem: str
    package: str
    pattern: re.Pattern[str]


@dataclass(frozen=True)
class SelectionPolicy:
    schemes: Mapping[str, VersionScheme]
    same_release_preview: frozenset[str]
    respect_reported_latest: frozenset[str]
    gradle: GradleRules
    compatibility: frozenset[CompatibilityRule]


@lru_cache(maxsize=1)
def default_policy() -> SelectionPolicy:
    resources = files("version_info").joinpath("data")
    definition = json.loads(resources.joinpath("release-policy.json").read_text(encoding="utf-8"))
    schema = json.loads(
        resources.joinpath("release-policy.schema.json").read_text(encoding="utf-8")
    )
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(definition)
    gradle = definition["gradle"]
    return SelectionPolicy(
        schemes=MappingProxyType({
            ecosystem: VersionScheme(scheme) for ecosystem, scheme in definition["schemes"].items()
        }),
        same_release_preview=frozenset(definition["same_release_preview"]),
        respect_reported_latest=frozenset(definition["respect_reported_latest"]),
        gradle=GradleRules(
            valid_pattern=re.compile(gradle["valid_pattern"]),
            part_pattern=re.compile(gradle["part_pattern"]),
            unstable=frozenset(gradle["unstable"]),
            qualifier_order=MappingProxyType(gradle["qualifier_order"]),
            version_prefix=gradle["version_prefix"],
        ),
        compatibility=frozenset(
            CompatibilityRule(rule["ecosystem"], rule["package"], re.compile(rule["pattern"]))
            for rule in definition["compatibility"]
        ),
    )
