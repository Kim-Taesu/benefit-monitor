"""Human review desk for the private AI review queue. No keys, no model calls, no HTTP.

list      pending queue items that have no human decision yet
show      facts, model gate result and each quote with its surrounding source text
page      local HTML page: facts on the left, full official text with highlights on the right
prepare   editable public-release draft prefilled from the AI draft; nothing is approved
approve   human approval: validates with the existing public gates, then appends to public/verified.json
reject    records a human rejection with a reason
expiring  approved public items whose verification, end date or deadline is near
stats     review time and backlog for the Phase 2 targets

Only a person running approve with --confirm-reviewed sets verified_at and public_release.
Decisions and drafts stay in the Git-ignored .tools/review-desk folder.
"""
import argparse
from copy import deepcopy
from datetime import datetime, timedelta
import html
import json
from pathlib import Path
import statistics
import tempfile
from zoneinfo import ZoneInfo

from .store import load, save

SEOUL = ZoneInfo('Asia/Seoul')
PROJECT = Path(__file__).resolve().parents[1]
DESK = '.tools/review-desk'
TEXT_FIELDS = ('cost_details', 'payment_conditions', 'selection', 'application_method', 'cancellation', 'restrictions')
LABELS = {'eligibility': '대상', 'event_period': '이용 기간', 'application_period': '접수 기간', 'fee_status': '요금',
          'cost_details': '비용', 'payment_conditions': '결제 조건', 'selection': '선정 방식', 'capacity': '정원',
          'application_method': '신청 방법', 'cancellation': '취소 조건', 'restrictions': '기타 제한',
          'availability': '남은 자리', 'summary': '요약', 'conditions': '조건', 'districts': '자치구'}
CHECKLIST = ['제목·요약이 원문과 같은 행사를 가리킨다', '날짜·마감·요금·대상 조건을 원문에서 직접 확인했다',
             '미확인 조건을 conditions에 미확인으로 적었다', 'evidence에는 실제로 대조한 원문 문장만 남겼다',
             '개인정보·내부 메모가 공개 필드에 없다']


def _now(value=None):
    return datetime.fromisoformat(value) if value else datetime.now(SEOUL)


class Desk:
    def __init__(self, root=PROJECT, now=None):
        self.root = Path(root).resolve()
        self.now = now or datetime.now(SEOUL)
        self.folder = self.root/DESK
        self.log_path = self.folder/'decisions.json'

    # ------------------------------------------------------------ loading
    def decisions(self):
        return load(self.log_path, {'schema_version': 'review-desk-v1', 'items': {}})

    def _save_decisions(self, data):
        self.folder.mkdir(parents=True, exist_ok=True)
        save(self.log_path, data)

    def queue(self):
        rows = []
        for path in sorted((self.root/'cache/ai_review/queue').glob('*.json')):
            row = load(path, None)
            if isinstance(row, dict) and row.get('signature'):
                rows.append(row)
        return rows

    def find(self, prefix):
        hits = [r for r in self.queue() if r['signature'].startswith(prefix) or r['candidate_id'].startswith(prefix)]
        if len(hits) != 1:
            raise ValueError(f'review item prefix must match exactly one queue item; matched {len(hits)}')
        return hits[0]

    def pending(self):
        decided = self.decisions()['items']
        return [r for r in self.queue() if decided.get(r['signature'], {}).get('decision') not in ('approved', 'rejected')]

    def context(self, row):
        host = load(self.root/row['input_file'], None)
        if not isinstance(host, dict):
            raise ValueError('review input missing; restore the runtime first')
        candidate = next(c for c in host['candidates'] if c['candidate_id'] == row['candidate_id'])
        docs = {d['id']: d for d in host['documents']}
        run = self.root/'.tools/claude-trial/live/runs'/(row.get('run_id') or 'missing')
        validation = load(run/'validation.json', {}) if row.get('run_id') else {}
        return dict(row=row, host=host, candidate=candidate, docs=docs, run=run, validation=validation,
                    facts=self._facts(run), proposed=self._proposed(run))

    @staticmethod
    def _proposed(run):
        result = load(run/'result.json', None)
        return deepcopy(result['records'][0]['proposed_fields']) if isinstance(result, dict) and result.get('records') else {}

    @staticmethod
    def _facts(run):
        """Facts from the assembled result, else from the normalized or raw compact output."""
        result = load(run/'result.json', None)
        if isinstance(result, dict) and result.get('records'):
            record = result['records'][0]
            reasons = {q['field']: q['reason'] for q in record['missing_questions']}
            return [dict(field=c['field'], status=c['status'], value=c['value'], unknown_reason=reasons.get(c['field']),
                         evidence=[dict(source_ref=e['source_ref'], quote=e['quote']) for e in c['evidence']])
                    for c in record['claims']]
        for name in ('normalized-output.json', 'rejected-result.json', 'model-output.json'):
            draft = load(run/name, None)
            records = draft.get('records') if isinstance(draft, dict) else None
            if records and isinstance(records[0].get('facts'), list):
                return [dict(field=f.get('field'), status=f.get('status'), value=f.get('value'),
                             unknown_reason=f.get('unknown_reason'),
                             evidence=[dict(source_ref=e.get('source_ref'), quote=e.get('quote', '')) for e in f.get('evidence', [])])
                        for f in records[0]['facts']]
        return []

    def _mark_opened(self, row):
        data = self.decisions()
        entry = data['items'].setdefault(row['signature'], {'candidate_id': row['candidate_id']})
        entry.setdefault('opened_at', self.now.isoformat())
        self._save_decisions(data)

    # ------------------------------------------------------------ views
    def list(self):
        lines = []
        for row in self.pending():
            host = load(self.root/row['input_file'], {})
            title = next((c.get('title', '') for c in host.get('candidates', []) if c['candidate_id'] == row['candidate_id']), '')
            age = self.now - datetime.fromisoformat(row['observed_at'])
            lines.append(f"{row['signature'][:12]}  {row['model_status']:<18} {age.days}일 대기  {title}  {row['url']}")
        return '\n'.join(lines) or '검토 대기 없음'

    @staticmethod
    def _value(value):
        if value is None:
            return '미확인'
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)

    def show(self, prefix):
        ctx = self.context(self.find(prefix))
        self._mark_opened(ctx['row'])
        v = ctx['validation']
        out = [f"제목: {ctx['candidate'].get('title', '')}", f"원문: {ctx['row']['url']}",
               f"모델 결과: {ctx['row']['model_status']}  검사 통과: {bool(v.get('valid'))}"]
        for error in v.get('errors', []) or ([v['error']] if v.get('error') else []):
            out.append(f'  검사 사유: {error}')
        for finding in v.get('coverage', {}).get('findings', []):
            out.append(f"  누락 검사: {finding['code']} {finding.get('cue', '')}")
        for fact in ctx['facts']:
            label = LABELS.get(fact['field'], fact['field'])
            out.append(f"\n[{label}] {fact['status']}: {self._value(fact['value'])}")
            if fact['status'] == 'unknown' and fact.get('unknown_reason'):
                out.append(f"  사유: {fact['unknown_reason']}")
            for e in fact['evidence']:
                body = ctx['docs'].get(e['source_ref'], {}).get('body', '')
                at = body.find(e['quote']) if e['quote'] else -1
                if at < 0:
                    out.append(f"  근거: «{e['quote']}»  ※ 원문에서 찾지 못함")
                else:
                    before, after = body[max(0, at-60):at].replace('\n', ' '), body[at+len(e['quote']):at+len(e['quote'])+60].replace('\n', ' ')
                    out.append(f"  근거: …{before}«{e['quote']}»{after}…")
        return '\n'.join(out)

    def page(self, prefix):
        ctx = self.context(self.find(prefix))
        self._mark_opened(ctx['row'])
        esc = html.escape
        rows = []
        for fact in ctx['facts']:
            quotes = ''.join(f'<blockquote>{esc(e["quote"])}</blockquote>' for e in fact['evidence'])
            reason = f'<div class="reason">{esc(fact.get("unknown_reason") or "")}</div>' if fact['status'] == 'unknown' else ''
            rows.append(f'<tr class="{esc(fact["status"])}"><th>{esc(LABELS.get(fact["field"], fact["field"]))}</th>'
                        f'<td><b>{esc(fact["status"])}</b> {esc(self._value(fact["value"]))}{reason}{quotes}</td></tr>')
        bodies = []
        for doc_id in ctx['candidate']['document_ids']:
            body = ctx['docs'][doc_id]['body']
            spans = sorted({(body.find(e['quote']), len(e['quote'])) for f in ctx['facts'] for e in f['evidence']
                            if e['source_ref'] == doc_id and e['quote'] and body.find(e['quote']) >= 0})
            text, cursor = [], 0
            for start, length in spans:
                if start < cursor:
                    continue
                text.append(esc(body[cursor:start]) + '<mark>' + esc(body[start:start+length]) + '</mark>')
                cursor = start + length
            text.append(esc(body[cursor:]))
            bodies.append(f'<h3>{esc(doc_id)}</h3><pre>{"".join(text)}</pre>')
        v = ctx['validation']
        problems = [*(v.get('errors') or []), *[f['code'] + ' ' + f.get('cue', '') for f in v.get('coverage', {}).get('findings', [])]]
        sig = ctx['row']['signature']
        document = f'''<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>검토 {esc(sig[:12])}</title><style>
:root{{--bg:#fbfaf7;--fg:#1f2328;--muted:#5f6670;--line:#d8d4cc;--mark:#ffe58a;--warn:#b42318}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16181c;--fg:#e8e6e1;--muted:#a3a8b0;--line:#3a3d43;--mark:#6b5a12;--warn:#ff8a7a}}}}
body{{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,sans-serif}}
header{{padding:16px;border-bottom:1px solid var(--line)}} main{{display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:16px}}
@media (max-width:860px){{main{{grid-template-columns:1fr}}}}
table{{width:100%;border-collapse:collapse}} th,td{{text-align:left;vertical-align:top;padding:8px;border-bottom:1px solid var(--line)}}
th{{width:7em;color:var(--muted);font-weight:600}} tr.unknown td{{color:var(--muted)}}
blockquote{{margin:6px 0;padding:4px 8px;border-left:3px solid var(--mark)}} .reason{{font-size:13px}}
pre{{white-space:pre-wrap;word-break:break-word;font:inherit}} mark{{background:var(--mark);color:inherit}}
.warn{{color:var(--warn)}} code{{font-size:13px}}
</style></head><body><header><h1>{esc(ctx['candidate'].get('title', ''))}</h1>
<p><a href="{esc(ctx['row']['url'])}">{esc(ctx['row']['url'])}</a></p>
<p>모델 결과 {esc(ctx['row']['model_status'])} · 검사 통과 {esc(str(bool(v.get('valid'))))}</p>
{''.join(f'<p class="warn">{esc(p)}</p>' for p in problems)}
<p>다음 단계: <code>python3 -m benefit_monitor.review_desk prepare {esc(sig[:12])}</code></p></header>
<main><section><h2>AI가 뽑은 조건</h2><table>{''.join(rows)}</table></section>
<section><h2>공식 원문</h2>{''.join(bodies)}</section></main></body></html>'''
        target = self.folder/'pages'/(sig + '.html')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(document)
        return target

    # ------------------------------------------------------------ decisions
    def prepare(self, prefix):
        ctx = self.context(self.find(prefix))
        row, p = ctx['row'], ctx['proposed']
        facts = {f['field']: f for f in ctx['facts']}
        def supported(field):
            fact = facts.get(field)
            return fact['value'] if fact and fact['status'] == 'supported' else None
        event = supported('event_period') or {}
        application = supported('application_period') or {}
        valid_until = p.get('valid_until') or event.get('end')
        deadline = p.get('deadline_at') or application.get('end')
        from .wire_format import DAY_END
        if deadline and deadline.endswith(DAY_END):
            # The notice gave a date only: shown as the last day, never as a time nobody wrote.
            day = deadline[:-len(DAY_END)]
            valid_until, deadline = min(valid_until, day) if valid_until else day, None
        if deadline and not valid_until:
            valid_until = datetime.fromisoformat(deadline).astimezone(SEOUL).date().isoformat()
        parts = [p.get('conditions') or supported('conditions')]
        parts += [f'{LABELS[f]}: {supported(f)}' for f in TEXT_FIELDS if supported(f)]
        unknown = [LABELS.get(f, f) for f, fact in facts.items() if fact['status'] == 'unknown' and f != 'availability']
        if unknown:
            parts.append('미확인: ' + ', '.join(unknown))
        fee = supported('fee_status')
        quotes = list(dict.fromkeys(e['quote'] for f in ctx['facts'] if f['status'] == 'supported' for e in f['evidence']))
        doc = ctx['docs'][ctx['candidate']['document_ids'][0]]
        draft = dict(source=row['source'], url=row['url'], title=ctx['candidate'].get('title', ''),
                     summary=p.get('summary') or supported('summary') or '', valid_until=valid_until, verified_at=None,
                     needs_recheck=True, valid_from=p.get('valid_from') or event.get('start'),
                     published_at=p.get('published_at') or doc.get('published_at'),
                     conditions='. '.join(x for x in parts if x), evidence='공식 원문 대조: ' + ' / '.join(quotes[:10]),
                     districts=p.get('districts') or supported('districts') or [],
                     review_notes=f"AI 조사 초안 {(row.get('run_id') or '')[:12]}를 사람이 공식 원문과 대조",
                     fee_status=fee if fee in ('free', 'paid') else 'unknown',
                     validity_kind='fixed' if valid_until or deadline else 'ongoing', deadline_at=deadline,
                     excluded_reason='', payment_terms={}, labels={}, benefit_value={}, public_release=False,
                     _review=dict(signature=row['signature'], run_id=row.get('run_id'), model_status=row['model_status'],
                                  prepared_at=self.now.isoformat(), checklist=CHECKLIST,
                                  notes=['_review 블록은 승인할 때 자동으로 지워진다',
                                         'fee_status가 conditional이면 unknown으로 두었다. 원문을 보고 free·paid·mixed로 고친다'
                                         if fee == 'conditional' else '요금 값은 원문과 다시 대조한다',
                                         'validity_kind ongoing은 종료일이 없는 상시 서비스에만 쓴다']))
        target = self.folder/'drafts'/(row['signature'] + '.json')
        if target.exists():
            raise ValueError(f'draft already exists; edit it or delete it first: {target}')
        target.parent.mkdir(parents=True, exist_ok=True)
        save(target, draft)
        data = self.decisions()
        entry = data['items'].setdefault(row['signature'], {'candidate_id': row['candidate_id']})
        entry.setdefault('opened_at', self.now.isoformat())
        entry['prepared_at'] = self.now.isoformat()
        self._save_decisions(data)
        return target

    def _decide(self, row, decision, **extra):
        data = self.decisions()
        entry = data['items'].setdefault(row['signature'], {'candidate_id': row['candidate_id']})
        if entry.get('decision') in ('approved', 'rejected'):
            raise ValueError('this item already has a human decision')
        started = entry.get('opened_at') or entry.get('prepared_at') or self.now.isoformat()
        entry.update(decision=decision, decided_at=self.now.isoformat(), run_id=row.get('run_id'),
                     model_status=row['model_status'], url=row['url'],
                     review_seconds=max(0, int((self.now - datetime.fromisoformat(started)).total_seconds())), **extra)
        self._save_decisions(data)
        return entry

    def approve(self, prefix, confirm=False):
        if not confirm:
            raise ValueError('approval requires --confirm-reviewed after checking the official source yourself')
        from .publish import releases
        row = self.find(prefix)
        if self.decisions()['items'].get(row['signature'], {}).get('decision') in ('approved', 'rejected'):
            raise ValueError('this item already has a human decision')
        path = self.folder/'drafts'/(row['signature'] + '.json')
        draft = load(path, None)
        if not isinstance(draft, dict):
            raise ValueError('prepare and edit a draft before approval')
        review = draft.pop('_review', {})
        if review.get('signature') != row['signature'] or (draft.get('source'), draft.get('url')) != (row['source'], row['url']):
            raise ValueError('draft does not belong to this review item')
        if not str(draft.get('evidence', '')).strip() or not str(draft.get('summary', '')).strip():
            raise ValueError('summary and human verification evidence are required')
        draft.update(verified_at=self.now.isoformat(), needs_recheck=False, public_release=True)
        config = load(self.root/'sources.yaml', None)
        entries = load(self.root/'public/verified.json', [])
        with tempfile.TemporaryDirectory(dir=self.folder) as temp:
            save(Path(temp)/'public/verified.json', entries + [draft])
            releases(Path(temp), config, self.now)  # the exact public gates, including duplicate and privacy checks
        save(self.root/'public/verified.json', entries + [draft])
        return self._decide(row, 'approved')

    def reject(self, prefix, reason):
        if not reason or not reason.strip():
            raise ValueError('rejection requires a reason')
        return self._decide(self.find(prefix), 'rejected', reason=reason.strip())

    # ------------------------------------------------------------ follow-up
    def expiring(self, days=7):
        config = load(self.root/'sources.yaml', {})
        age = timedelta(days=config.get('max_age_days', 7))
        horizon = self.now + timedelta(days=days)
        rows = []
        for entry in load(self.root/'public/verified.json', []):
            reasons = []
            if entry.get('verified_at'):
                due = datetime.fromisoformat(entry['verified_at']) + age
                if due <= horizon:
                    reasons.append(('재확인', due))
            if entry.get('valid_until'):
                end = datetime.fromisoformat(entry['valid_until'] + 'T23:59:59+09:00')
                if self.now <= end <= horizon:
                    reasons.append(('종료', end))
            if entry.get('deadline_at'):
                deadline = datetime.fromisoformat(entry['deadline_at'])
                if self.now <= deadline <= horizon:
                    reasons.append(('마감', deadline))
            if entry.get('valid_until') and datetime.fromisoformat(entry['valid_until'] + 'T23:59:59+09:00') < self.now:
                continue
            if reasons:
                kind, when = min(reasons, key=lambda pair: pair[1])
                rows.append((when, kind, entry['title'], entry['url']))
        rows.sort()
        return '\n'.join(f'{when.astimezone(SEOUL):%m-%d %H:%M}  {kind:<3}  {title}  {url}'
                         for when, kind, title, url in rows) or f'{days}일 안에 재확인·종료·마감할 공개 항목 없음'

    def stats(self):
        items = self.decisions()['items'].values()
        decided = [i for i in items if i.get('decision') in ('approved', 'rejected')]
        seconds = [i['review_seconds'] for i in decided if isinstance(i.get('review_seconds'), int)]
        backlog = [r for r in self.pending() if self.now - datetime.fromisoformat(r['observed_at']) > timedelta(days=1)]
        return {'decided': len(decided), 'approved': sum(i['decision'] == 'approved' for i in decided),
                'rejected': sum(i['decision'] == 'rejected' for i in decided),
                'median_review_minutes': round(statistics.median(seconds)/60, 1) if seconds else None,
                'pending': len(self.pending()), 'pending_over_one_day': len(backlog),
                'targets': {'median_review_minutes': 3, 'pending_over_one_day': 0}}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('command', choices=('list', 'show', 'page', 'prepare', 'approve', 'reject', 'expiring', 'stats'))
    parser.add_argument('item', nargs='?')
    parser.add_argument('--root', type=Path, default=PROJECT)
    parser.add_argument('--reason')
    parser.add_argument('--days', type=int, default=7)
    parser.add_argument('--confirm-reviewed', action='store_true')
    parser.add_argument('--now', help='testing only: ISO timestamp')
    args = parser.parse_args()
    desk = Desk(args.root, _now(args.now))
    needs_item = args.command in ('show', 'page', 'prepare', 'approve', 'reject')
    if needs_item and not args.item:
        parser.error('this command needs a queue item prefix from list')
    try:
        if args.command == 'list':
            print(desk.list())
        elif args.command == 'show':
            print(desk.show(args.item))
        elif args.command == 'page':
            print(desk.page(args.item))
        elif args.command == 'prepare':
            print(f'초안을 원문과 대조해 고친 뒤 approve 하세요: {desk.prepare(args.item)}')
        elif args.command == 'approve':
            entry = desk.approve(args.item, args.confirm_reviewed)
            print(f"승인 완료, 검토 {entry['review_seconds']}초. public/verified.json 변경을 확인하고 커밋하세요.")
        elif args.command == 'reject':
            desk.reject(args.item, args.reason)
            print('거절 기록 완료')
        elif args.command == 'expiring':
            print(desk.expiring(args.days))
        else:
            print(json.dumps(desk.stats(), ensure_ascii=False, indent=2))
    except ValueError as error:
        print(f'중단: {error}')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
