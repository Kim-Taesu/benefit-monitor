# 매일 정시 시작 (Cloudflare Workers Cron)

GitHub `schedule`은 매일 4~8시간 늦게 시작한다(00:37 cron, 2026-11-08~20 실제 시작 04:33~08:50 KST). `workflow_dispatch`는 바로 시작하므로, Cloudflare Workers 무료 플랜의 cron이 정해진 시각에 실행을 요청한다. 2026-11-20 사용자 승인([정책 대응표](../../docs/ai/policy-map.md)).

## 하는 일

- 03:00~04:50 KST, 10분마다 깨어난다(cron 1개). 03:20 전에는 아무것도 하지 않는다.
- 차례: 보건소(`health-notices.yml`) → 청약(`subscriptions.yml`) → 혜택 수집(`briefing-pages.yml`, 실행 이름 `수집`). 한 번에 하나만 요청한다.
- 세 워크플로가 같은 동시 실행 그룹이라, 하나라도 대기·실행 중이면 그 회차는 건너뛴다(대기 중인 실행이 취소되지 않게).
- 오늘 이미 성공했으면 넘어가고, 실패하면 하루 한 번 더 요청한다.
- 혜택 수집이 끝나면 AI 실행 → 승인 스냅샷 게시가 이어진다(약 20분). 정상이면 04:10 전후에 공개된다.
- GitHub 정기 실행은 백업으로 남는다. 그날 이미 성공했으면 수집 없이 끝난다.

판단 로직은 `src/plan.js`(순수 함수), 테스트는 `npm test`(`node --test`).

## 처음 설정 (사용자가 직접)

1. GitHub에서 fine-grained 토큰 만들기: Settings → Developer settings → Fine-grained tokens
   - Repository access: `Kim-Taesu/benefit-monitor` 하나만
   - Permissions: **Actions: Read and write** (Metadata: Read는 자동)
   - 만료일을 정하고, 만료 전에 다시 만들어 3번을 반복한다.
2. Cloudflare 로그인: `npx --yes wrangler@4.156.0 login` (무료 계정, 결제 정보 없음)
3. 이 폴더에서 토큰 넣기: `npx --yes wrangler@4.156.0 secret put GITHUB_TOKEN` → 토큰 붙여넣기
   - 처음에는 Worker가 없다는 안내가 나오면 4번을 먼저 하고 다시 한다.
4. 배포: `npm run deploy`

## 확인

- 실행 기록: `npx --yes wrangler@4.156.0 tail` 을 03:20~04:50 사이에 켜 두면 회차마다 `{"action":"dispatch"...}` 한 줄이 보인다.
- GitHub: Actions에서 03:20 이후 `Health notices` → `Subscriptions` → `수집` 순으로 `workflow_dispatch` 실행이 생긴다.
- 화면: 홈 위쪽 "오늘 데이터 준비 …" 줄에 크롤링·AI 생각·게시 시간이 나온다.

## 멈추기

Cloudflare 대시보드에서 Worker의 Triggers → cron 삭제, 또는 `npx --yes wrangler@4.156.0 delete`. GitHub 정기 실행(백업)은 그대로 돈다.
