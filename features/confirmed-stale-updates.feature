Feature: Confirmed stale updates
  Scenario: Only confirmed updates appear in stale output
    Given dependencies with confirmed updates and unchecked local or failed lookups
    When stale table or JSON output is requested
    Then only dependencies with confirmed available updates are shown
