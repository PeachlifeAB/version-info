Feature: Optional major update suppression
  Scenario: Preserve smaller and unknown updates
    Given major, minor, patch and unclassifiable updates
    When ignore-major is enabled
    Then only known major updates are hidden

  Scenario: Remove a stale file with no matching updates
    Given only major updates and an existing stale file
    When stale output ignores major updates
    Then the stale file is removed
    And the report does not claim all dependencies are latest
