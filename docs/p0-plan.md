# Benefit Monitor 2.0 P0 implementation plan

Goal: discover a relevant, officially reviewed benefit without login in ten seconds.
Spec: Benefit_Monitor_PRD_v1_2026-11-04.md, supplied by the user; upstream main 988f222.

Architecture: Vue 3 + TypeScript + Vite static frontend consumes the existing public JSON. Python publication and mirror contracts stay unchanged. A separate standard-library assembler copies only frontend build output, briefing.json and briefing.md into a clean Pages staging directory. Existing Python HTML remains the rollback fallback.

Constraints: no new services, billing, paid APIs, analytics, collector requests or worktrees. Keep noindex, cron 0 16 * * *, public-repository/zero-spend gates, source allowlists and evidence rules. Existing ChatGPT/Codex and compute pricing is outside this project guarantee.

- [x] Adapter: first test rejection of stale/failed/unverified/future/expired/malformed data; KST date boundaries; explicit region semantics; AND search/filter; fee-neutral sorting. Implement pure TypeScript functions; use Node built-in tests.
- [x] UI: system font, blue/teal accent, one/two/three column cards, labeled search/selects, native expandable details, official links, live result count, URL and history synchronization. No inferred amounts, eligibility or inventory. Refresh time gates every second and on tab resume.
- [x] Packaging: first test clean staging preserves exact JSON/MD bytes and excludes private/runtime files; implement scripts/assemble_pages.py. Build frontend once before collector, assemble after success/failure publication. Mirror unchanged. PR validation must never collect, mirror or deploy.
- [x] QA: Python suite, TS typecheck/build, Node unit tests, local Chromium E2E on 360/390/768/1440 widths, all data states, keyboard/axe and contrast checks. Capture only clearly marked synthetic test data. If local dependencies are unavailable run the same commands in existing gated public Actions; report actual evidence and any skipped work.
- [x] Delivery: README run/rollback commands, exact verification record, P1/P2 backlog; feature-branch PR, no main merge.

Review focus: stale files with individually fresh records; duplicate source URLs; regional labels that do not mean nationwide; exact KST midnight and application cutoff; slow/invalid network responses and URL history.

Regional decision: filter exact reviewed labels/districts. 서울 includes explicit 서울 labels, 서울 source and named Seoul districts. Nationwide requires explicit 전국 label; an empty district list never means 전국. Selecting a district does not assert eligibility or include 전국/서울-wide notices implicitly.
