# Final v0.6 verification — October 18, 2026

This integration combines the supplied shared-memory release with the previously repaired Windows implementation and the new Gemma-facing shared-memory tools. Historical verification artifacts are retained separately.

## Local Windows checks

- Python 3.12.10, editable package installation with test dependencies.
- Full suite: **159 passed, 3 skipped, 0 failed** (162 collected cases).
- The skips are only real symlink creation tests when Windows reports error 1314. Unexpected symlink failures still fail the suite.
- One Starlette TestClient dependency deprecation warning remains.
- Deterministic shared-memory stress: 20 agents, 12 trials, 240 preserved disjoint edits, zero lost updates, one same-field winner and 19 rejected competitors.
- Unified demo and synthetic benchmark pass with zero model calls.
- The readiness script reports credential presence without printing a secret. On this host, both the Gemini credential and Docker CLI were absent.

## Automated cross-platform checks

The [GitHub Actions workflow](https://github.com/Bharath122babu/FLUX-OS-UNIFIED/actions/workflows/tests.yml) runs Python 3.11 and 3.12 on Windows and Ubuntu. It includes the full test suite, offline demos, and 20-worker contention simulation.

The Ubuntu Python 3.12 job also preloads the Python and Node images and runs the real Docker smoke script. That script requires actual successful container execution, independent acceptance on sealed code, two accepted project revisions, persisted shared notes, ZIP export, and rejection of wrong expected stdout. Its model is explicitly scripted and makes zero cloud API calls.

## Live Gemma readiness

```bash
python scripts/preflight.py
```

For a real independently verified coding run, the terminal launching the server needs `GEMINI_API_KEY`, a working Docker daemon, `python:3.12-alpine`, and an operator-owned acceptance contract. `node:22-alpine` is additionally needed for Node command tools. See the README for the complete setup and API request.

`GEMMA_MODEL` optionally selects a different accessible model. The default is `gemma-4-26b-a4b-it`. The health endpoint and readiness script report the configured model consistently. Key presence does not prove provider access or sufficient quota.

No live Gemma call has been made for this integration. Container smoke checks do not constitute security certification. No model-performance uplift, automatic stale repair, durable conversation replay, or production deployment guarantee is claimed.
