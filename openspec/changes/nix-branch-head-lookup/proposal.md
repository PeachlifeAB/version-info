# Nix branch-head lookup with gh-aware credentials

Report Nix flake updates by comparing each locked revision with the head of the branch the input tracks. The current lookup requests the locked revision itself, so it can never report an update.

Resolve all GitHub flake inputs in one GraphQL request when a GitHub credential is available. Fall back to `git ls-remote` per input when none is.

Resolve the GitHub credential once at the edge: `GITHUB_TOKEN` when set, otherwise the logged-in `gh` account (`gh auth token`). Logging in with `gh` is sufficient; setting `GITHUB_TOKEN` is not required. Drop the "GITHUB_TOKEN not set" warning from the Nix and SwiftPM scanners.

Apply the same credential and `git ls-remote` fallback to SwiftPM tag lookups, so every GitHub-backed scanner behaves alike. The credential is shared through `util_http`, and git ref resolution through one `github_refs` module.
