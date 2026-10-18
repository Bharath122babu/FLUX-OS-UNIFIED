> **Historical document (pre-v0.5.0).** For current backend release and security guarantees, read `README.md`, `docs/RELEASE_NOTES_v0.5.0.md`, and `docs/SECURITY.md` first.

# FLUX//OS — architecture and design decisions

## Objective
With a fixed model, tools, and work budget, increase *verified useful completion* for tasks that require parallel software changes under evolving shared requirements, while reducing unsafe stale acceptance and unnecessary rework. This is a falsifiable hypothesis, **not an achieved benchmark result**.

## Three competing methods considered
| Architecture | Accuracy conditions | Cost / latency | Engineering complexity | Decision |
|---|---|---|---|---|
| One conventional tool loop + global restart | Simple baseline, redundant work under corrections | Frequent repeated model calls | Low | Retain as benchmark |
| Multiple agents freely editing a shared folder and prompt-memory | Races and undetected stale inputs unless heavily serialized | Many unnecessary calls / merge conflicts | Superficially simple but operationally fragile | Reject |
| One minimal agent loop + causal commit kernel + optional bounded workers | Rejects stale commits **only for recorded reads**; supports unaffected projection reuse | Some transaction overhead; possible repair savings | Medium-high | Implement and test |

## Execution ownership
- Gemma agent proposes actions; an explicit JSON-schema tool registry restricts actions.
- Each child has a separate path; merge uses content hashes and rejects overlapping conflicting edits.
- Tool-side state is authoritative only after a SQLite `BEGIN IMMEDIATE` transaction revalidates expected dependency projections and classification.
- Workers have no ability to bypass the kernel's interfaces through provided model tools, but direct Python code in the same host can bypass those interfaces: **not a hardened sandbox**.
- No separate graph-database truth source, no autonomous LLM security judge, no multiple coordinating supervisors.

## Five conceptual kernel outcomes
**ACCEPT**: dependencies current and operation authorized.
**CONTINUE**: work stays private pending completion.
**REPAIR**: an input changed; rebuild affected outputs.
**WAIT**: external effect / human approval pathway not implemented; hold such actions.
**REJECT**: invalid/stale/unauthorized/over-budget operation.

These are conceptual; implemented methods raise `Stale` / `Denied` and produce `DECLARED_CURRENT` / `STALE` / `INTEGRITY_FAILED` statuses. No unimplemented feature is disguised as an API.

## Invariants under test
1. Artifact commits are serialized with dependency revalidation; recorded stale dependencies cannot be accepted after a competing committed mutation.
2. Existing classification must be authorized before overwrite; declassification requires explicit role and sufficient clearance.
3. Each output records its actual declared JSON-pointer read projections; unrelated field updates retain compatibility.
4. Downstream derived artifacts become stale transitively after a material source change, with each affected node examined at most once per invalidation traversal.
5. Artifact blob hash is validated on status and read.
6. Child tasks are bounded; subagents cannot recursively create others.
7. File path resolution rejects traversal/symlink escape from the assigned workspace.

## Engineering decisions and rejected complexity
- SQLite on one coordinator. Postgres and distributed correctness add substantial unproven complexity for this stage.
- Append-only historical artifact versions plus current heads; no CRDT and no vector-clock layer.
- No probabilistic or RL scheduler, no learned confidence-gating to accept commits.
- Native Gemma 4 `functionCall`/`functionResponse`, not parsing random JSON text into arbitrary shell commands.
- Deterministic test results are kept distinct from model-evaluation results.
- Filesystem isolation for agent edits is only path-level. Code execution is **Docker-only**, with network disabled, memory/pid/cpu limits and read-only mounted project.
- A single human-readable dashboard shows underlying evidence without claiming metrics that were never measured.

## Important security gaps not solved here
These are important **NO-GO** gates for deploying on public internet or to untrusted groups: in-process actors are caller-provided; API does not authenticate or authorize remote callers; no real OS separation between main model tool runner and DB files; no safe external effects; no complete observability of hidden dependencies; child file merge is not an atomic DB+filesystem transaction; no durable distributed scheduling; model output may include instructions from untrusted documents. Docker's filesystem/privilege restrictions are a defense in depth for optional tests, not a comprehensive production security guarantee.

## Relevant open-source engineering evidence
- `SWE-agent/mini-swe-agent` `src/minisweagent/agents/default.py`: minimal query/action loop, budget and save semantics.
- `earendil-works/pi` `packages/agent/src/agent-loop.ts`: small loop, user steering, checked tool calls.
- `OpenHands/software-agent-sdk` `openhands-sdk/openhands/sdk/agent/agent.py`: event-driven action batches, isolated execution concerns, context condensation.
- `cline/cline` `sdk/packages/agents/src/agent-runtime.ts`: typed tools and model callback lifecycle.
- `langchain-ai/langgraph` `libs/langgraph/langgraph/graph/state.py`: shared state graph with reducers and checkpoints.
- `langchain-ai/deepagents` `libs/deepagents/deepagents/middleware/subagents.py`: scoped delegation and forked state.
- `letta-ai/letta-code` `src/skills/builtin/managing-shared-memory/SKILL.md`: shared Git-backed memory repository model.
- `pydantic/pydantic-ai` `pydantic_ai_slim/pydantic_ai/_agent_graph.py`: explicit end-strategy and tool ordering semantics.
- `https://gemma.ai/deployment/gemini-api/`: official Gemma 4 hosted function-calling example.

**Novelty scope:** This is an integrated engineering experiment; causality, MVCC, versioned dependencies, and tool calling are established concepts. The unproven contribution is whether their particular combination improves Gemma-powered dynamic development work.
