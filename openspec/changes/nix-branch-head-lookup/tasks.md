## 1. Credential resolution

- [x] 1.1 Add edge-resolved GitHub credential (`gh auth token`, else `GITHUB_TOKEN`, else none) consumed by `util_http`; remove both rate-limit warnings.

## 2. Branch-head lookup

- [x] 2.1 Parse `original.ref` and compare against branch head via batched GraphQL (chunked at 50), with `git ls-remote` fallback; SwiftPM tags use the same credential gate and fallback.
- [x] 2.2 Update `tests/test_nix.py` mocks and add tests for the fallback, gh credential and chunking.

## 3. Verify

- [x] 3.1 Add Gherkin feature and Robot test; update README and `.env.example` (`GITHUB_TOKEN` optional, `gh` login sufficient); run project gates.
