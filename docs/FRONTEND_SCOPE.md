# Operator console scope

The v0.6.0 console is packaged in `src/fluxos/frontend/` and served by FastAPI at `/ui/`. It uses ordinary HTML, CSS, JavaScript, and same-origin requests; no Node installation or frontend build is required. The root `/` remains a JSON service descriptor. `/docs` provides the full API schema.

| Control | Backend action | Model requests |
| --- | --- | --- |
| Initial page load | Read `/api/health` | None; key presence does not validate credentials. |
| CONNECT PROVIDER | Configure the app, then send a short readiness message through `/api/chat` | Real request, with fallback attempts if needed. |
| CHAT | Send the entered message to `/api/chat` | Real request; try configured models in order. |
| AGENT RUN | Submit project ID and task to `/api/gemma/run` | Real bounded coding loop using the primary model only. |
| RUN CONFLICT PROBE | Execute `/api/protocol-test` | None; temporary SQLite conflict demonstration. |

The provider configuration endpoint alone makes no model request. Its key and ordered model IDs live on the running FastAPI application's state, override that app's environment defaults, and disappear on server restart. It does not update environment variables or persist the credential. The password field is cleared after an attempted connection. The UI does not use browser storage.

The default console route lists `gemma-4-26b-a4b-it` and `gemma-4-31b-it`. Actual availability depends on the account. Coding runs deliberately use the first model without chat fallback. With only environment configuration, `GEMINI_MODELS` supplies an ordered list; otherwise `GEMMA_MODEL` or the built-in primary model is used.

The conflict probe compares a sequential last-write-wins dictionary with two observed conditional writes through the real SQLite kernel. It establishes the demonstrated stale-write rejection, not concurrent throughput or model usefulness.

The UI shows request results and publication status. It does not implement streaming, durable conversations, automatic stale repair, contract authoring, a file editor, or user authentication. Press Ctrl+Enter to submit; Enter inserts a newline. Coding acceptance still requires an operator-owned contract and real Docker. Developer tests and shared claims cannot grant `VERIFIED`.

Run on a trusted local machine. The [security boundaries](SECURITY.md) apply to the console and all API routes.
