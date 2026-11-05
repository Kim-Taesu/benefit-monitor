from datetime import datetime
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

from benefit_monitor.review_desk import Desk
from benefit_monitor.store import load, save

ROOT = Path(__file__).resolve().parents[1]
SEOUL = ZoneInfo('Asia/Seoul')
NOW = datetime(2026, 11, 5, 19, 0, tzinfo=SEOUL)
BODY = '서울 정원 체험 안내. 참가비는 무료입니다. 매주 토요일 운영합니다.'
SIG = 'a' * 64
RUN = 'b' * 64


class ReviewDeskTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        save(self.root/'sources.yaml', {'max_age_days': 14, 'sources': [{'id': 'seoul', 'domains': ['www.seoul.go.kr']}]})
        save(self.root/'public/verified.json', [])
        doc = dict(id='doc-1', source_id='seoul', final_url='https://www.seoul.go.kr/n/1', requested_url='https://www.seoul.go.kr/n/1',
                   fetch_status='ok', body=BODY, body_hash=hashlib.sha256(BODY.encode()).hexdigest(), published_at='2026-11-04')
        save(self.root/'.tools/ai-inputs'/(SIG + '.json'), dict(
            candidates=[dict(candidate_id='cand-1', source_id='seoul', title='정원 체험', document_ids=['doc-1'])], documents=[doc]))
        save(self.root/'cache/ai_review/queue'/(SIG + '.json'), dict(
            candidate_id='cand-1', source='seoul', url='https://www.seoul.go.kr/n/1', signature=SIG,
            input_file='.tools/ai-inputs/' + SIG + '.json', model_status='validated_draft', run_id=RUN,
            review_status='pending_human_review', publication_approved=False, observed_at='2026-11-04T10:00:00+09:00'))
        claims = [dict(id='c1', field='fee_status', value='free', status='supported',
                       evidence=[dict(source_ref='doc-1', quote='참가비는 무료입니다.', locator='d1s2')]),
                  dict(id='c2', field='selection', value=None, status='unknown', evidence=[])]
        proposed = dict(summary='토요일 정원 체험', conditions='매주 토요일 운영', valid_from=None, valid_until='2026-11-30',
                        deadline_at=None, published_at=None, districts=['중구'], labels=None, payment_terms=None,
                        benefit_value=None, fee_status='free')
        save(self.root/'.tools/claude-trial/live/runs'/RUN/'result.json', dict(records=[dict(
            claims=claims, proposed_fields=proposed,
            missing_questions=[dict(field='selection', reason='선정 방식 미기재', importance='critical', question='q')])]))
        save(self.root/'.tools/claude-trial/live/runs'/RUN/'validation.json', {'valid': True, 'errors': []})

    def desk(self, minutes=0):
        return Desk(self.root, NOW.replace(minute=minutes))

    def test_pending_show_and_page_never_approve(self):
        self.assertIn('정원 체험', self.desk().list())
        text = self.desk(1).show('aaaa')
        self.assertIn('«참가비는 무료입니다.»', text)
        self.assertIn('선정 방식 미기재', text)
        page = self.desk(2).page('aaaa').read_text()
        self.assertIn('<mark>참가비는 무료입니다.</mark>', page)
        self.assertEqual(load(self.root/'public/verified.json', None), [])

    def test_prepare_then_confirmed_approval_runs_public_gates(self):
        self.desk(1).show('aaaa')
        draft_path = self.desk(2).prepare('aaaa')
        draft = load(draft_path, None)
        self.assertIsNone(draft['verified_at'])
        self.assertFalse(draft['public_release'])
        self.assertIn('미확인: 선정 방식', draft['conditions'])
        self.assertIn('참가비는 무료입니다.', draft['evidence'])
        with self.assertRaisesRegex(ValueError, 'confirm'):
            self.desk(3).approve('aaaa')
        self.assertEqual(load(self.root/'public/verified.json', None), [])
        entry = self.desk(4).approve('aaaa', confirm=True)
        self.assertEqual(entry['review_seconds'], 180)
        public = load(self.root/'public/verified.json', None)
        self.assertEqual(len(public), 1)
        self.assertTrue(public[0]['public_release'])
        self.assertFalse(public[0]['needs_recheck'])
        self.assertEqual(public[0]['verified_at'], NOW.replace(minute=4).isoformat())
        self.assertNotIn('_review', public[0])
        with self.assertRaisesRegex(ValueError, 'decision'):
            self.desk(5).approve('aaaa', confirm=True)
        self.assertEqual(self.desk(6).list(), '검토 대기 없음')

    def test_private_text_or_swapped_url_is_refused_without_writing(self):
        path = self.desk(1).prepare('aaaa')
        draft = load(path, None)
        save(path, dict(draft, conditions='문의 someone@example.com'))
        with self.assertRaisesRegex(ValueError, 'private'):
            self.desk(2).approve('aaaa', confirm=True)
        save(path, dict(draft, url='https://www.seoul.go.kr/n/other'))
        with self.assertRaisesRegex(ValueError, 'belong'):
            self.desk(3).approve('aaaa', confirm=True)
        self.assertEqual(load(self.root/'public/verified.json', None), [])

    def test_reject_requires_reason_and_stats_track_backlog(self):
        stats = self.desk().stats()
        self.assertEqual((stats['pending'], stats['pending_over_one_day']), (1, 1))
        with self.assertRaisesRegex(ValueError, 'reason'):
            self.desk(1).reject('aaaa', ' ')
        self.desk(1).show('aaaa')
        self.desk(3).reject('aaaa', '원문과 다른 행사')
        stats = self.desk(4).stats()
        self.assertEqual((stats['rejected'], stats['pending'], stats['median_review_minutes']), (1, 0, 2.0))

    def test_expiring_lists_earliest_reason_once(self):
        save(self.root/'public/verified.json', [
            dict(title='곧 마감', url='https://www.seoul.go.kr/a', verified_at='2026-11-01T09:00:00+09:00',
                 valid_until='2026-11-06', deadline_at='2026-11-06T18:00:00+09:00'),
            dict(title='한참 남음', url='https://www.seoul.go.kr/b', verified_at='2026-11-05T09:00:00+09:00', valid_until='2026-12-31'),
            dict(title='이미 끝남', url='https://www.seoul.go.kr/c', verified_at='2026-10-01T09:00:00+09:00', valid_until='2026-11-01')])
        text = self.desk().expiring(7)
        self.assertEqual(text.count('곧 마감'), 1)
        self.assertIn('마감', text)
        self.assertNotIn('한참 남음', text)
        self.assertNotIn('이미 끝남', text)


if __name__ == '__main__':
    unittest.main()
