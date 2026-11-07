# AI 교차 조사·자동 공개 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** AI가 후보마다 공식 문서 여러 개를 대조해 조사하고, 고정 기준(현재 유효성 중심)을 넘는 결과를 자동 공개하며, 사용자가 어드민 페이지에서 바로 내릴 수 있게 한다.

**Architecture:** 비용 원장을 "누적 $5·200회·14일"에서 "월 $15"로 바꾼다. 조사 입력에 관련 공식 문서를 최대 3개 더한다. 결정론적 판정 모듈이 자동 공개 기록을 만들어 `briefing-data`에 평문으로 둔다. 모든 공개 경로(일반 수집 배포, AI 재배포, snapshot 재검사)가 이 기록과 내림 목록을 같은 함수로 재검사해 공개한다. 무료 일일 수집이 공개 항목의 원문을 매일 다시 확인한다.

**Tech Stack:** Python 3.12 표준 라이브러리, Vue 3 + TypeScript(Vite), GitHub Actions, GitHub REST API(contents, actions), Claude Haiku 5.5(Messages API, 구조화 출력).

**Spec:** `docs/superpowers/specs/2026-11-07-ai-cross-check-autopublish-design.md`

## Global Constraints

- 작업 위치: `~/personal/benefit-monitor/.maintenance/p0-source`, 브랜치 `feat/ai-cross-check-autopublish`. main 머지는 사용자 승인 후에만.
- Python 표준 라이브러리만 사용. 모델은 `claude-haiku-5-5` 고정, 요율 카드 `('0.10','0.50')` 그대로.
- 월 상한 `MONTHLY_CAP = 15_000_000` microUSD(KST 월 기준). 평생 누적 상한 없음. 원장 행은 지우거나 다시 쓰지 않는다.
- 하루 요청 상한: 조사 20, 주제 1, 문법 시험 2.
- HTTP 상한은 workflow 실행 1회 기준 100 이하(`sources/_config.json`의 `max_http_requests`와 AI 몫 합산). robots·크롤 지연·리다이렉트 금지(`OfficialReader`) 준수.
- 추가 문서는 후보당 최대 3개, 허용 도메인은 `sources.yaml` 전체 출처 도메인 합집합.
- 상시형 최근성 90일. 신선도 30시간. 공개 기준 판정은 호스트 코드만 한다(모델 문장 사용 금지).
- 화면 문구: 자동 공개 표시 `AI 정리 · 공식 원문 {N}곳 대조`, 어드민 크레딧 소진 표시 `AI 조사 중지: 크레딧 소진`.
- 어드민 토큰은 브라우저 `localStorage`에만 두고 `api.github.com` 외에는 보내지 않는다.
- 사람 승인 항목(`public/verified.json`)과 축제(`festivals`)는 이 기능이 바꾸지 않는다.
- 로직 변경 뒤 `python -m unittest discover -s tests -v`, 프런트는 `npm test && npm run build`, 마지막에 E2E(`BENEFIT_TEST_BROWSER_CHANNEL=chrome npx playwright test`).

## Review Focus

1. **연도 없는 날짜·지난 연도**("11월 15일까지", 2025년 차수 원문): 자동 공개되지 않아야 한다. Task 5에서 테스트한다.
2. **같은 글이 주소만 다른 두 문서**(모바일·PC 주소, 쿼리 차이): 교차 확인 2곳으로 세면 안 된다. 본문 해시 기준으로 1곳이다. Task 5에서 테스트한다.
3. **원문은 그대로인데 종료일이 오늘 지남**: 그날 공개 JSON에서 빠져야 한다. Task 6에서 테스트한다.
4. **AI 실행이 이틀 연속 실패**: 30시간 넘은 자동 항목은 숨기고, 사람 승인 항목은 그대로 둔다. Task 6에서 테스트한다.
5. **어드민에서 내린 행사가 새 URL로 재게시**: 제목+주최 매칭으로 재공개를 막는다. Task 5에서 테스트한다.

---

### Task 1: 월 상한 원장

**Files:**
- Modify: `benefit_monitor/trial_budget.py`
- Modify: `benefit_monitor/cloud_state.py:40-70, 170-185, 220-226`
- Modify: `benefit_monitor/cloud_daily.py:110-130`
- Modify: `benefit_monitor/ai_daily.py:20-55`
- Modify: `public/ai-cloud-trial.json`, `ai-automation.json`
- Test: `tests/test_monthly_budget.py`; 기존 `tests/test_cloud_state.py`, `tests/test_cloud_daily.py`, `tests/test_claude_trial.py` 갱신

**Interfaces:**
- Produces: `trial_budget.MONTHLY_CAP: int = 15_000_000`, `TrialBudget.month_exposure(state, now) -> int`(KST 월에 `started_at`이 속한 행의 노출액 합), `TrialBudget.summary()`에 `month_exposure_microdollars`, `month_remaining_microdollars` 추가. `MAX_REQUESTS`, `MAX_RUN_DAYS`, `CAP`은 삭제. 다른 모듈은 `MONTHLY_CAP`만 쓴다.
- Produces: 원장 상태 `cap_microdollars == MONTHLY_CAP`, `cap_kind == 'monthly'`, `max_requests` 키 제거. 기존 36행은 그대로 유효하다.
- Produces: `CloudSession.apply_limit_revision()`이 `LIMIT_REVISION = 2`에서 위 구조로 한 번 올린다. `expires_at` 키는 남기되 `None` 허용, 실행일 수 상한 없음.

- [ ] **Step 1: Write the failing tests** — `tests/test_monthly_budget.py`
  - `test_reserve_blocks_only_when_month_cap_exceeded`: 10월 행 14_999_000 + 11월 예약 2_000 → 성공. 11월 행 14_999_000 + 예약 2_000 → `ValueError('monthly budget exhausted')`.
  - `test_legacy_ledger_upgrades_without_rewriting_rows`: `cap_microdollars=5_000_000, max_requests=200`인 36행 원장 → revision 적용 뒤 rows가 바이트 단위로 같고 `cap_kind=='monthly'`.
  - `test_more_than_200_rows_valid`: 250행 원장 `_validate` 통과.
  - `test_no_run_day_limit`: `days` 30개 control이 `validate_control` 통과, `mark_day` 성공.
  - `test_halted_still_blocks`: `halted=True`면 예약 거절(기존 유지).
- [ ] **Step 2: Run** `python -m unittest discover -s tests -p "test_monthly_budget.py" -v` → FAIL
- [ ] **Step 3: Implement** 원장 파일 크기 상한을 1 MiB에서 8 MiB로, `cloud_state` 응답 상한도 같은 수준으로 올린다. `validate_control`의 `len(days)>MAX_RUN_DAYS`, `expiry<=bound` 검사를 제거하거나 `None`을 허용한다. `cloud_daily` 중단 조건은 `trial_budget_limit`(월 상한 도달)만 남긴다. `ai_daily`의 `trial_expires_at`, `MAX_RUN_DAYS` 분기를 제거한다. `public/ai-cloud-trial.json`에 `limit_revision: 2`, `expires_at: null`을 넣는다.
- [ ] **Step 4: Run** 전체 `python -m unittest discover -s tests -v` → PASS (갱신한 기존 테스트 포함)
- [ ] **Step 5: Commit** `feat(budget): 누적 $5·200회·14일 상한을 월 $15 상한으로 교체`

### Task 2: 하루 요청 상한 20건과 크레딧 소진 처리

**Files:**
- Modify: `benefit_monitor/claude_trial.py:175-192`(HTTP 오류 처리)
- Modify: `benefit_monitor/cloud_daily.py:150-205`
- Modify: `benefit_monitor/ai_daily.py:43-45`, `benefit_monitor/cli.py:18`, `benefit_monitor/ai_review.py:40`
- Modify: `.github/workflows/ai-daily.yml`(필요 시 annotation만)
- Test: `tests/test_credit_exhausted.py`, 기존 `tests/test_ai_daily.py` 갱신

**Interfaces:**
- Consumes: Task 1 `MONTHLY_CAP`.
- Produces: `claude_trial.is_credit_exhausted(status: int, body: str) -> bool`(HTTP 400이고 본문에 `credit balance`가 있으면 True). 이때 `budget.fail(digest, 'credit_exhausted', detail, halt=False)`.
- Produces: `cloud_run(...)` 결과 `{'status':'credit_exhausted','day':day}`. 그날 day 기록은 `failed`로 남고, `exit_code`는 1을 돌려 Actions가 실패 알림을 보낸다. 다음 날은 정상 시도한다.
- Produces: 하루 후보 상한 `max_ai_candidates_per_day: 20`(검증 범위 1..20), `review_candidates(max_candidates)` 범위 1..20.

- [ ] **Step 1: Write the failing tests**
  - `test_credit_error_does_not_halt`: 가짜 400 응답 본문 `{"error":{"type":"invalid_request_error","message":"Your credit balance is too low to access the Anthropic API."}}` → 원장 `halted is False`, 행 `error_code=='credit_exhausted'`.
  - `test_other_400_still_halts`: 다른 400 본문 → `halted is True`(기존 유지).
  - `test_cloud_run_reports_credit_exhausted_and_next_day_runs`: 첫날 결과 `status=='credit_exhausted'`, `exit_code==1`. 다음 날 `mark_day` 가능.
  - `test_daily_candidate_limit_20`: policy 20 허용, 21 거절.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** 크레딧 소진이 감지되면 그날 남은 조사를 멈추되 이미 받은 결과는 저장한다. 주제·공개 단계는 그대로 진행한다(이미 공개된 항목 유지). `ai-automation.json`의 `max_ai_candidates_per_day`를 20으로 바꾼다.
- [ ] **Step 4: Run** 전체 테스트 → PASS
- [ ] **Step 5: Commit** `feat(ai): 하루 조사 20건, 크레딧 소진 시 중단 없이 건너뛰기`

### Task 3: 관련 공식 문서 수집

**Files:**
- Create: `benefit_monitor/cross_sources.py`
- Modify: `benefit_monitor/ai_review.py:40-80`(host 문서 목록, signature, 저장 입력 검사)
- Test: `tests/test_cross_sources.py`

**Interfaces:**
- Produces: `cross_sources.related_urls(doc: dict, candidate: dict, peers: list[dict], domains: set[str], limit: int = 3) -> list[str]`. 순서는 (1) 원문 HTML의 `<a href>` 중 `official(url, domains)`이고 원문 URL과 다른 것, (2) 같은 `source`의 다른 후보 중 제목 유사도(공백 제거 문자 2-gram Jaccard ≥ 0.5)가 높은 순. 중복 URL을 빼고 최대 `limit`개.
- Produces: `cross_sources.allowed_domains(sources: dict) -> set[str]`.
- Consumes: `OfficialReader.read(candidate) -> doc`(기존). 추가 문서도 `reader.read({'source': <그 도메인을 가진 출처 id>, 'url': u, 'title': ''})`로 읽는다. 실패한 문서는 건너뛰고 `failures`에 기록한다.
- Produces: `review_candidates`의 host `documents`는 원문을 첫 번째로 두고 최대 4개다. 문서 본문 해시가 같은 문서는 하나만 남긴다. `signature`는 모든 문서 `body_hash`를 정렬해 포함한다. 허용 목록 밖 링크는 host의 `unverified_links`(최대 10개)에 기록만 한다.

- [ ] **Step 1: Write the failing tests**
  - `test_links_inside_body_on_allowlisted_domains_only`: `<a href="https://news.seoul.go.kr/x">`, `<a href="https://blog.example/y">`, 원문 자기 링크 → `['https://news.seoul.go.kr/x']`.
  - `test_peer_titles_ranked_by_similarity`: 제목 "어르신 10% 할인 시니어 동행상점" vs peers "시니어 동행상점 90곳 어디?"(채택), "청년 면접실"(제외).
  - `test_limit_and_dedup`: 링크 5개 → 3개, 중복 없음.
  - `test_host_documents_dedup_by_body_hash`: 같은 본문 두 URL → documents 1개만.
  - `test_http_budget_exhaustion_keeps_original_only`: 예산 소진 시 원문 1개로 조사 입력 생성, 실패 기록 1건 이상.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** `OfficialReader`가 원본 HTML을 노출하지 않으면 `read()` 반환에 `links: list[str]`(본문 추출 전 HTML에서 뽑은 절대 URL, 최대 50개)를 추가한다. `research_reason` 문구를 "공식 원문 여러 곳을 대조해 …"로 바꾼다.
- [ ] **Step 4: Run** 전체 테스트 → PASS
- [ ] **Step 5: Commit** `feat(ai): 조사 후보마다 관련 공식 문서 최대 3개를 함께 수집`

### Task 4: 조사 출력에 게시일과 날짜 규칙

**Files:**
- Modify: `benefit_monitor/research_guard.py:5-8`(FIELDS에 `published_at` 선택 필드)
- Modify: `benefit_monitor/wire_format.py`(`published_at` 값 규칙: `DATE_OR_EMPTY`, start 칸 사용)
- Modify: `docs/ai/prompts/research-system.md`
- Modify: `docs/ai/schemas/research-extraction-v3.schema.json`(필요 시)
- Test: `tests/test_wire_format.py`, `tests/test_research_extraction.py` 갱신

**Interfaces:**
- Produces: 조사 결과 claim `field == 'published_at'`, value `'YYYY-MM-DD'`, 근거 조각 필수. 원문에 게시일·수정일이 없으면 `unknown`이다.
- Produces: 프롬프트 규칙 세 가지.
  - 연도 없는 날짜는 event_period·application_period를 `unknown`으로 두고 이유에 원문 날짜를 적는다.
  - 문서끼리 값이 다르면 `disputed`로 두고 양쪽 조각을 근거로 단다.
  - "종료·마감·결과 발표·지난 차수" 문구가 있으면 restrictions에 그 조각을 근거로 남긴다.

- [ ] **Step 1: Write the failing tests**
  - `test_published_at_requires_date_and_segment`: `'2026-10-30'`+조각 → 통과, `'10월 30일'` → `ValueError('invalid period format')`.
  - `test_multi_document_segments_map_to_their_document`: d1·d2 조각을 함께 근거로 단 claim → evidence `source_ref`가 각 문서 id.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** 전체 테스트 → PASS. 스키마 sha가 바뀌므로 다음 실행에서 문법 시험이 자동으로 한 번 나가는지 `test_claude_trial` 기존 시험 경로로 확인.
- [ ] **Step 5: Commit** `feat(ai): 조사에 게시일 필드와 다문서·연도 규칙 추가`

### Task 5: 자동 공개 판정

**Files:**
- Create: `benefit_monitor/auto_publish.py`
- Modify: `benefit_monitor/ai_review.py`(검증된 조사 결과마다 판정 호출, 결과를 `cache/ai_publish/decisions.json`에 저장)
- Test: `tests/test_auto_publish.py`

**Interfaces:**
- Consumes: 조사 결과(`research-extraction-v3` 정규화 draft), host(`documents` 최대 4개), `now`, 내림 목록.
- Produces: `auto_publish.decide(draft: dict, host: dict, now: datetime, takedowns: list[dict]) -> dict`. 반환 `{'publish': bool, 'reasons': list[str], 'record': dict | None}`. `reasons`는 실패 코드 목록이다. 코드: `contract`, `disputed`, `core_missing`, `cost_missing`, `no_current_evidence`, `single_source`, `year_trap`, `past_signal`, `taken_down`, `stale_check`.
- Produces: `record` 스키마(공개 기록 1건):
  `{schema_version:1, candidate_id, source, url, title, summary, conditions, fee_status, districts, valid_from, valid_until, deadline_at, validity_kind:'fixed'|'ongoing', labels, payment_terms, review:{kind:'ai_auto', documents:[{url, body_hash, title}], document_count, checked_at, published_at|None, basis:{period_quotes:[...], operating_quotes:[...]}}, title_key}`.
  `title_key`는 제목과 주최 기관을 정규화(공백·괄호·연도 제거, 소문자)해 만든다.
- Produces: `auto_publish.PAST_SIGNAL = re.compile(r'종료|마감되었|마감됨|결과\s*발표|지난\s*(?:차수|행사)|\d{4}년\s*(?:행사|차)\s*(?:종료|결과)')`. 이 정규식은 문서 본문 전체에 대해 호스트가 검사한다.
- Produces: `auto_publish.takedown_matches(record_or_candidate: dict, takedowns: list[dict]) -> bool`(candidate_id 또는 title_key 일치).

판정 규칙(스펙 C 그대로, 모두 만족해야 publish):
1. `contract`: draft 계약 검사 통과(기존 `evaluate_draft` valid).
2. `disputed`: 어떤 claim도 `disputed`가 아니다.
3. `core_missing`: summary, conditions, fee_status, eligibility가 `supported`다. `cost_missing`: fee_status가 `paid`·`mixed`·`conditional`이면 cost_details 또는 payment_conditions가 `supported`다.
4. `no_current_evidence`
   - 기간형: event_period.end 또는 application_period.end가 연도 포함 날짜이고 오늘(KST) 이후다.
   - 상시형: 종료일이 없고, `published_at`이 `supported`이며 오늘-90일 이후다. 서로 다른 본문 해시 문서 2개 이상이 summary 또는 conditions 근거로 쓰인다.
5. `single_source`: 기간형은 종료일 근거 조각이 서로 다른 본문 해시 문서 2개 이상에서 나온다. 상시형은 4번 조건과 같다.
6. `year_trap`: 종료일 연도가 오늘 연도·다음 연도가 아니다. 또는 `published_at`이 365일보다 오래됐다. `past_signal`: 어느 문서 본문이든 `PAST_SIGNAL`이 맞는다.
7. `taken_down`: `takedown_matches` 참.
8. `stale_check`: 모든 문서의 `retrieved_at`이 `now-30h` 이후다.

- [ ] **Step 1: Write the failing tests** (`tests/test_auto_publish.py`, 합성 draft·host 픽스처)
  - `test_period_item_with_two_documents_publishes`: 종료일 2026-11-30, d1·d2(다른 해시)가 같은 종료일 근거 → `publish True`, `record['review']['document_count']==2`.
  - `test_year_less_date_is_held`: event_period unknown(연도 없음) + published 없음 → `'no_current_evidence' in reasons`.
  - `test_last_year_round_is_held`: 종료일 2025-11-30 → `no_current_evidence` 또는 `year_trap`.
  - `test_same_body_two_urls_counts_once`: d1·d2 본문 해시 같음 → `'single_source' in reasons`.
  - `test_past_signal_in_any_document_holds`: d2 본문에 "행사가 종료되었습니다" → `'past_signal' in reasons`.
  - `test_ongoing_needs_recent_published_and_two_docs`: 상시형, published 2026-10-01, 두 문서 → publish. published 2026-06-01 → `no_current_evidence`.
  - `test_takedown_blocks_by_id_and_title_key`: 같은 candidate_id → `taken_down`. 다른 URL이지만 같은 제목+주최 → `taken_down`.
  - `test_disputed_or_missing_core_holds`: 각각 해당 코드.
  - `test_paid_without_cost_holds`: fee paid, cost unknown → `cost_missing`.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement** `ai_review`는 `validated_draft`일 때 `decide`를 부르고, publish면 record를 `cache/ai_publish/approved.json`(candidate_id 키 dict)에 넣는다. hold면 `decisions.json`에 reasons를 남긴다. 검토 대기 행은 지금처럼 남긴다.
- [ ] **Step 4: Run** 전체 테스트 → PASS
- [ ] **Step 5: Commit** `feat(ai): 현재 유효성 중심의 자동 공개 판정`

### Task 6: 공개 경로 연결과 매일 재확인

**Files:**
- Create: `benefit_monitor/auto_release.py`
- Modify: `benefit_monitor/publish.py`(`PUBLIC_FIELDS`에 `review`, `payload`에서 자동 기록 병합)
- Modify: `benefit_monitor/public_snapshot.py`(자동 항목 재검사)
- Modify: `benefit_monitor/mirror.py`(briefing-data의 `ai-approved.json`, `ai-takedowns.json` 복원·저장)
- Modify: `benefit_monitor/operations.py:84`(`check_bodies`가 자동 기록도 확인)
- Modify: `.github/workflows/briefing-pages.yml`, `benefit_monitor/cloud_daily.py`(저장 경로)
- Test: `tests/test_auto_release.py`

**Interfaces:**
- Consumes: Task 5 record 스키마, `takedown_matches`.
- Produces: `auto_release.load(root) -> tuple[dict, list]`. `cache/ai_publish/approved.json`과 `cache/ai_publish/takedowns.json`을 읽는다(없으면 빈 값).
- Produces: `auto_release.public_items(approved: dict, takedowns: list, sources: dict, now: datetime) -> list[dict]`. 아래 기록을 뺀 뒤 공개 항목 dict(`PUBLIC_FIELDS` + `display_until`, `verified_at = review.checked_at`, `needs_recheck False`)를 돌려준다.
  - 형식 오류, 허용 도메인 밖 URL
  - 종료일 지남, 상시형 published 90일 초과
  - `review.checked_at`이 30시간 초과
  - 내림 목록 일치, `withdrawn` 상태
- Produces: `auto_release.mark_checked(approved, candidate_id, body_hash, now) -> str`. 반환은 `'ok'|'changed'|'gone'`. changed·gone이면 `status='withdrawn'`, `withdrawn_reason`을 기록하고 재조사 우선 대상으로 표시한다.
- Produces: 공개 JSON 항목의 `review` 칸.
  - 사람 승인: `{"kind":"human"}`
  - 자동: `{"kind":"ai_auto","document_count":N,"documents":[{"url":...,"title":...}],"checked_at":...}`
- Produces: briefing-data 파일 `ai-approved.json`(approved dict, 공개 가능 칸만), `ai-takedowns.json`(`[{candidate_id, title_key, taken_down_at, note}]`).

- [ ] **Step 1: Write the failing tests**
  - `test_expired_today_is_dropped`: valid_until 어제 → 빠짐.
  - `test_stale_over_30h_hidden_human_items_kept`: checked_at 31시간 전 → 자동 항목 없음, `public/verified.json` 항목은 그대로 공개.
  - `test_takedown_removes_on_all_paths`: `publish.payload`, `public_snapshot.validate` 모두에서 빠짐.
  - `test_snapshot_rejects_forged_auto_item`: 자동 항목의 URL·summary가 approved 기록과 다르면 `ValueError('snapshot fact differs ...')`.
  - `test_body_change_withdraws`: `mark_checked`가 다른 해시 → `'changed'`, 다음 payload에서 빠짐.
  - `test_review_field_human_and_auto`: 두 종류가 각각 표시됨.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement**
  - `check_bodies`는 사람 승인 항목 다음으로 자동 기록을 확인한다. 실행당 상한은 기존 `body_checks_per_run`에 자동 기록 수(최대 20)를 더한다.
  - 일반 수집 workflow는 `mirror --restore` 때 두 파일을 받고, 실행 뒤 `ai-approved.json`의 확인 시각·철회 상태만 갱신해 저장한다.
  - AI 실행은 새 record를 추가해 저장한다.
  - 동시 쓰기는 contents API sha 조건으로 하고, 충돌하면 한 번 다시 읽어 병합한다(병합 규칙: withdrawn 우선, checked_at 최신 우선).
- [ ] **Step 4: Run** 전체 테스트 → PASS
- [ ] **Step 5: Commit** `feat(publish): 자동 공개 기록을 모든 공개 경로에서 재검사해 공개`

### Task 7: 화면 표시

**Files:**
- Modify: `frontend/src/benefits.ts`(`review` 파싱, `Benefit.review`)
- Modify: `frontend/src/BenefitCard.vue`(배지·상세 원문 목록)
- Modify: `frontend/src/style.css`
- Test: `frontend/tests/benefits.test.ts`, `frontend/tests/e2e/app.spec.ts`(자동 항목 1건 시나리오)

**Interfaces:**
- Consumes: Task 6 `review` 칸.
- Produces: `Benefit.review: {kind:'human'} | {kind:'ai_auto'; documentCount:number; documents:{url:string;title:string}[]; checkedAt:string}`. `review`가 없으면 `{kind:'human'}`(구버전 호환)으로 본다. ai_auto의 documents URL은 `https:`이고 허용 도메인(`source-policy.json` 전체)이어야 한다. 아니면 그 항목을 보류(withheld)한다.

- [ ] **Step 1: Write the failing tests**
  - unit `review defaults to human and validates ai_auto documents`
  - unit `ai_auto with foreign document url is withheld`
  - e2e: 자동 항목 카드에 `AI 정리 · 공식 원문 2곳 대조`가 보이고, 상세 창에 원문 링크 2개가 있다. 사람 항목 카드에는 그 문구가 없다.
- [ ] **Step 2: Run** `npm test` → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** `npm test && npm run build`, E2E → PASS
- [ ] **Step 5: Commit** `feat(web): 자동 공개 항목 표시와 대조 원문 목록`

### Task 8: 어드민 페이지

**Files:**
- Create: `frontend/admin.html`, `frontend/src/admin/main.ts`, `frontend/src/admin/AdminApp.vue`, `frontend/src/admin/github.ts`
- Modify: `frontend/vite.config.ts`(multi-page input), `scripts/assemble_pages.py`(admin.html 포함)
- Modify: `.github/workflows/briefing-pages.yml`(takedown 반영용 snapshot 배포가 기존 `deploy_approved_snapshot` 입력으로 동작하는지 확인. 새 입력 없음)
- Test: `frontend/tests/admin-github.test.ts`, `frontend/tests/e2e/admin.spec.ts`

**Interfaces:**
- Consumes: 공개 `briefing.json`(자동 항목과 `review`), briefing-data `ai-takedowns.json`, `cache/ai_daily/latest.json`에서 나온 공개 상태 칸(Task 2의 `credit_exhausted`를 `briefing.json`의 `ai_status: {state:'ok'|'credit_exhausted'|'failed', last_success_day}`로 내보낸다. 이 칸은 Task 6에서 `payload`에 추가한다).
- Produces: `github.ts`
  - `takeDown(token: string, item: {candidate_id: string; title_key: string}, note: string): Promise<void>`: contents API로 briefing-data `ai-takedowns.json`을 sha 조건 갱신한다. 그 뒤 `GET /repos/{repo}/commits/main`으로 code sha를, 갱신 커밋 sha를 snapshot으로 삼아 `POST actions/workflows/briefing-pages.yml/dispatches` `{ref:'main', inputs:{deploy_approved_snapshot:true, snapshot_commit, expected_code_sha}}`를 보낸다.
  - `restore(token, candidate_id): Promise<void>`: 내림 목록에서 지우고 같은 배포를 한다.
  - 저장소는 상수 `Kim-Taesu/benefit-monitor`. 호출 대상은 `https://api.github.com`만.
- 화면: 토큰 입력(저장·삭제), 크레딧 상태 줄, 자동 공개 항목 목록(근거 원문 링크, 기간 근거, 확인 시각, 내리기 버튼 + 메모), 내린 항목 목록(되살리기). 메인 화면에서 링크하지 않는다. `<meta name="robots" content="noindex">`.
- 주의: `briefing.json`에 `candidate_id`·`title_key`가 필요하다. Task 6의 `review`에 `candidate_id`, `title_key`를 포함한다(공개해도 되는 해시·정규화 문자열).

- [ ] **Step 1: Write the failing tests**
  - unit: `takeDown`이 contents PUT(올바른 sha·base64 JSON)과 dispatch POST를 순서대로 부르고, 다른 호스트로 요청하지 않음(fetch 모킹).
  - unit: sha 충돌(409) 때 한 번 다시 읽어 병합.
  - e2e: 토큰 없으면 버튼 비활성. 모킹된 GitHub API로 내리기 후 "반영까지 2~3분" 안내. `credit_exhausted` 상태에서 `AI 조사 중지: 크레딧 소진` 표시. 외부 요청은 `api.github.com` 모킹 외 없음.
- [ ] **Step 2: Run** → FAIL
- [ ] **Step 3: Implement**
- [ ] **Step 4: Run** `npm test && npm run build`, E2E → PASS. `python scripts/assemble_pages.py` 산출물에 `admin.html` 존재.
- [ ] **Step 5: Commit** `feat(admin): 자동 공개 항목 내리기·되살리기 어드민 페이지`

### Task 9: 정책 기록과 마무리

**Files:**
- Modify: `AGENTS.md`(새 절 "승인된 AI 교차 조사·자동 공개 — 2026-11-07". 설계 문서의 승인 문구 인용, 기존 "$5 유지·200회·14일·추가 충전 금지·새 AI 사실 비공개만"이 이 절로 바뀐다고 명시)
- Modify: `README.md`(AI 절 갱신), `docs/ai/automation.md`(운영 방법: 크레딧 소진 알림, 어드민 토큰 만드는 법과 권한)
- Commit: 설계 문서와 이 계획

- [ ] **Step 1:** 문서 갱신
- [ ] **Step 2: Run** `python scripts/generate_source_policy.py --check`, 전체 Python 테스트, `npm test && npm run build`, E2E 전체 → 모두 PASS
- [ ] **Step 3: Commit** `docs: AI 교차 조사·자동 공개 승인과 운영 방법 기록`
- [ ] **Step 4:** PR 생성(머지는 사용자 승인 후). PR 본문에 "첫 실행에서 문법 시험 1회", "Anthropic 콘솔 크레딧은 소진 시 사용자가 수동 충전"을 적는다.
