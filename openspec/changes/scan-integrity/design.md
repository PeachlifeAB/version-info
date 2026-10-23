# Scan integrity

Scanner exceptions propagate through concurrent workers to the CLI boundary. The boundary prints a diagnostic and exits before rendering or modifying report files. Verbose output retains the exception chain. Supplemental Dockerfile scanning follows the same failure path.

The npm adapter uses PyYAML `safe_load_all` instead of `safe_load`. Documents and workspace importers contribute direct dependencies. Package/version sets deduplicate identical observations without discarding version drift.

Section merging moves unchanged into its own module to keep CLI orchestration below 250 lines. Existing merging regressions remain applicable.

Evidence: the live pnpm lockfile has document starts at lines 1 and 183; zod is in the packages/ppie-recover importer. Sanitized fixtures reproduce this structure. The two original regressions remain unchanged.

PyYAML stream API: https://pyyaml.org/wiki/PyYAMLDocumentation#loading-yaml
