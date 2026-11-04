# Seoul local beta implementation plan

> **For agentic workers:** Use superpowers:executing-plans to implement task-by-task.

**Goal:** Test Seoul-wide personalized topic cards, feedback and consented local learning without API keys.
**Architecture:** Existing adapt() remains the only publication gate. Pure TypeScript derives topic candidates from verified items; a separate Vue panel owns local profile/events. Existing filters/favorites and briefing schema remain compatible.
**Tech Stack:** Existing Vue 3, TypeScript, Vite, Node tests, Playwright/axe, Python stdlib.
**Spec:** User-approved conversation: 25 Seoul districts; residence and interests separate; age/carrier/interests; cards open related benefits; reasons and unknown eligibility; feedback; opt-in local events; synthetic aggregate tests only; no API/cloud setup or merge.

## Global constraints
- Work only in this existing checkout, no worktrees. No dependencies or service spending added.
- No synthetic public benefits, automatic approval, or inferred eligibility.
- No external log transmission, raw search strings, personal profile in share URLs, or credentials.
- Local event retention 30 days, maximum 500; profile ages 14–120 (under-14 learning deferred).
- Local records are experimental and are not all-user analytics or reports delivered to the operator.

## Review focus
- Corrupt/unavailable storage: browse works, failed persistence is reported.
- Expired/recheck data: recommendations disappear through existing adapter and live timer.
- Interest area != residence eligibility; keyword matching is explicitly candidate-only.
- Consent refusal/revocation: no event writes, purge existing events on withdrawal.
- Low sample feedback must not replace pinned interests or hide all available topics.

## Task 1: pure beta model
Files: frontend/src/beta.ts; frontend/tests/beta.test.ts.
Interfaces: Profile, LocalEvent, Topic; loadBeta/saveBeta; recordEvent; topicsFor(items,profile,events,now); summarizeEvents(events,now).
- [ ] Write tests for profile validation, 25 districts, consent/retention/cap, topic coverage, evidence gates, age/carrier candidate matching and ranking.
- [ ] Run node --test tests/beta.test.ts and observe missing implementation.
- [ ] Implement typed model with explicit enums, fail-closed storage validation, bounded local records; no raw search storage.
- [ ] Run npm test; expected all pass.

## Task 2: UI integration
Files: frontend/src/BetaPanel.vue, App.vue, BenefitCard.vue, style.css; frontend/tests/e2e/beta.spec.ts.
Interfaces: panel takes items/now; renders its own related BenefitCards; records only enum topics/actions; existing cards unchanged unless optional event used.
- [ ] Add browser tests for configure/card-open/feedback/consent/revoke/reset, storage failure, mobile/desktop axe, expiry and no outbound calls.
- [ ] Add collapsed beta panel after discovery results to preserve initial ten-second discovery and existing mobile first card visibility.
- [ ] Show all 25 selectable areas, age/carrier interests, local-only disclosure, feedback not sent notice, recommendation reasons and uncertainty.
- [ ] Use IntersectionObserver for visible topic exposures, once per panel session; exclude hidden/collapsed tabs.
- [ ] Run typecheck/build/browser tests in existing zero-spend CI if local npm DNS unavailable.

## Task 3: verification and delivery
Files: docs/qa/seoul-beta.md, docs/p0-backlog.md.
- [ ] Run full Python and Node suites, source policy check.
- [ ] Independent review of whole diff; fix substantive findings with regression tests.
- [ ] Create PR on exact current remote main, run existing CI (no deployment); collect screenshots and axe results.
- [ ] Document local-only limits, keyword ranking not AI, remaining source/API/log-server decisions.

## Execution ledger
- Local base a044815 has PR15 contents; remote main 2e672d7c699cb3381252eb1b82962c57f5f6d447.
- User already authorized implementation; continue without another plan approval.
- npm offline cache missing and online registry DNS unavailable; Node pure tests can run locally, build/browser checks use existing guarded GitHub CI.

- Task 1 complete: Node tests progressed from missing beta module to 46 passed; includes automatic topic replacement, pinned topics, consent, 30-day retention and malformed payloads.
- Task 2 implemented: Vue typecheck/build passed on CI head 8b22dde; 35/36 browser tests passed, including age input, mobile/desktop axe and screenshots. One test used check() while intentionally asserting failed consent stays unchecked; corrected to click().
- Review fixes: numeric v-model normalization; fail-closed consent withdrawal; cross-tab storage synchronization and consent recheck; conservative Seoul/nationwide scope labels. Added regression tests.
- Ruling: retain existing collectors/exports unchanged and scope only web display to Seoul; backend scope migration remains separate to preserve briefing consumers.
- Ruling: local feedback is not operator delivery; clearly label local-only until server integration is authorized.
- Ruling: use 20 exposures as an experimental threshold, not a validated recommendation model.
