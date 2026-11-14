# 개선 진행 기록

## 2026-11-14 — 별도 워크트리에서 Phase 0 완료·Phase 1 평가 기반 구현

- 작업 경로: `/Users/user/personal/benefit-monitor/.worktrees/phase01-evaluation`, 브랜치 `feat/phase01-evaluation`, 기준 HEAD `f7ff647`.
- 사용자 승인: `~/personal/benefit-monitor` 하위 워크트리 생성. 기존 worktree 금지의 이 범위만 대체했다. 공통 Git 디렉터리도 프로젝트 내부임을 확인했다.
- 격리: 원본의 앞선 작업 파일 10개만 복사했다. 원본 파일은 변경·삭제하지 않았고 다른 agent의 관리자 화면 변경은 가져오지 않았다. 키·캐시·원장은 복사하지 않았다.
- Phase 0: AGENTS 269→44줄, README 408→96줄. 원문은 `AGENTS.history.md`, `README.history.md`에 바이트 그대로 보존했고 원본 SHA 비교로 확인했다. 정책 대응표로 전체 24개 이력 절과 기본 규칙의 현행 적용을 연결했다.
- Phase 1: 35개 고정 합성 사례와 별도 기대 계약, 실제 게이트 평가 CLI, 기록 재생·관측 집계·동일 입력 비교·A/B 평가 도구를 구현했다. 새 네트워크/API 호출은 없다.
- 평가: 35/35 기대 일치. 과거 27개 run 중 26개 재생, 자료 불완전 1개. 현행 게이트 통과 2개, 거절 형식 13·근거 4·의미 7. 이는 현재 모델 정확도가 아니다.
- 비용: 완료 과거 요청 26개에 로컬 원장 $0.070479 기록 연결. 실제 청구·현재 월 사용액·불완전 run 비용은 미확인이다.
- 비교: 유효한 과거 주제 시나리오 1개에서 규칙과 AI가 같은 고유 항목 5개를 담았다. 중복 연결은 규칙 0, AI 1. 유용성 평가는 미실행이다.
- 검증(2026-11-14 15:58 KST): Python 전체 954개 실행, 953개 통과·1개 skip(age 바이너리 부재). 새 평가 테스트 11개 통과. CLI cases/replay/compare/score 실행 완료.
- 공개 게이트·스키마·비용 정책·운영 워크플로·조사 fingerprint 대상 파일은 바꾸지 않았다. 유료 호출·온라인 수집·배포·커밋·push는 하지 않았다.
- Phase 1 남은 관측: 정답 라벨 독립 검토, 현재 모델 실측, 사용자 유용성 평가, 전체 운영 단계 시간/반응 계측. 미관측은 null이며 이 단계 전체 완료로 표시하지 않는다.
- 다음 작업: `docs/ai/evaluation/README.md`의 실행 절차와 `baseline-summary.md`를 읽고 남은 평가를 연결한다. 비교 자료는 `.tools/evaluation/blind-packets.json`, 키는 별도 `blind-keys.json`, 미평가 양식은 `ratings.json`이다.

## 2026-11-14 — Phase 0 일부 적용

- 요청: 전체 개선을 Phase별 TODO·기대효과·달성목표로 나누고, prompt/context/harness 관점의 개선을 가능한 범위에서 적용.
- 완료: Phase 0~5 계획, 작업 안내, 실제 프롬프트 계약, 축제·혜택 프롬프트 구조화와 마지막 작업 지시 충돌 제거.
- 재현: 변경 전 `test_prompt_examples.py`의 새 회귀 테스트에서 festival·benefit 두 하위 사례가 실패했다. 마지막 지시가 본문의 상대 시점·긴급성 표현 금지와 충돌했다.
- 정정: 혜택 프롬프트의 `today`는 실제 API 전송 전에 생성된다. 누락이 아니므로 변경하지 않았다.
- 유지: 공개 게이트·스키마·월 $15 원장·고정 모델·조사 fingerprint 대상 파일. 조사 서명 변경에 따른 일괄 재조사를 만들지 않았다.
- 기존 별도 변경: `frontend/src/admin/AdminApp.vue`, `frontend/tests/e2e/admin.spec.ts`, 미추적 `frontend/playwright.chrome.local.config.ts`는 수정하지 않았다.
- 검증(2026-11-14 15:24 KST): `TMPDIR="$PWD/.tools/verification-tmp" python3 -m unittest discover -s tests -v` → 943개 통과, 종료 코드 0. 임시 파일은 저장소 내부에 두었다. 새 회귀 테스트와 기존 few-shot 실제 게이트 검사가 포함된다.
- 문서 검증: `git diff --check` 통과, 신규 안내·계획·진행 기록·프롬프트 안내의 상대 Markdown 링크가 모두 존재한다.
- 미실행: 유료 모델 평가, 온라인 수집, 프런트 실행, 배포, 커밋·push, 플러그인 설치·전역 설정 변경.
- 미완료: AGENTS.md 정책/이력 분리와 README 전체 현행화. 승인 예외를 잃지 않도록 정책 대응표 작성 후 별도 변경한다.
- 다음 작업: Phase 1 고정 평가 사례와 기준선을 먼저 만든다. 이후 Phase 2에서 개인화·피드백 경로를 연결한다.

## 다음 세션 기록 형식

- 작업 단위와 범위:
- 변경 파일과 이유:
- 실제 실행한 검사·결과·검증 시각:
- 미검증·실패·관측 한계:
- 결정과 근거:
- 다음 작업과 주의사항:

체크박스나 이 기록만으로 기능 완료를 주장하지 않는다. 실제 diff와 검사 결과를 함께 확인한다.
