# Compare npm latest and stable channels

## Why

Some packages advance stable while latest remains unchanged. Using latest alone hides available stable updates.

## What Changes

Use stable as the reported npm channel target only when its semantic version is greater than latest. Preserve latest on ties or missing, invalid or older stable tags. Preserve existing candidate eligibility rules.

## Impact

One comparison at the npm registry boundary. No report, scanner or other ecosystem changes.
