import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/generate_source_policy.py'


class SourcePolicyGeneratorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'frontend/src').mkdir(parents=True)
        self.output = self.root / 'frontend/src/source-policy.json'
        self.config = {'max_age_days': 7, 'private': 'PRIVATE_MARKER', 'sources': [
            {'id': 'official', 'name': '공식', 'domains': ['official.example'], 'private': 'PRIVATE_MARKER'},
            {'id': 'second', 'domains': ['second.example']}]}
        self.districts = {'districts': [{'name': '은평구', 'code': 'private-code'}]}
        self.save()

    def save(self):
        for name, data in [('sources.yaml', self.config), ('districts.json', self.districts)]:
            (self.root / name).write_text(json.dumps(data), encoding='utf-8')

    def run_cli(self, *args, default_root=False):
        command = [sys.executable, str(SCRIPT)]
        if not default_root:
            command += ['--root', str(self.root)]
        return subprocess.run(command + list(args), cwd=self.root, text=True, capture_output=True)

    def test_generate_projects_only_public_fields_and_is_deterministic(self):
        result = self.run_cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        before = self.output.read_bytes()
        self.assertEqual(json.loads(before), {'maxAgeDays': 7, 'sources': {
            'official': {'name': '공식', 'domains': ['official.example']},
            'second': {'name': 'second', 'domains': ['second.example']}}, 'districts': ['은평구']})
        self.assertNotIn(b'PRIVATE_MARKER', before)
        self.assertNotIn(b'private-code', before)
        self.assertEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.output.read_bytes(), before)
        self.assertEqual(self.run_cli('--check').returncode, 0)

    def test_check_detects_missing_or_stale_file_without_writing(self):
        self.assertNotEqual(self.run_cli('--check').returncode, 0)
        self.assertFalse(self.output.exists())
        self.output.write_bytes(b'old-policy')
        self.assertNotEqual(self.run_cli('--check').returncode, 0)
        self.assertEqual(self.output.read_bytes(), b'old-policy')
        self.assertEqual(self.run_cli().returncode, 0)
        self.config['sources'][0]['domains'] = ['changed.example']
        self.save()
        before = self.output.read_bytes()
        self.assertNotEqual(self.run_cli('--check').returncode, 0)
        self.assertEqual(self.output.read_bytes(), before)

    def test_invalid_input_never_replaces_existing_policy(self):
        original = copy.deepcopy(self.config)
        invalid = [dict(original, max_age_days=value) for value in [True, 0, -1, '7']]
        invalid += [dict(original, sources=value) for value in [[], {}, [original['sources'][0]] * 2]]
        for key in ['', 'bad-id', 42, '__proto__']:
            invalid.append(dict(original, sources=[dict(original['sources'][0], id=key)]))
        for name in ['', ' ', None]:
            invalid.append(dict(original, sources=[dict(original['sources'][0], name=name)]))
        for domains in [[], ['https://official.example'], ['*.example'], ['host:443'], ['a@host'], ['Mixed.example'], ['bad..example'], ['official.example'] * 2]:
            invalid.append(dict(original, sources=[dict(original['sources'][0], domains=domains)]))
        for config in invalid:
            with self.subTest(config=config):
                self.config = config
                self.save()
                self.output.write_bytes(b'old-policy')
                result = self.run_cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.output.read_bytes(), b'old-policy')
                self.assertNotIn('PRIVATE_MARKER', result.stderr)
        self.config = original
        self.districts = {'districts': [{'name': '은평구'}, {'name': '은평구'}]}
        self.save()
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.output.read_bytes(), b'old-policy')

    def test_malformed_json_and_output_symlink_are_rejected(self):
        self.output.write_bytes(b'old-policy')
        (self.root / 'sources.yaml').write_text('{broken')
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertEqual(self.output.read_bytes(), b'old-policy')
        self.save()
        self.output.unlink()
        target = self.root / 'untouched'
        target.write_bytes(b'unchanged')
        self.output.symlink_to(target)
        self.assertNotEqual(self.run_cli().returncode, 0)
        self.assertEqual(target.read_bytes(), b'unchanged')
        self.assertTrue(self.output.is_symlink())

    def test_default_root_uses_script_location_not_working_directory(self):
        result = self.run_cli('--check', default_root=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.output.exists())
