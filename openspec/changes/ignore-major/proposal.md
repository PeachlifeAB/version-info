# Optional major update suppression

## Why

Generated stale files may deliberately exclude major updates without changing the default report.

## What Changes

Add `--ignore-major` as a report filter. Hide only rows classified as major updates. Preserve unknown classifications and default output. Do not select alternative releases.

## Impact

CLI, shared report filtering, table, JSON and stale-file cleanup. No registry changes.
