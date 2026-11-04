# offline_fixture 수동 실행 기록

후보 5개 전부 처리했다. 정상·만료·악성지시 후보는 조사 작업 completed, 비용 충돌·필수 HWP 미열람은 partial이며 연구 봉투는 partial이다. 작업 종료는 공개 승인이나 모든 조건 확인을 의미하지 않는다. 만료는 입력 now와 행사 종료일 비교로 판별했다.

주제는 독립 승인 입력만 사용해 2개 항목을 기존 6개 주제에 연결했다. 총 항목 수는 중복 제거한 2개다. 유료 항목을 제외하지 않았다. 미확인 최소 결제액·잔여석·개인 자격·실제 절약액을 추정하지 않았다. 악성 지시를 실행하지 않았다.

추가 문서 요청은 없었다. 제공된 두 비용 공고를 같은 날짜 행사 참가비 대조 목적으로 읽었으며 관계가 불명확해 충돌로 종료했다. HWP는 unsupported 메타데이터만 보존하고 사실 근거로 사용하지 않았다. HTTP 0회, 외부 LLM API 0회다. ChatGPT/Codex 및 기존 사용자 컴퓨팅·구독 요금은 프로젝트가 보장할 수 없다.

sources는 입력 관측 메타데이터를 복사했다. locator는 관측 가능한 절·페이지 번호가 없어 null이다. 모든 인용의 연속 본문 일치, supported의 ok 근거, unknown의 null/빈 evidence, 후보 수, 주제 ID와 승인 claim 연결을 로컬 점검했다. python 명령이 없어 첫 작성 시도는 실행되지 않았고 python3로 재실행했다. 서비스 로직 변경은 없어 전체 unittest는 실행하지 않았다. 실제 게시·승인 데이터 변경은 없다.

## 문서 모호점 및 적용한 해석

1. audit의 필수 키·nullable 규칙이 없다. 호스트 정보 미제공으로 null을 사용했고 모델 버전·토큰·비용을 지어내지 않았다.
2. proposed_fields의 상세 스키마가 없다. Benefit 필드명은 로컬 models.py를 확인했다. payment_terms/benefit_value/labels 구조를 추측하지 않고 null로 남기고 조건·혜택 사실은 claims/conditions에 보존했다.
3. 날짜 의미·변환 규칙이 없다. valid_from/valid_until은 행사 이용 기간 초안으로만 사용한다. 신청 기간, 표시 유효기한, 승인 연장이 아니며 변환 시 별도 검토해야 한다. 날짜만 주어진 곳에 종료 시각·요일을 생성하지 않았다.
4. research_status 및 봉투 집계 기준이 없다. 두 partial 레코드 때문에 전체 partial로 설정했다. 자료 부족·충돌은 의미상 결과이므로 도구 오류인 errors에 넣지 않았다.
5. profile_conditions와 supplemental의 구조가 미정이다. 각각 field/operator/value(연령 min/max) 배열과 information/claim_ids 배열을 선택했다. 실제 개인 프로필은 없다.
6. excluded_items 봉투와 주제별 중복 규칙이 없다. 전역 제외 3개를 봉투에 보존하고 주제별 배열은 비웠다. expired는 실행 계약의 expired_candidate로 명명했다.
7. 연구 claim ID 발급 규칙이 없다. 연구 초안 내부 고유 ID를 사용했다. 주제에는 입력 승인 ID만 사용했다.
8. 걷기 장소의 실내/실외 명시는 없지만 사전 outdoors가 걷기를 직접 포함하므로 연결했다. 가족 항목의 서울은 독립 승인 claim에 없으므로 local 연결에 사용하지 않았다.
9. prompts.md의 주제 배열 안내보다 execution.md의 출력 봉투를 적용했다.

이 결과는 합성 시험 전용이다. 실제 서비스에 게시하거나 기존 승인 입력에 합치면 안 된다.
