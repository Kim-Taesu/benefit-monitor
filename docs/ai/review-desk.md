# 사람 검토 도구 — Phase 2, 2026-11-05

AI 조사 초안을 공식 원문과 나란히 보고, 사람이 승인한 것만 공개 검증 목록에 넣는 로컬 도구다. 키를 읽지 않고, 모델과 공식 사이트에 요청하지 않는다.

## 준비

클라우드가 실행 주체이면 검토 대기 자료는 암호화 상태 저장소에 있다. 먼저 로컬로 복원한다. 복원은 로컬 일일 실행을 다시 켜지 않는다.

```sh
python3 scripts/ai_cloud_handoff.py restore
```

이 스크립트는 `check`(원격 control 검증)와 `restore`(로컬 복원)만 쓴다. Mac→클라우드 전환용 `prepare`·`activate`는 2026-11-05 전환이 끝났고 2026-11-07 원장 개정(월 상한·만료 없음) 뒤로는 실행하면 안 되므로 은퇴했다. 실행하면 안내 문구와 함께 종료값 2로 멈추고 아무것도 읽거나 쓰지 않는다.

## 순서

```sh
python3 -m benefit_monitor.review_desk list
python3 -m benefit_monitor.review_desk show <ID 앞부분>
python3 -m benefit_monitor.review_desk page <ID 앞부분>
python3 -m benefit_monitor.review_desk prepare <ID 앞부분>
python3 -m benefit_monitor.review_desk approve <ID 앞부분> --confirm-reviewed
python3 -m benefit_monitor.review_desk reject <ID 앞부분> --reason "거절 이유"
```

1. `list`는 사람 결정이 없는 대기 항목과 대기 일수를 보여 준다.
2. `show`는 필드별 값, 미확인 사유, 근거 문장과 그 앞뒤 원문을 터미널에 보여 준다. 검사에서 거절된 초안도 볼 수 있다.
3. `page`는 왼쪽에 AI가 뽑은 조건, 오른쪽에 공식 원문 전체를 놓고 근거 문장을 강조한 HTML을 만든다. 출력된 경로를 브라우저로 연다.
4. `prepare`는 공개 형식의 초안 파일을 만든다. `verified_at`은 비어 있고 `public_release`는 false다. 미확인 조건은 conditions 끝에 "미확인:"으로 붙는다. 이 파일을 원문과 대조해 직접 고친다.
5. `approve --confirm-reviewed`는 사람이 원문을 확인했다는 선언이다. 이때만 `verified_at`이 현재 시각으로, `public_release`가 true로 바뀐다. 기존 공개 검사를 그대로 통과해야 `public/verified.json`에 추가된다. 출처·URL 불일치, 개인정보 패턴, 중복 항목은 파일을 바꾸지 않고 거부한다.
6. 승인 뒤 `git diff public/verified.json`을 확인하고 커밋한다. 화면 반영은 main 병합 뒤 정기 배포에서 일어난다.

## 후속 관리

```sh
python3 -m benefit_monitor.review_desk expiring --days 7
python3 -m benefit_monitor.review_desk stats
```

- `expiring`은 공개 항목 중 검증 유효기간 14일, 종료일, 마감 시각 가운데 가장 이른 것이 기간 안에 드는 항목을 보여 준다. 재확인 항목은 원문을 다시 보고 `verified_at`을 갱신해야 계속 표시된다.
- `stats`는 결정 수, 검토 시간 중앙값, 하루 넘게 결정되지 않은 대기 수를 Phase 2 목표와 함께 보여 준다.

## 기록 위치와 한계

- 결정 기록, 초안, HTML은 Git 제외 폴더 `.tools/review-desk`에 있다. 클라우드 상태 묶음에 들어가지 않으므로 복원 때 덮어쓰이지 않는다.
- 클라우드 쪽 대기 파일의 상태 값은 바꾸지 않는다. 결정 여부는 로컬 결정 기록으로 판단한다. 다른 컴퓨터에서 검토하면 결정 기록을 따로 옮겨야 한다.
- 검토 시간은 처음 `show`, `page`, `prepare` 중 하나를 실행한 시각부터 결정까지다. 도구 밖에서 원문을 읽은 시간은 포함하지 않는다.
- 이 도구는 사람의 판단을 대신하지 않는다. 검사 통과 초안도 원문과 다를 수 있다.
