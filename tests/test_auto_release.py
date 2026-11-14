"""Auto-published AI records are rechecked on every public path; ambiguity hides them."""
import base64
from copy import deepcopy
from datetime import timedelta
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from benefit_monitor import auto_release, cost_policy, operations, publish
from benefit_monitor.store import save
from test_pipeline import benefit, SOURCE, NOW

CID = 'a' * 24
BODY = '<main>' + '공식 전시는 2026년 11월 30일까지 열리며 누구나 무료로 관람할 수 있습니다. ' * 3 + '</main>'


def body_hash(page=BODY, url='https://official.example/ai/1'):
    from benefit_monitor.collectors.body import extract_body
    return hashlib.sha256(extract_body(page, url)[0].encode()).hexdigest()


def record(**kw):
    review = dict(kind='ai_auto', documents=[
        dict(url='https://official.example/ai/1', body_hash=body_hash(), title='AI 전시'),
        dict(url='https://official.example/ai/2', body_hash='2' * 64, title='')],
        document_count=2, checked_at=(NOW - timedelta(hours=1)).isoformat(), published_at=None,
        basis=dict(period_quotes=['2026년 11월 30일까지'], operating_quotes=[]))
    review.update(kw.pop('review', {}))
    value = dict(schema_version=1, candidate_id=CID, source='test', url='https://official.example/ai/1',
                 title='AI 전시', summary='공식 원문 두 곳으로 확인한 전시', conditions='누구나 관람', fee_status='free',
                 districts=[], valid_from=None, valid_until='2026-11-30', deadline_at=None, validity_kind='fixed',
                 labels={}, payment_terms={}, review=review, title_key='ai전시|테스트')
    value.update(kw)
    return value


class Base(unittest.TestCase):
    def setUp(self):
        # Inside the checkout: the cloud delivery path refuses roots outside it.
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.human = benefit().data()
        save(self.root / 'sources.yaml', dict(sources=[SOURCE], max_age_days=7))
        save(self.root / 'report.json', dict(verified_at=NOW.isoformat(), complete=False, new=[self.human], needs_recheck=[],
                                             collection=dict(online=True, successful_sources=['test'], successful_districts=0)))
        save(self.root / 'public/verified.json', [dict(self.human, public_release=True)])
        self.approve(record())

    def approve(self, *records, takedowns=()):
        save(self.root / 'cache/ai_publish/approved.json', {r['candidate_id']: r for r in records})
        save(self.root / 'cache/ai_publish/takedowns.json', list(takedowns))

    def items(self, now=NOW):
        return auto_release.public_items(*auto_release.load(self.root), {'test': SOURCE}, now)

    def urls(self, data):
        return [row['url'] for row in data['items']]


class PublicItemTests(Base):
    def test_expired_today_is_dropped(self):
        self.approve(record(valid_until='2026-10-25'))
        self.assertEqual(self.items(), [])
        self.approve(record(valid_until='2026-10-26'))
        [item] = self.items()
        self.assertEqual(item['display_until'], '2026-10-27T00:00:00+09:00')
        self.approve(record(valid_until='2026-10-26', deadline_at='2026-10-26T07:59:00+09:00'))
        self.assertEqual(self.items(), [])

    def test_stale_over_30h_hidden_human_items_kept(self):
        self.approve(record(review=dict(checked_at=(NOW - timedelta(hours=31)).isoformat())))
        self.assertEqual(self.urls(publish.payload(self.root, now=NOW)), [self.human['url']])
        self.approve(record(review=dict(checked_at=(NOW + timedelta(minutes=5)).isoformat())))
        self.assertEqual(self.items(), [])
        self.approve(record(review=dict(checked_at=(NOW - timedelta(hours=29)).isoformat())))
        [item] = self.items()
        # The display cutoff also hides it in the browser once 30 hours have passed.
        self.assertEqual(item['display_until'], (NOW + timedelta(hours=1)).isoformat())

    def test_ongoing_older_than_90_days_and_withdrawn_and_bad_records_are_hidden(self):
        ongoing = dict(valid_until=None, validity_kind='ongoing')
        self.approve(record(**ongoing, review=dict(published_at='2026-07-27')))
        self.assertEqual(self.items(), [])
        self.approve(record(**ongoing, review=dict(published_at='2026-08-01')))
        self.assertEqual(len(self.items()), 1)
        self.approve(record(**ongoing, review=dict(published_at=None)))
        self.assertEqual(self.items(), [])
        for bad in (record(status='withdrawn', withdrawn_reason='body_changed'), record(url='https://evil.example/ai/1'),
                    record(review=dict(documents=[dict(url='https://evil.example/x', body_hash='3' * 64, title='')])),
                    record(summary=''), record(fee_status='conditional'), record(conditions='문의 010-1234-5678'),
                    {k: v for k, v in record().items() if k != 'review'}, record(source='other'), 'not a record'):
            with self.subTest(bad=json.dumps(bad, ensure_ascii=False)[:80]):
                save(self.root / 'cache/ai_publish/approved.json', {CID: bad})
                self.assertEqual(self.items(), [])

    def test_auto_item_never_replaces_a_human_release_with_the_same_identity(self):
        self.approve(record(url=self.human['url'], summary='다른 AI 요약'))
        data = publish.payload(self.root, now=NOW)
        self.assertEqual([row['summary'] for row in data['items']], [self.human['summary']])

    def test_review_field_human_and_auto(self):
        data = publish.payload(self.root, now=NOW)
        human, auto = data['items']
        self.assertEqual(human['review'], {'kind': 'human'})
        self.assertEqual(auto['review'], {'kind': 'ai_auto', 'document_count': 2, 'candidate_id': CID, 'title_key': 'ai전시|테스트',
                                          'documents': [{'url': 'https://official.example/ai/1', 'title': 'AI 전시'},
                                                        {'url': 'https://official.example/ai/2', 'title': ''}],
                                          'checked_at': (NOW - timedelta(hours=1)).isoformat()})
        self.assertEqual(auto['verified_at'], auto['review']['checked_at'])
        self.assertIs(auto['needs_recheck'], False)
        self.assertNotIn('body_hash', json.dumps(data))
        self.assertNotIn('basis', json.dumps(data['items']))
        self.assertEqual(data['status'], 'partial')

    def test_markdown_export_marks_ai_items_and_leaves_human_items_unmarked(self):
        data = publish.payload(self.root, now=NOW)
        publish.write_export(self.root, data)
        text = (self.root / 'delivery/public/briefing.md').read_text()
        self.assertEqual(text.count('AI 정리 · 공식 원문 2곳 대조 (사람 검증 전)'), 1)
        human, auto = text.split('\n## ')[1:3]
        self.assertNotIn('AI 정리', human)
        self.assertIn('AI 정리', auto)

    def test_corrupt_takedowns_fail_closed_and_missing_files_are_empty(self):
        (self.root / 'cache/ai_publish/takedowns.json').write_text('{broken')
        self.assertEqual(auto_release.load(self.root), ({}, []))
        save(self.root / 'cache/ai_publish/takedowns.json', {'not': 'a list'})
        self.assertEqual(auto_release.load(self.root), ({}, []))
        (self.root / 'cache/ai_publish/approved.json').unlink()
        (self.root / 'cache/ai_publish/takedowns.json').unlink()
        self.assertEqual(auto_release.load(self.root), ({}, []))


class TakedownTests(Base):
    def test_takedown_removes_on_all_paths(self):
        from benefit_monitor.public_snapshot import validate
        raw = publish.payload(self.root, now=NOW)
        self.assertEqual(len(raw['items']), 2)
        for takedown in ({'candidate_id': CID}, {'title_key': 'ai전시|테스트'}):
            with self.subTest(takedown=takedown):
                self.approve(record(), takedowns=[dict(takedown, taken_down_at=NOW.isoformat(), note='')])
                self.assertEqual(self.urls(publish.payload(self.root, now=NOW)), [self.human['url']])
                self.assertEqual(self.urls(validate(self.root, deepcopy(raw), NOW)), [self.human['url']])
                cleaned = auto_release.apply_takedowns(deepcopy(raw), [takedown])
                self.assertEqual(self.urls(cleaned), [self.human['url']])

    def test_apply_takedowns_only_removes_matching_auto_items_and_their_topics(self):
        raw = publish.payload(self.root, now=NOW)
        human, auto = raw['items']
        raw['topic_cards'] = {'schema_version': 1, 'topics': [
            {'id': 'culture', 'title': '문화', 'items': [{'source': 'test', 'url': auto['url'], 'facts': auto}]},
            {'id': 'mixed', 'title': '혼합', 'items': [{'source': 'test', 'url': auto['url'], 'facts': auto},
                                                      {'source': 'test', 'url': human['url'], 'facts': human}]}]}
        before = deepcopy(raw)
        cleaned = auto_release.apply_takedowns(raw, [{'candidate_id': CID}, 'ignored', {'candidate_id': human['url']}])
        self.assertEqual(raw, before, 'input must not be mutated')
        self.assertEqual(cleaned['items'], [human])
        self.assertEqual([t['id'] for t in cleaned['topic_cards']['topics']], ['mixed'])
        self.assertEqual([r['url'] for r in cleaned['topic_cards']['topics'][0]['items']], [human['url']])
        # A human item is never taken down by this path, and nothing is ever added.
        self.assertEqual(auto_release.apply_takedowns(before, [{'title_key': 'anything'}])['items'], before['items'])


    def discount_payload(self):
        from test_grocery_discounts import real_basket
        raw = publish.payload(self.root, now=NOW)
        human, auto = raw['items']
        period = dict(valid_from='2026-10-20', valid_until='2026-11-20', validity_kind='fixed',
                      conditions='행사 기간 10월 20일~11월 20일.', labels={}, display_until='2026-11-30T00:00:00+09:00')
        raw['items'] = [dict(human, source='government', title='양파 20% 할인', summary='', **period),
                        dict(auto, source='mof_press', title='고등어 20% 할인', summary='', **period)]
        raw['grocery_baselines'] = dict(schema_version=1, source='grocery_baselines', fetched_at=NOW.isoformat(),
                                        items=[dict(b, baseline=None) for b in real_basket()])
        link = dict(title='t', discount=None, stores=None, start='2026-10-20', end='2026-11-20')
        raw['grocery_discounts'] = dict(schema_version=1, source='grocery_discounts', generated_at=NOW.isoformat(),
                                        links=[dict(link, basket_id='mackerel', url=auto['url']),
                                               dict(link, basket_id='onion', url=human['url'])])
        return raw

    def test_apply_takedowns_drops_discount_links_of_removed_items(self):
        raw = self.discount_payload()
        cleaned = auto_release.apply_takedowns(raw, [{'candidate_id': CID}], now=NOW)
        self.assertEqual([(x['basket_id'], x['url']) for x in cleaned['grocery_discounts']['links']],
                         [('onion', raw['items'][0]['url'])])
        raw['items'] = raw['items'][1:]
        self.assertNotIn('grocery_discounts', auto_release.apply_takedowns(raw, [{'candidate_id': CID}], now=NOW))

    def test_apply_takedowns_recomputes_discount_links_from_current_items(self):
        raw = self.discount_payload()
        raw['items'][0].update(valid_until='2026-11-12', conditions='행사 기간 10월 20일~11월 12일.')
        cleaned = auto_release.apply_takedowns(raw, [{'candidate_id': CID}], now=NOW)
        self.assertEqual([(x['basket_id'], x['end'], x['discount']) for x in cleaned['grocery_discounts']['links']],
                         [('onion', '2026-11-12', '20% 할인')])
        raw['items'][0]['labels'] = {'region': '서울'}
        self.assertNotIn('grocery_discounts', auto_release.apply_takedowns(raw, [{'candidate_id': CID}], now=NOW))
        raw = self.discount_payload()
        raw.pop('grocery_baselines')
        self.assertNotIn('grocery_discounts', auto_release.apply_takedowns(raw, [], now=NOW))
        # Never added when the payload had no discount bundle.
        raw = self.discount_payload()
        raw.pop('grocery_discounts')
        self.assertNotIn('grocery_discounts', auto_release.apply_takedowns(raw, [], now=NOW))


class SnapshotTests(Base):
    def validate(self, data, now=NOW):
        from benefit_monitor.public_snapshot import validate
        return validate(self.root, data, now)

    def test_snapshot_keeps_matching_auto_item(self):
        raw = publish.payload(self.root, now=NOW)
        clean = self.validate(deepcopy(raw))
        self.assertEqual(clean['items'], raw['items'])

    def test_snapshot_rejects_forged_auto_item(self):
        raw = publish.payload(self.root, now=NOW)
        for field, value in (('url', 'https://official.example/ai/forged'), ('summary', '바뀐 요약'),
                             ('review', dict(raw['items'][1]['review'], document_count=3))):
            with self.subTest(field=field):
                changed = deepcopy(raw)
                changed['items'][1][field] = value
                with self.assertRaisesRegex(ValueError, 'snapshot fact differs'):
                    self.validate(changed)
        changed = deepcopy(raw)
        changed['items'][0]['review'] = {'kind': 'ai_auto'}
        with self.assertRaisesRegex(ValueError, 'snapshot fact differs'):
            self.validate(changed)
        self.approve()
        with self.assertRaisesRegex(ValueError, 'snapshot fact differs'):
            self.validate(deepcopy(raw))

    def test_snapshot_hides_auto_item_that_went_stale_before_validation(self):
        self.approve(record(review=dict(checked_at=(NOW - timedelta(hours=29, minutes=30)).isoformat())))
        data = publish.payload(self.root, now=NOW)
        self.assertEqual(len(data['items']), 2)
        self.assertEqual(self.urls(self.validate(data, NOW + timedelta(hours=1))), [self.human['url']])

    def test_snapshot_ai_status_is_sanitized(self):
        raw = publish.payload(self.root, now=NOW)
        raw['ai_status'] = {'state': 'credit_exhausted', 'last_success_day': '2026-10-25', 'updated_at': NOW.isoformat(), 'x': 1}
        self.assertEqual(self.validate(deepcopy(raw))['ai_status'],
                         {'state': 'credit_exhausted', 'last_success_day': '2026-10-25', 'updated_at': NOW.isoformat()})
        raw['ai_status'] = {'state': 'hacked'}
        self.assertNotIn('ai_status', self.validate(raw))

    def test_import_reads_approval_files_at_the_snapshot_commit_and_current_takedowns(self):
        from benefit_monitor.public_snapshot import import_remote
        data = publish.payload(self.root, now=NOW)
        approved = json.loads((self.root / 'cache/ai_publish/approved.json').read_text())
        (self.root / 'cache/ai_publish/approved.json').unlink()
        (self.root / 'cache/ai_publish/takedowns.json').unlink()
        files = {'briefing.json?ref=' + 'a' * 40: data, 'ai-approved.json?ref=' + 'a' * 40: approved}
        requested = []

        def process(args, **kwargs):
            requested.append(args[-1])
            name = args[-1].split('/contents/')[1]
            if name not in files:
                return subprocess.CompletedProcess(args, 1, '', 'gh: Not Found (HTTP 404)')
            content = base64.b64encode(json.dumps(files[name]).encode()).decode()
            return subprocess.CompletedProcess(args, 0, json.dumps({'encoding': 'base64', 'content': content, 'sha': 'f' * 40}), '')
        with patch('benefit_monitor.public_snapshot.subprocess.run', side_effect=process):
            result = import_remote(self.root, 'Kim-Taesu/benefit-monitor', 'a' * 40, now=NOW)
        self.assertEqual(len(result['items']), 2)
        self.assertEqual(requested[0], 'repos/Kim-Taesu/benefit-monitor/contents/briefing.json?ref=' + 'a' * 40)
        self.assertIn('repos/Kim-Taesu/benefit-monitor/contents/ai-takedowns.json?ref=briefing-data', requested)
        files['ai-takedowns.json?ref=briefing-data'] = [{'candidate_id': CID}]
        with patch('benefit_monitor.public_snapshot.subprocess.run', side_effect=process):
            result = import_remote(self.root, 'Kim-Taesu/benefit-monitor', 'a' * 40, now=NOW)
        self.assertEqual(self.urls(result), [self.human['url']])
        files['ai-takedowns.json?ref=briefing-data'] = {'broken': True}
        with patch('benefit_monitor.public_snapshot.subprocess.run', side_effect=process):
            with self.assertRaises(ValueError):
                import_remote(self.root, 'Kim-Taesu/benefit-monitor', 'a' * 40, now=NOW)


class RecheckTests(Base):
    def setUp(self):
        super().setUp()
        cost_policy.reset(60)

    def test_body_change_withdraws(self):
        approved, _ = auto_release.load(self.root)
        later = NOW + timedelta(hours=2)
        self.assertEqual(auto_release.mark_checked(approved, CID, body_hash(), later), 'ok')
        self.assertEqual(approved[CID]['review']['checked_at'], later.isoformat())
        self.assertNotIn('status', approved[CID])
        self.assertEqual(auto_release.mark_checked(approved, CID, '9' * 64, later), 'changed')
        self.assertEqual((approved[CID]['status'], approved[CID]['withdrawn_reason'], approved[CID]['recheck_priority']),
                         ('withdrawn', 'body_changed', True))
        save(self.root / 'cache/ai_publish/approved.json', approved)
        self.assertEqual(self.urls(publish.payload(self.root, now=NOW)), [self.human['url']])
        # Withdrawn stays withdrawn even if the old text comes back; only a new AI decision republishes.
        self.assertEqual(auto_release.mark_checked(approved, CID, body_hash(), later), 'ok')
        self.assertEqual(approved[CID]['status'], 'withdrawn')
        fresh = {CID: record()}
        self.assertEqual(auto_release.mark_checked(fresh, CID, None, later), 'gone')
        self.assertEqual(fresh[CID]['withdrawn_reason'], 'source_gone')

    def test_record_approved_before_counters_were_dropped_keeps_its_place(self):
        # 2026-11-14: the stored original page differs from today's only by its view counter, so the
        # record moves to the cleaned hash instead of being withdrawn. A real edit still withdraws.
        from benefit_monitor.collectors.body import stable_text
        url = 'https://official.example/ai/1'
        old_body = '공식 전시 안내 등록일 2026-11-05 조회수 388 첨부파일. 전시는 2026년 11월 30일까지 열립니다.'
        old = hashlib.sha256(old_body.encode()).hexdigest()
        new = hashlib.sha256(stable_text(old_body.replace('388', '475')).encode()).hexdigest()
        key = hashlib.sha256(url.encode()).hexdigest()
        save(self.root / f'cache/ai_review/documents/{key}-{old}.json', dict(body=old_body))
        later = NOW + timedelta(hours=2)

        def approved():
            return {CID: record(review=dict(original_body_hash=old, documents=[dict(url=url, body_hash=old, title='AI 전시')]))}
        rows = approved()
        self.assertEqual(auto_release.mark_checked(rows, CID, new, later, root=self.root), 'ok')
        review = rows[CID]['review']
        self.assertEqual((review['original_body_hash'], review['documents'][0]['body_hash'], review['checked_at']),
                         (new, new, later.isoformat()))
        self.assertNotIn('status', rows[CID])
        self.assertEqual(auto_release.mark_checked(rows, CID, new, later, root=self.root), 'ok')
        for other in ('9' * 64, hashlib.sha256(stable_text(old_body + ' 신청은 마감되었습니다.').encode()).hexdigest()):
            rows = approved()
            self.assertEqual(auto_release.mark_checked(rows, CID, other, later, root=self.root), 'changed')
            self.assertEqual(rows[CID]['review']['original_body_hash'], old)
        # A record already withdrawn is not quietly moved: only a new decision brings it back.
        rows = approved()
        rows[CID].update(status='withdrawn', withdrawn_reason='body_changed', withdrawn_at=NOW.isoformat(), recheck_priority=True)
        self.assertEqual(auto_release.mark_checked(rows, CID, new, later, root=self.root), 'changed')
        self.assertEqual(rows[CID]['review']['original_body_hash'], old)
        # Without the stored page (or without a root) nothing is assumed.
        rows = approved()
        self.assertEqual(auto_release.mark_checked(rows, CID, new, later), 'changed')
        (self.root / f'cache/ai_review/documents/{key}-{old}.json').unlink()
        rows = approved()
        self.assertEqual(auto_release.mark_checked(rows, CID, new, later, root=self.root), 'changed')

    SOURCES = {'test': SOURCE, 'two': dict(id='two', domains=['two.example'], routes=['https://two.example/'], feed_url=None)}

    def check(self, approved, page=BODY, error=None, content_type='text/html; charset=utf-8', takedowns=(), now=None):
        import io
        from benefit_monitor.official_reader import OfficialReader
        save(self.root / 'sources.yaml', dict(sources=list(self.SOURCES.values()), max_age_days=7))
        calls = []

        class Response(io.BytesIO):
            headers = {'Content-Type': content_type}

        def network(request):
            url = request.full_url
            calls.append(url)
            if url.endswith('/robots.txt'):
                return Response(b'User-agent: *\nAllow: /')
            if error:
                raise error
            return Response(page.encode())
        now = now or NOW + timedelta(hours=7)
        with patch('benefit_monitor.official_reader.network_open', side_effect=network):
            errors = operations.check_bodies({}, [], self.SOURCES, now, 5, auto=approved, takedowns=list(takedowns),
                                             reader=OfficialReader(self.root, now))
        return errors, calls

    def test_daily_collection_rechecks_auto_records_within_the_budget(self):
        approved = {CID: record()}
        _, calls = self.check(approved)
        self.assertEqual(calls, ['https://official.example/robots.txt', 'https://official.example/ai/1'])
        self.assertEqual(approved[CID]['review']['checked_at'], (NOW + timedelta(hours=7)).isoformat())
        approved = {CID: record()}
        (self.root / 'cache/ai_review/http.json').unlink()  # The reader's 6-hour page cache is per run root.
        self.check(approved, page=BODY.replace('11월 30일', '12월 31일'), now=NOW + timedelta(hours=8))
        self.assertEqual(approved[CID]['status'], 'withdrawn')
        for code in (401, 403, 404, 410, 451):
            with self.subTest(code=code):
                approved = {CID: record()}
                (self.root / 'cache/ai_review/http.json').unlink(missing_ok=True)
                self.check(approved, error=HTTPError('https://official.example/ai/1', code, 'x', {}, None), now=NOW + timedelta(hours=9 + code % 7))
                self.assertEqual(approved[CID]['withdrawn_reason'], 'source_gone')
        from benefit_monitor.research_probe import RedirectBlocked
        approved = {CID: record()}
        (self.root / 'cache/ai_review/http.json').unlink(missing_ok=True)
        self.check(approved, error=RedirectBlocked(302, 'https://official.example/moved'), now=NOW + timedelta(hours=17))
        self.assertEqual(approved[CID]['withdrawn_reason'], 'source_gone')
        for kwargs in (dict(error=TimeoutError()), dict(error=HTTPError('https://official.example/ai/1', 500, 'x', {}, None)),
                       dict(content_type='application/pdf')):
            with self.subTest(kwargs=str(kwargs)):
                approved = {CID: record()}
                (self.root / 'cache/ai_review/http.json').unlink(missing_ok=True)
                errors, _ = self.check(approved, **kwargs)
                self.assertNotIn('status', approved[CID])
                self.assertEqual(approved[CID]['review']['checked_at'], record()['review']['checked_at'])
                self.assertEqual(errors[0]['item_id'], CID)
        cost_policy.reset(1)
        (self.root / 'cache/ai_review/http.json').unlink(missing_ok=True)
        _, calls = self.check({CID: record()})
        self.assertEqual(calls, [])

    def test_robots_refusal_never_withdraws(self):
        import io
        from benefit_monitor.official_reader import OfficialReader
        save(self.root / 'sources.yaml', dict(sources=list(self.SOURCES.values()), max_age_days=7))
        for code in (401, 403, 410, 451):
            with self.subTest(code=code):
                (self.root / 'cache/ai_review/http.json').unlink(missing_ok=True)
                approved = {CID: record()}

                def network(request):
                    raise HTTPError(request.full_url, code, 'x', {}, io.BytesIO())
                later = NOW + timedelta(hours=7)
                with patch('benefit_monitor.official_reader.network_open', side_effect=network):
                    errors = operations.check_bodies({}, [], self.SOURCES, later, 5, auto=approved, reader=OfficialReader(self.root, later))
                self.assertNotIn('status', approved[CID])
                self.assertEqual(approved[CID]['review']['checked_at'], record()['review']['checked_at'])
                self.assertEqual(errors[0]['category'], f'http_{code}')

    def test_robots_is_fetched_once_per_host_and_all_twenty_records_fit_the_budget(self):
        many = {}
        for n in range(25):
            cid = f'{n:024x}'
            host = 'official.example' if n % 2 else 'two.example'
            url = f'https://{host}/ai/{n}'
            many[cid] = record(candidate_id=cid, source='test' if n % 2 else 'two', url=url,
                               review=dict(documents=[dict(url=url, body_hash=body_hash(url=url), title='')], document_count=1))
        cost_policy.reset(22)
        _, calls = self.check(many)
        self.assertEqual(sorted(c for c in calls if c.endswith('robots.txt')),
                         ['https://official.example/robots.txt', 'https://two.example/robots.txt'])
        self.assertEqual(len(calls), 22)
        self.assertEqual(sum(r['review']['checked_at'] == (NOW + timedelta(hours=7)).isoformat() for r in many.values()), 20)
        self.assertFalse(any(r.get('status') for r in many.values()))
        # Checked within 6 hours: the next run in the same window only checks the 5 left over.
        cost_policy.reset(22)
        _, calls = self.check(many, now=NOW + timedelta(hours=8))
        self.assertEqual(len([c for c in calls if not c.endswith('robots.txt')]), 5)

    def test_never_displayable_records_are_not_rechecked(self):
        ongoing = record(valid_until=None, validity_kind='ongoing', review=dict(published_at='2026-07-01'))
        approved = {CID: record(), 'b' * 24: dict(ongoing, candidate_id='b' * 24),
                    'c' * 24: record(candidate_id='c' * 24, valid_until='2026-10-01'),
                    'd' * 24: record(candidate_id='d' * 24, status='withdrawn')}
        later = NOW + timedelta(hours=7)
        self.assertEqual(auto_release.recheck_targets(approved, [], self.SOURCES, later), [CID])
        self.assertEqual(auto_release.recheck_targets(approved, [{'candidate_id': CID}], self.SOURCES, later), [])
        stale = {CID: record(review=dict(checked_at=(NOW - timedelta(hours=40)).isoformat()))}
        self.assertEqual(auto_release.recheck_targets(stale, [], self.SOURCES, NOW), [CID], 'stale records are rechecked')


class MergeTests(unittest.TestCase):
    def test_merge_withdrawn_wins_newer_check_wins_new_ids_added_deletions_kept(self):
        base = {CID: record(), 'b' * 24: record(candidate_id='b' * 24)}
        ours = deepcopy(base)
        ours[CID]['review']['checked_at'] = (NOW + timedelta(hours=3)).isoformat()
        ours['c' * 24] = record(candidate_id='c' * 24)
        ours.pop('b' * 24)
        theirs = deepcopy(base)
        theirs[CID].update(status='withdrawn', withdrawn_reason='body_changed', withdrawn_at=NOW.isoformat(), recheck_priority=True)
        theirs[CID]['review']['checked_at'] = (NOW + timedelta(hours=1)).isoformat()
        theirs['d' * 24] = record(candidate_id='d' * 24)
        merged = auto_release.merge_approved(base, ours, theirs)
        self.assertEqual(sorted(merged), sorted([CID, 'c' * 24, 'd' * 24]))
        self.assertEqual(merged[CID]['status'], 'withdrawn')
        self.assertEqual(merged[CID]['review']['checked_at'], (NOW + timedelta(hours=3)).isoformat())
        # A newer AI decision replaces an older withdrawn version.
        redecided = deepcopy(ours)
        redecided[CID] = record(decided_at=(NOW + timedelta(hours=4)).isoformat(), summary='새 결정')
        merged = auto_release.merge_approved(base, redecided, theirs)
        self.assertEqual(merged[CID]['summary'], '새 결정')
        self.assertNotIn('status', merged[CID])

    def test_public_record_keeps_only_public_safe_fields(self):
        value = record(status='withdrawn', withdrawn_reason='body_changed', secret='x')
        value['review']['body'] = 'host body'
        clean = auto_release.public_record(value)
        self.assertNotIn('secret', clean)
        self.assertNotIn('body', clean['review'])
        self.assertEqual(clean['status'], 'withdrawn')


class StatusTests(Base):
    def test_ai_status_is_copied_sanitized_and_omitted_when_absent(self):
        self.assertNotIn('ai_status', publish.payload(self.root, now=NOW))
        save(self.root / 'cache/ai_daily/status.json', {'state': 'ok', 'last_success_day': '2026-10-26', 'updated_at': NOW.isoformat(), 'ledger': 1})
        self.assertEqual(publish.payload(self.root, now=NOW)['ai_status'],
                         {'state': 'ok', 'last_success_day': '2026-10-26', 'updated_at': NOW.isoformat()})
        save(self.root / 'cache/ai_daily/status.json', {'state': 'failed', 'last_success_day': None, 'updated_at': NOW.isoformat()})
        self.assertEqual(publish.payload(self.root, now=NOW, failure=True)['ai_status']['state'], 'failed')
        for bad in ({'state': 'halted', 'last_success_day': None, 'updated_at': NOW.isoformat()},
                    {'state': 'ok', 'last_success_day': 'yesterday', 'updated_at': NOW.isoformat()},
                    {'state': 'ok', 'last_success_day': None, 'updated_at': '2026-10-26T08:00:00'}, []):
            save(self.root / 'cache/ai_daily/status.json', bad)
            self.assertNotIn('ai_status', publish.payload(self.root, now=NOW))


class MirrorTests(Base):
    REPO = 'Kim-Taesu/benefit-monitor'

    def gh(self, files, writes, conflicts=0):
        state = {'conflicts': conflicts}

        def run(args, **kwargs):
            endpoint = next(a for a in args if a.startswith('repos/'))
            name = endpoint.split('/contents/')[1].split('?')[0]
            if 'PUT' in args:
                payload = json.loads(kwargs['input'])
                if state['conflicts']:
                    state['conflicts'] -= 1
                    return subprocess.CompletedProcess(args, 1, '', 'gh: sha does not match (HTTP 409)')
                writes.append((name, payload.get('sha'), json.loads(base64.b64decode(payload['content']))))
                files[name] = (json.loads(base64.b64decode(payload['content'])), 'n' * 40)
                return subprocess.CompletedProcess(args, 0, json.dumps({'commit': {'sha': 'c' * 40}}), '')
            if name not in files:
                return subprocess.CompletedProcess(args, 1, '', 'gh: Not Found (HTTP 404)')
            value, sha = files[name]
            if '--jq' in args:  # mirror.run asks gh for the sha only.
                return subprocess.CompletedProcess(args, 0, sha + '\n', '')
            content = base64.b64encode(json.dumps(value).encode()).decode()
            return subprocess.CompletedProcess(args, 0, json.dumps({'encoding': 'base64', 'content': content, 'sha': sha}), '')
        return run

    def test_restore_and_save_approved_with_sha_lease_and_one_merge_on_conflict(self):
        from benefit_monitor import mirror
        (self.root / 'cache/ai_publish/approved.json').unlink()
        remote = {CID: dict(record(), secret='never public')}
        files = {'ai-approved.json': (remote, '1' * 40), 'ai-takedowns.json': ([{'candidate_id': 'z' * 24}], '2' * 40),
                 'ai-status.json': ({'state': 'ok', 'last_success_day': '2026-10-25', 'updated_at': NOW.isoformat()}, '3' * 40)}
        writes = []
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh(files, writes)):
            mirror.restore_ai(self.root, self.REPO)
        approved, takedowns = auto_release.load(self.root)
        self.assertNotIn('secret', approved[CID])
        self.assertEqual(takedowns, [{'candidate_id': 'z' * 24}])
        self.assertEqual(json.loads((self.root / 'cache/ai_daily/status.json').read_text())['last_success_day'], '2026-10-25')
        auto_release.mark_checked(approved, CID, body_hash(), NOW)
        auto_release.save_approved(self.root, approved)
        # Another writer added a record meanwhile; the save re-reads once and merges.
        files['ai-approved.json'] = ({**remote, 'e' * 24: record(candidate_id='e' * 24)}, '4' * 40)
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh(files, writes, conflicts=1)):
            mirror.save_ai(self.root, self.REPO)
        name, sha, saved = writes[-1]
        self.assertEqual((name, sha), ('ai-approved.json', '4' * 40))
        self.assertEqual(sorted(saved), sorted([CID, 'e' * 24]))
        self.assertEqual(saved[CID]['review']['checked_at'], NOW.isoformat())
        self.assertNotIn('secret', json.dumps(saved))
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh(files, writes, conflicts=2)):
            with self.assertRaises(RuntimeError):
                mirror.save_ai(self.root, self.REPO)

    def test_missing_remote_files_are_empty_and_failed_restore_fails_closed_and_blocks_save(self):
        from benefit_monitor import mirror
        writes = []
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh({}, writes)):
            mirror.restore_ai(self.root, self.REPO)
        self.assertEqual(auto_release.load(self.root), ({}, []))
        self.approve(record())
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh({}, writes)):
            mirror.save_ai(self.root, self.REPO)
        self.assertEqual([(w[0], w[1]) for w in writes], [('ai-approved.json', None)])

        def broken(args, **kwargs):
            return subprocess.CompletedProcess(args, 1, '', 'gh: Server Error (HTTP 500)')
        self.approve(record())
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=broken):
            mirror.restore_ai(self.root, self.REPO)
        self.assertEqual(auto_release.load(self.root), ({}, []))
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=AssertionError('must not write')):
            with self.assertRaises(ValueError):
                mirror.save_ai(self.root, self.REPO)

    def test_corrupt_local_approval_list_is_never_uploaded(self):
        from benefit_monitor import mirror
        files = {'ai-approved.json': ({CID: record()}, '1' * 40)}
        writes = []
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh(files, writes)):
            mirror.restore_ai(self.root, self.REPO)
        for broken in ('{half', '[1, 2]'):
            (self.root / 'cache/ai_publish/approved.json').write_text(broken)
            with patch('benefit_monitor.mirror.subprocess.run', side_effect=AssertionError('must not write')):
                with self.assertRaises(ValueError):
                    mirror.save_ai(self.root, self.REPO)
        # Unreadable takedowns hide items but must not turn the upload into {}.
        auto_release.save_approved(self.root, {CID: record()})
        (self.root / 'cache/ai_publish/takedowns.json').write_text('{broken')
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh(files, writes)):
            mirror.save_ai(self.root, self.REPO)
        self.assertEqual(list(writes[-1][2]), [CID])

    def test_apply_takedowns_remote_filters_current_briefing_and_keeps_its_lease(self):
        from benefit_monitor import mirror
        data = publish.payload(self.root, now=NOW)
        files = {'briefing.json': (data, '5' * 40), 'ai-takedowns.json': ([{'candidate_id': CID}], '6' * 40)}
        writes = []
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh(files, writes)):
            mirror.apply_takedowns_remote(self.root, self.REPO)
        exported = json.loads((self.root / 'delivery/public/briefing.json').read_text())
        self.assertEqual(self.urls(exported), [self.human['url']])
        self.assertEqual([(w[0], w[1]) for w in writes], [('briefing.json', '5' * 40)])
        files['ai-takedowns.json'] = ({'bad': 1}, '6' * 40)
        with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh(files, writes)):
            with self.assertRaises(ValueError):
                mirror.apply_takedowns_remote(self.root, self.REPO)

    def test_takedown_deploy_rechecks_ai_items_against_the_restored_approval_list(self):
        from benefit_monitor import mirror
        data = publish.payload(self.root, now=NOW)
        auto = next(r for r in data['items'] if auto_release.is_auto(r))
        data['topic_cards'] = {'topics': [{'id': 't', 'items': [{'source': auto['source'], 'url': auto['url']}]}]}
        cases = (({CID: record()}, [self.human['url'], auto['url']]),
                 ({CID: record(status='withdrawn', withdrawn_reason='body_changed')}, [self.human['url']]),
                 ({CID: record(valid_until='2026-10-25')}, [self.human['url']]),
                 ({CID: record(review=dict(checked_at=(NOW - timedelta(hours=31)).isoformat()))}, [self.human['url']]),
                 ({CID: record(summary='승인 목록과 다른 요약')}, [self.human['url']]),
                 ({}, [self.human['url']]))
        for approved, expected in cases:
            with self.subTest(approved=json.dumps(approved, ensure_ascii=False)[:90]):
                files = {'briefing.json': (data, '5' * 40), 'ai-takedowns.json': ([], '6' * 40),
                         'ai-approved.json': (approved, '7' * 40)}
                writes = []
                with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh(files, writes)):
                    clean = mirror.apply_takedowns_remote(self.root, self.REPO, now=NOW)
                self.assertEqual(self.urls(clean), expected)
                if len(expected) == 1:
                    self.assertEqual(clean['topic_cards']['topics'], [])
                    self.assertEqual([w[0] for w in writes], ['briefing.json'])
                else:
                    self.assertEqual(writes, [])

    def test_workflow_saves_recorded_withdrawals_even_after_a_failed_collection(self):
        raw = (Path(__file__).resolve().parents[1] / '.github/workflows/briefing-pages.yml').read_text()
        step = raw.split('- name: Save rechecked AI approval list', 1)[1].split('- name:', 1)[0]
        self.assertIn("if: steps.briefing.outcome != 'skipped'", step)
        self.assertIn('continue-on-error: true', step)
        self.assertIn('--save-ai', step)

    def test_takedown_deploy_refuses_a_malformed_remote_briefing(self):
        from benefit_monitor import mirror
        good = publish.payload(self.root, now=NOW)
        for bad in ({'items': []}, dict(good, items='x'), dict(good, generated_at='2026-10-26T08:00:00'),
                    dict(good, status='unknown'), dict(good, items=[1]), dict(good, status='collection_failed'), []):
            with self.subTest(bad=str(bad)[:60]):
                files = {'briefing.json': (bad, '5' * 40), 'ai-takedowns.json': ([], '6' * 40)}
                writes = []
                with patch('benefit_monitor.mirror.subprocess.run', side_effect=self.gh(files, writes)):
                    with self.assertRaises(ValueError):
                        mirror.apply_takedowns_remote(self.root, self.REPO, now=NOW)
                self.assertEqual(writes, [])
                self.assertFalse((self.root / 'delivery/public/briefing.json').exists())

    def test_ai_run_uploads_status_through_the_runner_store_and_never_raises(self):
        from benefit_monitor.cloud_daily import upload_ai_status
        status = {'state': 'failed', 'last_success_day': None, 'updated_at': NOW.isoformat()}
        save(self.root / 'cache/ai_daily/status.json', status)
        calls = []

        class Store:
            def _api(self, path, body=None):
                calls.append((path, body))
                return {'sha': '7' * 40}
        self.assertTrue(upload_ai_status(self.root, Store()))
        self.assertEqual(calls[0], ('contents/ai-status.json?ref=briefing-data', None))
        path, body = calls[1]
        self.assertEqual((path, body['sha'], body['branch']), ('contents/ai-status.json', '7' * 40, 'briefing-data'))
        self.assertEqual(json.loads(base64.b64decode(body['content'])), status)

        class Broken:
            def _api(self, path, body=None):
                raise RuntimeError('offline')
        self.assertFalse(upload_ai_status(self.root, Broken()))


class SnapshotDeliveryOrderTests(Base):
    def test_ai_run_saves_approval_list_before_the_snapshot_and_defers_after_a_merge(self):
        import os
        from benefit_monitor import cloud_daily as m

        class Store:
            token = 'fixture-token'

            def _api(self, path, body=None):
                return {'private': False, 'full_name': 'Kim-Taesu/benefit-monitor'}
        events = []
        local = {cid: auto_release.public_record(r) for cid, r in auto_release.load(self.root)[0].items()}
        env = {'GITHUB_REF': 'refs/heads/main', 'GITHUB_SHA': 'a' * 40, 'PATH': os.environ.get('PATH', '')}
        for saved, expected in ((local, 'dispatched_not_yet_verified'), ({}, 'ai_approval_merged_deferred')):
            events.clear()
            with patch.dict(os.environ, env, clear=True), patch.object(m, 'validate', return_value={'items': []}), \
                    patch.object(m, 'public_file_lease', return_value='b' * 40), \
                    patch.object(m, 'save_ai', side_effect=lambda *a, **k: events.append('save_ai') or saved), \
                    patch.object(m, 'mirror', side_effect=lambda *a, **k: events.append('mirror') or 'c' * 40), \
                    patch.object(m, 'actions_request', side_effect=lambda *a, **k: events.append('dispatch')):
                result = m.publish_snapshot(self.root, Store(), NOW, 'k' * 20, expected_sha='b' * 40)
            self.assertEqual(result['status'], expected)
            self.assertEqual(events, ['save_ai', 'mirror', 'dispatch'] if saved else ['save_ai'])
        with patch.dict(os.environ, env, clear=True), patch.object(m, 'validate', return_value={'items': []}), \
                patch.object(m, 'public_file_lease', return_value='d' * 40), \
                patch.object(m, 'save_ai', side_effect=AssertionError('lease first')):
            with self.assertRaisesRegex(ValueError, 'changed during AI run'):
                m.publish_snapshot(self.root, Store(), NOW, 'k' * 20, expected_sha='b' * 40)


class RuntimeRestoreTests(Base):
    def test_runtime_pack_includes_ai_publish(self):
        from benefit_monitor.age_state import FOLDERS
        self.assertIn('cache/ai_publish/', FOLDERS)

    def test_packed_approvals_survive_restore_and_failed_restore_stops_before_paid_work(self):
        from benefit_monitor import cloud_daily as m

        class Store:
            token = 'fixture-token'
        newer = record(candidate_id='e' * 24)
        held = record(candidate_id='f' * 24)
        # Packed runtime: the previous run's restored base had CID and held; the run then held f (removed)
        # and approved e, but its upload failed.
        save(self.root / 'cache/ai_publish/remote.json', {'sha': '1' * 40, 'approved': {CID: record(), 'f' * 24: held}})
        auto_release.save_approved(self.root, {CID: record(), 'e' * 24: newer})
        remote = {CID: record(status='withdrawn', withdrawn_reason='body_changed'), 'f' * 24: held,
                  'g' * 24: record(candidate_id='g' * 24)}
        order = []

        def restored_ai(root, repository, env=None):
            order.append('restore_ai')
            save(Path(root) / 'cache/ai_publish/approved.json', remote)
            save(Path(root) / 'cache/ai_publish/remote.json', {'sha': '2' * 40, 'approved': remote})
            return True
        with patch.object(m, 'restore_mirror', side_effect=lambda *a, **k: order.append('restore') or 'a' * 40), \
                patch.object(m, 'restore_ai', side_effect=restored_ai):
            self.assertEqual(m.restore_public(self.root, Store(), NOW), 'a' * 40)
        self.assertEqual(order, ['restore', 'restore_ai'])
        approved, _ = auto_release.load(self.root)
        self.assertEqual(sorted(approved), sorted([CID, 'e' * 24, 'g' * 24]))
        self.assertEqual(approved[CID]['status'], 'withdrawn')
        # An empty pack (first run) never deletes remote approvals.
        (self.root / 'cache/ai_publish/remote.json').unlink()
        auto_release.save_approved(self.root, {})
        with patch.object(m, 'restore_mirror', return_value='a' * 40), patch.object(m, 'restore_ai', side_effect=restored_ai):
            m.restore_public(self.root, Store(), NOW)
        self.assertEqual(sorted(auto_release.load(self.root)[0]), sorted(remote))
        for corrupt in ('approved.json', 'remote.json'):
            with self.subTest(corrupt=corrupt):
                save(self.root / 'cache/ai_publish/remote.json', {'sha': '1' * 40, 'approved': remote})
                auto_release.save_approved(self.root, {'h' * 24: record(candidate_id='h' * 24)})
                (self.root / 'cache/ai_publish' / corrupt).write_text('{broken')
                with patch.object(m, 'restore_mirror', return_value='a' * 40), patch.object(m, 'restore_ai', side_effect=restored_ai):
                    m.restore_public(self.root, Store(), NOW)
                self.assertEqual(auto_release.load(self.root)[0], remote, 'unreadable pack or base keeps the remote copy')
                self.assertFalse(json.loads((self.root / 'cache/ai_publish/restore-note.json').read_text())
                                 ['packed_ok' if corrupt == 'approved.json' else 'base_ok'])
        with patch.object(m, 'restore_mirror', return_value='a' * 40), patch.object(m, 'restore_ai', return_value=False):
            with self.assertRaisesRegex(ValueError, 'before any paid call'):
                m.restore_public(self.root, Store(), NOW)


class StoreDecisionTests(unittest.TestCase):
    def test_corrupt_approved_is_moved_aside_not_silently_overwritten(self):
        from benefit_monitor.ai_review import _store_decision
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as folder:
            root = Path(folder)
            (root / 'cache/ai_publish').mkdir(parents=True)
            (root / 'cache/ai_publish/approved.json').write_text('{"half":')
            (root / 'cache/ai_publish/decisions.json').write_text('[not a dict]')
            save(root / 'cache/ai_publish/remote.json', {'sha': '1' * 40, 'approved': {}})
            decision = {'publish': True, 'reasons': [], 'record': record()}
            _store_decision(root, CID, decision, {'run_id': 'r', 'signature': 's'}, NOW)
            # No partial list that a later save_ai could upload as the whole list; the lease is gone.
            self.assertFalse((root / 'cache/ai_publish/approved.json').exists())
            self.assertFalse((root / 'cache/ai_publish/remote.json').exists())
            self.assertEqual(json.loads((root / 'cache/ai_publish/decisions.json').read_text())[CID]['publish'], True)
            aside = sorted(p.name for p in (root / 'cache/ai_publish').glob('*.corrupt-*.json'))
            self.assertEqual(len(aside), 2)
            self.assertEqual((root / 'cache/ai_publish' / next(a for a in aside if a.startswith('approved'))).read_text(), '{"half":')
            from benefit_monitor import mirror
            with patch('benefit_monitor.mirror.subprocess.run', side_effect=AssertionError('must not write')):
                with self.assertRaises(ValueError):
                    mirror.save_ai(root, 'Kim-Taesu/benefit-monitor')
            # Later decisions in the same run still cannot be uploaded (no lease until the next restore).
            _store_decision(root, 'b' * 24, dict(decision, record=record(candidate_id='b' * 24)), {'run_id': 'r', 'signature': 's'}, NOW)
            with patch('benefit_monitor.mirror.subprocess.run', side_effect=AssertionError('must not write')):
                with self.assertRaises(ValueError):
                    mirror.save_ai(root, 'Kim-Taesu/benefit-monitor')


class TabPickRecheckTests(unittest.TestCase):
    """Festival and benefit picks (2026-11-14) are re-checked on every publish path."""

    def setUp(self):
        import test_benefit_pick as tb, test_festival_pick as tf
        from benefit_monitor import benefit_pick as bp, festival_pick as fp
        self.tb, self.tf, self.bp, self.fp = tb, tf, bp, fp
        self.data = {'items': list(tb.ITEMS), 'festivals': tf.BUNDLE,
                     'benefit_pick': bp.public(tb.stored(), tb.ITEMS, [], tb.NOW),
                     'festival_pick': fp.public(tf.stored(), tf.BUNDLE, [], tf.NOW)}

    def test_unchanged_picks_survive(self):
        out = auto_release.recheck_tab_picks(deepcopy(self.data), [], self.tb.NOW)
        self.assertEqual(out['benefit_pick'], self.data['benefit_pick'])
        self.assertEqual(out['festival_pick'], self.data['festival_pick'])
        self.assertEqual(out['benefit_pick']['source'], 'ai')

    def test_removed_item_drops_its_line_and_the_summary(self):
        data = deepcopy(self.data)
        gone = self.data['benefit_pick']['picks'][0]
        data['items'] = [r for r in data['items'] if (r['source'], r['url']) != (gone['source'], gone['url'])]
        out = auto_release.recheck_tab_picks(data, [], self.tb.NOW)
        self.assertNotIn(gone['url'], [p['url'] for p in out['benefit_pick']['picks']])
        self.assertIsNone(out['benefit_pick']['summary'])

    def test_rechecking_twice_keeps_a_dropped_line_pick(self):
        tb, tf, bp, fp = self.tb, self.tf, self.bp, self.fp
        extra = tb.row('seoul', 'https://x.kr/1', '제철 차 학습라운지', '무료 교육 운영', '16개 프로그램 무료 운영', 'free')
        bpick = tb.stored(picks=tb.draft()['picks'] + [dict(id=bp.item_id(extra), line='학습라운지 교육')])
        fpicks = [dict(id=tf.APPLE, line='무료, 일부 체험 유료'), dict(id=tf.POHANG, line='무료, 밤 불빛 행사'),
                  dict(id=tf.GAME, line='무료 전시'), dict(id=tf.BUSAN, line='하루 무료 공연')]
        data = {'items': list(tb.ITEMS) + [extra], 'festivals': tf.BUNDLE,
                'benefit_pick': bp.public(bpick, list(tb.ITEMS) + [extra], [], tb.NOW),
                'festival_pick': fp.public(tf.stored(picks=fpicks), tf.BUNDLE, [], tf.NOW)}
        self.assertEqual((data['benefit_pick']['source'], data['festival_pick']['source']), ('ai', 'ai'))
        data['items'] = [r for r in data['items'] if r is not tb.COGPE]
        data['festivals'] = dict(tf.BUNDLE, items=[r for r in tf.BUNDLE['items'] if r['id'] != tf.BUSAN])
        once = auto_release.recheck_tab_picks(data, [], tb.NOW)
        twice = auto_release.recheck_tab_picks(deepcopy(once), [], tb.NOW)
        for key in ('benefit_pick', 'festival_pick'):
            self.assertEqual((once[key]['source'], once[key]['summary'], len(once[key]['picks'])), ('ai', None, 3), key)
            self.assertEqual(twice[key], once[key], key)

    def test_takedowns_mute_the_ai_text(self):
        takedowns = [{'kind': 'benefit_pick_text', 'day': '2026-11-14'}, {'kind': 'festival_pick_text', 'day': '2026-11-14'}]
        out = auto_release.recheck_tab_picks(deepcopy(self.data), takedowns, self.tb.NOW)
        self.assertEqual((out['benefit_pick']['source'], out['festival_pick']['source']), ('rule', 'rule'))

    def test_missing_data_removes_the_pick(self):
        data = deepcopy(self.data)
        data['items'] = []
        data.pop('festivals')
        out = auto_release.recheck_tab_picks(data, [], self.tb.NOW)
        self.assertNotIn('benefit_pick', out)
        self.assertNotIn('festival_pick', out)

    def test_apply_takedowns_rechecks_the_benefit_pick(self):
        data = deepcopy(self.data)
        for row in data['items']:
            row.setdefault('review', {'kind': 'human'})
        out = auto_release.apply_takedowns(data, [{'kind': 'benefit_pick_text', 'day': '2026-11-14'}], now=self.tb.NOW)
        self.assertEqual(out['benefit_pick']['source'], 'rule')


if __name__ == '__main__':
    unittest.main()
