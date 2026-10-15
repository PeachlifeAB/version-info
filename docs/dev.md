# Developer notes

Internals and details that the README leaves out.

## Development tasks

Tasks run through mise (`mise.toml`):

| Task                   | Runs                                              |
| ---------------------- | ------------------------------------------------- |
| `mise run test`        | `pytest`                                          |
| `mise run lint`        | `ruff check` and `ruff format --check`            |
| `mise run lint:fix`    | `ruff check --fix` and `ruff format`              |
| `mise run typecheck`  | `mypy` and `pyright`                              |
| `mise run lint:all`    | lint, typecheck, deptry, gitleaks                 |
| `mise run ci`          | lint:all, semgrep, SBOM, test                     |

Scanners register in `version_info/scanners.py`. Each scanner has a `detect` marker check and
a `scan_section` function that returns one `Section`.

## Scan scope

`version_info/main.py` scans the target directory plus its immediate child directories,
skipping hidden directories and these names:

```text
__pycache__  build  dist  docs  examples  fixtures
node_modules  references  test  tests  vendor  archived  worktrees
```

Sections with the same title are merged. A dependency found in several files keeps one row
with `source` listing each file and a `+N` suffix when the versions agree. When versions
differ, every row is kept.

## Direct dependencies only

Scanners filter to direct dependencies, so lockfile transitive entries do not flood registries:

- **npm**: reads `dependencies` and `devDependencies` of the root package in `package-lock.json`.
  Without `package-lock.json`, reads `pnpm-lock.yaml`: the v9 `importers["."]` section, or the
  v6 top-level sections. Peer suffixes are stripped; `link:`, `file:` and `:` specifiers are skipped.
- **Go**: prefers `go.mod` (no `// indirect`) over `go.sum`.
- **Cargo**: cross-references `Cargo.lock` with `Cargo.toml`; excludes workspace crates.
- **Gradle**: reads coordinates from `gradle.lockfile`. Latest release comes from Maven Central
  `maven-metadata.xml` (`<release>`).

## Mise

When `mise` is available, the scanner calls:

- `mise ls --current --installed --json --local` for the installed version.
- `mise outdated --local --json` for the latest version (one call for all tools).

Without `mise`, the declared version is used with `not checked` status.

Files read: `mise.toml`, `.mise.toml`, `.tool-versions`.

## Docker

Channel tags (`latest`, `stable`, `edge`, `nightly`) and branch tags (`main`, `master`) resolve
through digest mapping:

1. Fetch the manifest digest for the channel tag.
2. Find the version tag (for example `v1.96.5`) with the same digest. Docker Hub needs no extra requests.
3. If no version tag matches, use the channel tag and compare local and upstream digests.

Branch tags that match no release show a short digest suffix:

```text
ghcr.io/open-webui/open-webui   main (b8095)   main (c2e47)   public
```

There is no `docker run` and no image content probing. Lookups use only registry APIs.

### Build-only Compose services

Services with `build:` and no `image:` show `local` status:

```yaml
services:
  cognee-api:
    build:
      context: .
      dockerfile: docker/cognee-api/Dockerfile
```

```text
NAME        CURRENT   LATEST   STATUS  SOURCE
---------   -------   ------   ------  ------
cognee-api                     local   docker-compose.yml
```

Add a Dockerfile annotation to track the version:

```dockerfile
# version-info: datasource=pypi depName=cognee artifact=cognee-api
ARG COGNEE_VERSION=1.0.1
RUN pip install cognee==${COGNEE_VERSION}
```

Supported forms:

- `# version-info: datasource=pypi depName=<package> artifact=<service-name>`
- `# renovate: datasource=pypi depName=<package>` (artifact name inferred from the service)

With an annotation, `CURRENT` shows the resolved `ARG` value and `LATEST` the registry's latest version.

### Dockerfile installs

Package installs in Dockerfile `RUN` commands (pip, npm, go, cargo, gem) appear in their native
ecosystem section. `SOURCE` shows `docker/<service>/<dockerfile>`:

```text
Python (PyPI)  2 packages, 1 update
NAME       CURRENT              LATEST      STATUS   SOURCE
--------   -----------------    --------    ------   ------
cognee     >=1.0.9,<2.0.0       1.5.0       pinned   docker/cognee-api/Dockerfile
requests   unpinned             2.32.3      pinned   docker/api/Dockerfile
```

### Ranges and unpinned declarations

Constraints such as `>=1.0.9,<2.0.0` or no pin at all appear as `CURRENT`. Freshness is not
computed for them, and they show `pinned` status. They count as dependencies, not as updates.

## Freshness values

Rows carry a `freshness` field in JSON: `latest`, `patch_behind`, `minor_behind`,
`major_behind`, `not_checked` or `uncomparable`. `--stale` keeps everything except `latest`.
