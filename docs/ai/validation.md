# AI 초안 로컬 검증

외부 패키지·API·네트워크 없이 저장된 초안을 검사한다. 공개 JSON과 기존 수집기를 변경하지 않는다.

```sh
python3 -m benefit_monitor.ai_contract research docs/ai/examples/research-input.json docs/ai/evaluations/v2/research-result.json
python3 -m benefit_monitor.ai_contract topic docs/ai/examples/topic-input.json docs/ai/evaluations/v2/topic-result.json
python3 -m unittest discover -s tests -v
```

종료 코드 0은 구조·참조 검사 통과이며 사실 승인이나 게시 허가가 아니다. 오류면 종료 코드 1이다. 입력은 신뢰할 수 있는 호스트가 생성해야 한다. 모델이 입력과 결과를 함께 조작하는 상황을 방어하는 인증 기능은 없다.

## 검사 범위

- [조사 스키마](schemas/research-result.schema.json), [주제 스키마](schemas/topic-result.schema.json): 필수 키, 타입, enum, 여분 키 거부.
- 호스트 후보·문서 ID, 메타데이터 일치, 본문 SHA256, 연속된 실제 인용, 성공 문서 여부.
- unknown/disputed 처리, 충돌·보충 설명의 claim 참조, 시간대와 종료 날짜.
- 승인 snapshot 및 허용 주제, 표시 가능한 item, **해당 item에 속하는** 승인 claim 연결.
- 승인 필드 주입 거부. 합성 자료는 실제 조사 결과로 제출 불가.

Python 검사기는 이 두 스키마가 사용하는 type/enum/minLength/properties/required/additionalProperties/items/anyOf만 지원한다. 범용 JSON Schema 엔진이 아니다. 스키마 확장 시 검사기와 테스트도 함께 확장해야 한다.

## 호스트 판정

| evidence_readiness | 의미 |
|---|---|
| expired | 제안 종료일 또는 신청 마감이 지남. 공개 후보 제외, 날짜 자체는 사람 확인 필요 |
| needs_review | 중요 질문, 미열람 문서, 충돌, 미완료 또는 종료일 누락 |
| ready_for_human_review | 위 기계 검사에서 누락을 찾지 못함. 여전히 원문과 의미를 사람이 검토 |

종료일은 서울 날짜 기준으로 비교한다. 부분 작업 완료(completed)도 needs_review일 수 있다. 합성 시험은 항상 synthetic=true로 표시한다.

인용 존재가 주장 의미·수치·수수료·자격의 정확성을 증명하지 않는다. 모델이 빠뜨린 질문을 자동 발견하거나 제안 요약의 모든 문장을 의미 검증하지 않는다. 실제 공식 출처 allowlist/robots/리다이렉트/예산/캐시 검사는 수집 호스트의 책임이며 이 오프라인 검사기로 대체하지 않는다. 운영 승인 snapshot 생성과 공개 파이프라인 연결은 미구현이다. 공개 게이트 우회 용도로 사용하지 않는다.

## 2026-11-04 재검증

v2 원본 결과를 수정하지 않고 검사했다. 조사 5건 중 4건은 needs_review, 1건은 expired다. 주제 6개는 승인된 합성 항목과 claim 참조 검사에 통과했다. 새 모델 연구 결과가 아니라 기존 결과의 기계적 재검증이다.

실제 조사 DNS 재확인: mediahub.seoul.go.kr 이름 해석이 `[Errno 8] nodename nor servname provided, or not known`으로 실패했다. HTTP 요청·성공·본문 열람 모두 0건. 다른 도구로 우회하지 않았다. 실제 네트워크 조사 품질은 아직 검증되지 않았다. 외부 LLM API 호출·추가 서비스 구매는 없으며 사용자의 기존 Codex/ChatGPT 구독·컴퓨팅 비용은 이 프로젝트가 보장하지 않는다.
