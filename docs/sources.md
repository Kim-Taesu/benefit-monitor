# 출처 정의 관리 — 2026-11-06

출처 하나는 `sources/<id>.json` 파일 하나다. 수집 설정(`collect`)과 유지보수 안내(`runbook`)를 함께 둔다. 형식은 [schema/source.schema.json](../schema/source.schema.json)이 정한다.

운영 코드가 읽는 `sources.yaml`은 생성물이다. 직접 고치지 않는다.

```sh
python3 -m benefit_monitor.source_registry check        # 모든 정의를 스키마로 검사
python3 -m benefit_monitor.source_registry show <id>    # 출처 하나의 정의·runbook
python3 -m benefit_monitor.source_registry probe <id>   # 실제 수집해 후보 제목 확인(공식 HTTP, 기본 10회 한도)
python3 scripts/generate_sources.py                     # sources.yaml 다시 만들기
```

`python -m unittest`가 `sources.yaml`이 정의와 다르면 실패한다.

## 파일 구성

| 칸 | 뜻 |
|---|---|
| `status` | `active` 운영 수집, `excluded` 정책상 수집 안 함, `deferred` 아직 연결 안 함 |
| `reason` | excluded·deferred의 판정 이유. 같은 조사를 반복하지 않게 남긴다 |
| `collect` | 예전 `sources.yaml` 항목에서 id·name을 뺀 것. 오타 키는 거절된다 |
| `runbook.checked_at` | 접근 정보를 실제로 확인한 마지막 날(KST). 확인 없이 바꾸지 않는다 |
| `runbook.access` | robots, 화면 방식(서버 HTML·RSS·XML·검색 POST·자바스크립트 전용), 상세 접근(GET·POST 전용), 조건 위치(글·이미지) |
| `runbook.extraction` | 목록에서 제목·주소·기간을 읽는 방법 |
| `runbook.pitfalls` | 알려진 함정과 일부러 하지 않는 것 |
| `runbook.manual_check`, `on_failure` | 사람이 확인하는 방법과 실패 때 할 일 |
| `runbook.code` | 관련 코드 경로. 테스트가 존재를 확인한다 |
| `runbook.history` | 날짜별 변경 기록 |

모르는 값은 `unknown`으로 둔다. 추측으로 채우지 않는다.

## 출처 추가·변경

1. `sources/<id>.json`을 만든다. 가장 비슷한 출처 파일을 복사해 시작한다.
2. 운영 수집이면 `sources/_config.json`의 `source_order`에 id를 넣는다. 순서가 생성물 순서다.
3. `python3 -m benefit_monitor.source_registry probe <id>`로 실제 후보를 본다.
4. `python3 scripts/generate_sources.py`와 `python3 scripts/generate_source_policy.py`를 실행하고 테스트를 돌린다.

제외할 때는 `status`를 `excluded`로 바꾸고 `collect`를 지우고 `reason`을 쓴다. 파일은 지우지 않는다.

## 일일 출처 상태 검사

`Source health` workflow는 공개 브리핑 수집이 끝날 때마다 실행됩니다(`workflow_run`, push 실행은 제외). `briefing-data` 브랜치의 `briefing.json`에서 출처별 상태를 읽고, 출처 정의의 `monitoring.expect`와 비교합니다. 수동 실행도 됩니다.

| expect | 이번 수집에서 실패하면 | 이번 수집에서 성공하면 |
|---|---|---|
| `working` | **CI 실패** | 통과 |
| `known_failing` | 통과(표에 남음) | 경고: 복구됐으니 `working`으로 바꾸라는 안내 |
| `manual` | 통과 | 자동 수집기가 없는데 상태가 바뀌면 경고 |

이런 경우에도 CI가 실패합니다.
- 보고에 `working` 출처가 없음
- 서울 구 목록 중 하나라도 수집 실패
- 공개 상태가 `collection_failed`
- 보고 시각이 이번 수집 시작보다 이르거나 30시간보다 오래됨

`known_failing`·`manual`에는 `since`와 `reason`이 필요합니다. 이 검사는 브리핑 실행과 분리되어 있어, 출처가 실패해도 공개 배포와 AI 일일 실행은 막지 않습니다. 오래된 승인 snapshot을 다시 배포한 수동 실행 뒤에는 보고 시각 검사로 실패할 수 있습니다.

```sh
python3 -m benefit_monitor.source_check --briefing <briefing.json>
```
