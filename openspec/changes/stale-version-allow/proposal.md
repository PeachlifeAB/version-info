# Explicit stale version allowances

Generate project-root `.stale-versions-allow` using `version-info allow <dependency> <version> --reason "<reason>" [--path <root>]`.

Require an exact installed dependency/version match and at least three whitespace-separated reason words. Suggest the closest installed pair on mismatch without writing.

Apply validated allowances only to `--stale`. Preserve other dependencies and full inventory output. Remove obsolete report files when no unsuppressed updates remain.
