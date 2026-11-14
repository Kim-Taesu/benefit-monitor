# Phase 1 평가 실행과 해석

이 평가 도구는 표준 라이브러리와 기존 실제 게이트를 사용한다. 키를 읽거나 API·공식 사이트를 호출하지 않으며 운영 원장과 공개 상태를 수정하지 않는다. 평가 파일은 현재 작업 트리 안에 쓰고 기존 결과 파일 덮어쓰기를 거부한다.

## 세 가지 결과를 분리

| 평가 | 입력 | 알 수 있는 것 | 알 수 없는 것 |
|---|---|---|---|
| 고정 사례 | `cases.json`의 합성 입력·수작업 초안, 별도 `contract.json` | 실제 게이트가 과거 실패·경계 사례를 올바르게 처리하는지 | 현재 모델의 추출 정확도·인젝션 저항성 |
| 과거 응답 재생 | 실제 저장된 입력·응답·메타데이터·선택적 비용 원장 | 현재 코드와 과거 응답의 호환성, 거절 분류 | 최신 원문·현재 배포 결과·현재 프롬프트의 효과 |
| 같은 입력 비교 | 재생 검사를 통과한 주제 응답과 `daily_topics.basis_cards()` | 연결 수·중복·동일 입력 조건, 평가 가능한 카드 | 사용자 평가 전 개인 유용성 |

35개 고정 사례는 기존 회귀 사례와 통과 프롬프트 예시를 바탕으로 만들었다. 원문·URL도 합성 fixture이므로 실제 공식 확인으로 해석하지 않는다. 별도 정답 계약은 평가 실행 코드가 읽기만 한다. 계약의 `expected`는 자동 비교하고, `expected_facts`, `forbidden_claims`, `evidence_ids`는 독립 검토를 위한 명시적 라벨이다. 모든 문장의 의미를 자동 판정한다는 뜻은 아니다. 현재 라벨의 독립 리뷰는 미완료다.

## 고정 사례 실행

작업 트리 루트에서 실행한다. 새 출력 이름을 사용한다.

```sh
python3 -m benefit_monitor.evaluation cases --output .tools/evaluation/gates-run1.json
```

기대 결과 불일치는 종료 코드 1이다. 평가 도구 오류는 예외로 실패한다. 코드·프롬프트·입력·계약 해시, Git 기준 커밋, 검사 시각과 로컬 검사 시간을 남긴다. 작업 트리 변경은 코드 해시에 반영한다. 통과율·위험한 수용·유효 사례 거절을 별도로 센다.

R01~R14는 기간·비용·근거·철회·신선도, V01~V08은 대조/후보 분류, B01~B06·F01~F03·G01~G02·H01~H02는 추천 문장 검사다. R13은 악성 문구를 무시한 답을 검사하는 사례이며 실제 모델이 그 문구를 무시하는지 시험하지는 않는다.

## 저장된 실제 응답 재생

```sh
python3 -m benefit_monitor.evaluation replay \
  --input /Users/user/personal/benefit-monitor/.maintenance/p0-source/.tools/claude-trial/live \
  --output .tools/evaluation/recorded-run1.json
```

허용 프로젝트 내부의 명시한 디렉터리에서 `runs/*/{input,metadata,model-output,rejected-result,result}.json`, `responses/<id>.json`, `budget.json`만 읽는다. 키·설정·다른 `.tools` 파일을 탐색하지 않는다. 입력 해시를 메타데이터와 대조하고, 원장에 응답 해시가 있으면 원본 응답도 대조한다. 원장이 없거나 원본 응답 대신 저장된 초안만 있으면 공급자 응답의 완전한 진위 검증은 할 수 없다.

원문의 `fetch_status`는 **당시 저장된 읽기 상태**다. 완전한 응답 저장은 extraction 관측이며 의미상 추출 성공을 뜻하지 않는다. 조사 v3만 자동 공개 게이트를 과거 입력 시각에 재적용한다. 이전 계약은 현행 공개 평가와 섞지 않는다. `artifact_invalid`, `missing_response`, 입력/응답 해시 불일치는 검증 성공이 아니다.

비용은 원장에 일치하는 완료 요청의 `charged_microdollars`만 사용한다. 로컬 계산 기록이지 공급자 청구서가 아니다. 실패·예약 보존 금액과 전체 계정 사용액을 이 합계로 대체하지 않는다. 기록 없는 비용·전체 소요시간·사용자 반응은 `null`이다.

## 단계별 관측 가져오기

`events`는 다음 형식의 배열을 읽는다. 같은 run/stage 중복은 거절한다. stage 내부의 여러 문서·호출은 먼저 합산해 한 관측으로 기록한다.

```json
[
  {"run_id":"sample-001","stage":"read","status":"failed","reason":"fetch_failed","duration_ms":null,"cost_usd":null},
  {"run_id":"sample-002","stage":"validation","status":"failed","reason":"format","duration_ms":12,"cost_usd":0}
]
```

```sh
python3 -m benefit_monitor.evaluation events --input .tools/evaluation/events.json --output .tools/evaluation/stages-run1.json
```

단계는 collection/read/extraction/validation/publication/recommendation/response다. status는 ok/failed/held/skipped다. response에는 평가한 경우에만 `useful: true|false`를 넣는다. 관측이 없는 단계는 건수 0과 측정값 null로 구분한다. 시간·비용 일부가 빠졌으면 전체 합계를 임의 추정하지 않는다. 사용자 유용성 평가가 없으면 유용한 추천당 비용은 null이다.

`cli.run`과 `ai_daily.daily`에는 비공개 단계 계측이 연결되어 있다. `cache/ai_daily/observations.json`에 최근 1,000행만 저장하며 기존 비공개 runtime 아카이브에 포함된다. 원문·프롬프트·개인 프로필·예외 메시지는 저장하지 않는다. 저장이나 진단 출력 실패가 기존 결과·예외를 바꾸지 않는다. 사용자 반응은 수집하지 않는다.

`attempt_id`는 한 실행, `run_id`는 개별 span 식별자다. 여러 문서 읽기/추천은 별도 span으로 기록하므로 같은 stage의 여러 행을 합쳐 성공한 실행 수로 해석하지 않는다. `ok`는 해당 함수의 정상 반환이고, 사실 정확성·공개 완료·사용자 유용성을 뜻하지 않는다. `stopped_before_result`는 실패, 규칙 대체는 held로 분류한다.

`extraction` 시간은 부모가 측정한 모델 subprocess 전체 시간(기동·사전 검사·API·내부 검증 포함)이다. subprocess 내부 최초 validation 시간은 별도 측정하지 않으며 부모에서 `evaluate_draft`를 거치는 재검증만 validation으로 남는다. 중첩 span의 시간을 합산하면 중복되므로 전체 지연으로 보고하지 않는다. 온라인 이전 수집 snapshot 재사용과 offline 수집은 skipped다. 계측값은 실제 공급자 청구와 연결되지 않아 extraction 비용은 null이다. 기존 재생 원장은 별도로 비교한다.

```sh
python3 -m benefit_monitor.evaluation events --input cache/ai_daily/observations.json --output .tools/evaluation/runtime-stages-run1.json
```

현재는 로컬 테스트로 저장·복원과 오류 격리를 확인했다. 배포 후 실측이 필요하며 전체 운영 단계와 사용자 반응 계측 완료를 뜻하지 않는다. 실패 사유 구분은 수집 실패(fetch_failed), 형식(format), 근거(grounding), 의미(semantic), 공개 보류 사유, 추천 미노출(validation_rejected)로 유지한다.

## 규칙 추천과 AI 추천 비교

```sh
python3 -m benefit_monitor.evaluation compare \
  --input /Users/user/personal/benefit-monitor/.maintenance/p0-source/.tools/claude-trial/live \
  --output .tools/evaluation/comparison-run1.json \
  --key .tools/evaluation/blind-keys.json \
  --ratings .tools/evaluation/blind-packets.json
```

입력·시각이 같은 상태에서 현행 검사를 통과한 AI 주제 결과와 기존 규칙 카드를 비교한다. 부적합한 과거 응답을 유효 추천인 것처럼 평가에 섞지 않는다. 두 결과 중 어떤 것이 AI인지 매핑한 키는 분리한다. 문체로 출처를 추측할 수 있으므로 완전한 이중맹검 실험은 아니다.

비교 packet에는 원래 입력 맥락이 포함되므로 `.tools`에만 저장한다. 공개 보고서에는 해시와 개수만 넣는다. `--ratings`는 비교 명령에서 미평가 packet 출력 경로이고, score 명령에서는 사람이 채운 평가 입력이다.

평가자는 키를 읽지 않고 A/B마다 다음을 기록한다.

- useful: 선택하거나 원문을 확인하는 데 도움이 되었는가?
- grounded: 제공된 근거에 맞고 과장·자격 보장이 없는가?
- duplicate: 불필요하게 같은 항목을 반복하는가?

미평가는 null을 유지한다. 평가 파일은 `{ "packet의 id": {"A": {"useful": true, "grounded": true, "duplicate": false}, "B": {...}} }` 형식이다. 단일 packet에서는 id 바깥 객체 없이 A/B 객체를 사용한다.

```sh
python3 -m benefit_monitor.evaluation score \
  --input .tools/evaluation/blind-packets.json --key .tools/evaluation/blind-keys.json \
  --ratings .tools/evaluation/ratings.json --output .tools/evaluation/scores-run1.json
```

현재 비교 가능한 실제 저장 사례는 1개이고 기준 시각은 2026-11-19인 과거 개발용 재생 시나리오다. 지금의 실제 혜택 상황이나 충분한 표본이 아니다. 두 방식 모두 고유 항목 5개, 규칙은 연결 5개·중복 0개, AI는 연결 6개·중복 1개다. 다양성이나 사용성이 더 좋다는 결론은 내리지 않는다.

## 이번 기준선과 남은 관측

[기준선 요약](baseline-summary.md)을 참고한다. 35개 게이트 사례 실행과 과거 응답 재검사·비교 도구는 구현했다. 정답 35개는 독립 agent가 원문·기대 계약을 대조하고 수정 후 재검토했다([검토 기록](review-2026-11-14.md)). 사람 검수나 모델 평가용 holdout은 아니다. 실제 현재 모델 평가, 사용자 유용성 평가, 운영 단계 소요시간 실측은 남아 있다. 이 항목을 완료하기 전 Phase 1 전체가 달성됐다고 표시하지 않는다.
