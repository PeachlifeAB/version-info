*** Settings ***
Library    Process


*** Test Cases ***
Npm Compares Latest And Stable Channels
    ${result}=    Run Process
    ...    uv
    ...    run
    ...    pytest
    ...    tests/test_npm_stable_channel.py
    ...    tests/test_npm.py
    ...    tests/test_npm_pnpm.py
    ...    --no-cov
    ...    -q
    ...    stderr=STDOUT
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}
