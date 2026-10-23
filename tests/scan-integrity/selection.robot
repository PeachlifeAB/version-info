*** Settings ***
Library    Process


*** Test Cases ***
Failed Scans Preserve Reports And Pnpm Streams Are Scanned
    ${result}=    Run Process
    ...    uv
    ...    run
    ...    pytest
    ...    tests/test_scan_integrity.py
    ...    tests/test_cli.py
    ...    tests/test_output_file.py
    ...    --no-cov
    ...    -q
    ...    stderr=STDOUT
    Should Be Equal As Integers    ${result.rc}    0    ${result.stdout}
