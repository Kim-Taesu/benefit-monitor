from datetime import datetime, timezone
import gzip
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_cloud_state as fixtures  # noqa: E402

from benefit_monitor import response_archive as archive  # noqa: E402
from benefit_monitor.age_state import pack_runtime, runtime_headroom  # noqa: E402
from benefit_monitor.cloud_state import GitHubStateStore, CloudSession, file_name  # noqa: E402

RESPONSES = '.tools/claude-trial/live/responses'


def runtime_names(raw):
    with tarfile.open(fileobj=io.BytesIO(gzip.decompress(raw)), mode='r:') as tar:
        return tar.getnames()


class ShardTests(unittest.TestCase):
    def test_half_month_by_seoul_date(self):
        self.assertEqual(archive.shard_of(datetime(2026, 11, 15, 14, 59, tzinfo=timezone.utc)), '2026-11a')
        self.assertEqual(archive.shard_of(datetime(2026, 11, 15, 15, 0, tzinfo=timezone.utc)), '2026-11b')  # 16일 0시 KST
        self.assertEqual(archive.shard_of(datetime(2026, 11, 30, 15, 0, tzinfo=timezone.utc)), '2026-12a')

    def test_file_names_are_fixed_patterns_only(self):
        self.assertEqual(file_name('responses-2026-11b'), 'ai-responses-2026-11b.age')
        for bad in ('responses-2026-13a', 'responses-../x', 'responses-2026-11c', 'other'):
            with self.assertRaises(ValueError):
                file_name(bad)

    def test_unpack_rejects_unexpected_members(self):
        with self.assertRaises(ValueError):
            archive.unpack(archive.pack({'../budget.json': b'x'}))
        with self.assertRaises(ValueError):
            archive.unpack(archive.pack({'notes.txt': b'x'}))


class ArchiveTests(fixtures.CloudStateTests.__base__):
    setUp = fixtures.CloudStateTests.setUp
    module = fixtures.CloudStateTests.module
    store = fixtures.CloudStateTests.store
    session = fixtures.CloudStateTests.session

    def put(self, root, request_id, body=b'{"ok":true}', suffix='.json'):
        path = Path(root) / RESPONSES / (request_id + suffix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        return path

    def test_old_runtime_with_responses_migrates_into_a_shard(self):
        # The runtime saved before this change still carries the response files.
        first = f'{1:064x}'
        store = self.store()
        old = io.BytesIO()
        with tarfile.open(fileobj=old, mode='w') as tar:
            info = tarfile.TarInfo(RESPONSES + '/' + first + '.json')
            info.size = len(b'{"ok":true}')
            tar.addfile(info, io.BytesIO(b'{"ok":true}'))
        self.control['runtime_sha'] = store.write('runtime', gzip.compress(old.getvalue(), mtime=0), None)
        store.write('control', json.dumps(self.control).encode(), None)
        session = CloudSession.restore(self.root, store)
        self.assertTrue((self.root / RESPONSES / (first + '.json')).exists())
        session.save_runtime()
        runtime = runtime_names(self.remote.files['ai-runtime.age'][len(b'age-fixture:'):])
        self.assertFalse(any(name.startswith(RESPONSES) for name in runtime))
        shard = archive.unpack(self.remote.files['ai-responses-2026-11a.age'][len(b'age-fixture:'):])
        self.assertEqual(shard, {first + '.json': b'{"ok":true}'})
        # A fresh machine gets the response back from the shard, not from the runtime.
        with tempfile.TemporaryDirectory(dir=fixtures.ROOT) as other:
            fixtures.save(Path(other) / 'public/ai-cloud-trial.json', self.policy)
            CloudSession.restore(other, GitHubStateStore(other, 'fake-personal-token', self.crypto, opener=self.remote))
            self.assertEqual((Path(other) / RESPONSES / (first + '.json')).read_bytes(), b'{"ok":true}')

    def test_unchanged_shard_is_not_written_again(self):
        self.put(self.root, f'{2:064x}')
        session = self.session()
        session.save_runtime()
        writes = sum(r.get_method() == 'PUT' and 'ai-responses' in r.full_url for r in self.remote.requests)
        session.save_runtime()
        again = sum(r.get_method() == 'PUT' and 'ai-responses' in r.full_url for r in self.remote.requests)
        self.assertEqual(writes, again)

    def test_a_missing_local_file_never_shrinks_a_shard(self):
        path = self.put(self.root, f'{3:064x}')
        session = self.session()
        session.save_runtime()
        path.unlink()
        with self.assertRaises(ValueError):
            session.save_runtime()
        self.assertIn(path.name, archive.unpack(self.remote.files['ai-responses-2026-11a.age'][len(b'age-fixture:'):]))

    def test_shard_not_read_at_restore_is_merged_not_overwritten(self):
        store = self.store()
        store.write('responses-2026-12a', archive.pack({f'{9:064x}.json': b'remote'}), None)
        archive.restore(self.root, store, self.control['budget'])  # ledger has no 12a row
        self.put(self.root, 'e' * 64, b'new')  # no ledger row: goes to the current half-month
        written = archive.save_all(self.root, store, self.control['budget'], datetime(2026, 12, 3, tzinfo=timezone.utc))
        self.assertEqual(written, {'2026-12a': 2})
        self.assertEqual(set(archive.unpack(self.remote.files['ai-responses-2026-12a.age'][len(b'age-fixture:'):])),
                         {f'{9:064x}.json', 'e' * 64 + '.json'})

    def test_restore_refuses_a_conflicting_local_copy(self):
        store = self.store()
        name = f'{1:064x}.json'
        store.write('responses-2026-11a', archive.pack({name: b'remote'}), None)
        self.put(self.root, f'{1:064x}', b'different')
        with self.assertRaises(ValueError):
            archive.restore(self.root, store, self.control['budget'])

    def test_preflight_size_no_longer_counts_responses(self):
        self.put(self.root, f'{4:064x}', b'x' * 4096)
        self.assertFalse(any(name.startswith(RESPONSES) for name in runtime_names(pack_runtime(self.root))))
        self.assertIsNone(runtime_headroom(self.root))


if __name__ == '__main__':
    unittest.main()
