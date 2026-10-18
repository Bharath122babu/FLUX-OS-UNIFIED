# FLUX//OS v0.4.0 — Project Runtime Integration

**Implementation scope:** upgrades v0.3.1 while preserving a single authoritative FLUX kernel and one gateway.

- New `project_revisions` and `project_heads` tables. Accepted revision promotion and artifact commit occur in one SQLite `BEGIN IMMEDIATE` transaction; two concurrent writers from the same expected project revision cannot both advance the head.
- New `Memory.project_head` and `project_history`, verified against the accepted artifact's sealed file hashes before returning data. Subsequent Gemma API runs load the last **accepted** project files into a fresh private candidate, and witness the accepted prior output as an input.
- New API routes: `GET /api/projects/{project_id}` and `GET /api/projects/{project_id}/export` (accepted ZIP only). `POST /api/gemma/run` accepts a stable `project_id`.
- Added `edit_file` exact-match tool and bounded `search_code` tool with mediated dependency tracking.
- New process-level black-box Python CLI acceptance specification, `acceptance/cases.json`, executed in an isolated Docker CLI process without importing candidate code into a trusted unittest interpreter. Trusted host compares exit code and exact stdout. Missing Docker/config -> unverified draft.
- Project acceptance requires a black-box report with an operator contract hash and exact candidate file manifest hash. Existing v0.3 legacy unittest runner stays available for non-project compatibility; it is **not** eligible to advance an accepted project head.
- Added project identity, accepted project viewer, and ZIP export in local browser UI.
- 86 local unit/integration/mocked-boundary tests passed. Original 75 also passed.

## Remaining blockers

Live Gemma test, real Docker black-box execution/security assessment, JS and browser tests, durable model sessions, multi-user authentication, and fair comparative Gemma benchmark are not done. Local API is not intended for exposure on the public internet. The engine only tracks reads mediated by its tool layer.
