# 장보기 "이거 싼 건가?" 빠른 확인 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 자주 사는 25개 품목을 장보기 검색으로 찾으면 오늘 평균가와 "N개월 평균보다 X% 쌈/비쌈" 카드가 맨 위에 뜨게 한다.

**Architecture:** 새 모듈 `benefit_monitor/grocery_baselines.py`가 주 1회 별도 GitHub Actions 실행에서 품목당 1요청으로 기간 평균(KAMIS 월별 표, 축평원 날짜 범위)을 받아 `briefing-data/grocery-baselines.json`에 저장한다. 일일 공개 빌드는 `mirror --restore` 때 그 파일을 내려받아 `briefing.json`의 별도 키 `grocery_baselines`로 낸다. 기존 `groceries` 묶음과 AI 경로는 그대로 둔다. 프런트는 그 키를 파싱해 기존 "품목 찾기" 검색에 결과 카드를 붙인다.

**Tech Stack:** Python 3.12 표준 라이브러리(unittest), Vue 3 + TypeScript(vitest, Playwright), GitHub Actions

**Spec:** `docs/superpowers/specs/2026-11-10-grocery-quick-check-design.md`

## Global Constraints

- Python 표준 라이브러리만 쓴다. 익명 공개 HTTPS GET만 쓰고, robots를 확인하며, 도메인은 `www.kamis.or.kr`·`www.ekapepia.com`만 허용한다. 유료 API, 인증키, 로그 서비스는 쓰지 않는다.
- 요청은 `collectors.rss.fetch`로만 보낸다(`cost_policy.budget` 적용). 주간 실행의 요청 상한은 30회다.
- 공식 게시값을 추정·환산하지 않는다. 기간을 부풀리지 않는다. 평균·기간·단위·행 중 하나라도 확인되지 않으면 배지를 숨긴다.
- 고기 기간 시작일은 `2026-07-01`로 고정한다(축평원 조사 방법 변경일).
- 배지 문구: `▼ {N}개월 평균보다 {p}% 쌈` / `▲ {N}개월 평균보다 {p}% 비쌈` / `{N}개월 평균과 같음`. N이 12 이상이면 "12개월"이다. 색은 p ≤ −10이면 `cheap`, p ≥ 10이면 `pricey`, 나머지는 `normal`이다(기존 `.grocery-badge` 클래스를 쓴다). 기준 기간이 1개월 미만이면 배지를 숨긴다.
- 기준값은 30일이 지나면 버린다(`checked_at` 기준).
- 기존 `groceries` 묶음 스키마, `grocery_pick`, `claude_trial.validate_host`, 기존 ±10% 평년 배지와 "평년보다 싼 것만" 필터는 바꾸지 않는다.
- `publish.py`·`public_snapshot.py`를 고치면 `public/topic-publication.json`의 `policy_sha256`을 `topic_publication.policy_hash(root)` 값으로 다시 기록한다.
- 로직을 바꾸면 `python -m unittest discover -s tests -v`를 실행한다. 프런트는 `cd frontend && npm test && npm run build`를 실행한다. e2e는 시스템 Chrome과 임시 config로 실행한다.
- 커밋 메시지는 한국어로 쓰고 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`로 끝낸다. main에 직접 커밋하지 않는다(브랜치 `feat/grocery-quick-check`).

## Review Focus

1. **축평원 날짜 범위가 기간 평균이 아닐 수 있다.** 마지막 날 값이나 합계라면 고기 % 전체가 틀린다. Task 1이 실측으로 확인하고, 아니면 멈춘다.
2. **오늘값과 기준값의 행이 다를 수 있다.** 단위(20kg/10kg), 품종(애호박/쥬키니), 등급(1등급/1+등급)이 어긋나면 그럴듯하지만 틀린 %가 크게 보인다. Task 2(단위 대조)와 Task 6(행 id 대조)에서 고정한다.
3. **KAMIS 월별 표의 빈 달과 진행 중인 이번 달.** '-'나 이번 달 값이 평균에 섞이면 기간이 부풀거나 값이 치우친다. Task 2에서 고정한다.
4. **주간 실행 실패나 briefing-data 파일 부재.** 첫 배포 직후나 수집 실패가 이어지면 일일 공개가 깨지지 않고 배지만 사라져야 한다. Task 4·5에서 고정한다.
5. **모바일 검색 입력.** 공백, "대 파", 영문 대소문자, 여러 품목이 걸리는 짧은 입력("파")에서 엉뚱한 카드가 뜨면 안 된다. Task 6에서 고정한다.

---

### Task 1: 장바구니 설정, KAMIS 코드 확정, 축평원 범위 평균 실측

**Files:**
- Modify: `sources/groceries.json` (`basket` 배열 추가)
- Create: `benefit_monitor/grocery_baselines.py` (`basket()` 검증만)
- Create: `tests/test_grocery_baselines.py`
- Create: `tests/fixtures/grocery_baselines/` (`kamis_monthly_rice.html`, `ekape_range_pork_belly.html`, 대조용 하루치 3개)

**Interfaces:**
- Produces: `basket(source: dict) -> list[dict]`. 각 항목의 키는 정확히 `id, name, aliases, group, row, kamis | ekape` 중 하나씩이다.
  - `id`: `^[a-z_]{2,30}$`
  - `name`: 화면 이름
  - `aliases`: 1~5개 문자열
  - `group`: `"고기·알" | "채소" | "기타"` 중 하나
  - `row`: `{"kind": "produce"|"meat", "id": str}`. 기존 `cache/groceries.json`의 produce `id`(예: `"파|대파|1kg|상품"`) 또는 meat `id`(예: `"4304-27-삼겹살"`)와 정확히 같다.
  - `kamis`: `{"itemcategorycode","itemcode","kindcode","productrankcode"}`. 모두 숫자나 영숫자 문자열이다.
  - `ekape`: `{"species","part","label"}`. `label`은 기존 meat 행의 `label`이다.
  - 형식이 틀리거나 25개를 넘거나 id가 겹치면 `ValueError`를 낸다.

- [ ] **Step 1: 축평원 범위가 평균인지 실측한다 (요청 최대 6회).** robots 1회, 삼겹살(4304/27) 하루치 3회(최근 조사일 3개), 같은 3일 범위 1회를 받는다. 범위의 전국값이 하루치 전국값 3개의 산술평균과 ±1원 안에서 같은지 확인한다. 응답은 fixture로 저장한다. **다르면 여기서 멈추고 사용자에게 보고한다**(설계서: 고기 배지 숨김 또는 재질문).
- [ ] **Step 2: KAMIS 18개 품목의 기간별 페이지 코드를 찾는다 (요청 최대 8회).** 기간별 페이지(`/customer/price/agricultureRetail/period.do`)의 품목 선택 데이터에서 찾는다. 기본 페이지의 hidden input과 JS 품목 목록, `action=itemList`가 단서다. 단위와 품종이 일간 행과 같은 조합을 고른다. 쌀은 `20kg` 상품을 쓴다. 쌀 월별 응답은 fixture로 저장한다.
- [ ] **Step 3: 설계서의 25개를 `sources/groceries.json`의 `basket`에 기록한다.** 별칭에 최소 다음을 넣는다.
  - 계란: "계란, 달걀"
  - 대파: "대파, 파"
  - 애호박: "애호박, 호박"
  - 오징어: "오징어, 물오징어"
  - 한우 등심: "한우, 등심, 소고기"
  - 미국산 갈비살: "갈비살, 소갈비살"
  - 닭: "닭, 생닭, 닭고기"

  고기 행은 "등심 1등급", "갈비살(냉장) 미국산", "XL30구 일반란"이다. `python scripts/generate_source_policy.py`가 `sources.yaml`·프런트 정책을 다시 만드는지 확인하고 실행한다.
- [ ] **Step 4: 실패하는 테스트를 쓴다.**
  - `test_basket_accepts_repo_config`: 저장소 설정을 그대로 넣으면 25개가 나오고 group 분포가 7/12/6이다.
  - `test_basket_rejects_duplicate_id`, `test_basket_rejects_both_kamis_and_ekape`, `test_basket_rejects_26_items`
  - `test_basket_rows_exist_in_fixture_bundle`: 기존 `tests/test_groceries.py`의 fixture 묶음이나 최소 fixture에 모든 `row.id`가 있다.
- [ ] **Step 5: `python -m unittest tests.test_grocery_baselines -v`로 실패를 확인하고, `basket()`을 구현한 뒤 통과시킨다.**
- [ ] **Step 6: 커밋한다.** `feat(groceries): 자주 사는 장바구니 25개 설정과 기간 가격 코드`

### Task 2: 기간 평균 파서

**Files:**
- Modify: `benefit_monitor/grocery_baselines.py`
- Test: `tests/test_grocery_baselines.py`

**Interfaces:**
- Consumes: Task 1의 fixture
- Produces:
  - `parse_kamis_monthly(page: str, today: date) -> dict | None`. 반환 형태는 `{"avg": int, "months": int, "from": "YYYY-MM", "to": "YYYY-MM", "unit": str}`이다.
  - `parse_ekape_range(page: str, label: str, start: date, end: date) -> dict | None`. 반환 형태는 같은 키이고, `months = (end - start).days // 30`이다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.**
  - `test_kamis_monthly_rice_last_12_complete_months`: today=2026-11-10이면 2025-11~2026-10을 쓴다. avg는 fixture 12개 월값의 반올림 평균이고, months=12, unit="20kg"이다.
  - `test_kamis_monthly_skips_dash_months`: 두 달을 '-'로 바꾼 fixture에서 months=10이고, from과 to는 값이 있는 달이다.
  - `test_kamis_monthly_excludes_current_month`: 11월 값이 있어도 넣지 않는다.
  - `test_kamis_monthly_rejects_changed_header`: 헤더가 `구분`으로 시작하지 않으면 None이다.
  - `test_kamis_monthly_none_when_zero_months`
  - `test_ekape_range_national_average`: 삼겹살 label이고 2026-07-01~11/7이면 avg=fixture 전국값, months=4이다.
  - `test_ekape_range_missing_label_none`: 등급 label이 표에 없으면 None이다.
  - `test_ekape_range_reuses_price_guard`: 범위 밖 금액이나 이상한 셀이면 None이다(`groceries._price` 재사용).
- [ ] **Step 2: 테스트가 실패하는지 확인한다.**
- [ ] **Step 3: 두 함수를 구현한다.** 셀 파싱은 `groceries._rows`·`_price`·`_cell`을 재사용한다. 고기 범위 표는 `groceries.parse_meat(page, cut, day)`가 이미 읽는다면 그 결과의 `national`을 쓴다.
- [ ] **Step 4: 테스트가 통과하는지 확인한다.**
- [ ] **Step 5: 커밋한다.** `feat(groceries): KAMIS 월별·축평원 기간 평균 파서`

### Task 3: 주간 수집과 보존 규칙

**Files:**
- Modify: `benefit_monitor/grocery_baselines.py`
- Test: `tests/test_grocery_baselines.py`

**Interfaces:**
- Consumes: `basket`, `parse_kamis_monthly`, `parse_ekape_range`, `collectors.rss.fetch`, `groceries._robots`
- Produces:
  - `collect(source: dict, now: datetime, previous: dict | None) -> dict`. 반환 묶음은 `{"schema_version": 1, "source": "grocery_baselines", "fetched_at": iso, "items": [{"id","name","aliases","group","row","baseline": {...,"checked_at": "YYYY-MM-DD"} | None}]}`이다.
  - `sanitize(bundle: object, now: datetime) -> dict | None`. 형식을 검사하고, `checked_at`이 30일을 넘은 baseline은 None으로 바꾼다. 항목은 최대 25개다.
  - `MAX_REQUESTS = 30`

- [ ] **Step 1: 실패하는 테스트를 쓴다.** `fetch`를 목으로 대체한다.
  - `test_collect_one_request_per_item_plus_robots`: 요청 수가 25+2이다.
  - `test_collect_keeps_previous_on_item_failure`: 한 품목이 예외를 내면 이전 baseline과 이전 checked_at을 유지한다.
  - `test_collect_robots_disallow_raises`
  - `test_collect_stops_at_budget_keeps_previous`: 예산 예외가 나면 남은 품목은 이전 값을 유지한다.
  - `test_sanitize_drops_baseline_older_than_30_days`
  - `test_sanitize_rejects_unknown_keys_and_bad_types`
  - `test_sanitize_none_for_wrong_schema`
- [ ] **Step 2: 테스트가 실패하는지 확인한다.**
- [ ] **Step 3: `collect`와 `sanitize`를 구현한다.** KAMIS URL 파라미터는 `action=monthly&yyyy={now.year}&period=3&convert_kg_yn=N`에 품목 코드를 더한다. 축평원 URL은 `searchStartDate=2026-07-01&searchEndDate={최근 조사일}&searchCondition1/2`이다. 최근 조사일은 어제부터 최대 3일을 거슬러 찾는다. 기존 `groceries._collect_meat`의 탐색과 같은 규칙이다.
- [ ] **Step 4: 테스트가 통과하는지 확인한다.**
- [ ] **Step 5: 커밋한다.** `feat(groceries): 기간 평균 주간 수집과 30일 보존`

### Task 4: briefing-data 저장, 복원, 주간 워크플로

**Files:**
- Modify: `benefit_monitor/grocery_baselines.py` (`main()`, `python -m benefit_monitor.grocery_baselines --repository R [--root P]`)
- Modify: `benefit_monitor/mirror.py` (`restore`가 `grocery-baselines.json`을 `cache/grocery_baselines.json`으로 내려받음)
- Create: `.github/workflows/grocery-baselines.yml`
- Modify: `AGENTS.md` (장보기 절 120행 부근)
- Test: `tests/test_grocery_baselines.py`, `tests/test_mirror.py`

**Interfaces:**
- Consumes: `mirror._get(repository, name, env)`, `mirror._put(repository, name, value, sha, env)`, Task 3의 `collect` / `sanitize`
- Produces:
  - briefing-data 파일 `grocery-baselines.json`. 내용은 `collect`의 반환 묶음이다.
  - 로컬 `cache/grocery_baselines.json`

- [ ] **Step 1: 실패하는 테스트를 쓴다.**
  - `test_main_reads_previous_and_puts_result`: `_get`·`_put`·`collect`를 목으로 대체한다. 이전 값이 `collect`의 previous로 전달되고, `_put`이 sha와 함께 호출된다.
  - `test_main_retries_once_on_stale_sha_then_fails`: `_put`이 False를 내면 다시 읽고 한 번 재시도한다. 두 번째도 False면 종료 코드는 1이다.
  - `test_main_skips_put_when_sanitize_fails`
  - `test_mirror_restore_saves_grocery_baselines`
  - `test_mirror_restore_missing_baselines_is_not_error`: 404이면 파일을 만들지 않고 restore는 성공한다.
  - `test_mirror_restore_baselines_read_error_is_not_fatal`: 다른 오류가 나도 기존 restore 결과는 유지하고 baselines만 비운다.
- [ ] **Step 2: 테스트가 실패하는지 확인한다.**
- [ ] **Step 3: `main()`과 `mirror` 복원을 구현한다.** `restore`가 baselines 실패 때문에 실패하지 않게 한다(Review Focus 4).
- [ ] **Step 4: 테스트가 통과하는지 확인한다.**
- [ ] **Step 5: `.github/workflows/grocery-baselines.yml`을 쓴다.** `briefing-pages.yml`의 build job 머리를 그대로 따른다.
  - `if: github.event.repository.private == false && vars.BENEFIT_PAGES_ZERO_SPEND == 'confirmed'`
  - checkout은 같은 고정 SHA와 `persist-credentials: false`, setup-python은 3.12
  - `permissions: contents: write`, `timeout-minutes: 10`
  - `concurrency: group: benefit-pages, cancel-in-progress: false`
  - `on: schedule: cron '7 14 * * 0'`(일요일 23:07 KST, 일일 수집 00:37 전), `workflow_dispatch`
  - 단계: `python -m benefit_monitor.grocery_baselines --repository "$GITHUB_REPOSITORY"`, env `GH_TOKEN: ${{ github.token }}`

  Secret이나 AI 단계는 없다.
- [ ] **Step 6: AGENTS.md 장보기 절을 갱신한다.** 다음을 한국어 한 단락으로 쓴다.
  - 주간 기준값 실행, 요청 약 27회(상한 30)
  - `briefing-data/grocery-baselines.json`
  - 2026-07-01 고정 시작일, 30일 폐기, 사용자 승인일 2026-11-10
- [ ] **Step 7: 전체 `python -m unittest discover -s tests -v`를 통과시키고 커밋한다.** `feat(groceries): 기간 평균 주간 실행과 briefing-data 보존`

### Task 5: 공개 briefing.json에 `grocery_baselines` 추가

**Files:**
- Modify: `benefit_monitor/publish.py` (`attach_groceries` 옆에 `attach_grocery_baselines(root, data, now)`)
- Modify: `benefit_monitor/public_snapshot.py:129-137` (같은 sanitize를 거쳐 `clean['grocery_baselines']`)
- Modify: `public/topic-publication.json` (`policy_sha256` 재기록)
- Test: `tests/test_publish.py`, `tests/test_public_snapshot.py`

**Interfaces:**
- Consumes: `grocery_baselines.sanitize`, `cache/grocery_baselines.json`
- Produces: `briefing.json`의 최상위 키 `grocery_baselines`. 형태는 sanitize 결과와 같다. `groceries`가 없으면 넣지 않는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.**
  - `test_publish_attaches_sanitized_baselines`
  - `test_publish_omits_baselines_without_groceries`
  - `test_publish_omits_baselines_when_file_missing_or_bad`: 공개 자체는 성공한다.
  - `test_public_snapshot_passes_baselines_through_sanitize`
  - `test_public_snapshot_drops_baselines_on_collection_failed`
- [ ] **Step 2: 테스트가 실패하는지 확인한다.**
- [ ] **Step 3: 구현한다.** 그 뒤 `python -c "from pathlib import Path;from benefit_monitor.topic_publication import policy_hash;print(policy_hash(Path('.')))"` 값을 `public/topic-publication.json`의 `policy_sha256`에 기록한다.
- [ ] **Step 4: 전체 unittest를 통과시키고 커밋한다.** `feat(groceries): 공개 브리핑에 기간 평균 별도 키`

### Task 6: 프런트 파싱, 검색 매칭, 배지 계산

**Files:**
- Modify: `frontend/src/groceries.ts`
- Test: `frontend/tests/groceries.test.ts`

**Interfaces:**
- Consumes: `briefing.json`의 `grocery_baselines`, 기존 `parseGroceries`가 만든 `PriceRow[]`
- Produces:
  - `interface BasketItem{id:string;name:string;aliases:string[];group:'고기·알'|'채소'|'기타';rowKey:string;baseline:{avg:number;months:number;from:string;to:string;unit:string}|null}`. `rowKey`는 기존 화면이 쓰는 `row.kind+row.id`와 같다.
  - `parseBaselines(raw:unknown, now:number):BasketItem[]`. 형식이 틀리면 `[]`이고, `checked_at`이 30일을 넘으면 baseline=null이다.
  - `quickMatch(q:string, basket:BasketItem[]):{best:BasketItem;others:BasketItem[]}|null`. 공백을 제거하고 소문자로 바꾼 뒤 name과 aliases를 비교한다. 순위는 정확 일치 > 접두 일치 > 부분 일치이고, 같은 순위면 설정 순서를 따른다. `others`는 함께 걸린 다른 품목 다음에 같은 group의 다른 품목을 채워 최대 3개다.
  - `baselineBadge(row:PriceRow, item:BasketItem):{level:'cheap'|'normal'|'pricey';pct:number;label:string}|null`

- [ ] **Step 1: 실패하는 테스트를 쓴다.**
  - `quickMatch('삼겹')`.best.name==='삼겹살'
  - `quickMatch(' 대 파 ')`.best.name==='대파'
  - `quickMatch('달걀')`는 계란
  - `quickMatch('파')`는 정확 일치하는 별칭 '파'의 대파가 best이다.
  - `quickMatch('없는품목')`===null
  - `quickMatch('')`===null
  - `others` 길이가 3 이하이고 best를 포함하지 않는다.
  - `baselineBadge`: current 2650, avg 2880, months 12이면 `{level:'normal',pct:-8,label:'▼ 12개월 평균보다 8% 쌈'}`
  - current 2500, avg 2880이면 level 'cheap'(−13%)
  - months 4이면 label에 '4개월 평균'
  - pct 0이면 '12개월 평균과 같음'
  - months 0이면 null
  - `row.unit`에 baseline.unit이 들어 있지 않으면 null(Review Focus 2)
  - rowKey가 다른 행이면 null
  - `parseBaselines`: checked_at 31일 전이면 baseline null, schema_version 2면 `[]`
- [ ] **Step 2: `cd frontend && npx vitest run tests/groceries.test.ts`로 실패를 확인한다.**
- [ ] **Step 3: 세 함수를 구현한다.** 단위 대조는 기존 `parseUnit`을 쓴다.
- [ ] **Step 4: 테스트가 통과하는지 확인한다.**
- [ ] **Step 5: 커밋한다.** `feat(web): 장바구니 검색 매칭과 기간 평균 배지 계산`

### Task 7: 결과 카드 화면

**Files:**
- Create: `frontend/src/GroceryQuickCheck.vue`
- Modify: `frontend/src/GrocerySection.vue` (검색어가 있을 때 카드를 이번 주 추천보다 먼저 보여줌), `frontend/src/App.vue` (`parseBaselines` 전달)
- Test: `frontend/tests/e2e/groceries.spec.ts`

**Interfaces:**
- Consumes: Task 6의 `quickMatch`·`baselineBadge`·`BasketItem`, 기존 `won`, `PriceRow`
- Produces: `<GroceryQuickCheck :q="q" :basket="basket" :rows="bundle.rows" :produce-date :meat-date @pick="name=>q=name" />`

카드 문구는 설계서 목표 1과 A안 목업(`.superpowers/brainstorm/*/content/search-result.html`의 A카드)을 따른다. 각 줄은 다음과 같다.
- 첫 줄: `{name} · 전국 평균 소매가`
- 큰 줄: `{won(current)} /{단위}`
- 배지: 위의 배지 문구
- 작은 줄: `{N}개월 평균 {won(avg)} · {M/D} 조사`
- 링크: others 이름을 ` · `로 잇고 끝에 ` ›`를 붙인다. 누르면 검색어가 그 이름으로 바뀐다.

baseline이 없으면 배지와 작은 줄의 평균 부분을 숨긴다. 장바구니 품목인데 오늘 행이 없으면 카드를 보여주지 않는다. 검색어가 장바구니에 없고 기존 목록 결과도 0개면, 기존 빈 화면 문구 아래에 `아직 자주 사는 품목에 없어요`를 더한다.

- [ ] **Step 1: 실패하는 e2e를 쓴다.** fixture `briefing.json`에 `grocery_baselines`를 넣는다.
  - 390×844 화면에서 `#grocery-q`에 "삼겹"을 입력하면 카드가 화면 안에 보인다(`toBeInViewport`).
  - 카드가 이번 주 추천보다 위에 있다.
  - 배지 텍스트는 `개월 평균보다`를 포함한다.
  - 링크를 누르면 검색어와 카드 제목이 바뀐다.
  - baseline이 null인 품목은 배지가 없다.
  - "없는품목"을 치면 `아직 자주 사는 품목에 없어요`가 나온다.
- [ ] **Step 2: 시스템 Chrome 임시 config로 e2e를 실행해 실패를 확인한다.**
- [ ] **Step 3: 컴포넌트를 구현하고 배치를 조정한다.** 스타일은 기존 `.grocery-badge`와 카드 토큰을 쓴다. 큰 가격은 `font-size: 2.2rem; font-weight: 800`이다.
- [ ] **Step 4: `npm test && npm run build`와 e2e를 통과시킨다.** 360px와 390px 스크린샷을 `docs/qa/screenshots/grocery-quick-check-{360,390}.png`로 남긴다.
- [ ] **Step 5: 전체 `python -m unittest discover -s tests -v`를 실행하고 커밋한다.** `feat(web): 장보기 검색 결과 카드(오늘 평균가·기간 평균 대비)`
