# version-info

Lists the versions your project depends on next to the latest published version, as a
table or JSON.

A local version check for personal projects. For automatic pull requests and security
audits on a server, use Dependabot or Renovate.

## Quick start

```bash
version-info
```

```table
NAME    CURRENT    LATEST    SOURCE
------  ---------  --------  ---------
gh      2.90.0     2.92.0    mise.toml
yq      4.53.2     4.53.2    mise.toml
```

# Installation

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
uv tool install git+https://github.com/PeachlifeAB/version-info
```

## Commands

```text
version-info [PATH] [options]
```

| Flags                 | Description                          |
| --------------------- | ------------------------------------ |
| `PATH`                | Directory to scan                    |
| `--json`              | Print JSON instead of tables.        |
| `--stale`             | Show just stale dependencies         |
| `-o`, `--output-file` | Write output to a file.              |
| `--concurrency N`     | Max concurrent registry lookups.     |
| `--timeout SECONDS`   | Network and command timeout.         |
| `--verbose`           | Print scanner diagnostics to stderr. |
| `--version`           | Print the version and exit.          |

With `--stale`, `--output-file` writes nothing when every row is latest.

## Scripting

```bash
version-info . --json | jq -r '.sections[].rows[] | select(.state == "update_available") | .name'
version-info . --stale --json -o stale.json
```

Environment variables and their defaults are listed in [`.env.example`](.env.example).
Command-line options win over environment variables.

## Supported

| Ecosystem    | Marker files                                      |
| ------------ | ------------------------------------------------- |
| Docker       | `docker-compose.yml`, `compose.yml`, `Dockerfile` |
| Python       | `uv.lock`, `requirements.txt`, `Pipfile.lock`     |
| Node         | `package-lock.json`, `pnpm-lock.yaml`             |
| Go           | `go.mod`, `go.sum`                                |
| Rust         | `Cargo.lock`                                      |
| Ruby         | `Gemfile.lock`                                    |
| Gradle       | `gradle.lockfile`, `gradle/libs.versions.toml`                                 |
| Nix          | `flake.lock`                                      |
| SwiftPM      | `Package.resolved`                                |
| Terraform    | `.terraform.lock.hcl`                             |
| Tools (mise) | `mise.toml`, `.mise.toml`, `.tool-versions`       |

Gradle catalogs report library versions declared directly or through `version.ref`.
Maven lookups try Maven Central, then Google Maven on HTTP 404. Catalog and lockfile
rows remain separate. Plugins, rich version constraints, versionless libraries and
custom catalog paths are not inventoried.
Docker image resolution, Dockerfile install detection and scanner internals are described
in [`docs/dev.md`](docs/dev.md).

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
Provided "AS IS", without warranties or conditions of any kind, subject to the license terms.
