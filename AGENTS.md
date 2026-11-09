# Project instructions

- Work only in ~/personal/benefit-monitor. Do not create project files elsewhere or create worktrees.
- Zero additional service spending is a strict user requirement. Never use paid APIs, LLM API calls, subscriptions, trials needing payment details, paid search/browser/SaaS, paid schedulers, paid hosting, or provision cloud resources.
- Do not request or use payment credentials or turn on billing. Never execute purchases, reservations, or benefit applications.
- Use Python standard library, anonymous public official HTTPS pages and local files only.
- Keep HTTP request budget <=100 (default 60). Respect robots, TLS, source allowlists, 6-hour district caches and failure cooldowns. Do not bypass access controls.
- Project cannot guarantee the pricing of ChatGPT/Codex or the user's existing compute/subscription. State that boundary accurately.
- Confirmed facts, application eligibility, remaining inventory and fee status must stay distinct. Never invent dates or mark partial coverage complete.
- Run python -m unittest discover -s tests -v after logic changes.

- "Free" is a requirement for briefing research, generation, infrastructure and delivery costs. It is NOT a filter requiring benefits, events, programs or recruitment to be free.
- Include verified paid events, discounts, purchases with savings, refunds and rewards when relevant. State participation cost, minimum spend, payment/eligibility conditions and uncertain fees explicitly.
- Never prefer or exclude a benefit solely because of fee_status. Keep paid infrastructure integrations forbidden.

## 승인된 Claude 일회 실험 예외 — 2026-11-05

사용자가 Claude API $5 결제와 로컬 키·계정 지출한도 설정 완료를 명시했다. 위 무료 원칙의 예외는 `benefit_monitor.claude_trial`을 통한 Anthropic 일회 실험에 한정한다. 전체 날짜·재시작·조사·주제 호출을 합친 누적 한도는 USD5이며 매일 초기화하지 않는다. `api.anthropic.com`의 모델 목록과 Messages 인증 호출만 허용한다. 공식 문서에서 단가를 확인한 Claude Haiku5.5로 시작하며 더 비싼 모델로 자동 전환하지 않는다.

Python 표준 라이브러리만 사용한다. 키는 Git 제외·600 권한의 `.env.claude`에서 프로그램이 읽고 대화·로그·공개 산출물에 노출하지 않는다. 요청 전에 영속 원장에 비용을 예약하고 실패·usage 미확인은 예약을 유지한 채 중단한다. 계정 $5 한도와 로컬 원장을 함께 사용하며 로컬 추정만으로 공급자 청구액을 보장한다고 주장하지 않는다.

공식 혜택 조회의 익명 HTTPS·허용목록·robots·6시간 캐시·실패 대기·HTTP 예산과 기존 무료 수집기의 기본 금지는 유지한다. 유료 검색·브라우저·다른 공급자·추가 충전·정기 지출·클라우드·스케줄·배포·공개·자동 신청/구매·main 병합은 이 예외에 포함하지 않는다. 일별 카드 판단은 우선 비공개 연속 스냅샷 실험으로 검증한다.

## 승인된 4일 한정 활성화 예외 — 2026-11-05

사용자는 [활성화 검토안](docs/ai/evaluations/goal-integration-2026-11-05/activation-review.md)을 제시한 승인 요청에 `ok`로 응답했다. 기존 누적 $5·40요청 안에서 하루 조사 최대2건·주제1회, 일일 실행 최대4회와 실제 검증 최대1회, 활성화 후4일 만료를 허용한다. 한도 초기화·추가 충전은 금지한다. 새 AI 사실은 비공개 사람 검토 대기에만 저장하며, 기존 승인·유효 사실에 한한3개 분류 편집 정책의 공개 카드 갱신을 허용한다.

개인 GitHub 계정 `Kim-Taesu`와 공개 저장소 `Kim-Taesu/benefit-monitor`만 사용한다. 기존 작업 브랜치 `docs/ai-research-playbook`의 양쪽 이력을 보존하는 결합·커밋·일반 push, 기존 `briefing-data` 공개 JSON 반영, 기존 Pages 환경에 작업 브랜치 허용 추가와 workflow 실행을 허용한다. 전역 계정 전환·강제 push·main 병합·새 자원·과금 설정 변경은 금지한다.

프로젝트 밖 경로 예외는 `/Users/user/Library/LaunchAgents/com.benefit-monitor.ai-daily.plist` 한 파일 설치·등록·해제에 한정한다. 다른 전역 파일·회사 계정·서비스·인증정보는 접근하지 않는다. 로그·상태·임시 파일·키·원장은 프로젝트 내부에 둔다. 실제 활성화 시각·만료시각·검증 결과를 기록한다.

## 승인된 GitHub Actions 전환 예외 — 2026-11-05

사용자는 API Secret 등록 후 [전환 설계](docs/superpowers/specs/2026-11-05-ai-actions-migration-design.md)에 `설계대로 전환 진행`으로 승인했다. 기존 누적 비용·요청·4회 일일 시도·만료를 유지하며 GitHub Actions의 필요한 AI step에만 ANTHROPIC_API_KEY를 주입한다. Python 외부 패키지는 추가하지 않는다. 암호화에 한해 공식 release와 SHA256을 고정한 age 명령행 도구를 프로젝트 .tools 안에 설치하고, 복호화 identity를 Git 제외600 파일과 BENEFIT_AI_STATE_IDENTITY Secret에 저장하는 예외를 허용한다. 전역 설치는 금지한다.

기존 briefing-data에 control/runtime 암호문만 저장하며 평문 원장·검토 대기·키는 Git/cache/artifact에 공개하지 않는다. 비용 예약은 Claude 전송 전에 원격에 영속 저장하며 손상·누락·미정산·저장 실패를 초기화나 재전송으로 바꾸지 않는다. 기존 개인 인증은 Secret 설정에만 쓰고 runner는 해당 저장소의 단기 GITHUB_TOKEN만 사용한다. main은 사용자가 머지한다. 실제 main 검증·최신 상태 handoff 전까지 로컬 스케줄을 유지하고, 최종 전환 시 기존 지정 job을 해제해 중복 실행을 막는다.

## 승인된 실험 한도 변경 — 2026-11-05

사용자가 "요청 200회, 실행 14일, $5 유지로 진행해"라고 승인했다. 이 절은 위 절들의 요청 수, 일일 실행 횟수, 만료 시각만 바꾼다. 나머지 조건은 그대로다.

- 누적 요청 상한은 40회에서 200회로 바뀐다. 누적 금액 상한 USD5는 그대로이며 추가 충전, 금액 상한 상향, 원장 초기화는 계속 금지한다.
- 일일 실행 상한은 4회에서 14회로 바뀐다. 만료는 활성화 시각 2026-11-05 13:09:12 KST에 14일을 더한 2026-11-19 13:09:12 KST다. 하루 조사 최대 2건, 주제 1회는 그대로다.
- 원격 control은 신뢰된 Actions runner가 단기 GITHUB_TOKEN으로 한 번만 갱신한다. 갱신 대상은 한도와 만료뿐이며 기존 요청 기록, 예약, 중단 상태, 날짜 기록은 바꾸지 않는다.
- 허용 호출에 `/v1/messages/count_tokens`를 더한다. 공식 문서상 무료인 요청 형식 사전검증과 토큰 측정에만 쓰며 원장 요청 수에 넣지 않는다.

## 승인된 실패 대응과 실행 트리거 변경 — 2026-11-06

2026-11-06 첫 구조화 출력 요청이 HTTP 400 "The compiled grammar is too large"로 거절되어 원장이 중단(halted)됐다. 사용자는 스키마 단순화, 사람 확인 뒤 중단 해제, 실행 트리거 변경을 모두 "ok"로 승인했다.

- 구조화 출력 스키마는 유니온(anyOf)과 정규식 패턴을 쓰지 않는다. 빠진 제약은 호스트 검사가 거절로 처리한다.
- 중단 해제는 사람이 수동 실행(workflow_dispatch)에서 `resume_reviewed_halt`를 켰을 때만 한다. 미정산 예약이 있거나 금액 상한에 닿았으면 거부한다. 실패 기록과 예약 금액은 원장에 그대로 남고 해제 시각이 `manual_reviews`에 추가된다. 원장 초기화와 날짜 기록 삭제는 계속 금지한다.
- AI 일일 실행은 공개 브리핑 수집 완료(`workflow_run`)를 주 트리거로 쓰고 15분 예약은 보조로 둔다. 공개 브리핑 예약은 00:37 KST로 옮긴다. 그날 수집 실행이 10:00 KST까지 없으면 AI 실행이 공개 브리핑 수집을 한 번 수동 실행한다. 모두 무료 GitHub 기능이다.
- 요청이 거절된 날은 Actions 결과를 실패로 표시한다.
- 사용자가 2026-11-06 "ok"로 승인: 유니온 제거판도 거절되어 조사 사실을 한 모양 배열로 바꾸고, 새 스키마마다 출력 16토큰짜리 유료 문법 시험 요청을 실제 요청 전에 한 번 보낸다. 시험은 원장 요청 수에 넣고, HTTP 400 거절이면 실험을 멈추지 않고 그 단계만 건너뛴다. 하루 최대 요청은 조사 2, 주제 1, 시험 2로 5회다. 수동 `grammar_probe_only` 실행은 날짜 기록을 쓰지 않는다.
- 사용자가 2026-11-06 "ok"로 승인: 그날 보낸 요청이 모두 무과금 HTTP 4xx 거절이었던 날은 사람이 수동 실행에서 `retry_rejected_day`를 켰을 때 한 번만 다시 시도할 수 있다. 실행일 수는 늘지 않고, 원래 결과와 거절된 요청 ID는 날짜 기록의 `retry_of`에, 거절 기록은 원장에 그대로 남는다. 요금이 붙었거나 5xx·연결 실패가 섞인 날은 재시도하지 않는다.

## 출처 정의 관리 — 2026-11-06

출처 설정은 `sources/<id>.json`에서 고친다. `sources.yaml`은 `scripts/generate_sources.py`가 만드는 생성물이라 직접 고치지 않는다. runbook의 접근 정보는 실제 확인한 것만 적고 모르면 `unknown`으로 둔다. 자세한 규칙은 [docs/sources.md](docs/sources.md). 일일 수집 뒤 `Source health` workflow가 출처별 `monitoring.expect`와 실제 상태를 비교해 `working` 출처가 실패하면 CI를 실패로 만든다. 알려진 고장은 `known_failing`으로 이유와 날짜를 남기고, 고쳐지면 `working`으로 돌린다.

## 승인된 AI 품질 보강 — 2026-11-07

사용자가 2026-11-07 결과 피드백(조사 eligibility 형식 거절, 주제 분류가 고정 근거를 그대로 옮김)에 "좋다. 진행."으로 승인했다. 비용 한도·요청 수·만료·원장은 바꾸지 않는다.

- 조사 프롬프트에 eligibility scope 허용값(`restricted`·`unrestricted`·`disputed`)과 "결제해야 받는 할인·적립·페이백은 `paid`" 규칙을 명시한다. 스키마는 바꾸지 않는다.
- 주제 근거에 `public/topic-basis.json`의 `keyword_policy.approved`로 켜는 고정 단어 규칙(`benefit_monitor/public_topics.py`)을 더한다. 규칙은 이미 공개 승인된 항목의 제목·요약·대상 표기만 보고 주제 후보만 추가한다. 새 사실을 만들거나 공개 승인하지 않는다. AI는 후보 안에서만 카드를 고른다.
- 이 변경에 맞춰 `public/topic-publication.json`의 `policy_sha256`을 다시 계산한다. 주제 스키마가 바뀌므로 기존 승인대로 문법 시험 요청이 한 번 나갈 수 있다.

## 승인된 전국 축제 별도 섹션 — 2026-11-07

사용자가 "국내 축제 정보도 보여주면 좋겠다, 최대한 많은 정보"를 요청하고, 출처 점검 결과를 본 뒤 "별도 축제 섹션"을 골랐다. 이 절은 위 공개 원칙의 예외를 축제 섹션 하나에 한정한다.

- 출처는 한국관광공사 `korean.visitkorea.or.kr`의 대한민국 구석구석 전국축제 목록(`sources/kfes.json`) 하나다. robots 허용, 익명 공개 화면이 쓰는 폼 POST만 쓴다. 실행당 요청은 robots 포함 약 5회이며 전체 HTTP 상한 75회 안에 든다.
- 공식 목록 칸(이름·기간·지역·장소·주최·요금 원문·할인·개요·프로그램·홈페이지·문화관광축제 여부)을 고치지 않고 `briefing.json`의 `festivals`에 담는다. 사람 검증 전이라고 표시한다. 휴대전화 번호·이메일은 지운다.
- 검증 혜택 목록(`public/verified.json`)·검토 큐·AI 조사·주제 카드·즐겨찾기에는 넣지 않는다. 요금은 원문 단어로만 무료·유료·일부 유료·미확인으로 나누며, 요금으로 거르거나 순서를 바꾸지 않는다.

## 승인된 AI 교차 조사·자동 공개 — 2026-11-07

사용자가 2026-11-07 설계를 논의하며 아래와 같이 승인했다. 설계: `docs/superpowers/specs/2026-11-07-ai-cross-check-autopublish-design.md`.

- "A,C 로 하고 C 는 기준 충족하면 자동공개해"
- 가장 피할 실패: "과거 자료나 끝난 이벤트인데 현재 운영중인, 실제로 앞으로 오픈할것처럼 보이는거가 가장 용납하기 어렵지"
- 상시 운영 혜택: "다른 증거가 있으면 공개해도 돼"
- 비용: "금액은 난 월 $10~20 도 괜찮은거같음"
- 크레딧 소진: "일단 현재 유지하다가 크레딧 다 쓰면 내가 알림받을 때 수동 충전할게"
- 어드민: "그 자리에서 바로 내릴 수 있는 방법. 어드민 페이지를 하나 만들어서 운영하면 될듯", 반영 지연은 "조금 걸려도 됨"

이 절은 앞선 절의 아래 한도를 다음과 같이 **대체**한다. 이 절에 없는 내용(Haiku 5.5 고정, GitHub Actions Secret, 무료 인프라, 출처·robots 규칙)은 그대로다.

- 누적 $5 상한 → **월 $15 상한**(프로그램 원장 기준). 누적(평생) 상한은 없다.
- 누적 200요청, 14 실행일, 2026-11-19 13:09 KST 만료 → **모두 제거**. 월 금액 상한이 유일한 지출 한도다.
- "추가 충전 금지" → 크레딧이 떨어지면 사용자가 알림(GitHub 실패 메일)을 받고 **직접 수동 충전**한다. 자동 충전·미리 충전은 하지 않는다.
- "새 AI 사실은 비공개 사람 검토 대기에만" → 결정적 자동 공개 기준(`benefit_monitor/auto_publish.py`)을 모두 통과한 항목은 자동 공개할 수 있다. 기준을 하나라도 통과하지 못하면 이전처럼 비공개 보류다. 모델 문장은 공개하지 않고 코드가 검증한 값만 쓴다. 자동 공개 항목은 화면에 AI 표시를 붙이고, 지난 날짜가 현재·예정처럼 보이지 않도록 날짜 규칙과 본문 재확인을 적용한다.
- 일일 조사 2건 → **최대 20건**.
- 실행당 HTTP 상한 75 → **상한 100**, 수집 기본값은 설정값 75로 둔다.

추가 사항:
- 공식 관련 문서를 후보당 최대 3개까지 교차 확인에 쓴다.
- 어드민 페이지(`/admin.html`)로 자동 공개 항목을 내리고 복원할 수 있다. 토큰은 기본 `sessionStorage`, 사용자가 선택하면 `localStorage`에 둔다. 내림/복원은 contents API와 `briefing-pages.yml`의 `apply_takedowns: true` dispatch로 반영한다.
- 이 기능의 게이트 코드가 바뀌어 `public/topic-publication.json`의 주제 카드 승인 해시(`policy_sha256`)를 다시 기록했다. 게이트 코드를 바꿀 때마다 다시 기록하며 가드 테스트가 강제한다.
- 비용 외 금지 사항(유료 서비스·결제 정보·구매·신청 대행)은 그대로 적용된다.
- 주제 카드 승인은 2027-11-07까지 유효하며 이후에는 사람이 갱신해야 한다(게이트 코드가 바뀌었다면 `policy_sha256`도 다시 기록). 이는 위 "11/19 만료 제거"와 별개인 주제 카드 공개 승인의 유한 만료다.

## 승인된 AI 품질·신뢰도 검증 전환 — 2026-11-09

사용자가 2026-11-09 점검 결과를 보고 "데이터 수집은 파이썬으로 하고 수집된 데이터에 대해서 품질 강화 신뢰도 체크를 ai agent 를 해야"라고 요구하고, 제안 A·B·C·D에 "A, B, C, D 개선해."로 승인했다. 설계: `docs/superpowers/specs/2026-11-09-ai-quality-verification-design.md`.

- 앞 절의 "사람이 승인한 기존 공개 항목을 AI가 고치거나 내리는 것" 금지를 아래 범위로 바꾼다. AI는 공개 항목을 공식 원문과 대조(kind `verify`)할 수 있다. 원문에 그대로 있는 인용으로 코드가 확인한 불일치는 재검증 보류(`hold_reason='ai_contradicted'`)만 건다. 내용을 고치거나 새로 공개하지 않으며, 보류는 사람이 다시 검증해야 풀린다.
- AI는 검토 대기 후보를 끝남·혜택 아님·진행 중으로 분류할 수 있다. 코드가 확인한 끝남·혜택 아님만 대기열에서 빼고, 공개·검증·종료로 표시하지 않는다.
- 무료 브리핑 수집 결과를 기존 AI 수신자 공개키로 age 암호화해 `briefing-data/ai-collection.age`에 둔다. 앞 절의 "briefing-data에 control/runtime 암호문만 저장"에 이 암호문 하나를 더한다. AI 실행은 오늘 스냅샷이 있으면 목록 수집을 다시 하지 않는다.
- 자동 공개 기준은 설계 C대로 고친다. 그에 따라 `public/topic-publication.json`의 `policy_sha256`을 다시 기록한다.
- 06시 이전 실행 금지를 없앤다.
- 하루 유료 요청은 검증 40, 조사 20, 주제 1, 문법 시험 3이다. 월 $15 상한, Haiku 5.5 고정, 실행당 HTTP 100회, 무료 인프라 원칙은 그대로다.
