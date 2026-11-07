# Task 4 보고

## 구현
- research_guard.FIELDS에 선택 필드 `published_at` 추가(REQUIRED_FIELDS 아님).
- wire_format: published_at은 `start` 칸에 `YYYY-MM-DD`, 빈 값/형식 오류/end 사용은 `invalid period format`, 근거 필수. unknown이면 선택 필드라 버려짐. 스키마는 enum에 값 하나 늘 뿐 union/pattern 없음.
- v3 스키마 JSON: 텍스트 필드 분기 enum에 published_at 추가.
- ai_contract: 후보 문서 집합과 인용 출처 집합이 다르면 gap이던 조건을 `not sources`(출처 없음)로 완화. 후보 밖 문서는 기존 `document belongs to another candidate`로 계속 거부.
- 프롬프트: 필드 행, 슬롯 설명, 다문서 인용 줄, 규칙 세 가지(연도 없는 날짜 unknown, 문서 간 불일치 disputed, 종료/마감/결과 발표/지난 차수는 restrictions 근거).

## TDD
- RED: test_published_at_requires_date_and_segment (KeyError published_at), 다문서 테스트 실패 확인.
- GREEN: tests.test_wire_format 19개 통과. 전체 `unittest discover` 493개 OK.
- 다문서 테스트는 d1s4, d2s2 근거가 각각 doc-a, doc-b source_ref로 매핑됨을 확인.

## 파일
benefit_monitor/{ai_contract,research_guard,wire_format}.py, docs/ai/prompts/research-system.md, docs/ai/schemas/research-extraction-v3.schema.json, tests/test_wire_format.py

## 자체 점검 / 우려
- 스키마 sha 변경 -> 다음 실행에서 문법 시험 1회 자동 발생(호출은 하지 않음, 기존 sha 기반 경로 사용).
- readiness 완화 테스트는 gap이 다른 조건(availability unknown, valid_until 없음)으로도 걸려 `ready`까지 도달시킬 수 없어, 부분집합 인용이 유효하고 외부 문서 출처는 거부됨만 검증함(판별력 한계).
- 전체 실행 출력의 `::error::` 줄은 기존 테스트의 모의 경로 출력.

## 수정 라운드 1
1. tests/test_ai_contract.py에 직접 검증 추가: 예제 결과에서 critical 질문·unknown claim을 제거해 `ready_for_human_review`에 도달시킨 뒤, 후보 document_ids에 문서를 하나 더 넣어도 여전히 ready. 변경 전 ai_contract(HEAD~1)로 되돌리면 이 테스트가 `needs_review != ready_for_human_review`로 실패함을 확인, 복원 후 통과. "출처 0개" 케이스는 supported claim이 근거로 출처를 요구해 validate 입력으로 만들 수 없어 생략.
   - 후보 밖 문서 출처는 `document belongs to another candidate`로 거부되는 테스트 추가.
2. test_wire_format의 외부 출처 케이스: 변환기는 후보 문서로만 sources를 만들어 외부 근거가 KeyError로 끝나므로, 외부 문서를 sources에 직접 넣고 validate가 위 사유를 내는지 단언.
3. 프롬프트: published_at의 연도 없는 값도 unknown, 사유에 원문 날짜, 연도 없는 값은 응답 전체 거부 사유임을 명시.
4. `test_published_at_end_slot_is_rejected` 추가.
- 결과: 대상 테스트 48개 OK, 전체 496개 OK.
