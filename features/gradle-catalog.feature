Feature: Gradle version-catalog library inventory
  Scenario: Discover Android library versions
    Given a project with gradle/libs.versions.toml
    When version-info scans the project
    Then direct and referenced library versions are reported as declared versions
    And AndroidX metadata can be retrieved from Google Maven
    And existing Gradle lockfile inventory remains available
