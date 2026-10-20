*** Settings ***
Library    Process

*** Test Cases ***
Gradle Catalog Scanner Contract
    ${result}=    Run Process    uv    run    pytest    tests/test_gradle_catalog.py    --no-cov
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}\n${result.stderr}
