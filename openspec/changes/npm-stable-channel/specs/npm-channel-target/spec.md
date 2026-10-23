## ADDED Requirements

### Requirement: Compare latest and stable channel targets

When a nonempty latest tag exists, the npm adapter SHALL compare stable and latest using the existing npm semantic version comparator. It SHALL use stable as the reported channel target only when stable is greater. It SHALL retain latest when stable is missing, empty, invalid, non-string, older or equal in semantic precedence. Other dist-tags SHALL NOT participate in this comparison. Existing release eligibility and missing-latest error handling SHALL remain unchanged.

#### Scenario: Higher stable channel

- **GIVEN** latest 2.16.0, stable 2.44.2 and beta 2.45.1
- **WHEN** checking from version 2.15.0
- **THEN** the selected update is 2.44.2

#### Scenario: Stable does not advance the target

- **GIVEN** stable is missing, invalid, equal to or older than latest
- **WHEN** npm metadata is processed
- **THEN** latest remains the reported target
