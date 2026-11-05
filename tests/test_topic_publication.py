import json
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch

import test_public_topics as topic_test
from test_pipeline import NOW
from benefit_monitor.store import save


class TopicPublicationTests(unittest.TestCase):
    setUp=topic_test.PublicTopicsTests.setUp
    approve_basis=topic_test.PublicTopicsTests.approve_basis
    fake_topic_model=topic_test.PublicTopicsTests.fake_topic_model
    def prepare_draft(self):
        from benefit_monitor.topic_refresh import refresh
        self.approve_basis()
        with patch('benefit_monitor.topic_refresh.invoke',side_effect=self.fake_topic_model):
            return refresh(self.root,NOW,execute=True)

    def test_export_requires_explicit_hash_bound_publication_approval(self):
        from benefit_monitor.topic_publication import cards
        from benefit_monitor.public_topics import content_hash
        draft=self.prepare_draft()
        self.assertIsNone(cards(self.root,NOW))
        save(self.root/'public/topic-publication.json',dict(approved=True,draft_sha256=content_hash(draft),expires_at=(NOW+timedelta(hours=2)).isoformat()))
        exported=cards(self.root,NOW)
        self.assertEqual(exported['topics'][0]['id'],'culture')
        self.assertNotIn('evidence_claim_ids',json.dumps(exported))
        self.assertIsNone(cards(self.root,NOW+timedelta(hours=3)))
        draft['topics'][0]['title']='새로 바뀐 제목'
        save(self.root/'cache/ai_topics/draft.json',draft)
        self.assertEqual(cards(self.root,NOW)['topics'][0]['title'],'문화·체험')

    def test_revoked_items_are_removed_before_public_topic_export(self):
        from benefit_monitor.topic_publication import cards
        from benefit_monitor.public_topics import content_hash
        draft=self.prepare_draft()
        save(self.root/'public/topic-publication.json',dict(approved=True,draft_sha256=content_hash(draft),expires_at=(NOW+timedelta(hours=2)).isoformat()))
        save(self.root/'public/verified.json',[])
        value=cards(self.root,NOW)
        self.assertTrue(value is None or value['topics']==[])

    def test_public_export_embeds_cards_only_after_explicit_approval(self):
        from benefit_monitor import publish
        from benefit_monitor.public_topics import content_hash
        draft=self.prepare_draft()
        self.assertNotIn('topic_cards',publish.run(self.root,now=NOW))
        save(self.root/'public/topic-publication.json',dict(approved=True,draft_sha256=content_hash(draft),expires_at=(NOW+timedelta(hours=2)).isoformat()))
        data=publish.run(self.root,now=NOW)
        self.assertEqual(data['topic_cards']['topics'][0]['id'],'culture')
        exported=json.loads((self.root/'delivery/public/briefing.json').read_text())
        self.assertEqual(exported['topic_cards'],data['topic_cards'])

    def test_standing_policy_is_bound_to_reviewed_rules_and_basis(self):
        from benefit_monitor.topic_publication import cards,policy_hash
        self.prepare_draft()
        save(self.root/'public/topic-publication.json',dict(approved=True,mode='reviewed_policy',policy_sha256=policy_hash(self.root),expires_at=(NOW+timedelta(days=4)).isoformat()))
        self.assertEqual(cards(self.root,NOW)['topics'][0]['id'],'culture')
        basis=json.loads((self.root/'public/topic-basis.json').read_text());basis['items'][0]['topic_ids']=['career']
        save(self.root/'public/topic-basis.json',basis)
        self.assertIsNone(cards(self.root,NOW))

    def test_malformed_topic_approval_does_not_break_verified_briefing_export(self):
        from benefit_monitor import publish
        for text in ['not-json','[]']:
            path=self.root/'public/topic-publication.json';path.write_text(text)
            data=publish.run(self.root,now=NOW)
            self.assertNotIn('topic_cards',data)
            self.assertEqual(len(data['items']),1)

    def test_two_day_end_to_end_chain_and_model_failure_fallback(self):
        import io
        from benefit_monitor import cost_policy
        from benefit_monitor.ai_daily import daily
        from benefit_monitor.topic_publication import policy_hash
        from test_pipeline import SOURCE
        self.approve_basis()
        save(self.root/'sources.yaml',dict(sources=[dict(SOURCE,feed_url='https://official.example/feed')],max_age_days=7))
        save(self.root/'ai-automation.json',dict(enabled=True,recurring_spend_approved=True,public_application_approved=True,max_ai_candidates_per_day=2))
        save(self.root/'public/topic-publication.json',dict(approved=True,mode='reviewed_policy',policy_sha256=policy_hash(self.root),expires_at=(NOW+timedelta(days=4)).isoformat()))
        for name in ('README.md','research.md','research-extraction.md','schemas/research-extraction-v3.schema.json'):
            path=self.root/'docs/ai'/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('테스트 지침')
        def public_fetch(url,domains):
            cost_policy.budget.consume()
            if url.endswith('/robots.txt'):return b'User-agent: *\nAllow: /'
            return ('<rss><channel><item><title>'+self.item['title']+'</title><link>'+self.item['url']+'</link></item></channel></rss>').encode()
        class Response(io.BytesIO):headers={'Content-Type':'text/html'}
        def read_body(request):
            return Response(b'User-agent: *\nAllow: /' if request.full_url.endswith('/robots.txt') else b'<html><main>Official public program body for a controlled test. Conditions and application dates have been reviewed for this synthetic fixture.</main></html>')
        calls=[]
        def model(root,kind,input_path):
            calls.append(kind)
            if kind=='research' or len(calls)>2:return {'status':'rejected_draft','run_id':'b'*64}
            return self.fake_topic_model(root,kind,input_path)
        with patch('benefit_monitor.collectors.rss.fetch',side_effect=public_fetch),patch('benefit_monitor.official_reader.network_open',side_effect=read_body),patch('benefit_monitor.ai_review.invoke',side_effect=model),patch('benefit_monitor.topic_refresh.invoke',side_effect=model):
            first=daily(self.root,NOW,online=True,allow_spend=True,publish=True)
            second=daily(self.root,NOW+timedelta(days=1),online=True,allow_spend=True,publish=True)
        self.assertEqual(calls,['research','topic','topic'])
        self.assertFalse(first['topics']['used_fallback'])
        self.assertTrue(second['topics']['used_fallback'])
        public=json.loads((self.root/'delivery/public/briefing.json').read_text())
        self.assertEqual(public['topic_cards']['topics'][0]['id'],'culture')
        self.assertEqual(public['items'][0]['verified_at'],self.item['verified_at'])
        self.assertNotIn('cache/ai_review',json.dumps(public))
        self.assertEqual(len(list((self.root/'cache/ai_review/queue').glob('*.json'))),1)


if __name__=='__main__':unittest.main()
