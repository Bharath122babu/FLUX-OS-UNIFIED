# FLUX//OS release acceptance and remediation matrix

Audit baseline: 2026-10-17, FLUX-OS-HackDay-2026.zip. Candidate patch: v0.2.0.

| Audit finding | Current treatment | Evidence | Status |
|---|---|---|---|
| Classification promotion with unchanged payload leaves descendants readable | Dependency witnesses include authority digest, and classification/producer changes propagate staleness | `test_classification_escalation_blocks_same_value_derived_read`, `test_author_change_same_value_invalidates` | Repaired within recorded-dependency threat model |
| Stale candidate file leaked to shared workspace | All top-level model writes are made in private candidate; stale candidate discarded; accepted code referenced through published immutable snapshot | `test_requirement_change_during_model_run_rejects_authoritative_result`, `test_rejected_candidate_does_not_leak_any_file` | Repaired for mediated model file tools |
| Transitive statuses inconsistent | Current-node validation, eager invalidation propagation, graph effective state | `test_transitive_graph_status_matches_effective_when_hashes_coincide`, `test_diamond_graph_validation_no_repeated_explosion` | Repaired under single-host concurrency model |
| Child branch truncates files >8192 chars | Binary-exact verified copy, independent of model read limit | `test_byte_exact_snapshot_larger_than_model_read_limit`, `test_parallel_delegation_preserves_large_unedited_source` | Repaired |
| Empty or model-authored tests can claim success | Zero tests => NO_TESTS. Operator-supplied, uneditable acceptance suite required for VERIFIED. No independent suite => DRAFT. | `test_empty_discovered_tests_are_not_pass`, `test_acceptance_suite_isolated_and_required_for_publication` | Repaired local validation gate; general task semantics not proven |
| Unfenced job state | CAS state transitions, owner permission path, generation checked when publishing | `test_job_transition_cas_and_owner_fence`, `test_cancelled_job_cannot_publish_even_with_acceptance` | Repaired for local coordinator; crash recovery not implemented |
| Externally modified accepted files considered current | SHA256 manifests verified at status/read and explicit snapshot verifier | `test_acceptance_suite_isolated_and_required_for_publication` | Repaired for on-disk hash mismatches |
| Reread overwrites earlier dependency witness | Observation refuses different hash or authority in same run | `test_observation_cannot_launder_changed_source_by_rereading` | Repaired for mediated reads |
| Caller-facing local demo lacks authenticated remote access | Loopback bind and peer/origin middleware | `test_local_api_rejects_untrusted_origin` | Public deployment **NOT SAFE**; not a substitute for auth |
| Host process and kernel not isolated against hostile Python | Model only has specific scoped tools; Docker for executing tests | Code review; local tests | **OPEN**, requires hardened worker/gateway split |
| Provider effect crash/unknown outcome | No email/payment/deployment tools exposed | No such tools in model tool schema | **OUT OF SCOPE**; cannot claim exactly once |
| Negative-read witness / full hidden-input tracking | Not provided | Design notes | **OPEN**: fail closed for stronger correctness claims |
| Distributed durable recovery / performance superiority | Not provided | No distributed or live-Gemma A/B runs | **OPEN**, not a production system |

## Decision record

1. Keep one SQLite authority and one deterministic commit boundary; no new mutable graph or redundant LLM supervisor.
2. Preserve tiny Gemma 4 tool loop and dynamic scoped child tasks.
3. Define DRAFT vs VERIFIED explicitly. Only independently tested outputs can receive authoritative file artifact records.
4. Reject public deployment and model-uplift claims until the remaining release gates are met.

## Tests

`PYTHONPATH=src pytest -q` => **48 passed**. Docker/Gemma API end-to-end not available here; subprocess and model client tests use deterministic mocks. `fluxos demo` and `fluxos benchmark` run, but benchmark is a synthetic work-unit demonstration.
