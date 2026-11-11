# 장보기 카드 공식 할인행사 연결 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 장보기 결과 카드의 배지 아래에, 지금 진행 중이고 그 품목이 대상인 정부 할인행사를 최대 2줄 보여준다. 양파 기간 평균도 복구한다.

**Architecture:** 해수부 보도자료를 기존 HTML 수집기의 새 출처(`mof_press`)로 추가한다. 정책브리핑은 이미 `government` 출처로 수집 중이다. 후보는 기존 AI 조사와 자동 공개 경로를 그대로 탄다. 공개된 혜택 항목(`briefing.json` `items`)은 새 결정적 모듈 `benefit_monitor/grocery_discounts.py`가 장바구니 품목과 연결하고, 결과를 별도 키 `grocery_discounts`로 낸다. 프런트는 그 키만 그린다.

**Tech Stack:** Python 3.12 표준 라이브러리(unittest), Vue 3 + TypeScript(node --test, Playwright), GitHub Actions

**Spec:** `docs/superpowers/specs/2026-11-11-grocery-discount-link-design.md`

## Global Constraints

- Python 표준 라이브러리, 익명 공개 HTTPS GET, robots 확인, 허용목록만 쓴다. 해수부 도메인은 `www.mof.go.kr`이다. 농식품부(`www.mafra.go.kr`)는 상세 302 때문에 쓰지 않으며, 우회하지 않는다.
- 행사 수집(해수부 출처)은 실행당 최대 5회다. 수집 순서는 `groceries` 바로 앞이다. 전체 상한(수집 95, 프로젝트 100)은 바꾸지 않는다.
- 카드에 붙이는 조건은 네 가지다.
  - 시작일과 끝나는 날이 모두 확인돼야 한다(`valid_from`·`valid_until` 존재, `validity_kind == 'fixed'`).
  - `valid_from ≤ 오늘 ≤ valid_until`이어야 한다(KST).
  - 품목명이나 분명한 품목군 단어가 있어야 한다.
  - "농축산물 전 품목"처럼 넓은 표현만 있으면 붙이지 않는다.
- 국산 한정 표현(국산, 국내산, 우리, 한우, 한돈)이 있으면 수입 품목(`us_beef_rib`처럼 수입인 장바구니 항목, 바나나)에 붙이지 않는다.
- 모델은 연결을 정하지 않는다. 연결은 공개 항목의 `title`·`conditions`·`summary` 텍스트만 보고 코드가 정한다. 할인율, 매장, 날짜는 원문 표현에서 그대로 옮기고 만들어 내지 않는다.
- 카드 줄 형식: `{행사명} {할인} · {매장} · {M/D}까지 · 원문`. 할인이나 매장을 찾지 못하면 그 조각만 뺀다. 최대 2줄이며 끝나는 날이 가까운 순서다. 3건 이상이면 `외 N건`을 붙이고 혜택 탭으로 이어지게 한다.
- 360×800, 390×844에서 가격, 배지, 할인 1줄이 첫 화면에 다 보여야 한다.
- 게이트 파일(`publish.py`, `public_snapshot.py`)을 고치면 `public/topic-publication.json`의 `policy_sha256`을 `topic_publication.policy_hash(root)`로 다시 기록한다. 조사 지시문(`docs/ai/prompts/research-system.md`)을 고치면 `ai_review.fingerprint`가 바뀌므로 그 영향(문법 시험 요청 1회 가능)을 AGENTS.md 절에 적는다.
- 커밋은 한국어로 쓰고 `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`로 끝낸다. 브랜치는 `docs/grocery-discount-link`를 이어 쓴다. main에 직접 커밋하지 않는다.
- e2e는 시스템 Chrome 임시 config로 돌린다. `npx playwright install`은 하지 않는다. 임시 config는 커밋하지 않는다.

## Review Focus

1. **끝난 행사:** 어제 끝난 행사(`valid_until` = 어제)는 카드에 없어야 한다. 백엔드 연결과 프런트 날짜 재필터 양쪽에서 막는다(Task 3, Task 4).
2. **시작 전 행사:** 내일 시작하는 행사(`valid_from` = 내일)도 없어야 한다(Task 3, Task 4).
3. **넓은 표현과 오연결:** "한우세일"이 삼겹살에, "농축산물 전 품목 할인"이 아무 품목에나, "국산 수산물"이 수입 품목에 붙으면 안 된다(Task 3).
4. **수산물 행사의 연결 범위:** "수산물 할인"은 고등어와 오징어에만 붙는다(Task 3).
5. **할인 줄 때문에 배지가 첫 화면 밖으로 밀리는 경우:** 할인이 2줄 붙어도 가격과 배지는 보여야 한다(Task 4 e2e).

---

### Task 1: 해수부 보도자료 출처와 행사 후보 단어

**Files:**
- Create: `sources/mof_press.json` (출처 정의와 runbook. 형식은 `sources/government.json`을 따름)
- Modify: `benefit_monitor/collectors/html.py` (해수부 `fn_selectDoc('<n>')` 링크를 `/doc/ko/selectDoc.do?docSeq=<n>&menuSeq=971&bbsSeq=10`으로 옮김. 기존 Seven-Eleven 처리와 같은 방식)
- Modify: `sources/_config.json` (`source_order`에서 `groceries` 바로 앞에 `mof_press`)
- Modify: `sources/government.json` (`keywords`에 `세일`, `수산대전`, `농할`, `반값` 추가)
- Regenerate: `sources.yaml` (`python scripts/generate_sources.py`), `scripts/generate_source_policy.py`가 만드는 프런트 정책
- Create: `tests/fixtures/mof_press/list.html` (실제 목록 발췌. 행사 제목이 없으면 실제 행 하나의 제목만 바꾼 사본을 따로 두고 "편집본"이라고 주석)
- Test: `tests/test_html_collector.py` 또는 기존 html 수집기 테스트 파일(빌더가 찾음)

**Interfaces:**
- Produces: 출처 id `mof_press`. 후보의 형태는 기존 html 후보와 같다(`dict(source, url, title, summary, needs_recheck)`). 행사 후보 단어는 아래와 같다.
  - `keywords`(제목에 하나 이상 필요): `할인`, `세일`, `수산대전`, `농할`, `할인지원`, `소비촉진`, `반값`, `특별판매`
  - 대상 단어(하나 이상 필요): `농축산물`, `농산물`, `축산물`, `한우`, `한돈`, `수산물`, `수산식품`, `김장`, `성수품`

  대상 단어 조건은 `mof_press`에만 적용한다. 기존 html 수집기에 선택 필드 `require_any`를 추가해 구현한다. 필드가 없는 출처는 동작이 그대로다.

- [ ] **Step 1: 해수부 목록을 받아 fixture로 저장한다.** 요청은 robots 1회와 목록 1회다. 2026-11-11 정찰본 위치는 `/private/tmp/claude-501/-Users-user-personal-benefit-monitor/4bd2b23e-18a6-416c-9bcc-be67b2fc6f0a/scratchpad/recon2/mof_list.html`이다. 그것을 발췌해 써도 된다.
- [ ] **Step 2: 실패하는 테스트를 쓴다.**
  - `test_mof_fn_selectdoc_link_becomes_detail_url`: 목록 fixture에서 `fn_selectDoc('69292')`가 `https://www.mof.go.kr/doc/ko/selectDoc.do?docSeq=69292&menuSeq=971&bbsSeq=10`이 된다.
  - `test_mof_keeps_only_food_discount_titles`: "국산 수산물 할인 행사" 제목은 후보가 되고, "어촌뉴딜 3.0 신규 대상지" 제목은 빠진다.
  - `test_require_any_absent_keeps_old_behavior`: `government`처럼 `require_any`가 없는 출처는 기존과 같다.
  - `test_mof_press_source_order_before_groceries`
- [ ] **Step 3: 테스트가 실패하는지 확인한다.** `python3 -m unittest <파일> -v`
- [ ] **Step 4: 구현한다.** `sources/mof_press.json`의 내용은 다음과 같다.
  - `collect.html_url`: 목록 URL `https://www.mof.go.kr/doc/ko/selectDocList.do?menuSeq=971&bbsSeq=10`
  - `article_path_pattern`: `/doc/ko/selectDoc.do`
  - `keywords`, `require_any`
  - `monitoring.expect`: `working`
  - runbook: robots `Allow: /`, server_html, get, 2026-11-11 정찰 기록

  해수부 목록이 하루에 행사 제목이 없으면 기존 html 수집기가 "No matching official articles"를 낸다. 이 출처는 그날 실패가 정상이므로 runbook `monitoring`에 맞는 기대값을 정한다(빌더가 `docs/sources.md`를 보고 결정한다. 예: 빈 결과를 실패로 세지 않는 기존 옵션이 있으면 그것을 쓴다).
- [ ] **Step 5: 전체 `python3 -m unittest discover -s tests -v`를 통과시키고 커밋한다.** `feat(sources): 해수부 보도자료 할인행사 후보 수집`

### Task 2: 조사 지시문에 정부 할인행사 규칙 추가

**Files:**
- Modify: `docs/ai/prompts/research-system.md` (64행 fee_status 규칙 근처)
- Modify: `AGENTS.md` (새 승인 절 "승인된 장보기 할인행사 연결 — 2026-11-11")
- Test: 지시문 문구를 검사하는 기존 테스트가 있으면 그 파일. 없으면 `tests/test_ai_review.py`에 문구 존재 테스트 1개

**Interfaces:**
- Produces: 지시문 문장 (그대로 넣는다):
  `정부·공공기관의 농축수산물 할인행사(예: 대한민국 수산대전, 농축산물 할인지원, 한우·한돈 세일)는 신청 자격이 없으면 eligibility text=`unrestricted`, items=[]이다. 물건을 사야 받는 할인이므로 fee_status는 `paid`다. 행사 기간의 시작일과 끝나는 날을 원문 그대로 인용하고, 참여 매장 종류(대형마트·슈퍼·하나로마트·전통시장·온라인몰 등), 할인율이나 한도, 대상 품목을 conditions 인용에 원문 그대로 남긴다.`

- [ ] **Step 1: 실패하는 테스트를 쓴다.** `test_research_prompt_has_government_sale_rule`: 지시문에 `정부·공공기관의 농축수산물 할인행사`와 `unrestricted`, `paid`가 모두 있다.
- [ ] **Step 2: 실패를 확인한다.**
- [ ] **Step 3: 문장을 추가한다.** AGENTS.md 승인 절에는 다음을 적는다.
  - 사용자 결정 1·2와 출처(정책브리핑, 해수부)
  - 농식품부를 쓰지 않는 이유
  - 행사 수집 실행당 5회, 장보기 앞 순서
  - 카드 연결 규칙(시작일·끝나는 날 확인, 품목명·품목군 단어만, 넓은 표현 제외, 국산 한정 시 수입 제외)
  - `grocery_discounts` 별도 키
  - 지시문 변경으로 `ai_review.fingerprint`가 바뀌어 문법 시험 요청이 한 번 나갈 수 있다는 점
  - 사용자 승인일 2026-11-11
- [ ] **Step 4: 전체 unittest를 통과시키고 커밋한다.** `feat(ai): 정부 할인행사 조사 규칙`

### Task 3: 할인행사–장바구니 연결 모듈과 공개 키

**Files:**
- Create: `benefit_monitor/grocery_discounts.py`
- Modify: `benefit_monitor/publish.py` (`attach_grocery_baselines` 옆에 `attach_grocery_discounts(root, data, now)`. `groceries`와 `grocery_baselines`가 모두 있을 때만, 예외는 삼켜서 공개를 막지 않음)
- Modify: `benefit_monitor/public_snapshot.py` (같은 sanitize를 통과시키고, `collection_failed`면 제외)
- Modify: `public/topic-publication.json` (`policy_sha256` 재기록)
- Test: `tests/test_grocery_discounts.py`, `tests/test_publish.py`, `tests/test_public_snapshot.py`

**Interfaces:**
- Consumes:
  - 공개 혜택 항목 `items`. 필드는 `title`, `summary`, `conditions`, `valid_from`, `valid_until`, `validity_kind`, `url`, `source`, `review`이다.
  - `grocery_baselines` 묶음의 `items`(`id`, `name`, `aliases`, `group`, `row`)
- Produces:
  - `link(items: list[dict], basket: list[dict], today: date) -> list[dict]`. 각 원소는 다음과 같다.
    `{"basket_id": str, "title": str, "discount": str|None, "stores": str|None, "start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "url": str}`
    정렬은 `basket_id` 다음 `end` 오름차순이다.
  - `sanitize(bundle: object, now: datetime) -> dict|None`. 묶음 형태는 다음과 같다.
    `{"schema_version": 1, "source": "grocery_discounts", "generated_at": iso, "links": [...]}`
    오늘(KST)이 `end`를 넘었거나 `start` 전인 링크는 버린다. 링크는 최대 100개이고, 키 집합이 정확해야 한다. `url`은 https만 허용한다.
  - `briefing.json`의 최상위 키 `grocery_discounts`
  - 고정 표:
    - `GROUP_WORDS`:
      - `("수산물","수산식품")` → 장바구니 `group`이 기타인 고등어·오징어(장바구니 id로 지정)
      - `("한우","소고기")` → 한우 등심, 미국산 갈비살(국산 한정이면 제외)
      - `("한돈","돼지고기")` → 삼겹살, 목심, 앞다리
      - `("닭","닭고기","계란","달걀")` → 닭, 계란
      - `("채소",)` → 채소 묶음 전체
    - `BROAD_ONLY`: `("농축산물","전 품목","전품목","농산물")`. 이 단어만 있고 품목명이나 위 품목군 단어가 없으면 연결하지 않는다.
    - `DOMESTIC_WORDS`: `("국산","국내산","우리 ","한우","한돈")`
    - 수입 품목 id 집합은 장바구니 설정의 id를 읽어 정한다. 미국산 갈비살, 바나나가 해당한다.
  - 행사 판별: 텍스트에 할인 단어(`할인`, `세일`, `수산대전`, `농할`, `반값`, `특별판매`) 중 하나가 있어야 연결 후보가 된다.
  - 조각 추출 (정규식, 원문 그대로):
    - `discount`: `최대\s*\d{1,2}\s*%`, `\d{1,2}\s*%\s*할인`, `\d+(?:만)?\s*원\s*(?:할인|환급|한도)` 중 처음 것
    - `stores`: 단어 목록 `대형마트`, `SSM`, `슈퍼`, `하나로마트`, `전통시장`, `온라인몰`, `온라인`을 나온 순서대로 최대 3개, `·`로 잇는다.

- [ ] **Step 1: 실패하는 테스트를 쓴다.** 오늘은 `date(2026,11,11)`이다.
  - `test_link_fish_event_to_mackerel_and_squid_only`: "한국 수산식품 홍보주간 … 최대 50% … 대형마트·온라인몰", 11-07~11-27이면 고등어·오징어 링크 2개가 나온다. `discount == "최대 50%"`, `stores == "대형마트·온라인몰"`이다.
  - `test_link_skips_ended_event`: 끝나는 날 11-10이면 `[]`
  - `test_link_skips_not_started_event`: 시작일 11-12이면 `[]`
  - `test_link_requires_fixed_validity_and_both_dates`: `valid_from`이 None이거나 `validity_kind != 'fixed'`이면 `[]`
  - `test_link_hanwoo_not_attached_to_pork`: "한우세일"은 한우 등심에만 붙는다. 수입 갈비살은 국산 한정이라 제외되고, 삼겹살에도 붙지 않는다.
  - `test_link_broad_only_not_attached`: "농축산물 전 품목 최대 40% 할인"이면 `[]`
  - `test_link_domestic_excludes_imports`: "국산 과일·바나나 할인"이면 바나나 제외
  - `test_link_direct_item_name`: "양파 할인 공급"이면 양파
  - `test_link_non_discount_item_ignored`: 할인 단어가 없는 혜택 항목은 무시
  - `test_sanitize_drops_expired_links_at_now`, `test_sanitize_rejects_bad_keys_and_http_url`
  - `test_publish_attaches_discounts_when_baselines_present`, `test_publish_omits_discounts_without_baselines`, `test_public_snapshot_passes_discounts_through_sanitize`, `test_public_snapshot_drops_on_collection_failed`
- [ ] **Step 2: 테스트가 실패하는지 확인한다.**
- [ ] **Step 3: 구현한다.** 연결은 공개 직전 `publish.py`에서 그날 `items`와 `grocery_baselines`로 계산한다. 따로 캐시하지 않는다. 그 뒤 `policy_sha256`을 다시 기록하고 `tests/test_topic_publication.py`를 통과시킨다.
- [ ] **Step 4: 전체 unittest를 통과시키고 커밋한다.** `feat(groceries): 공식 할인행사를 장바구니 품목에 연결`

### Task 4: 카드 할인 줄

**Files:**
- Modify: `frontend/src/groceries.ts` (`parseDiscounts`, `discountsFor`)
- Modify: `frontend/src/GroceryQuickCheck.vue`, `frontend/src/GrocerySection.vue`, `frontend/src/App.vue`, `frontend/src/style.css`
- Test: `frontend/tests/groceries.test.ts`, `frontend/tests/e2e/groceries.spec.ts`

**Interfaces:**
- Consumes: `briefing.json`의 `grocery_discounts`(Task 3), 기존 `BasketItem`, `quickMatch`, `baselineBadge`
- Produces:
  - `interface DiscountLink{basketId:string;title:string;discount:string|null;stores:string|null;start:string;end:string;url:string}`
  - `parseDiscounts(raw:unknown, now:number):DiscountLink[]`. 형식이 틀리면 `[]`이다. 오늘(KST)이 기간 밖인 링크는 버린다.
  - `discountsFor(links:DiscountLink[], basketId:string):{shown:DiscountLink[];more:number}`. `shown`은 최대 2개이고 `end` 오름차순이다.
  - `discountLine(l:DiscountLink):string`. 형식은 `{title} {discount} · {stores} · {M/D}까지`이고, null인 조각과 그 구분자는 뺀다. 원문 링크는 템플릿에서 `<a href=url target=_blank rel="noopener">원문</a>`로 붙인다.

- [ ] **Step 1: 실패하는 단위 테스트를 쓴다.**
  - `discountLine({title:'한국 수산식품 홍보주간',discount:'최대 50%',stores:'대형마트·온라인몰',end:'2026-11-27',…})==='한국 수산식품 홍보주간 최대 50% · 대형마트·온라인몰 · 11/27까지'`
  - `discount`가 null이면 `'… · 대형마트·온라인몰 · 11/27까지'`
  - `stores`가 null이면 `'… 최대 50% · 11/27까지'`
  - `parseDiscounts`: 오늘이 `end` 다음 날이면 제외, `start` 전날이면 제외, http URL이면 제외
  - `discountsFor`: 링크 3개면 `shown` 2개, `more` 1
- [ ] **Step 2: 실패를 확인한다.** `cd frontend && node --test tests/groceries.test.ts`
- [ ] **Step 3: 카드에서 배지 줄과 근거 줄 사이에 할인 줄을 그린다.** `more>0`이면 끝에 `외 {more}건`을 붙이고, 누르면 혜택 탭(`#benefits`)으로 간다. 기존 `role="status"` 요약 끝에 첫 할인 줄 문구를 더한다.
- [ ] **Step 4: 실패하는 e2e를 쓴다.** fixture `briefing.json`의 `grocery_discounts`에 고등어 링크 3개(오늘 진행 2개 + 어제 끝난 1개)와 삼겹살 0개를 넣는다.
  - "고등어"를 검색하면 할인 줄이 2개 이하이고, 어제 끝난 행사 제목은 없다.
  - 360×800과 390×844에서 가격, 배지, 첫 할인 줄이 `toBeInViewport({ratio:1})`이다.
  - "삼겹"을 검색하면 할인 줄이 없다.
  - 원문 링크의 `href`가 fixture URL이다.
- [ ] **Step 5: 구현하고 `npm test && npm run build`와 groceries e2e, 전체 e2e를 통과시킨다.** 스크린샷 `docs/qa/screenshots/grocery-discount-{360,390}.png`를 남긴다. 덮어쓴 기존 스크린샷은 git checkout으로 되돌린다.
- [ ] **Step 6: 커밋한다.** `feat(web): 장보기 카드에 진행 중인 공식 할인행사 줄`

### Task 5: 양파 기간 평균 복구

**Files:**
- Modify: `benefit_monitor/grocery_baselines.py` (`parse_kamis_monthly`의 단위·품종·등급 읽기), 필요하면 `sources/groceries.json`의 양파 `kamis` 코드
- Create: `tests/fixtures/grocery_baselines/kamis_monthly_onion.html` (실제 응답 발췌)
- Test: `tests/test_grocery_baselines.py`

**Interfaces:**
- Consumes: `parse_kamis_monthly(page, today) -> {avg,months,from,to,unit,kind,grade}|None`, `_produce_matches(row_id, parsed)`
- Produces: 같은 인터페이스. 양파 페이지에서 `unit == "1kg"`을 읽는다. 원문에 단위가 있을 때만 그렇게 한다.

- [ ] **Step 1: 양파 기간별 페이지를 1~3회 받는다.** 현재 코드(itemcategorycode 200, itemcode 245, kindcode 00, productrankcode 0)로 받고, 필요하면 다른 kindcode도 받는다. 단위·품종이 어디에, 어떤 형식으로 나오는지 확인하고 fixture로 저장한다. **원문 어디에도 단위가 없으면 여기서 멈추고 보고한다**(설계서: 못 찾으면 숨김 유지). 이 경우 Step 2~4는 하지 않고 보고서에 근거를 남긴다.
- [ ] **Step 2: 실패하는 테스트 `test_kamis_monthly_onion_reads_unit`를 쓴다.** 양파 fixture가 `unit == '1kg'`이고 `_produce_matches('양파|양파|1kg|상품', parsed)`가 True이다. 기존 쌀·감자·고등어 fixture 테스트는 그대로 통과해야 한다.
- [ ] **Step 3: 단위 읽기를 고친다.** 새 형식을 추가로 인식하는 방식이다. 추정값으로 채우지 않는다.
- [ ] **Step 4: 전체 unittest를 통과시키고 커밋한다.** `fix(groceries): 양파 기간별 페이지 단위 읽기`
