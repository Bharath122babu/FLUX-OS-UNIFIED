> **Historical document (pre-v0.5.0).** For current backend release and security guarantees, read `README.md`, `docs/RELEASE_NOTES_v0.5.0.md`, and `docs/SECURITY.md` first.

# FLUX//OS — Final Release Audit v0.3.1

**Scope:** Code review and locally executed regression tests of the original
`FLUX-OS-UNIFIED-v0.3.0.zip`, followed by narrow corrective maintenance.
**Decision:** Suitable for a controlled, loopback, trusted-coordinator demo;
**NOT** approved for internet-facing deployment, untrusted tenants, confidential
workloads, or unsupported claims of improved Gemma benchmark scores.

## Objective and frozen architecture

One Gemma tool-use loop -> mediated, private workspace tools -> one
`UnifiedGate` -> one causal SQLite state kernel. One authority owner. No
second supervisor, memory source of truth, prediction scheduler or RL router.

## Dead-code and release-hygiene results

- Static AST inspection found unused imports in `agent.py`, `api.py`,
  `demo.py`, `gateway.py`, and `unified_demo.py`. Removed them.
- Removed unused `_validate(seen=...)` parameter; retained `memo` for
  iterative proof evaluation. Kept all live CLI entrypoints and both
  distinct demo functions; they are invoked by the CLI or tests.
- Removed import-time `app=create_app(...)` side effect; CLI constructs
  the service explicitly. For embedding use `create_app(home)`.
- Removed two **old** binary dashboard screenshots that did not depict
  the current version. Preserved original audits and release histories for
  provenance rather than silently deleting them.
- Recomputed `SOURCE_SHA256.json` so it describes this final archive.

## Verified code fixes

1. **Atomic source registration:** `register_source_tree` now compares the
   current fact and commits a changed version in one `BEGIN IMMEDIATE` transaction.
   A reusable `_put_fact_tx` helper prevents divergent fact-invalidation behavior.
2. **Safe snapshot sealing:** publication enumerates and checks admissible files
   via `Workspace.snapshot_to`, rather than blindly copying a directory.
3. **Structured invalid-candidate result:** unsafe symlinks and forbidden
   workspaces return `REJECT/COMMIT_REJECTED` instead of uncaught errors.
4. **Resource bounds:** file reads no longer load whole files just to truncate
   them to 8 KiB; workspace manifests cap total bytes at 20 MB and entries at 100.
5. **Timeout containment:** each Docker test container has a unique name and
   the launcher attempts forced cleanup after the CLI times out.
6. **Local API hygiene:** module import no longer creates state directories;
   IPv6 loopback Host header parsing is corrected.

## Execution performed

- `PYTHONPATH=src pytest -q`: **75 passed** (63 original + 12 new).
- Python compile: passed.
- `fluxos unified-demo`: real file dependency invalidation and preservation passed;
  `model_calls=0`.
- `fluxos benchmark`: deterministic mechanism demo, `gemma_calls=0`;
  **not** a measured model performance benchmark.
- Built an installable wheel. A temporary virtual environment installed the wheel; installed CLI and API smoke checks passed using the preinstalled dependency packages from the local runtime because offline resolution of new dependency wheels was unavailable. See VERIFICATION.json.
- Fresh ZIP extraction tested separately; archive member CRC validated.

## Open risks and explicit limits

**P0 before production**
- In-process `Principal` is not authenticated. The API is local-only and
  unauthenticated; there is no protection against malicious local processes.
- Trusted operator acceptance suites can import model-authored Python. The
  candidate code may attack the *Python test interpreter itself* even when
  running under `python -I` inside Docker; mocked Docker tests do not prove
  hostile-code isolation or a tamper-proof verifier.
- Filesystem validation, snapshot sealing and SQLite publication are not one
  OS/filesystem/database atomic operation. Unmanaged concurrent writes remain a
  race risk. The authority server and worktree must have exclusive ownership.
- Docker-based execution and real Gemma API inference remain **unverified here**.

**Deferred intentionally**
- Durable resume/reconciliation after a killed coordinator process.
- Language-specific acceptance runners for JS/TS and browser tests.
- Effectful third-party actions, authenticated remote workers, distributed consensus.
- Full task-solving A/B benchmark against a conventional Gemma harness.

## Release decision

Ship as a labeled **local development research artifact** for controlled demo
and further benchmarking. Do not represent it as production-ready, exploit-proof,
or proven to make Gemma smarter. Keep a single canonical design while testing.
