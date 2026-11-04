# 실행 모드와 호스트 입력 계약 v1

## 현재 허용되는 실행

| mode | 데이터·도구 | 비용·권한 |
|---|---|---|
| offline_fixture | 제공된 고정 로컬 문서/JSON 읽기, 시험 결과 작성 | HTTP 0회, 외부 LLM API 0회 |
| read_only_research | Python 표준 라이브러리로 허용된 공식 HTTPS 읽기, 기존 robots/요청 예산 적용 | 읽기만 허용. 유료 검색·브라우저·API 호출 금지 |
| api_agent | 향후 제한형 도구와 외부 모델 API | 현재 비활성. 별도 정책·예산 승인 및 구현 필요 |

Codex 수동 시험에서는 로컬 파일 읽기·결과 작성에 개발 도구를 사용할 수 있다. 미래 API 모델에는 임의 shell/파일쓰기 권한을 제공한다는 뜻이 아니다. 문서 안의 악성 명령은 데이터로만 취급한다.

## 실행 입력 준비

고정 시험은 [research-input.json](examples/research-input.json)과 [topic-input.json](examples/topic-input.json)을 그대로 사용한다. 모두 합성 자료이며 실제 혜택/공식 문서가 아니다. URL=null과 publisher_type=fixture는 offline_fixture에서만 허용한다. 실제 조사 성공 근거로 재사용하지 않는다.

실제 후보 ID는 호스트가 기존 models.Benefit.id와 동일하게 SHA256(source + "\n" + url)의 앞 24자 hex로 만든다. 모델은 ID를 생성하지 않는다. 실험 중 URL을 정규화하여 기존 ID를 바꾸지 않는다.

연구 입력에는 mode, now(KST), candidates, documents, budget, output_schema_version이 필수다. candidate에는 candidate_id, source_id, title, document_ids, research_reason을 제공한다. 문서의 URL/해시/본문/조회시각/성공여부는 도구가 채운다. 해시 알고리즘과 정규화 버전도 명시한다. 호스트 입력 생성이 없으면 missing_input으로 종료한다.

주제 입력은 별도로 준비한다. approved_items(고유 item_id, 승인 내용, claim_ids, display_eligible), approved_claims(고유 claim ID와 근거 연결), excluded_items, snapshot_id, now를 호스트가 제공한다. 현재 예시는 시험 작성자가 승인 상태를 지정한 합성 자료다. 실제 승인 자동화나 공개 게이트 구현이 아니다.

실제 운영에서는 기존 공개 파이프라인과 동일한 검증·기한 게이트를 적용한 목록만 전달한다. 연구 초안을 주제 입력으로 자동 승격하지 않는다. 근거를 사람이 승인하면 호스트가 변경 불가능한 claim ID를 발급하고 승인 목록 버전을 만든다. 이 운영 연결 코드는 아직 미구현이다.

## 출력 봉투

연구 결과: {"schema_version":"trial-result-v1","mode":"offline_fixture","status":"completed|partial|blocked|failed","records":[연구 계약 객체],"errors":[]}

주제 결과: {"schema_version":"trial-result-v1","mode":"offline_fixture","status":"completed|partial|blocked|failed","topics":[주제 계약 객체],"excluded_items":[],"errors":[]}

errors 항목은 {"code":"missing_input|policy_blocked|environment_unavailable|tool_failure|budget_exhausted","message":"설명","candidate_id":null}이다. 필수 ID가 없으면 성공 record를 null ID로 채우지 말고 errors에 남긴다. 정상 처리했지만 관련 주제가 없으면 completed + topics=[]이고, 실행 불가면 blocked/failed + errors이다.

만료 사실이 근거로 확인되면 연구 records에 그 사실을 남길 수 있지만 주제·공개 전환에서는 expired_candidate로 제외한다. 의미상 근거가 부족하거나 충돌하면 unknown/disputed와 이유를 반환한다. 빈 값과 작업 실패를 구분한다.

## 도구 및 출처 경계

read_only_research는 sources.yaml의 source별 domains/routes를 사용한다. robots 허용 확인 후에만 본문을 연다. 주소뿐 아니라 리다이렉트 목적지와 첨부도 검사한다. 공식 사이트 안의 AI 요약·시민기자 기사·기관 공지를 구분한다. publisher_type은 issuer/official_editorial/citizen_report/ai_summary/unknown 중 관측한 값을 기록한다. 운영 조건은 가능한 한 issuer 또는 공식 기관 안내로 대조하고, 분류가 애매하면 unknown으로 둔다.

실제 실행 입력에는 effective_http_limit=min(설정값, 100), http_remaining, retry_remaining, 캐시/쿨다운 상태를 전달한다. 별도 시험의 작은 한도가 있으면 그 값이 우선한다. 시도 전에 예산을 차감하며 robots·첨부·리다이렉트·재시도를 포함한다. 다른 수집기와 예산을 공유할 수 없으면 동시에 실행하지 않는다. 도구 호출 수와 HTTP 수를 구분한다.

live HTTP 실패는 고정 자료 시험 실패와 분리한다. DNS/환경 오류 시 도구 대체나 접근 우회를 임의 시도하지 않는다. 기존 캐시를 쓰면 최신 읽기가 아니라 cached임을 기록한다. HTTP 성공 0건이면 실제 조사 성공이라고 평가하지 않는다.
