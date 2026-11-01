Feature: Deprecated dependencies
  Scenario: Report a deprecated pinned version from deps.dev
    Given a lockfile pinning a version deps.dev marks as deprecated
    When version-info scans the project
    Then the dependency is reported as deprecated with the registry's reason
    And it appears in stale output

  Scenario: A deps.dev failure never fails the scan
    Given deps.dev is unreachable
    When version-info scans the project
    Then the dependency keeps its normal state
