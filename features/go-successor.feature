Feature: Go module successors
  Scenario: Report a newer major version published under the next module path
    Given a go.mod requiring github.com/o/lib at v1.4.0
    And the Go proxy serves github.com/o/lib/v2 at v2.1.0
    When version-info scans the project
    Then the dependency is reported as an update to v2.1.0 at path github.com/o/lib/v2

  Scenario: Probe the next major of a gopkg.in module
    Given a go.mod requiring gopkg.in/yaml.v3
    When version-info probes for a newer major
    Then it asks the Go proxy for gopkg.in/yaml.v4

  Scenario: Surface a deprecation notice from the latest go.mod
    Given the latest go.mod of a required module starts with a Deprecated comment
    When version-info scans the project
    Then the dependency row carries that notice

  Scenario: Ignore a missing next major
    Given the Go proxy has no module at the next major path
    When version-info scans the project
    Then the dependency keeps its normal state
