## ADDED Requirements

### Requirement: Optional major suppression

The CLI SHALL accept `--ignore-major`, disabled by default. The report SHALL hide only rows classified as `major_behind` when enabled, in table and JSON output. It SHALL NOT select an alternative release. Unknown classifications SHALL remain unless another filter excludes them.

#### Scenario: Filter known majors

- **GIVEN** major, minor, patch and unclassifiable updates
- **WHEN** ignore-major is enabled
- **THEN** only the known major-update rows are hidden

### Requirement: Stale file consistency

Major suppression SHALL compose with confirmed-update-only stale filtering. File presence SHALL reflect the same filtered rows as the report. Empty stale results SHALL remove an existing output file. Text output SHALL say `No matching updates.` when major suppression is active rather than claiming all dependencies are latest.

#### Scenario: Major-only stale file

- **GIVEN** only major updates and an existing output file
- **WHEN** stale output ignores majors
- **THEN** the output file is removed
- **AND** JSON output remains valid
