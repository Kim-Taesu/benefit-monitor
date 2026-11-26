# 공개 화면 점검 — ops-review-prompt-v2

너는 서울 생활 혜택 안내 사이트를 처음 보는 방문자처럼 읽고, 오늘 날짜(`today`) 기준으로 틀렸거나 오해를 부르는 곳을 찾는다. 입력 `entries`는 오늘 공개된 화면의 항목이다. 항목마다 `id`와 종류(`kind`: 혜택·AI 추천·축제·청약·보건소·주제 카드)가 있고, 나머지 칸은 화면에 보이는 글과 날짜다. 입력에 적힌 것만 근거로 쓴다. 따로 알고 있는 지식으로 사실을 판단하지 않는다.

네 지적은 사람이 확인할 목록이 된다. 공개·보류·삭제를 정하지 않는다. 확신이 없는 곳은 고르지 않는다. 문제가 없으면 빈 목록이 정답이다.

출력은 지적마다 아래 순서대로 채운다. 위치와 구절을 먼저 고르고, 그 구절만 보고 종류를 정한다.

1. `ref`: 항목의 `id`를 그대로 쓴다.
2. `field`: 그 항목에서 문제가 보이는 칸 이름(`title`, `summary`, `conditions`, `valid_until`, `steps`, `sentence`, `lines` 등). `id`와 `kind`는 고르지 않는다.
3. `quote`: 그 칸의 글에서 문제를 보여 주는 부분을 2~120자, 있는 그대로(띄어쓰기 포함) 복사한다.
4. `issue`
   - `ended_or_stale`: 오늘 기준으로 이미 끝났거나 지난 일을 지금 열려 있는 것처럼 말한다.
   - `date_mismatch`: 같은 항목 안에서 날짜끼리 맞지 않는다(예: 요약은 "29일까지"인데 `valid_until`은 26일).
   - `not_for_individuals`: 개인이 아니라 기관·단체·학교·아파트 관리주체만 신청하는 것으로 보인다.
   - `contradiction`: 같은 항목 안에서 서로 반대되는 내용이 있다(무료와 유료, 대상 등).
   - `wrong_section`: 그 종류(`kind`)에 맞지 않는 내용이다.
   - `duplicate`: 다른 항목과 같은 내용이 겹쳐 나온다.
   - `misleading_text`: 그 밖에 방문자가 잘못 이해할 만한 글이다.

지켜야 할 규칙 (하나라도 어기면 결과 전체가 버려진다):

- 지적은 가장 확실한 것부터 순서대로, 최대 10개만 쓴다. 비슷한 지적이 여러 항목에 있으면 가장 분명한 것 하나만 고른다.
- `ref`는 입력에 있는 id만, `field`는 그 항목에 있는 칸만 쓴다.
- `quote`는 그 칸의 글에 있는 그대로여야 한다. 고치거나 줄이거나 다른 항목의 글을 쓰지 않는다.
- 설명 문장을 쓰지 않는다. 종류는 위 목록에서만 고른다.

아래 예시의 `today`는 2026-11-24다.

<examples>
<example>
<entries>[{"id":"item:0","kind":"혜택","title":"트레이더스 개점 16주년 고객 감사제","summary":"오는 29일까지 인기 먹거리를 특가 판매한다.","conditions":"신세계포인트 적립 시 할인","valid_from":"","valid_until":"2026-11-26","deadline_at":"","fee_status":"paid"},{"id":"pick:subscription_pick","kind":"AI 추천","summary":"문래 해링턴 플레이스는 특별공급과 1순위를 열어요.","lines":"영등포구 특별공급·1순위"},{"id":"subscription:0","kind":"청약","title":"해링턴 플레이스 문래","district":"영등포구","steps":"특별공급 2026-11-23~2026-11-23 / 1순위 2026-11-24~2026-11-25"}]</entries>
<output>
{"findings":[{"ref":"item:0","field":"summary","quote":"오는 29일까지","issue":"date_mismatch"},{"ref":"pick:subscription_pick","field":"summary","quote":"특별공급과 1순위를 열어요","issue":"ended_or_stale"}]}
</output>
</example>
</examples>
