# Local verification — October 18, 2026

The initial GitHub publication expanded the README and preserved the supplied application source and tests. A subsequent Windows portability fix changed application code and tests as described below. This record supplements the original verification artifact; it does not replace its historical claims.

## Environment

- Windows, native PowerShell
- Python 3.12.10
- Fresh project-local virtual environment
- Editable install with `python -m pip install -e ".[test]"`
- Installed dependencies include FastAPI 0.143.3, Starlette 1.8.0, HTTPX 0.28.1, Pydantic 2.14.1, Uvicorn 0.54.0, and pytest 9.1.1.
- Docker CLI was not available. No live model request was performed.

## Initial publication results

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

These results established native Windows limitations in the supplied release. The original artifact's report of 104 passing tests applies to its original environment, not this initial run. Docker, live Gemma, and agent-performance validation remain separate checks.

## Windows portability follow-up

The local suite now reports **107 passed, 3 skipped, 0 failed** on the same Python 3.12.10 environment. The unified demo and synthetic benchmark also pass with zero model calls.

- Workspace file names use forward slashes on every platform, matching the kernel and Docker paths. Backslash and traversal inputs remain rejected.
- Text writes preserve LF bytes on Windows, keeping the reported content hash consistent with the stored bytes and exported ZIP contents.
- Copies of accepted read-only revisions are writable private workspaces. The source revision remains read-only and unchanged; publication still seals a separate snapshot.
- Rejected-snapshot cleanup restores file and directory writability before deleting the rejected copy. The regression also covers nested files and preservation of the original candidate.
- The tampering test explicitly makes its target writable before modifying it, so it tests hash-based tamper detection on both Windows and Linux.
- Real symlink tests skip only on Windows error 1314 (missing privilege). Other symlink errors remain failures. The directory escape test now explicitly creates a directory symlink.
- Six additional test cases cover exact UTF-8/LF bytes and hashes, nested snapshot manifests, writable copies of sealed sources, and unsafe path rejection.
- A GitHub Actions matrix covers Ubuntu and Windows on Python 3.11 and 3.12, including the suite and both offline commands.

The three local skips are the real symlink tests listed above. Skipping those tests does not grant the application symlink access or remove its rejection logic. To execute them locally, use a test session with Windows Developer Mode or symlink privilege, as described in the [Python documentation](https://docs.python.org/3/library/os.html#os.symlink). No system settings were changed by this fix. Live Docker and Gemma execution are still untested.

## Publication changes

- Expanded `README.md` with setup, architecture, acceptance workflow, configuration, CLI/API reference, troubleshooting, and contribution guidance.
- Extended `.gitignore` to exclude virtual environments, environment-file variants, and private-key files.
- Added this verification record.
- Updated `SOURCE_SHA256.json` to reflect the documentation and ignore-rule changes and include this record. The original release verification artifact is preserved.
