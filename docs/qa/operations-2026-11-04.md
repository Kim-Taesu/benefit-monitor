# 운영 점검 — 2026-11-04 저녁 KST

## 배포 확인

https://kim-taesu.github.io/benefit-monitor/ 는 HTTP로 열리며 Vue 2.0 화면이 표시된다.
Pages JSON과 briefing-data에서 생성시각 2026-11-04T18:16:22.788925+09:00,
상태 partial, 항목 45개, run_id 41805703747을 확인했다. 표시 기한은 11월5일 00:00 KST다.
Pages 응답과 미러 Git blob SHA-1은 모두 `16c7457db3af80b505dc18ad4516bca197185d90`이고
166,472바이트로 일치한다. 390px/1440px 화면에서 가로 넘침이 없고 모바일 카드 45개를 확인했다.
마지막 수동 배포 실행은 성공했고 커밋은 8280b456a2084a1b97cd609e854008cd10eaa118이다.
https://github.com/Kim-Taesu/benefit-monitor/actions/runs/41805703747

main의 #9~#14 최신 변경을 배포했다는 뜻이 아니다. main push는 테스트만 실행한다.
현재 GitHub 커넥터에 workflow_dispatch가 없고 로컬 gh는 api.github.com에 연결되지 않는다.
최신 main 배포 및 이후 코드·데이터 동일성 확인은 미완료다. 기존 수동 workflow_dispatch 또는
정기 실행이 필요하며, 새 예약이나 배포 트리거는 만들지 않았다.

## 승인 데이터 재검증 범위

96개 승인 입력 중 10건의 공식 HTML 본문을 다시 읽어 기간·대상·요금·조건을 대조했다.
운영 공개 45건 또는 전체 승인 입력의 전수 검증은 아니다. 실제 잔량·개인 자격·신청 성공은 미확인이다.

| 공식 원문 | 대조 결과 |
|---|---|
| https://mediahub.seoul.go.kr/archives/2019849 | 독서/걷기 7일 미션과 별도 추첨 구분, 달성 시 1,000포인트 안내 보강 |
| https://mediahub.seoul.go.kr/archives/2019836 | 운행시간·교통카드·요금 대조, 주말/공휴일 미운행 보강 |
| https://mediahub.seoul.go.kr/archives/2019568 | 챌린지별 인증·선착순·포인트·예산 종료 조건 대조 |
| https://mediahub.seoul.go.kr/archives/2019606 | 배달존·최소 주문·쿠폰·상품권 환급·기간 대조 |
| https://mediahub.seoul.go.kr/archives/2019810 | 전시·공연·명상별 시간과 요금 구분 대조 |
| https://mediahub.seoul.go.kr/archives/2019823 | 투어 접수·활쏘기·사진전의 서로 다른 일정 대조 |
| https://mediahub.seoul.go.kr/archives/2019848 | 밤로그/쓰레기 공모와 별도 청년 공모의 일정·참여 방식 대조 |
| https://mediahub.seoul.go.kr/archives/2019868 | 추가 5% 페이백·기존 보유 상품권·지급일·구매/보유 한도 보강 |
| https://mediahub.seoul.go.kr/archives/2019869 | 무료 시범운영 기간·횟수·선착순·대상·휴관 대조 |
| https://yeyak.seoul.go.kr/web/reservation/selectReservView.do?rsv_svc_id=S261027144850152852 | 레진아트 11월4일 23:59 마감·회차·대상·선정·무료 조건 대조 |

이 10건만 실제 재열람 시각으로 verified_at을 갱신했다. 원문이 없어도 모든 값을 갱신하는 자동화는 없다.
SH 양천영등포 희망돌보미 공고는 기존 승인 조건에 시작일·마감시각 충돌이 남아 있어 needs_recheck=True로
보류했다. SH robots에서 해당 AI/자동 열람 에이전트에 대한 거부 규칙을 확인해 원문 재열람을 진행하지
않았으며 기존 확인 시각을 유지했다. 원문·첨부를 다시 읽었다고 주장하지 않는다.

원문은 robots를 먼저 확인하고 공개 HTTPS만 열람했다. 로컬 Python DNS가 실패하여 공개 브라우저의
동일 출처 읽기로 대체했다. 수집 코드의 UA/robots/TLS/허용 호스트/요청 예산을 변경하지 않았다.
성남 TLS·세븐일레븐 timeout·국가유산 connection은 운영 JSON에 기록된 실패이며 이번에 해결하지 않았다.

## 파서와 다음 확인

서울시 기사 9개 표본에서 div.news_detail_cont가 하나인 실제 구조를 확인했다. main/article가 없는 경우
기존 document 비교에 조회수·추천 목록이 섞였다. 정확한 호스트/기사 경로에 한정한 본문 선택과
모호한 영역의 전체 문서 대체, v3/v2 해시 전환 비교를 보강했다. 이미지/JS 조건은 여전히 감지하지 못한다.

후속: 최신 main 배포 → 이 PR 검토/승인 → 나머지 원문 및 제한 출처 검증 → 실제 사용자 10초 발견 평가.
