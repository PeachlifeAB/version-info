Feature: Explicit stale version allowances
  Scenario: Generate an allowance for an installed dependency
    Given an exact installed dependency and version
    When allow is requested with a reason of at least three words
    Then the CLI writes a validated allowance without duplicates

  Scenario: Reject a nonmatching request
    Given a misspelled dependency or a different installed version
    When allow is requested
    Then the command fails with the closest dependency and version suggestion
    And the allowance file remains unchanged

  Scenario Outline: Suppress only an exact allowed version
    Given a validated exact dependency and version allowance
    When a stale <format> report is requested
    Then the allowed dependency is absent
    And an empty report file is not created
    And an obsolete report file is removed
    Examples:
      | format |
      | table  |
      | JSON   |

  Scenario: Preserve other stale dependencies
    Given an allowance that does not match another stale dependency
    When a stale report is requested
    Then the other stale dependency remains visible

  Scenario: Reject invalid policy
    Given an allowance with a missing field, wildcard, range or short reason
    When a stale report is requested
    Then the command fails without modifying the existing report

  Scenario: Keep the full inventory visible
    Given a valid stale allowance
    When a report is requested without stale filtering
    Then the allowed dependency remains visible
