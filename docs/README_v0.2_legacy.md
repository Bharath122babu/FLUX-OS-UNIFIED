## Original background and earlier instructions

# FLUX//OS
### A Causally Consistent Agent Runtime for Gemma 4

**Hacktoberfest Hack Day Gwalior × ABV-IIITM IEEE — October 18, 2026**

> One Gemma model. Multiple dynamically delegated agents. Versioned shared memory. Stale work rejected before it becomes authoritative.

**Status:** Patched and regression-tested **single-host research/hackathon prototype**, *not* production-grade multi-tenant security, and *not yet demonstrated to outperform a conventional Gemma harness*. This document distinguishes an independently reproducible deterministic experiment from real AI-powered execution.

## What it does

- **Gemma 4 native tool-calling agent** uses Google's documented `gemma-4-26b-a4b-it` Gemini API model ID. Without `GEMINI_API_KEY` it fails explicitly; no fake Gemma responses.
- **Dynamic workers:** the model may create a batch of 1–3 task-defined subagents (not predefined subject roles), executing simultaneously in separate file workspaces; the harness checks for merge conflicts. No recursive delegation.
- **Causal memory:** SQLite/WAL immutable versions, JSON-pointer witnessed reads, hashing, atomic commits, optimistic validation, projection-equivalent reuse, transitive invalidation, and selective repair support.
- **Authority checks:** existing *and* new record classifications are verified on overwrite, preventing a documented FLUX-v0.1 issue.
- **Integrity:** artifact content hashes are verified when checking status and reading.
- **Candidate publication gate:** Gemma edits private snapshots. Runs without operator-owned acceptance tests return inspectable **DRAFT** output; only independently passing acceptance suites create authoritative **VERIFIED** code artifacts. Rejected and stale candidates never overwrite canonical files.
- **Authority witnesses:** Derived records track the source classification and producer identity as well as the value hash, so permission upgrades invalidate older descendants.
- **Guarded tools:** UTF-8 source file inspection/editing plus optional test execution in a no-network, resource-limited Docker container. No arbitrary shell tool exposed to Gemma.
- **Local UI:** polished dashboard for dependency graph, event timeline, real file contents, changing requirements, recovery, and real model execution.
- **Synthetic baseline:** demonstrates two of three outputs being invalidated on a schema change while unrelated styles persist. These counts are **work units**, not measured model-token or wall-time performance wins.

## Quick start

Requirements: Python 3.11+, pip. Docker optional for safe test execution. Active internet/API key required for real Gemma model calls.

```bash
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -e '.[test]'
pytest -q
fluxos serve
```

Open **http://127.0.0.1:8765**. Bind only to localhost; the demo REST routes have *no authentication*.

If your environment has packages but no package index connection, you can temporarily use `PYTHONPATH=src python -m fluxos.cli serve` and `PYTHONPATH=src pytest -q`.

### Real Gemma 4 agent

Set a server-side key (do **not** paste an API key into the web UI or source code):

```bash
# macOS/Linux:
export GEMINI_API_KEY='your-key-here'
# Windows PowerShell:
# $env:GEMINI_API_KEY='your-key-here'
fluxos serve
```

Then use **Gemma Workspace** in the dashboard. The model must actually call tools to write files; the UI displays execution trace and **DRAFT/VERIFIED** release state. With no independent acceptance suite, code is retained under `.fluxos-drafts/` but is never committed as authoritative. The API model used is `gemma-4-26b-a4b-it`. If that model is unavailable for your account, the harness returns the provider error instead of silently switching models.

If running tests, install Docker and ensure the `python:3.12-alpine` image is locally available before the event:

```bash
docker pull python:3.12-alpine
```

Testing is deliberately unavailable when Docker is absent rather than silently executing model-generated code on the host.

### Run without any AI key

```bash
fluxos demo       # shows before → changed → repaired statuses
fluxos benchmark  # compares fixed work-unit counts (not real Gemma accuracy)
```

In the dashboard: **Start fresh → Change contract → Repair stale work**. You can enter your own valid identifier in **New API field**. The frontend and integration-test artifacts turn stale; independent styling remains current. Recovery writes genuinely changed project files, and the ledger records every transition. This is a deterministic **mechanics** demonstration; no LLM execution takes place in this tab.

### Independent acceptance gate (optional, but required to publish authoritative code)

An operator or user must author tests **before** starting the model. They must not be placed in the model-writable project. The local app looks for tests at `.fluxos/acceptance/test*.py` and mounts this directory read-only in the Docker test container. For an example goal such as creating `hello.py` with `greet() -> "hello"`:

```bash
mkdir -p .fluxos/acceptance
cp examples/acceptance/test_hello.py .fluxos/acceptance/test_hello.py
# Ensure Docker is running and python:3.12-alpine is available.
fluxos serve
```

Only if **at least one independent test is discovered and all pass** can the result receive `VERIFIED` and its snapshot reference become authoritative. If no test suite is provided, Docker is unavailable, or tests fail, the output is a **DRAFT**. Even `VERIFIED` means these specified tests passed—it is *not* proof of every part of the natural-language request or the model's general reliability.

`output["draft_snapshot"]` points to a non-authoritative local directory; `output["published_snapshot"]` is populated only for accepted results. The previous unchecked direct workspace-write behavior has been removed. The demo tab is a separate deterministic illustration, not a Gemma run.

## Repository

```text
src/fluxos/
  kernel.py       transactionally versioned causal memory kernel
  agent.py        Gemini API native function calls, dynamic agents, safe workspace
  demo.py         reproducible dependency-change experiment
  benchmark.py    honest work-unit comparison with caveats
  api.py          local-only FastAPI JSON endpoints and UI
  cli.py          serve / demo / benchmark
  web/            dashboard (vanilla HTML/CSS/JS, zero build toolchain)
tests/            adversarial, concurrency, API, mocked-Gemma tests
artifacts/        example benchmark JSON / dashboard screenshot
examples/acceptance/  trusted acceptance test example
tests/test_regressions.py  security, transitive-repair, snapshot and job-fence regressions
examples/         walkthrough and sample goal
docs/             architecture, risk register, judging script
```

## Fundamental decision boundary

`Gemma` decides **what to attempt**. The kernel decides **what may become authoritative**. No LLM confidence score is allowed to override a failed permission, integrity, or dependency check.

```text
Student task ──► Gemma tool loop ──► isolated workspace
                    │  └── dynamic worker batch (optional, max 3)
                    │         └── optimistic file merge
                    ▼
              Proposed artifact
                    ▼
          Causal commit boundary ──► ACCEPT / STALE / DENIED
                    ▼
           Current recorded artifact
```

Artifacts with passing structural checks are labelled **DECLARED_CURRENT**, not scientifically true or cryptographically proven to have complete provenance. Hidden reads are not observable in an in-process Python library. This prototype is **not** an execution sandbox for hostile Python modules, outside the optional limited Docker testing subprocess.

## What this does **not** yet provide

- No general performance uplift benchmark for Gemma 4 (not run here; no API key provided).
- No hardened deployed authentication, public hosting, distributed coordinator, or true process-separated state gateway. A loopback-origin/peer check is defense in depth, not remotely trustworthy authentication.
- No direct integration with public GitHub repository mutation or continuous deployment.
- No general semantic dependence discovery or proof of correct model reasoning.
- No exactly-once effect guarantee for payments, email, or other remote services. Such actions are not exposed.
- No full production Git three-way merge, cross-tenant safe API, or formally proven transactional protocol. Snapshots and SQLite live on the same host, and unreferenced snapshots after a crash require garbage collection.
- No time-travel rollback of real-world effects.

A public GitHub repo and event portal submission must still be created. For a responsible final pitch, demonstrate Gemma responding to a changing requirement **with a genuine API key**, and report the actual results of an A/B trial against a baseline.

## Reproducible benchmarks and verification

- `pytest -q`: **48 passing tests** in the released build (including 19 added adversarial regression cases); automated checks of authorization, stale commits, hash tampering, projection-sensitive preservation, concurrent writes, dynamic worker merge, API routes, and Google tool-calling protocol with deterministic mock responses.
- `fluxos benchmark`: tracked-invalidation fixed scenario (3 output units baseline; 2 repaired after a scoped field change). **Not a fair model benchmark**; it reports no fictional token savings.
- `docs/EVALUATION.md`: proposed matched-model evaluation protocol; run before making "Gemma performs better" claims.
- `docs/SECURITY.md`: current trust boundaries and known limitations.

## License and acknowledgments

MIT. The prototype uses standard SQLite MVCC-like transaction ideas, Python tool calling, Gemma 4 via Google's Gemini API, and lessons from open-source coding-agent runtimes. Credit to prior research on causal dependency tracking, software build graphs, and reliable state machines; those general ideas are **not claimed as inventions** here.

Additional source references and original-code limitations are documented in `docs/ARCHITECTURE.md`.

### Multimodal input for Track 2

Gemma Workspace accepts an optional screenshot or hand-drawn architecture sketch alongside the text goal. The server passes the actual image bytes as a Gemini API `inlineData` part, not as a fake caption. Current limits: PNG/JPEG/WebP only, 2 MB. The function-calling response still goes through the same guarded tool runner and causal commit checks.

## Patch release (October 17, 2026)

See [RELEASE_NOTES.md](docs/RELEASE_NOTES.md) for the detailed changes, threat-model limits, and regression cases. No live Gemma 4 performance advantage has been measured. All model-client tests use deterministic mocks.
