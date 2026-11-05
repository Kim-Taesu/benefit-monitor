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
