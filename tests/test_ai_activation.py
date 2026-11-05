import plistlib
from pathlib import Path
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]

class AIActivationTests(unittest.TestCase):
    def test_activation_plan_is_reviewable_and_does_not_install_or_enable(self):
        from benefit_monitor.ai_activation import prepare
        with tempfile.TemporaryDirectory(dir=ROOT/'.tools') as folder:
            root=Path(folder)
            plan=prepare(root,root/'activation')
            config=__import__('json').loads((root/'activation/ai-automation.json').read_text())
            self.assertFalse(config['enabled'])
            self.assertFalse(config['recurring_spend_approved'])
            self.assertFalse(config['public_application_approved'])
            agent=plistlib.loads((root/'activation/ai-daily.plist').read_bytes())
            self.assertIn('--scheduled',agent['ProgramArguments'])
            self.assertEqual(agent['StartInterval'],900)
            self.assertEqual(agent['WorkingDirectory'],str(root))
            self.assertIn(str(Path(__import__('sys').executable).parent),agent['EnvironmentVariables']['PATH'].split(':'))
            self.assertEqual(agent['EnvironmentVariables']['TMPDIR'],str(root/'.tools/tmp'))
            self.assertFalse((root/'ai-automation.json').exists())
            self.assertEqual(plan['installed'],False)

if __name__=='__main__':unittest.main()
