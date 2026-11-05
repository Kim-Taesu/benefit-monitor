from copy import deepcopy
import hashlib
import importlib
import json
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[1]
REQUIRED=['eligibility','event_period','application_period','fee_status','cost_details','payment_conditions',
          'selection','capacity','application_method','cancellation','restrictions','availability']


class ResearchGuardTests(unittest.TestCase):
    def setUp(self):
        self.body='대상 제한없음 상세내용 유아동반 가족은 많이 찾아와주세요. 주의사항 준비물을 지참하세요.'
        host=json.loads((ROOT/'docs/ai/examples/research-input.json').read_text())
        self.host=host;host['candidates']=host['candidates'][:1]
        self.cid=host['candidates'][0]['candidate_id']
        doc=host['documents'][0];host['documents']=[doc];host['candidates'][0]['document_ids']=[doc['id']]
        doc.update(body=self.body,body_hash=hashlib.sha256(self.body.encode()).hexdigest(),fetch_status='ok')
        self.doc=doc
        self.fact={'field':'eligibility','status':'supported','value':{'scope':'unrestricted','required':[],'not_confirmed':[]},
                   'evidence':[{'source_ref':doc['id'],'quote':'대상 제한없음','locator':None}],'unknown_reason':None}
        facts=[self.fact]+[{'field':name,'status':'unknown','value':None,'evidence':[],'unknown_reason':'원문에서 확인되지 않음'} for name in REQUIRED if name!='eligibility']
        self.draft={'schema_version':'research-extraction-v3','status':'completed','errors':[],
                    'records':[{'candidate_id':self.cid,'research_status':'completed','facts':facts,'stop_reason':'sufficient_evidence'}]}

    def audit(self):
        return importlib.import_module('benefit_monitor.research_guard').audit(self.draft,self.host)

    def assemble(self):
        return importlib.import_module('benefit_monitor.research_extraction').assemble(self.draft,self.host)

    def preserve_family(self):
        self.fact['value']={'scope':'restricted','required':['유아 동반 가족'],'not_confirmed':['정확한 나이·거주 조건']}
        self.fact['evidence'].append({'source_ref':self.doc['id'],'quote':'유아동반 가족은 많이 찾아와주세요.','locator':None})

    def test_unrestricted_summary_cannot_hide_detail_restriction(self):
        codes={f['code'] for f in self.audit()['findings']}
        self.assertIn('unrestricted_with_restriction',codes)
        self.assertIn('restriction_not_quoted',codes)

    def test_restriction_must_be_in_value_as_well_as_quote(self):
        self.preserve_family();self.fact['value']['required']=['특정 대상']
        self.assertIn('restriction_not_preserved',{f['code'] for f in self.audit()['findings']})

    def test_preserved_restriction_and_explicit_unknowns_pass_local_checks(self):
        self.preserve_family()
        full,report=self.assemble()
        self.assertTrue(report['valid'],report)
        self.assertEqual(full['records'][0]['claims'][0]['field'],'eligibility')
        self.assertEqual(full['records'][0]['claims'][0]['value']['required'],['유아 동반 가족'])
        self.assertEqual(report['assessments'][0]['evidence_readiness'],'needs_review')
        self.assertFalse(report['publication_approved'])

    def test_missing_critical_field_and_alias_are_rejected(self):
        self.preserve_family();self.draft['records'][0]['facts'].pop()
        self.assertIn('missing_required_field',{f['code'] for f in self.audit()['findings']})
        self.fact['field']='대상'
        with self.assertRaises(ValueError):self.assemble()

    def test_quote_for_another_candidate_does_not_cover_restriction(self):
        self.preserve_family();self.fact['evidence'][-1]['source_ref']='other-doc'
        self.assertIn('restriction_not_quoted',{f['code'] for f in self.audit()['findings']})

    def test_unknown_eligibility_does_not_clear_visible_restriction(self):
        self.fact.update(status='unknown',value=None,evidence=[],unknown_reason='자격 확인 필요')
        self.assertFalse(self.audit()['valid'])

    def test_unrestricted_without_detected_restriction_stays_human_review_only(self):
        self.doc['body']='대상 제한없음 상세내용 누구나 신청 가능.'
        self.doc['body_hash']=hashlib.sha256(self.doc['body'].encode()).hexdigest()
        _,report=self.assemble()
        self.assertTrue(report['valid'],report)
        self.assertFalse(report['publication_approved'])

    def test_noncanonical_legacy_output_is_not_silently_renamed(self):
        self.draft['schema_version']='research-extraction-v2';self.fact['field']='대상'
        original=deepcopy(self.draft)
        self.assertIn('noncanonical_field',{f['code'] for f in self.audit()['findings']})
        self.assertEqual(self.draft,original)

    def test_age_restriction_in_another_successful_document_is_not_ignored(self):
        self.preserve_family()
        second=deepcopy(self.doc);second.update(id='second',body='상세내용 만19~39세 청년 대상',body_hash=hashlib.sha256('상세내용 만19~39세 청년 대상'.encode()).hexdigest())
        self.host['documents'].append(second);self.host['candidates'][0]['document_ids'].append('second')
        self.assertFalse(self.audit()['valid'])

    def test_typed_dates_are_not_accepted_as_free_text(self):
        self.preserve_family()
        event=next(f for f in self.draft['records'][0]['facts'] if f['field']=='event_period')
        event.update(status='supported',value={'start':'2026-11-02T00:00:00+09:00','end':'2026-11-03'},evidence=deepcopy(self.fact['evidence']),unknown_reason=None)
        with self.assertRaises(ValueError):self.assemble()

    def test_summary_only_adult_restriction_is_not_ignored(self):
        self.doc['body']='대상 성인 상세내용 나무 체험입니다.'
        self.assertIn('unrestricted_with_restriction',{f['code'] for f in self.audit()['findings']})

    def test_application_deadline_and_event_dates_are_typed_and_propagated(self):
        self.preserve_family()
        for field,value in [('event_period',{'start':'2026-11-01','end':'2026-11-30'}),
                            ('application_period',{'start':'2026-11-01T00:00:00+09:00','end':'2026-11-20T16:00:00+09:00'})]:
            fact=next(f for f in self.draft['records'][0]['facts'] if f['field']==field)
            fact.update(status='supported',value=value,evidence=deepcopy(self.fact['evidence']),unknown_reason=None)
        full,report=self.assemble()
        self.assertTrue(report['valid'],report)
        self.assertEqual(full['records'][0]['proposed_fields']['valid_until'],'2026-11-30')
        self.assertEqual(full['records'][0]['proposed_fields']['deadline_at'],'2026-11-20T16:00:00+09:00')
        fact['value']['end']='2026-11-20T16:00:00'
        with self.assertRaises(ValueError):self.assemble()

    def test_duplicate_field_and_supported_inventory_cannot_pass(self):
        self.preserve_family();self.draft['records'][0]['facts'].append(deepcopy(self.fact))
        self.assertIn('duplicate_field',{f['code'] for f in self.audit()['findings']})
        self.draft['records'][0]['facts'].pop()
        fact=next(f for f in self.draft['records'][0]['facts'] if f['field']=='availability')
        fact.update(status='supported',value='잔여석20',evidence=deepcopy(self.fact['evidence']),unknown_reason=None)
        with self.assertRaises(ValueError):self.assemble()

    def test_supported_unknown_fee_and_noncanonical_dates_fail_closed(self):
        self.preserve_family()
        fee=next(f for f in self.draft['records'][0]['facts'] if f['field']=='fee_status')
        fee.update(status='supported',value='unknown',evidence=deepcopy(self.fact['evidence']),unknown_reason=None)
        with self.assertRaises(ValueError):self.assemble()
        fee.update(status='unknown',value=None,evidence=[],unknown_reason='요금 미확인')
        event=next(f for f in self.draft['records'][0]['facts'] if f['field']=='event_period')
        event.update(status='supported',value={'start':'20261101','end':'20261130'},evidence=deepcopy(self.fact['evidence']),unknown_reason=None)
        with self.assertRaises(ValueError):self.assemble()

    def test_omitted_candidate_cannot_pass_coverage_as_empty_partial(self):
        self.draft.update(status='partial',records=[])
        self.assertIn('unreviewed_candidate',{f['code'] for f in self.audit()['findings']})

    def test_cancellation_calendar_qualifier_cannot_be_dropped(self):
        self.preserve_family()
        text=' 프로그램3일 전까지 취소. 주말·공휴일 제외, 센터 운영일(평일) 기준.'
        self.doc['body']+=text;self.doc['body_hash']=hashlib.sha256(self.doc['body'].encode()).hexdigest()
        fact=next(f for f in self.draft['records'][0]['facts'] if f['field']=='cancellation')
        fact.update(status='supported',value='프로그램3일 전까지 취소',evidence=[{'source_ref':self.doc['id'],'quote':'프로그램3일 전까지 취소.','locator':None}],unknown_reason=None)
        self.assertIn('qualifier_not_preserved',{f['code'] for f in self.audit()['findings']})
        fact['value']='프로그램3일 전까지 취소. 주말·공휴일 제외, 센터 운영일(평일) 기준'
        fact['evidence'][0]['quote']=text.strip()
        self.assertTrue(self.audit()['valid'])


if __name__=='__main__':unittest.main()
