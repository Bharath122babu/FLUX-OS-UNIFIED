# Verification record

Code revision: `17d7d162059ddc71accea2c0743c1edaea9639fa`.

[GitHub Actions run 39103660001](https://github.com/Bharath122babu/FLUX-OS-UNIFIED/actions/runs/39103660001) passed all four Windows/Ubuntu × Python 3.11/3.12 jobs. Each job passed **171 tests**. The Ubuntu 3.12 job additionally passed real Docker acceptance and the paired evaluator smoke: **B0 regenerated four units; F0 regenerated three and reused one**. That smoke used deterministic reference code and made **zero real model calls**. It is orchestration evidence, excluded from AI completion statistics.

The earlier complete local Windows run passed 167 tests with three symlink privilege skips. After the final metric and test additions, all nine evaluation tests passed in the focused rerun. CI then ran the complete final 171-test suite, including all symlink checks. The test suite reports a FastAPI/Starlette HTTPX deprecation warning; it did not fail validation.

`deterministic.json` contains the full three-seed, 50-writer matrix and all injected process exits. Its `provenance` records the base git revision, dirty checkout status and exact source hashes used during measurement. Do not rewrite that stamp to imply the experiment ran from a later clean revision.

The dashboard was built with the Data Analytics runtime, inspected at mobile and desktop widths, and checked for painted chart paths, working series toggles, table search and source inspection. Its pending live fields are null. Docker Desktop/WSL setup on the local PC is separate from these CI results. No paid pilot was executed for this record.
