# Design

## Ownership

- `cli.py`: scan and allow argument contracts.
- `stale_allow.py`: typed allowances, schema validation, exact matching, suggestions and serialization.
- `main.py`: resolve project policy once, scan, then generate an allowance or filter before rendering.
- `data/stale-allow.schema.json`: JSON Schema Draft 2020-12.

The requested project root owns one policy covering its scanned children and all ecosystems. Identity is the literal dependency name and current version, without normalization. Old unmatched records remain harmless; validation against installed versions occurs when adding a record, not when scanning.

Invalid files and nonmatching requests fail before report mutation. Missing policy means no allowances. The allow command updates an existing pair's reason, preserving unrelated records. Fuzzy matching uses Python's standard-library difflib for suggestions only.

## Prior art

Inspected 2026-10-25:

- IBM/audit-ci (297 stars, updated 13 days ago): structured allowlist records with notes and expiry; `lib/allowlist.ts` and `lib/nsp-record.ts`.
- renovatebot/renovate (22,885 stars, updated 2026-10-25): dependency filters and current-version matching; `lib/config/options/index.ts`.

These tools permit broader suppression. This contract requires exact identity and a reason; no external runtime or fuzzy-matching dependency is needed. Existing jsonschema validates the policy.
