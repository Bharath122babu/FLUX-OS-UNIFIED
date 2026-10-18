# FLUX//OS v0.3.1 — Finalization maintenance release

This version preserves the 0.3 unified architecture. It removes unused imports,
removes an unused validation argument, eliminates an import-time API side effect,
and drops stale v0.2 binary screenshots. It makes source-tree registration atomic,
bounds file reads and workspace manifests, uses validated snapshot copies at the
publication gate, enforces structured REJECT outcomes for invalid workspaces,
adds best-effort Docker timeout cleanup and fixes IPv6 Host parsing.

**Testing:** 75 passing local pytest tests including 12 new release regressions.
Old tests and provenance/audit notes remain available.

**Unverified:** real Gemma 4 improvement, Docker adversarial testing, hostile
Python test interpreter security, and durable distributed recovery. This is not
a general-purpose production system.
