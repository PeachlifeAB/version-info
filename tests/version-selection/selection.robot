*** Settings ***
Library    Process


*** Test Cases ***
Registry Selection Preserves Candidates And Produces Consistent CLI Output
    ${result}=    Run Process
    ...    uv
    ...    run
    ...    pytest
    ...    tests/test_selection_adapters.py
    ...    tests/test_selection_cli.py
    ...    tests/test_version_ranking_gradle.py
    ...    tests/test_selection_native.py
    ...    tests/test_release_selection.py
    ...    tests/test_gradle_versioning.py
    ...    --no-cov
    ...    -q
    ...    cwd=${EXECDIR}
    ...    stderr=STDOUT
    Log    ${result.stdout}
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}
