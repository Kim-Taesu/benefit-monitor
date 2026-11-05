from copy import deepcopy
import importlib
import unittest


class TopicSemanticsTests(unittest.TestCase):
    def setUp(self):
        self.host={'snapshot_id':'s','approved_items':[{'item_id':'a','display_eligible':True,'claim_ids':['c'],
                    'topic_basis':{'topic_ids':['culture','family'],'title_facets':['family','weekend','free'],
                                   'evidence_claim_ids':['c']}}],
                   'approved_claims':[{'id':'c','item_id':'a','field':'reviewed_conditions','value':'가족 주말 체험, 참가비 무료'}]}
        self.result={'topics':[{'topic_id':'culture','title':'주말 가족 무료 문화 체험',
                      'item_links':[{'item_id':'a','evidence_claim_ids':['c'],'reason':'취업과 관련 있음'}]}]}

    def review(self):
        return importlib.import_module('benefit_monitor.topic_semantics').review(self.result,self.host)

    def test_supported_topics_and_all_title_facets_pass_only_local_gate(self):
        report=self.review()
        self.assertTrue(report['valid'],report)
        self.assertFalse(report['publication_approved'])

    def test_career_cannot_be_proved_by_model_reason(self):
        self.result['topics'][0]['topic_id']='career'
        self.assertIn('unsupported_topic',[x['code'] for x in self.review()['findings']])

    def test_family_weekend_and_free_require_every_item(self):
        item=deepcopy(self.host['approved_items'][0]);item.update(item_id='b',claim_ids=['cb'])
        item['topic_basis']={'topic_ids':['culture'],'title_facets':[],'evidence_claim_ids':['cb']}
        self.host['approved_items'].append(item)
        self.host['approved_claims'].append({'id':'cb','item_id':'b','value':'성인 평일 유료 체험'})
        self.result['topics'][0]['item_links'].append({'item_id':'b','evidence_claim_ids':['cb'],'reason':'가족에게 추천'})
        findings=self.review()['findings']
        self.assertEqual({x['facet'] for x in findings if x['code']=='unsupported_title_facet'},{'family','weekend','free'})

    def test_missing_or_foreign_basis_is_review_required(self):
        del self.host['approved_items'][0]['topic_basis']
        self.assertFalse(self.review()['valid'])
        self.host['approved_items'][0]['topic_basis']={'topic_ids':['culture'],'title_facets':['family','weekend','free'],'evidence_claim_ids':['other']}
        self.assertIn('invalid_topic_basis',[x['code'] for x in self.review()['findings']])

    def test_generic_title_does_not_waive_topic_membership(self):
        self.result['topics'][0].update(topic_id='career',title='주제 모음')
        self.assertFalse(self.review()['valid'])

    def test_unrecognized_title_requires_editor_review(self):
        self.result['topics'][0]['title']='누구나 전액 보장 특별 혜택'
        self.assertIn('unreviewed_title',[x['code'] for x in self.review()['findings']])

    def test_relative_weekend_is_not_proven_by_generic_weekend_basis(self):
        self.result['topics'][0]['title']='이번 주말 가족 무료 문화 체험'
        self.assertIn('relative_title_requires_review',[x['code'] for x in self.review()['findings']])

    def test_malformed_basis_stays_closed(self):
        for value in [None,{},[['culture']]]:
            self.host['approved_items'][0]['topic_basis']['topic_ids']=value
            self.assertFalse(self.review()['valid'])
        self.host['approved_items'][0]['topic_basis']['topic_ids']=['culture']
        self.host['approved_items'][0]['topic_basis']['evidence_claim_ids']=[{}]
        self.assertFalse(self.review()['valid'])

    def test_fallback_link_cannot_hide_a_foreign_extra_claim(self):
        self.result['topics'][0]['item_links'][0]['evidence_claim_ids'].append('foreign')
        self.assertFalse(self.review()['valid'])

    def test_card_wide_profile_condition_requires_separate_review(self):
        self.result['topics'][0]['profile_conditions']=[{'field':'age','operator':'between','min':19,'max':39,'basis':'일부 항목의 나이 조건','reference_date':None}]
        self.assertIn('profile_conditions_require_review',[f['code'] for f in self.review()['findings']])


if __name__ == '__main__':unittest.main()
