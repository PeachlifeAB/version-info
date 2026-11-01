Feature: GitHub credential and branch-head lookups
  Scenario: A logged-in gh account is enough
    Given GITHUB_TOKEN is unset and gh is logged in
    When a Nix flake or SwiftPM scan runs
    Then the gh token authenticates GitHub requests
    And no GITHUB_TOKEN warning is printed

  Scenario: GITHUB_TOKEN wins over gh
    Given GITHUB_TOKEN is set
    When a scan runs
    Then gh is not invoked

  Scenario: Flake inputs are compared with their tracked branch head
    Given a flake lock pinned behind the head of the tracked branch
    When a Nix scan runs with a GitHub credential
    Then all inputs are resolved in one batched GraphQL request
    And the inputs are reported as update available

  Scenario Outline: Credential-free lookups use git
    Given neither GITHUB_TOKEN nor a logged-in gh is available
    When a <ecosystem> scan runs
    Then refs are resolved with git ls-remote
    And the GitHub API is not called
    Examples:
      | ecosystem |
      | Nix       |
      | SwiftPM   |
