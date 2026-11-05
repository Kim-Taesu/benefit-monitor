import json
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from benefit_monitor.store import save
from test_pipeline import benefit,SOURCE,NOW,ROOT


class PublicTopicsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.item=benefit(fee_status='paid',conditions='입장료 5000원, 서울 문화 체험').data()
        save(self.root/'sources.yaml',dict(sources=[SOURCE],max_age_days=7))
        self.report=dict(verified_at=NOW.isoformat(),new=[self.item],needs_recheck=[],collection=dict(online=True,successful_sources=['test']))
        save(self.root/'report.json',self.report)
        save(self.root/'public/verified.json',[dict(self.item,public_release=True)])

    def approve_basis(self):
        from benefit_monitor.public_topics import content_hash
        from benefit_monitor.publish import payload
        data=payload(self.root,NOW)['items'][0]
        save(self.root/'public/topic-basis.json',{'schema_version':1,'items':[
            {'item_id':benefit().id,'content_sha256':content_hash(data),'approved':True,'topic_ids':['culture'],'title_facets':[]}]})

    def test_only_public_approved_facts_and_reviewed_content_bound_topic_basis_enter(self):
        from benefit_monitor.public_topics import approved_snapshot
        self.assertEqual(approved_snapshot(self.root,NOW,[])['approved_items'],[])
        self.approve_basis()
        host=approved_snapshot(self.root,NOW,[])
        self.assertEqual(len(host['approved_items']),1)
        self.assertEqual(host['approved_items'][0]['item_id'],benefit().id)
        self.assertEqual(host['approved_items'][0]['topic_basis']['topic_ids'],['culture'])
        self.assertFalse((self.root/'delivery/public').exists())
        self.assertNotIn('evidence',host['approved_items'][0])
        from benefit_monitor.claude_trial import validate_host
        validate_host(host,'topic',self.root)
        host['approved_items'][0]['conditions']='변조한 조건'
        with self.assertRaises(ValueError):validate_host(host,'topic',self.root)

    def test_changed_fact_or_revoked_public_approval_removes_topic_input(self):
        from benefit_monitor.public_topics import approved_snapshot
        self.approve_basis()
        self.item['conditions']='입장료 10000원, 변경된 조건'
        self.report['new']=[self.item]
        save(self.root/'report.json',self.report)
        save(self.root/'public/verified.json',[dict(self.item,public_release=True)])
        self.assertEqual(approved_snapshot(self.root,NOW,[])['approved_items'],[])
        save(self.root/'public/verified.json',[])
        self.assertEqual(approved_snapshot(self.root,NOW,[])['approved_items'],[])

    def test_expired_or_review_held_items_never_reenter_by_previous_cards(self):
        from benefit_monitor.public_topics import approved_snapshot
        self.approve_basis()
        self.report['needs_recheck']=[self.item];self.report['new']=[]
        save(self.root/'report.json',self.report)
        host=approved_snapshot(self.root,NOW,[{'topic_id':'culture','item_links':[{'item_id':benefit().id}]}])
        self.assertEqual(host['approved_items'],[])

    def fake_topic_model(self,root,kind,input_path):
        host=json.loads(input_path.read_text());item=host['approved_items'][0]
        result={'schema_version':'trial-result-v1','mode':'api_agent','status':'completed','errors':[],
                'topics':[{'schema_version':'topic-draft-v1','topic_id':'culture','title':'문화·체험',
                           'item_links':[{'item_id':item['item_id'],'evidence_claim_ids':item['claim_ids'],'reason':'승인된 문화체험','match_type':'explicit'}],
                           'profile_conditions':[],'excluded_items':[],'snapshot_id':host['snapshot_id'],'audit':None}],
                'excluded_items':[]}
        save(root/'.tools/claude-trial/live/runs'/('a'*64)/'result.json',result)
        return {'status':'validated_draft','run_id':'a'*64}

    def test_refresh_saves_only_private_draft_and_attempts_once_per_day(self):
        from unittest.mock import patch
        from benefit_monitor.topic_refresh import refresh
        self.approve_basis()
        with patch('benefit_monitor.topic_refresh.invoke',side_effect=self.fake_topic_model):
            first=refresh(self.root,NOW,execute=True)
        with patch('benefit_monitor.topic_refresh.invoke',side_effect=AssertionError('once per KST day')):
            second=refresh(self.root,NOW+timedelta(minutes=1),execute=True)
        self.assertEqual(len(first['topics']),1)
        self.assertFalse(first['used_fallback'])
        self.assertTrue(second['used_fallback'])
        self.assertEqual(second['topics'][0]['item_links'][0]['item_id'],benefit().id)
        self.assertFalse((self.root/'delivery/public/topics.json').exists())
        self.assertFalse(first['publication_approved'])

    def test_refresh_failure_uses_previous_valid_only_and_drops_revoked_items(self):
        from unittest.mock import patch
        from benefit_monitor.topic_refresh import refresh
        self.approve_basis()
        with patch('benefit_monitor.topic_refresh.invoke',side_effect=self.fake_topic_model):refresh(self.root,NOW,execute=True)
        later=NOW+timedelta(days=1);self.report['verified_at']=later.isoformat();save(self.root/'report.json',self.report)
        with patch('benefit_monitor.topic_refresh.invoke',return_value={'status':'rejected_draft','run_id':'b'*64}):
            fallback=refresh(self.root,later,execute=True)
        self.assertTrue(fallback['used_fallback'])
        self.assertEqual(len(fallback['topics']),1)
        save(self.root/'public/verified.json',[])
        revoked=refresh(self.root,later+timedelta(minutes=1),execute=False)
        self.assertEqual(revoked['topics'],[])

    def test_reviewed_category_rule_uses_only_already_approved_category_facts(self):
        from benefit_monitor.public_topics import approved_snapshot
        self.item['labels']={'category':'문화·체험'};self.report['new']=[self.item]
        save(self.root/'report.json',self.report);save(self.root/'public/verified.json',[dict(self.item,public_release=True)])
        basis={'schema_version':1,'items':[],'category_policy':{'approved':False,'mapping':{'문화·체험':['culture']}}}
        save(self.root/'public/topic-basis.json',basis)
        self.assertEqual(approved_snapshot(self.root,NOW,[])['approved_items'],[])
        basis['category_policy']['approved']=True;save(self.root/'public/topic-basis.json',basis)
        host=approved_snapshot(self.root,NOW,[])
        self.assertEqual(host['approved_items'][0]['topic_basis']['topic_ids'],['culture'])
        self.assertEqual(host['approved_items'][0]['topic_basis']['title_facets'],[])
        basis['category_policy']['mapping']={'문화·체험':['career']};save(self.root/'public/topic-basis.json',basis)
        with self.assertRaises(ValueError):approved_snapshot(self.root,NOW,[])


if __name__=='__main__':unittest.main()
