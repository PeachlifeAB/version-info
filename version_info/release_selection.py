from __future__ import annotations

from dataclasses import dataclass, replace
from functools import cmp_to_key

from .model import Artifact, State
from .release_models import (
    CandidateDecision,
    DecisionReason,
    ReleaseCandidate,
    ReleaseSelection,
    ReleaseStage,
)
from .release_policy import SelectionPolicy
from .release_versions import compare_releases, release_stage, same_preview_line


@dataclass(frozen=True)
class SelectionContext:
    ecosystem: str
    package: str
    current: str | None
    reported: str | None
    policy: SelectionPolicy

    def compare(self, left: str, right: str) -> int:
        return compare_releases(left, right, self.ecosystem, self.policy)

    def stage(self, version: str) -> ReleaseStage:
        return release_stage(version, self.ecosystem, self.policy)


def _compatible(version: str, context: SelectionContext) -> bool:
    for rule in context.policy.compatibility:
        if rule.ecosystem != context.ecosystem or rule.package != context.package:
            continue
        current = rule.pattern.fullmatch(context.current or "")
        candidate = rule.pattern.fullmatch(version)
        if current is None or candidate is None:
            return False
        if current.groupdict().get("compatibility") != candidate.groupdict().get("compatibility"):
            return False
    return True


def _metadata_rejection(
    candidate: ReleaseCandidate, context: SelectionContext
) -> DecisionReason | None:
    if candidate.yanked:
        return DecisionReason.yanked
    if context.stage(candidate.version) == ReleaseStage.unclassified:
        return DecisionReason.unclassified
    if context.current is None:
        return None
    if context.stage(context.current) == ReleaseStage.unclassified:
        return DecisionReason.current_unclassified
    if not _compatible(candidate.version, context):
        return DecisionReason.incompatible
    return None


def _version_rejection(version: str, context: SelectionContext) -> DecisionReason | None:
    if context.current is None:
        return None
    current_stage = context.stage(context.current)
    stage = context.stage(version)
    if context.compare(version, context.current) <= 0:
        return DecisionReason.not_newer
    if stage == ReleaseStage.preview:
        if current_stage == ReleaseStage.stable:
            return DecisionReason.preview
        if not same_preview_line(version, context.current, context.ecosystem, context.policy):
            return DecisionReason.preview_line
    if (
        context.ecosystem in context.policy.respect_reported_latest
        and context.reported is not None
        and context.stage(context.reported) != ReleaseStage.unclassified
        and context.compare(context.current, context.reported) <= 0
        and context.compare(version, context.reported) > 0
    ):
        return DecisionReason.above_channel
    return None


def select_release(
    *,
    ecosystem: str,
    package: str,
    current: str | None,
    reported: str | None,
    candidates: list[ReleaseCandidate],
    complete: bool,
    policy: SelectionPolicy,
) -> ReleaseSelection:
    context = SelectionContext(ecosystem, package, current, reported, policy)
    decisions: list[CandidateDecision] = []
    for candidate in candidates:
        reason = (
            _metadata_rejection(candidate, context)
            or _version_rejection(candidate.version, context)
            or DecisionReason.eligible
        )
        decisions.append(
            CandidateDecision(
                candidate.version,
                context.stage(candidate.version),
                reason == DecisionReason.eligible,
                reason,
            )
        )
    eligible = [candidate.version for candidate in decisions if candidate.eligible]
    eligible.sort(key=cmp_to_key(context.compare), reverse=True)
    if current is None:
        eligible.sort(
            key=lambda version: context.stage(version) == ReleaseStage.stable, reverse=True
        )
    has_comparable_candidate = any(
        candidate.stage != ReleaseStage.unclassified for candidate in decisions
    )
    chosen = (
        current
        if has_comparable_candidate
        and current is not None
        and context.stage(current) != ReleaseStage.unclassified
        else None
    )
    if eligible:
        chosen = reported if current is None and reported in eligible else eligible[0]
    decisions = [
        replace(candidate, reason=DecisionReason.selected)
        if candidate.eligible and candidate.version == chosen
        else candidate
        for candidate in decisions
    ]
    return ReleaseSelection(current, reported, chosen, complete, decisions)


@dataclass(frozen=True)
class SelectionLookup:
    artifact: Artifact
    state: State


def registry_selection(
    *,
    ecosystem: str,
    package: str,
    current: str | None,
    reported: str | None,
    candidates: list[ReleaseCandidate],
    complete: bool,
    url: str,
    policy: SelectionPolicy,
) -> SelectionLookup:
    selection = select_release(
        ecosystem=ecosystem,
        package=package,
        current=current,
        reported=reported,
        candidates=candidates,
        complete=complete,
        policy=policy,
    )
    artifact = Artifact(value=selection.chosen, url=url, selection=selection)
    return SelectionLookup(artifact, State.ok if selection.chosen is not None else State.error)
