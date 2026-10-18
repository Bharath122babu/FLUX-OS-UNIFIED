# Shared memory in the Gemma harness

The supplied v0.6 archive added kernel APIs. The final integration exposes a bounded subset through the existing Gemma function-calling loop, with no second database or supervisor model.

## Model tool contract

1. Call `read_shared_memory` with an exact JSON object pointer such as `/plan`. An absent final field returns `present: false` and `expected_hash: null`.
2. Call `patch_shared_memory` with `changes`, each containing exactly `path`, `expected_hash`, and a text `value`. The hash must match an earlier exact-field observation by this agent. Creation requires an observed absence.
3. The kernel validates all recorded causal reads, target field preimages, and active job fences in the same SQLite write transaction. It applies every operation or none.
4. The host updates this agent's witnesses using the exact committed result returned by that transaction. It never rereads a potentially newer head to justify its own edit. Later conflicting writes still make the candidate stale.

Model-facing patches allow 1–16 operations, values up to 8 KB of UTF-8 text, and read results up to 16 KB. Read a narrow field when the whole note store exceeds the response limit. The trusted Python `Memory.patch_fact` API supports up to 64 operations and JSON object values.

`record_shared_claim` takes a predicate, text value, and declared source. `read_shared_claims` returns visible assertions for the predicate. Different values are `DISPUTED`; a single visible value is `UNCONTESTED`. Neither is proof. Claim listings are advisory, not causal witnesses or independently authenticated evidence.

## Namespaces and lifecycle

- Normal API jobs use `shared:project:<project_id>` inside the existing principal scope.
- Standalone SDK runs without a project ID use a task namespace derived from the requirement identifier.
- Child workers receive the parent's namespace through a host-only constructor argument. Model tool parameters cannot select another project or arbitrary fact key.
- Later jobs on the same project reuse persisted notes. The inspection endpoint is `GET /api/projects/{project_id}/memory`; an empty inspection does not create a note fact.
- Notes and claims commit independently of source acceptance. They remain unverified and can survive a failed or draft coding run. They do not become accepted code or change the project head.
- Shared fact reads participate in candidate publication witnesses. Changed inputs can invalidate dependent artifacts and produce `STALE_REJECTED`. This release does not automatically repair stale projects or replay interrupted conversations.

## Worker cancellation and crash quarantine

API mutations carry the active job generation. Child mutations additionally carry their parent's generation. Both are checked under the same SQLite write lock as the mutation. A cancelled, completed, or reconciled job cannot append notes or claims using its old generation.

`Memory.reconcile_interrupted_jobs(scope)` remains an explicit trusted-coordinator operation. Stop previous workers before calling it. It quarantines work and increments generations; it does not replay uncertain external effects.

## Trusted Python example

```python
from fluxos.kernel import Memory, Principal

memory = Memory('.fluxos-example')
worker = Principal('worker', 'example', 1, frozenset({'reader', 'writer', 'agent'}))
memory.put_fact(worker, 'shared', {}, expected_version=0)
observed = memory.observe(worker)
observed.absent_fact('shared', '/plan')
observed.patch_fact('shared', [
    {'path': '/plan', 'expected_hash': None, 'value': 'implement the CLI'}
])
assert memory.validate_manifest(worker, observed.manifest())
```

An ordinary whole-fact writer must supply the current `expected_version` (zero for creation). Only trusted in-process coordinator principals may intentionally publish without a version precondition. The model never receives the coordinator role. Caller-created principal objects are not remote authentication.

## Verification

- `tests/test_shared_memory_v06.py` exercises the supplied kernel contention, classification, negative-read, claim, and recovery semantics.
- `tests/test_shared_tools.py` covers actual function-call parsing with a mocked provider, acceptance integration, inherited worker notes, stale-read rejection, project isolation, mutation fencing, and races after the exact own-write receipt.
- `scripts/shared_memory_stress.py` runs 20 workers over 12 trials, preserving 240 independent field edits and rejecting same-field races.
- `scripts/docker_acceptance_smoke.py` runs actual Docker commands and a scripted-model API workflow with two accepted revisions and shared-note reuse.

The hosted model configuration follows [Google's Gemma on Gemini API documentation](https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api). `GEMINI_API_KEY` supplies the credential; `GEMMA_MODEL` optionally overrides `gemma-4-26b-a4b-it`. Provider access is not established by a passing mock test or by credential presence.
