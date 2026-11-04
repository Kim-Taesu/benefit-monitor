# Phase 0/1 실행 상태 — 2026-11-04

## Phase 0: 진단·재현 절차 완료, 실연결 달성조건 미통과

- localhost DNS 정상. mediahub.seoul.go.kr 및 www.seoul.go.kr는 gaierror Errno8.
- 실제 Python urllib로 robots 요청1회 시도 → DNS 실패, 응답0, 본문0, 재시도0.
- 실행 환경에 프록시 환경변수 없음. resolver 설정 파일 존재. 이것만으로 설정 오류나 원격 사이트 장애 원인을 단정할 수 없음.
- 현재 도구 목록에 managed environment_status 없음. `/etc/codex/network-policy.json` 없음. 네트워크 권한을 임의로 확장하거나 다른 실행 도구로 우회하지 않음.
- 신규 진단기는 TLS 기본 검증, 공식 allowlist, robots 선확인, 최대6 요청, 2MiB 제한, redirect 미추적, 재시도0, 실패15분 대기를 적용한다. 구별 목록을 수집하지 않아 운영 6시간 캐시를 변경하지 않는다.
- 성공 조건은 같은 실행에서 공식 시작 페이지와 그 페이지에서 발견한 상세 기사를 모두 읽는 것이다. 이 성공은 연결 증명이며 혜택 사실 검증 성공이 아니다.

재현 (저장소 루트):

```sh
python3 -m benefit_monitor.research_probe
python3 -m unittest discover -s tests -v
```

실행 결과는 `.tools/phase01/network-probe.json`에 저장한다. 15분 이내 실패 재실행은 요청 없이 cooldown으로 끝난다. 재개 시 네트워크가 허용된 기존 실행 환경에서 같은 명령을 실행한다. shell 제한 해제·시스템 DNS 변경·IP 직결·유료 프록시·새 서버는 해결책으로 도입하지 않는다. 현재 세션에는 네트워크 설정을 수정할 수 있는 지원 도구가 없어 연결 복구까지 완료하지 못했다.

기록: [실제 진단 JSON](network-probe.json). 테스트222개 통과(새 진단 테스트9개 포함). 모의 성공·차단 테스트와 실제 연결 성공을 구분한다.

## Phase 1: 범위·설계 문서 완료, 신규 출처 실사 대기

- 기존 설정15개 출처의 자동 수집 방식·누락 영역 정리.
- 25개 구 기사 seed와 구청/문화체육/청년1인가구/도서관평생학습 4종 확장 큐 작성.
- **확장100칸은 발견한100개 공식 출처가 아니다.** 구청2개 진입점은 기존 설정에 있고 게시판·산하기관 실사는 미완료. 나머지 URL은 지어내지 않고 null로 둠.
- 3분야 비교30칸(개발12/보류18), 조사 질문·요청 한도·채점 기준·실패 분모를 고정.
- 현재 단계에서 sources.yaml/공개 혜택/배포/키/결제 설정 변경 없음.

자료: [출처 지도](source-map.md), [비교 계획](benchmark-plan.md), [표본 등록부](case-register.csv).

Phase 1의 ‘출처별 접근 가능 여부 확인’은 Phase 0 연결 복구에 의존하므로 전체 완료로 표시하지 않는다. 다음은 공식 진입점에서 기관 연결을 확인하고 URL·robots·파서 방식·실제 접근 결과를 채우는 작업이다. 승인된 비용 정책을 유지하며 그 후 Phase2 신규 발견 시험에 들어간다.

## 추가 진단: 실행 환경 네트워크 비활성 확인

후속 진단에서 비밀정보가 아닌 실행 플래그 `CODEX_SANDBOX_NETWORK_DISABLED=1`을 확인했다. `github.com`도 동일한 DNS 오류이고, macOS `scutil --dns`는 `No DNS configuration available`을 반환했다. localhost 해석과 소켓 생성 자체는 가능했다. 외부 IP 직결이나 DNS 변경은 시도하지 않았다.

따라서 현재 실행기의 네트워크 비활성이 확인된 차단 요인이다. Mac 전체의 인터넷이나 서울시 서버가 고장났다고 판단하지 않는다. 이 세션은 네트워크 제한 상태이며 권한 확장 요청도 허용되지 않아 코드 변경만으로 복구할 수 없다. 해당 플래그를 삭제하는 것은 권한 복구 방법이 아니므로 하지 않는다.

재개 방법은 네트워크가 허용된 Codex 환경에서 같은 저장소를 열거나, 사용자 일반 Mac 터미널에서 기존 진단기를 실행하는 것이다. 새 서비스나 API 결제는 필요 없다.

```sh
cd /Users/user/personal/benefit-monitor/.maintenance/p0-source
python3 -m benefit_monitor.research_probe
```

직전 실패 후 15분 이내면 cooldown으로 종료한다. 출력 JSON의 status=passed 및 documents_read=2를 확인해야 Phase0 통과다. 다른 오류라면 그 오류를 먼저 해결한다. 이후 출처 실사도 같은 허용 환경에서 진행해야 한다. 사용자 터미널의 연결 성공만으로 이 제한된 세션의 네트워크가 복구되지는 않는다.
