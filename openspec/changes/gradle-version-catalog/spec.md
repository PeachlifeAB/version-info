# Gradle version-catalog inventory

## Contract

Discover `gradle/libs.versions.toml` at the scan root without executing Gradle.
Report library coordinates using string shorthand, `module`, or `group` and `name`.
Resolve direct string versions and references into `[versions]` string values.
Skip versionless libraries, unresolved references, rich constraints and plugins.
Classify catalog rows as `declared_manifest`; preserve lockfile rows as `resolved_lockfile`.
Try Google Maven only after Maven Central returns HTTP 404.
Preserve the existing Python 3.10 minimum using conditional Tomli installation.

## References

- https://docs.gradle.org/current/userguide/version_catalogs.html
- https://developer.android.com/build/remote-repositories
- https://github.com/hukkin/tomli#building-a-tomlitomllib-compatibility-layer

## Verification

- `uv run pytest tests/test_gradle_catalog.py tests/test_gradle.py`
- `uv run pytest`
- `uv run mypy`
- `uv run pyright`
