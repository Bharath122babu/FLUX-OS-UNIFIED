# Adversarial verification protocol

| Test | Expected outcome | Evidence |
|---|---|---|
| `unittest.py` and `sitecustomize.py` in model workspace | Do not shadow trusted launcher | `test_unified_core.py::test_trusted_runner_unittest_shadow_local_subprocess` |
| Spoof old `Ran 1 test` output without trusted report | NOT `PASS` | `test_old_fake_unittest_stdout_no_longer_passes` |
| Source file changes outside registry during run | REPAIR / `STALE_REJECTED` | `test_byte_changed_outside_repo_registry_is_refused` |
| Existing source `api.py` read | `/hashes/api.py` witness captured | `test_file_hash_source_is_provenanced_at_content_projection` |
| Unrelated `styles.css` changes without filename changes | `api.py` result remains current | `test_unrelated_file_content_change_preserves_precise_file_witness` |
| Previously missing input file added later | Negative-directory witness invalidated | `test_missing_file_negative_witness_invalidates_when_path_appears` |
| Same-scope writer overwrites another artifact | `Denied` | `test_second_worker_cannot_overwrite_artifact` |
| Non-fenced agent result | `Denied` / `Stale` | `test_agent_result_requires_fenced_job` |
| Corrupt sealed workspace | Graph reports `INTEGRITY_FAILED` | `test_graph_handles_corrupt_published_snapshot` |
| Developer tests fail, acceptance otherwise passes | DRAFT, not VERIFIED | `test_dev_suite_failure_disqualifies_acceptance_success` |
| Cross-origin different localhost port or DNS rebinding Host | HTTP 403 | `test_api_rejects_cross_port_local_origin` |
| Actual source contract changes | Only dependent output stale | `fluxos unified-demo` + regression test |

All are **local tests**, except the launcher test which launches local isolated Python instead of Docker. A Docker daemon and a Google API key are required for the corresponding live integration tests, which remain unverified.

## Stronger tests not yet passed

- Actual Docker test with adversarial Python code attempting `sys.modules` tampering, `os._exit`, stdout spoofing, interpreter monkeypatching and sandbox escapes.
- Full external effect crash reconciliation and duplicate-prevention cases (no external effect adapter exists in v0.3).
- Crash between snapshot file sealing and SQLite artifact commit; orphan cleanup and atomic publication across files+DB.
- Concurrent canonical writer changes precisely at the SQLite commit boundary.
- Live Gemma function-calling on coding tasks against an independent baseline with matched token budget.
