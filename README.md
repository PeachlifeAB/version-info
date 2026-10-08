# version-info

Scans your project dependencies and prints installed VS latest version numbers
in a human readable table or as json.

This is a hobby project tool for local version checking.
Dependabot and Renovate is recommended to use on server side for automatic PRs
and deep security audits.

## Usage

```bash
# Human readable table showing curr
uv run version-info /path/to/project

# JSON output for scripting
uv run version-info /path/to/project --json
uv run version-info . --json | jq '.[] | .rows[] | select(.state == "update_available")'
```

## Output

```text
Tools (mise)  2 tools, 1 update
NAME    CURRENT    LATEST    SOURCE
------  ---------  --------  ---------
gh      2.90.0     2.92.0    mise.toml
yq      4.53.2     4.53.2    mise.toml

Docker  10 images, 3 updates, 2 local, 1 registry issue
NAME                               CURRENT        LATEST         STATUS    SOURCE
---------------------------------  -------------  -------------  --------  ------------------
ai-db-pgbackrest                                                 local     docker-compose.yml
falkordb-server                    v4.18.1        v4.18.3        public    docker-compose.yml
openmemory-mcp                     latest         latest         public    docker-compose.yml
tailscale                          v1.96.5        v1.96.5        public    docker-compose.yml
ghcr.io/user/comfyui-mcp-server    v0.1.1                        private   docker-compose.yml
ghcr.io/open-webui/open-webui      main (b8095)   main (c2e47)   public    docker-compose.yml
```

The table is intentionally plain: no icons, glyphs, or legend.

- `CURRENT` and `LATEST` are version facts only — values like `1.2.3`, `v1.2.3`, `3.12-slim`, `main`,
  or `latest`. Operational outcomes belong in `STATUS`.
- `STATUS` terse reasons: `public`, `private`, `local`, `auth`, `rate`, `not found`, `timeout`, `error`.
  Omitted entirely when the section has no issues.
- `SOURCE` names the file that produced the row: `mise.toml`, `docker-compose.yml`, `Cargo.lock`, etc.

Color applies only to `CURRENT`: green means up-to-date, yellow means minor/patch behind,
red means major behind.

## Supported Ecosystems

| Ecosystem     | Marker files                                      |
| ------------- | ------------------------------------------------- |
| Docker        | `docker-compose.yml`, `compose.yml`, `Dockerfile` |
| Python (PyPI) | `uv.lock`, `requirements.txt`, `Pipfile.lock`     |
| Node (npm)    | `package-lock.json`                               |
| Go            | `go.mod`, `go.sum`                                |
| Rust (Cargo)  | `Cargo.lock`                                      |
| Ruby (Gems)   | `Gemfile.lock`                                    |
| Nix           | `flake.lock`                                      |
| SwiftPM       | `Package.resolved`                                |
| Terraform     | `.terraform.lock.hcl`                             |
| Tools (mise)  | `mise.toml`, `.mise.toml`, `.tool-versions`       |

## Scan Scope

Scans project lockfiles, manifests, runtime tools for external dependencies.

The CLI scans the target directory plus immediate child directories, supporting
simple monorepos while ignoring noise.

Default child directories excluded:

```text
__pycache__  build  dist  docs  examples  fixtures
node_modules  references  test  tests  vendor  archived  worktrees
```

Scanner selection is marker-driven — a scanner only runs when its marker file is present.

## Docker

Channel tags (`latest`, `stable`, `edge`, `nightly`) and branch tags (`main`, `master`) are
resolved via digest mapping.

1. Fetch the manifest digest for the channel tag.
2. Find the version tag (e.g. `v1.96.5`) that shares that digest — zero extra requests on Docker Hub.
3. If no version tag matches, use the channel tag as identity and compare local vs upstream digest
   for freshness.

Branch tags that don't align with a version release show a short digest suffix:

```text
ghcr.io/open-webui/open-webui   main (b8095)   main (c2e47)   public
```

No `docker run` or image content probing. Pure registry API.

### Local build artifacts and Dockerfile dependencies

Build-only Compose services (services with `build:` but no `image:`) are detected and shown with
`local` status. For example, a service `cognee-api` defined as:

```yaml
services:
  cognee-api:
    build:
      context: .
      dockerfile: docker/cognee-api/Dockerfile
```

Appears as:

```text
NAME        CURRENT   LATEST   STATUS  SOURCE
---------   -------   ------   ------  ------
cognee-api                     local   docker-compose.yml
```

For local build artifacts, you can add a **Dockerfile annotation** to enable version tracking:

```dockerfile
# version-info: datasource=pypi depName=cognee artifact=cognee-api
ARG COGNEE_VERSION=1.0.1
RUN pip install cognee==${COGNEE_VERSION}
```

Supported formats:

- `# version-info: datasource=pypi depName=<package> artifact=<service-name>`
- `# renovate: datasource=pypi depName=<package>` (artifact name inferred from service)

When an annotation is present, CURRENT shows the resolved ARG value and LATEST shows the registry's
latest version.

### Dockerfile installs fold into native ecosystem tables

Package installs from Dockerfile RUN commands (pip, npm, go, cargo, gem) appear in their native ecosystem
section, not in the Docker section. The SOURCE column shows `docker/<service>/<dockerfile>` so you can
trace the origin.

```text
Python (PyPI)  2 packages, 1 update
NAME       CURRENT              LATEST      STATUS   SOURCE
--------   -----------------    --------    ------   ------
cognee     >=1.0.9,<2.0.0     1.5.0         pinned   docker/cognee-api/Dockerfile
requests   unpinned             2.32.3      pinned   docker/api/Dockerfile
```

### Range and unpinned declarations

Packages declared with version ranges or without pins show their constraint as CURRENT instead of
an exact version. Freshness math is disabled for these rows since the constraint is not a version fact.

```text
NAME     CURRENT              LATEST      STATUS
------   -----------------    --------    ------
falkordb >=1.0.9,<2.0.0       1.5.0       pinned
requests unpinned            2.32.3      pinned
```

The `pinned` status indicates the constraint is declared but not a precise version.
These rows count as dependencies but not as update_available in the section summary.

## Mise

When `mise` is available, the scanner calls:

- `mise ls --current --installed --json --local` for the installed version.
- `mise outdated --local --json` for the latest version (one call for all tools).

If `mise` is unavailable, the declared version in config is used as a fallback with `not checked` status.

## Direct Dependencies Only

Scanners filter to direct dependencies to avoid flooding registries with transitive lockfile entries:

- **npm**: reads `dependencies`/`devDependencies` from the root package in `package-lock.json`.
- **Go**: prefers `go.mod` (direct deps, no `// indirect`) over `go.sum`.
- **Cargo**: cross-references `Cargo.lock` with `Cargo.toml`; excludes workspace-local crates.

## Environment

| Variable                   | Default | Description                                  |
| -------------------------- | ------- | -------------------------------------------- |
| `VERSION_INFO_TIMEOUT_S`   | `10`    | Network/exec timeout in seconds              |
| `VERSION_INFO_VERBOSE`     | `0`     | Set to `1` for scanner diagnostics on stderr |
| `VERSION_INFO_CONCURRENCY` | `4`     | Global cap on concurrent registry lookups    |
| `GITHUB_TOKEN`             | —       | Nix, SwiftPM and improved rate limits        |

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
Provided "AS IS", without warranties or conditions of any kind, subject to the license terms.
