*** Settings ***
Library    Process


*** Test Cases ***
Stale Output Contains Only Confirmed Updates
    ${result}=    Run Process
    ...    uv
    ...    run
    ...    pytest
    ...    tests/test_stale_confirmed_updates.py
    ...    tests/test_stale_only.py
    ...    tests/test_output_file.py
    ...    --no-cov
    ...    -q
    ...    stderr=STDOUT
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}
