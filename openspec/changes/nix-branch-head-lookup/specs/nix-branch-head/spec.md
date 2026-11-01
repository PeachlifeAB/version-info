## ADDED Requirements

### Requirement: Branch-head comparison

The Nix scanner SHALL compare each locked GitHub revision with the head of the branch in the input's `original.ref`, or the repository default branch when no ref is declared.

#### Scenario: Locked revision behind the branch head

- **WHEN** the locked revision differs from the tracked branch head
- **THEN** the row SHALL be `update_available` with the branch head as latest

#### Scenario: Locked revision is the branch head

- **WHEN** the locked revision equals the tracked branch head
- **THEN** the row SHALL be `ok`

### Requirement: Single batched lookup with a credential

With a GitHub credential, the scanner SHALL resolve all GitHub flake inputs in one GraphQL request, chunked at 50 repositories.

#### Scenario: Many inputs

- **WHEN** a credential is available and the lock has several GitHub inputs
- **THEN** exactly one GraphQL request SHALL be made for up to 50 inputs and no per-input REST request

### Requirement: Credential-free fallback

Without a GitHub credential, the scanner SHALL resolve each branch head with `git ls-remote` and SHALL NOT call the GitHub API.

#### Scenario: No credential

- **WHEN** neither `GITHUB_TOKEN` nor a logged-in `gh` is available
- **THEN** each input SHALL be resolved by `git ls-remote` and no rate-limit warning SHALL be printed

#### Scenario: SwiftPM without a credential

- **WHEN** neither `GITHUB_TOKEN` nor a logged-in `gh` is available
- **THEN** SwiftPM tags SHALL be listed with `git ls-remote --tags` and the GitHub API SHALL NOT be called

### Requirement: gh-aware credential resolution

The CLI SHALL resolve the GitHub credential once at startup: `GITHUB_TOKEN` when set, else the output of `gh auth token` when `gh` is installed and logged in, else none. Setting `GITHUB_TOKEN` SHALL NOT be required when `gh` is logged in.

#### Scenario: gh logged in, no env token

- **WHEN** `GITHUB_TOKEN` is unset and `gh auth status` reports a logged-in account
- **THEN** the gh token SHALL authenticate GitHub requests and no "GITHUB_TOKEN not set" warning SHALL be printed

#### Scenario: Env token wins

- **WHEN** `GITHUB_TOKEN` is set
- **THEN** it SHALL be used and `gh` SHALL NOT be invoked

#### Scenario: Token is only sent to GitHub hosts

- **WHEN** a request targets a non-GitHub host
- **THEN** the credential SHALL NOT be attached
