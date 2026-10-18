# FLUX//OS v0.6.0 — Source-level shared-memory engineering decisions

**Scope:** Four upstream repositories compared at *relevant core implementation paths*. This is **not** a claim that every line of each entire upstream repository was audited. The upstream repositories were inspected through public GitHub source access; their full ZIPs were not supplied in this turn. FLUX v0.5.0 source was extracted from the provided project release archive, upgraded and tested. No upstream source code was copied into FLUX.

## Upstream implementation references

1. **MemTX:** [`src/memtx/memtx_manager.py`](https://github.com/lxy1134/MEMTX_/blob/main/src/memtx/memtx_manager.py) (inspected SHA `79bc539b143b3c46e5f0ca94e24e3751c371847d`), [`conflict_detector.py`](https://github.com/lxy1134/MEMTX_/blob/main/src/memtx/conflict_detector.py) (SHA `c87237b89ce8e3180d4f6ac4302ec38688a8b551`), [`dependency_graph.py`](https://github.com/lxy1134/MEMTX_/blob/main/src/memtx/dependency_graph.py) (SHA `95c97aba9da859bce61015c5fae3ba2e2ce31982`). MemTX stages writes and compares concurrent claims, explicitly models belief state transitions and propagates invalidations. Its reviewed manager constructs an in-memory `_store` of records and maintains `_txns`, while FLUX uses SQLite transactional heads and versioned artifacts. **Decision:** adopt *semantic separation* of contradictory claims from causal currentness, but not MemTX's additional belief-state manager or its heuristic source-authority winner as automatic truth.

2. **Letta Code:** [`src/skills/builtin/managing-shared-memory/SKILL.md`](https://github.com/letta-ai/letta-code/blob/main/src/skills/builtin/managing-shared-memory/SKILL.md) (SHA `70fbb88a566bc6404ad620fe695e3c2b9a727c90`). Shared memory is a Git repository mounted for multiple agents; commits are pushed after a turn, and conflicting pushes receive a pull/rebase and bounded retry. **Decision:** maintain durable, observable revision identities and explicit conflicting writes, but retain FLUX's causal read witnesses rather than relying on Git diff/merge as proof of semantic validity. The Letta source inspected here is its public shared-memory workflow specification, not a complete runtime trace.

3. **Graphiti:** [`graphiti_core/graphiti.py`](https://github.com/getzep/graphiti/blob/main/graphiti_core/graphiti.py), [`graphiti_core/utils/maintenance/edge_operations.py`](https://github.com/getzep/graphiti/blob/main/graphiti_core/utils/maintenance/edge_operations.py) (SHA `0b6a0d852e414f17a6f4d95fd877aae1666dfdb5`). Graphiti uses temporally evolving graph facts, source episodes, extracted relationships, deduplication and resolution paths. **Decision:** keep assertion provenance and avoid converting conflicting evidence into a single 'true' value; do *not* add an LLM-based temporal extraction pipeline inside the critical commit path for the hackathon.

4. **Automerge:** [`rust/automerge/src/transaction/inner.rs`](https://github.com/automerge/automerge/blob/main/rust/automerge/src/transaction/inner.rs) (SHA `0e92b8844b1a08f446522e7bc2935eae861bbd38`). Transactions carry actor identity and dependency-frontier hashes and commit operation sets. **Decision:** implement a small atomic field-level conditional patch instead of importing a complete CRDT implementation. Disjoint changes can safely accumulate if their observed field values remain unchanged; conflicting edits to the same field fail. CRDT reconciliation is not a semantic consistency oracle.

## FLUX source-level changes

| Observed FLUX v0.5 defect | New code | Invariant / test |
| --- | --- | --- |
| Blind whole-fact writes silently lose concurrent edits | `kernel.Memory.put_fact(..., expected_version=...)` with mandatory preconditions for all non-`coordinator` roles | An agent without `expected_version` is refused; a stale expected version fails transactionally |
| 20 different agent fields silently overwritten | `kernel.Memory.patch_fact(changes, read_manifest=...)` using JSON pointers, preimage hashes, single `BEGIN IMMEDIATE` commit | 20 simultaneous independent patches preserve all 20 field changes; conflicting same-field patches fail |
| Overlapping partial edits may alter inconsistent state | Patch validates all preimages before applying any operation; overlapping paths are prohibited | All-or-nothing failure, no partial field publication |
| Hidden field absence not tracked | `Observation.absent_fact()` and dedicated negative witness hash | The introduction of the previously absent key makes dependent work stale; unrelated edits keep absence valid |
| Contradictory claims can both look 'current' | `Memory.record_claim` / `Memory.claims` append-only conflicting-assertion view inside the same SQLite DB | Contradictions reported `DISPUTED`, not automatically resolved or called verified; original evidence/source labels retained |
| Claim/privacy side channels | Claim statuses filtered to principal's clearance; `Memory.project_history` filters project revisions by artifact classification | Secret claim and secret revision metadata are not returned to lower-clearance readers |
| Crash leaves a job marked RUNNING | `Memory.reconcile_interrupted_jobs()` marks orphan jobs `INTERRUPTED` and increments generation | Old worker cannot publish with previous generation; NO replay of uncertain tool effects |

### Trust boundaries that must not be blurred

- The `coordinator` role is reserved for **trusted in-process authoritative inputs**, including user requirement changes and controlled test fixtures. An agent principal must not receive this role. The caller-created `Principal` object is **not authentication**; sandbox and API policies must prevent untrusted code from constructing arbitrary principals or accessing SQLite.
- An agent's conditional fact patch may include a `read_manifest`; when supplied it is checked in the same write transaction. It cannot prove that the model considered every implicit input, or that the claimed result is true.
- `record_claim`'s `source` is a **declared evidence identifier**, not independently verified evidence. `UNCONTESTED` means no visible conflicting explicit claim; it does **not** mean `VERIFIED`, complete, or true. Claims cannot automatically resolve natural-language paraphrases or ontology equivalence.
- Conditional field edits currently support JSON **objects**, not array CRDTs, remote eventually consistent replicas, full semantic three-way merge or distributed consensus. Source snapshots and published workspace budgets remain bounded.
- The job-recovery operation is a **fence and quarantine**, not safe automatic replay. It must be run only by the coordinator after older workers are stopped. External effects can remain outcome-unknown.
- Real Gemma calls, real Docker adversarial runs, internet-capable MCP integrations and measured performance uplift are outside these tests.

## Reproducible checks

```bash
python -m pip install -e '.[test]'
pytest -q
python scripts/shared_memory_stress.py
fluxos unified-demo
```

The new adversarial tests live in `tests/test_shared_memory_v06.py`, including randomized multi-trial path disjointness, classification boundaries, negative dependencies, multiple writers and an explicit low-clearance metadata denial.

## Stop/go decision

**Conditional GO** for advancing the local shared-memory kernel beyond v0.5. **NO-GO** for claiming perfect multi-agent behavior, complete semantic truth, general collaborative editing, production security, automatic crash recovery, or proven Gemma advantage. Continue with a real-model scenario and an equal-budget baseline when model access is available.
