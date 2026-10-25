*** Settings ***
Library    Process


*** Test Cases ***
Exact Allowances Are Generated And Applied Through The CLI
    ${result}=    Run Process
    ...    uv
    ...    run
    ...    pytest
    ...    tests/test_stale_allow_cli.py
    ...    --no-cov
    ...    -q
    ...    stderr=STDOUT
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}
