# Gemma 4: paired harness benchmark (not yet run)

**Null hypothesis:** FLUX//OS does not improve independently verified useful completions or reduce effective recovery cost relative to a straightforward agent loop using the same exact Gemma 4 model.

## Arms

- B0: Gemma 4 + the same tool set + private environment, no causal source revalidation, conservative full restart on change.
- F0: B0 + versioned source observations + UnifiedGate + selective preservation.
- F1 (optional): F0 + at most three dynamic child workers, with all their calls and cost counted. Disable if F1 loses on quality-adjusted cost.

## Controls

Pin the exact model ID/temperature; use the same task definitions, repo revision, trusted acceptance suite, model and total budget, Docker image, machine and retry policy. Randomize treatment order. Use at least 12 nontrivial tasks covering untouched state, changed API contract, new file addition, secret label change, nested dependency chains, conflicting writers and cancellation; run 3 or more independent trials per task if budget allows.

## Metrics

- Primary: fraction of tasks that pass independent acceptance without policy breach.
- Safety: falsely accepted stale candidate count; unauthorized publication; tamper acceptance.
- Efficiency: model token usage, calls, wall time, p95 tail latency, share of unaffected work reused, amount of recomputation and Docker executions.
- Reproducibility: per-task evidence, exact source/version hashes, request IDs, acceptance logs and failed runs.

**Current state:** `fluxos benchmark` and `fluxos unified-demo` are deterministic, with zero Gemma calls. They are *not* evidence of model uplift.
