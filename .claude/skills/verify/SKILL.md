---
name: verify
description: >-
  benefit-monitor 변경을 실제로 실행해서 확인하는 방법. PR 전 로컬 화면(빌드 + 시스템 Chrome E2E), 머지·배포 뒤
  라이브 데이터(briefing.json 점검), 수동 재배포 전후 비교. "확인해봐", "배포 확인", "반영해", "재배포",
  "라이브 확인", "e2e 돌려" 이나 ax:ship 이 배포 뒤 확인을 찾을 때 사용.
---

# verify — benefit-monitor

통과 보고는 아래 명령을 **실제로 실행한 결과**로만 한다. 워크플로가 초록색이라고 배포가 맞는 것은 아니다 —
2026-11 수동 재배포가 약 7분간 `collection_failed`(혜택 0건)를 공개한 적이 있다.

## 1. PR 전 — 로컬 (변경이 화면·데이터 조립에 닿을 때)

```bash
python3 -m unittest discover -s tests          # 로직
cd frontend && npm run build \
  && BENEFIT_TEST_BROWSER_CHANNEL=chrome BENEFIT_SCREENSHOT_DIR="$PWD/../.tools/verify-shots" \
     npx playwright test                       # 시스템 Chrome. `npx playwright install` 하지 않는다
git status --short                             # 검증만 했는데 추적 파일이 바뀌었으면 그것도 보고한다
```

- `BENEFIT_SCREENSHOT_DIR` 를 빼면 E2E 가 추적 중인 `docs/qa/screenshots/` 를 다시 쓴다. 문서용 스크린샷을
  일부러 갱신할 때만 뺀다.

- 기준(2026-11-19 main): E2E 95개 통과, 약 35초. 리뷰 수정을 반영한 뒤에도 이 단계를 다시 돌린다 —
  리뷰 수정이 장보기 섹션 렌더를 깨뜨렸는데 단위 테스트는 통과했던 적이 있다.
- worktree 에서 `npm ci` 가 네트워크로 실패하면, `package-lock.json` 이 같은지 `cmp` 로 확인한 뒤 다른 체크아웃의
  `frontend/node_modules` 를 심볼릭 링크로 연결한다(링크는 커밋하지 않는다).

## 2. 배포 사실 (먼저 알아 둘 것)

- **main 머지는 Pages 배포가 아니다.** push 때는 테스트만 돈다. 정기 배포는 매일 `briefing-pages.yml`
  스케줄(00:37 KST)이다.
- 즉시 반영 = 입력 없는 수집 실행: `gh workflow run briefing-pages.yml --ref main` (무료 경로, 약 7분).
  수집 실행은 직전 AI 실행의 탭 추천·AI 장보기 추천을 복원한다(2026-11-11 `a3be599` 이후). 그러니 재배포 뒤
  추천이 사라졌다면 회귀다. 예외: 장보기 조사일(`groceries.*.survey_date`)이 바뀌어 AI 장보기 추천이 의도대로
  숨겨진 경우.
- **쓰지 않는다:** `deploy_approved_snapshot=true`. 스냅샷이 몇 시간 지나면 `snapshot is stale` 로 실패하고,
  워크플로가 설계대로 `collection_failed` 를 **공개 배포**한다.

## 3. 배포 전후 — 라이브 데이터

```bash
python3 -m benefit_monitor.live_check --save "$TMPDIR/before.json"     # 배포 전: 지금 공개본 보관 + 점검
gh workflow run briefing-pages.yml --ref main                          # (재배포가 필요할 때만)
gh run list --workflow briefing-pages.yml --limit 1 --json databaseId,createdAt,event   # 10초쯤 뒤: createdAt 이 방금인지 확인
gh run watch <databaseId> --exit-status                                # 바로 위에서 확인한 run 만 감시
python3 -m benefit_monitor.live_check --before "$TMPDIR/before.json"   # 배포 후: 공개본 점검 + 전후 비교
```

- `live_check` 가 실패로 보는 것: `collection_failed`, 혜택 0건, 갱신 36시간 초과, 장보기 가격 비어 있음,
  **배포 전에 보이던 AI 추천(festival·benefit·subscription·grocery)이 사라짐.** 경고: 혜택 수 감소, 비어 있는
  추천, `ai_status` 이상, 3회 이상 연속 실패한 출처.
- 결과물 품질(조사일 신선도·AI 추천 지금 기준 재검사·주제 카드·축제 후보)은 `git fetch --depth 60 origin briefing-data` 뒤 `python3 -m benefit_monitor.quality_report --git-ref origin/briefing-data`로 본다. 정기로는 `Quality report` 워크플로가 수집 뒤와 매일 07:23 KST에 돈다.
- Pages CDN 이 몇 분 늦을 수 있다. 실패면 2~3분 간격으로 최대 3번 다시 읽고, 그래도 실패면 멈추고 보고한다.
  다시 읽기 전에 결과 데이터를 고치거나 재배포를 반복하지 않는다.
- 보고에는 `live_check` 출력의 `status · 혜택 N건 · 갱신 시각 · AI 추천 표시` 줄을 그대로 붙인다.
- 화면까지 봐야 하면(새 탭·카드 UI) Chrome 확장으로 https://kim-taesu.github.io/benefit-monitor/ 를 연다.
  확장이 연결되지 않았으면 코드를 비교하고 끝내지 말고, 위 `live_check` 결과와 "화면 미확인" 을 함께 보고한다.

## 4. 실패했을 때

- 배포 뒤 실패: 원인 후보를 증거(워크플로 로그 줄, `live_check` 출력)와 함께 보고하고, 되돌리는 방법을 제안한다.
  보통은 원인 커밋을 revert 하고 수집 실행을 한 번 더 한다. 승인 스냅샷 재배포로 되돌리지 않는다.
- 같은 검사가 고친 뒤에도 3번 실패하면 멈추고 사용자에게 넘긴다.
