## ADDED Requirements

### Requirement: CLI-managed exact allowances

The CLI SHALL generate `.stale-versions-allow` as a JSON array of dependency, version and reason records. Names and versions SHALL match installed records exactly. Reasons SHALL contain at least three whitespace-separated words.

#### Scenario: Add an installed version

- **WHEN** an exact installed dependency and version are allowed with a valid reason
- **THEN** the CLI SHALL create or update that pair without duplicating it or discarding other records

#### Scenario: Reject a mismatch

- **WHEN** no installed pair matches the request
- **THEN** the CLI SHALL fail without writing and suggest the closest installed pair when one exists

### Requirement: Validated shared stale filtering

The CLI SHALL apply project-root allowances across scanned ecosystems and subprojects only with `--stale`.

#### Scenario: All stale rows are allowed

- **WHEN** every stale row has an exact allowance
- **THEN** no stale output file SHALL be created and an existing output file SHALL be removed

#### Scenario: Invalid policy

- **WHEN** a policy contains invalid JSON, missing fields, wildcards, ranges or fewer than three reason words
- **THEN** the CLI SHALL fail without modifying the existing report

#### Scenario: A different version or dependency remains stale

- **WHEN** a row's dependency or installed version differs from an allowance
- **THEN** the row SHALL remain subject to normal stale reporting
