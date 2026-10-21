# 2. Preserve candidates and use explicit update eligibility

Date: 2026-10-20 UTC

## Status

Accepted

## Context

The registry-selected Maven release can be a preview even when a stable update exists. The public Gradle regression records current `1.9.3`, reported `1.14.0-alpha03` and available stable `1.13.0`.

Pinned Renovate Gradle APIs and shared filtering reproduced `1.13.0` as highest eligible. Eight native comparisons retained complete candidate multisets in the experiment; 514 upstream tests passed. Custom beta-family preference is not native behavior.

## Decision

1. Preserve every captured candidate, including unselected, incompatible and unclassified versions. Record eligibility separately; do not mutate or truncate the original collection.
2. Use ecosystem-native ordering and release eligibility. For the verified Gradle policy, stable current versions do not advance to previews. Preview current versions may advance to newer stable releases; matching preview-family labels do not outrank final releases automatically.
3. Represent compatibility through explicit package rules, separate from prerelease classification. A configured compatibility value must not change in a recommended update. Do not infer compatibility from every unknown suffix.
4. Select recommendations from eligible candidates using native version order. Retention does not imply recommendation. If eligibility cannot be established, retain the candidate without claiming it is a safe update.
5. Resolve and validate policy at the boundary, then pass immutable typed configuration to selection. Registry adapters collect versions; one shared selection owner applies policy with an ecosystem-specific versioning implementation.
6. Preserve original candidate strings and make eligibility reasons observable. Do not replace the original Gradle regression or treat synthetic prototype preferences as production acceptance criteria.

## Consequences

Stable promotion replaces the experimental beta-over-final preference. Explicit compatibility rules protect variants such as Guava's `-jre`; unconfigured suffixes are not universal compatibility contracts.

Acceptance does not certify all ecosystems or implement production behavior. Cargo metadata remains unavailable. The CLI currently requires Python 3.10 or later and no Node runtime. A Maven-only Python comparator is not an equivalent Gradle implementation; a new runtime dependency requires a separate installation design and approval.

## Evidence

- [Captured native selection](../../tests/fixtures/selection/native-gradle.json)
- [Captured Gradle contracts](../../tests/fixtures/selection/gradle-contract.json)
- [Native release filtering](https://github.com/renovatebot/renovate/blob/e698ff5201cf54060c41a32aa40470be1f6ddc86/lib/workers/repository/process/lookup/filter.ts#L166-L192)
- [Explicit compatibility](https://github.com/renovatebot/renovate/blob/e698ff5201cf54060c41a32aa40470be1f6ddc86/lib/modules/versioning/regex/readme.md#L10-L28)
