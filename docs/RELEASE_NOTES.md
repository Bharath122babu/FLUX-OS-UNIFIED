# FLUX//OS 0.2.0 — Correctness repair release (October 17, 2026)

**Release classification:** local single-host research and hackathon prototype. Not approved for internet exposure or confidential/untrusted multi-tenant work.

## Fixed: security and semantics

- Derived memory now records an authority witness for each dependency (classification plus source author); a source's authority change invalidates descendants even if its payload and JSON projection stay identical.
- New SQLite schema is migrated in place, adding `deps.expected_authority` and `jobs.generation`. Older dependency witnesses without an authority claim are treated as uncertified (fail closed) until rebuilt.
- Repaired eager transitive invalidation: compares the dependency of the **current traversed node**, not the outermost source, and propagates stale ancestors through the graph. Graph display computes effective currentness.
- Bounded iterative, memoized dependency validation avoids recursive depth/exponential repeated validation of diamond-shaped DAGs. It rejects detected cycles and excessive traversal.
- Gemma operates in a **private candidate** worktree. Parent and child branches copy bytes exactly rather than using model-truncated text reads. Rejected candidates are removed and cannot write to authoritative workspaces.
- Only results passing an **operator-provided independent acceptance test suite** are published as authoritative memory artifacts with immutable snapshot hash manifests. Without acceptance tests or Docker, files remain inspectable *DRAFT* snapshots, not verified releases. Zero discovered tests are explicitly `NO_TESTS`.
- Job transitions reject invalid or stale state transitions and use a generation fence before artifact publication. The API labels drafts as DRAFT rather than silently marking them successfully verified.
- Development API adds loopback-peer and origin restrictions. Local users still do not authenticate; never expose it publicly.
- Published workspace hashes are checked during kernel currentness validation, and `Memory.verify_published_snapshot()` allows explicit rechecking. Filesystem tampering now returns `INTEGRITY_FAILED` rather than silently accepting a corrupted code artifact.
- Observation objects refuse to silently replace conflicting witness versions when a source changes during one agent run, preventing read-laundering of stale decisions.

## Testing and evidence

48 tests pass on the patched source, including previous tests and new adversarial regressions for relabelling, author changes, transitive graph discrepancies, diamond DAGs, rejected file leaks, versioned job fencing, exact >8KB copies, symlinks, acceptance gating, published file tamper, cancellation, and cross-origin denial.

No Docker engine or live Gemma API key was available for an end-to-end model/acceptance run. The acceptance path is tested with a **mocked subprocess**, not a real container; model protocol calls are similarly mocked. No statistically valid Gemma or competitor benchmark has been run. `fluxos benchmark` is still only a deterministic work-unit example.

## Open P0/P1 release blockers for public deployment

The runtime is *not* an authenticated service or hardened sandbox for untrusted Python. It cannot guarantee complete observation of hidden dependencies; arbitrary external effects are not supported. There is no full cross-resource crash recovery/garbage collector for orphan snapshots. The project has no third-party security audit or production throughput qualification. These limitations remain explicitly open rather than being claimed fixed.

**Decision:** use for local judging demonstrations and further research only. Never claim universal consistency, task-level proof, or guaranteed competition success.
