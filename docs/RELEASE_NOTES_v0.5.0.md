# v0.5.0 backend-only engineering release

## Goal

Adopt selective **engineering patterns** from OpenCode (proper tool contracts, bounded command execution, observable turn lifecycle, optimistic modifications) without importing OpenCode's entire service graph. Keep the single FLUX causal publication kernel.

## P0 fixes implemented and tested locally

| Gap | Remediation | New test |
|---|---|---|
| Tested A can publish untested B | Seal A before acceptance, accept only sealed hash, recheck under kernel transaction | Source mutation after sealing, sealed mutation during test, mutation before commit |
| Forged unit-test PASS | Accept only callback executed in trusted host on sealed snapshot; Python unittest diagnostics cannot authorize release | Forged PASS yields DRAFT |
| Global acceptance contract | Per-project trusted acceptance location; contract-hash recheck | Cross-project isolation, changed contract |
| Insufficient patching | Staged preimage-hash mutations with write/edit/delete/move, no partial candidate changes on validation failure | Positive patch and failed preimage, child file deletion |
| No command environment | Docker-only bounded Python/Node command execution, no host fallback; pessimistic full-source witnesses | Mocked command flags, timeout cleanup and bounded outputs |
| Source files >8KiB unavailable | Paginated line reads with exact file hash | 11,000-line fixture |
| Transient model failures fatal | Retry 408/429/5xx and transport transient faults before tools execute | Retry 503 and non-retryable 401 |
| No durable execution diagnostics | Append-only per-job model/tool/gate events in SQLite | Journal through modeled turn |

## Still open (must not be reported complete)

1. Live adversarial Docker testing: Docker binary/daemon unavailable in audit environment.
2. Real Gemma 4 end-to-end demonstration: no API credential/calls in release testing.
3. Persistent conversation state and safe replay of interrupted tool invocations.
4. Automatic model-driven stale repair.
5. MCP, long-running PTY, Git, JS/browser acceptance, production API authentication.
6. Same-Gemma head-to-head A/B evaluation.

## Trust boundaries

- `UnifiedGate.publish` is an in-process host function; `trusted_acceptance` must only be constructed by trusted operator code. Never deserialize a network-supplied callback or take acceptance status from model output.
- The current black-box contract executes candidate Python in a Docker container and compares host-owned exact stdout/exit code. The `Workspace.run_tests` unittest path remains developer feedback only, even when it prints PASS.
- Snapshot sealing sets read-only filesystem permissions but cannot stop a same-UID malicious trusted process or privileged local user. Hashes and kernel verification detect subsequent tampering when accessed; they are not immutable object storage.
- The candidate can run arbitrary code in the Docker-only command tool; do not provide sensitive host mounts or a privileged daemon. Image pulls are disabled in the tool so image provisioning is an explicit operator step.
- Model/tool journal records metadata and hashes, not a complete restorable transcript; no exactly-once external effects or crash replay is claimed.

## Reproduction

```bash
python -m pip install -e '.[test]'
pytest -q
fluxos unified-demo
```

A same-model benchmark and real Docker threat-model execution remain separate release gates.
