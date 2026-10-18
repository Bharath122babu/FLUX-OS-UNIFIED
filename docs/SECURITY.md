# v0.6.0 backend security boundaries

**STATUS: local single-host research system. NOT certified for untrusted production deployments.**

The trust boundary is operator-owned Python code + SQLite kernel versus model-proposed file writes, tool parameters and candidate processes. There is no cryptographically authenticated client identity or hardened separation between the trusted gateway and kernel. Use loopback only; never deploy to the public internet.

## Shared-memory tools

- Model-facing keys are derived by the host from the project or task identifier. Children inherit their parent's namespace. This is local project scoping, not authenticated multi-tenancy.
- Shared note patches require exact prior field reads, matching preimages, and validation of the complete recorded read set inside the SQLite write transaction.
- The exact committed patch receipt advances only the writer's own witnesses. A later competing write still fails final validation.
- API job and child/parent generation fences are checked in the same transaction as shared-note creation, patches, and claim append operations. Trusted SDK callers without a job remain responsible for their own lifecycle.
- Notes and claims persist separately from code acceptance and remain unverified. Claims are advisory and never substitute for independent black-box acceptance. Declared claim sources are not authenticated evidence.
- Project history and claim reads filter by clearance. Stored claim values are checked against their hashes before being returned or included in a conflict status.
- Reconciliation is an explicit trusted-coordinator operation after stopping old workers; it fences mutations and publication, but does not replay conversations or external effects.

## Verified by local tests

- A forged acceptance-result dictionary alone cannot authorize a publish; a trusted *in-process evaluator function* must execute on the sealed snapshot.
- Candidate bytes are sealed before evaluation and rehashed after evaluation and before SQLite publication. The kernel checks the accepted snapshot on commit and reads.
- An operator contract hash is checked after acceptance when the black-box runner supplies the contract path; contracts are scoped to `acceptance/<project_id>/cases.json`.
- Existing candidate file edits require SHA-256 preimages. Multi-file staged candidate writes reject mismatched preimages without leaking partial files in ordinary error paths.
- Docker-only command tool constructs no-network, resource-limited and unprivileged container invocations. These arguments were mock-tested; the daemon itself was **unavailable** for live execution.
- Unmediated model command reads are pessimistically witnessed against the entire registered source tree.
- Permission checks, job-generation ownership, project-head compare-and-set and causal manifests remain in SQLite.

## Not established / not secure by construction

- `run_tests` executes candidate Python in the unittest interpreter. That interpreter can be monkeypatched by candidate code and is therefore **development diagnostic only**. It NEVER grants independent acceptance.
- Filesystem permissions are not durable immutable object storage, and the local host running as the same UID can modify sealed paths. Hash validation detects tampering later; it does not make tampering impossible.
- Docker may have implementation/kernel/daemon vulnerabilities. Never mount secrets, host Docker sockets, or personal data in candidate containers. This release has **not** passed a live container penetration test.
- The API is loopback-only and lacks authenticated users, CSRF tokens for non-browser clients, tenant isolation, and rate limits. Its `gemma-demo` principal is trusted test scaffolding, not an identity system.
- Provider requests are synchronous; journaled events are diagnostic, NOT replay-safe conversation state. Crashes can leave orphaned candidate or sealed directories; cleanup is best-effort.
- No safe exactly-once protocol for external effectful tools; they are intentionally omitted.
- Context pollution/prompt injection can still cause bad model decisions despite system instructions and tool boundaries.
- A source read through an arbitrary program may not be fully observed. Conservative full-project witnesses are used for command-tool calls, not claimed precise provenance.
- JS/TS acceptance is not independent nor trusted; the strict acceptance contract only supports Python CLI stdin/stdout/exit codes.

## Required release gate for wider deployment

Authenticate identities, configure an isolated worker host, live Docker adversarial tests, immutable artifact storage, durable workflow recovery, tenant isolation, limits and observability, real model end-to-end testing, and cross-language acceptance. See `RELEASE_NOTES_v0.5.0.md`.
