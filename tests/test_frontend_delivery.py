import json
import tempfile
import unittest
from pathlib import Path
from scripts.assemble_pages import assemble

ROOT = Path(__file__).resolve().parents[1]


class FrontendDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'frontend/dist/assets').mkdir(parents=True)
        (self.root / 'delivery/public').mkdir(parents=True)
        (self.root / 'frontend/dist/index.html').write_text('<html lang="ko">app</html>')
        (self.root / 'frontend/dist/assets/app.js').write_text('export{}')
        for name, content in [('briefing.json', '{"status":"collection_failed","items":[]}\n'), ('briefing.md', '# Public\n')]:
            (self.root / 'delivery/public' / name).write_text(content)
        (self.root / 'delivery/public/index.html').write_text('legacy')

    def test_assembles_exact_public_bytes_and_only_app_assets(self):
        out = assemble(self.root)
        for name in ['briefing.json', 'briefing.md']:
            self.assertEqual((out / name).read_bytes(), (self.root / 'delivery/public' / name).read_bytes())
        self.assertEqual((out / 'index.html').read_text(), '<html lang="ko">app</html>')
        self.assertTrue((out / 'assets/app.js').exists())
        self.assertEqual({p.name for p in (self.root / 'delivery/public').iterdir()}, {'index.html', 'briefing.json', 'briefing.md'})
        (out / 'assets/obsolete.js').write_text('old')
        assemble(self.root)
        self.assertFalse((out / 'assets/obsolete.js').exists())

    def test_admin_page_is_staged_but_other_html_is_not(self):
        (self.root / 'frontend/dist/admin.html').write_text('<html lang="ko">admin</html>')
        out = assemble(self.root)
        self.assertEqual((out / 'admin.html').read_text(), '<html lang="ko">admin</html>')
        (self.root / 'frontend/dist/other.html').write_text('x')
        with self.assertRaises(ValueError):
            assemble(self.root)

    def test_private_and_unexpected_build_files_are_rejected_before_replacement(self):
        out = assemble(self.root)
        (self.root / 'frontend/dist/report.json').write_text('private')
        with self.assertRaises(ValueError):
            assemble(self.root)
        self.assertTrue((out / 'index.html').exists())
        self.assertFalse((out / 'report.json').exists())

    def test_symlink_build_files_are_rejected(self):
        (self.root / 'frontend/dist/assets/leak.js').symlink_to(self.root / 'delivery/public/briefing.json')
        with self.assertRaises(ValueError):
            assemble(self.root)

    def test_checked_in_source_policy_matches_collector_allowlists(self):
        policy=json.loads((ROOT/'frontend/src/source-policy.json').read_text())
        config=json.loads((ROOT/'sources.yaml').read_text())
        self.assertEqual(policy['maxAgeDays'],config['max_age_days'])
        self.assertEqual(policy['sources'],{s['id']:{'name':s.get('name',s['id']),'domains':s['domains']} for s in config['sources']})
        self.assertEqual(policy['districts'],[d['name'] for d in json.loads((ROOT/'districts.json').read_text())['districts']])
