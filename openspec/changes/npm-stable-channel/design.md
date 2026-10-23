# npm channel target

The npm adapter owns dist-tag interpretation. Reuse `compare_releases` with the existing npm policy, then pass the selected target into `registry_selection`. Preserve complete candidate lists and release eligibility.

Renovate retains npm dist-tags but defaults to respecting latest. This change intentionally differs by comparing latest and stable. Reference revision: a45ee254dc3a7d512f4467174fc9b5503bbf481a, inspected 2026-10-23.

- https://github.com/renovatebot/renovate/blob/a45ee254dc3a7d512f4467174fc9b5503bbf481a/lib/modules/datasource/npm/get.ts#L123-L126
- https://github.com/renovatebot/renovate/blob/a45ee254dc3a7d512f4467174fc9b5503bbf481a/lib/config/options/index.ts#L2156-L2161
- https://github.com/renovatebot/renovate/blob/a45ee254dc3a7d512f4467174fc9b5503bbf481a/lib/workers/repository/process/lookup/filter.ts#L152-L163

Missing latest remains an error. A malformed stable tag does not invalidate latest. No additional network request or dependency is required.
