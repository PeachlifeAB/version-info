*** Settings ***
Library    Process


*** Test Cases ***
Major Suppression Composes With Stale Files
    ${result}=    Run Process
    ...    uv
    ...    run
    ...    pytest
    ...    tests/test_ignore_major.py
    ...    tests/test_output_file.py
    ...    --no-cov
    ...    -q
    ...    stderr=STDOUT
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}
