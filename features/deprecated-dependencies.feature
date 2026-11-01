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

  Scenario: An archived GitHub repository counts as deprecated
    Given a dependency whose GitHub repository is archived
    And a GitHub credential is available
    When version-info scans the project
    Then the dependency is reported as deprecated with the note "repository archived"
    And all repositories are checked in one batched GraphQL request

  Scenario: Archived status is not guessed without a credential
    Given a dependency hosted on GitHub
    And no GitHub credential is available
    When version-info scans the project
    Then the dependency keeps its normal state
