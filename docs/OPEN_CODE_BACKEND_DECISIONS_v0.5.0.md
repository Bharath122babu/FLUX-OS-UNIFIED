# OpenCode and OpenHands backend influence — explicit boundaries

The implementation is original Python work and does **not** incorporate copied OpenCode or OpenHands source code. Their current MIT terms would permit appropriately attributed reuse, but no direct copying was needed for v0.5.0.

| Upstream architecture pattern | FLUX application | Status |
|---|---|---|
| OpenCode model step + retry boundary (`packages/core/src/session/runner/`) | Bounded transient provider retry before tool effects | Partial; no streaming session runner |
| OpenCode file editing and patch tools (`packages/core/src/tool/plugin/`) | Checked staged text edits, move/delete, hash fencing | Partial; not full contextual unified diff parser |
| OpenCode shell and job ownership (`packages/core/src/tool/plugin/shell.ts`, `job.ts`) | Docker-only command with timeout cleanup, no shell parser policy used as confinement | Partial; no PTY/background execution |
| OpenCode source snapshots (`packages/core/src/snapshot.ts`) | Content-addressed candidate seal, manifest checks and CAS publication | Implemented local correctness checks, no object-store durability |
| OpenCode session storage (`packages/core/src/session/store.ts`) | SQLite diagnostic events per job | Partial; does not resume LLM conversation |
| OpenHands workspace abstractions (`openhands-sdk/openhands/sdk/workspace/`) | Private candidate workspaces and an explicit execution boundary | Partial |
| OpenCode MCP (`packages/core/src/mcp/`) | Not included | Deferred pending core safety proof |
| FLUX causal memory | Versioned read witnesses, dependency-aware validity, selective invalidation and project-head CAS | Distinct FLUX kernel; automated model repair remains open |

### Prior inspection status

See the archived `FLUX_OPENCODE_BACKEND_AUDIT_WAVE1.zip` in the prior conversation for 53 scoped checks (39 partially traced, 14 mapped only). This release does not retroactively turn that comparison into an exhaustive line-by-line audit. Runtime behavior remains more meaningful than repository size.
