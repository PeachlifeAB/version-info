## Context

`registry_nix._github_latest_commit` requests `/commits/{locked_rev}`, which returns the locked commit itself. `NixFlakeDep` drops `original.ref`. `util_http.get_text` reads `GITHUB_TOKEN` per request; the Nix and SwiftPM scanners print a warning when it is unset, even if `gh` is logged in.

## Decisions

- **Credential at the edge.** A small `github_auth` module resolves the token once (`GITHUB_TOKEN`, else `gh auth token` with the shared exec timeout, else none) and `util_http` consumes the resolved value. Scanners stop reading the environment. Alternative rejected: reading `gh`'s `hosts.yml`, which may hold the token in the keyring.
- **GraphQL batch.** One aliased query per chunk of 50: `rN: repository(owner, name) { ref(qualifiedName: "refs/heads/<ref>") { target { oid } } }`, or `defaultBranchRef` when no ref is declared. Failed aliases map to per-row errors without failing the section.
- **`git ls-remote` fallback.** One subprocess per input via the existing exec utility with the shared timeout, bounded by `--concurrency`. Needs no API quota.
- **Shared ref lookup.** `github_refs.ls_remote` serves Nix heads and SwiftPM tags; both use the same credential gate (`github_token()`).
- **Warnings removed.** Both rate-limit warnings go; the unauthenticated path is no longer rate limited. `--verbose` reports which credential source was used.
- Non-branch refs (tags, revs) in `original.ref` resolve through `git ls-remote` in both paths; GraphQL handles branches only.

## Risks

- `gh auth token` is a subprocess at startup: skip it when `GITHUB_TOKEN` is set and tolerate absence or failure.
- GraphQL node limits: chunking at 50 stays well under them.
