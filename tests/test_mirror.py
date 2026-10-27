import base64
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benefit_monitor import mirror
from benefit_monitor.store import save


class MirrorTests(unittest.TestCase):
    def test_request_contains_only_the_public_json_and_current_file_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = dict(schema_version=1, generated_at="2026-10-27T07:01:00+09:00",
                        source_report_at="2026-10-27T07:00:00+09:00", items=[], status="awaiting_verification")
            save(root / "delivery/public/briefing.json", data)
            save(root / "report.json", {"profile": "private"})
            requests = []

            def api(args, **kwargs):
                requests.append((args, kwargs.get("input")))
                if "GET" in args:
                    self.assertIn("repos/Kim-Taesu/benefit-monitor/contents/briefing.json?ref=briefing-data", args)
                    return subprocess.CompletedProcess(args, 0, "current-sha\n", "")
                self.assertIn("PUT", args)
                payload = json.loads(kwargs["input"])
                self.assertEqual(payload["sha"], "current-sha")
                self.assertEqual(payload["branch"], "briefing-data")
                self.assertEqual(json.loads(base64.b64decode(payload["content"])), data)
                return subprocess.CompletedProcess(args, 0, "{}", "")

            with patch("benefit_monitor.mirror.subprocess.run", side_effect=api):
                mirror.run(root, "Kim-Taesu/benefit-monitor")
            self.assertEqual(len(requests), 2)

    def test_missing_export_does_not_send_a_request(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch("benefit_monitor.mirror.subprocess.run") as api:
                with self.assertRaises(FileNotFoundError):
                    mirror.run(Path(directory), "Kim-Taesu/benefit-monitor")
                api.assert_not_called()

    def test_restore_reads_only_metadata_from_existing_public_json(self):
        from datetime import datetime
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            save(root/'sources.yaml',{'sources':[{'id':'test'}]})
            remote={'operational_state':{'schema_version':1,'items':{},'profile':'do not copy'},'items':[{'conditions':'do not restore'}]}
            response=json.dumps({'content':base64.b64encode(json.dumps(remote).encode()).decode(),'encoding':'base64'})
            with patch('benefit_monitor.mirror.subprocess.run',return_value=subprocess.CompletedProcess([],0,response,'')):
                mirror.restore(root,'Kim-Taesu/benefit-monitor',datetime.fromisoformat('2026-10-28T07:00:00+09:00'))
            state=json.loads((root/'cache/operational_state.json').read_text())
            self.assertEqual(state,{'schema_version':1,'items':{},'sources':{}})
            self.assertFalse((root/'cache/verified_items.json').exists())

    def test_failure_export_preserves_previous_operational_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            save(root/'sources.yaml',{'sources':[{'id':'test'}]})
            prior={'schema_version':1,'items':{},'sources':{'test':{'consecutive_failures':3}}}
            save(root/'delivery/public/briefing.json',{'status':'collection_failed','items':[]})
            def api(args,**kwargs):
                if 'GET' in args:
                    if '--jq' in args:return subprocess.CompletedProcess(args,0,'sha','')
                    envelope={'encoding':'base64','content':base64.b64encode(json.dumps({'operational_state':prior}).encode()).decode()}
                    return subprocess.CompletedProcess(args,0,json.dumps(envelope),'')
                uploaded=json.loads(base64.b64decode(json.loads(kwargs['input'])['content']))
                self.assertEqual(uploaded['operational_state'],prior)
                self.assertEqual(uploaded['items'],[])
                return subprocess.CompletedProcess(args,0,'{}','')
            with patch('benefit_monitor.mirror.subprocess.run',side_effect=api):mirror.run(root,'Kim-Taesu/benefit-monitor')
            self.assertEqual(json.loads((root/'delivery/public/briefing.json').read_text())['operational_state'],prior)
