from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReleaseStage(str, Enum):
    stable = "stable"
    preview = "preview"
    unclassified = "unclassified"


class DecisionReason(str, Enum):
    selected = "selected"
    eligible = "eligible"
    not_newer = "not_newer"
    preview = "preview"
    preview_line = "preview_line"
    incompatible = "incompatible"
    yanked = "yanked"
    unclassified = "unclassified"
    current_unclassified = "current_unclassified"
    above_channel = "above_registry_channel"


@dataclass(frozen=True)
class ReleaseCandidate:
    version: str
    yanked: bool = False


@dataclass(frozen=True)
class CandidateDecision:
    version: str
    stage: ReleaseStage
    eligible: bool
    reason: DecisionReason


@dataclass(frozen=True)
class ReleaseSelection:
    current: str | None
    reported: str | None
    chosen: str | None
    complete: bool
    candidates: list[CandidateDecision]
