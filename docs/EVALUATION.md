> **Historical document (pre-v0.5.0).** For current backend release and security guarantees, read `README.md`, `docs/RELEASE_NOTES_v0.5.0.md`, and `docs/SECURITY.md` first.

# What it takes to prove a Gemma 4 harness win

**Current status:** No real Gemma 4 API key was supplied to the build environment, so real model outcomes are **NOT TESTED**. The mock transport verifies request/tool/response plumbing, not AI quality. The deterministic three-artifact scenario verifies only the implemented memory behavior.

## Experimental design (must be executed)

| Group | Model | Tools | Extra mechanism | Comparison |
|---|---|---|---|---|
| A | Gemma 4 26B A4B | Same file/test tools | Minimal loop, full re-run | Quality/cost baseline |
| B | Same ID / settings | Same tools | Typed feedback and bounded context | Whether tooling helps |
| C | Same ID / settings | Same tools | B + causal dependency invalidation | Value of FLUX tracking |
| D | Same ID / settings | Same tools | C + dynamic parallel workers | Benefit of delegation |

**Important:** Fix model revision, temperature, task set, tool budget, workspace state, API access, and evaluator before running. Use at least 20 representative tasks, 3 repetitions each, and report intervals as well as averages. Do not select only tasks where FLUX succeeds.

### Tasks
- API contract changes midway through development; inspect stale reads and required repairs.
- Two agents editing overlapping files; reject data loss and measure unnecessary restarts.
- Interrupted coding task with a subsequent resume requirement (not yet supported here).
- Repeated independent edits; compare preserved work units and actual wall time.
- Authorization/tampering adversarial cases; count accepted unsafe commits.

### Metrics
Verified task completion (hidden tests); stale or unauthorized commits; number of model calls; prompt/output tokens from provider usage; wall-clock p50/p95; sandbox test outcomes; number of regenerated artifacts; effective cost per correct completion.

A Gemma uplift claim is permitted **only** if D (or C) beats the relevant baseline on the held-out same-task evaluation under comparable budget. Otherwise document failure and turn off the feature causing overhead.
