## ADDED Requirements

### Requirement: Observable context-aware release selection

The CLI SHALL retain every observed version independently of eligibility. Stable dependencies SHALL prefer eligible stable updates. Preview dependencies SHALL permit stable promotion. Recommendations SHALL preserve explicit compatibility values and SHALL NOT recommend downgrades. JSON selection records SHALL validate against JSON Schema 2020-12 and declare candidate completeness.

#### Scenario: Stable recommendation retains previews

- **GIVEN** a stable dependency and observed stable and preview updates
- **WHEN** its project is scanned
- **THEN** the latest eligible stable update is recommended
- **AND** every observed candidate remains recorded with its decision reason

#### Scenario: Preview graduates to final

- **GIVEN** a preview dependency and a newer eligible final release
- **WHEN** its project is scanned
- **THEN** the final release can be recommended without a preview-family preference

#### Scenario: Compatibility separates eligibility from retention

- **GIVEN** an explicit package compatibility rule and alternate variants
- **WHEN** its project is scanned
- **THEN** the recommendation preserves the installed compatibility value
- **AND** alternate variants remain recorded as incompatible

#### Scenario: Partial or incomparable observations remain explicit

- **GIVEN** a selected-release response, partial tag page or unclassified versions
- **WHEN** its project is scanned
- **THEN** absent metadata is not fabricated
- **AND** incomplete collections and unclassified candidates remain observable
- **AND** no comparable observations produce an error rather than an up-to-date claim

#### Scenario: Backend contracts remain intact

- **GIVEN** Docker variants, configured mise requests or Nix commit references
- **WHEN** its project is scanned
- **THEN** native backend-specific selection remains unchanged
- **AND** installation remains supported on Python 3.10 without Node
