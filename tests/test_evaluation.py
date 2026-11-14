"""Offline evaluation must execute real gates and keep unknown observations unknown."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from benefit_monitor import evaluation

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'docs/ai/evaluation'


class EvaluationTests(unittest.TestCase):
    def test_fixed_contract_against_real_gates_without_network(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            report = evaluation.run_cases(DATA/'cases.json', DATA/'contract.json')
        self.assertEqual(report['summary']['cases'], 35)
        self.assertEqual(report['summary']['failed'], 0, [r for r in report['rows'] if not r['passed']])
        self.assertEqual(report['new_api_calls'], 0)
        self.assertEqual(report['model_quality'], 'not_measured')
        self.assertEqual(len(report['contract_sha256']), 64)
        self.assertNotIn('page_text', json.dumps(report))

    def test_changed_expectation_is_a_failure_not_silently_rewritten(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            contract = json.loads((DATA/'contract.json').read_text())
            contract['cases'][0]['expected']['publish'] = False
            file = Path(tmp)/'contract.json'
            file.write_text(json.dumps(contract))
            before = file.read_bytes()
            report = evaluation.run_cases(DATA/'cases.json', file)
            self.assertGreater(report['summary']['failed'], 0)
            self.assertEqual(file.read_bytes(), before)

    def test_duplicate_or_missing_case_contract_rejected(self):
        cases = json.loads((DATA/'cases.json').read_text())
        contract = json.loads((DATA/'contract.json').read_text())
        for bad in [contract['cases'][:-1], contract['cases'] + [contract['cases'][0]]]:
            with self.assertRaises(ValueError):
                evaluation.validate_contract(cases, dict(contract, cases=bad))

    def test_unmeasured_time_cost_and_feedback_are_not_zero(self):
        summary = evaluation.summarize_events([
            {'run_id':'one','stage':'read','status':'failed','reason':'fetch_failed','duration_ms':None,'cost_usd':None},
            {'run_id':'two','stage':'validation','status':'failed','reason':'format','duration_ms':3,'cost_usd':0},
        ])
        self.assertEqual(summary['stages']['read']['reasons'], {'fetch_failed':1})
        self.assertIsNone(summary['stages']['read']['duration_ms'])
        self.assertEqual(summary['stages']['validation']['duration_ms'], 3)
        self.assertEqual(summary['stages']['response']['observations'], 0)
        self.assertIsNone(summary['cost_per_useful_recommendation_usd'])
        self.assertIsNone(summary['total_cost_usd'])

    def test_bad_event_values_rejected(self):
        event = {'run_id':'one','stage':'read','status':'ok','reason':None,'duration_ms':0,'cost_usd':0}
        for key,value in [('stage','bogus'),('cost_usd',-1),('cost_usd',float('nan')),('duration_ms',True),('status','sure')]:
            with self.subTest(key=key,value=value), self.assertRaises(ValueError):
                evaluation.summarize_events([dict(event, **{key:value})])
        with self.assertRaises(ValueError):
            evaluation.summarize_events([event,event])

    def test_symlink_cannot_read_outside_selected_artifacts(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            parent=Path(tmp); selected=parent/'selected';selected.mkdir()
            target=parent/'unrelated.json';target.write_text('{}')
            (selected/'input.json').symlink_to(target)
            with self.assertRaises(ValueError):
                evaluation.read_json(selected/'input.json',selected)

    def test_recorded_response_hash_is_verified(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root=Path(tmp);rid='c'*64;run=root/'runs'/rid;run.mkdir(parents=True)
            host={'candidates':[], 'documents':[]}
            (run/'input.json').write_text(json.dumps(host))
            (run/'metadata.json').write_text(json.dumps({'kind':'research','input_sha256':evaluation.recorded_input_hash(host)}))
            (root/'responses').mkdir()
            (root/'responses'/(rid+'.json')).write_text('{}')
            (root/'budget.json').write_text(json.dumps({'requests':[{'id':rid,'status':'completed',
                'charged_microdollars':100,'response_sha256':'incorrect'}]}))
            self.assertEqual(evaluation.replay(root)['rows'][0]['status'],'response_hash_mismatch')

    def test_replay_missing_response_is_not_validation_success(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp); run = root/'runs'/('a'*64); run.mkdir(parents=True)
            host = {'candidates':[], 'documents':[]}
            (run/'input.json').write_text(json.dumps(host))
            (run/'metadata.json').write_text(json.dumps({'kind':'research','input_sha256':evaluation.recorded_input_hash(host)}))
            report = evaluation.replay(root)
            self.assertEqual(report['rows'][0]['status'], 'missing_response')
            self.assertEqual(report['summary']['validated'], 0)
            self.assertIsNone(report['summary']['historical_cost_usd'])

    def test_replay_input_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as tmp:
            root = Path(tmp); run = root/'runs'/('b'*64); run.mkdir(parents=True)
            (run/'input.json').write_text('{}')
            (run/'metadata.json').write_text(json.dumps({'kind':'research','input_sha256':'incorrect'}))
            report = evaluation.replay(root)
            self.assertEqual(report['rows'][0]['status'], 'input_hash_mismatch')

    def test_verify_wire_is_decoded_before_assuming_valid(self):
        cases=json.loads((DATA/'cases.json').read_text())['cases']
        valid=next(c for c in cases if c['id']=='V01')
        self.assertEqual(evaluation.decode_recorded('verify',valid['draft'],valid['host'])['purpose'],'audit')
        invalid=next(c for c in cases if c['id']=='V08')
        with self.assertRaises(ValueError):
            evaluation.decode_recorded('verify',invalid['draft'],invalid['host'])
        with self.assertRaises(ValueError):
            evaluation.decode_recorded('verify',{},valid['host'])

    def test_blind_pair_has_same_context_and_keeps_key_separate(self):
        host = {'now':'2026-11-14T07:00:00+09:00','candidates':[{'id':'a'}]}
        packet, key = evaluation.blind_pair('case-a',host,[{'id':'a'}],[{'id':'a','line':'소개'}])
        self.assertNotIn('ai', packet)
        self.assertNotIn('rule', packet)
        self.assertEqual(set(key['arms'].values()), {'ai','rule'})
        self.assertEqual(packet['input_sha256'], evaluation.digest(host))
        self.assertIsNone(packet['ratings']['A']['useful'])
        ratings=deepcopy(packet['ratings']);ratings['A']['useful']=True;ratings['B']['useful']=False
        self.assertEqual(evaluation.score_ratings(packet,key,ratings)['rated_arms'],2)
        self.assertEqual(evaluation.score_ratings(packet,key,packet['ratings'])['rated_arms'],0)
        scores=evaluation.score_batch([packet],[key],{packet['id']:packet['ratings']})
        self.assertEqual(scores['useful_rate'],{'rule':None,'ai':None})
        with self.assertRaises(ValueError):
            evaluation.score_batch([packet,packet],[key],{packet['id']:ratings})
