Feature: Compare npm release channel targets
  Scenario: Stable is newer than latest
    Given npm latest is 2.16.0 and stable is 2.44.2
    And beta is 2.45.1
    When checking updates from 2.15.0
    Then the selected update is 2.44.2

  Scenario: Stable cannot improve latest
    Given stable is missing, invalid, equal to or older than latest
    When checking npm updates
    Then latest remains the reported channel target
