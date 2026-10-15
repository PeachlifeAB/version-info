# version-info

Lists the versions your project depends on next to the latest published version, as a
table or JSON.

A local version check for personal projects. For automatic pull requests and security
audits on a server, use Dependabot or Renovate.

## Quick start

```bash
git clone git@github.com:PeachlifeAB/version-info.git
cd version-info
uv sync

uv run version-info /path/to/project
```

Show only what is behind:

```bash
uv run version-info /path/to/project --stale
```

## Commands

```text
version-info [PATH] [options]
```

| Option                  | Default | Effect                                                                  |
| ----------------------- | ------- | ----------------------------------------------------------------------- |
| `PATH`                  | `.`     | Directory to scan. Its immediate child directories are scanned too.     |
| `--json`                | off     | Print JSON instead of tables.                                           |
| `--stale`               | off     | Show only rows not confirmed latest, including unchecked rows.          |
| `-o`, `--output-file`   | none    | Also write the output to this file. See below.                          |
| `--concurrency N`       | `16`    | Maximum concurrent registry lookups.                                    |
| `--timeout SECONDS`     | `10`    | Network and command timeout.                                            |
| `--verbose`             | off     | Print scanner diagnostics to stderr.                                    |
| `--version`             |         | Print the version and exit.                                             |

With `--stale`, `--output-file` writes nothing when every row is latest, and removes an
existing file. Table mode then prints `All dependencies are latest.` to stderr, so stdout
stays empty.

Scripting:

```bash
version-info . --json | jq -r '.sections[].rows[] | select(.state == "update_available") | .name'
version-info . --stale --json -o stale.json
```

Environment variables and their defaults are listed in [`.env.example`](.env.example).
Command-line options win over environment variables.

## Output

```text
Tools (mise)  2 tools, 1 update
NAME    CURRENT    LATEST    SOURCE
------  ---------  --------  ---------
gh      2.90.0     2.92.0    mise.toml
yq      4.53.2     4.53.2    mise.toml
```

- `CURRENT` and `LATEST` hold version values only. Problems appear in `STATUS`.
- `STATUS` shows `public`, `private`, `local`, `pinned`, `auth`, `rate`, `not found`,
  `timeout` or `error`. It is omitted when a section has no issues.
- `SOURCE` names the file that produced the row.
- Color applies to `CURRENT` only: green is up to date, yellow is minor or patch behind,
  red is major behind.

## Supported ecosystems

| Ecosystem     | Marker files                                                 |
| ------------- | ------------------------------------------------------------ |
| Docker        | `docker-compose.yml`, `compose.yml`, `Dockerfile`            |
| Python (PyPI) | `uv.lock`, `requirements.txt`, `Pipfile.lock`                |
| Node (npm)    | `package-lock.json`, `pnpm-lock.yaml`                        |
| Go            | `go.mod`, `go.sum`                                           |
| Rust (Cargo)  | `Cargo.lock`                                                 |
| Ruby (Gems)   | `Gemfile.lock`                                               |
| Gradle        | `gradle.lockfile`                                            |
| Nix           | `flake.lock`                                                 |
| SwiftPM       | `Package.resolved`                                           |
| Terraform     | `.terraform.lock.hcl`                                        |
| Tools (mise)  | `mise.toml`, `.mise.toml`, `.tool-versions`                  |

Only direct dependencies are reported. Scanner selection is marker-driven: a scanner runs
only when its marker file exists.

Docker image resolution, Dockerfile install detection and scanner internals are described
in [`docs/dev.md`](docs/dev.md).

## Development

```bash
uv sync
mise run ci
```

See [`docs/dev.md`](docs/dev.md) for tasks, scanner internals and the registry details.

## License

Licensed under the [Apache License, Version 2.0](LICENSE).
Provided "AS IS", without warranties or conditions of any kind, subject to the license terms.
