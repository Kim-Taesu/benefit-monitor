# 조사 및 주제 출력 계약

버전: draft-v1. 조사/주제 출력 JSON Schema와 Python 표준 라이브러리 검증기를 구현했다. [검증 실행과 한계](validation.md)를 함께 따른다. 운영 승인·변환 연결은 아직 구현하지 않았다. 아래 필드를 기존 Benefit 객체에 직접 추가하거나 briefing.json에 그대로 게시하지 않는다.

시험 결과의 바깥 봉투와 오류 반환은 [실행 계약](execution.md)을 따른다. 관측 메타데이터가 없는 실패를 성공 객체의 null ID로 대신하지 않는다.

## 조사 초안

| 필드 | 형식 / 의미 |
|---|---|
| schema_version | 문자열 `research-draft-v1` |
| candidate_id, source_id | 호스트가 제공한 ID. AI가 새 source를 발급하지 않음 |
| research_status | completed / partial / blocked / failed. 공개 승인과 무관 |
| sources | 아래 근거 문서 배열 |
| claims | 아래 주장 배열 |
| missing_questions | field, question, importance(critical/optional), reason |
| conflicts | field, claim_ids, description, resolution(null 또는 근거 있는 해결 설명) |
| proposed_fields | 기존 Benefit에 대응할 summary/conditions/districts/날짜/fee_status/labels/payment_terms/benefit_value의 초안. 알려지지 않은 값은 null 또는 unknown |
| supplemental | 공식 준비물·예약 방법 등 보충 정보와 claim_ids. 본문 사실과 같은 검증 기준 |
| review_reasons | 사람이 확인해야 하는 이유 배열 |
| stop_reason | sufficient_evidence / budget_exhausted / access_blocked / unsupported_document / unresolved_conflict / tool_failure |
| audit | 호스트가 채우는 모델/프롬프트/계약/파서 버전, 실행 시각, 토큰, 도구 횟수, 추정 비용 |

### 근거 문서 sources[]

`id`, `requested_url`, `final_url`, `source_id`, `document_role`(notice/terms/attachment/correction/faq), `retrieved_at`, `published_at`(불명확하면 null), `body_hash`, `extraction_scope`, `fetch_status`(ok/blocked/failed/unsupported).

URL·해시·조회 시각·성공 여부는 **도구가 관측한 값으로 호스트가 채운다**. AI가 지어내거나 수정하지 못하게 한다. fetch_status가 ok가 아니면 해당 문서를 사실 근거로 사용할 수 없다.

### 주장 claims[]

`id`, `field`, `value`, `status`(supported/unknown/disputed), `evidence` 배열(`source_ref`, `quote`, `locator`).

- supported는 읽은 원문이 해당 주장을 뒷받침한다는 후보 상태이며 사람 승인과 다르다.
- quote는 실제 추출 본문의 연속된 구절이다. 변경/요약된 문장을 직접 인용으로 넣지 않는다.
- locator는 관측 가능한 절·페이지 번호. 알 수 없으면 null이다.
- supported에는 최소 1개 유효 근거가 필요하다. unknown의 value는 null이고 evidence는 빈 배열이다.
- disputed에는 충돌하는 근거를 각각 남기고 대표값을 강제로 선택하지 않는다.
- 인용이 존재한다는 것만으로 의미상 일치가 보장되지 않는다. 숫자·단위·최대/확정·조건 연결을 별도 검사한다.

### 기존 공개 스키마로의 변환 경계

1. 초안을 별도 비공개 경로에 둔다. public/verified.json, inputs/public.json, cache/verified_items.json으로 자동 저장하지 않는다.
2. 호스트가 ID·출처·인용 실재성·스키마·시간대·모순·개인정보를 검사한다.
3. 중요 필드 충돌이나 필수 문서 미열람은 검토 대기로 남긴다.
4. 승인자가 원문과 필드를 확인한 뒤 기존 Benefit 필드로 변환한다. verified_at/public_release는 기존 승인 절차에서만 설정한다.
5. validation.py 및 publish.py의 기존 검증을 통과해야 한다. 기존 benefit_value는 특정 원문 문구 형식을 요구하므로 새 AI 출력이 이를 우회하면 안 된다.

`proposed_fields`의 알 수 없는 값은 승인 변환 시 기존 스키마에 맞게 명시적으로 처리한다. 기존 스키마가 nullable이 아닌 항목에 임의의 빈 문자열을 넣어 통과시키지 않는다.

## 주제 제안

| 필드 | 형식 / 의미 |
|---|---|
| schema_version | `topic-draft-v1` |
| topic_id | 기존 허용 ID 또는 검토 대기 신규 ID |
| title | 짧은 한국어 명사/행동 중심 제목. 보장·과장 표현 금지 |
| item_links | item_id, evidence_claim_ids, reason, match_type(explicit/contextual) |
| profile_conditions | 구조화된 선택 조건. 실제 사용자 프로필 값은 포함하지 않음 |
| excluded_items | item_id, reason |
| snapshot_id | 호스트가 제공한 검증 목록 버전 |
| audit | 모델·프롬프트 버전 등 호스트 기록 |

AI가 목록에 없는 item ID나 URL을 생성하면 거부한다. 기존 데이터 검증 게이트를 통과한 항목만 화면 연결 가능하다. 건수는 AI 출력에 의존하지 않고 렌더링 시 유효 ID의 중복 제거 후 계산한다. confidence 점수로 자동 승인하지 않는다.

## 현재 검증기에서 지원하는 범위

`audit`은 모델 출력에서 null만 허용한다. 호스트 실행 기록은 별도 보고서에 보관한다. `proposed_fields`의 `labels`, `payment_terms`, `benefit_value`는 구조가 확정될 때까지 null만 허용하고 상세 사실은 claims에 둔다. 임의 객체를 기존 공개 필드에 주입하지 않는다. 주제 profile_conditions는 district/participation/carrier의 eq 또는 age의 between만 허용한다. 스키마 밖 필드는 거부한다.

`research_status`와 `stop_reason`은 모델의 작업 종료 보고다. 공개 준비도 선언이 아니다. 검증기는 별도 assessments에 execution_status와 evidence_readiness를 기록한다. ready_for_human_review도 사람 검토 대상일 뿐 승인 상태가 아니다.
