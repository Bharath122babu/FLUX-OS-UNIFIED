# Hacktoberfest Hack Day Gwalior — Submission Checklist

Track 1 — Best Open-Source AI Project: original model harness and causal execution kernel; MIT licensed; real Gemma 4 provider implementation. Repository **must be made public on GitHub by the participant**.

Track 2 — Best Use of Gemma 4: actual `gemma-4-26b-a4b-it` function calls, image/sketch input, bounded multi-agent delegation, file creation and validation. To claim successful Gemma usage, **run with a real Google AI Studio API key before submission**. Tests here cover mocked API behavior only.

Before 4 PM IST on October 18, 2026:
- [ ] Install and run locally on the presentation laptop
- [ ] Test a live Gemma response and real tool call using your own API key
- [ ] Pull Docker image and verify Python unit tests inside an isolated test container (optional but strongly recommended)
- [ ] Collect and report real baseline vs FLUX Gemma runs if claiming performance improvement
- [ ] Confirm accurate language about causal claims and current limitations
- [ ] Publish all project source to public GitHub with LICENSE, README, demo screenshot
- [ ] Submit repository and select both prize categories in the MLH portal
- [ ] Practice 7-minute presentation with one judge-controlled field change

**Never** include an API key, `.env`, runtime SQLite files, or private user documents in the Git repository.
