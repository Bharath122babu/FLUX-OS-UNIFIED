# FLUX//OS — Project Overview

## The one-line idea

**FLUX//OS is a causal agent harness that lets coding agents work in parallel without allowing stale, conflicting, incomplete, or unverified work to silently become the accepted project.**

It is not another chat wrapper. It is a controlled execution and publication layer around an AI coding loop.

## Why this matters

Coding agents are increasingly capable of creating files and running commands. The difficult systems problem begins when several workers operate while requirements, source files, and shared decisions are changing.

A normal shared-memory design often behaves like this:

```text
Worker A reads version 7
Worker B reads version 7
Worker A writes version 8
Worker B writes version 8

Result: B silently overwrites A
```

The project can appear successful even though valid work was lost.

FLUX//OS changes the publication rule: **a worker may propose a result, but the kernel decides whether that result is still causally valid and independently verified.**

## The FLUX protocol

```text
Task + operator-owned acceptance contract
        ↓
Bounded Gemma tool-calling loop
        ↓
Private candidate workspace
        ↓
Recorded reads, hashes, versions, and dependencies
        ↓
Sealed candidate snapshot
        ↓
Independent black-box acceptance
        ↓
Source, contract, snapshot, and project-head rechecks
        ↓
SQLite causal commit gate
        ↓
VERIFIED / DRAFT / STALE_REJECTED / COMMIT_REJECTED
```

### 1. The agent observes before it edits

The harness exposes typed tools for:

- Listing files.
- Searching source.
- Reading complete files or bounded ranges.
- Writing files.
- Applying exact, preimage-checked changes.
- Moving and deleting files.
- Running bounded Python or Node commands in Docker.
- Delegating bounded work to child workers.
- Reading and conditionally patching project-scoped shared memory.
- Recording and inspecting explicitly unverified claims.

Important reads become witnesses. A later commit can be rejected if the facts or files that the worker relied on have changed.

### 2. The agent works privately

The model never edits the accepted project directly. Its candidate is isolated from the accepted revision. This makes incomplete work recoverable and prevents a model’s intermediate state from becoming production state.

### 3. Shared memory uses conditional writes

FLUX shared memory stores values with versions and hashes. A worker submits the value it observed as a precondition.

```text
Expected hash: abc123
New value: contract-v2
```

If another worker changed that field first, the write becomes `STALE_REJECTED`. Different fields can still be updated independently.

### 4. Candidate acceptance is independent

Developer feedback is useful, but a model’s reported `PASS` is not publication authority. FLUX seals a candidate and runs an operator-owned black-box acceptance contract against the sealed bytes.

The accepted revision is committed only after the candidate, source, contract, and recorded causal witnesses are rechecked. Hidden or omitted dependencies are outside that guarantee.

## Agent harness architecture

### Gemma client and agent loop

The Gemma integration provides a bounded function-calling loop. The model proposes typed tool calls rather than arbitrary shell commands. The loop records model and tool events and can retry selected transient provider failures.

The harness does not pretend that model output is truth. Model output is a proposal that must pass tool, dependency, acceptance, and commit boundaries.

### Unified tool gateway

The gateway is the model’s controlled interface to the project. It centralizes:

- Path validation.
- Workspace boundaries.
- File preconditions.
- Read pagination.
- Command limits.
- Worker limits.
- Event recording.
- Shared-memory access.

This is safer and more auditable than giving each worker an unrestricted shell and a shared folder.

### Bounded workers

FLUX can delegate a limited batch of child coding workers. Children receive separate workspaces and cannot recursively create more workers. Merges are checked for overlapping or conflicting changes.

### Docker execution

Python and Node commands run through preloaded Docker images with network access disabled and resource limits applied. Docker is a defense-in-depth boundary, not a claim of hardened production isolation.

### Causal SQLite kernel

SQLite is the single commit authority. It records:

- Facts and versions.
- Observed dependency projections.
- Artifact history.
- Project heads.
- Job generations.
- Execution events.
- Shared-memory updates.

There is no second hidden memory database, autonomous judge, or extra planner deciding whether a revision becomes accepted.

## What makes FLUX different

| Capability | Regular shared memory | FLUX//OS |
|---|---|---|
| Conflicting same-field writes | Often last writer wins | Stale write is rejected |
| Disjoint edits | May require global serialization | Compatible field edits can coexist |
| Requirement changes | Usually prompt-dependent | Recorded dependencies can become stale |
| Agent workspace | Shared mutable location | Private candidate workspace |
| Model-reported test pass | May be treated as success | Cannot independently authorize publication |
| Acceptance | Often coupled to the agent | Sealed, operator-owned black-box check |
| Incomplete output | May leak into the project | Kept private or marked incomplete |
| History | Limited or ad hoc | Causal SQLite revision and event history |
| Recovery behavior | Often manual overwrite | Explicit stale, draft, and rejected outcomes |

## Current evidence

See [benchmark methodology](BENCHMARKS.md) for the 921-record safety matrix, 534 compatible writes, and raw live pilot evidence. The smaller demonstrations below are separate workloads. Current integration checks are in [submission verification](SUBMISSION_INTEGRATION_2026-10-18.md).

### Shared-memory stress result

The deterministic stress workload reported:

- 20 agents.
- 12 trials.
- 240 disjoint edits preserved.
- 0 lost updates.
- 1 same-field winner.
- 19 same-field conflicts rejected.

This checks conditional writes and conflict rejection in that workload; it is not a model-quality measurement.

### Selective-repair result

The synthetic contract-change workload reported:

- Regular restart path: 3 units restarted.
- FLUX repair path: 2 affected units repaired.
- Unaffected `styles` work preserved.
- All units current after repair.

This supports the claim that causal tracking can reduce unnecessary rework in the tested workload.

### Live Gemma pilot limitation

The eight-run pilot did not establish a model-performance advantage:

- Baseline: 1/4 verified tasks.
- FLUX: 0/4 verified tasks.

Provider rate limits, retries, missing outputs, and the small sample affected the result. Therefore, FLUX should not claim better model intelligence, lower cost, or higher end-to-end completion until a larger matched evaluation is completed.

## What the evidence supports

The strongest defensible claim is:

> **In the tested cases, FLUX preserves compatible edits, rejects stale conflicts, isolates incomplete candidates, and requires independent acceptance before publication. Its dependency guarantees cover recorded observations.**

These results establish tested coordination mechanics. They do not establish superiority to other agent frameworks or better live model outcomes.

## Recommended demonstration

1. Open the local FLUX control room.
2. Click RUN CONFLICT PROBE to compare a last-write-wins dictionary with actual SQLite conditional writes; no model is involved.
3. Show regular memory accepting both writes and silently losing one.
4. Show FLUX accepting the first conditional write and rejecting the stale second write.
5. Run `fluxos unified-demo` to change the source contract from `email` to `student_id` in the separate deterministic demo.
6. Show only dependent artifacts becoming stale.
7. Repair the affected artifacts while preserving the independent style artifact.
8. Show the benchmark table and state the Gemma pilot result accurately.
9. Close with the core message: **coordination correctness before publication speed.**

## Boundaries and future work

FLUX//OS is a trusted, single-host research prototype. It does not currently provide public-internet authentication, production multi-tenancy, durable conversation replay, automatic model-driven stale repair, full JS/TS/browser acceptance, MCP stdio support, or a proven live model-quality advantage.

Those limitations are part of the project’s credibility: the system reports what it has verified and refuses to turn an unverified model claim into an accepted revision.

## Final pitch

Most agent systems ask: **“Can the model generate code?”**

FLUX//OS asks the harder operational question:

> **“When several agents generate code while reality changes, can we prove which work is still valid before accepting it?”**

FLUX//OS provides a concrete answer: private work, witnessed dependencies, conditional shared memory, independent acceptance, and a single causal commit authority.
