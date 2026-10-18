# Source-Level Comparison: OpenCode, OpenHands, FLUX//OS

Date: 2026-10-18. Research reference for v0.4.0, **not** a broad feature parity claim.

## Studied upstream implementation points

- OpenCode (MIT), `anomalyco/opencode`, branch `dev` at tree `86c7f7c84048d776ba94b94bfab782b2b0a6d776`: `packages/core/src/session/runner/step.ts` (`b3d9234e39453bef991c0783c522964bb8e357ae`), `packages/core/src/session/context.ts` (`e8cf2455bfac3eec5adf5c86d5f924d9aa0440ef`), `packages/core/src/tool/plugin/subagent.ts` (`87443f5e8a4b828eede4b632468511693f8ab9ee`), `packages/core/src/snapshot.ts` (`3ac6df3e24145ce8423532020b27459c48296dd0`), `packages/core/src/tool/plugin/shell.ts` (`af454a7d63391473d939436c87fff5c4b73eefb5`).
- OpenHands Software Agent SDK (MIT): `openhands-sdk/openhands/sdk/agent/agent.py` (`28b3472226f4098ac1b6eff33270acca27f1cc0a`) and `openhands-sdk/openhands/sdk/workspace/base.py` (`d0c95ad30d5b0ef8207aac3cb40f7372e4280cea`).

## Distinction

| Concern | Upstream engineering pattern | v0.4.0 choice | Still missing |
|---|---|---|---|
| Durable sessions | Session IDs and history independent of ephemeral tools | Stable project ID + accepted revisions; each task still creates a new session | Durable conversation replay/cancellation after process crash |
| Reasoning loop | Stream/cancel/retry/provider errors | Synchronous Gemma tool calls | Streaming, 429 exponential retry, rate limits, provider metrics |
| Code tools | Read, write, exact edits, shell, subagents | Read/write/edit, bounded code search; subagent batch | General guarded terminal, AST/LSP navigation, git integration |
| Project state | Workspaces and snapshots; Git integration | Immutable accepted artifact snapshot + CAS project head | Model-facing history browser, full file explorer, branch merging |
| Validation | Dedicated tool execution and test feedback | Operator-owned black-box process contracts for accepted projects | Diverse language/browser validators; real Docker adversarial testing |
| Memory consistency | Session checkpoints, tool history | One versioned causal store with witnessed reads, selective invalidation | Proof of complete read capture across all possible tools |
| UI | Full TUI/web/desktop and many integrations | One goal-first local browser and project ZIP export | Production project IDE and multi-user auth |

## What we actually ported

No upstream implementation files or code snippets have been copied into FLUX//OS. We implemented **equivalent patterns**—project identity, private workspaces, file edits, bounded code search, one agent loop, published revisions—in Python. These are commonplace engineering techniques, not unique inventions of OpenCode/OpenHands. Original MIT notices remain in their repositories; our original code is MIT licensed.

## Where FLUX adds differentiated engineering

For every accepted project revision, the runtime records witnessed dependencies, applies a job-generation fence, checks the expected project head **inside the same SQLite transaction** as the artifact version, and refuses a stale head publication. Read-only independent evaluation is bound to a source manifest hash. No independent source file is allowed to appear as a verified project merely because a model claimed completion.

This is a correctness *mechanism*, **not** demonstrated end-to-end speedup vs OpenCode/OpenHands, which have many features we do not support.

## Measured evidence

- 86 local pytest tests passed against source tree, including new project concurrency, export, and mock black-box tests.
- Real Gemma inference not tested.
- Docker black-box acceptance not tested against a live daemon. Tool contract tested with mocked subprocess; security claims remain bounded.
- No comparative task-success or token-use measurements; benchmark is still deterministic mechanics only.

## Scope freeze

Do not copy OpenCode's entire provider/tool/UI stack. Next prioritize live Gemma sessions, actual Docker execution, safe read instrumentation, objective benchmark, and then durable resume. Avoid a second scheduler/memory kernel.
