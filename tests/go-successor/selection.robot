*** Settings ***
Library    Process


*** Test Cases ***
Go Successors Are Reported
    ${result}=    Run Process
    ...    uv
    ...    run
    ...    pytest
    ...    tests/test_go.py
    ...    tests/test_stale_confirmed_updates.py
    ...    --no-cov
    ...    -q
    ...    stderr=STDOUT
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}
