# Reproducible FLUX evaluation

The primary AI outcome is **independently verified task completion under equal resource budgets**, F0 versus B0. Kernel correctness, efficiency and real-model usefulness are separate results. A safety failure cannot be offset by a performance score.

## Measured evidence, 18 October 2026

The [saved Windows experiment](../benchmarks/results/2026-10-18/deterministic.json) used seeds 11, 29, 47; 24-node generated dependency graphs; and 1, 2, 5, 10, 20, 50 concurrent kernel writers in three workload classes.

| Measure | Observed numerator / denominator |
| --- | --- |
| Stale acceptance | 0 / 9 tested stale candidates |
| Lost updates | 0 / 534 scheduled compatible writes |
| Unauthorized publication | 0 / 3 attempts |
| Atomicity violations | 0 / 6 failed patches |
| Old-generation publication | 0 / 3 attempts |
| Invalidation recall | 57 / 57 genuinely stale artifacts |
| False invalidation | 0 / 23 eligible independent artifacts |
| Actual eligible reuse | 23 / 23 artifacts |
| Regenerations avoided versus full restart | 23 / 80 classified artifacts |
| Attack detection | 15 / 15 rejection probes; 0 false accepts |

All 921 recorded invariant checks passed. This includes per-writer records of 54 shared concurrency-group oracles, rather than 921 statistically independent experiments. Four additional process boundary cases are included in that count. Zero observed failures applies to these cases only. Throughput and tail latency vary with machine, filesystem and load; consult the raw group and attempt records instead of treating one run as a universal capacity figure.

**The real-model pilot is complete:** four tasks × B0/F0 × one trial = eight attempted runs. B0 passed **1/4**, F0 passed **0/4**, and the paired difference was **−25 percentage points**, with a task-cluster bootstrap interval of **−75 to 0 points**. This small, error-affected study establishes no FLUX benefit. See the [readout](../benchmarks/results/2026-10-18/gemma-pilot-v1/READOUT.md), [raw results](../benchmarks/results/2026-10-18/gemma-pilot-v1/results.json), and exported candidates/contracts. Actual billed cost and exact aggregate token usage are unavailable. The [earlier prerequisite report](../benchmarks/results/2026-10-18/pilot/results.json) is preserved as historical evidence from before Docker/WSL installation.

The measured pilot used **protocol 1**. The current runner uses **protocol 2**, which continues within the existing turn budget when a claimed completion has no required output, honors provider Retry-After/RPC RetryInfo hints with a task-wide cooldown, and counts an unaffected unit as eligible only when a prior verified artifact exists. Plans record their protocol and incompatible historical plans are rejected. These fixes have mocked and Docker-reference checks; a second real-model pilot has **not** been run.

## Run the suites

Install `python -m pip install -e ".[test]"`. Commands below run from the repository root; output paths must be new, preserving existing evidence.

```powershell
# A / B / C / E: no API calls or Docker required
python -m fluxos.evaluation deterministic --output .fluxos-benchmarks/kernel.json

# Inspect the approved eight-run schedule; this never calls a provider
python -m fluxos.evaluation plan --output .fluxos-benchmarks/pilot-plan.json

# Inspect all 20 controlled task definitions
python -m fluxos.evaluation catalog

# Validate paired orchestration using reference code and REAL Docker, no AI calls
docker pull python:3.12-alpine
docker pull node:22-alpine
python scripts/evaluation_docker_smoke.py

# With Docker running and GEMINI_API_KEY set locally, execute the pilot
python -m fluxos.evaluation run --output .fluxos-benchmarks/pilot --execute

# Produce reviewed rows for the dashboard from saved records
python -m fluxos.evaluation.report --deterministic .fluxos-benchmarks/kernel.json --live .fluxos-benchmarks/pilot/results.json --output .fluxos-benchmarks/dashboard.json
```

Never put a key in source, a command argument, a plan, or an experiment report. `GEMINI_API_KEY` is read from the process environment. The pilot pins `gemma-4-26b-a4b-it`, temperature 0.2, minimal thinking, 24 logical model calls, 36 generation HTTP attempts, 80,000 total tokens, 1,024 output tokens per generation, five turns per unit and 600 seconds per complete two-phase task. This permits at most 192 logical model calls and 640,000 budgeted tokens across eight runs; actual billing is not capped or inferred in dollars. Failed requests with unknown token usage are conservatively charged against the token budget and reported with unknown actual usage. Count-token requests are separately recorded. Timeout cleanup can extend elapsed time; tasks exceeding the wall budget fail completion.

The provider's [Gemma API guide](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api) documents model IDs and thinking options. The runner uses Google's [countTokens API](https://ai.google.dev/api/tokens) before reserving each generation's prompt and output allowance. Verify account availability before changing the pinned model.

The CLI default remains the small pilot. A larger study can be **planned without execution** using `plan --full --arms B0 B1 F0 F1 --trials 3 --output ...`. That schedules 240 runs. It is not authorized by the small-pilot choice and was not executed.

## What each suite establishes

| Suite | Oracle and measured population |
| --- | --- |
| A: safety | Stale CAS/preimage/read witnesses, overlapping and failed multi-field patches, authorization, superseded generations, compatible edits. Unexpected exceptions fail the check. |
| B: reuse | Fixed API/styles graph and seeded DAGs with independently computed transitive reachability; actual reads of eligible artifacts and actual selective repairs. Includes missing fields/files and exact content restoration. |
| C: concurrency | All workers observe before committing; disjoint, same-field and nested/transitive cases. Stores every attempt, expected conflicts, errors, zero automatic retries, group throughput and nearest-rank p50/p95 including lock wait. |
| D: AI usefulness | Randomized paired arms, the same task hash, settings, tools and task-wide budgets; operator-owned exact CLI contracts evaluated in Docker after sealing. Both phases must pass unit and full-project acceptance. |
| E: attacks/recovery | Forged hashes, confidential claim metadata, cancelled writes, fake PASS dictionaries, tampered seals and real subprocess termination after sealing, before DB commit, after DB commit and after a local effect receipt. |

The crash callback's acceptance is explicitly synthetic. The process termination and persisted SQLite/filesystem state are real. The effect test uses a local receipt and records `UNCERTAIN_NOT_REPLAYED`; it does not establish exactly-once behavior for arbitrary external services. Orphan snapshots are retained for inspection; interrupted jobs are quarantined instead of automatically replaying paid calls.

An unrestricted in-process caller can omit a true dependency. The benchmark records this as `BOUNDARY_LIMITATION`, excluded from the passing score, rather than calling it detected. Mediated model file tools observe reads; opaque commands conservatively witness the entire source tree. Content restoration does not automatically resurrect an invalidated artifact. These boundaries preclude claims of complete dependency discovery or production-grade isolation.

## Matched arms and task scope

On Windows, `powershell -File scripts/run_gemma_pilot.ps1` prepares missing images, runs the Docker smoke first, and asks for the key with hidden input if it is absent from the environment. It executes only the eight-run pilot and restores the previous environment afterward. It creates a fresh timestamped output directory; it never replays interrupted attempts automatically.

| Arm | Memory and reuse policy |
| --- | --- |
| B0 | Last-write-wins shared notes; full unit restart after every input mutation; no causal source witnesses. |
| B1 | B0 plus whole-record version checks and preimage conflict rejection. |
| F0 | FLUX recorded dependencies, invalidation and reuse of still-current units; no children. |
| F1 | F0 with optional bounded production child delegation sharing the same task budget. |

All arms retain sealed trusted acceptance, candidate permissions and job authorization, so the comparison isolates memory/dependency policy. No MemTX implementation was evaluated. F1 is optional and no claim is made that delegation helps.

The catalog has 8 coordination-related workflows, 8 development workflows and 4 adversarial prompts. These are **controlled two-unit Python CLI microbenchmarks**, not large-repository software engineering tasks or proof of real concurrent LLM collaboration. Coordination labels identify sequential mutation/cancellation/recovery workflows; physical races are measured in C. The dependency-upgrade task changes a vendored sorting configuration, not a real package ecosystem. Host-generated exact expected outputs stay outside the candidate mount. They are independent of model-authored tests, but are inspectable by a human reviewing the benchmark source.

Every run shares one meter across all units, repairs, provider retries and children. Attempts remain in the denominator even when they fail. Unattempted prerequisite blocks are excluded. Results preserve hashes of starting inputs and acceptance contracts, source file hashes, git state, resolved Docker image IDs, model settings, token usage, latency, faults and errors. Logs exclude secret headers. `journal.jsonl` flushes STARTED/FINISHED records; an interrupted STARTED run requires operator reconciliation and must not be silently discarded or resumed as a free attempt.

Per-arm completion uses successes/attempts with descriptive Wilson intervals. The comparison pairs by task and trial and bootstraps task clusters, keeping repeated trials together. Four task clusters provide weak uncertainty estimates; identical observed outcomes can produce degenerate intervals. Cost per completion includes all attempted runs' actual billed cost, divided by verified completions, only when complete billing evidence exists. P95 completion time includes failures and retries. Concurrency chart percentiles pool raw attempt latencies; throughput divides committed writes by summed group elapsed seconds, rather than averaging rates.

## Dashboard

The portable `benchmark-dashboard.html` in the accompanying benchmark ZIP contains the six requested measures, denominator tables, pooled concurrency curves, all eight completed pilot rows, matched-arm results, paired uncertainty, attack records and source inspection. Its snapshot is reproducible through `fluxos.evaluation.report`; authored React is in `benchmarks/dashboard/`. It uses the Data Analytics dashboard runtime. Unknown billing and exact token totals remain null; observed tokens are labeled as lower bounds. The dashboard is an evaluation artifact; the FLUX service remains backend-only.
