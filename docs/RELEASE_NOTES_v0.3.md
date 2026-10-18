# v0.3.0 — Unified Core implementation, 17 October 2026

## Changelog and provenance

Based on `FLUX-OS-v0.2.0-CORRECTED.zip`. The previous independent audit reported P0 failures in real file-read causal tracking and the Python `unittest.py` acceptance runner, plus P1 ownership, graph integrity and status problems. This build **modifies source code**, adds focused tests, and retains the original architecture and old tests.

### Completed (local verification)

- Centralized publication decisions in `src/fluxos/gateway.py` as `UnifiedGate` with typed `GateOutcome`. Only the SQLite kernel (`put_artifact`) commits authoritative work.
- Versioned file-source tree stored as a fact. `names` and per-file `/hashes` projections allow source-local revalidation. `GemmaAgent` records mediated reads (`read_file`, `list_files`), writes of existing source files, and absent/new filename semantics, including the initial displayed filename list.
- Re-checks base workspace bytes and private candidate bytes before any gateway publication. Results that depend on a changed base are rejected; no changes appear in canonical source.
- Prevents unrelated same-scope writers from overwriting a previously authored artifact without explicit trusted `publisher` capability. All `result:*` artifacts require a live job generation fence.
- Hardened testing integration: trusted launcher mounted from a separate directory, `python -I`, no candidate-owned `PYTHONPATH`, result record parsed after actual test execution, read-only/no-network resource-limited Docker invocation. Local subprocess reproduction confirms original `unittest.py` and `sitecustomize.py` shadow probes no longer print for the trusted launcher. **No live Docker test executed.**
- `VERIFIED` now requires independent acceptance test pass *and* no observed developer suite failure or timeout. No acceptance or unavailable Docker => draft, not verified.
- Corrupted published snapshot returns `INTEGRITY_FAILED` in the graph view rather than crashing graph rendering.
- Local API rejects wrong Host headers and mismatched localhost origins, including different ports. This is not authentication.
- Reordered UI to make the single development prompt primary and show evidence below it. Only two navigation choices; detailed event timeline is collapsed.
- Added file-hash mutation/recovery demonstration (`fluxos unified-demo`) explicitly marked **no model calls**. Previous deterministic demo and synthetic benchmark remain.
- Regression suite extended with tests for fine-grained file witness preservation, missing-file witnesses, changed source during run, cross-worker ownership, tampered snapshots, trusted launcher, and developer test failures.

### Testing results and limitations

Run `python -m pip install -e '.[test]' && pytest -q` (or `PYTHONPATH=src pytest -q`). The automated suite is **63 tests** in the build container, all passing. Check `artifacts/VERIFICATION.json` for provenance and reproducibility commands.

**Not completed or not proven:** Real live Gemma API run, real Docker acceptance execution, comparative Gemma uplift, production security isolation, guaranteed exact-once external effects, robust long-lived distributed workflows, side-effect reconciliation, full JS/browser acceptance. The user should not submit or market those as completed.
