# FLUX//OS 0.6.0 — Multi-agent shared-memory correctness

**Upgraded from:** v0.5.0 backend-only release (104 tests). Existing test principals used for coordinator-driven fixture changes were explicitly given the `coordinator` role to preserve intentional user/requirement updates under the new fail-closed fact-write contract.

**Changes:** agent writes require an expected fact version; atomic JSON object field patches, per-path preimage checks, source-read-manifest validation, negative read dependencies, explicit unverified/conflicted claims, classification-filtered project revision history, explicit interrupted job fencing, extra stress simulation.

**No extra LLM planner, no second memory store, no CRDT dependency.** SQLite remains the sole causal state authority.

## Final integration follow-up

- Retained the tested Windows path, byte/hash, private-copy, and sealed-snapshot relocation/cleanup fixes from the GitHub v0.5 branch.
- Connected Gemma to bounded project-scoped shared-note reads, conditional patches, and append-only claim tools. Child workers inherit the parent memory namespace.
- Added exact-field read preconditions and atomic post-write receipts so own edits do not cause self-staleness or silently accept another worker's later write.
- Fenced shared-note and claim mutations against both worker and parent job ownership/generation in their SQLite write transaction.
- Added strict version-number validation, authorization before reporting secret CAS details, bounded read sets, and integrity checks on stored claim payloads.
- Added a project memory inspection endpoint, `GEMMA_MODEL` configuration, a credential-safe readiness script, and a real Docker/scripted-model API smoke check.

Local Windows results: 159 passed, 3 symlink-privilege skips, 0 failed. See `FINAL_VERIFICATION_v0.6.0.md` for verification scope.

**Not complete:** automated repair, faithful semantic conflict detection, robust tool execution recovery, distributed shared memory, full codebase scale, MCP and live model benchmarking remain open. Notes and claims are unverified coordination data; they do not authorize code acceptance. All model-loop tests use mocks or a scripted model until a real credential is supplied. No measured Gemma-performance improvement is claimed.
