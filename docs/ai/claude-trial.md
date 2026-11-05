# Claude $5 일회 실험 사용법

현재 상태: v2·v3 실제 실험을 수행했고, 사용자 승인4일 운영 연결·정기 등록·공개 화면을 검증했다. 자동 사실 승인 품질은 입증하지 못해 AI 초안은 비공개 사람 검토 대기에만 저장한다. [전체 연결 결과](evaluations/goal-integration-2026-11-05/README.md)와 [운영 상태](automation.md)를 먼저 읽는다.

2026-11-05부터 실제 요청은 [구조화 출력 전송 계약](structured-output.md)과 `docs/ai/prompts/`의 전용 프롬프트를 쓴다. 아래 설명 중 문서 묶음을 시스템 프롬프트로 보내던 부분은 이전 방식이다.

## 키와 예산

키는 프로젝트 루트의 Git 제외 `.env.claude`에 `ANTHROPIC_API_KEY=...` 한 줄로 저장한다. 권한은 600이며 심볼릭 링크를 허용하지 않는다. 키를 채팅·로그·VITE 변수·공개 JSON에 넣지 않는다. 사용자 계정 지출 한도 $5와 로컬 누적 한도를 함께 사용한다.

원장 `.tools/claude-trial/live/budget.json`은 이미 초기화됐다. **다시 init하거나 원장을 삭제·복사·초기화하지 않는다.** 실행 위치는 이 작업 저장소 루트다. 다른 root의 별도 예산 생성을 차단한다.

```sh
python3 -m benefit_monitor.claude_trial status
```

이 명령은 키를 읽거나 네트워크를 호출하지 않는다. 상한은 매일 $5가 아니라 전체 실험 누적 $5·200요청이다(2026-11-05 사용자 승인으로 40요청에서 상향, 금액은 유지). 실패 예약도 남고 재시작·날짜 변경으로 리셋되지 않는다. 현재 usage 계산액 $0.046849, 실패 포함 점유 $0.077693다. 실제 계정 청구서는 별도로 확인한다.

## 연결·입력·출력

```sh
python3 -m benefit_monitor.claude_trial auth
python3 -m benefit_monitor.claude_trial run --kind research --input .tools/claude-trial/inputs/검토한-조사입력.json
python3 -m benefit_monitor.claude_trial run --kind topic --input .tools/claude-trial/inputs/검토한-주제입력.json
```

위는 후속 검토용 명령 형식이며 추가 실행 권고가 아니다. auth도 실제 요청이면 총 호출 수를 차감한다. 같은 키·요청의 성공 캐시는 재사용한다. 입력·프롬프트·생성 설정이 달라지면 새 유료 요청이다. 모델은 `claude-haiku-5-5`, API는 `api.anthropic.com`만 사용한다. 입력 요청 최대 64,000 UTF-8 bytes, 출력 최대 8192토큰이며 thinking은 비활성이다. 유료 검색·서버 도구·캐싱 요금 모드·고속 처리·다른 모델 자동 전환은 사용하지 않는다.

호스트 입력은 `mode=api_agent`, `synthetic=false`인 프로젝트 내부 JSON이어야 한다. 조사 입력은 기존 allowlist의 공식 본문·ID·해시·시각을 포함한다. 주제 입력은 사람 검토 ID에 묶인 평가용 스냅샷 또는 기존 공개 승인·현재 유효 사실과 검토된 편집 근거를 대조한 운영 스냅샷으로 한정한다. 개인 프로필·클릭 기록·키는 보내지 않는다. 이 CLI는 제공된 본문을 판단하며 검색 도구 루프나 스케줄러는 구현하지 않았다. 새 공식 원문 수집은 기존 무료 수집 정책을 따른다.

결과는 비공개 `live/runs/<request_id>/`에 입력·프롬프트·메타데이터·검증과 함께 저장된다. `validated_draft`도 `publication_approved=false`, `semantic_review=required`다. 주제 스냅샷은 KST 만료·마감을 걸러내며 실패 시 이전 카드의 유효 연결만 남기는 로컬 fallback이 있다. 실제 공개·일별 예약 실행에는 연결하지 않았다.

## 오류 처리

HTTP 실패·usage 불명·응답 캐시 손상은 자동 재시도하지 않는다. 실패 예약은 반환하지 않는다. `resume`은 운영자가 오류를 검토한 경우에만 쓰며 예약·호출 수·상한을 보존한다. 품질 실패를 반복 호출로 덮기 위해 사용하지 않는다.

`--retry-failed-once`는 검토한 HTTP400 요청의 명시적 단 한 번 재시도다. `--repair-from <request_id>`는 동일 입력의 첫 거절 초안에만 한 번 보정 의견을 제공한다. 둘 다 추가 요청과 비용을 차감하며 무한 반복·정답 주입을 허용하지 않는다. 이번 실험에서는 진단 재시도와 1회 보정을 이미 수행했고 품질 미통과를 기록했다.

프로젝트 기본 무료 정책은 유지하며 이 사용자 승인 Claude 일회 예외 외의 API·인프라 지출은 허용하지 않는다. 공개·배포·main 병합은 별도다.

## 추가 과금 없는 품질 보강 — 2026-11-05

[보강 결과와 한계](evaluations/claude-quality-2026-11-05/README.md). 당시 `run --kind research`는 추출v2를 요청했고, 현재 후속 요청은 [추출 v3](research-extraction.md)를 요청한다. Python이 v1 내부 계약으로 조립한다. 호스트의 `output_schema_version=research-draft-v1`은 조립 결과 계약이므로 유지한다. 모델 응답은 `model-output.json`, 조립 결과는 `result.json` 또는 `rejected-result.json`에 구분해 저장한다.

주제 입력의 각 approved_item에는 호스트가 작성한 `topic_basis`가 필요하다. `topic_ids`, `title_facets`, `evidence_claim_ids`를 제공하며 모델이 작성한 reason을 근거로 대신 쓰지 않는다. 근거가 없으면 API 요청 전에 중단한다. title_facets는 family/weekend/free이며 모든 연결 항목에서 확인돼야 한다. ‘이번 주말’ 같은 상대 날짜와 사전에 없는 자유 제목은 추가 검토로 남긴다. 무료라는 제목의 근거가 없다고 유료 혜택 자체를 배제하지 않는다.

```sh
python3 -m benefit_monitor.replay_quality \
  --basis docs/ai/evaluations/claude-quality-2026-11-05/topic-basis.json \
  --output .tools/claude-trial/quality-replay-new.json
```

이 재생 명령은 키·네트워크 없이 기존 원장 응답 해시와 입력 해시를 검사하고 원래 v1 응답을 재검증한다. 원본 파일을 덮어쓰지 않으며 output은 아직 없는 새 경로여야 한다. Git 제외 원본 `.tools/claude-trial/live`가 없는 환경에서는 실제 재생을 수행할 수 없다. 편집 근거표는 기존 사용자 승인 사실에서 Codex가 작성한 개발용 규칙이며 새 사람 승인은 대기 중이다. 통과하더라도 공개 승인으로 쓰지 않는다.

## 추출v2 실제 재실험

사용자의 후속 실행 지시로1회 추가 호출했다. 형식은 통과했으나 상세의 가족 조건을 누락해 중요 오류로 중단했다. 나머지6회와 운영 연결은 미실행이다. [사전등록·결과·비용](evaluations/claude-v2-trial-2026-11-05/README.md).

## v3 표준 필드·누락 검사

새 조사 요청은 표준 field명과12개 필수 확인 항목을 요구한다. 자격·이용/접수 기간을 구조화하고 원문에서 감지한 제한 문구의 인용·값 보존을 검사한다. v2를 자동 이름 변환하거나 성공 결과로 고치지 않는다. [보강 결과](evaluations/claude-v3-guard-2026-11-05/README.md).

```sh
python3 -m benefit_monitor.replay_research_guard \
  --request-id 6c565a36701ff00a00ea43a629eb41f136261117430c34681aab81e2481c9f55 \
  --output .tools/claude-trial/v3-coverage-replay-new.json
```

이 명령은 기존 입력·응답 해시를 확인하고 원래 계약 결과와 새 누락 검사를 구분한다. 키·네트워크·API를 사용하지 않으며 output은 새 프로젝트 내부 경로여야 한다. 저장 원본이 없으면 재생할 수 없다. v3의 실제 API 호출은 이번 보강에 포함하지 않았다.
