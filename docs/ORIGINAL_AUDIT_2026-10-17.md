**Historical pre-repair audit.** Findings describe the superseded v0.1 build, not the current v0.2.0 source. See REMEDIATION_MATRIX.md.

# FLUX//OS — Canonical Architecture Audit and Build Decisions

Date: 2026-10-17. Source artifact: `FLUX-OS-HackDay-2026.zip` (actual source extracted and tested). This document preserves our objective, evidence, choices, disagreements, and stop/go criteria. **Status: architecture direction worth continuing; present source is NO-GO for trust-sensitive or public deployments.**

## 0. Frozen goal and assumptions

**Research hypothesis:** For the same Gemma 4 model, identical tools, task sets, and resource budget, an agent harness with trustworthy source dependency tracking and limited incremental repair can improve **verified useful completion** on evolving multi-agent software tasks, relative to a simple loop and a durable-workflow baseline.

**Not the goal:** More agents, more memory modules, a graph visualization, universal semantic truth, a new general database, or an unverifiable claim of outperforming Gemma standalone.

Assumptions: begin with one authoritative storage coordinator; typed mediated reads; immutable versioned outputs; workers initially untrusted; private candidate workspaces; no irreversible provider calls without durable effect semantics. Deploying across hosts requires a separate phase. Tests are run on an ephemeral local container filesystem; Gemma credentials are not provided; Docker is not installed in the audit environment. Code-level research sampled relevant files at retrieved repository versions, **not exhaustive whole-repository security review**.

**Decisions frozen for this round:** keep a tiny model/tool loop; one typed causal commitment kernel; isolate work in candidate branches; use verification gates; delegate durability to a mature system when needed; favor a minimal user-facing IDE-style workspace; no separate semantic truth database or always-on supervisor. These decisions may change only after a failed invariant or comparative benchmark.

## 1. Existing build: verified facts

Project code inspected: `src/fluxos/kernel.py` (Memory, Observation, SQLite transactions, projections, eager transitive invalidation), `src/fluxos/agent.py` (Gemma function calls, workspace tools, thread-based child delegates, candidate results), `src/fluxos/api.py` (local HTTP), `src/fluxos/demo.py` (contract-change mechanics), web `index.html`/`app.js`, and the tests.

- Local command `PYTHONPATH=src pytest -q` returned **29 passed** in under 1 second (one run). This tests specified examples, **not** security correctness, Gemma superiority, or crash recovery.
- `artifacts/benchmark.json` states Gemma calls = 0 and `quality_improvement_claim = NOT_MEASURED`. It contains a fixed 3-vs-2-unit work-count illustration, **not** a framework comparison.
- No live Gemma API call was executed in this audit; the code has a hosted Gemma client but no connected key was used. Docker is absent, so Docker-only tests cannot be validated here.

### P0, experimentally reproduced: classification escalation does not invalidate derived content

Code path: `kernel.py` `put_fact`, `_invalidate_dependents`, `_validate`; `Observation.artifact`.

Reproduction: an internal worker reads a versioned internal fact and publishes a derived internal artifact. Administrator promotes the same underlying fact value to secret. The worker's future source read is denied, but the derived artifact is still `DECLARED_CURRENT` and its original value remains readable by the worker. This demonstrates confidentiality downgrade-by-derivation after authority changes. Causal compatibility must cover **label, authority, revocation, origin** and content, not hash only.

Evidence: `reproduced_failures.json.classification_upgrade_without_invalidation`.

**Required fix:** record and validate a source authority epoch / classification digest; changes to classification must invalidate or reclassify all sensitive descendants even if value projection unchanged. At read time, validate the effective label (and transitive mandatory protection if that is the chosen policy). Add same-transaction tests for changes and ancestor escalation.

### P0, experimentally reproduced: stale file edits outlive rejected commits

Code path: `agent.py` `write_file` writes directly to the working directory; `GemmaAgent.run` tries `memory.put_artifact()` only **after** execution. When required state changed during execution, commit was rejected (`STALE_REJECTED`) but a candidate source file remained visible in the workspace.

Evidence: `reproduced_failures.json.stale_candidate_leaks_to_workspace`.

**Required fix:** never let a speculative worker write to the authoritative workspace. Use per-generation private filesystem snapshots or worktrees; validate dependency certificates and ownership fence; atomically publish a versioned candidate manifest and promote the workspace only after successful commit. A rejected candidate must remain quarantined, not become the next agent's working tree.

### P1, experimentally reproduced: raw transitive status diverges from effective status

Code path: `kernel.py:_invalidate_dependents`: inside the BFS loop the comparison uses outer `kind` and outer `source`, not the current `node` tuple. With artifact A changing to exactly B's stored value, `B` becomes stale; descendant `C` retains stored `DECLARED_CURRENT`, although recursive `status(C)` reports `STALE`.

Evidence: `reproduced_failures.json.transitive_raw_graph_staleness`.

**Required fix:** use the current node's source/kind, and propagate invalidation based on effective child validity, not an unrelated head hash. Keep a bounded, memoized traversal and test long/diamond graphs, collision-shaped payloads, and mixed fact/artifact ancestries. Make the dashboard derive effective statuses or establish a reliable materialized invariant.

### P1: current 'completion' is not a completion gate

`GemmaAgent.run` reports `VERIFIED` when Docker `unittest discover` exits zero and files exist, but there is no task-relative test-sufficiency proof; empty suites may succeed. It reports `OUTPUT` and may commit evidence even when verification is unavailable or fails. A result labelled `DECLARED_CURRENT` means recorded provenance matches, **not** the task succeeded. Completion must depend on independently defined acceptance tests, plus explicit test counts and exact execution identity.

### P1: child code copying can silently truncate files

`_spawn_many` copies parent files using `Workspace.read_file`, which truncates to the first 8192 characters; hash baseline is over original full bytes. That can create spurious file differences or lose content in a private branch even when no child intentionally edited the file. Use byte-exact snapshot/copy, separate model read limits from filesystem copies, and verify snapshot hashes.

### P1: job states lack ownership and durable recovery

`create_job`, `set_job` do not accept authenticated identity/capability, no state-transition CAS/lease fence, and `set_job` unconditionally overwrites state. They are not a real fault-tolerant scheduler. HTTP endpoints are unauthenticated; documentation correctly scopes the server to local development. No public deployment until identity and isolation are enforced.

### P2: additional specification gaps

No negative-read witnesses for absent files/records; untracked filesystem/external I/O; executable sandbox only for Docker tests (model tool file writes remain in host Python process); no durable external-effect ledger; no acknowledged human-approval workflow; one coordinator SQLite limits distributed operations; model comparisons not run. Many of these are documented limits, not new exploit findings. Treat them as blockers only when a claimed guarantee depends on them.

## 2. Bounded source-code comparison: what to borrow, and what not to imitate

Repositories were selected for **closest conceptual overlap**, not popularity. Code paths were directly read through GitHub's source interface (some supporting behavior is described by first-party project documentation). File hashes refer to the retrieved content at review time.

| System / inspected file | Actual implementation feature | Decision for FLUX//OS |
|---|---|---|
| [MemTX](https://github.com/lxy1134/MEMTX_/blob/main/src/memtx/memtx_manager.py) (`79bc539`) | Transactions capture snapshot IDs, choose isolation by risk, stage beliefs and guard irreversible actions. Source includes in-memory `_store`, `_txns` state. | **Strong nearest research prior art.** Borrow separate candidate/committed/action-safe states; do not pretend MemTX is a durable Postgres service or our own original invention. |
| [MemTX state machine](https://github.com/lxy1134/MEMTX_/blob/main/src/memtx/state_machine.py) (`249c9b8`) | Explicit allowed state transitions, invalid transition error. | Implement formal typed transitions for jobs/artifacts/effects, instead of free-form status strings. |
| [MemTX dependency graph](https://github.com/lxy1134/MEMTX_/blob/main/src/memtx/dependency_graph.py) (`95c97ab`) | Maintains parent/child sets, traverses descendants and revoked ancestors. | Explicitly test transitive invalidation and avoid inferring truth from graph shape. |
| [Bazel Skyframe](https://github.com/bazelbuild/bazel/blob/master/src/main/java/com/google/devtools/build/skyframe/EagerInvalidator.java) (`f8f2c0d`) | `invalidate` walks changed `SkyKey` inputs through a dirty-node visitor; Skyframe registers dependencies through controlled reads. | **Key engineering model:** hermeticity/complete source capture is more important than fancy graph ranking. Do not claim perfect minimal recomputation with hidden reads. |
| [Dagster](https://github.com/dagster-io/dagster/blob/master/python_modules/dagster/dagster/_core/definitions/data_version.py) (`08aed0b`) | `DataProvenance` includes `code_version`, input data versions, storage IDs. | Track code version + prompt/tool versions + environment image alongside source versions; hashes alone are insufficient. |
| [LangGraph](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint/langgraph/checkpoint/base/__init__.py) | Checkpoints record channel versions, `versions_seen`, pending writes and metadata. | Checkpointing is existing practice. Compare FLUX's fine-grained *causal revalidation* to this baseline; don't market checkpointing as unique. |
| [DBOS](https://github.com/dbos-inc/dbos-transact-py/blob/main/dbos/_recovery.py) (`35955ac`) | Recovery re-enqueues pending workflows through an atomic queue handoff; avoids multiple concurrent recovery runners. | Preferred candidate for durable workflow execution once Postgres is adopted. Avoid recreating queue/recovery engine unless measured value warrants it. |
| [Restate](https://github.com/restatedev/sdk-python/blob/main/python/restate/context.py) (`feb0086`) | Invocation context has IDs, scopes, idempotency keys and typed state operations. | Alternative durable backend for services; useful IDs and effects semantics; don't mix 2 durability authorities. |
| [Temporal](https://github.com/temporalio/sdk-python/blob/main/temporalio/worker/_replayer.py) (`b3eb1a4`) | Replayer accepts recorded workflow histories, plugins, and known workflow code for deterministic replay. | Adopt replay testing as a release gate. Temporal is a complexity-heavy alternative, not mandatory for the hackathon. |
| [Deep Agents](https://github.com/langchain-ai/deepagents/blob/main/libs/deepagents/deepagents/middleware/subagents.py) (`2eb9b42`) | Subagents get isolated scoped task context by default; fork mode and recursion restrictions are explicit. | Dynamic spawning must be contract-bound, with scope/capabilities and bounded recursion; do not use static subject-specific workers. |
| [Letta](https://github.com/letta-ai/letta-code/blob/main/src/skills/builtin/managing-shared-memory/SKILL.md) (`70fbb88`) | Shared memory repositories are Git-backed; agents commit changes, sync/rebase, and surface merge conflicts. | Keep Git/worktree view for development artifacts; memory should not be a second automatically authoritative chat history. |
| [OpenHands](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/agent/agent.py) (`28b3472`) | `_ActionBatch` mediates tool batches and blocked actions; `step()` handles pending actions before sampling more model output. | Keep simple agent loop, but make tool permissions and execution events explicit and recorded. |
| [mini-SWE-agent](https://github.com/SWE-agent/mini-swe-agent/blob/main/src/minisweagent/agents/default.py) (`ca310e3`) | `run` repeatedly calls `step()`, enforces time/cost/step budgets, serializes trajectories. | Baseline for Gemma: minimal tool loop; anything FLUX adds must beat it on relevant changing-state tasks. |

**Scope boundary:** Not every source file or entire repository was audited. Source lines are inspected implementation examples, not assertions about all guarantees and versions. MemTX's 2026 research paper claims improvements on evaluated tasks; our independent replication of those measurements has **not** been done.

## 3. Side-by-side architecture selection

| Option | Potential correctness | Speed / cost | Complexity | Decision |
|---|---|---|---|---|
| A. Minimal Gemma agent loop + restart all work after any change | Easier to reason about; lacks incremental reuse | Low overhead except expensive rework | Low | **Keep as baseline.** |
| B. LangGraph/DBOS with shared state and ordinary checkpoints | Durable workflow best practices, but semantic dependency reuse not automatic | Moderate overhead, robust recovery | Medium | **Keep as strong baseline / infrastructure.** |
| C. Tiny Gemma loop + causal certification kernel + sealed worktrees + durable workflow provider | Best hypothesis for rejecting observed stale dependencies while conserving independent work | Additional validation overhead; possible token savings only under edits/corrections | Medium-high | **Recommended target**, conditioned on P0 fixes and A/B evidence. |
| D. Layered multiple supervisors / semantic truth models / separate schedulers / CRDT + vector clocks | More unproven interfaces; no automatic correctness guarantee | Likely much higher token and engineering cost | Very high | **Reject until proven necessary.** |

The winner is **C as a research target**, not yet a proven product. Begin with a single-host corrected kernel and introduce a durable workflow provider only at the crash-recovery gate.

## 4. Minimal control plane — not dozens of micro-decisions

One typed admission boundary: `decide(actor, candidate, snapshot, requested_effect)` produces `ACCEPT | CONTINUE_PRIVATE | REPAIR | WAIT_RECONCILE | REJECT` with a machine-readable reason. Deterministic checks: actor/tenant/clearance, observed read-set completeness, source content + authority epochs, ownership/generation, candidate hash, tests, effect status, budgets. Gemma proposes task steps and semantic repairs but cannot override the commit kernel. It should not be invoked for every memory hash comparison.

One agent loop: prepare bounded context -> model -> schema-validate tool call -> isolated tool execution -> record evidence -> iterate -> independent completion gate. Zero default children; spawn only for genuinely independent, bounded subjobs. A child cannot publish to the parent workspace directly.

One storage authority: immutable input/output versions, typed dependency edges, candidate branch identity, approvals and effect intents, job lifecycle, audit event IDs. A graph display is a *projection* of committed data, not a parallel truth store.

## 5. Gemma experiment: avoid fake improvement claims

Fix the model and tool schema. Run three seeds per task, 12+ development tasks, including intentional upstream API/schema changes, secret-label escalation, concurrent edits, mid-commit crash, repeated ancestry and malicious retrieved text. Compare:

1. `B0`: minimal Gemma 4 coding loop with identical tools and task budget.
2. `B1`: conventional checkpointed runner (LangGraph / DBOS pattern) without causal selective invalidation.
3. `F0`: FLUX kernel + baseline agent, after P0 fixes.
4. `F1`: F0 + bounded context compiler.
5. `F2`: F1 + isolated dynamic agents (optional; must earn its overhead).

Report task-level outcomes, not just averages: independently passing acceptance tests, source- and policy-violation counts, stale-commit attempts accepted, wasted/replayed work, actual token usage, provider requests, wall time and p95 latency. Report both changed and unchanged tasks. Preserve all failures. Same model, environment, budget and seeds across conditions. If F2 is worse than F1, disable dynamic spawning by default.

Current Gemma advantage: **NOT MEASURED**. Local deterministic demo: **NOT equivalent to a Gemma benchmark**.

## 6. Interface study and design freeze

Successful consumer-oriented coding agents put the user's goal first and make execution detail inspectable, not mandatory. The current FLUX UI has four navigation views, a user goal textarea, causal graph, event timeline, and generated-files view. It is adequate for explaining causality; not yet a development workspace with preview, acceptance-test status, or branch review.

Freeze a three-pane layout with **one user prompt**, **central live workspace/diff/preview**, **right contextual verification and agent status**. Collapse the evidence graph and scheduler trace behind `Why?` and `Investigate` controls. Surface `Accepted / Repairing / Waiting / Rejected` with exact reason rather than exposing internal scheduler microdecisions. Keep admin diagnostics separate from user experience.

## 7. Release gates — strict order

- **Gate 0 (must pass):** write adversarial regression tests for classification escalation, graph status divergence, rejected-candidate file visibility, and child-file truncation; patch all. Explicitly reject remote deployment until there is authenticated, cross-tenant mediation.
- **Gate 1:** private worktree transactions with atomic publication of version + file manifest; genuine completion criteria; identity, lease and generation fencing. No unverified file made authoritative.
- **Gate 2:** crash injection at every commit/effect phase, durable retry semantics, no duplicated external effect after unknown outcome. Consider DBOS vs Restate; use one.
- **Gate 3:** head-to-head Gemma A/B harness experiment with independent tests, ≥12 evolving tasks, 3 repeats, uncertainty and ablations. Only now make measured improvement claims.
- **Gate 4:** public repository, reproducible scripts/data, clear safety limitations, one satisfying judge-controlled onstage fault/recovery demo.

## 8. Explicit kill rules and future audit checkpoint

- Reject any second authoritative memory/graph state machine.
- Reject per-operation LLM approval/safety judges in the kernel hot path.
- Reject model-specific finetuning, RL scheduler, CRDTs or distributed consensus until a benchmark proves they target the bottleneck.
- Reject unbounded agent creation and uncontrolled file merges.
- Reject `VERIFIED` if there is no credible task-relative acceptance-test evidence.
- Reject all production / model-superiority claims based only on current tests.

**Next engineering operation:** Patch the three reproduced P0/P1 behaviors in `kernel.py` and `agent.py`, add adversarial tests to CI, rerun 29 originals, then test workspace commit atomicity. After that implement the A/B benchmark. Do not add more features until gate 0 passes.

## 9. Audit evidence files

- `adversarial_audit_probes.py`: self-contained reproductions against a temporary DB/workspace. No source code changes required.
- `reproduced_failures.json`: actual observations from running the probes.
- `FLUX-OS-HackDay-2026.zip`: earlier actual project artifact; **not** silently marked fixed by this audit.

Decision log: 2026-10-17 first review, **KEEP** tiny agent loop + singular causal kernel, **REPAIR** transitive status/clearance/worktree boundaries, **DEFER** distributed scheduler, multi-model optimization, all speculative novelty claims, **MEASURE** Gemma against strong baselines.
