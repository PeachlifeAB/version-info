## ADDED Requirements

### Requirement: Confirmed stale output

Stale output SHALL include only dependencies with a confirmed newer eligible version available. Local, unchecked, failed and incomparable observations SHALL NOT be classified as stale. Normal output SHALL retain these observations. Table, JSON and output-file behavior SHALL use the same filter.

#### Scenario: Unknown is not stale

- **GIVEN** dependencies with confirmed updates and local or failed lookups
- **WHEN** stale output is requested
- **THEN** only confirmed updates are included
- **AND** normal output retains every observation
