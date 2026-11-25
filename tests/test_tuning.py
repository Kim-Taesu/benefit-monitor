import json
import re
import unittest
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import tuning

ROOT = Path(__file__).resolve().parents[1]


class TuningTests(unittest.TestCase):
    def test_committed_file_is_valid_and_every_value_is_used(self):
        data = json.loads(tuning.FILE.read_text(encoding='utf-8'))
        self.assertEqual(tuning.errors(data), [])
        code = '\n'.join(p.read_text(encoding='utf-8') for p in (ROOT / 'benefit_monitor').rglob('*.py'))
        used = set(re.findall(r"tuning\.value\('([^']+)'\)", code))
        self.assertEqual(used, set(data['values']), 'every tuning value is read by code, and only those exist')

    def test_values_outside_their_approved_range_are_refused(self):
        entry = dict(value=9, min=7, max=14, unit='일', why='후보 기간')
        doc = lambda **e: dict(schema_version=1, values={'festival.window_days': dict(entry, **e)})
        self.assertEqual(tuning.errors(doc()), [])
        self.assertEqual(tuning.errors(doc(value=15)), ['festival.window_days: 15 outside [7, 14]'])
        self.assertEqual(tuning.errors(doc(value=6)), ['festival.window_days: 6 outside [7, 14]'])
        self.assertEqual(tuning.errors(doc(value=9.5)), ['festival.window_days: integer range needs an integer value'])
        self.assertEqual(tuning.errors(doc(value=True)), ['festival.window_days: not a number'])
        self.assertEqual(tuning.errors(doc(why='')), ['festival.window_days: description'])
        self.assertEqual(tuning.errors(dict(schema_version=1, values={'x': {'value': 1}})), ['x: keys'])
        self.assertEqual(tuning.errors({'values': {}}), ['document shape'])

    def test_a_bad_file_or_unknown_name_fails_loudly(self):
        tuning._load.cache_clear()
        try:
            with patch.object(tuning, 'FILE', ROOT / 'config/missing.json'):
                with self.assertRaises(OSError):
                    tuning.value('festival.window_days')
        finally:
            tuning._load.cache_clear()
        with self.assertRaises(KeyError):
            tuning.value('festival.no_such_value')
        self.assertEqual(tuning.value('festival.metro_window_days'), 21)


if __name__ == '__main__':
    unittest.main()
