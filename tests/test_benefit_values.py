import json
import tempfile
import unittest
from pathlib import Path

from benefit_monitor.validation import validate
from benefit_monitor import publish
from benefit_monitor.store import save
from test_pipeline import benefit, SOURCE, NOW

ROOT = Path(__file__).resolve().parents[1]


def value(**updates):
    claim=dict(kind='discount_rate',value=10,qualifier='up_to',conditions='테스트 자료: 지정 결제수단과 한도 확인 필요 <테스트>',evidence_url='https://official.example/')
    claim.update(updates)
    number=str(claim['value'])
    suffix={'discount_rate':'% 할인','discount_amount':'원 할인','grant_amount':'원 지원','refund_amount':'원 환급','reward_points':'포인트 적립'}.get(claim['kind'],'원')
    claim.setdefault('evidence_quote',('최대 ' if claim['qualifier']=='up_to' else '')+number+suffix)
    return claim


def record(claim=...):
    claim=value() if claim is ... else claim
    quote=claim.get('evidence_quote','') if isinstance(claim,dict) else ''
    return dict(benefit(url='https://official.example/',fee_status='paid',evidence='비공개 운영 메모 / '+quote).data(),benefit_value=claim)



class BenefitValueTests(unittest.TestCase):
    def test_optional_empty_value_preserves_existing_content_hash(self):
        original=benefit()
        empty=validate(dict(original.data(),benefit_value={}),{SOURCE['id']:SOURCE},NOW)
        self.assertEqual(original.content(),empty.content())
        self.assertNotIn('benefit_value',empty.content())

    def test_verified_value_supports_bounded_rates_and_integer_amounts(self):
        for claim in [value(),value(value=0.5),value(kind='discount_amount',value=5000),value(kind='grant_amount',value=100000),value(kind='refund_amount',value=1000),value(kind='reward_points',value=100)]:
            with self.subTest(claim=claim):
                self.assertEqual(validate(record(claim),{SOURCE['id']:SOURCE},NOW).data()['benefit_value'],claim)

    def test_invalid_numbers_units_shapes_or_qualifiers_fail(self):
        bad=[None,[],value(value=True),value(value=0),value(value=-1),value(value=float('nan')),value(value=float('inf')),value(value=101),value(value=1.001),value(kind='discount_amount',value=1.5),value(kind='grant_amount',value=10**12),value(kind='price'),value(qualifier='guaranteed'),value(conditions=''),value(extra='unsupported')]
        for claim in bad:
            with self.subTest(claim=claim),self.assertRaises((ValueError,TypeError)):
                validate(record(claim),{SOURCE['id']:SOURCE},NOW)

    def test_official_quote_and_already_observed_target_are_required(self):
        for claim in [value(evidence_url='http://official.example/'),value(evidence_url='https://evil.example/'),value(evidence_url='https://official.example/other'),value(evidence_quote=''),value(evidence_quote='原文에 없는 인용')]:
            with self.subTest(claim=claim),self.assertRaises(ValueError):
                validate(record(claim),{SOURCE['id']:SOURCE},NOW)
        terms=dict(method='테스트',funding_source='테스트',excluded_methods='미확인',minimum_spend='미확인',limit='미확인',evidence_url='https://official.example/payment')
        claim=value(evidence_url=terms['evidence_url'])
        self.assertEqual(validate(dict(record(claim),payment_terms=terms),{SOURCE['id']:SOURCE},NOW).benefit_value,claim)

    def test_supplied_number_unit_and_maximum_marker_must_match_the_quote(self):
        for claim in [value(kind='grant_amount',value=5000,evidence_quote='최대 5000원 할인'),value(value=20,evidence_quote='최대 10% 할인'),value(kind='grant_amount',value=5000,evidence_quote='최대 10% 할인'),value(qualifier='exact',evidence_quote='최대 10% 할인'),value(evidence_quote='10% 할인'),value(value=1,evidence_quote='최대 0.1% 할인')]:
            with self.subTest(claim=claim),self.assertRaises(ValueError):
                validate(record(claim),{SOURCE['id']:SOURCE},NOW)
        validate(record(value(value=0.5,evidence_quote='최대 0.50% 할인')),{SOURCE['id']:SOURCE},NOW)
        for quote in ['최대 5,000원 할인','최대 5000 원 할인']:
            validate(record(value(kind='discount_amount',value=5000,evidence_quote=quote)),{SOURCE['id']:SOURCE},NOW)

    def test_quote_must_be_part_of_internal_review_evidence(self):
        with self.assertRaises(ValueError):validate(dict(record(),evidence='다른 확인 근거'),{SOURCE['id']:SOURCE},NOW)

    def test_payment_threshold_and_signed_figures_are_not_benefit_values(self):
        for claim in [value(kind='discount_amount',value=5000,evidence_quote='최대 5,000원 결제 시 10% 할인'),value(kind='grant_amount',value=5000,evidence_quote='최대 5,000원 할인, 지원 대상 확인'),value(qualifier='exact',evidence_quote='-10% 할인')]:
            with self.subTest(claim=claim),self.assertRaises(ValueError):validate(record(claim),{SOURCE['id']:SOURCE},NOW)

    def test_schema_covers_model_fields_and_typed_claim_contract(self):
        schema=json.loads((ROOT/'schema/benefit.schema.json').read_text())
        self.assertLessEqual(set(benefit().data()),set(schema['properties']))
        claim=schema['properties']['benefit_value']
        self.assertFalse(claim['additionalProperties'])
        self.assertEqual(set(claim['properties']),set(value()))


class BenefitValuePublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        save(self.root/'sources.yaml',dict(sources=[SOURCE],max_age_days=7))

    def export(self,item,approved=None):
        save(self.root/'public/verified.json',[dict(approved or item,public_release=True)])
        save(self.root/'report.json',dict(verified_at=NOW.isoformat(),complete=False,new=[item],needs_recheck=[],collection=dict(online=True,successful_sources=[SOURCE['id']],successful_districts=0)))
        return publish.run(self.root,now=NOW)

    def test_public_value_is_preserved_with_conditions_and_escaped_evidence(self):
        result=self.export(record())
        self.assertEqual(result['schema_version'],1)
        self.assertEqual(result['items'][0]['benefit_value'],value())
        self.assertEqual(result['items'][0]['fee_status'],'paid')
        for filename in ['index.html','briefing.md']:
            text=(self.root/'delivery/public'/filename).read_text()
            self.assertIn('최대 10% 할인',text);self.assertIn('지정 결제수단',text);self.assertIn('https://official.example/',text)
            self.assertNotIn('<테스트>',text);self.assertNotIn('비공개 운영 메모',text)
        self.assertNotIn('비공개 운영 메모',(self.root/'delivery/public/briefing.json').read_text())

    def test_claim_changes_and_recheck_do_not_bypass_existing_release_gate(self):
        item=record()
        changed=record(value(value=20,evidence_quote='최대 20% 할인'));changed['evidence']='최대 20% 할인'
        self.assertEqual(self.export(changed,approved=item)['items'],[])
        self.assertEqual(self.export(dict(item,needs_recheck=True),approved=item)['items'],[])

    def test_missing_value_does_not_change_existing_public_contract(self):
        result=self.export(benefit().data())
        self.assertEqual(len(result['items']),1);self.assertNotIn('benefit_value',result['items'][0])

    def test_private_value_conditions_are_rejected_before_publication(self):
        item=record(value(conditions='연락 010-1234-5678'))
        with self.assertRaises(ValueError):self.export(item)

    def test_value_payment_evidence_cannot_publish_credential_query_parameters(self):
        target='https://official.example/payment?token=synthetic-secret'
        terms=dict(method='테스트',funding_source='테스트',excluded_methods='미확인',minimum_spend='미확인',limit='미확인',evidence_url=target)
        item=dict(record(value(evidence_url=target)),payment_terms=terms)
        with self.assertRaises(ValueError):self.export(item)

    def test_new_value_is_not_publicly_approved_by_a_legacy_or_empty_value_release(self):
        item=record();legacy=dict(item);legacy.pop('benefit_value')
        self.assertEqual(self.export(item,approved=legacy)['items'],[])
        self.assertEqual(self.export(item,approved=dict(item,benefit_value={}))['items'],[])
