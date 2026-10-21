# Context-aware registry recommendations

## Why

Registry-selected previews can conceal stable updates. Selecting before collecting versions loses candidate evidence and compatibility decisions.

## What Changes

- Preserve observed versions independently of eligibility and expose decisions in CLI JSON.
- Apply native ordering, stable promotion, explicit compatibility and downgrade protection through one selection owner.
- Preserve backend-specific Docker, mise and Nix behavior and Python 3.10 installation.

## Impact

Registry adapters, selection policy, JSON reporting and offline acceptance fixtures. No additional runtime or registry requests.
