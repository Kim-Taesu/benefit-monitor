"""Free collection snapshot reused by the AI run; no network, no age binary."""
import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import cli, collection_snapshot as snap
from benefit_monitor.store import save, load
from test_pipeline import benefit, SOURCE, NOW


class CollectionSnapshotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        save(self.root/'sources.yaml', dict(sources=[dict(SOURCE, feed_url='https://official.example/feed')], max_age_days=7))
        self.item = benefit(); save(self.root/'inputs/items.json', [self.item.data()])
        self.candidate = dict(source='test', url='https://official.example/new', title='New notice', summary='candidate', needs_recheck=True)

    def collect_online(self):
        with patch('benefit_monitor.cli.collect', return_value=[self.candidate]):
            return cli.run(self.root, self.root/'inputs/items.json', True, NOW)

    def test_online_collection_records_snapshot(self):
        self.collect_online()
        data = load(self.root/snap.SNAPSHOT, None)
        self.assertEqual(data['schema_version'], 1)
        self.assertEqual(data['collected_at'], NOW.isoformat())
        self.assertEqual([c['url'] for c in data['incoming']], [self.candidate['url']])
        self.assertEqual(data['successful_sources'], ['test'])

    def test_run_with_snapshot_makes_no_listing_request_and_keeps_results(self):
        first = self.collect_online()
        data = load(self.root/snap.SNAPSHOT, None)
        with patch('benefit_monitor.cli.collect', side_effect=AssertionError('no listing fetch')):
            again = cli.run(self.root, self.root/'inputs/items.json', True, NOW + timedelta(hours=1), snapshot=data)
        self.assertEqual(again['cost_policy']['public_http_requests'], 0)
        self.assertEqual(again['collection']['successful_sources'], first['collection']['successful_sources'])
        self.assertEqual([r['id'] for r in again['review_queue']], [r['id'] for r in first['review_queue']])

    def test_only_todays_well_formed_snapshot_is_used(self):
        self.collect_online()
        raw = (self.root/snap.SNAPSHOT).read_bytes()
        self.assertIsNotNone(snap.parse_today(raw, NOW + timedelta(hours=2)))
        self.assertIsNone(snap.parse_today(raw, NOW + timedelta(days=1)))   # yesterday's collection
        self.assertIsNone(snap.parse_today(raw, NOW - timedelta(hours=1)))  # from the future
        bad = json.loads(raw); bad['incoming'] = 'x'
        self.assertIsNone(snap.parse_today(json.dumps(bad).encode(), NOW))
        self.assertIsNone(snap.parse_today(b'not json', NOW))

    def test_recipient_file_is_a_public_age_key(self):
        root = Path(__file__).resolve().parents[1]
        self.assertRegex(snap.recipient(root), r'^age1[a-z0-9]{20,200}$')


if __name__ == '__main__':
    unittest.main()
