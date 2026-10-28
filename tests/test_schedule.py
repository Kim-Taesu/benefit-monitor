import json
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import publish
from benefit_monitor.store import save


class ScheduleTests(unittest.TestCase):
    def test_workflow_is_the_single_daily_schedule_source(self):
        self.assertEqual(publish.collection_time(), time(6))
        with tempfile.TemporaryDirectory() as directory:
            workflow = Path(directory) / 'workflow.yml'
            workflow.write_text("on:\n  schedule:\n    - cron: '15 22 * * *'\n  workflow_dispatch:\n")
            self.assertEqual(publish.collection_time(workflow), time(7, 15))
            workflow.write_text("on:\n  schedule:\n    - cron: '0 */2 * * *'\n")
            with self.assertRaises(ValueError):
                publish.collection_time(workflow)

    def test_six_am_boundary_and_trigger(self):
        now = datetime.fromisoformat('2026-10-29T06:00:00+09:00')
        for event, expected in [('schedule', True), ('workflow_dispatch', False), ('push', False), ('', False)]:
            with self.subTest(event=event):
                context = publish.run_context(now, now, event)
                self.assertEqual(context['expected_collection_at'], now.isoformat())
                self.assertEqual(context['scheduled_run_confirmed'], expected)
        before = now.replace(hour=5, minute=59)
        context = publish.run_context(before, before, 'schedule')
        self.assertEqual(context['status'], 'pre_schedule_snapshot')
        self.assertFalse(context['scheduled_run_confirmed'])

    def test_export_times_and_failure_are_honest(self):
        now = datetime.fromisoformat('2026-10-29T06:03:00+09:00')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            save(root / 'sources.yaml', {'sources': [], 'max_age_days': 7})
            save(root / 'public/verified.json', [])
            save(root / 'report.json', {'verified_at': now.isoformat(), 'complete': False, 'needs_recheck': [],
                 'collection': {'online': True, 'successful_sources': ['test']}})
            with patch.dict('os.environ', {'GITHUB_EVENT_NAME': 'schedule'}):
                result = publish.run(root, now=now)
                self.assertEqual(result['generated_at'], now.isoformat())
                self.assertEqual(result['source_report_at'], now.isoformat())
                self.assertEqual(result['valid_through'], '2026-10-30T00:00:00+09:00')
                self.assertTrue(result['run_context']['scheduled_run_confirmed'])
                failed = publish.run(root, now=now, failure=True)
                self.assertIsNone(failed['valid_through'])
                self.assertFalse(failed['run_context']['scheduled_run_confirmed'])
                saved = json.loads((root / 'delivery/public/briefing.json').read_text())
                self.assertEqual(saved['status'], 'collection_failed')
