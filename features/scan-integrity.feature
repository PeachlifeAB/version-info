Feature: Trustworthy stale reports
  Scenario: A scanner fails
    Given a detected dependency file cannot be parsed
    And a stale output file already exists
    When stale output is requested
    Then the command exits unsuccessfully with a diagnostic
    And the existing output file is preserved
    And no all-current message is printed

  Scenario: A pnpm workspace lockfile has multiple YAML documents
    Given separate package-manager and application lockfile documents
    When npm dependencies are scanned
    Then workspace application dependencies are checked
    And distinct locked versions remain visible
