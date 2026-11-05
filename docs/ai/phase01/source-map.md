# 출처 조사 지도

설정과 실제 접속 성공은 별개다. 2026-11-05 실제 접근 실사를 진행했다. 문서 열람과 실제 파서 수집·혜택 조건 검증은 구분한다. 신규 도메인은 운영 허용목록에 추가하지 않았다.

## 기존 출처 15개

| 출처 | 현재 수집 | 실제 범위 / 미수집 영역 |
|---|---|---|
| 서울시 (`seoul`) | html_links | 공식 목록의 제목·URL 후보 |
| 강서구 (`gangseo`) | district_news | 서울시 공식 자치구 뉴스 첫 페이지 · 구청 공지 전체 수집 아님 |
| 은평구 (`eunpyeong`) | district_news | 서울시 공식 자치구 뉴스 첫 페이지 · 구청 공지 전체 수집 아님 |
| 성남시 (`seongnam`) | rss | 피드 제목·URL 후보 |
| 정부 (`government`) | html_links | 공식 목록의 제목·URL 후보 |
| 문화·예약 (`culture`) | html_links | 서울 공공서비스예약 첫 화면 공개 목록 · 잔여석·예약 성공 미확인 |
| KT (`kt`) | manual_only | 자동 수집기 없음 |
| 마트 (`retail`) | html_links | 신세계그룹 공식 이마트 뉴스 · 홈플러스 전단 자동 수집 미연결 |
| 편의점 공식 제휴 (`convenience`) | html_links | CU 공식 제휴 멤버십 안내 · 다른 편의점·앱 전용 행사 미포함 |
| 서울시 평생학습포털 (`seoul_lifelong`) | html_links | 평생학습포털 첫 화면 공식 이벤트 · 강좌 전체 수집 아님 |
| 세븐일레븐 공식 제휴 (`seven`) | html_links | 세븐일레븐 공식 카드 제휴 · 이미지 행사·앱 잔량 미포함 |
| 이마트24 공식 제휴 (`emart24`) | html_links | 공식 제휴 서비스 안내 · 행사 전체·앱 잔량 미포함 |
| SH 주택 공고 (`sh`) | sh_notice | SH 주택임대·분양 공고 게시판 첫 페이지 · 제목 기준 후보, 신청 자격·접수 상태 미확인 |
| 공유누리 공공시설 (`eshare`) | eshare | 공유누리 서울 인터넷 예약 자원 검색 첫 페이지 · 이용료 제한 없음 · 실시간 예약 가능 여부 미확인 |
| 국가유산 행사 (`heritage`) | heritage_events | 국가유산청 월별 행사 공개 목록(이번 달·다음 달, 서울) · 행사별 예약·잔여석 미확인 |

## 25개 구 확장 큐

각 구에 ①구청 공지 ②문화·체육 ③청년·1인가구 ④도서관·평생학습의 4개 조사 칸을 만들었다. **100칸은 발굴 작업 수이며 검증된 100개 출처가 아니다.** 구별 기관 수와 명칭은 실제 공식 링크 확인 후 확정한다.

| 구 | 기존 조사 | 구청 진입점 | 산하 시설 3분야 |
|---|---|---|
| 종로구 | 서울시 기사 첫 페이지 | [https://www.jongno.go.kr](https://www.jongno.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 중구 | 서울시 기사 첫 페이지 | [https://www.junggu.seoul.kr](https://www.junggu.seoul.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 용산구 | 서울시 기사 첫 페이지 | [https://www.yongsan.go.kr](https://www.yongsan.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 성동구 | 서울시 기사 첫 페이지 | [https://www.sd.go.kr](https://www.sd.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 광진구 | 서울시 기사 첫 페이지 | [https://www.gwangjin.go.kr/portal/main](https://www.gwangjin.go.kr/portal/main) · 200 오류 페이지·성공 미산입 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 동대문구 | 서울시 기사 첫 페이지 | [https://www.ddm.go.kr](https://www.ddm.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 중랑구 | 서울시 기사 첫 페이지 | [https://www.jungnang.go.kr](https://www.jungnang.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 성북구 | 서울시 기사 첫 페이지 | [https://www.sb.go.kr/www/index.do](https://www.sb.go.kr/www/index.do) · 실제 문서 열람 | 실제 연결 확인4/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 강북구 | 서울시 기사 첫 페이지 | [https://www.gangbuk.go.kr/](https://www.gangbuk.go.kr/) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 도봉구 | 서울시 기사 첫 페이지 | [https://www.dobong.go.kr/default.asp](https://www.dobong.go.kr/default.asp) · 실제 문서 열람 | 실제 연결 확인4/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 노원구 | 서울시 기사 첫 페이지 | [https://www.nowon.kr](https://www.nowon.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 은평구 | 서울시 기사 첫 페이지 | [https://www.ep.go.kr](https://www.ep.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 서대문구 | 서울시 기사 첫 페이지 | [https://www.sdm.go.kr/](https://www.sdm.go.kr/) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 마포구 | 서울시 기사 첫 페이지 | [https://www.mapo.go.kr](https://www.mapo.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 양천구 | 서울시 기사 첫 페이지 | [https://www.yangcheon.go.kr](https://www.yangcheon.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 강서구 | 서울시 기사 첫 페이지 | [https://www.gangseo.seoul.kr/index](https://www.gangseo.seoul.kr/index) · 기존 관측 본문 캐시 재사용 | 실제 연결 확인4/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 구로구 | 서울시 기사 첫 페이지 | [https://www.guro.go.kr/www/mini.do](https://www.guro.go.kr/www/mini.do) · 실제 문서 열람 | 실제 연결 확인2/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 금천구 | 서울시 기사 첫 페이지 | [https://www.geumcheon.go.kr](https://www.geumcheon.go.kr) · 실제 문서 열람 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 영등포구 | 서울시 기사 첫 페이지 | [https://www.ydp.go.kr](https://www.ydp.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 동작구 | 서울시 기사 첫 페이지 | [https://www.dongjak.go.kr](https://www.dongjak.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 관악구 | 서울시 기사 첫 페이지 | [https://www.gwanak.go.kr](https://www.gwanak.go.kr) · 차단·정책·오류 기록 | 실제 연결 확인0/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 서초구 | 서울시 기사 첫 페이지 | [https://www.seocho.go.kr/site/seocho/main.do](https://www.seocho.go.kr/site/seocho/main.do) · 실제 문서 열람 | 실제 연결 확인4/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 강남구 | 서울시 기사 첫 페이지 | [https://www.gangnam.go.kr/main.do](https://www.gangnam.go.kr/main.do) · 실제 문서 열람 | 실제 연결 확인4/4칸, 기관별 접근·파서 검증은 상태별 기록 |
| 송파구 | 서울시 기사 첫 페이지 | [공식 메인](https://www.songpa.go.kr/www/index.do) · 회차3에서 요구 간격 이후 재열람 | 새 관측으로 연결4/4칸 확보; 하위 기관 접근·파서는 미검증 |
| 강동구 | 서울시 기사 첫 페이지 | [https://www.gangdong.go.kr/newportal/](https://www.gangdong.go.kr/newportal/) · 실제 문서 열람 | 실제 연결 확인4/4칸, 기관별 접근·파서 검증은 상태별 기록 |

## 확장 우선순위

1. 은평·강서: 이미 설정된 구청 진입점에서 공지·시설 링크를 확인하고 기존 관심 지역과 비교한다. 이것을 서울 전체 대표 표본으로 취급하지 않는다.
2. 나머지 구는 districts.json 순서로 순환 조사한다. 이전 조사량이 적은 구를 먼저 배정해 편중을 기록한다.
3. 문화·운동은 공공서비스예약/평생학습/국가유산 + 구 산하 시설, 장보기·멤버십은 KT/CU/세븐/이마트24/공식 마트, 청년·1인가구는 구청/청년시설/SH/공유누리를 시작점으로 삼는다.
4. 기업 전국 혜택은 서울 이용 가능 여부를 확인한다. 로그인 전용·앱 전용·이미지/첨부 미판독 자료는 미확인으로 남긴다.
5. 신규 출처 등록 전 운영 주체, 공식 상호 링크, robots, 자동 접근 조건, 개인정보 포함 여부, 파서 방식, 갱신 계획, 실패 처리, 사람 검토자를 기록한다. 접근 가능하다고 재배포 권한까지 인정하지 않는다.

기계 판독 자료: [기존 출처](source-inventory.json), [25개 구 지도](district-map.json).

## 2026-11-05 접근 실사 결과

[실제 요청 기록](source-audit-2026-11-05.json)에 robots·실패·상한 초과를 포함했다. 기존 출처15개 중 최초 시작 문서 열람11개·차단4개, 후속 강서구 메인 확인 후 열람12개·차단3개다. 200 응답만으로 수집 성공이나 혜택의 현재 유효성을 판정하지 않는다. 공유누리는 검색 초기 화면, 국가유산은 날짜 인자 없는 XML까지 읽었으므로 운영 조회 전체를 검증한 것이 아니다.

| 출처 | 실제 시작 문서 | 결과·남은 범위 |
|---|---|---|
| seoul | `https://mediahub.seoul.go.kr/news/newsMain.do` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| gangseo | `https://www.gangseo.seoul.kr/` | redirect_not_followed: destination needs separate policy review |
| eunpyeong | `https://www.ep.go.kr/` | robots 차단 |
| seongnam | `https://snvision.seongnam.go.kr/rss/rss_news.php` | <urlopen error [SSL: SSLV3_ALERT_HANDSHAKE_FAILURE] ssl/tls alert handshake failure (_ssl.c:1082)> |
| government | `https://www.korea.kr/news/policyNewsList.do` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| culture | `https://yeyak.seoul.go.kr/web/main.do` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| kt | `https://membership.kt.com/` | The read operation timed out |
| retail | `https://www.shinsegaegroupnewsroom.com/family/emart/` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| convenience | `https://cu.bgfretail.com/service/membership_info.do?category=service&depth2=2&depth3=1` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| seoul_lifelong | `https://sll.seoul.go.kr/` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| seven | `https://www.7-eleven.co.kr/product/cardInfo.asp?gbn=2` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| emart24 | `https://emart24.co.kr/service/alliance` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| sh | `https://www.i-sh.co.kr/app/lay2/program/S1T294C297/www/brd/m_247/list.do?multi_itm_seq=2` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| eshare | `https://www.eshare.go.kr/UserPortal/adv/unifdSearch/UnifiedSearchMainView.do` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |
| heritage | `https://www.khs.go.kr/cha/openapi/selectEventListOpenapi.do` | 문서 열람; 상세 조건·전체 목록 수집은 별도 검증 |

25개 구청의 진입점은 서울시 [공식 메인](https://www.seoul.go.kr/main/index.jsp)의 자치구25 목록에서 확보했고, 원문 해시를 district-map.json에 기록했다. 이는 각 구청25개 또는 확장100칸의 접근·기관 실사 완료가 아니다. 강서·은평 외23개 구청은 미요청이다. 신규 도메인의 robots·상호 연결·공개 접근 조건 검토 후 조사용 허용목록을 별도로 기록해야 하며 운영 sources.yaml 자동 확장은 하지 않는다.

갱신·우선순위는 source-inventory.json에 유지했다. robots 차단은 대기시간 만료만으로 허용되지 않는다. TLS 오류·시간초과·리다이렉트·2 MiB 초과 자료는 우회하지 않고, 같은 호스트에 실패15분 대기를 적용했다. 구별 운영 목록의6시간 캐시는 읽기만 했으며 갱신하지 않았다.

후속 강서구 조사: `/index` 실제 열람 성공. 공지 `/gs040101`은 robots 차단으로 요청0회, `/munhwa`는302 목적지 `/munhwa/index`를 기록하고 추적0회로 중단했다. 현재 누적60/60으로 이 회차를 종료했다. 강서구의 네 분야 진입점은 실제 메인 링크에서 확보했으며 청년·평생학습 하위 페이지는 미요청이다.

## 구청 별도 실사 회차2

[회차2 원장](district-access-r02.json)에25개 구의 robots·TLS·공식 진입점 결과를 기록했다. 허용 증거의 문서 열람7개·기존 강서구 본문 캐시 재사용1개·차단15개·200 오류 페이지1개·이동 안내만1개다. 송파 메인은 요청 간격 위반으로 격리했다. 일부 루트200은 이동 안내만 있었으므로 HTML에 명시된 목적지를 별도 정책 검토 후 읽었으며 JavaScript나 인증용 쿠키를 실행하지 않았다. 접근 거부·인증서 오류·HTML로 반환된 robots·리다이렉트는 정상 목록과 구분했다.

실제 구청 본문에서 기관·영역 연결30/100칸을 관측했으나 송파구 파생4칸을 격리해 현재 허용 증거는26/100칸이다. 같은 호스트의 robots 허용 경로라도 대상 본문을 미열람이면 `linked_policy_allowed_not_read`, 다른 기관 도메인은 `new_domain_review_pending`으로 남겼다. 차단된 부모 페이지에서 기관 이름·URL을 추정하여 채우지 않았다. 수집 방법·갱신·우선순위는 구별 지도 각 출처에 명시했다.

입력 표본30칸(개발12/보류18)은 [해시 잠금 자료](../evaluations/phase234-2026-11-05/case-pool-manifest.json)에 기록했다. 실제 대상 문서16개와 목록 원문만 확보한14개를 구분하므로 표본 상세 조사가 완료된 것으로 표시하지 않는다. 장보기 표본의 같은 브랜드는3개 이하이며 같은 행사 홍보·신청을 별도 표본으로 중복 세지 않았다.

회차2는 송파구3600초 Crawl-delay를128.520846초 간격으로 어겨 운영 검증 실패다. 해당 본문·파생 연결은 격리했으며 다음 적법한 관측 전 달성조건 근거로 쓰지 않는다. [사건과 교정](status.md)에 실패와 새 제어 테스트를 구분해 기록했다.

## 회차3 후속 관측

[회차3 원장](document-access-r03.json)은39/60요청·전체 누적159회다. 먼저 수집해 둔 상세14개를 포함해 잠근 입력30개의 대상 HTML을 모두 확보했다. 이미지·신청 약관·실제 자격을 모두 검증했다는 뜻은 아니다. 입력 원문 해시는 유지하고 후속 상세를 별도 문서로 추가했다.

송파 메인을2026-11-05 01:38:44 KST에 새로 읽었다. 이전 본문 요청 이후3672.988926초로3600초 요건을 충족했다. 같은 원문 해시라도 새 적법한 요청 시각을 근거로 연결4칸을 다시 확인했으며 현재 연결 근거는30/100칸이다. 과거 회차2 위반·격리 기록은 그대로 남긴다. 나머지70칸과 연결 기관 자체의 정책·본문·파서는 미완료다.

기존 허용 기업 뉴스룸에서 이마트24 보도자료3개를 추가 판독했다. 기존 운영 파서의 이마트 영역과 다른 범위이며 운영 설정을 확장하지 않았다. [비용·기간·결제조건과 미확인 사항](../evaluations/phase234-2026-11-05/commercial-followup.md)을 구분해 기록했다. 앱·로그인·결제는 실행하지 않았다.

## 서울시 공식 프로그램 경로의 추가 지도

구청 메인이 차단된 경우에도 이미 허용된 서울시 공공서비스예약의 해당 지역 프로그램 문서는 별도로 확보했다. [구별 지도](district-map.json)의 `additional_official_program_sources`16개 문서를13개 추가 칸에 연결했다. 기관 홈페이지 연결30칸과 별도로 공식 프로그램 문서13칸을 확보했으며,57칸은 아직 출처 미확인이다. 프로그램 주소·운영기관 근거로만 구를 연결하고 구청 산하 기관 소유라고 확대하지 않았다. 각 문서의 접근·방식·갱신·우선순위를 기록했다.

이 추가는 네트워크 요청 없이 이미 확보한 공식 본문을 출처 지도에 반영한 것이다. 구청 차단을 우회하거나 기관 홈페이지43개를 검증한 결과가 아니다. 전체100칸은 조사 큐이며 사용자가 요구한100개 수집기 또는100개 접근 성공 목표가 아니다. 미확인 칸과 자동 파서 범위는 계속 공개한다.

회차3 기관 하위 실사 후 현재44/60회·누적164회다. 성북구1인가구·대학도서관/박물관목록2개를추가열람했다. 도봉은302및실패대기, 강서는비정상형식robots의Crawl-delay판독실패로추가요청을보류했다. [개별결과](institution-access-r03.json)를따르며과거성공본문을현재허용근거로대체하지않는다.

## 공식 센터 디렉터리 후속 확인

[서울청년센터17개 항목](facility-directory-r03.json)을 목록2페이지에 걸친 전체18개 보기로 실제 확보했다. 새로 근거를 얻은7칸을 포함해 현재 기관홈연결30·공식프로그램13·공식디렉터리7·미확인50칸이다. 강서 센터 소개도 별도 열람했으나 다른16개 소개·프로그램 전체를 읽었다고 표시하지 않는다.

서울도서관 공식 루트는 읽었으나 도서관 찾기 응답은2MiB를 넘어 중단했다. 공원 연결은404, 박물관은TLS 실패였다. [현재 원장](document-access-r03.json)은54/60회·누적174회이며 [네트워크 정책 재대조](network-policy-audit-r03.json)와 구분해 기록한다.
