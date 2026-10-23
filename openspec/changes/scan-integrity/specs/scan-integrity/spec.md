## ADDED Requirements

### Requirement: Failed scans cannot produce successful reports

If scanner detection or execution raises an exception, the CLI SHALL exit nonzero and print a diagnostic without requiring verbose mode. It SHALL NOT claim all dependencies are current, emit a successful partial report, create, replace or delete the output file. This contract SHALL apply to registered scanners and supplemental Dockerfile dependency scanning.

#### Scenario: Preserve a previous report

- **GIVEN** a malformed dependency file and an existing stale report
- **WHEN** stale output is requested
- **THEN** the command exits unsuccessfully with a diagnostic
- **AND** the report remains unchanged

### Requirement: pnpm YAML streams and workspace dependencies

The npm adapter SHALL parse every document in a pnpm YAML stream using the dependency's safe stream parser. It SHALL inspect direct dependencies in every workspace importer, deduplicate identical package versions and preserve distinct locked versions. It SHALL retain support for existing single-document pnpm formats. Parse errors SHALL propagate to CLI scan handling.

#### Scenario: Application dependencies in a later document

- **GIVEN** package-manager and application lockfile documents
- **WHEN** npm dependencies are scanned
- **THEN** application dependencies are checked
- **AND** workspace importers are included
