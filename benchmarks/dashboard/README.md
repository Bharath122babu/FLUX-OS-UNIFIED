# Benchmark dashboard

`DashboardContent.jsx` is the authored React composition for the Data Analytics dashboard runtime. `fluxos.evaluation.report` derives reviewed rows from saved JSON experiments; it does not contain sample performance figures.

The accompanying benchmark distribution includes a self-contained `benchmark-dashboard.html`. Open that file directly in a browser, or serve its directory with `python -m http.server`. It has no CDN or package-install requirement. Source inspection, chart legends, search and pagination remain available offline.

To rebuild with the Codex Data Analytics plugin installed:

1. Generate a snapshot with `python -m fluxos.evaluation.report --deterministic <result.json> --live <pilot/results.json> --output <snapshot.json>`.
2. Run the plugin's `scripts/prepare-data-app.mjs --surface dashboard --output <new-absolute-folder> --snapshot <snapshot.json>` using Node.
3. Read the generated `AGENTS.md`, copy this authored composition into `src/content/dashboard/DashboardContent.jsx`, and set `src/data.json`'s `buildStatus` to `complete` when finished.
4. Run `scripts/data-app.mjs build --project-dir <folder> --separate-data`, followed by `export-offline --project-dir <folder> --output <folder>/.data-app-offline/exports/benchmark-dashboard.html` from that plugin.

Keep the generated stable dashboard identity when updating an existing artifact. Raw experiment records in `benchmarks/results/` are authoritative; an unavailable live completion rate or actual billed cost stays null. This dashboard is an evaluation artifact, not a frontend for the FLUX API.
