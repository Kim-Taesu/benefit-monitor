# read_only_research 시험 기록

- 입력: `live-input.json`; 후보 ID `553a6c9f04a25c7f30e5944d`, source ID `seoul`.
- 대상: 청계 A01 무료 야간 자율주행버스. 제목은 호스트 입력이며 조사로 확인한 사실이 아니다.
- 읽은 작업 지침: `AGENTS.md`, `docs/ai/README.md`, `execution.md`, `research.md`, `output-contract.md`, `prompts.md`, `sources.yaml`의 seoul 출처 설정. 이전 대화·평가 결과는 열지 않았다.
- 조사 질문: 현재 운영일·시간·노선은 무엇인가? 탑승 방법과 이용 제한은 무엇인가? 이용료 및 적용 조건은 무엇인가? 모두 미확인이다.
- 최초 대상: https://mediahub.seoul.go.kr/robots.txt. 원문 접근 허용 확인을 위해 먼저 요청을 준비했다.
- 관측 시각: 2026-11-04T13:51:15.551675+00:00. DNS 해석이 `gaierror: [Errno 8] nodename nor servname provided, or not known`으로 실패했다.
- 예산: 전체 10회 중 시도 전 1회 차감, 잔여 9회. 실제 HTTP 전송 0회, HTTP 성공 0회, 본문 읽기 0건, 보조 문서 0건, 재시도 0회, 외부 LLM API 0회.
- TLS 검증 기본 SSL context 및 리다이렉트 거부 opener를 구성했으나 DNS 단계에서 중단되어 TLS 연결은 이루어지지 않았다. 익명 Python 표준 라이브러리만 사용했다.
- robots 내용을 받지 못해 허용 여부를 판단할 수 없다. 원문 및 다음 링크를 읽거나 선택하지 않았다. 첫 DNS/전송 오류 시 같은 호스트 중단 조건에 따라 우회·대체 도구·재시도를 수행하지 않았다.
- 결과: `blocked`, `environment_unavailable`, `records=[]`. 실제 조사 성공이나 부분 본문 확인으로 계산할 수 없다. 확인된 운영 사실·자격·잔여석·비용 정보는 없다.
- 관측 파일: `evidence/robots.json`, `evidence/requests.json`. 실제 읽은 응답 본문이 없어 본문 파일이나 해시는 생성하지 않았다.
- 로컬 실행기에서 `python` 명령을 찾지 못해 네트워크 없이 종료된 뒤 `python3`로 조사 명령을 실행했다. 이는 HTTP 재시도가 아니다.
- 운영 코드·scripts·승인 데이터는 수정하지 않았다. 논리 변경이 없어 unittest 실행 대상이 아니다.
- 추가 유료 서비스·구매·예약·신청을 사용하지 않았다. ChatGPT/Codex 자체 및 사용자의 기존 컴퓨팅·구독 가격은 이 프로젝트에서 보장하지 않는다.
