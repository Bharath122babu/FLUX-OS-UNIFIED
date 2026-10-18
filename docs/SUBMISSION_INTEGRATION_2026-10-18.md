# Final-submission integration — 18 October 2026

Source archive: `FLUX-OS-UNIFIED-v0.6.0-FINAL-SUBMISSION.zip` supplied by the project owner.

Archive SHA-256: `df0a7089b9b2989608508501fc6fb23c64297759c9e05b8c7b657e4eb354dea3`.

The archive adds an operator console, in-app provider configuration, conversational chat, a real SQLite conflict probe, and project overview documentation. Those features were integrated onto the existing repository rather than replacing its newer kernel, agent, gateway, evaluation framework, and regression tests with older archive copies.

Preserved behavior includes shared-memory model tools, own-write receipts, project scoping, job-generation fences, clearance filtering, source and sealed-snapshot checks, Windows snapshot handling, Docker acceptance, and protocol 2 evaluation budgets and retries. Existing measured protocol 1 pilot records remain unchanged.

Integration adjustments:

- Package HTML, CSS, and JavaScript in the wheel and serve them at `/ui/`; preserve the root JSON descriptor.
- Keep configured credentials on each app's state without disk persistence or process-environment mutation.
- Offer the existing Gemma primary model and a second Gemma chat fallback. Coding runs keep a single primary model.
- Sanitize chat failure responses and omit model thought parts from displayed chat text.
- Apply the existing loopback, Host, and same-origin checks to the new endpoints.
- Implement the advertised Ctrl+Enter shortcut and describe the dictionary comparison accurately.
- Replace outdated backend-only README claims with console setup, architecture diagrams, acceptance workflow, and measured benchmark denominators.

## Validation

Mock provider tests make no paid model calls. The previously completed eight-attempt Gemma pilot is historical evidence, not a new test of the console or protocol 2.

- Full Windows Python 3.12 suite: **175 passed, 3 skipped, 0 failed** (178 collected cases). The skips are real-symlink tests requiring Windows privileges. One upstream Starlette/httpx deprecation warning remains.
- Four console regression tests cover packaged asset routes, the actual kernel probe, cross-origin rejection, app-local credentials, chat fallback/error sanitization, and coding-model selection without fallback.
- JavaScript syntax check: passed with Node.
- Browser check: console loaded and the conflict probe displayed `PROTOCOL PASS`, `COMMITTED`, and `STALE_REJECTED` with no provider key. The README screenshot records this local check.
- Wheel built and force-installed into a separate validation environment. Packaged HTML/JS/CSS, the API conflict probe, and evaluation protocol 2 passed import/route checks from the installed wheel.
- Real Docker acceptance smoke: Python and Node commands passed; two revisions each passed three acceptance cases; shared notes were reused; ZIP export passed; incorrect stdout was rejected. Zero live model calls.
- Real Docker paired reference evaluation: B0 regenerated four units; F0 regenerated three and reused one. This verifies orchestration with scripted reference code, not AI performance. Zero live model calls.
- README relative links and the saved JPEG preview were checked; three Mermaid diagrams describe architecture, publication flow, and stale-write rejection.
