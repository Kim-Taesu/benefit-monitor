from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class QualityReplayTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.tools')
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.rows=[]
        self.research=json.loads((ROOT/'docs/ai/evaluations/v2/research-result.json').read_text())
        self.host=json.loads((ROOT/'docs/ai/examples/research-input.json').read_text())
        self.topic=json.loads((ROOT/'docs/ai/evaluations/v2/topic-result.json').read_text())
        self.thost=json.loads((ROOT/'docs/ai/examples/topic-input.json').read_text())
        research=self.add_run('research',self.host,self.research)
        topic=self.add_run('topic',self.thost,self.topic)
        (self.root/'core-pilot-results.json').write_text(json.dumps([{'reference_candidate_id':'fixture','report':{'run_id':research}}]))
        (self.root/'daily-replay-results.json').write_text(json.dumps([{'day':self.thost['now'],'report':{'run_id':topic}}]))
        (self.root/'live/budget.json').write_text(json.dumps({'requests':self.rows}))

    def add_run(self,kind,host,draft):
        raw=json.dumps({'stop_reason':'end_turn','content':[{'type':'text','text':json.dumps(draft)}]}).encode()
        digest=hashlib.sha256(raw).hexdigest()
        run=self.root/'live/runs'/digest;run.mkdir(parents=True)
        responses=self.root/'live/responses';responses.mkdir(exist_ok=True)
        (responses/(digest+'.json')).write_bytes(raw)
        (run/'input.json').write_text(json.dumps(host))
        (run/'metadata.json').write_text(json.dumps({'kind':kind,'input_sha256':hashlib.sha256(json.dumps(host,ensure_ascii=False,sort_keys=True).encode()).hexdigest()}))
        self.rows.append({'id':digest,'status':'completed','response_sha256':digest})
        return digest

    def replay(self):
        return importlib.import_module('benefit_monitor.replay_quality').replay(self.root,{'items':{}})

    def test_replays_original_contract_and_new_semantic_gate_without_writes_or_network(self):
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('benefit_monitor.claude_trial.network_open',side_effect=AssertionError('offline only')):
            report=self.replay()
        self.assertEqual(report['research_valid'],1)
        self.assertEqual(report['topic_structural_valid'],1)
        self.assertEqual(report['topic_semantic_valid'],0)
        self.assertEqual(report['new_api_calls'],0)
        self.assertEqual({str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()},before)

    def test_response_tampering_fails_instead_of_revalidating_changed_data(self):
        response=next((self.root/'live/responses').glob('*.json'))
        response.write_text('{}')
        with self.assertRaisesRegex(ValueError,'hash'):
            self.replay()

    def test_input_tampering_fails(self):
        path=next((self.root/'live/runs').glob('*/input.json'))
        host=json.loads(path.read_text());host['now']='2026-11-06T12:00:00+09:00';path.write_text(json.dumps(host))
        with self.assertRaisesRegex(ValueError,'hash'):
            self.replay()

    def test_legacy_compact_result_is_audited_without_rewriting_history(self):
        from benefit_monitor.replay_research_guard import replay_record
        host=deepcopy(self.host);host['candidates']=host['candidates'][:1]
        doc=host['documents'][0];host['documents']=[doc];host['candidates'][0]['document_ids']=[doc['id']]
        compact={'schema_version':'research-extraction-v2','status':'completed','errors':[],
                 'records':[{'candidate_id':host['candidates'][0]['candidate_id'],'research_status':'completed',
                             'facts':[{'field':'conditions','value':'원문 검토','status':'supported','evidence':[{'source_ref':doc['id'],'quote':doc['body'][:15],'locator':None}],'unknown_reason':None}],
                             'stop_reason':'sufficient_evidence'}]}
        rid=self.add_run('research',host,compact)
        (self.root/'live/budget.json').write_text(json.dumps({'requests':self.rows}))
        before={str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with patch('benefit_monitor.claude_trial.network_open',side_effect=AssertionError('offline only')):
            report=replay_record(self.root,rid)
        self.assertTrue(report['original_contract']['valid'])
        self.assertFalse(report['current_coverage']['valid'])
        self.assertEqual(report['new_api_calls'],0)
        self.assertEqual({str(p):p.read_bytes() for p in self.root.rglob('*') if p.is_file()},before)


if __name__=='__main__':unittest.main()
