import unittest
from datetime import datetime
from unittest.mock import patch

from benefit_monitor import pipeline_timing as pt
from benefit_monitor import publish

NOW = datetime.fromisoformat('2026-11-20T04:30:00+09:00')


def utc(kst):
    """'HH:MM' on 2026-11-20 KST as GitHub's UTC string."""
    return datetime.fromisoformat('2026-11-20T' + kst + ':00+09:00').astimezone(pt.SEOUL).isoformat()


def run(rid, created, conclusion='success', title='수집', status='completed'):
    return {'id': rid, 'created_at': utc(created), 'status': status, 'conclusion': conclusion, 'display_title': title}


def jobs(step_name, start, end, conclusion='success'):
    return {'jobs': [{'steps': [{'name': 'Set up job', 'conclusion': 'success', 'started_at': utc(start), 'completed_at': utc(start)},
                                {'name': step_name, 'conclusion': conclusion, 'started_at': utc(start), 'completed_at': utc(end)}]}]}


class FakeGitHub:
    def __init__(self, runs, jobs):
        self.runs, self.jobs = runs, jobs

    def __call__(self, path):
        if path.startswith('actions/workflows/'):
            return {'workflow_runs': self.runs.get(path.split('/')[2], [])}
        return self.jobs[int(path.split('/')[2])]


class GateTests(unittest.TestCase):
    def test_manual_runs_always_run(self):
        self.assertEqual(pt.gate(pt.BRIEFING, False, lambda p: 1 / 0, NOW), 'true')

    def test_scheduled_run_skips_after_todays_success_only(self):
        yesterday = dict(run(1, '03:00'), created_at='2026-11-19T00:00:00+09:00')
        github = FakeGitHub({pt.BRIEFING: [yesterday]}, {})
        self.assertEqual(pt.gate(pt.BRIEFING, True, github, NOW), 'true')
        github.runs[pt.BRIEFING] = [run(2, '04:00')]
        self.assertEqual(pt.gate(pt.BRIEFING, True, github, NOW), 'false')

    def test_snapshot_deploys_and_failures_do_not_count_as_collection(self):
        github = FakeGitHub({pt.BRIEFING: [run(3, '04:10', title='승인 스냅샷 게시'), run(4, '04:00', conclusion='failure'),
                                           run(5, '04:20', status='in_progress', conclusion=None)]}, {})
        self.assertEqual(pt.gate(pt.BRIEFING, True, github, NOW), 'true')

    def test_own_run_and_other_workflows(self):
        github = FakeGitHub({'health-notices.yml': [run(7, '03:20', title='Health notices')]}, {})
        self.assertEqual(pt.gate('health-notices.yml', True, github, NOW), 'false')
        self.assertEqual(pt.gate('health-notices.yml', True, github, NOW, self_id='7'), 'true')

    def test_unreadable_run_list_runs_anyway(self):
        self.assertEqual(pt.gate(pt.BRIEFING, True, lambda p: 1 / 0, NOW), 'true')


class CrawlWindowTests(unittest.TestCase):
    def github(self):
        return FakeGitHub(
            {'health-notices.yml': [run(10, '03:20', title='Health notices')],
             'subscriptions.yml': [run(11, '03:30', title='Subscriptions')],
             pt.BRIEFING: [run(13, '04:15', title='승인 스냅샷 게시'), run(12, '03:40')]},
            {10: jobs('Collect district health-centre notice boards', '03:21', '03:23'),
             11: jobs('Collect Seoul·Gyeonggi 청약 schedule', '03:31', '03:36'),
             12: jobs('Collect and export public briefing', '03:42', '03:47'),
             13: jobs('Collect and export public briefing', '04:16', '04:16', conclusion='skipped')})

    def test_sums_todays_crawl_steps(self):
        window = pt.crawl_window(self.github(), NOW)
        self.assertEqual(window, {'collect_started_at': '2026-11-20T03:21:00+09:00',
                                  'collect_finished_at': '2026-11-20T03:47:00+09:00', 'collect_seconds': 12 * 60})

    def test_without_todays_collection_there_is_no_timing(self):
        github = self.github()
        github.runs[pt.BRIEFING] = []
        self.assertIsNone(pt.crawl_window(github, NOW))

    def test_health_after_the_collection_is_left_out(self):
        github = self.github()
        github.jobs[10] = jobs('Collect district health-centre notice boards', '03:50', '03:52')
        self.assertEqual(pt.crawl_window(github, NOW)['collect_seconds'], 10 * 60)


class SanitizeTests(unittest.TestCase):
    base = {'collect_started_at': '2026-11-20T03:21:00+09:00', 'collect_finished_at': '2026-11-20T03:47:00+09:00',
            'collect_seconds': 720, 'ai_started_at': '2026-11-20T03:48:00+09:00', 'ai_finished_at': '2026-11-20T04:01:00+09:00'}

    def test_valid_timing_and_publication(self):
        self.assertEqual(pt.sanitize(self.base, NOW), self.base)
        published = pt.mark_published({'pipeline_timing': dict(self.base)}, NOW)['pipeline_timing']
        self.assertEqual(published['published_at'], NOW.isoformat())
        self.assertEqual(pt.sanitize(published, NOW), published)

    def test_rejects_disorder_future_old_extra_and_bad_seconds(self):
        cases = [dict(self.base, ai_started_at='2026-11-20T03:40:00+09:00'),
                 dict(self.base, ai_finished_at='2026-11-20T05:00:00+09:00'),
                 dict(self.base, collect_started_at='2026-11-19T03:00:00+09:00'),
                 dict(self.base, note='x'), dict(self.base, collect_seconds=99999),
                 dict(self.base, collect_seconds=1.5), dict(self.base, ai_started_at='2026-11-20T03:48:00'),
                 {k: v for k, v in self.base.items() if k != 'ai_finished_at'}, None, 'x']
        for value in cases:
            with self.subTest(value=value):
                self.assertIsNone(pt.sanitize(value, NOW))


class ExternalScheduleContextTests(unittest.TestCase):
    def test_external_cron_counts_as_scheduled(self):
        now = datetime.fromisoformat('2026-11-20T03:47:00+09:00')
        context = publish.run_context(now, now, 'external_schedule')
        self.assertEqual(context['status'], 'scheduled_refresh')
        self.assertTrue(context['scheduled_run_confirmed'])
        self.assertEqual(context['trigger'], 'external_schedule')
        self.assertEqual(publish.run_context(now, now, 'workflow_dispatch')['status'], 'manual_refresh')

    def test_workflow_files_wire_the_gate(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1] / '.github/workflows'
        for name in pt.CRAWLS:
            text = (root / name).read_text()
            with self.subTest(workflow=name):
                self.assertIn('external_schedule:', text)
                self.assertIn('--gate ' + name, text)
        briefing = (root / pt.BRIEFING).read_text()
        self.assertIn("|| '수집' }}", briefing)
        self.assertIn("needs.gate.outputs.run == 'true'", briefing)
        self.assertIn('BENEFIT_EXTERNAL_SCHEDULE', briefing)


if __name__ == '__main__':
    unittest.main()
