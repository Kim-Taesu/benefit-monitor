"""The tab pick registry (2026-11-18) must name every place a pick kind is wired to."""
import unittest
from importlib import import_module
from pathlib import Path

from benefit_monitor import ai_daily, claude_trial, cloud_daily, mirror
from benefit_monitor.tab_picks import KEYS, TAB_PICKS

ROOT = Path(__file__).resolve().parents[1]


class TabPickRegistryTests(unittest.TestCase):
    def test_each_kind_has_its_module_model_task_and_daily_step(self):
        daily = Path(ai_daily.__file__).read_text()
        for kind in TAB_PICKS:
            with self.subTest(kind=kind.name):
                module = import_module('benefit_monitor.' + kind.module)
                self.assertTrue(callable(module.public) and callable(module.refresh))
                self.assertEqual(module.TAKEDOWN_KIND, kind.name + '_pick_text')
                self.assertIn(kind.name, claude_trial.KINDS)
                self.assertIn(f"('{kind.name}',{kind.name}_refresh)", daily)
                self.assertEqual(kind.key, kind.name + '_pick')

    def test_upload_restore_and_admin_follow_the_registry(self):
        self.assertEqual([r for r, _ in mirror.TAB_PICKS], [k.remote for k in TAB_PICKS])
        self.assertEqual([l for l, _, _ in cloud_daily.TAB_PICKS], [k.local for k in TAB_PICKS])
        self.assertEqual(list(cloud_daily.pick_report({})), [k.name for k in TAB_PICKS])
        admin = (ROOT / 'frontend/src/admin/github.ts').read_text()
        for key in KEYS:
            self.assertIn(f"'{key}_text'", admin)


if __name__ == '__main__':
    unittest.main()
