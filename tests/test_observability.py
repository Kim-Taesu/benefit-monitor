import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benefit_monitor import observability as obs

ROOT=Path(__file__).resolve().parents[1]


class ObservationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name)

    def rows(self):return json.loads((self.root/obs.FILE).read_text())

    def test_stage_wall_time_and_status_without_payload_or_exception_text(self):
        @obs.entry
        def run(root):
            with obs.span('collection','source_collection') as event:
                event.set_status('skipped','snapshot_reused')
            return obs.call('recommendation','benefit',lambda:{'source':'rule','used_fallback':True,'summary':'private text'})
        with patch.object(obs.time,'perf_counter',side_effect=[1,1.25,2,2.5]):
            result=run(self.root)
        self.assertTrue(result['used_fallback'])
        rows=self.rows();self.assertEqual([r['duration_ms'] for r in rows],[250,500])
        self.assertEqual([r['status'] for r in rows],['skipped','held'])
        self.assertEqual(len({r['attempt_id'] for r in rows}),1)
        self.assertNotIn('private text',json.dumps(rows))

    def test_failed_operation_rethrows_and_trace_never_logs_exception_message(self):
        @obs.entry
        def run(root):
            return obs.call('read','official_read',lambda:(_ for _ in ()).throw(ValueError('fake-secret-value')))
        with self.assertRaisesRegex(ValueError,'fake-secret-value'):run(self.root)
        row=self.rows()[0];self.assertEqual(row['status'],'failed')
        self.assertEqual(row['reason'],'operation_failed')
        self.assertNotIn('fake-secret',json.dumps(row))

    def test_observation_write_failure_does_not_change_success_or_original_error(self):
        @obs.entry
        def run(root):return obs.call('publication','auto_publish',lambda:{'publish':False,'reasons':['private text']})
        with patch.object(obs,'flush',side_effect=OSError('secret')),patch('sys.stderr'):
            self.assertFalse(run(self.root)['publish'])
            @obs.entry
            def broken(root):raise RuntimeError('original failure')
            with self.assertRaisesRegex(RuntimeError,'original failure'):broken(self.root)

    def test_nested_entry_keeps_one_attempt_and_retains_bounded_rows(self):
        @obs.entry
        def inner(root):return obs.call('validation','draft_validation',lambda:({}, {'valid':False}))
        @obs.entry
        def outer(root):return inner(root)
        with patch.object(obs,'MAX_ROWS',2):
            for _ in range(3):outer(self.root)
        self.assertEqual(len(self.rows()),2)
        self.assertEqual(len({r['attempt_id'] for r in self.rows()}),2)
        self.assertTrue(all(r['status']=='failed' for r in self.rows()))

    def test_no_active_trace_changes_nothing_and_saves_nothing(self):
        value={'body':'secret'}
        self.assertIs(obs.call('read','official_read',lambda:value),value)
        self.assertFalse((self.root/obs.FILE).exists())

    def test_extraction_missing_cost_is_unknown_and_request_id_is_safe(self):
        @obs.entry
        def run(root):return obs.call('extraction','model_invoke',lambda:{'status':'validated_draft','run_id':'a'*64})
        run(self.root);row=self.rows()[0]
        self.assertIsNone(row['cost_usd']);self.assertEqual(row['request_id'],'a'*64)

    def test_symlink_destination_is_not_written(self):
        target=self.root/'unrelated';target.mkdir()
        folder=self.root/'cache/ai_daily';folder.mkdir(parents=True)
        (folder/'observations.json').symlink_to(target/'outside.json')
        @obs.entry
        def run(root):return obs.call('read','official_read',lambda:{})
        with patch('sys.stderr'):run(self.root)
        self.assertFalse((target/'outside.json').exists())

    def test_offline_collection_records_skip_and_private_archive_roundtrip(self):
        from datetime import datetime
        from benefit_monitor.cli import run
        from benefit_monitor.store import save
        from benefit_monitor.age_state import pack_runtime, restore_runtime
        save(self.root/'sources.yaml', {'sources': []})
        result=run(self.root, now=datetime.fromisoformat('2026-11-14T07:00:00+09:00'))
        row=self.rows()[0]
        self.assertEqual((row['stage'],row['status'],row['reason']),('collection','skipped','offline'))
        self.assertIsInstance(result,dict)
        self.assertGreaterEqual(row['duration_ms'],0)
        raw=pack_runtime(self.root)
        restored=self.root/'restored'
        restore_runtime(restored,raw)
        self.assertEqual(json.loads((restored/obs.FILE).read_text()),self.rows())
        self.assertFalse((self.root/'public/observations.json').exists())

    def test_broken_stderr_does_not_replace_result_or_error(self):
        @obs.entry
        def run(root):return 42
        @obs.entry
        def broken(root):raise ValueError('original')
        with patch.object(obs,'flush',side_effect=OSError),patch('sys.stderr') as stderr:
            stderr.write.side_effect=BrokenPipeError
            self.assertEqual(run(self.root),42)
            with self.assertRaisesRegex(ValueError,'original'):broken(self.root)

    def test_stopped_before_result_is_not_success(self):
        @obs.entry
        def run(root):return obs.call('extraction','model_invoke',lambda:{'status':'stopped_before_result'})
        run(self.root)
        self.assertEqual(self.rows()[0]['status'],'failed')
