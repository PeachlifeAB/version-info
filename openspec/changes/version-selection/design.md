# Context-aware registry recommendations

## Contract

Apply the accepted policy in ADR 0002 across adapters where existing metadata supports it. Preserve all observed candidate strings and report eligibility separately. Mark metadata as complete only when the response supplies the relevant version collection; backend-selected releases and unpaginated tag responses remain partial.

Stable dependencies prefer eligible stable updates. Preview dependencies can advance to newer previews or final releases without downgrades. Gradle preview eligibility follows the verified native numeric release-line rule. npm honors the latest distribution channel unless the installed version already exceeds it. Explicit package compatibility rules constrain recommendations without removing alternate candidates. Unparseable and yanked candidates remain recorded with reasons.

Use Python packaging for PEP 440, semver for SemVer ecosystems, and univers' native RubyGems implementation for Ruby. Implement Gradle's documented ordering independently; do not substitute Maven ordering or copy Renovate implementation code. Keep policy values in validated JSON and pass typed immutable policy into pure selection.

Wire current versions through registry lookups and Dockerfile annotation consumers. Expose candidate decisions in JSON without flooding table output. Preserve Docker tag/digest selection, configured mise requests and Nix references. Do not add registry requests solely to pretend metadata is complete, retry blocked Cargo metadata, introduce Node, or start another POC.

## Verification

1. Existing captured Gradle regression passes unchanged.
2. Offline public-adapter contracts cover PyPI, npm, Cargo, Gradle, Terraform, SwiftPM, Go and Ruby, including candidate counts and completeness.
3. Native captured Gradle eligibility agrees with production selection for the supported frozen cases.
4. CLI JSON and stale/table behavior agree with selected results; serialized decisions validate against JSON Schema 2020-12.
5. Existing Docker/mise/Nix, error handling, concurrency and installation contracts remain green on Python 3.10 and the current runtime.
6. Robot acceptance and routed QA gates run before integration; failures and unavailable metadata are reported explicitly.

## Implementation constraints

Gradle single-version ordering uses a Python adapter because univers provides Maven, not Gradle, semantics. Its comparison, validation and stability contracts are checked against 136 vectors captured from the pinned native APIs. Eight captured selection cases separately verify eligibility and complete candidate retention. Invalid comparison operands are retained but never passed to ordering. No Node runtime is added.

Policy resources are validated once as JSON Schema 2020-12 and converted to immutable typed values. Selection performs no environment or filesystem reads. Registry boundaries supply current versions and candidate completeness; JSON serialization exposes the resulting decisions.

## References

- [Accepted policy](../../../docs/adr/0002-preserve-candidates-and-use-explicit-update-eligibility.md)
- https://docs.gradle.org/current/userguide/single_versions.html#version_ordering
- https://github.com/renovatebot/renovate/blob/e698ff5201cf54060c41a32aa40470be1f6ddc86/lib/modules/versioning/gradle/compare.ts#L49-L218
- https://github.com/renovatebot/renovate/blob/e698ff5201cf54060c41a32aa40470be1f6ddc86/lib/modules/versioning/gradle/index.spec.ts#L7-L214
- https://github.com/renovatebot/renovate/blob/e698ff5201cf54060c41a32aa40470be1f6ddc86/lib/workers/repository/process/lookup/filter.ts#L166-L192
- https://github.com/renovatebot/renovate/blob/e698ff5201cf54060c41a32aa40470be1f6ddc86/lib/modules/versioning/regex/readme.md#L10-L28
- https://github.com/aboutcode-org/univers/blob/92b1a2498e60779775ac9351fd7c38a035f97eb1/src/univers/gem.py
