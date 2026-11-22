# 실행 구조

매일 새벽 어떤 순서로 무엇이 실행되어 화면에 도착하는지 정리한 문서입니다. 2026-11-20 `main`(PR #74 머지 후) 기준이며, 정책·한도의 원문은 [작업 지침](../AGENTS.md)과 [정책 대응표](ai/policy-map.md)가 우선합니다.

![매일 새벽 갱신 흐름 애니메이션](architecture/daily-pipeline.gif)

> 그림의 시각은 2026-11-20 실제 실행 소요 시간(보건소 약 2.5분, 청약 약 6.5분, 혜택 수집 약 8분, AI 약 12분, 게시 약 1분)으로 계산한 **예상치**입니다. Cloudflare cron으로 시작하는 첫 실행은 2026-11-21입니다.

## 목차

1. [한눈에 보기](#1-한눈에-보기)
2. [하루 타임라인](#2-하루-타임라인)
3. [무엇이 무엇을 깨우나](#3-무엇이-무엇을-깨우나)
4. [Cloudflare cron의 판단](#4-cloudflare-cron의-판단)
5. [워크플로 한 장 요약](#5-워크플로-한-장-요약)
6. [`briefing-pages.yml`의 네 가지 모드](#6-briefing-pagesyml의-네-가지-모드)
7. [AI 실행 안쪽](#7-ai-실행-안쪽)
8. [혜택 공개 판단](#8-혜택-공개-판단)
9. [데이터 저장소 `briefing-data`](#9-데이터-저장소-briefing-data)
10. [화면이 데이터를 읽는 방식](#10-화면이-데이터를-읽는-방식)
11. [안전장치](#11-안전장치)
12. [수동 실행 입력](#12-수동-실행-입력)
13. [확인하는 방법](#13-확인하는-방법)
14. [이 문서의 그림 갱신](#14-이-문서의-그림-갱신)

---

## 1. 한눈에 보기

```mermaid
flowchart TB
  cron["⏰ Cloudflare cron · 03:20~04:50 KST, 10분마다"]:::cf
  src[("🌐 공식 출처 · 익명 HTTPS · 실거래 API")]

  subgraph GHA["⚙️ GitHub Actions (공개 저장소 무료 러너)"]
    direction LR
    health["health-notices.yml<br/>보건소 공지"] ~~~ subs["subscriptions.yml<br/>청약 일정·실거래"] ~~~ brief["briefing-pages.yml<br/>run-name: 수집"]
    brief -->|"④ workflow_run"| ai["ai-daily.yml<br/>AI 검증·추천"]:::ai
    ai -->|"⑥ dispatch"| deploy["briefing-pages.yml<br/>run-name: 승인 스냅샷 게시"]
  end

  claude[("🤖 Claude API · Haiku 5.5 · 월 $30 원장")]:::ai

  subgraph OUT["저장 · 공개"]
    direction LR
    data[("🗄️ briefing-data 브랜치<br/>briefing.json · 탭별 JSON · 암호화 AI 상태")]:::data
    pages["🖥️ GitHub Pages<br/>Vue 정적 화면"]:::data --> user["📱 사용자 브라우저"]
  end

  cron -->|"① dispatch"| health
  cron -->|"② dispatch"| subs
  cron -->|"③ dispatch"| brief
  src --> GHA
  ai <-->|"요청마다 비용 예약"| claude
  GHA -->|"수집 결과 · ⑤ 스냅샷 커밋"| data
  deploy -->|"⑦ 고정 커밋 재검증 후 deploy"| pages

  classDef cf fill:#fff4e6,stroke:#f38020
  classDef ai fill:#f3f0ff,stroke:#8250df
  classDef data fill:#eefbf1,stroke:#1a7f37
```

| 층 | 무엇 | 돈 |
| --- | --- | --- |
| 예약 | Cloudflare Workers 무료 cron 1개(`scheduler/cloudflare`) — 워크플로 실행 요청만 함 | 무료 플랜, 결제 정보 없음 |
| 실행 | GitHub Actions 표준 러너 | 공개 저장소 무료 |
| 수집 | Python 표준 라이브러리, 공식 익명 HTTPS | 0 |
| AI | 승인된 Claude 호출만, Haiku 5.5 고정 | 월 $30 원장 상한(2026-11-20 상향, 사용자가 직접 충전) |
| 저장 | 같은 저장소의 `briefing-data` 브랜치 | 0 |
| 공개 | GitHub Pages | 0 |

---

## 2. 하루 타임라인

GitHub `schedule`은 2026-11-08~20 동안 매일 4~8시간 늦게 시작했습니다. 그래서 정시 시작은 Cloudflare cron이 맡고, GitHub 예약은 백업으로만 남았습니다.

```mermaid
gantt
  title 2026-11-20 실제(GitHub 예약) vs 2026-11-21부터 목표(Cloudflare cron)
  dateFormat HH:mm
  axisFormat %H:%M

  section 목표 · Cloudflare
  보건소 · 03시20분 회차       :c1, 03:20, 3m
  청약 · 03시30분 회차         :c2, 03:30, 7m
  혜택 수집 · 03시40분 회차    :c3, 03:40, 8m
  AI 검증·추천                 :c4, after c3, 12m
  승인 스냅샷 게시             :c5, after c4, 2m
  05시 마감                    :milestone, m1, 05:00, 0m

  section 11-20 실제 · GitHub 예약
  예약 시각 00시07~37분         :crit, g0, 00:07, 30m
  늦은 시작 대기                :done, g1, 00:37, 421m
  보건소                       :g2, 07:38, 3m
  청약                         :g3, 07:39, 7m
  혜택 수집                    :g4, 07:44, 8m
  AI 검증·추천                 :g5, 07:52, 12m
  승인 스냅샷 게시             :g6, 08:04, 2m
```

| 작업 | 정시 시작(주) | 백업 | 그날 이미 성공했으면 |
| --- | --- | --- | --- |
| 보건소 `health-notices.yml` | Cloudflare 03:20~ | GitHub 00:07 KST | 게이트에서 수집 없이 종료 |
| 청약 `subscriptions.yml` | Cloudflare (보건소 다음 회차) | GitHub 00:12 KST | 게이트에서 수집 없이 종료 |
| 혜택 수집 `briefing-pages.yml` | Cloudflare (청약 다음 회차) | GitHub 00:37 KST | 게이트에서 수집 없이 종료 |
| AI `ai-daily.yml` | 혜택 수집 성공 직후 `workflow_run` | 06:00~23:45 KST 15분마다 | `already_completed_today`로 종료 |
| 장보기 기준가 `grocery-baselines.yml` | GitHub 매주 일요일 23:07 KST | — | — |

> 게이트는 [`pipeline_timing.gate`](../benefit_monitor/pipeline_timing.py)입니다. 예약 실행(GitHub cron 또는 `external_schedule=true`)만 건너뛰며, 실행 목록을 못 읽으면 그냥 실행합니다(“두 번이 안 하는 것보다 낫다”). 사람이 누른 수동 실행은 게이트를 거치지 않습니다.

---

## 3. 무엇이 무엇을 깨우나

```mermaid
flowchart TB
  CF(["⏰ Cloudflare cron"]):::cf
  GS(["🕛 GitHub schedule<br/>(백업)"]):::gh
  ME(["🧑 사람<br/>workflow_dispatch"]):::me
  PUSH(["main push"]):::gh
  PR(["pull_request"]):::gh

  H["health-notices.yml"]
  S["subscriptions.yml"]
  B1["briefing-pages.yml<br/>run-name: 수집"]
  A["ai-daily.yml"]
  B2["briefing-pages.yml<br/>run-name: 승인 스냅샷 게시"]
  B3["briefing-pages.yml<br/>run-name: main 반영 검사"]
  SH["source-health.yml"]
  F["frontend-checks.yml"]

  CF -->|"external_schedule=true"| H
  CF --> S
  CF --> B1
  GS --> H & S & B1 & A
  ME --> H & S & B1 & A
  B1 -->|"workflow_run (success)"| A
  B1 -->|workflow_run| SH
  A -->|"dispatch: deploy_approved_snapshot<br/>+ snapshot_commit + expected_code_sha"| B2
  A -.->|"10시 이후에도 오늘 수집이 없으면<br/>dispatch (수집)"| B1
  PUSH --> B3
  PR --> F

  classDef cf fill:#fff4e6,stroke:#f38020
  classDef gh fill:#eef4ff,stroke:#2f6feb
  classDef me fill:#f3f0ff,stroke:#8250df
```

- `ai-daily.yml`은 “오늘 끝난 무료 수집”이 있어야만 유료 작업을 시작합니다. 시계로 막지 않고 수집 완료로 막습니다([`cloud_daily.cloud_run`](../benefit_monitor/cloud_daily.py)).
- 백업 예약으로 AI가 먼저 깨어나도 수집이 없으면 `waiting_for_existing_refresh`로 끝납니다. 10시(`FALLBACK_REFRESH_HOUR`) 이후에도 수집이 없을 때만 수집을 직접 요청합니다.
- `main 반영 검사`(push)는 테스트·빌드만 하고 배포하지 않습니다. 머지만으로는 화면이 바뀌지 않습니다.

---

## 4. Cloudflare cron의 판단

Worker는 10분마다 오늘의 세 워크플로 실행 목록을 읽고, 순수 함수 [`plan.js`](../scheduler/cloudflare/src/plan.js)가 할 일을 정합니다. 한 회차에 최대 하나만 요청합니다.

```mermaid
flowchart TD
  T(["10분마다 깨어남<br/>18:00~19:50 UTC"]) --> W{"03:20~04:50 KST<br/>사이인가?"}
  W -- 아니오 --> I1["idle"]
  W -- 예 --> Q{"오늘 세 워크플로 중<br/>대기·실행 중인 것이 있나?"}
  Q -- 예 --> WT["wait<br/>(같은 동시 실행 그룹이라<br/>대기 실행이 취소되지 않게)"]
  Q -- 아니오 --> L["순서대로 확인<br/>① 보건소 ② 청약 ③ 혜택 수집"]
  L --> OK{"오늘 성공했나?"}
  OK -- 예 --> NX["다음 워크플로"] --> OK
  OK -- 아니오 --> TR{"오늘 2번<br/>시도했나?"}
  TR -- 예 --> NX
  TR -- 아니오 --> D["dispatch<br/>external_schedule=true"]
  NX -- 셋 다 끝 --> I2["idle: today done"]
```

```mermaid
stateDiagram-v2
  direction LR
  state "보건소" as health
  state "청약" as subs
  state "혜택 수집" as collect
  state "오늘 끝" as done
  [*] --> health: 03시20분 회차
  health --> subs: 성공 또는 2회 실패
  subs --> collect: 성공 또는 2회 실패
  collect --> done: 성공 또는 2회 실패
  done --> [*]
```

- 혜택 수집 실행은 `run-name`이 `수집`인 것만 셉니다. 같은 파일의 `승인 스냅샷 게시`, `main 반영 검사`는 세지 않습니다.
- 세 워크플로가 `benefit-pages` 동시 실행 그룹을 공유합니다. GitHub는 그룹당 대기 실행을 하나만 두고 이전 대기 실행을 취소하므로, 무엇이든 돌고 있으면 그 회차는 건너뜁니다.
- 끄는 법·토큰 설정은 [`scheduler/cloudflare/README.md`](../scheduler/cloudflare/README.md)에 있습니다.

---

## 5. 워크플로 한 장 요약

| 파일 | 이름 | 트리거 | 동시 실행 그룹 | 주요 명령 | Secret |
| --- | --- | --- | --- | --- | --- |
| `health-notices.yml` | Health notices | Cloudflare · schedule · dispatch | `benefit-pages` | `python -m benefit_monitor.health_notices` | — |
| `subscriptions.yml` | Subscriptions | Cloudflare · schedule · dispatch | `benefit-pages` | `python -m benefit_monitor.subscriptions` | `REAL_ESTATE_TRANSACTION` |
| `briefing-pages.yml` | Daily benefit briefing | Cloudflare · schedule · dispatch · push | `benefit-pages` | `mirror --restore` → `cli --online` → `publish` → Pages 배포 | — |
| `ai-daily.yml` | AI daily trial | `workflow_run` · schedule · dispatch | `benefit-ai-daily` | `python scripts/run_ai_cloud.py` | `ANTHROPIC_API_KEY`, `BENEFIT_AI_STATE_IDENTITY` |
| `source-health.yml` | Source health | `workflow_run` · dispatch | — | `python -m benefit_monitor.source_check` | — |
| `grocery-baselines.yml` | Grocery baselines | 주간 schedule · dispatch | `benefit-pages` | `python -m benefit_monitor.grocery_baselines` | — |
| `frontend-checks.yml` | Frontend P0 checks | pull_request · dispatch | `frontend-p0-<ref>` | Python 회귀 · `plan.test.js` · `npm test/build` · E2E | — |

모든 실행 job은 `github.event.repository.private == false && vars.BENEFIT_PAGES_ZERO_SPEND == 'confirmed'` 조건이 붙어 있어 비공개 저장소(유료 분 사용 가능성)에서는 돌지 않습니다.

---

## 6. `briefing-pages.yml`의 네 가지 모드

같은 파일이 입력에 따라 다른 일을 합니다. `run-name`으로 구분합니다.

```mermaid
flowchart LR
  E{"이벤트 / 입력"} -->|push| P["main 반영 검사"]
  E -->|"deploy_approved_snapshot=true"| S["승인 스냅샷 게시"]
  E -->|"apply_takedowns=true"| T["내림 적용"]
  E -->|그 외| C["수집"]
```

| 단계 | 수집 | 승인 스냅샷 게시 | 내림 적용 | main 반영 검사 |
| --- | :-: | :-: | :-: | :-: |
| gate (오늘 이미 성공했으면 건너뜀) | 예약일 때만 | — | — | — |
| 요청한 코드 SHA와 checkout 일치 확인 | — | ✅ | — | — |
| 출처 정책·Python 테스트·프런트 테스트/빌드 | ✅ | ✅ | ✅ | ✅ |
| `mirror --restore` → `cli --online` → `publish` | ✅ | — | — | — |
| 수집 스냅샷 암호화 업로드(AI 실행이 재사용) | ✅ | — | — | — |
| AI 승인 목록 재확인 저장(`mirror --save-ai`) | ✅ | — | — | — |
| 고정 커밋 재검증 후 내보내기(`public_snapshot`) | — | ✅ | — | — |
| 공개 브리핑에서 내린 항목만 제거 | — | — | ✅ | — |
| 실패하면 이전 추천 대신 실패 상태 공개 | ✅ | ✅ | — | — |
| `briefing-data`에 공개 JSON 미러 | ✅ | — | — | — |
| `assemble_pages.py` → GitHub Pages 배포 | ✅ | ✅ | ✅ | — |

```mermaid
sequenceDiagram
  autonumber
  participant R as 러너 (수집)
  participant BD as briefing-data
  participant O as 공식 출처
  participant GP as GitHub Pages
  R->>BD: mirror --restore (공개 JSON·승인 목록·탭별 JSON, sha 임대 기록)
  R->>R: publish --prepare-import
  R->>O: cli --online ① 출처 수집 ② 남은 예산으로 자동 공개 항목 원문 재확인 (요청 예산 95/100, robots·TLS·허용 호스트)
  R->>R: publish → delivery/public/briefing.json
  R->>BD: collection_snapshot --upload (age 암호화)
  R->>BD: mirror --save-ai (재확인 시각·철회만)
  R->>BD: mirror (briefing.json 1차 공개)
  R->>GP: assemble_pages → deploy-pages
  Note over R,GP: 수집이 실패해도 경고 상태를 먼저 배포한 뒤 run을 실패로 끝냄
```

---

## 7. AI 실행 안쪽

`ai-daily.yml` → [`scripts/run_ai_cloud.py`](../scripts/run_ai_cloud.py) → [`cloud_daily.cloud_run`](../benefit_monitor/cloud_daily.py) → [`ai_daily.daily`](../benefit_monitor/ai_daily.py) 순서입니다.

```mermaid
sequenceDiagram
  autonumber
  participant W as ai-daily.yml
  participant CD as cloud_daily
  participant BD as briefing-data
  participant AD as ai_daily.daily
  participant C as Claude (Haiku 5.5)
  participant BP as briefing-pages.yml

  W->>CD: workflow_run(수집 success)
  CD->>BD: 암호화 상태 복원 (control·runtime·원장)
  CD->>CD: 키 해시 = 승인 키? · 월 한도 남았나? · 오늘 이미 했나?
  CD->>CD: 오늘 무료 수집 완료 확인 (todays_refresh)
  CD->>BD: 공개 JSON 복원 + sha 임대
  CD->>BD: 수집 스냅샷 복원 (목록 재수집 생략)
  CD->>AD: daily(online, allow_spend, publish)
  loop 요청마다 비용 먼저 영속 예약
    AD->>C: 원문 대조·조건 추출 (검증 ≤40, 조사 ≤40)
    AD->>C: 탭 검증 ≤20 (보건소 공지 분류·축제 소개 대조)
    AD->>C: 주제 1 · 장보기 1 · 보건소 문장 ≤10
    AD->>C: 축제 1 · 혜택 1 · 청약 1 · 측정 변형 4
  end
  AD-->>CD: 결과 (실패한 추천은 규칙 카드로 대체)
  CD->>BD: ai-status · ai-approved · ai-*-pick · ai-health-notes
  CD->>BD: briefing.json 스냅샷 커밋 (sha 임대가 그대로일 때만)
  CD->>BP: dispatch 승인 스냅샷 게시 (snapshot_commit, expected_code_sha)
```

하루 최대 Claude 요청 수(정규 실행 기준, 승인된 한도):

```mermaid
pie showData
  title 하루 최대 요청 119건의 구성
  "원문 검증" : 40
  "추가 조사" : 40
  "탭 검증(공지 분류·축제 대조)" : 20
  "보건소 안내 문장" : 10
  "요청 설정 측정(공개 안 함)" : 4
  "주제" : 1
  "장보기 추천" : 1
  "축제 추천" : 1
  "혜택 추천" : 1
  "청약 추천" : 1
```

| 결과 상태 | 뜻 | 다음 |
| --- | --- | --- |
| `completed` | 오늘 일을 끝내고 스냅샷 게시 요청 | 게시 run이 Pages 배포 |
| `completed_with_provider_failure` | 일부 요청 거절·실패, 받은 결과는 게시 | 관리자 화면 `ai_status=failed` |
| `credit_exhausted` | 크레딧 소진, 받은 결과만 게시 | 다음 날 정상 실행 |
| `already_completed_today` | 오늘 이미 완료 | 아무것도 안 함 |
| `waiting_for_existing_refresh` | 오늘 무료 수집이 아직 없음 | 수집 완료 후 `workflow_run`으로 다시 |
| `refresh_dispatched` | 10시 이후에도 수집이 없어 직접 요청 | 수집 완료가 다시 이 워크플로를 깨움 |
| `trial_budget_limit` | 월 상한 도달 | 다음 달 자동 재개 |
| `ai_approval_merged_deferred` | 다른 실행과 승인 목록이 병합됨 | 다음 수집이 공개 |

---

## 8. 혜택 공개 판단

모델은 사실을 고치거나 승인하지 않습니다. 코드 게이트를 모두 통과해야만 자동 공개되고, 하나라도 걸리면 보류합니다.

```mermaid
flowchart TD
  C["수집 후보"] --> M{"사람 승인<br/>목록에 있나?"}
  M -- 예 --> RC
  M -- 아니오 --> X["AI 원문 대조·조건 추출<br/>(구조화 출력)"]
  X --> G1{"계약 형식 OK?<br/>후보 1개·레코드 1개"}
  G1 -- 아니오 --> H1["보류: contract"]
  G1 -- 예 --> G2{"원문과 다툼(disputed)?"}
  G2 -- 예 --> H2["보류: disputed"]
  G2 -- 아니오 --> G3{"핵심 필드 근거 있나?"}
  G3 -- 아니오 --> H3["보류: core_missing"]
  G3 -- 예 --> G4{"비용 상태 근거 있나?"}
  G4 -- 아니오 --> H4["보류: cost_missing"]
  G4 -- 예 --> G5{"종료일이 지나지 않았고<br/>연도가 원문에서 확인되나?"}
  G5 -- 아니오 --> H5["보류: 날짜"]
  G5 -- 예 --> RC["공개 직전 재확인<br/>신선도·원문 해시·철회 목록"]
  RC --> P["✅ 공개 briefing.json"]
```

- 판정 코드: [`auto_publish.decide`](../benefit_monitor/auto_publish.py), 철회·재확인: [`auto_release.py`](../benefit_monitor/auto_release.py).
- 매일 재확인(최대 20건, 6시간 안에 확인한 항목은 건너뜀)은 AI 실행에서 AI 검증·조사보다 **먼저** 돕니다. AI 실행은 수집 스냅샷을 재사용하므로 수집 요청이 없습니다. 수집 실행은 예산 95회를 거의 다 쓰므로 수집 뒤 남은 예산으로만 재확인합니다. 이미 공개된 항목은 마지막 확인 뒤 30시간이 지나면 화면에서 빠지고, 예산이 모자라 확인하지 못한 항목은 `report.json`의 `body_check_failures`에 `budget_exhausted`로 남습니다. 2026-11-22에는 두 번 바뀌었습니다. 재확인이 맨 뒤에 있을 때는 예산이 바닥나 공개 기간이 남은 항목들이 빠졌고, 수집 실행에서도 맨 앞으로 옮겼더니 축산물 마지막 5개 부위가 빠졌습니다.
- 축제·장보기·보건소·청약은 검증 혜택과 다른 별도 채널입니다. 모델 문장은 승인된 필드(`grocery_pick`, `health_notes[].sentence`, `festival_pick`, `benefit_pick`, `subscription_pick`)에만 “AI 작성” 표시와 함께 들어가고, 실패하면 규칙 카드·링크로 대체합니다.

---

## 9. 데이터 저장소 `briefing-data`

실행 사이의 상태는 같은 저장소의 `briefing-data` 브랜치에 파일 단위로 커밋합니다(GitHub Contents API, sha로 동시 쓰기 감지).

```mermaid
gitGraph
  commit id: "어제 스냅샷"
  branch briefing-data
  checkout briefing-data
  commit id: "health-notices.json" type: HIGHLIGHT
  commit id: "subscriptions.json"
  commit id: "subscription-trades.json"
  commit id: "ai-collection.age"
  commit id: "ai-approved.json (재확인)"
  commit id: "briefing.json 1차"
  commit id: "ai-control/runtime.age"
  commit id: "ai-status.json"
  commit id: "ai-*-pick.json"
  commit id: "briefing.json 스냅샷" tag: "snapshot_commit" type: HIGHLIGHT
```

| 파일 | 쓰는 쪽 | 읽는 쪽 | 공개 |
| --- | --- | --- | --- |
| `briefing.json` | 혜택 수집(1차), AI 실행(스냅샷) | 수집·AI 복원, source-health, 게시 run | ✅ 화면 데이터 |
| `health-notices.json` | health-notices | 수집 시 병합 | ✅ (briefing에 포함) |
| `subscriptions.json`, `subscription-trades.json` | subscriptions | 수집 시 병합, 청약 추천 | ✅ (briefing에 포함) |
| `grocery-baselines.json` | grocery-baselines | 수집 시 병합 | ✅ (briefing에 포함) |
| `ai-approved.json` | 수집(재확인·철회), AI 실행 | 수집·AI | 공개 가능한 필드만 |
| `ai-*-pick.json`, `ai-health-notes.json` | AI 실행 | 수집 시 병합(유효기간 검사) | ✅ “AI 작성” 표시 |
| `ai-tab-checks.json` | AI 실행 | 수집 시 병합(공지·축제 묶음과 재대조) | ✅ 접힌 행정 공지·축제 요금 메모 |
| `ai-status.json` | AI 실행 | 관리자 화면·briefing | 상태 문자열만 |
| `ai-control.age`, `ai-runtime.age`, `ai-collection.age` | AI 실행·수집 | AI 실행 | ❌ age 암호화(원장·검토 대기 자료) |

---

## 10. 화면이 데이터를 읽는 방식

![운영 화면 탭 전환](architecture/site-tabs.gif)

```mermaid
flowchart LR
  subgraph Pages["GitHub Pages (delivery/site)"]
    idx["index.html + assets/*.js·css<br/>(Vue 3 · Vite 빌드)"]
    adm["admin.html"]
    bj[("briefing.json<br/>모든 탭 데이터")]
    bm["briefing.md"]
  end
  subgraph Browser["사용자 브라우저"]
    app["App.vue<br/>혜택 · 청약 · 장보기 · 축제 · 보건소"]
    ls[("localStorage<br/>즐겨찾기 · 내 지역 · 방문 기록 · 선호/제외")]
  end
  idx --> app
  bj -->|fetch| app
  app <--> ls
```

- 사이트에는 빌드 산출물과 `briefing.json`·`briefing.md`만 올라갑니다([`assemble_pages.py`](../scripts/assemble_pages.py)). 서버 코드·API는 없습니다.
- 개인 정보(즐겨찾기·내 지역·반응)는 브라우저 안에만 있고 서버로 보내지 않습니다. 자세한 범위는 [브라우저 저장 범위](ai/personalization.md).
- 새 공개 전까지 이전 목록을 “○○ 기준” 안내와 함께 보여 주고, 공개되면 `pipeline_timing`(크롤링·AI·게시 소요 시간)을 한 줄로 보여 줍니다.

---

## 11. 안전장치

```mermaid
mindmap
  root((안전장치))
    비용
      공개 저장소일 때만 실행
      BENEFIT_PAGES_ZERO_SPEND 변수 확인
      요청 전 비용 영속 예약
      월 30달러 원장 상한
      자동 충전 없음
    동시성
      benefit-pages 그룹 공유
      Cloudflare는 실행 중이면 대기
      briefing.json sha 임대
      승인 목록 병합 시 게시 연기
    공개 품질
      코드 게이트 통과만 자동 공개
      실패 시 실패 상태 공개
      고정 커밋과 코드 SHA 재검증
      철회 목록 반영
    비밀
      Secret은 필요한 step에만
      공개 JSON에 키 문자열 검사
      상태 파일은 age 암호화
    접근 예절
      robots TLS 허용 호스트
      6시간 자치구 캐시
      실패 대기시간
      수집 요청 하루 95회 실행당 100회
```

---

## 12. 수동 실행 입력

| 워크플로 | 입력 | 하는 일 |
| --- | --- | --- |
| `briefing-pages.yml` | (없음) | 수집 한 번 더. 실행 이름 `수집` |
| | `deploy_approved_snapshot` + `snapshot_commit` + `expected_code_sha` | 승인된 고정 스냅샷 재검증 후 배포. **보통 AI 실행이 자동으로 요청하며 사람이 임의로 다시 누르지 않습니다** |
| | `apply_takedowns` | 내림 목록만 현재 공개 브리핑에 적용해 재배포 |
| | `external_schedule` | Cloudflare가 쓰는 표식. 오늘 이미 성공했으면 건너뜀 |
| `ai-daily.yml` | `check_only` (기본 켬) | 복원·Secret·원격 저장만 검증, Claude 호출 없음 |
| | `investigate_missing_conditions` (기본 켬) | 누락 조건 추가 조사 |
| | `refresh_completed_day` | 완료된 오늘을 한 번 더 실행(원장 보존) |
| | `retry_rejected_day` | 오늘 요청이 모두 무과금 4xx 거절이었을 때 한 번 재시도 |
| | `close_unresolved_reservation` | 결과가 없는 비용 예약을 쓴 것으로 닫고 오늘을 다시 실행 |
| | `resume_reviewed_halt` | 사람이 원인을 확인한 뒤 중단 해제 |
| | `grammar_probe_only` | 스키마 문법 컴파일만 시험(유료 1건 미만) |
| `health-notices.yml`, `subscriptions.yml` | `external_schedule` | Cloudflare가 쓰는 표식 |
| `frontend-checks.yml` | `check_ai_cloud` | 승인된 AI 전환의 무과금 Secret·원장 검증 |

복구 입력의 세부 조건은 [정책 대응표](ai/policy-map.md)에서 원 승인 조항을 확인합니다.

---

## 13. 확인하는 방법

| 무엇을 | 어떻게 |
| --- | --- |
| cron이 깨어나는지 | `scheduler/cloudflare`에서 03:20~04:50에 `npx --yes wrangler@4.156.0 tail` → 회차마다 `{"action":"dispatch"...}` |
| 순서대로 돌았는지 | `gh run list --limit 10` → `Health notices` → `Subscriptions` → `수집` → `AI daily trial` → `승인 스냅샷 게시` |
| 화면 데이터가 오늘 것인지 | `python3 -m benefit_monitor.live_check` (배포 전후 비교, [verify 스킬](../.claude/skills/verify/SKILL.md)) |
| 출처 실패 | `Source health` run 요약, 수집 run의 Step Summary(출처 ID·유형만) |
| 화면 | 홈 위쪽 “오늘 데이터 준비 …” 줄의 크롤링·AI·게시 시간 |

---

## 14. 이 문서의 그림 갱신

GIF 원본은 [`architecture/src`](architecture/src)에 있습니다. 실행 구조가 바뀌면 `pipeline.html`의 `STEPS`를 고친 뒤 다시 만듭니다. 시스템 Chrome과 저장소의 Playwright, `ffmpeg`를 사용합니다.

```sh
OUT="$PWD/.tools/verification-tmp/gif"; mkdir -p "$OUT/pipe" "$OUT/site"
node docs/architecture/src/capture.cjs "$PWD/frontend/node_modules/playwright" "$OUT"
# 프레임 → GIF (예: 파이프라인, 프레임당 1.8초)
ffmpeg -y -framerate 1/1.8 -i "$OUT/pipe/f%02d.png" \
  -vf "fps=10,split[a][b];[a]palettegen=max_colors=128[p];[b][p]paletteuse=dither=bayer" \
  -loop 0 docs/architecture/daily-pipeline.gif
```

Mermaid 그림은 GitHub에서 바로 렌더링됩니다. 시각·한도 숫자는 코드([`plan.js`](../scheduler/cloudflare/src/plan.js), 워크플로 `cron`, [`AGENTS.md`](../AGENTS.md))와 함께 고칩니다.
