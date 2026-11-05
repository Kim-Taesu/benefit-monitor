# Actions 최종 전환 감사

2026-11-05 사용자 PR #18 main 머지 뒤 전환을 완료했다. 운영 코드 main은777032ac09684b5a4753f1a0972894c20dc0eec9다. agent가 main에 병합하지 않았다. [구조화된 결과](post-merge-verification.json).

| 요구사항 | 실제 확인 |
|---|---|
| 최신 상태 이관 | Mac job 해제와 enabled=false 후 원장·완료일·검토 자료를 다시 암호화했다. 준비 때의 오래된 snapshot을 활성화하지 않았다. |
| main 검증 선행 | [무과금 실행41987718272](https://github.com/Kim-Taesu/benefit-monitor/actions/runs/41987718272)의 check_passed. Secret 일치·age 복호화·Contents 저장과 최신 main receipt를 확인했다. |
| cloud 활성 | 검증 receipt·원장·날짜·runtime digest 일치 후 active=true로 전환했다. AI daily trial workflow는 active이고 표준 ubuntu-24.04 runner를 사용한다. |
| 오늘 중복 차단 | [실행41987825991](https://github.com/Kim-Taesu/benefit-monitor/actions/runs/41987825991)의 already_completed_today·종료 성공. 수집·Claude·공개 배포를 추가 실행하지 않았다. |
| 누적 한도 보존 | 로컬·원격30회, usage 계산75924 microUSD·실패 예약 포함 점유106768 microUSD. 전체 $5·40요청·일일 시도4회·2026-11-09 13:09:12 KST 만료를 유지한다. |
| 단일 실행 주체 | Mac job 미등록·로컬 enabled=false, cloud active=true. Mac을 켜둘 필요가 없다. 개인 API 키와 복호화 identity의600 로컬 사본은 보존했다. |
| 보안 | 두 main 실행의 로그 각각1개와 원격 암호문2개, Git609개 blob·tracked261개 파일에서 실제 키/private identity 및 base64 일치0. 새 runtime artifact/cache를 만들지 않았다. |
| 기존 정책 | 공식 robots·TLS·허용목록·HTTP75/hard cap100·구6시간 캐시·실패900초·사람 사실 승인·주제 검증과 기존 무료 workflow를 유지한다. |

다음 적격 실행일은11/6이다. KST06:00~23:45에15분 간격으로 점검하되, 당일 기존 main 무료 수집 완료를 기다린다. GitHub 지연·누락 때문에 정시 리포트를 보장하지 않는다. 다음 날짜의 실제 생성·공개 dispatch·Pages 배포는 아직 관측하지 않았다. 이관 검증은 실제 새로운 AI 결과의 품질 평가가 아니다.

중단하려면 Actions의 AI daily trial에서 Disable workflow를 선택한다. 이미 진행한 지출을 되돌리지는 않는다. cloud 사용 후 로컬 enabled를 임의로 다시 켜지 않는다. 필요하면 최신 원격 원장·미정산 예약을 복원·대조하고 하나의 실행 주체만 재개한다. `python3 scripts/ai_cloud_handoff.py restore`는 로컬 스케줄을 켜지 않는다.

## 구현 중 내린 판단

원래 설계와 구현 계획 사이의 판단을 순서대로 보존한다. 별도 리뷰의 Important3건은 실패 재현 후 수정했고, 남긴 Minor·판정 유보는 없다.

1. Task N 표제는 계획 추출 도구의 식별자로 유지하고 본문은 한국어로 썼다. 잘못 판단하면 진행 도구가 태스크를 읽지 못한다.
2. age fixture를 실제 공식 gzip tar 형식으로 수정했다. 다른 형식을 모의하면 실제 배포 형식 검증이 약해진다.
3. runtime은 immutable blob SHA로도 읽게 했다. pointer 갱신 전 중단됐을 때 이전 자료를 복원하기 위해서이며, 잘못되면 복구가 중단된다.
4. 예산 모듈은 optional checkpoint callback, Claude CLI는 cloud에서만 factory를 연결했다. 로컬 기본 경로를 유지하며, 연결이 누락되면 원격 예산 보호가 약해지므로 provider 호출0 실패 검사를 고정했다.
5. cloud_run에 store 주입을 테스트 경계로 허용했다. 실제 workflow는 고정 저장소+age를 사용하며, 잘못된 주입은 원격 경계 검증을 약화시킬 수 있다.
6. main 반영 전 검증은 기존 frontend-checks의 명시적 manual job을 썼다. PR에는 Secret을 주입하지 않으며, 조건이 틀리면 Secret 경계가 약해질 수 있다.
7. check_only도 snapshot/code/ref receipt를 원격에 기록한다. 읽기뿐 아니라 쓰기 권한과 최신 상태를 검증하며, 잘못되면 검증 세대가 불필요하게 바뀔 수 있지만 날짜·비용을 추가하지 않는다.
8. activate를 최신 업로드 → main check → 활성의2단계로 나눴다. 일치가 깨지면 재검증이 필요하며, 오래된 상태를 활성화하는 위험을 피한다.
9. AI 실행 전에 기존 무료 수집기의 최신 operational hold를 복원한다. 잘못된 병합은 보류를 되돌릴 수 있어 기존 병합 규칙과 최초 공개 file SHA의 CAS를 함께 사용한다.
10. Task5는 사용자 main 머지 전에는 미완료로 유지했다. 사용자 머지 후에만 Mac 해제와 최종 이관을 했으며 이 선행 조건은 이제 충족됐다. 잘못 앞당기면 운영 공백이나 두 writer가 생길 수 있다.
