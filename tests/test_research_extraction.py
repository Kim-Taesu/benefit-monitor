from copy import deepcopy
import importlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ResearchExtractionTests(unittest.TestCase):
    def setUp(self):
        self.host = json.loads((ROOT/'docs/ai/examples/research-input.json').read_text())
        self.host['candidates'] = self.host['candidates'][:1]
        ids = set(self.host['candidates'][0]['document_ids'])
        self.host['documents'] = [d for d in self.host['documents'] if d['id'] in ids]
        self.candidate = self.host['candidates'][0]['candidate_id']
        doc = next(d for d in self.host['documents'] if d['fetch_status'] == 'ok')
        self.fact = {'field':'conditions','value':'원문 검토 필요','status':'supported',
                     'evidence':[{'source_ref':doc['id'],'quote':doc['body'][:15],'locator':None}],
                     'unknown_reason':None}
        self.draft = {'schema_version':'research-extraction-v2','status':'completed','errors':[],
                      'records':[{'candidate_id':self.candidate,'research_status':'completed',
                                  'facts':[self.fact],'stop_reason':'sufficient_evidence'}]}

    def assemble(self):
        return importlib.import_module('benefit_monitor.research_extraction').assemble(self.draft,self.host)

    def test_host_metadata_and_ids_are_filled_then_existing_contract_runs(self):
        original=deepcopy(self.draft)
        full,report=self.assemble()
        self.assertTrue(report['valid'],report)
        record=full['records'][0]
        self.assertEqual(record['source_id'],self.host['candidates'][0]['source_id'])
        self.assertEqual(record['sources'][0]['body_hash'],self.host['documents'][0]['body_hash'])
        self.assertRegex(record['claims'][0]['id'],r'^claim-[0-9a-f]{24}$')
        self.assertEqual(record['claims'][0]['evidence'],self.fact['evidence'])
        self.assertEqual(self.assemble()[0],full)
        self.assertEqual(self.draft,original)
        self.assertEqual(report['assessments'][0]['evidence_readiness'],'needs_review')

    def test_forged_quote_still_fails_original_evidence_check(self):
        self.fact['evidence'][0]['quote']='없는 문장'
        _,report=self.assemble()
        self.assertFalse(report['valid'])
        self.assertIn('quote not in successful source',report['errors'])

    def test_unknown_is_preserved_and_not_silently_repaired(self):
        self.fact.update(status='unknown',value=None,evidence=[],unknown_reason='조건 미명시')
        full,report=self.assemble()
        self.assertTrue(report['valid'])
        self.assertEqual(full['records'][0]['missing_questions'][0]['reason'],'조건 미명시')
        self.fact['value']='추정값'
        _,report=self.assemble()
        self.assertFalse(report['valid'])

    def test_model_metadata_and_unknown_candidates_cannot_override_host(self):
        self.draft['records'][0]['source_id']='injected'
        with self.assertRaises(ValueError):self.assemble()
        del self.draft['records'][0]['source_id']
        self.draft['records'][0]['candidate_id']='other'
        with self.assertRaises(ValueError):self.assemble()

    def test_dates_and_conflicting_supported_values_are_not_fixed(self):
        self.fact.update(field='event_date',value='2026-11-02T00:00:00+09:00')
        with self.assertRaises(ValueError):self.assemble()
        self.fact.update(field='fee_status',value='free')
        second=deepcopy(self.fact);second['value']='paid'
        self.draft['records'][0]['facts'].append(second)
        with self.assertRaises(ValueError):self.assemble()

    def test_disputed_claim_retains_both_sides_and_review_gate(self):
        self.fact.update(status='disputed')
        self.fact['evidence'].append(dict(self.fact['evidence'][0],quote=self.host['documents'][0]['body'][-15:]))
        full,report=self.assemble()
        self.assertTrue(report['valid'],report)
        self.assertIsNone(full['records'][0]['conflicts'][0]['resolution'])
        self.assertEqual(report['assessments'][0]['evidence_readiness'],'needs_review')

    def test_trial_consumer_uses_compact_assembler(self):
        from benefit_monitor.claude_trial import evaluate_draft
        full, report = evaluate_draft(self.draft,self.host,'research')
        self.assertTrue(report['valid'],report)
        self.assertEqual(full['schema_version'],'trial-result-v1')

    def test_current_request_cannot_accept_a_legacy_response(self):
        from benefit_monitor.claude_trial import evaluate_draft
        with self.assertRaises(ValueError):
            evaluate_draft(self.draft,self.host,'research',required_version='research-extraction-v3')


if __name__ == '__main__':unittest.main()
