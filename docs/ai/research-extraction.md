# 조사 추출 계약 v3 — 표준 필드와 누락 차단

후속 Claude 조사 요청은 `research-extraction-v3` JSON 하나를 반환한다. [v3 스키마](schemas/research-extraction-v3.schema.json)가 정확한 형식이다. Python 조립 후 기존 [v1 내부 출력 계약](output-contract.md)과 근거 검증을 그대로 적용한다.

## AI와 Python의 역할

AI는 후보 참조·조사 상태·중단 사유와 사실(field/value/status/evidence/unknown_reason)을 작성한다. Python은 source ID·URL·본문 해시·조회 시각·claim ID·봉투·미확인 질문·충돌 참조를 채운다. 근거는 호스트가 제공한 문서 ID와 정확한 연속 인용이어야 한다. 개인 프로필·키·승인 필드는 출력하지 않는다.

아래12개 필드는 후보마다 정확히 한 번 확인한다. 자료에 없으면 생략하지 않고 `status=unknown`, `value=null`, `evidence=[]`, 구체적인 `unknown_reason`을 남긴다. 한국어 별칭을 임의로 쓰지 않는다. 선택 필드는 summary/conditions/districts이며 중복 필드는 거절한다.

| field | supported/disputed 값 형식 |
|---|---|
| eligibility | scope, required[], not_confirmed[] 객체 |
| event_period | start/end 날짜 객체; YYYY-MM-DD 또는 null |
| application_period | start/end 객체; timezone이 있는 timestamp 또는 null |
| fee_status | free/paid/conditional |
| cost_details | 참가·재료·최소구매 등 비용 설명 문자열 |
| payment_conditions | 결제수단·포인트·중복 적용 등 문자열 |
| selection | 선착순·추첨·심사 등 문자열 |
| capacity | 모집정원 정수; 현재 잔여석과 별개 |
| application_method | 신청·본인확인·서류 등 문자열 |
| cancellation | 취소·노쇼·지각 조건 문자열 |
| restrictions | 기타 필수 제한 문자열 |
| availability | 이번 계약에서는 unknown만 허용; 잔여석은 별도 실시간 확인 필요 |

eligibility.scope는 restricted/unrestricted/disputed다. restricted에는 구체적인 required 조건이 있어야 한다. unrestricted에 필수 제한을 동시에 넣지 않는다. disputed는 양쪽 근거를 기록하고 해결됐다고 추정하지 않는다. 정확한 나이·거주지·추가비용이 미명시면 not_confirmed 또는 별도 unknown으로 남긴다.

지원된 이용기간은 Python이 valid_from/valid_until로, 접수 종료는 deadline_at으로 옮긴 뒤 기존 날짜·만료 검사를 적용한다. 날짜를 추정하거나 timestamp를 잘라 날짜로 고치지 않는다. 미확인 값·잘못된 인용을 지워 통과시키지 않는다.

## 요약·상세 차이 검사

요약의 대상란뿐 아니라 같은 후보의 상세·주의사항·보조 문서를 모두 읽는다. `대상 제한없음`과 본문의 `유아동반 가족`처럼 범위가 달라 보이면 제한없음만 전체 자격으로 확정하지 않는다. 상세 제한을 보존하고, 관계가 불명확하면 disputed/unknown과 양쪽 근거를 남긴다.

호스트는 현재 다음과 같은 제한 후보 문구를 탐지한다: 유아/어린이/아동/성인/청년/가족/주민/회원과 동반·대상·한정·전용 표현, 해당 그룹이 붙은 대상란, 나이 범위. 각 문구가 올바른 문서의 eligibility/restrictions 인용에 포함되고 추출 값에도 남아 있는지 확인한다. 다른 후보의 인용이나 not_confirmed에만 옮기는 것으로 확인된 제한을 대신하지 않는다. 문구가 있는데 unrestricted로 단정하면 거절한다.

**이것은 한정된 문구 검사다.** 모든 자격·부정문·예외·의미상 동등 표현을 판별하지 못한다. 실제로 무관한 언급도 보수적으로 검토에 걸릴 수 있다. 오탐을 피하려고 조건을 지우거나 모델이 자동 승인하지 않는다. 통과해도 사람의 의미·사실·공개 승인이 필요하다. 필수 필드를 모두 unknown으로 채운 결과를 조사 성공이나 완전한 조건 해결로 집계하지 않는다.

## 이전 버전과 현재 판정

v2 스키마와 과거 응답·프롬프트·검증 기록은 보존한다. 읽기 전용 재생은 v2의 원래 형식 통과와 새 coverage 거절을 별도로 보고한다. 새 v3 요청에는 v2 응답을 받아들이지 않는다.

[실제 v2 재실험](evaluations/claude-v2-trial-2026-11-05/README.md)은 형식 통과에도 가족 조건을 누락했다. [v3 로컬 보강·재검증](evaluations/claude-v3-guard-2026-11-05/README.md)에서는 그 실패를 차단했다. 새 모델 출력 품질·실제 토큰 절감·독립 보류표본 우위는 아직 미측정이다. 자동 검색·정기 실행·공개 연결은 없다.
