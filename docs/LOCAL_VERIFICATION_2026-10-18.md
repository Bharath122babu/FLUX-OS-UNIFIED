# Local verification — October 18, 2026

The README was expanded for GitHub publication. Application source and tests are unchanged from the supplied v0.5.0 release. This record supplements the original verification artifact; it does not replace its historical claims.

## Environment

- Windows, native PowerShell
- Python 3.12.10
- Fresh project-local virtual environment
- Editable install with `python -m pip install -e ".[test]"`
- Installed dependencies include FastAPI 0.143.3, Starlette 1.8.0, HTTPX 0.28.1, Pydantic 2.14.1, Uvicorn 0.54.0, and pytest 9.1.1.
- Docker CLI was not available. No live model request was performed.

## Results

| Check | Result |
| --- | --- |
| Editable installation with test dependencies | Passed |
| `fluxos --help` | Passed |
| `fluxos unified-demo` | Passed; dependent frontend becomes stale and is repaired, styles remain current, zero model calls |
| `fluxos benchmark` | Passed; two invalidated units repaired, styles preserved, all artifacts current afterward, zero model calls |
| `python -m pytest -q --tb=short` | **96 passed, 8 failed**, one dependency deprecation warning |
| Local README links | All file targets exist |
| Actual CLI server smoke check | `/`, `/docs`, `/api/health`, and `/api/projects/smoke` each returned HTTP 200 on loopback; server stopped after the check |

## Native Windows failures

| Test | Observed cause |
| --- | --- |
| `test_workspace_roundtrip` | `Workspace.list_files` returns nested paths with Windows backslashes, which `Workspace.safe` rejects. |
| `test_patch_create_edit_move_and_delete` | Same nested-path rejection during staged manifest validation. |
| `test_api_project_export_contains_accepted_revision` | Same nested-path rejection before the export request. |
| `test_workspace_symlink_escape` | Windows symlink creation requires a privilege absent in this session (`WinError 1314`). |
| `test_workspace_rejects_symlink_in_snapshot` | Same missing symlink privilege. |
| `test_symlink_source_cannot_be_sealed` | Same missing symlink privilege. |
| `test_project_head_detects_snapshot_tampering` | Test attempts to overwrite a read-only sealed file; Windows denies the write. |
| `test_failed_commit_cleans_candidate_copy` | Cleanup leaves a read-only published snapshot directory behind on Windows. |

The suite also emitted a Starlette warning that its HTTPX-based TestClient integration is deprecated. It did not account for the eight failures.

These results establish known native Windows limitations. The original artifact's report of 104 passing tests applies to its original environment, not this run. No new Linux, Docker, live Gemma, or agent-performance validation is claimed.

## Publication changes

- Expanded `README.md` with setup, architecture, acceptance workflow, configuration, CLI/API reference, troubleshooting, and contribution guidance.
- Extended `.gitignore` to exclude virtual environments, environment-file variants, and private-key files.
- Added this verification record.
- Updated `SOURCE_SHA256.json` to reflect the documentation and ignore-rule changes and include this record. The original release verification artifact is preserved.
