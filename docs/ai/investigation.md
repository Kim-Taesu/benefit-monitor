# 제한된 공식 문서 추가 조사

## 사용 사례와 실행 범위

나들이·축제·전시·공연·문화·체험·공원 문구가 있는 혜택 후보의 이용 기간, 대상, 비용, 신청 방법을 보충한다. 제목/요약 단어는 조사할 후보를 고르는 힌트이며 프로그램 적합성이나 신청 자격의 판정이 아니다. 개인 프로필과 Phase 2 행동 기록은 전송하지 않는다.

기존 일반 조사 경로는 유지한다. 추가 조사는 사용자 승인에 따라 `AI daily trial`의 정기·브리핑 완료 연동 실행에서 기본 활성화된다. 수동 `workflow_dispatch`에서는 기본 선택된 `investigate_missing_conditions`를 해제해 해당 실행만 끌 수 있다. 클라우드 실행이 작성하는 `ai-automation.json`의 같은 이름 정책이 `ai_daily → cli → ai_review`로 전달된다. 새 유료 kind, 모델, 외부 검색 서비스는 없다.

## 루프와 책임

1. 호스트가 후보의 공식 본문을 읽고, 실제 발견한 링크 중 기존 출처에 등록되고 AI 읽기가 허용된 HTML 경로를 최대 12개 제시한다. 임의 URL은 모델의 도구가 아니다.
2. 기존 research facts를 추출하고 `next_step`에 부족한 필드와 `link_id` 하나 또는 stop을 반환한다. 확장 스키마와 지침은 이 모드에만 붙인다.
3. 호스트가 링크 ID·누락 필드·출처·남은 한도를 검사한다. OfficialReader의 robots, TLS, 리다이렉트 차단, 6시간 캐시, 실패 대기, 전역 HTTP 예산을 그대로 사용한다.
4. 새 문서를 읽었을 때만 누적 근거를 다시 추출한다. 동일 본문이면 `no_new_evidence`로 멈춘다. 이전 모델의 추측을 새로운 근거로 넣지 않는다.
5. 충분한 근거로 끝났더라도 기존 `auto_publish` 게이트를 통과해야 공개한다. 미확인·충돌·거절·실패·한도 종료는 조사 결과를 비공개로 보존하고 공개 보류한다.

목표 필드가 모두 supported여도 모델이 충돌 종료를 명시하면 충분한 근거로 덮어쓰지 않는다. supported는 실제 입력의 segment ID와 기존 근거 검사를 통과해야 하지만, 의미상 사실 정확성을 완전히 보장하지 않는다.

## 한도와 재실행

- 후보당 최대 3회 runner 호출, 총 4문서, 공식 HTTP 12회. robots와 기존 허용 재시도도 HTTP 상한에 포함한다. 전체 실행의 기존 HTTP 상한도 동시에 적용한다.
- 각 추가 호출은 기존 `max_ai_candidates_per_day`의 남은 수에서 차감한다. 하루 조사 최대 40회, 기존 월 $15 원장 예약·복구·암호화·동시 실행 경계를 변경하지 않는다. 집계된 model_calls는 runner 시도 수이며 실제 유료 청구 수는 원장에서 확인한다.
- 모델 거절이나 도구/공급자 실패를 루프에서 재시도하지 않는다. 추가 조사에서 거절된 같은 근거를 익일 자동 재호출하지 않는다. 본문이 바뀌면 새 입력으로 조사할 수 있다.
- 다음 추가 조사 실행은 앞서 읽은 문서 URL도 다시 확인한다. 내용이 같으면 저장된 결과를 재사용한다. 중간 `credit_exhausted` 시 추가 문서와 종료 상태를 저장하므로 다음 추가 조사 실행이 최초 한 문서 추출부터 반복하지 않는다.
- 프로세스가 강제 종료된 경우의 임의 중간 재개를 약속하지 않는다. 기존 일일 attempted/failed 상태와 원장 미정산 복구 규칙을 따른다. 원장·일일 상태를 지워 다시 실행하지 않는다.

기존 기본 조사 fingerprint 대상 파일은 수정하지 않았다. 추가 조사에는 별도 계약·프롬프트 해시를 합친다. 계측 코드만 바뀐다고 새 조사 fingerprint를 만들지 않는다.

## 비공개 산출물과 해석

- `.tools/ai-inputs/investigation-<sha256>.json`: 차수별 실제 호스트 입력. 이미 있는 파일의 내용이 다르면 중단한다.
- 기존 `.tools/claude-trial/live/runs/<id>`: 원본 모델 출력, 정규화 결과, 검증·비용 연결 메타데이터.
- `cache/ai_review/investigations/<sha256>.json`: 단계별 호출 ID, 입력/문서 해시, 미확인 필드, 요청 링크 ID, 종료 상태와 새 출처 후보.
- `followup_supported_fields`: 첫 추출 이후 추가 문서를 근거로 supported로 바뀌어 마지막까지 유지된 목표 필드. 실제 사용자 가치나 모델 정확도 점수가 아니다.
- `http_budget_used`: 해당 후보의 초기 읽기·재확인을 포함한 지역 예산 사용량. `additional_http_requests`는 루프 진입 후 전역 HTTP 예산 증가량이다.

새 도메인은 위 비공개 보고서의 `source_candidates`에만 남는다. 출처 등록 파일이나 허용목록을 자동으로 고치지 않는다. 저장 경로는 기존 암호화 runtime 아카이브 범위에 포함되며 공개 JSON에는 넣지 않는다.

종료 상태는 sufficient_evidence, insufficient_evidence, no_relevant_links, no_new_evidence, unsupported_document, access_blocked, unresolved_conflict, budget_exhausted, model_failed, invalid_model_output, invalid_document, awaiting_api_authorization로 구분한다. 마지막 상태는 입력 준비만 했다는 뜻이다.

## 운영 전 확인

이 변경은 배포하거나 유료 실행하지 않았다. 반영 후 기존 main 전용 workflow와 복원된 공유 원장을 통해 실행해야 한다. 다른 worktree에 원장을 복제해 테스트하지 않는다.

1. `check_only=true`는 기존 복원·Secret·원격 제어만 확인하며 추가 조사도 호출하지 않는다.
2. 확장 스키마의 공급자 문법 시험이 필요하면 `grammar_probe_only=true`와 `investigate_missing_conditions=true`를 함께 선택한다. 기존 유료 grammar probe 경로와 원장을 사용하며 실제 실행 전 모델 호출 비용이 있다는 점을 확인한다.
3. 실제 추가 조사는 정기·연동 실행과 `check_only=false`, `investigate_missing_conditions=true`인 수동 실행에서 사용한다. 당일 이미 완료/시도한 실행을 우회하지 않는다. 수동으로 끄더라도 이후 자동 실행의 기본값은 켜짐이다.
4. 종료 사유·추가 문서가 보충한 필드·원장 비용·사용자가 다시 검색해야 했던 질문을 함께 비교한다. 호출 수 증가만으로 성공이라 평가하지 않는다.

## 이번 검증

합성 조사 테스트는 링크 위조, 프롬프트 삽입, 새 도메인, 접근 차단, 첨부, 충돌, HTTP/모델 한도, 동일 본문, 실제 조각 근거 보충, 재실행과 비용 중단을 다룬다. 클라우드/일일 테스트는 기본 활성화·명시적 비활성화 전달과 기존 한도 보존을 확인한다.

공식 페이지 읽기 smoke는 기존 공개 목록의 서울시 문서 1개로 시도했다. HTTP 2회 후 URLError로 끝났고 유료 호출은 0회다. TLS나 접근 제한을 우회하지 않았다. 온라인 원문 수집 성공·현재 모델의 링크 선택 능력·실제 재검색 감소는 미검증이다.
