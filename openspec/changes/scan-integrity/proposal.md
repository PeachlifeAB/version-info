# Trustworthy stale reports

## Why

A failed scanner is currently discarded, allowing a successful empty report to claim dependencies are current and delete a previous report. Multi-document pnpm lockfiles trigger this failure.

## What Changes

Surface scanner exceptions at the CLI boundary. Exit unsuccessfully before rendering or modifying report files. Parse every pnpm YAML document and every workspace importer, preserving distinct locked versions.

## Impact

CLI scan orchestration and npm lockfile parsing. Move unchanged section-merging policy out of the oversized CLI module. No dependency or release-selection changes.
