*** Settings ***
Library    Process


*** Test Cases ***
GitHub Credential And Branch Head Lookups Behave As Specified
    ${result}=    Run Process
    ...    uv
    ...    run
    ...    pytest
    ...    tests/test_github_auth.py
    ...    tests/test_nix_branch_head.py
    ...    tests/test_nix.py
    ...    tests/test_swiftpm.py
    ...    --no-cov
    ...    -q
    ...    stderr=STDOUT
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}
