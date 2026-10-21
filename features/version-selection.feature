Feature: Context-aware dependency update selection
  Registry adapters retain observed candidates independently of update eligibility.

  Scenario: Stable dependencies prefer available stable updates
    Given a stable dependency and registry candidates containing stable and preview updates
    When the project is scanned
    Then the latest eligible stable update is recommended
    And every observed candidate remains available with its decision reason

  Scenario: Preview dependencies can graduate to final releases
    Given a preview dependency and a newer final release
    When the project is scanned
    Then the final release is recommended without trapping the dependency on a preview label

  Scenario: Explicit compatibility is preserved
    Given a dependency with a configured compatibility suffix
    When a newer matching variant and an alternate variant are observed
    Then the matching variant is recommended
    And the alternate variant remains recorded as incompatible

  Scenario: Backend selections never recommend downgrades
    Given a backend-selected release older than the installed version
    When the project is scanned
    Then no downgrade is recommended
    And the observed backend release remains recorded

  Scenario: Partial metadata remains explicit
    Given a backend that exposes only its selected release or a page of tags
    When the project is scanned
    Then candidate coverage is reported as partial
    And missing candidate metadata is not fabricated

  Scenario: Missing comparable observations do not imply latest
    Given a registry response with no comparable versions
    When the project is scanned
    Then the lookup reports an error rather than an up-to-date recommendation

  Scenario: Existing non-release backends retain native semantics
    Given Docker variants, configured mise requests or Nix commit references
    When the project is scanned
    Then the existing backend-specific selection contract is preserved
