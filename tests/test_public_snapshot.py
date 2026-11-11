from copy import deepcopy
from datetime import timedelta
import json
import unittest

from benefit_monitor import publish
from benefit_monitor.store import save
from test_pipeline import NOW,benefit
import test_topic_publication as topic_test


class PublicSnapshotTests(unittest.TestCase):
    setUp=topic_test.TopicPublicationTests.setUp
    approve_basis=topic_test.TopicPublicationTests.approve_basis
    fake_topic_model=topic_test.TopicPublicationTests.fake_topic_model
    prepare_draft=topic_test.TopicPublicationTests.prepare_draft

    def stage(self,data,now=NOW):
        from benefit_monitor.public_snapshot import stage
        return stage(self.root,data,now)

    def test_snapshot_uses_existing_release_gate_and_renders_without_runtime_report(self):
        raw=publish.payload(self.root,now=NOW)
        raw['profile']={'private':'not public'}
        (self.root/'report.json').unlink()
        clean=self.stage(raw)
        self.assertEqual(clean['items'][0]['conditions'],self.item['conditions'])
        self.assertNotIn('profile',clean)
        self.assertEqual(json.loads((self.root/'delivery/public/briefing.json').read_text()),clean)
        self.assertTrue((self.root/'delivery/public/briefing.md').exists())

    def test_changed_or_unapproved_fact_is_rejected_before_export(self):
        raw=publish.payload(self.root,now=NOW);raw['items'][0]['conditions']='unapproved new conditions'
        with self.assertRaises(ValueError):self.stage(raw)
        self.assertFalse((self.root/'delivery/public/briefing.json').exists())

    def test_expired_and_future_snapshots_and_extended_item_cutoff_fail(self):
        raw=publish.payload(self.root,now=NOW)
        for stamp in [NOW-timedelta(hours=3),NOW+timedelta(minutes=1)]:
            changed=deepcopy(raw);changed['generated_at']=stamp.isoformat()
            with self.assertRaises(ValueError):self.stage(changed)
        changed=deepcopy(raw);changed['items'][0]['display_until']='2027-01-01T00:00:00+09:00'
        with self.assertRaises(ValueError):self.stage(changed)

    def test_current_local_hold_cannot_be_erased_by_snapshot(self):
        raw=publish.payload(self.root,now=NOW)
        save(self.root/'cache/operational_state.json',{'schema_version':1,'items':{
            benefit().id:{'source':'test','hold_at':NOW.isoformat(),'hold_reason':'body_changed'}},'sources':{}})
        self.assertEqual(self.stage(raw)['items'],[])

    def test_approved_topic_bundle_is_revalidated_without_private_draft(self):
        from benefit_monitor.topic_publication import policy_hash
        self.prepare_draft()
        save(self.root/'public/topic-publication.json',dict(approved=True,mode='reviewed_policy',policy_sha256=policy_hash(self.root),expires_at=(NOW+timedelta(hours=2)).isoformat()))
        raw=publish.run(self.root,now=NOW)
        (self.root/'report.json').unlink()
        clean=self.stage(raw)
        self.assertEqual(clean['topic_cards']['topics'][0]['id'],'culture')
        self.assertNotIn('evidence_claim_ids',json.dumps(clean['topic_cards']))
        raw['topic_cards']['topics'][0]['title']='누구나 무료 보장'
        self.assertNotIn('topic_cards',self.stage(raw))

    def test_failure_snapshot_cannot_embed_recommendations(self):
        raw=publish.payload(self.root,now=NOW);raw['status']='collection_failed'
        with self.assertRaises(ValueError):self.stage(raw)
        failed=publish.payload(self.root,now=NOW,failure=True)
        self.assertEqual(self.stage(failed)['items'],[])

    def test_snapshot_preserves_observed_district_count_and_time(self):
        save(self.root/'districts.json',{'districts':[{'name':'강서구'}]})
        report=json.loads((self.root/'report.json').read_text())
        report['district_coverage']=[{'district':'강서구','status':'checked','mode':'live',
                                     'checked_at':NOW.isoformat(),'candidates_count':7}]
        save(self.root/'report.json',report)
        raw=publish.payload(self.root,now=NOW)
        row=self.stage(raw)['coverage']['districts'][0]
        self.assertEqual(row['candidates_count'],7)
        self.assertEqual(row['checked_at'],NOW.isoformat())
        for bad in (-1,True,'7'):
            changed=deepcopy(raw);changed['coverage']['districts'][0]['candidates_count']=bad
            with self.assertRaises(ValueError):self.stage(changed)

    def test_import_requests_only_pinned_commit_and_never_an_llm(self):
        import base64,subprocess
        from unittest.mock import patch
        from benefit_monitor.public_snapshot import import_remote
        data=publish.payload(self.root,now=NOW)
        envelope={'encoding':'base64','content':base64.b64encode(json.dumps(data).encode()).decode()}
        requested=[]
        def process(args,**kwargs):
            requested.append(args)
            if '/contents/briefing.json' not in args[-1]:  # No AI approval files on the data branch yet.
                return subprocess.CompletedProcess(args,1,'','gh: Not Found (HTTP 404)')
            return subprocess.CompletedProcess(args,0,json.dumps(envelope),'')
        with patch('benefit_monitor.public_snapshot.subprocess.run',side_effect=process):
            result=import_remote(self.root,'Kim-Taesu/benefit-monitor','a'*40,now=NOW)
        self.assertEqual(len(result['items']),1)
        self.assertEqual(requested[0][-1],'repos/Kim-Taesu/benefit-monitor/contents/briefing.json?ref='+'a'*40)
        with patch('benefit_monitor.public_snapshot.subprocess.run',side_effect=AssertionError('invalid request must stop')):
            with self.assertRaises(ValueError):import_remote(self.root,'company/private','a'*40,now=NOW)
            with self.assertRaises(ValueError):import_remote(self.root,'Kim-Taesu/benefit-monitor','briefing-data',now=NOW)

    def test_clean_checkout_receives_only_public_files_and_revalidates_bundle(self):
        import tempfile,shutil
        from pathlib import Path
        from test_pipeline import ROOT
        from benefit_monitor.topic_publication import policy_hash
        from benefit_monitor.public_snapshot import stage
        self.prepare_draft()
        save(self.root/'public/topic-publication.json',dict(approved=True,mode='reviewed_policy',policy_sha256=policy_hash(self.root),expires_at=(NOW+timedelta(hours=2)).isoformat()))
        source=publish.run(self.root,now=NOW)
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            target=Path(folder)
            for name in ['sources.yaml','public/verified.json','public/topic-basis.json','public/topic-publication.json']:
                path=target/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(self.root/name,path)
            clean=stage(target,source,NOW)
            self.assertEqual(clean['topic_cards']['topics'][0]['id'],'culture')
            self.assertFalse((target/'.env.claude').exists())
            self.assertFalse((target/'.tools/claude-trial/live/budget.json').exists())
            self.assertFalse((target/'cache/ai_topics/draft.json').exists())

    def test_public_snapshot_passes_baselines_through_sanitize(self):
        from unittest.mock import patch
        from test_publish import baseline_bundle
        raw=publish.payload(self.root,now=NOW)
        raw['groceries']={'x':1};raw['grocery_baselines']=baseline_bundle('2026-09-01')
        with patch('benefit_monitor.groceries.sanitize',return_value={'notice':'x'}):
            clean=self.stage(raw)
        self.assertIsNone(clean['grocery_baselines']['items'][0]['baseline'])
        raw['grocery_baselines']=dict(baseline_bundle(),source='x')
        with patch('benefit_monitor.groceries.sanitize',return_value={'notice':'x'}):
            self.assertNotIn('grocery_baselines',self.stage(raw))
        raw['grocery_baselines']=baseline_bundle()
        with patch('benefit_monitor.groceries.sanitize',return_value=None):
            self.assertNotIn('grocery_baselines',self.stage(raw))

    def discount_bundle(self,end='2026-12-31'):
        return dict(schema_version=1,source='grocery_discounts',generated_at=NOW.isoformat(),links=[dict(
            basket_id='onion',title='양파 할인',discount=None,stores=None,start='2026-01-01',end=end,url='https://www.mof.go.kr/a')])

    def test_public_snapshot_passes_discounts_through_sanitize(self):
        from unittest.mock import patch
        raw=publish.payload(self.root,now=NOW)
        raw['groceries']={'x':1};raw['grocery_discounts']=self.discount_bundle()
        with patch('benefit_monitor.groceries.sanitize',return_value={'notice':'x'}):
            clean=self.stage(raw)
        self.assertEqual(clean['grocery_discounts']['links'][0]['basket_id'],'onion')
        raw['grocery_discounts']=self.discount_bundle(end='2026-01-02')
        with patch('benefit_monitor.groceries.sanitize',return_value={'notice':'x'}):
            self.assertNotIn('grocery_discounts',self.stage(raw))
        raw['grocery_discounts']=dict(self.discount_bundle(),source='x')
        with patch('benefit_monitor.groceries.sanitize',return_value={'notice':'x'}):
            self.assertNotIn('grocery_discounts',self.stage(raw))

    def test_public_snapshot_drops_discounts_on_collection_failed(self):
        from unittest.mock import patch
        failed=publish.payload(self.root,now=NOW,failure=True)
        failed['groceries']={'x':1};failed['grocery_discounts']=self.discount_bundle()
        with patch('benefit_monitor.groceries.sanitize',return_value={'notice':'x'}):
            clean=self.stage(failed)
        self.assertNotIn('grocery_discounts',clean)

    def test_public_snapshot_drops_baselines_on_collection_failed(self):
        from unittest.mock import patch
        from test_publish import baseline_bundle
        failed=publish.payload(self.root,now=NOW,failure=True)
        failed['groceries']={'x':1};failed['grocery_baselines']=baseline_bundle()
        with patch('benefit_monitor.groceries.sanitize',return_value={'notice':'x'}):
            clean=self.stage(failed)
        self.assertNotIn('grocery_baselines',clean);self.assertNotIn('groceries',clean)


if __name__=='__main__':unittest.main()
