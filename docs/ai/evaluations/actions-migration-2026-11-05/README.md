# GitHub Actions 전환 검증

상태: 구현·작업 브랜치 무과금 검증 완료, 최종 리뷰·PR 준비 중. 사용자 main 머지와 최신 상태 handoff는 아직 수행하지 않았다. Mac 스케줄이 현재 실행 주체이며 cloud control은 active=false다.

## 승인 범위와 보존한 한도

사용자가 API Secret 등록 후 [설계](../../../superpowers/specs/2026-11-05-ai-actions-migration-design.md)에 `설계대로 전환 진행`으로 승인했다. 기존 누적 USD5·40요청, 하루 조사2건·주제1회, 전체 일일 시도4회, 2026-11-09 13:09:12 KST 만료를 유지한다. 추가 결제·전역 설치·agent의 main 병합은 하지 않는다.

API Secret은 ANTHROPIC_API_KEY, 상태 복호화 Secret은 BENEFIT_AI_STATE_IDENTITY다. 값은 AI 처리 step에만 주입하며 프런트 job·PR 테스트·Pages artifact에 전달하지 않는다. age v1.3.2의 공식 배포 SHA256을 고정해 프로젝트 .tools에만 설치한다. recipient와 이관 기준 해시는 공개 정책이며 private identity·API 키·평문 원장은 Git 제외600 파일에 둔다.

## 확인한 결과

- [실제 runner 검증](https://github.com/Kim-Taesu/benefit-monitor/actions/runs/41980953212): 작업 브랜치 코드55fce1e28fa1866682e899c3706983c24fa7d9f3에서 Secret fingerprint 일치, 실제 age 복호화·원장 복원·Contents 쓰기 확인 성공. check_only는 수집·Claude·공개 배포를 호출하지 않는다.
- 검증 전후 로컬·원격 API 요청30회, 실패2건의 예약을 포함한 점유106768 microUSD, usage 계산75924 microUSD. 이는 공급자 계정 전체 청구·세금 보장이 아니다.
- 이미 완료한2026-11-05 실행을1회로 이관했다. 같은 날짜의 실행은 재시도하지 않는다. 모의 제어 테스트에서 완료일 중복·실패일 중복·만료·4회·40요청·미정산·잘못된 Secret에 수집/유료 호출0을 확인했다.
- 제어 상태와 검토 자료는 기존 briefing-data의 ai-control.age·ai-runtime.age에 암호문으로 보존했다. 매 예약·정산은 Contents 파일 SHA 조건으로 원격에 저장하고 확인한다. 저장 실패 시 Claude HTTP를 보내지 않는다.
- runtime 업로드와 control pointer 갱신 사이 중단은 이전 immutable blob을 복원한다. archive는 budget/days·링크·탈출 경로·credential 파일을 복원하지 않는다. control이 항상 원장·날짜의 권위다.
- Linux runner의 Python393개·프런트52개·브라우저43개 검사가 성공했다. 이후 추가한 이관 경계와 최신 무료 수집 보류 복원 검사를 포함해 로컬 Python397개가 통과했다. 최종 HEAD 검증 결과는 별도 결과 JSON에 기록한다.

공식 조회의 robots·TLS·허용목록·HTTP75/hard cap100·구6시간 캐시·실패900초와 공개 승인·주제 의미 검사·화면 fallback은 유지한다. AI가 추출한 새 사실은 계속 비공개 사람 검토 대기다.

## 최종 전환 순서

1. 새 PR을 사용자가 main에 머지한다. agent는 main에 병합하지 않는다.
2. 작업 사본을 그 main 커밋과 일치시킨 뒤 `python3 scripts/ai_cloud_handoff.py activate`를 실행한다. 등록된 Mac job이 실행 중이면 중단하지 않고 기다린다. job 해제·enabled=false 뒤 최신 원장/날짜/검토 자료를 다시 암호화한다. 결과는 staged_requires_main_check이며 아직 cloud는 비활성이다.
3. main의 AI daily trial을 check_only=true로 실행한다. 최신 snapshot·main SHA의 검증 receipt와 요청 수·완료 날짜를 확인한다. 이 단계는 Contents 쓰기까지 검사하며 Claude 호출은 없다.
4. 동일 main에서 activate를 다시 실행한다. Mac 해제·최신 runtime/원장/날짜·main receipt가 모두 일치할 때만 cloud active=true로 변경한다.
5. AI daily trial을 check_only=false로 실행해 당일 중복 차단을 확인한다. 실제 다음 날짜의 생성·배포는 후속 관측이다. dispatch 수락과 Pages 배포 성공을 구분한다.

실패 시 로컬을 임의 재활성화하지 않는다. 원격이 더 최신일 수 있으므로 먼저 control과 예약을 대조한다. `python3 scripts/ai_cloud_handoff.py restore`는 로컬 writer가 중단된 경우에만 최신 자료를 복원하며 스케줄을 켜지 않는다. 원본 로컬 산출물은 삭제하지 않는다.

## 확인하지 않은 항목

사용자 main 머지, Mac 해제, main 최신 handoff, cloud 유료 실행, 다음 날짜의 실제 리포트는 아직 확인하지 않았다. 현재 검증 성공은 이 항목들의 완료를 뜻하지 않는다. GitHub schedule의 정시 실행·모델 사실 정확도·새 사실 자동 승인을 보장하지 않는다.
