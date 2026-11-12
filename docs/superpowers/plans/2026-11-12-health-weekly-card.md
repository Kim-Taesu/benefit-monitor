# 이번 주 보건소 추천 카드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 보건소 탭 맨 위에 "이번 주 보건소 추천" 카드(서울 전체 종류별 구 수 + 구별 AI 첫 문장 요약)를 프런트만으로 추가한다.

**Architecture:** `frontend/src/health.ts`에 순수 함수 `weeklyPicks`를 더해 기존 `parseHealth` 결과를 묶는다(파서는 바꾸지 않음 — 호출처 HealthSection.vue·App.vue·admin/AdminApp.vue). 새 컴포넌트 `HealthWeekly.vue`가 그리고 `HealthSection.vue`가 지역 필터 상태를 넘긴다.

**Tech Stack:** Vue 3.5 + TypeScript, `node --test`, Playwright(시스템 Chrome).

**Spec:** `docs/superpowers/specs/2026-11-12-health-weekly-card-design.md` (grill: `.ax/plans/2026-11-12-health-weekly-card-design.md`)

## Global Constraints

- 백엔드·`briefing.json`·`publish.py`·`public_snapshot.py`·`policy_sha256` 변경 없음. 새 유료 호출 없음.
- 종류 표시 이름에 "무료" 금지. 종류 표·이름 단어는 spec 표 그대로.
- 대상 사업: `status==='checked' && !stale`만. 수집 불가 구(사업 없음)는 카드에 없음.
- 링크 새 창 `rel="noopener noreferrer"` + sr-only "(새 창)". 버튼 탭 영역 ≥44px. 모바일 가로 스크롤 없음.
- 커밋은 파일 경로로만 add. base SHA `1d7e865`.
- e2e는 시스템 Chrome: 커밋하지 않는 임시 파일 `frontend/playwright.chrome.local.config.ts`를 만든다 — `import config from './playwright.config'; export default {...config,use:{...config.use,launchOptions:{executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'}}};` (작업 끝나면 삭제, add 금지).

## Review Focus

1. 첫 문장 자르기가 `1.5kg`·`09:00~11:30`·`02-2600-5933`에서 끊기지 않음 — T1 테스트.
2. KST 7일 경계(오늘-6 포함, 오늘-7 제외, 미래 제외) — T1 테스트.
3. 문장 0개인 구도 이름+링크로 보임, 카드 "AI 작성" 표시는 문장이 하나라도 있을 때만 — T1(데이터)·T2(e2e).
4. 종류 칩 필터와 지역 필터 동시 적용 시 빈 결과 → 카드 안 빈 안내, 카드 자체는 유지 — T2.
5. 같은 구에 같은 종류 사업 둘(예: 간염검사 B형·C형) → 구 수 1 — T1.

---

### Task 1: `weeklyPicks` 데이터 함수

```yaml
task_id: T1
owner: superpowers   # 새 순수 함수, 기존 심볼 수정 없음(impact: parseHealth 호출처 3, 변경 안 함)
allowed_files: [frontend/src/health.ts, frontend/tests/health.test.ts]
forbidden_changes: [parseHealth/filterHealth 시그니처·동작, HealthProgram/HealthBundle 기존 필드]
must_read: [docs/superpowers/specs/2026-11-12-health-weekly-card-design.md, frontend/src/health.ts]
expected_output: weeklyPicks가 spec "데이터 규칙"대로 종류 집계·구 묶음·첫 문장·새 공지를 계산; 단위 테스트 green
verification_command: cd frontend && npm test && npm run typecheck
handoff_summary_required: true
```

**Interfaces — Produces:**
```ts
export type HealthKind='metabolic'|'pregnancy'|'youth'|'mind'|'mobile'|'smoking'|'tb'|'hepatitis'|'basic';
export const HEALTH_KINDS:{key:HealthKind;label:string;words:string[]}[]; // spec 표 순서
export function healthKind(name:string):HealthKind|null;
export function firstSentence(s:string):string;
export interface WeeklyProgram{name:string;url:string;center:string;kind:HealthKind|null;summary:string|null}
export interface WeeklyDistrict{district:string;newNotices:number;programs:WeeklyProgram[];more:number;kinds:HealthKind[]}
export interface WeeklyPicks{kinds:{key:HealthKind;label:string;districts:number}[];districts:WeeklyDistrict[];hasSummary:boolean}
export function weeklyPicks(bundle:HealthBundle,todayKst:string):WeeklyPicks; // todayKst 'YYYY-MM-DD'
```
`programs`는 최대 3개, `more`는 나머지 수, `kinds`는 그 구의 전체 대상 사업 종류(칩 필터용).

- [ ] **Step 1: 실패 테스트 작성** (`frontend/tests/health.test.ts`, 기존 `board`/`raw` 헬퍼 재사용, programs·health_notes를 raw에 추가)
  - `healthKind`: '대사증후군 관리'→metabolic, '[구로형] 임신 준비 지원'→pregnancy, '예비부부 건강검진'→pregnancy, '1인 청년가구 건강검진'→youth, '마음건강검진 상담지원'→mind, '모바일 헬스케어'→mobile, '금연클리닉'→smoking, '결핵검사'→tb, 'B형간염검사'→hepatitis, '골밀도 검사'→basic, '내몸사랑 기초건강검진'→basic, '무료건강검진'→basic, '치매 조기검진'→null.
  - `firstSentence`: '만 20세~69세 광진구민이라면 무료로 받아보세요. 평일 09:00~17:00에 예약하세요.'→'만 20세~69세 광진구민이라면 무료로 받아보세요.'; '1.5kg 이하 체중 변화를 확인해요. 전화 02-2600-5933.'→'1.5kg 이하 체중 변화를 확인해요.'; '짧아요. 두 번째 문장이 깁니다.'→ 원문 전체(첫 문장 12자 미만); 마침표 없는 문장→그대로.
  - 집계: 강서(대사증후군 관리 checked+note, 간염검사 B형·C형 checked) + 광진(대사증후군 failed) → kinds = [{metabolic,1},{hepatitis,1}] (광진 failed 제외, 간염 중복 1).
  - stale(checked_at 11일 전) 사업 제외.
  - 구 안 순서·상한: 문장 있는 사업 먼저, 4개 중 3개 + more=1.
  - 문장 없는 구도 districts에 포함, summary null; hasSummary는 note 하나라도 있으면 true, 없으면 false.
  - 새 공지(today '2026-11-11'): hint 공지 '2026-11-05' 셈, '2026-11-04' 안 셈, '2026-11-12' 안 셈, hint:false 안 셈 → newNotices 1, 그 구가 문장 많은 다른 구보다 위.
- [ ] **Step 2:** `cd frontend && npm test` → 새 테스트 FAIL(export 없음).
- [ ] **Step 3: 구현** (`frontend/src/health.ts`). 첫 문장: `/[.!?](?=\s|$)/`의 첫 일치에서 자름(숫자 사이 점은 뒤가 공백이 아니라 자연히 제외). 날짜 비교는 'YYYY-MM-DD' 문자열, 오늘-6일은 UTC 정오 기준 Date 연산으로 계산.
- [ ] **Step 4:** `cd frontend && npm test && npm run typecheck` → 전부 PASS.
- [ ] **Step 5: Commit** `git add frontend/src/health.ts frontend/tests/health.test.ts && git commit -m "feat(health): 이번 주 보건소 추천 데이터 묶기(weeklyPicks)"`

### Task 2: 카드 화면 + e2e

```yaml
task_id: T2
owner: superpowers   # 화면 전용; 검증은 단위+typecheck+e2e+스크린샷(리뷰 깊이: visual)
allowed_files: [frontend/src/HealthWeekly.vue, frontend/src/HealthSection.vue, frontend/src/style.css, frontend/tests/e2e/health.spec.ts]
forbidden_changes: [frontend/src/health.ts, 기존 공지·상시 목록 동작]
must_read: [docs/superpowers/specs/2026-11-12-health-weekly-card-design.md, frontend/src/HealthSection.vue, frontend/src/GroceryQuickCheck.vue]
expected_output: 보건소 탭 맨 위(상시 목록 위)에 카드; 칩 필터·지역 필터·구 더 보기 동작; e2e green
verification_command: cd frontend && npm test && npm run build && npx playwright test -c playwright.chrome.local.config.ts tests/e2e/health.spec.ts
handoff_summary_required: true
```

**Interfaces — Consumes:** T1의 `weeklyPicks`, `HEALTH_KINDS`. `HealthWeekly.vue` props: `{bundle:HealthBundle; district:string; today:string}`. `today`는 HealthSection에서 `props.now`를 KST 날짜로(`festivals.ts`의 `kstDate(now)` 재사용).

- [ ] **Step 1: e2e 실패 테스트** (`health.spec.ts` 기존 fixture에 강서 사업 2개+광진 board/사업 1개 추가):
  - `section[aria-labelledby="health-weekly-title"]`에 "이번 주 보건소 추천", "AI 작성", 강서 첫 문장 '[테스트] 강서구 20~69세라면 대사증후군 검진을 무료로 받을 수 있어요.'(두 번째 문장 '전화로 예약하고'는 없음).
  - 서울 전체 칩 "대사증후군 검진·관리 2개 구" 누르면 `aria-pressed="true"`, 그 종류 없는 구 묶음 사라짐; 다시 누르면 복원.
  - 지역 select '광진구' → 카드에 광진만.
  - 390px 폭에서 `document.documentElement.scrollWidth<=clientWidth`.
- [ ] **Step 2:** 실행해 FAIL 확인.
- [ ] **Step 3: 구현** — 제목·안내 문구는 spec 그대로("AI가 공식 페이지를 요약했습니다. 대상·기간·비용은 원문에서 확인하세요."). 기본 4개 구, "구 더 보기"(버튼). 칩·지역 필터 결과 0개면 "조건에 맞는 구가 없어요". `picks.districts` 비면 카드 미표시. 새 공지 배지 "새 공지 N건". 기존 CSS 토큰만 사용.
- [ ] **Step 4:** verification_command PASS + 390px 스크린샷 1장을 `.ax/plans/shots/`에 저장해 컨트롤러가 확인.
- [ ] **Step 5: Commit** (위 4개 파일 경로만).

### Task 3: 문서·PR·배포 (main-session)

```yaml
task_id: T3
owner: main-session   # push·PR·머지·워크플로 실행은 사람 승인 게이트
allowed_files: [AGENTS.md]
must_read: [AGENTS.md "승인된 보건소 상시 사업 AI 안내 문장" 절]
expected_output: AGENTS.md에 화면 규칙 한 단락(새 정책 아님); 전체 py/fe/e2e green 후 PR — 머지·배포는 사용자 승인 후
verification_command: python -m unittest discover -s tests && cd frontend && npm test && npm run build && npx playwright test -c playwright.chrome.local.config.ts
handoff_summary_required: true
```

- [ ] AGENTS.md 보건소 AI 문장 절 끝에 "이번 주 보건소 추천 카드(2026-11-12)" 한 단락: 프런트 묶음만, 종류 이름 무료 금지, 첫 문장 규칙, 문장 없는 구 표시.
- [ ] 전체 검증 후 ax:review → quality-check → update-pr. 머지 후 배포는 `Briefing pages` 수동 실행(프런트 변경만이므로).
