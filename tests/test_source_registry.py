import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from benefit_monitor.source_registry import build_config, load, validate

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads((ROOT / 'schema/source.schema.json').read_text())


def definition(**changes):
    base = json.loads((ROOT / 'sources/emart24_events.json').read_text())
    base.update(changes)
    return base


class SourceRegistryTests(unittest.TestCase):
    def test_checked_in_sources_yaml_is_generated_from_definitions(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/generate_sources.py'), '--check'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_every_definition_passes_schema_and_names_existing_code(self):
        settings, definitions = load(ROOT)
        self.assertEqual([d['id'] for d in definitions if d['status'] == 'active'], settings['source_order'])
        self.assertTrue({d['id'] for d in definitions if d['status'] != 'active'} >= {'gs25', 'gs_the_fresh'})

    def test_inactive_sources_never_reach_operational_config(self):
        ids = {s['id'] for s in build_config(ROOT)['sources']}
        self.assertNotIn('gs25', ids)
        self.assertNotIn('youth_policy', ids)
        self.assertIn('emart24_events', ids)

    def test_schema_rejects_typos_wrong_values_and_status_mismatch(self):
        self.assertEqual(validate(definition(), SCHEMA, 'emart24_events.json'), [])
        typo = definition(); typo['collect']['keyword'] = ['이벤트']
        self.assertTrue(any('unknown key keyword' in e for e in validate(typo, SCHEMA)))
        wrong = definition(); wrong['runbook']['access']['robots'] = 'maybe'
        self.assertTrue(any('robots' in e for e in validate(wrong, SCHEMA)))
        self.assertTrue(validate(definition(status='excluded'), SCHEMA))
        self.assertTrue(any('file name' in e for e in validate(definition(), SCHEMA, 'other.json')))
        bad_date = definition(); bad_date['runbook']['checked_at'] = '11월 6일'
        self.assertTrue(validate(bad_date, SCHEMA))
        flag = definition(); flag['collect']['ai_review'] = 'no'
        self.assertTrue(any('ai_review' in e for e in validate(flag, SCHEMA)))

    def test_missing_order_entry_and_missing_code_path_fail_load(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            shutil.copytree(ROOT / 'sources', root / 'sources')
            shutil.copytree(ROOT / 'schema', root / 'schema')
            shutil.copytree(ROOT / 'benefit_monitor', root / 'benefit_monitor')
            shutil.copytree(ROOT / 'tests', root / 'tests', ignore=shutil.ignore_patterns('__pycache__'))
            config = json.loads((root / 'sources/_config.json').read_text())
            config['source_order'].remove('heritage')
            (root / 'sources/_config.json').write_text(json.dumps(config))
            with self.assertRaisesRegex(ValueError, 'heritage'):
                load(root)
            config['source_order'].append('heritage')
            (root / 'sources/_config.json').write_text(json.dumps(config))
            (root / 'benefit_monitor/collectors/public.py').unlink()
            with self.assertRaisesRegex(ValueError, 'code path missing'):
                load(root)


if __name__ == '__main__':
    unittest.main()
