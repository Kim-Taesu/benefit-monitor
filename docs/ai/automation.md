# 수집·AI 검토·주제 카드·일일 실행 연결

상태: 사용자 승인4일 운영의 실제 수집·AI 검토 대기·공개 전달·Pages 배포·화면·정기 등록·첫 실행 검증을 완료했다. AI 모델 품질의 자동 사실 승인 통과나4일 경과 관측 완료를 뜻하지 않는다.

```mermaid
flowchart LR
  A[기존 공식 수집기] --> B[본문 변경 감지]
  B --> C[Claude 추출 v3]
  C --> D[코드 검증]
  D --> E[비공개 검토 대기]
  E --> F[사람의 사실 승인]
  F --> G[기존 공개·기한 게이트]
  G --> H[AI 주제 제안]
  H --> I[주제·제목 검증]
  I --> J[별도 공개 승인]
  J --> K[정적 공개 JSON과 화면]
```

## 명령과 승인 경계

기존 수집 명령의 기본 경로는 무료 수집만 수행한다. AI 단계는 명시적으로 선택한다.

```sh
python3 -m benefit_monitor.cli --online --ai-review --ai-max-candidates 2
```

이 명령은 공식 본문을 읽고 입력을 준비하지만 API를 호출하지 않는다. 이번 일회 실험 안에서 실제 생성까지 허용하려면 `--ai-allow-spend`를 별도로 지정한다. 모든 실행은 동일한 `.tools/claude-trial/live/budget.json`을 사용한다. 하위 시험 runtime을 만들어도 별도 API 원장을 만들지 않는다.

HTTP 수집의 `cost_policy`는 공식 페이지 수집만 기록한다. Claude 사용 여부는 `ai_review.api_spend_requested`, 실제 사용량·비용은 별도 누적 원장으로 확인한다. 무료 HTTP telemetry를 전체 작업의 API 무과금 증거로 사용하지 않는다.

검토 결과는 `cache/ai_review/queue/`에 남으며, 계약 통과도 `pending_human_review`다. 공개 승인 파일에 자동 쓰지 않는다. 같은 본문·프롬프트 입력은 재호출하지 않고 작은 후보 한도 안에서 미확인 항목을 순환한다. 중단 후 입력을 동일하게 재사용해 시각 변경 때문에 새 유료 요청이 생기지 않게 한다. 본문 변경 시 기존 승인 항목을 재검토 보류한다.

## 주제 입력과 공개 카드

주제 입력은 기존 `publish.payload`의 읽기 전용 공개 게이트를 통과한 현재 사실에서 만든다. 원문·프롬프트·키·개인 프로필은 주제 입력에 포함하지 않는다. 후보의 공개 승인, 검증 시각·기한·재검토 보류를 재검사한다.

`public/topic-basis.json`은 주제 편집 승인이다. 항목별 편집은 내용 해시에 묶는다. 별도 승인을 받은 category 정책은 이미 사람이 승인한 labels.category의 문화·체험→culture, 교육·강좌→learning, 할인·적립→shopping만 연결할 수 있다. 다른 분류를 취업이나 가족에 임의 연결하지 않는다. 무료/주말/가족 수식은 기본 승인하지 않는다.

`topic_refresh`는 KST 하루1회만 유료 주제 시도를 허용한다. 실패하면 마지막 유효 초안의 현재 ID·claim만 남긴다. 카드 전체에 적용하는 프로필 조건은 별도 검토로 차단하며, 브라우저 개인 설정은 외부로 전송하지 않는다.

`public/topic-publication.json`은 별도 공개 승인이다. 정확한 초안 해시 또는 검토된 정책·편집 근거의 해시에 묶이며 만료시각이 필요하다. 규칙·근거가 바뀌면 정책 승인을 재확인한다. 승인된 카드만 `briefing.json.topic_cards`에 포함된다. 화면은 현재 검증된 항목과 사실이 일치하는 연결만 표시하고, 카드 묶음이 없거나 만료·잘못된 형식이면 기존 주제 규칙으로 복귀한다. 이전 카드가 만료 항목을 부활시키지 않는다.

## 일일 명령과 비활성 계획

```sh
python3 -m benefit_monitor.ai_daily
python3 -m benefit_monitor.ai_activation --output .tools/새-활성화-검토안
```

첫 명령은 기본 dry_run이며 네트워크·API·공개 쓰기를 하지 않는다. 두 번째 명령은 **설치하지 않고** 비활성 설정과 LaunchAgent 검토안을 프로젝트 내부에 만든다.

활성 설정은 `ai-automation.json`이다. enabled, recurring_spend_approved, public_application_approved는 기본 false다. 매일 KST06:00 이후의 첫15분 점검에서 실행하고 하루 중복을 차단한다. 하루 조사 최대2개·주제1회이며 기존 누적 $5·40요청을 초기화하지 않는다. 비정상 종료 후 같은 날 유료 작업을 자동 재시작하지 않는다.

LaunchAgent 설치와 설정 활성화는 현재 하지 않았다. 사용자 요청의 “반복 API 지출·공개 적용은 별도 승인 범위”를 따른다. 실제 배포 전달 경로와 활성화 검토표를 완성한 뒤 구체적 승인을 받는다. 기존 브랜치를 사용하며 main 병합을 하지 않는다.

## 검증과 한계

[전체 목표 실행 기록](evaluations/goal-integration-2026-11-05/README.md). 실제 API 시험은 정확도 평가이며 모델이 모든 조건을 정확하게 추출했다는 증거가 아니다. 조사 초안의 자동 사실 승인·신청·구매·예약은 구현하지 않는다. 기존 robots·TLS·허용 호스트·2MiB·HTTP예산·실패900초·구6시간캐시 정책과 무료 수집기의 기본 금지는 유지한다.

## 원격 전달 검증과 활성화 조건

`remote_delivery`는 공개 승인과 원격 전달 승인을 모두 요구하고, 변경 없는 커밋된 작업 사본만 전달한다. 인증 전에 저장소·작업 브랜치·공개 snapshot을 검사한다. 하위 명령에는 허용한 실행 환경만 전달하며 기존 셸 API 키·GitHub 토큰을 넘기지 않는다. 프로젝트 내부의 개인 토큰이 있으면 소유자·0600 권한·계정 이름을 검사해 사용한다. 없으면 `gh auth token --user Kim-Taesu`로 개인 계정 하나를 지정한다. 실제 API 계정 이름과 공개 저장소 여부를 다시 검사한다. 전역 계정 전환을 하지 않는다.

공개 JSON만 기존 `briefing-data`에 반영하고 반환된 고정 commit SHA와 코드 SHA를 작업 브랜치의 기존 `briefing-pages.yml`에 전달한다. workflow는 프로젝트 코드를 실행하기 전에 요청한 코드 SHA와 체크아웃을 비교한다. 깨끗한 배포 사본은 키·원장·비공개 검토 초안 없이 `public_snapshot`으로 승인 사실·기한·보류 상태·편집 정책을 재검증한다. 오래된 snapshot과 승인 사실 변경은 거절한다. 성공적인 dispatch는 실제 배포 완료로 표시하지 않는다.

실패 상태를 미러링할 때도 기존 원격 보류와 더 최신인 로컬 본문/제목 변경 보류를 유지한다. 원격 복원으로 재검토 대상을 다시 추천하지 않는다.

익명 조회 결과 기존 Pages 환경은 main만 허용한다. main 병합 없이 공개하려면 `docs/ai-research-playbook`을 환경의 허용 브랜치에 추가하는 별도 승인이 필요하다. 로컬·원격 커밋은 공통 조상이 없지만 기준 tree SHA가 동일하다. 승인 후 양쪽 이력을 보존하고 일반 push를 수행하며 강제 push는 사용하지 않는다. [확인 자료](evaluations/goal-integration-2026-11-05/remote-work-comparison.json).

비활성 LaunchAgent 계획은 Python·gh 경로를 명시하고 TMPDIR·로그를 프로젝트 안에 둔다. 설치 전에 프로젝트의 `cache/ai_daily`, `.tools/tmp`를 준비해야 한다. 정기 작업은 이 Mac이 켜져 있고 사용자 세션이 실행 중일 때만 동작하며 실행 시각을 보장하지 않는다. macOS 전역 LaunchAgent 파일 한 개의 설치·등록은 별도 승인에 포함해야 한다.

검토안은 활성화 후4일 한정, 하루 조사 최대2개·주제1회다. 전체 누적40요청 중13회가 남았으므로 최대12회 일일 시도와 최대1회 검증 여유를 제안한다. 기존 실패 예약과 $5 한도를 유지하며 실제 청구·세금·계정 잔액을 보장하는 값으로 표현하지 않는다. `trial_expires_at`과 주제 공개 정책 만료를 활성화 시각에 맞춰 설정한다. 시간 창이5개 달력 날짜에 걸쳐도 일일 시도는 최대4회로 제한한다. 중단하려면 `ai-automation.json`의 enabled를 false로 바꾸며, 이미 공개된 카드는 기존 기한 검사를 계속 받는다.

## 보안 검증 중 발견과 조치

개발 중 한 모의 테스트의 실패 메시지가 상속 셸 환경을 출력해 프로젝트와 무관한 인증정보가 대화에 노출됐다. 생성된 로컬 로그를 삭제했으며 테스트는 가짜 환경만 사용하고 환경 값을 실패 메시지에 출력하지 않도록 수정했다. 실제 원격 전달도 환경 허용목록을 사용한다. 외부 서비스 호출은 모의 처리였고 해당 서비스에 실제 요청하지 않았다. 대화에 노출된 인증정보 교체는 사용자 조치로 남아 있다. 저장소의 비밀 패턴 검사 통과를 이 노출이 없었다는 증거로 취급하지 않는다.

## 활성화 승인과 인증 단계 — 2026-11-05

사용자가4일 한정 검토안에 `ok`로 응답해 반복 지출·공개·지정 LaunchAgent 설치 범위를 승인했다. [승인 기록](evaluations/goal-integration-2026-11-05/activation-approval.json). 개인 계정·공개 저장소·무료 확인 변수·기존 Pages 설정은 인증 조회로 재확인했다. 첫 push는 저장된 OAuth 토큰의 workflow scope 부족으로 GitHub가 거절했다. 이 권한을 우회하지 않는다.

인증 갱신은 프로젝트 내부 `.tools/personal-gh-auth`의 개인 계정 설정만 사용하며 전역 활성 계정을 전환하지 않는다. 새 토큰이 이 설정에 저장되면0600 권한·Git 제외를 유지하고 원격 전달 프로그램이 해당 개인 설정을 선택한다. 일회용 인증 코드·토큰을 공개 문서에 기록하지 않는다. 실제 GitHub 계정 이름과 공개 저장소 여부를 다시 확인한 뒤 push·배포를 이어간다. 이 인증 단계 당시에는 스케줄과 공개 반영이 미완료였으며, 최종 완료는 아래 정기 등록 결과에 기록했다.

인증 갱신 과정에서 gh의 이름 지정 조회가 새 로컬 토큰보다 전역 키체인의 옛 토큰을 우선 반환함을 확인했다. 새 개인 토큰의 workflow scope와 실제 계정을 직접 확인하고 Git 제외·0600의 `.tools/personal-gh-auth/token.json`에 저장했다. 프로그램은 이 파일을 우선하며 전역 키체인과 활성 계정을 바꾸지 않는다. 토큰 값은 대화·공개 산출물에 기록하지 않는다.

첫 실제 일일 실행의 승인 항목31개 주제 입력은 보기 좋은 JSON 형식의 파일 크기 제한으로 과금 전에 중단됐다. 다음 입력은 전체 원본을 compact JSON으로 저장한다. 모델 전송에는 모든 항목·요약·조건·기한·편집 근거와 별도 fee_status·payment_terms·benefit_value를 보존하고, 중복 공개 메타데이터만 제외한다. 전체 원본과 원래 claim ID는 로컬 검증에 그대로 사용한다.64kB API 전송 한도는 유지한다. 별도 승인된 검증1회는 실제 응답을 받았지만 잘못된 ID·표준 제목 문제로 거절됐다. 이를 성공으로 바꾸거나 유료 재시도하지 않고 기존 화면 규칙으로 복귀한다.

## 실제 활성화 검증 결과

[전체 실행 기록](evaluations/goal-integration-2026-11-05/activation-result.json). 첫 실제 일일 실행은 공식 HTTP67/설정75회, 공개 JSON43건, AI 조사2건이다. 조사1건은 계약 통과·1건은 거절됐으며 둘 다 pending_human_review로 비공개 대기에만 저장했다. 별도 주제 검증1회도 거절돼 공개 AI 주제는0개이고 기존 화면 주제 규칙으로 복귀했다. 승인 사실 원본은 변경하지 않았다.

[실제 workflow](https://github.com/Kim-Taesu/benefit-monitor/actions/runs/41967802419)의 빌드·배포가 성공했다. 공개 URL의 항목·자치구 관측이 고정 snapshot과 일치하고,390/1440 화면의 실제 초기 데이터도 일치했다. JSON43건 중 기존 서울 베타 범위40건을 표시했으며 문화 카드12건 선택·가로 넘침 없음·화면 오류 없음·외부 API 호출 없음을 확인했다. 나머지3건은 기존 지역 범위 필터에 따른 제외로, 검증 실패나 혜택 종료를 뜻하지 않는다.

기존 main 정기 작업이 오늘 KST06:47에 시작된 점을 확인했다. 새 정기 AI 실행은06:00 이후라도 당일 main 정기 작업이 없거나 진행 중이면 과금·일일 시도 기록 전에 기다린다. 다음15분 점검에서 재확인하고 기존 정기 작업 완료 뒤에 수집·AI·배포를 실행해 작업 브랜치 화면이 뒤늦은 main 배포로 덮이는 순서를 방지한다. GitHub 정기 작업 자체가 실행되지 않는 날에는 자동 공개도 대기하므로 정시 실행을 보장하지 않는다. 이미 완료한 날에는 이 조회도 반복하지 않는다.

누적30요청의 usage 계산액은$0.075924, 이전 실패 예약 포함 예산 점유$0.106768, 보수적 잔여$4.893232·10회다. 기존 전체 상한·실패 예약은 유지한다. 사용자에게 지정된 LaunchAgent 파일 하나만 관리자 권한으로 설치하는 명령을 전달했다. 상위 폴더의 소유권·권한은 변경하지 않았다. 파일 설치 후 등록·첫 중복 차단 실행을 확인해야 전체 완료를 판정한다.

## 정기 등록 완료와 중단 방법

사용자가 지정 plist 파일을 설치한 뒤, 검토안과 byte 일치·사용자501 소유·0600 권한을 확인했다. gui/501/com.benefit-monitor.ai-daily에 등록했고 첫 실행은 already_completed_today, 종료값0으로 기존 당일 작업 중복을 차단했다. API는 등록 전후 모두30회다. 등록한 job은15분 간격으로 점검하며 기존 main 정기 작업 완료 후 하루1회 실행한다. 최대4회 일일 시도 또는2026-11-09 13:09:12 KST 만료 중 먼저 도달한 조건에서 수집·유료 호출·공개 전달을 중단한다.

즉시 중단하려면 프로젝트 `ai-automation.json`의 enabled를 false로 바꾼다. 등록 자체를 해제하려면 개인 사용자 세션에서 `launchctl bootout gui/501/com.benefit-monitor.ai-daily`를 실행한다. 이는 승인한 job 하나에만 적용한다. 기간 만료는 작업 동작을 중단하며 plist 파일·등록을 자동 삭제하지 않는다. 이미 공개된 데이터의 표시기한 검사는 계속 적용된다.

최종 workflow41969019660은 Python362개·프런트 단위52개·빌드·snapshot 검증·Pages 배포를 통과했다. 최종 배포 코드d2c0973836180105a6d29edcfd840abdea5140e7, deployment7565342259의 성공과 실제 URL을 확인했다. [요구사항별 완료 감사](evaluations/goal-integration-2026-11-05/completion-audit.md). 운영 연결 완료와 모델 정확도 실패·향후 경과 관측을 구분한다.

## GitHub Secrets 전환 완료 — 2026-11-05

사용자가 Secrets 기반 전환 설계를 승인했다. [전환 검증과 최종 절차](evaluations/actions-migration-2026-11-05/README.md). 사용자가 PR #18을 main에 머지한 뒤 Mac job 해제·enabled=false → 최신 원장/검토 자료 암호화 업로드 → main check_only 검증 → cloud 활성화를 완료했다. 실제 main 실행은 already_completed_today로 종료했고 요청30회를 유지했다. 앞 절은 전환 전 로컬 등록 이력이다. [최종 전환 감사](evaluations/actions-migration-2026-11-05/completion-audit.md).

새 `ai-daily.yml`은 공개 표준 ubuntu-24.04 runner에서 KST06:00~23:45의15분 점검을 수행한다. 당일 main 무료 수집 완료 후 최신 보류 상태를 병합하고 하루1회 처리한다. 한 concurrency group과 원격 CAS로 실행을 직렬화한다. handoff가 완료되지 않은 control에서는 과금하지 않는다. 누적 한도·4회·기존 만료에 도달하면 자기 AI workflow만 중지하며, API 실패로 workflow 중지에 실패해도 프로그램 gate가 호출을 막는다. 기존 무료 workflow는 유지한다.

키는 AI step의 ANTHROPIC_API_KEY, 암호화 identity는 BENEFIT_AI_STATE_IDENTITY Secret에서 읽는다. 명시적 cloud 모드·개인 저장소·schedule/workflow_dispatch가 아니면 환경변수 키를 받지 않는다. 로컬 기본 loader는 `.env.claude` 그대로다. runner에는 개인 장기 GitHub 토큰을 옮기지 않고 해당 job의 단기 GITHUB_TOKEN만 사용한다. frontend/npm/PR 테스트에 AI Secret을 전달하지 않는다.

평문 원장·검토 대기·모델 응답은 cache/artifact로 올리지 않는다. 공식 SHA256을 검증한 프로젝트 내부 age가 기존 briefing-data에 control/runtime 암호문을 저장한다. control은 비용 예약 전 원격 확인과 최신 날짜 기록을 담당하며, 이전 runtime이 원장을 되돌릴 수 없다. 누락·손상·미정산·충돌은 자동 초기화하지 않고 중단한다. 공개 전달은 기존 validator를 통과한 JSON의 고정 snapshot과 main SHA로 기존 Pages workflow를 dispatch한다.

무과금 점검은 Actions의 Frontend P0 checks → Run workflow → 작업 브랜치 → check_ai_cloud=true로 실행한다. 이 경로는 등록된 Secret과 암복호화·원격 쓰기만 검증하며 당일 시도·Claude·배포를 수행하지 않는다. main 반영 후에는 AI daily trial의 check_only=true도 같은 검증을 수행한다.

중단은 Actions의 AI daily trial에서 Disable workflow를 선택한다. 진행 중 작업까지 이미 지출한 비용을 되돌리지는 않는다. cloud 전환 후 Mac enabled를 임의로 다시 켜지 않는다. 최신 원격 원장과 미정산 예약을 복원·대조한 뒤 하나의 실행 주체만 재개해야 한다. 복구 명령은 `python3 scripts/ai_cloud_handoff.py restore`이며 미정산 예약도 보존해 검토할 수 있고 스케줄을 자동 재개하지 않는다. 원격 control 검증만 하려면 `check`를 쓴다. 전환용 `prepare`·`activate`는 은퇴했다(2026-11-07 원장 개정 뒤의 revision 2 control을 로컬 캡처로 바꾸면 안 된다). 실행하면 안내 문구와 함께 종료값 2로 멈춘다.

## 실험 한도 변경 — 2026-11-05

사용자 승인으로 누적 요청 200회, 일일 실행 14회, 만료 2026-11-19 13:09:12 KST로 바꿨다. 금액 상한 $5, 하루 조사 최대 2건과 주제 1회는 그대로다.

- 코드 상한: `trial_budget.MAX_REQUESTS=200`, `MAX_RUN_DAYS=14`, `cloud_state.MAX_EXPIRY`. 기존 40요청 원장도 그대로 읽는다.
- 원격 control은 main 병합 뒤 첫 Actions 실행이 한 번만 갱신한다. `check_only` 실행도 같은 갱신을 하므로 과금 없이 확인할 수 있다. 결과의 `limit_revision_applied`, `max_requests`, `expires_at`으로 확인한다.
- 기존 30회 기록과 실패 예약, 노출액 106,768 microUSD, 11/5 완료 기록은 바꾸지 않는다.
- 하루 최대 3요청이라 14일을 다 써도 약 42회 수준이다. 200회는 상한일 뿐 목표 사용량이 아니다.
- 주제 공개 정책 만료도 같은 시각으로 맞췄다.

## 실행 트리거와 실패 표시 — 2026-11-06

GitHub 예약 실행이 크게 늦거나 빠져서 트리거를 바꿨다. 모두 무료 GitHub 기능이다.

| 관측 | 내용 |
|---|---|
| 공개 브리핑 01:00 예약 | 10/28~11/6 매일 5.8~10.7시간 늦음, 11/4 실행 없음 |
| AI 15분 예약 | 11/5 등록 뒤 약 38번 중 1번 실행, 그마저 시간대 밖 |

- AI 일일 실행은 공개 브리핑 실행이 성공으로 끝나면 바로 시작한다(`workflow_run`). 15분 예약은 보조다.
- 공개 브리핑 예약은 부하가 몰리는 정각을 피해 00:37 KST로 옮겼다.
- AI 실행이 기다리는 "오늘의 수집"에 예약 실행뿐 아니라 수동 실행도 넣었다. push 실행은 수집하지 않아 넣지 않는다.
- 10:00 KST까지 그날 수집 실행이 하나도 없으면 AI 실행이 공개 브리핑을 한 번 수동 실행한다. 그 완료가 다시 AI 실행을 시작한다.
- 요청이 공급자에게 거절된 날은 브리핑 공개는 그대로 하되 Actions 결과를 실패로 표시한다.
- 원장이 중단되면 사람이 원인을 확인한 뒤 Actions → AI daily trial → Run workflow에서 `resume_reviewed_halt`를 켜서 해제한다. `check_only`를 함께 켜면 Claude 호출 없이 해제만 한다.
- 그날 요청이 모두 무과금 4xx 거절이었다면 같은 수동 실행에서 `retry_rejected_day`(check_only 끔)를 켜서 그날을 한 번 다시 시도할 수 있다. 실행일 수는 늘지 않고 원래 결과는 `retry_of`에 남는다.
- 수동 실행에서 `grammar_probe_only`를 켜면 조사 스키마의 문법 컴파일만 유료 1건(출력 16토큰, $0.001 미만)으로 시험한다. 날짜 기록을 쓰지 않고, 거절되면 실험을 멈추지 않은 채 Actions 결과만 실패로 표시한다.

## 운영: 교차 조사·자동 공개 — 2026-11-07

한도는 월 $15(프로그램 원장)뿐이다. 하루 조사는 최대 20건이다. 이전의 누적 $5·200요청·14 실행일·11/19 만료는 없다.

### 크레딧 소진
- Anthropic 크레딧이 떨어지면 해당 실행이 `credit_exhausted`로 끝나고 GitHub Actions 실패 메일이 온다. 이 메일이 알림이다.
- 사용자가 Anthropic 콘솔에서 수동 충전한다. 다음 날 실행부터 자동으로 재개된다. 코드나 workflow를 고칠 필요가 없다.
- 상태는 `ai-status.json`(briefing-data)과 `ai-status` 출력에서 본다. 소진 중에는 새 자동 공개가 없고 기존 공개 항목은 그대로 유지된다.

### 어드민 토큰 만들기
1. GitHub Settings > Developer settings > Fine-grained personal access tokens > Generate new token.
2. Repository access는 `Kim-Taesu/benefit-monitor` 하나만 선택한다.
3. Permissions: Contents Read and write, Actions Read and write. 그 외는 주지 않는다.
4. 만료는 짧게(예: 7~30일) 정한다.
5. `/admin.html`에 붙여 넣는다. 기본은 이 탭의 `sessionStorage`이고, "기억" 옵션을 켜야 `localStorage`에 저장된다. 공용 기기에서는 켜지 않는다.

### 보류 이유 확인
- 자동 공개 판단은 항목별 `reasons` 목록으로 남는다. 비공개 `cache/ai_publish/decisions.json`과 검토 대기 행의 `auto_publish.reasons`에서 본다. `contract`(출력 계약 불일치), `taken_down`, `stale_check`(본문 재확인 실패) 등이 있다.
- 이유가 있으면 공개하지 않는 것이 정상 동작이다.

### 내리기와 복원
- 어드민 페이지에서 항목을 내리면 `ai-takedowns.json`에 기록하고 `briefing-pages.yml`을 `apply_takedowns: true`로 실행해 현재 공개 브리핑에서 뺀다. 복원은 기록을 지우고 같은 방식으로 반영한다.
- 반영까지 workflow 실행 시간만큼 걸린다. 조회 실패 때에는 모든 자동 공개 항목을 숨기는 쪽으로 동작한다.
- 내리기 배포는 현재 `briefing.json`을 다시 쓰기 전에 자동 공개 항목을 `ai-approved.json`과 내림 목록으로 수집 경로와 똑같이 재검사한다. 철회·만료·30시간 경과·승인본과 다른 항목은 같이 빠진다. `briefing.json` 형태가 이상하면 배포하지 않고 단계를 실패시킨다.

### 암호화 runtime 크기와 보관
- briefing-data의 `ai-runtime.age`·`ai-control.age`는 1 MB를 넘으면 contents API가 본문을 주지 않는다. 그래서 sha만 contents API(object 형식)로 묻고 본문은 git blob API로 읽는다. 암호문 상한은 8 MiB다.
- 매 AI 실행은 유료 호출과 날짜 사용 전에 오래된 비공개 자료를 정리한다. 대상은 `.tools/claude-trial/live/runs/`, `.tools/ai-inputs/`, `cache/ai_review/documents/`의 14일 넘은 항목 중 현재 검토 상태(`cache/ai_review/state.json`)·자동 공개 기록의 결정·본문 캐시 색인이 가리키지 않는 것뿐이다. 원장(`budget.json`)·응답 캐시(`responses/`)·검토 대기열은 지우지 않는다. 기준 파일이나 시각을 읽을 수 없으면 아무것도 지우지 않는다.
- 정리 뒤에도 파일 수 3072개, 원본 24 MiB, 압축 6 MiB 중 하나를 넘으면 `runtime_too_large`로 멈추고 Actions가 실패한다. 이때는 유료 호출도, 그날 실행 기록도 남기지 않는다. 응답 캐시는 원장이 가리키므로 장기적으로 이 한도에 닿을 수 있다. 그때는 사람이 검토해 정리 방법을 정한다.

### 게이트 코드와 주제 카드 승인 해시
자동 공개 게이트 등 공개 경로 코드를 바꾸면 `public/topic-publication.json`의 `policy_sha256`을 다시 기록해야 한다.

```sh
python3 -c "from benefit_monitor.topic_publication import policy_hash; print(policy_hash('.'))"
```

출력값을 `policy_sha256`에 넣는다. 맞지 않으면 가드 테스트(`tests/test_topic_publication.py`)가 실패한다.

주제 카드 공개 승인(`public/topic-publication.json`)은 2027-11-07까지 유효하며 이후에는 사람이 갱신해야 한다. 게이트 코드가 바뀌었다면 `policy_sha256`도 다시 기록한다.
