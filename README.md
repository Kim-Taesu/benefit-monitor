# benefit-monitor

공식 출처의 생활 정보를 수집하고 근거·기간을 확인해 혜택, 장보기, 축제, 보건소 탭으로 보여 줍니다. AI는 원문 조건 추출·대조와 공통 추천을 맡습니다. 혜택 탭은 공통 AI·규칙 추천에 브라우저의 선호·제외·동의한 반응을 적용합니다. 개인 프로필을 모델에 보내는 추천이나 자율 검색 agent는 아직 구현하지 않았습니다.

## 코드 위치와 현재 작업

실제 저장소는 `~/personal/benefit-monitor/.maintenance/p0-source`입니다. 상위 폴더는 예전 사본입니다. 사용자 승인으로 그 프로젝트 하위 워크트리에서 작업할 수 있습니다. 명령은 선택한 Git 작업 트리 루트에서 실행합니다.

- [개선 단계와 완료 기준](docs/ai/improvement-phases.md)
- [현재 진행·검증 기록](docs/ai/progress.md)
- [브라우저 개인화 동작과 보관 범위](docs/ai/personalization.md)
- [작업 지침](AGENTS.md) · [정책 대응표](docs/ai/policy-map.md)
- 기존 상세 설명은 [이전 README](README.history.md)에 보존했습니다. 과거 상태를 설명하는 내용이 있으므로 현행 정책은 위 문서와 구현을 확인합니다.

## 실행 환경과 명령

Python 3.11 이상이며 백엔드 런타임은 표준 라이브러리만 사용합니다. 패키지 빌드는 `pyproject.toml`의 setuptools를 사용합니다. 프런트는 Node.js 22.18 이상과 `frontend/package-lock.json`의 의존성을 사용합니다.

```sh
mkdir -p .tools/verification-tmp
TMPDIR="$PWD/.tools/verification-tmp" python3 -m unittest discover -s tests -v
python3 -m benefit_monitor.cli
python3 -m benefit_monitor.briefing
```

기본 실행은 로컬 데이터만 처리합니다. 데이터가 없는 새 작업 트리에서 위 실행이 실제 운영 자료를 복원하거나 혜택을 검증해 주지는 않습니다. 온라인 수집은 `python3 -m benefit_monitor.cli --online`이며 아래 접근·요청 예산을 적용합니다. 이 명령만으로 유료 AI를 실행하지 않습니다.

프런트 의존성이 준비되어 있다면 `frontend`에서 실행합니다.

```sh
npm run dev
npm test
npm run typecheck
npm run build
npm run test:e2e
```

새 환경의 의존성 설치는 `npm ci`를 별도로 실행합니다. 브라우저 설치·온라인 다운로드는 오프라인 테스트에 포함하지 않습니다.

## 데이터 흐름

```text
공식 목록·가격·공지 수집 → 후보와 원문 확인
                       ├─ 혜택: 사람 승인 또는 AI 추출 + 코드 공개 판정
                       └─ 축제·시세·보건소: 별도 표시·검증 규칙
                                      ↓
                         공개 JSON 조립·만료·철회 검사
                                      ↓
                         Vue 화면 / GitHub Pages
                                      ↑
                   AI 공통 추천 또는 규칙 카드·링크 대체
```

- `benefit_monitor/collectors`, `festivals.py`, `groceries.py`, `health_notices.py`: 출처별 수집.
- `ai_verify.py`, `ai_review.py`, `auto_publish.py`: 원문 대조·조건 추출·자동 공개 판정.
- `*_pick.py`, `health_notes.py`: 공통 추천과 안내 문장. 모델이 실패하면 각 작업의 규칙 결과로 대체합니다.
- `publish.py`, `public_snapshot.py`, `auto_release.py`: 공개 조립·스냅샷·철회 반영.
- `cloud_daily.py`, `.github/workflows`: 기존 Actions 실행·상태 보존·배포.
- `frontend/src`: 표시와 브라우저 내부 관심사·피드백·즐겨찾기.

검증 전 후보를 곧바로 공개 혜택으로 올리지 않습니다. AI 초안은 코드 게이트를 모두 통과할 때만 자동 공개되며, 부족한 근거·지난 날짜·충돌은 보류됩니다. 공식 확인은 본인의 자격·남은 자리·재고를 보장하지 않습니다.

축제와 시세는 공식 목록·게시값을 별도 채널로 보여 주며, 검증 혜택과 섞지 않습니다. 보건소는 공지·상시 사업 링크·검사를 통과한 AI 안내를 조합합니다. 가격은 실제 매장 가격과 다를 수 있습니다. 비용 상태와 신청 조건은 원문을 함께 확인합니다.

## 출처와 수집 범위

출처 정의는 `sources/<id>.json`이며 `sources.yaml`은 생성물입니다.

```sh
python3 -m benefit_monitor.source_registry check
python3 scripts/generate_sources.py
python3 scripts/generate_source_policy.py
```

수집 범위·접근 방식·알려진 실패는 출처별 runbook과 [출처 관리](docs/sources.md)를 확인합니다. 목록 확인 성공은 본문 전체 검증을 뜻하지 않습니다. 서울 구별 뉴스는 구청 전체 공지가 아닙니다. 이미지·첨부·접근 제한 때문에 수집·조사가 안 되는 출처도 있으며 이를 전체 수집 성공으로 표시하지 않습니다.

robots·TLS·허용 호스트·6시간 자치구 캐시·실패 대기시간을 적용합니다. 일일 기본 수집 95회, 실행당 프로젝트 상한 100회입니다. 보건소와 주간 기준가는 승인된 별도 예산·워크플로를 사용합니다. 요청 제한을 우회하지 않습니다.

## 운영 비용과 비공개 데이터

기본 수집·호스팅은 추가 유료 서비스를 도입하지 않습니다. 승인된 Claude 호출만 고정 모델과 월 $15 원장 한도 안에서 실행합니다. 사용자가 크레딧을 직접 충전하며 자동 충전은 없습니다. 공급자 청구와 기존 ChatGPT/Codex·컴퓨트 요금은 프로젝트가 보장하지 않습니다.

API 키는 필요한 Actions step의 Secret 또는 승인된 로컬 경로로만 읽습니다. 새 작업 트리에 키·평문 원장·캐시를 자동 복사하지 않습니다. 로컬 기본 실행과 평가에는 키가 필요 없습니다. 원장 예약 실패·미정산을 초기화로 해결하지 않습니다.

`cache/`, `.tools/`, 원본 보고서·프로필·키는 Git에서 제외합니다. 공개 산출물에는 공개 가능한 필드만 넣습니다. 유료 행사·할인·환급도 수집 대상이며, 운영 비용의 무료 원칙을 혜택 무료 필터로 사용하지 않습니다.

## 스케줄과 배포

일일 브리핑은 `.github/workflows/briefing-pages.yml`(00:37 KST), 보건소는 `health-notices.yml`(00:07 KST), 장보기 기준가는 `grocery-baselines.yml`(주간)로 실행합니다. AI는 수집 완료 트리거와 보조 예약을 사용합니다. GitHub 예약은 지연·누락될 수 있으며 정시 전달을 보장하지 않습니다.

운영 주소: https://kim-taesu.github.io/benefit-monitor/

공개 JSON은 Pages와 `briefing-data`에 전달합니다. 상태·생성/확인 시각·표시 기한을 검사해야 하며 이전 파일이 남아 있다고 오늘 갱신 성공으로 판단하지 않습니다. 배포 성공은 개인 알림 수신을 뜻하지 않습니다. 관리자 철회와 수동 복구의 세부 조건은 [정책 대응표](docs/ai/policy-map.md)를 확인합니다.

## AI 검증과 평가

프롬프트와 입력 경계는 [프롬프트 계약](docs/ai/prompts.md), 평가 실행은 [평가 안내](docs/ai/evaluation/README.md)를 따릅니다. 고정 합성 사례의 게이트 검사, 과거 실제 응답 재생, 사용자 유용성 평가를 서로 구분합니다. 오프라인 통과율을 현재 모델의 정확도나 실제 운영 무오류 보장으로 표현하지 않습니다.
