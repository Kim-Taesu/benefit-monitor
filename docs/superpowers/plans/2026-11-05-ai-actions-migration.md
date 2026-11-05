# AI Actions 전환 구현 계획

> **실행 담당자:** superpowers:executing-plans로 현재 세션에서 태스크별 실행한다. 사용자에게 설계대로 진행 승인을 받았다. 구현 병렬 위임은 하지 않는다.

**목표:** 키를 GitHub Secrets에서 주입하고 기존 영속 한도·검토 자료·중복 차단을 보존하는 Mac 독립 일일 실행을 만든다.

**구조:** 기존 일일 수집·검토·주제·공개 검사를 재사용한다. age 암호문 control/runtime을 기존 briefing-data에 저장하고, control을 매 비용 예약 전에 원격 확정한다. 로컬은 최종 handoff 전까지 운영을 유지한다.

**기술:** Python 표준 라이브러리, 프로젝트 내부 age1.3.2, 기존 GitHub CLI·표준 Ubuntu24.04 Actions·Pages.

**설계:** [승인한 설계](../specs/2026-11-05-ai-actions-migration-design.md).

## 공통 제약

- 누적 $5·40요청·하루 조사2/주제1·전체 일일 시도4·2026-11-09 13:09:12 KST 만료를 유지한다. 현재30요청·점유106768microUSD·기존 실패 예약을 초기화하지 않는다.
- 기존 개인 저장소·작업 브랜치만 사용하며 main은 사용자가 머지한다. 새 유료 서비스·전역 설치·worktree 생성은 하지 않는다.
- 공개 Git/cache/artifact에 키·복호화 identity·평문 원장·검토 대기를 넣지 않는다. 알려진 키 값은 출력하지 않는다.
- 원격 control 누락·손상·저장 실패·reserved 잔존은 유료 중단이다. runtime보다 control이 우선한다.
- 공식 조회 HTTP·robots·TLS·캐시·쿨다운과 사람의 사실 승인·현재 공개 gate를 유지한다.
- 논리 변경 후 `TMPDIR="$PWD/.tools/tmp" python3 -m unittest discover -s tests -v`를 수행한다.

## 중점 검토

1. 비용 예약 원격 저장 직후 프로세스가 죽어도 .sent 부재 때문에 재전송하지 않아야 한다 — 태스크2/3.
2. 자식 Claude 프로세스가 갱신한 최신 budget을 부모의 오래된 control이 덮어쓰면 안 된다 — 태스크2.
3. GitHub snapshot/암호문이 같은 branch에서 동시에 바뀌어도 file SHA 충돌을 무시하면 안 된다 — 태스크2.
4. archive의 budget/days·symlink·개인 키 경로가 최신 control/프로젝트 경계를 덮어쓰면 안 된다 — 태스크1/2.
5. 구현 전 오래된 로컬 상태를 올려 활성화하거나 Mac/cloud를 동시에 켜면 안 된다 — 태스크4/5.

### Task 1: 프로젝트 내부 암호화 도구와 검증된 archive

**파일:** 새 `scripts/install_age.py`, `benefit_monitor/age_state.py`, `tests/test_age_state.py`. 승인 예외를 `AGENTS.md`에 반영.

**인터페이스:** install(root:Path, platform_name:str, machine:str)->Path; AgeState(root:Path, identity:Path), encrypt(raw:bytes)->bytes, decrypt(cipher:bytes)->bytes; pack_runtime(root:Path)->bytes, restore_runtime(root:Path, raw:bytes)->None. identity 파일은 Git 제외·600이며 외부 경로와 링크를 거절한다.

- [x] 거절 테스트: 잘못된 archive digest·지원하지 않는 플랫폼·symlink·경로 탈출·금지된 credential 경로·크기 초과를 거절한다. restore는 budget/days를 복원하지 않는다.
- [x] 위 테스트를 실행해 미구현 실패를 확인한다.
- [x] age1.3.2 공식 release만 허용한다. darwin-arm64 SHA256 `e2020b073c44f692685a24d6abc378817eb81ffaaf49fd0531ef8565f767f2f5`, linux-amd64 `cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10`. 다운로드32MiB·압축해제128MiB 한도와 정확한 binary 파일2개만 허용한다. Mac 전역 설치는 하지 않는다.
- [x] 로컬 프로젝트에 설치하고 실제 임시 identity의 roundtrip·변조·잘못된 identity 거절을 확인한다. stdout/env로 private identity를 출력하지 않는다.
- [x] 관련 테스트·전체 Python 검사 후 태스크를 커밋한다.

### Task 2: 암호문 영속 control과 예약 checkpoint

**파일:** 새 `benefit_monitor/cloud_state.py`, `tests/test_cloud_state.py`; 수정 `benefit_monitor/trial_budget.py`.

**인터페이스:** GitHubStateStore(root:Path, token:str, crypto:AgeState, opener=None), read(kind:str)->tuple[bytes,str], write(kind:str, raw:bytes, expected_sha:str|None)->str. 허용 파일은 ai-control.age/ai-runtime.age, 저장소·branch는 고정한다. CloudSession.restore/mark_day/checkpoint_budget/finish은 원격 SHA와 최신 로컬 context를 관리한다. TrialBudget은 cloud context가 명시된 경우 변경 트랜잭션만 checkpoint한다.

- [x] 가짜 원격 테스트: 저장 실패 후 provider 호출0, 두 writer의 stale SHA 거절, 최신 자식 budget 보존, control 부재/손상/다른 cap·모델 거절, runtime이 budget/day를 덮어쓰지 않음을 고정한다.
- [x] 미구현 실패를 확인한다.
- [x] GitHub HTTPS API에만 인증을 보내고 redirect를 따르지 않는다. ciphertext1MiB·응답2MiB 한도, JSON/base64와 blob SHA를 검증한다. control은 budget·days·trial 식별자·active·generation을 포함하고 이전 상태를 자동 재생성하지 않는다.
- [x] `_locked`에서 원본 상태와 비교해 변경 시만 로컬 fsync 후 원격 저장한다. 읽기는 업로드하지 않는다. hook 오류 시 예약/정산을 성공으로 반환하지 않는다.
- [x] 모든 회귀 검사 후 커밋한다.

### Task 3: cloud 키·일일 제어·공개 전달

**파일:** 새 `benefit_monitor/cloud_daily.py`, `tests/test_cloud_daily.py`; 수정 `benefit_monitor/claude_trial.py`, `tests/test_claude_trial.py`.

**인터페이스:** configured_key(root:Path)->str, cloud_run(root:Path, now=None, check_only=True)->dict. cloud mode는 명시적 env와 저장소/이벤트 검증을 요구하며 기본 로컬 loader는 바꾸지 않는다. 공개 전달은 고정 snapshot/code SHA로 기존 briefing-pages workflow를 dispatch한다.

- [x] cloud 환경키·누락·금지된 event/repository·잘못된 fingerprint·reserved/halting·만료·이미 처리한 날을 테스트한다. 과금 함수를 모의해 모두 호출0임을 검증한다.
- [x] 미구현 실패를 확인한다.
- [x] 최신 control을 복원한 다음에만 검사를 시작한다. 당일 main 정기 작업 미완료면 mark_day 전 대기한다. inner daily가 자기 로컬 day를 기록하기 전 control의 당일 시도를 먼저 원격 확정하되, inner daily에 사전 attempted를 넣어 스스로 차단하지 않도록 분리한다.
- [x] 기존 daily를 재사용해 수집·AI·공개 export를 처리한다. 개인 OAuth 사용자 API 대신 단기 GITHUB_TOKEN의 해당 저장소 contents/actions 권한만 사용한다. 원격 archive/control을 완료 처리할 때 최신 context budget을 다시 읽는다.
- [x] 실제 환경키를 출력하지 않고 공개 payload·로그에 포함되면 거절한다. 실패 시 이전 검토·예약을 유지한다. 실제 Claude 호출 없이 회귀 검사 후 커밋한다.

### Task 4: trusted workflow와 안전한 handoff 도구

**파일:** 새 `.github/workflows/ai-daily.yml`, `scripts/ai_cloud_handoff.py`, `tests/test_ai_cloud_handoff.py`; 기존 workflow는 snapshot 공개 인터페이스를 유지한다.

**인터페이스:** handoff prepare/check/activate/restore 명령은 개인 계정·고정 저장소·원장·등록된 job을 검사한다. Secret 생성·등록은 기존 개인 gh 설정과 stdin만 사용한다. 설계 승인으로 추가 identity Secret1개를 허용한다.

- [x] handoff 전 로컬 실행 보존, active cloud 이관 시 로컬 해제 선행, 오래된 snapshot 활성화 거절, 원장 기준 불일치·예약 잔존 거절을 테스트한다.
- [x] 미구현 실패를 확인한다.
- [x] workflow는 기본 branch schedule와 trusted dispatch만 허용한다. 매15분 KST06~23:45 점검, concurrency 하나, cancel-in-progress=false. 공개·무료 확인을 유지한다. 설치/checkout 단계에는 AI Secret을 주입하지 않는다.
- [x] contents:write/actions:write는 해당 job만 사용한다. 만료/실행 한도 도달 시 자기 workflow만 disable하며 실패해도 프로그램 gate는 유지한다. 개인 장기 token은 runner에 전달하지 않는다.
- [x] check_only 실제 branch dispatch에서 Secret fingerprint·복호화·이관된30요청/실패예약·11/5 중복 차단·storage 권한을 확인한다. 아직 로컬을 끄지 않는다.
- [x] 전체 검사·실제 무과금 cloud 검증 후 커밋한다.

### Task 5: 문서·PR·사용자 머지 뒤 최종 전환

**파일:** `README.md`, `docs/ai/automation.md`, 새 migration 결과 JSON/감사 문서. 기존 frozen 증거는 수정하지 않는다.

- [x] 전체 unittest·출처 정책·diff·현재 frontend CI를 확인하고 설계 범위 리뷰를 수행한다. 키/identity를 실제 값 메모리 대조로 공개 이력·로그·artifact에서 검사한다.
- [x] 기존 branch의 새 PR을 작성해 누적 한도와 crypto 도구, 아직 로컬 활성 상태, 사용자 main 머지 필요를 명시한다. 자동 main 병합은 하지 않는다.
- [x] 사용자 머지 후 로컬 실행 중 여부 확인·job 해제·enabled=false·최신 상태 암호화/업로드·cloud active 전환을 순서대로 수행한다. 이때 실패하면 두 환경 동시 재개를 막고 최신 control 확인 후에만 복구한다.
- [x] 실제 main cloud 첫 실행의 복원·당일 중복 차단·API30회 유지·등록된 스케줄·Mac 해제를 확인한다. 확인된 배포와 dispatch를 구분해 기록한다. 다음 날 관측은 후속으로 남긴다.

## 자체 검토

설계의 Secret 주입·암호화·원장 예약·runtime 보존·후행 main 배포·4회/만료·자식 프로세스·handOff/복구를 태스크1~5에 대응했다. 외부 Python 패키지·새 서비스·전역 설치·agent main 머지는 포함하지 않는다. API key 값은 실행 인자나 문서에 포함하지 않는다. 태스크는 현재 세션에서 순차 실행하며 사용자에게 실행 방법 재선택을 요구하지 않는다.
