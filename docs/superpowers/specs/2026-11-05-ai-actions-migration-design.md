# GitHub Actions AI 일일 실행 전환 설계

상태: 설계 검토 중. ANTHROPIC_API_KEY Secret 등록은 실제 이름·메타데이터로 확인했다. 값은 조회하거나 출력하지 않았다. 현재 로컬 스케줄과 누적 원장은 변경하지 않았다.

## 의도와 고정 범위

사용자는 GitHub Secrets를 사용해 Mac을 켜둘 필요 없는 AI 일일 리포팅을 원한다. 앞서 설명한 키 주입·Actions 실행·누적 원장/검토 대기 보존·Mac 중복 실행 중단의4단계를 구체화한다.

- 개인 공개 저장소 Kim-Taesu/benefit-monitor, 기존 작업 브랜치 docs/ai-research-playbook, 기존 briefing-data와 Pages만 사용한다. 새 호스팅·유료 서비스·클라우드 자원을 만들지 않는다.
- 기존 누적 $5·40요청을 초기화하지 않는다. 현재30요청, usage 계산$0.075924, 실패 예약 포함 점유$0.106768을 그대로 이관한다.
- 하루 조사 최대2건·주제1회, 전체 일일 시도 최대4회와2026-11-09 13:09:12 KST 만료를 연장하지 않는다. 이미 완료한11/5 실행도1회로 센다.
- 공식 조회의 기존 HTTP 설정75·hard cap100·robots·TLS·허용목록·6시간 캐시·실패 대기와 사람이 승인하는 사실 경계는 유지한다.
- 새 추출은 비공개 검토 대기다. 승인된 유효 사실만 주제 입력으로 사용하며 실패 시 이전 유효 카드 또는 기존 화면 규칙으로 복귀한다.
- main 병합은 사용자가 한다. 작업 브랜치에서 구현·검증·PR을 준비하고, 기본 브랜치 반영과 최종 이관을 확인하기 전에는 현재 자동 실행을 끄지 않는다.

## 확인한 현재 조건

- Python 코드에는 외부 패키지 의존성이 없고 Claude 키는 현재 로컬600 파일에서만 읽는다.
- Actions Secrets는 값을 API로 다시 읽을 수 없다. 따라서 Mac에서 Secret을 당겨 쓰는 구조를 만들지 않는다.
- Actions runner는 일회 환경이므로 cache/artifact만 믿고 원장을 복원하면 누적 과금 한도가 초기화될 수 있다.
- Mac에는 gpg가 없다. Ubuntu24.04 runner에는 GnuPG가 기본 제공되지만, Mac에서 검토 자료를 복구하고 초기 이관까지 처리하려면 별도 경로가 필요하다.
- 이관에 필요한 최소 상태27개 파일도 압축·base64 약72,736bytes여서 단일48KiB Secret에 들어가지 않는다. 대량 상태를 Secrets로 나누는 방식은 사용하지 않는다.

## 선택한 구성 — 구현자의 제안

Python 표준 라이브러리는 유지한다. 암호화만 검증된 age 명령행 도구를 사용한다. 자체 암호 알고리즘은 구현하지 않는다. 이 도구1개를 Mac과 runner의 프로젝트 내부 .tools/bin에 설치하고 버전·공식 배포 SHA256을 고정·검증한다. 전역 설치·설정 변경은 하지 않는다. 이 시스템 도구 추가는 이 설계에서 승인받을 변경이다.

공개 저장소에 보존하는 새 상태 파일은 기존 briefing-data의 암호문2개뿐이다.

| 파일 | 내용 | 갱신 시점 |
|---|---|---|
| ai-control.age | 기존 전체 원장, 당일 시도 기록, 시험 만료/횟수, 이관 기준·세대 정보 | 하루 시도 시작 전과 모든 API 예약·정산·실패 시 |
| ai-runtime.age | 검토 대기·해당 모델 입출력·주제 초안/이전 유효 카드·캐시·운영 보류 등 허용한 runtime 파일 | 실행 종료·실패 처리 시 |

복호화 identity는 프로그램이 무작위로 생성해 로컬 Git 제외600 파일과 새 repository Secret BENEFIT_AI_STATE_IDENTITY에 보관한다. 값은 대화·로그·커밋·artifact에 출력하지 않는다. 이 Secret 추가는 API 키 추가 등록이나 새로운 서비스 지출이 아니다. 기존 개인 GitHub 인증으로 프로그램이 stdin을 통해 등록하며 사용자에게 키 값을 전달받지 않는다.

age는 데이터 무결성 검사를 통과한 뒤에만 복호화 결과를 파싱한다. 임시 평문은 프로젝트 내부600 파일이며, 실패 시 삭제하고 API를 호출하지 않는다. 원문·검토 대기·원장을 평문 Git/cache/artifact로 올리지 않는다.

## 누적 과금·중단·동시성

1. 모든 Actions AI 실행은 저장소 전체에서 고정 concurrency group 하나를 공유하고 진행 중 작업을 취소하지 않는다.
2. job이 시작한 다음 Contents API로 최신 암호문을 읽는다. repository Secret에 실행 중 원장을 다시 저장하는 방식은 쓰지 않는다. Secret은 workflow 대기열 등록 시 읽히기 때문이다.
3. 원장 파일의 blob SHA를 조건으로 암호문을 저장한다. 충돌·손상·부재·복호화 실패를 새 원장 생성으로 바꾸지 않고 중단한다. 같은 branch의 briefing.json 업데이트는 다른 파일로 분리한다.
4. Claude HTTP 전송 전에 비용 예약을 원격 암호문에 영속 저장·확인한다. 저장이 실패하면 HTTP를 보내지 않는다. 정산·실패 예약도 즉시 같은 경로에 저장한다.
5. 기존 TrialBudget은 로컬 파일 잠금을 유지하며 cloud 모드에서 변경 트랜잭션에만 원격 저장 hook을 호출한다. summary 같은 읽기에는 업로드하지 않는다. ai_review가 만든 자식 프로세스도 같은 control context를 사용한다.
6. 재시작 시 미정산 reserved가 남아 있으면 유료 호출을 멈춘다. 사라진 .sent 파일이나 이전 입력 캐시를 이유로 같은 요청을 재전송하지 않는다. 정산 업로드 실패도 예약을 유지한 보수적 중단으로 처리한다.
7. 당일 시도 기록을 수집·유료 요청 전에 원격에 저장한다. 중단된 날은 자동 재실행하지 않는다. 이 기록은 기존 로컬 days.json과 함께 이관하므로 환경 전환이 당일 추가 호출을 허용하지 않는다.
8. runtime archive의 오래된 budget/days 파일이 최신 control을 덮어쓸 수 없도록 복원 우선순위를 고정한다. control이 항상 권위다.

프로그램의 한도는 이 프로그램의 호출을 통제한다. 공급자 계정 전체의 청구액·세금·기존 구독 비용을 보장한다고 표현하지 않는다. 소유자가 직접 이전 Git 상태를 강제로 복원하거나 workflow를 바꾸는 악의적 관리 권한 공격까지 해결하는 설계는 아니다.

## workflow와 키 사용

- 새 AI workflow는 기본 브랜치의 schedule 및 명시적 workflow_dispatch만 받는다. PR·fork·pull_request_target 이벤트로 키를 주입하지 않는다.
- 공개 저장소·기존 무료 실행 확인 변수를 검사하고 표준 ubuntu-24.04 runner만 사용한다. larger runner·새 유료 기능·추가 cache/artifact는 만들지 않는다.
- ANTHROPIC_API_KEY와 상태 identity는 필요한 AI 처리 step에만 env로 주입한다. checkout, npm, 프런트 빌드와 Pages artifact에는 전달하지 않는다. VITE 등 공개 빌드 변수로 사용하지 않는다.
- cloud 모드의 키 loader는 환경변수를 검증해 읽는다. 기본 로컬 모드는 기존 .env.claude를 계속 사용하므로 기존 셸의 임의 API 키를 자동 채택하지 않는다.
- GitHub 접근은 job의 단기 GITHUB_TOKEN만 사용한다. Contents write는 암호문/공개 JSON, Actions write는 기존 Pages workflow dispatch와 자기 AI workflow 중지에만 사용한다. 개인 장기 OAuth 토큰을 runner로 옮기지 않는다.
- 기존 공개 gate·snapshot validator와 공개 결과 형태는 재사용한다. cloud publisher는 고정 코드 SHA·snapshot SHA로 기본 브랜치의 기존 Pages workflow를 dispatch한다. dispatch 성공과 실제 배포 성공은 구분한다.

## 실행 시각과 종료

기존 main 정기 수집은 유지한다. 새 AI workflow는 KST06:00~23:45 구간을15분 간격으로 점검한다. 당일 기존 main 정기 수집이 아직 없거나 실행 중이면 원장·당일 시도 기록·유료 호출 전에 대기한다. 완료한 날은 추가 수집·생성을 하지 않는다. GitHub의 지연·누락 때문에 정시 실행을 보장하지 않는다.

누적 한도·4회 일일 시도·기존 만료 중 먼저 도달한 조건에서 자기 AI workflow를 비활성화한다. 최초 이관/검증 전에는 이 중지 동작을 운영 workflow에 적용하지 않는다. GitHub 장애로 비활성화 API가 실패해도 프로그램의 만료/횟수 gate가 API 호출을 차단한다. 기존 무료 수집 workflow는 끄지 않는다.

## 이관과 되돌리기

1. 현재 로컬 상태와 원본 API 산출물은 그대로 보존한다. 키 파일·개인 GitHub 토큰·프로필·임의 파일을 archive에 넣지 않는다. 허용 파일 경로·총 크기·파일 수·링크 여부를 검증한다.
2. 작업 브랜치에서 테스트와 무과금 workflow 검증을 한다. Secret 존재·키 fingerprint 일치·암복호화·원장 복원·중복 차단·공개 전달 권한을 확인한다. 현재 Claude 호출30회가 늘지 않아야 한다.
3. 사용자가 새 PR을 main에 반영한 뒤 최종 handoff를 수행한다. cloud 스케줄은 handoff 준비 상태가 아니면 과금하지 않는다. 그때까지 현재 Mac 스케줄을 유지한다.
4. 최종 handoff는 현재 Mac 스케줄을 해제하고 enabled=false로 만든 다음 최신 원장·당일 상태·검토 대기를 암호화해 올린다. AI 프로세스가 실행 중이면 종료를 확인하거나 안전하게 기다린 뒤 진행한다. 앞서 준비한 오래된 snapshot을 그대로 활성화하지 않는다.
5. 원격의 이관 세대·기준 원장 해시·금액·요청 수·당일 상태가 일치하고, cloud에서 복원·중복 차단을 확인한 다음 활성화한다. 원장 파일은 이후 자동 초기화할 수 없다.
6. handoff 실패 시 cloud를 비활성 상태로 두고, 원격/로컬 중 앞선 원장과 미정산 상태를 먼저 대조한 뒤에만 기존 로컬 실행을 재개한다. 두 환경을 동시에 켜지 않는다.

복구·사람 검토 명령은 암호문을 로컬 .tools 아래로 내려받아 같은 age identity로 복호화한다. 키·원문을 콘솔에 출력하지 않고 기존 queue/result 파일로 복원한다. 기존 로컬 산출물과 이력은 삭제하지 않는다. cloud 이후의 최신 원장을 반영하지 않고 로컬 실행을 다시 켜는 동작은 금지한다.

## 검증 계약

- 환경변수 키 사용·누락·잘못된 키·로그 미출력과 기본 로컬 loader의 호환성.
- 기존30요청·실패 예약·완료한11/5 실행·기존 만료가 이관 전후 일치. 누락/손상 상태로 초기화하지 않음.
- 원격 저장 실패 시 API 전송0, 충돌 시 덮어쓰기 없음, 정산 실패/중단 뒤 중복 유료 호출 없음, stale runtime이 control을 덮어쓰지 않음.
- 잘못된 identity·변조/절단 암호문·경로 탈출·symlink·과대 archive 거절. 실제 age 암복호화 roundtrip을 Mac과 CI에서 확인.
- 두 dispatch·재시작·부분 실패에서도 동일 일자의 조사2/주제1·전체4회·누적 $5/40 유지.
- 공식 HTTP·robots·캐시·본문 hold·주제 의미 검사·기존 화면 fallback 회귀 검사.
- 실제 Secrets 주입·복원·당일 중복 차단 검증은 추가 Claude 호출0회. 공개 결과·JS·artifact·로그에서 현재 키와 identity 검출0.
- 마지막으로 main의 스케줄 활성화와 Mac job 해제, 다음 실행 예정·현재 요청 수·중단 방법을 기록한다. 합성 검사와 실제 과금/배포·향후 날짜 관측을 구분한다.

## 근거와 비교

- [GitHub Secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets): step env 주입과 대용량 Secret 경계.
- [Secrets 참조](https://docs.github.com/en/actions/reference/security/secrets):48KB 제한과 repository Secret의 대기열 시점 읽기. 원장 저장소로 사용하지 않는 이유다.
- [age 공식 배포·사용법](https://github.com/FiloSottile/age): 독립 암호화 도구. 정확한 release와 Mac/Linux SHA256은 구현 계획에서 고정한다.
- [공개 표준 runner 비용](https://docs.github.com/en/billing/concepts/product-billing/github-actions): 공개 저장소의 표준 runner와 별도 storage 비용을 구분한다. runtime은 artifact/cache를 새로 사용하지 않는다.
- [workflow 간 dispatch](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/trigger-a-workflow): 단기 GITHUB_TOKEN의 workflow_dispatch 예외를 사용한다.

GnuPG는 runner에 기본 제공되지만 Mac에는 없고 초기 이관/검토 복구를 복잡하게 한다. plain budget 또는 Actions cache는 각각 기존 비공개 경계·영속 한도를 충족하지 못한다. age 도구 하나와 기존 GitHub 암호문 파일을 선택한 것은 구현자의 판단이며 사용자 승인 전 도구 설치·상태 업로드·스케줄 변경은 하지 않는다.

## 설계 검토 기록

별도 builder check가 문서를 읽고 계획에 필요한 중요한 미답 질문이 없다고 확인했다. 이 검토는 구현·암호화 실실행·키 일치·원격 예산 저장 성공의 증거가 아니다. 사용자 설계 승인 후 구현 계획·실패 재현·실제 검증을 수행한다.
