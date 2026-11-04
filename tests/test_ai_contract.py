import copy
import json
import unittest
from pathlib import Path
from benefit_monitor.ai_contract import validate, check_schema

ROOT = Path(__file__).resolve().parents[1] / 'docs/ai'

class AIContractTests(unittest.TestCase):
    def setUp(self):
        self.host = json.loads((ROOT/'examples/research-input.json').read_text())
        self.result = json.loads((ROOT/'evaluations/v2/research-result.json').read_text())
        self.thost = json.loads((ROOT/'examples/topic-input.json').read_text())
        self.topics = json.loads((ROOT/'evaluations/v2/topic-result.json').read_text())

    def check(self):
        return validate(self.result, self.host, 'research')

    def test_original_trial_and_readiness(self):
        r = self.check()
        self.assertEqual(r['errors'], [])
        self.assertEqual([x['evidence_readiness'] for x in r['assessments']], ['needs_review','expired','needs_review','needs_review','needs_review'])
        self.assertEqual(r['assessments'][0]['execution_status'], 'completed')

    def test_original_topics(self):
        self.assertTrue(validate(self.topics,self.thost,'topic')['valid'])

    def test_forged_quote(self):
        self.result['records'][0]['claims'][0]['evidence'][0]['quote'] = '존재하지 않는 인용'
        self.assertFalse(self.check()['valid'])

    def test_host_metadata_tampering(self):
        self.result['records'][0]['sources'][0]['body_hash'] = 'f'*64
        self.assertFalse(self.check()['valid'])

    def test_host_body_hash(self):
        self.host['documents'][0]['body'] += ' altered'
        self.assertFalse(self.check()['valid'])

    def test_approval_injection(self):
        self.result['records'][0]['proposed_fields']['public_release'] = True
        self.assertFalse(self.check()['valid'])

    def test_duplicate_candidate(self):
        self.result['records'].append(copy.deepcopy(self.result['records'][0]))
        self.assertFalse(self.check()['valid'])

    def test_missing_candidate_in_completed(self):
        self.result['status'] = 'completed'
        self.result['records'].pop()
        self.assertFalse(self.check()['valid'])

    def test_wrong_item_claim(self):
        self.topics['topics'][0]['item_links'][0]['evidence_claim_ids'] = ['approved-family']
        self.assertFalse(validate(self.topics,self.thost,'topic')['valid'])

    def test_stale_snapshot(self):
        self.topics['topics'][0]['snapshot_id'] = 'old'
        self.assertFalse(validate(self.topics,self.thost,'topic')['valid'])

    def test_excluded_item(self):
        self.thost['excluded_items'].append({'item_id':'fixture-normal','reason':'expired'})
        self.assertFalse(validate(self.topics,self.thost,'topic')['valid'])

    def test_naive_timestamp(self):
        self.host['now'] = '2026-11-04T22:00:00'
        self.assertFalse(self.check()['valid'])

    def test_fixture_not_live(self):
        self.host['mode'] = self.result['mode'] = 'read_only_research'
        self.assertFalse(self.check()['valid'])

    def test_bool_not_integer(self):
        self.assertTrue(check_schema(True, {'type':'integer'}))

    def test_unknown_property(self):
        self.result['extra'] = 'unexpected'
        self.assertFalse(self.check()['valid'])

    def test_blocked_error_required(self):
        self.result['status'] = 'blocked'
        self.result['records'] = []
        self.assertFalse(self.check()['valid'])

    def test_missing_reference(self):
        self.result['records'][0]['claims'][0]['evidence'][0]['source_ref'] = 'nonexistent'
        self.assertFalse(self.check()['valid'])

    def test_unknown_only_is_not_ready(self):
        r = self.result['records'][0]
        r['sources'] = []
        r['claims'] = [{'id':'unknown','field':'conditions','value':None,'status':'unknown','evidence':[]}]
        r['missing_questions'] = r['conflicts'] = r['supplemental'] = []
        report = self.check()
        self.assertTrue(report['valid'])
        self.assertEqual(report['assessments'][0]['evidence_readiness'], 'needs_review')

    def test_contradictory_fee(self):
        self.result['records'][0]['proposed_fields']['fee_status'] = 'free'
        self.assertFalse(self.check()['valid'])

    def test_contradictory_date(self):
        self.result['records'][0]['proposed_fields']['valid_until'] = '2099-12-31'
        self.assertFalse(self.check()['valid'])

    def test_duplicate_conflict_evidence(self):
        c = self.result['records'][2]['claims'][0]
        c['evidence'] = [c['evidence'][0], copy.deepcopy(c['evidence'][0])]
        self.assertFalse(self.check()['valid'])

    def test_included_and_excluded(self):
        self.topics['topics'][0]['excluded_items'].append({'item_id':'fixture-normal','reason':'excluded'})
        self.assertFalse(validate(self.topics,self.thost,'topic')['valid'])

    def test_missing_host_budget(self):
        del self.host['budget']
        self.assertFalse(self.check()['valid'])

    def test_invalid_age_reference_date(self):
        self.topics['topics'][1]['profile_conditions'][0]['reference_date'] = 'not-a-date'
        self.assertFalse(validate(self.topics,self.thost,'topic')['valid'])
