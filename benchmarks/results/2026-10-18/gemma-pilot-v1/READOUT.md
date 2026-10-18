# Gemma paired pilot · protocol 1

Eight runs completed on Windows with real Docker acceptance on 18 October 2026. The model was `gemma-4-26b-a4b-it`, temperature 0.2, minimal thinking. Every run had the same limits: 24 logical model calls, 36 generation HTTP attempts, 80,000 budgeted tokens, 1,024 output tokens per generation, five turns per unit and 600 seconds per two-phase task. Run order was randomized with seed 20261018.

| Measure | B0 | F0 |
| --- | ---: | ---: |
| Both phases independently verified / attempted tasks | 1 / 4 (25%) | 0 / 4 (0%) |
| Verified unit generations / unit attempts | 11 / 16 | 8 / 16 |
| Logical model calls | 76 | 61 |
| Generation HTTP attempts | 85 | 76 |
| Provider retries | 9 | 15 |
| HTTP 429 responses | 4 | 16 |
| HTTP 500 responses | 6 | 4 |
| Observed token lower bound | 135,045 | 99,225 |
| Exact total tokens | unavailable | unavailable |
| Actual billed cost / cost per verified task | unavailable | unavailable |
| P50 attempted-task time | 132.59 s | 100.02 s |
| P95 attempted-task time | 153.58 s | 147.10 s |
| Regenerated / reused units | 16 / 0 | 16 / 0 |
| Recorded generation-fence failures | 0 | 0 |

F0 − B0 completion difference: **−25 percentage points**; paired task-cluster percentile bootstrap 95% interval **−75 to 0 points**, four pairs across four tasks. With only four task clusters and one trial each, this interval is weak evidence. The pilot supports **no claim of FLUX uplift, cost savings, or faster successful completion**. In particular, failed attempts' shorter runtimes do not establish a performance improvement.

The baseline's sole complete task was `coord-disjoint-edits`. Required files were missing in 4/16 B0 and 8/16 F0 unit attempts; provider errors affected 1/16 B0 and 5/16 F0 unit attempts. These categories can overlap. At least one generated program also violated the specified compact-JSON stdout format, which independent acceptance rejected. Valid individual components were insufficient: completion required both full-project phases to pass.

Twenty HTTP 429 and ten HTTP 500 responses were retained. [Google documents project-level quotas and model-specific limits](https://ai.google.dev/gemini-api/docs/rate-limits); the recorded status codes do not establish whether the specific limit was per-minute or daily. [Google recommends bounded exponential backoff](https://ai.google.dev/gemini-api/docs/troubleshooting). Protocol 1 retried after 0.4/0.8 seconds and did not retain or honor provider retry hints. Failed requests had unknown usage, so exact totals stay null; the observed tokens above are lower bounds and are not billing estimates.

Neither arm reused a unit in this pilot. Protocol 1's raw `eligible_reuse_artifacts=3` per arm counted unaffected unit slots even when a prior output had failed. The valid prior-output population was **one verified unaffected artifact per arm**, derived separately in [diagnostics.json](diagnostics.json). This measurement bug is fixed in protocol 2; the original raw records remain unchanged. Conservative whole-tree witnesses for shell commands also limit reuse opportunities: shell commands were used in 11/16 B0 and 8/16 F0 unit generations. This mechanism can invalidate an otherwise independent component when another source changes; the traces do not prove that it explains every unused artifact.

The recorded task timer starts when the shared model meter is initialized, after local memory/workspace setup, and includes generation, retries, tools, acceptance and publication. It excludes that initial setup and plan-level Docker readiness checks. Reported latency is for all attempts, not only verified completions.

The original [results](results.json), [plan](plan.json), [journal](journal.jsonl), independently owned [contracts](acceptance/), generated [unit candidates](candidates/) and [assembled projects](assembled/) are preserved. [exported-files.json](exported-files.json) binds copied candidate/assembly files to SHA-256 hashes. The raw source hashes and git state identify the executed code; absent `protocol_version` means protocol 1. Reproduce that behavior from the recorded Git revision, rather than running its plan with the current protocol-2 runner.

Protocol 2 adds the missing-output continuation, provider-informed cooldown and corrected eligibility population. It retains the same task, call, token, turn and wall budgets. Its checks use mocks and real Docker reference code, **not another real-model study**. Before another paid pilot, check the project's active limits in AI Studio and use a new versioned plan; all additional attempts must remain visible.
