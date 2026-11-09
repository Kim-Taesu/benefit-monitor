"""The packed private runtime stays bounded without dropping anything a current record needs."""
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest

from benefit_monitor import runtime_retention as retention
from benefit_monitor.store import save

NOW = datetime.fromisoformat('2026-11-30T07:00:00+09:00')
OLD = (NOW - timedelta(days=15)).isoformat()
NEW = (NOW - timedelta(days=13)).isoformat()


def h(char):
    return char * 64


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1])
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def run_dir(self, rid, at):
        save(self.root / retention.RUNS / rid / 'input.json', {'now': at})
        save(self.root / retention.RUNS / rid / 'metadata.json', {})
        return self.root / retention.RUNS / rid

    def input_file(self, sig, at):
        save(self.root / retention.INPUTS / (sig + '.json'), {'now': at})
        return self.root / retention.INPUTS / (sig + '.json')

    def document(self, name, at):
        save(self.root / retention.DOCUMENTS / name, {'retrieved_at': at})
        return self.root / retention.DOCUMENTS / name

    def test_old_unreferenced_entries_go_and_referenced_or_recent_ones_stay(self):
        stale_run, state_run, approved_run, recent_run = (self.run_dir(h(c), t) for c, t in
                                                         (('1', OLD), ('2', OLD), ('3', OLD), ('4', NEW)))
        undated_run = self.run_dir(h('5'), 'not a time')
        stale_in, state_in, approved_in, recent_in = (self.input_file(h(c), t) for c, t in
                                                     (('a', OLD), ('b', OLD), ('c', OLD), ('d', NEW)))
        stale_doc = self.document(h('e') + '-' + h('f') + '.json', OLD)
        cached_doc = self.document(h('e') + '-' + h('0') + '.json', OLD)
        recent_doc = self.document(h('9') + '-' + h('8') + '.json', NEW)
        save(self.root / 'cache/ai_review/state.json', {'items': {'x' * 24: {
            'run_id': h('2'), 'input_file': retention.INPUTS + '/' + h('b') + '.json', 'signature': h('b')}}})
        save(self.root / 'cache/ai_publish/approved.json', {'y' * 24: {'candidate_id': 'y' * 24}})
        save(self.root / 'cache/ai_publish/decisions.json', {'y' * 24: {'run_id': h('3'), 'signature': h('c')},
                                                              'z' * 24: {'run_id': h('1'), 'signature': h('a')}})
        save(self.root / 'cache/ai_review/http.json', {'hosts': {}, 'pages': {h('e'): {
            'at': 0, 'file': retention.DOCUMENTS + '/' + cached_doc.name}}})
        result = retention.prune(self.root, NOW)
        self.assertEqual(result, {'status': 'pruned', 'runs': 1, 'inputs': 1, 'documents': 1})
        self.assertFalse(stale_run.exists() or stale_in.exists() or stale_doc.exists())
        for kept in (state_run, approved_run, recent_run, undated_run, state_in, approved_in, recent_in,
                     cached_doc, recent_doc):
            self.assertTrue(kept.exists(), kept)

    def test_verification_runs_are_kept_only_three_days(self):
        old_verify = self.run_dir(h('5'), (NOW - timedelta(days=4)).isoformat())
        save(old_verify / 'metadata.json', {'kind': 'verify'})
        new_verify = self.run_dir(h('6'), (NOW - timedelta(days=2)).isoformat())
        save(new_verify / 'metadata.json', {'kind': 'verify'})
        research = self.run_dir(h('7'), (NOW - timedelta(days=4)).isoformat())
        save(research / 'metadata.json', {'kind': 'research'})
        for name in ('cache/ai_review/state.json', 'cache/ai_publish/approved.json',
                     'cache/ai_publish/decisions.json', 'cache/ai_review/http.json'):
            save(self.root / name, {})
        retention.prune(self.root, NOW)
        self.assertEqual((old_verify.exists(), new_verify.exists(), research.exists()), (False, True, True))

    def test_unreadable_reference_file_prunes_nothing(self):
        stale = self.run_dir(h('1'), OLD)
        (self.root / 'cache/ai_publish').mkdir(parents=True)
        (self.root / 'cache/ai_publish/approved.json').write_text('{broken')
        self.assertEqual(retention.prune(self.root, NOW)['status'], 'skipped_unreadable_references')
        self.assertTrue(stale.exists())

    def test_ledger_responses_and_review_queue_are_never_touched(self):
        response = self.root / '.tools/claude-trial/live/responses' / (h('1') + '.json')
        queue = self.root / 'cache/ai_review/queue' / (h('2') + '.json')
        save(response, {'now': OLD})
        save(queue, {'now': OLD, 'observed_at': OLD})
        retention.prune(self.root, NOW)
        self.assertTrue(response.exists() and queue.exists())


if __name__ == '__main__':
    unittest.main()
