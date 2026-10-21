from __future__ import annotations

from dataclasses import dataclass

from .release_policy import GradleRules


@dataclass(frozen=True)
class GradleReleaseLine:
    major: int | None
    minor: int | None
    patch: int | None


def gradle_parts(version: str, rules: GradleRules) -> list[str]:
    """Parse Gradle single versions without interpreting rich constraints."""
    if not rules.valid_pattern.fullmatch(version):
        raise ValueError(version)
    return rules.part_pattern.findall(version)


def compare_gradle(left: str, right: str, rules: GradleRules) -> int:
    """Compare numeric parts and case-sensitive words using Gradle qualifier ranks."""
    left_parts = gradle_parts(left, rules)
    right_parts = gradle_parts(right, rules)
    for index, left_part in enumerate(left_parts):
        if index >= len(right_parts):
            return 1 if left_part.isdecimal() else -1
        right_part = right_parts[index]
        if left_part.isdecimal() and right_part.isdecimal():
            difference = int(left_part) - int(right_part)
        elif left_part.isdecimal() != right_part.isdecimal():
            return 1 if left_part.isdecimal() else -1
        else:
            left_rank = rules.qualifier_order.get(left_part.lower(), 0)
            right_rank = rules.qualifier_order.get(right_part.lower(), 0)
            difference = left_rank - right_rank
            if left_rank == 0 and right_rank == 0:
                difference = int(left_part > right_part) - int(left_part < right_part)
        if difference:
            return 1 if difference > 0 else -1
    if len(right_parts) > len(left_parts):
        return -1 if right_parts[len(left_parts)].isdecimal() else 1
    return 0


def gradle_release_line(version: str, rules: GradleRules) -> GradleReleaseLine:
    if version[:1].lower() == rules.version_prefix.lower():
        version = version[1:]
    try:
        parts = gradle_parts(version, rules)
    except ValueError:
        return GradleReleaseLine(None, None, None)
    major = int(parts[0]) if parts[0].isdecimal() else None
    minor = int(parts[1]) if major is not None and len(parts) > 1 and parts[1].isdecimal() else 0
    patch = (
        int(parts[2])
        if major is not None and len(parts) > 2 and parts[1].isdecimal() and parts[2].isdecimal()
        else 0
    )
    return GradleReleaseLine(major, minor, patch)
