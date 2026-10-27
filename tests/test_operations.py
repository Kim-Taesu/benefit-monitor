import tempfile
import unittest
from pathlib import Path
from datetime import timedelta
from unittest.mock import patch
from benefit_monitor import cli
from benefit_monitor.store import save, load
from test_pipeline import benefit, SOURCE, NOW

class OperationsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        save(self.root/'sources.yaml',dict(sources=[dict(SOURCE,feed_url='https://official.example/feed')],max_age_days=7))
        self.item=benefit();save(self.root/'inputs/items.json',[self.item.data()])

    def run_at(self,title,now=NOW):
        candidate=dict(source='test',url=self.item.url,title=title,summary='candidate',needs_recheck=True)
        with patch('benefit_monitor.cli.collect',return_value=[candidate]):
            return cli.run(self.root,self.root/'inputs/items.json',True,now)

    def test_changed_observed_title_cannot_be_overwritten_by_approval(self):
        self.run_at('Original source title')
        r=self.run_at('New conditions in title',NOW+timedelta(hours=1))
        self.assertEqual(len(r['needs_recheck']),1)
        self.assertEqual(r['review_queue'][0]['reason'],'title_changed')
        self.assertEqual(self.run_at('New conditions in title',NOW+timedelta(hours=2))['needs_recheck'][0]['verified_at'],self.item.verified_at)

    def test_first_observed_title_can_differ_from_editorial_title(self):
        r=self.run_at('Original source title')
        self.assertEqual(len(r['new']),1)
        self.assertEqual(r['needs_recheck'],[])

    def test_new_review_clears_hold_but_same_approval_does_not(self):
        self.run_at('Original');self.run_at('Changed',NOW+timedelta(hours=1))
        updated=self.item.data();updated['verified_at']=(NOW+timedelta(hours=2)).isoformat()
        save(self.root/'inputs/items.json',[updated])
        self.assertEqual(self.run_at('Changed',NOW+timedelta(hours=3))['needs_recheck'],[])

    def test_state_contains_no_raw_text_or_url(self):
        self.run_at('private-looking source text')
        state=load(self.root/'cache/operational_state.json',{})
        self.assertIn(self.item.id,state.get('items',{}))
        self.assertNotIn('private-looking',str(state));self.assertNotIn(self.item.url,str(state))

    def test_body_change_holds_approval_and_respects_robots(self):
        from benefit_monitor import operations, cost_policy
        state={};cost_policy.reset(60)
        body=b'<main>'+b'Public conditions '*10+b'Fee 1000</main>'
        def response(url,domains):
            return b'User-agent: *\nAllow: /' if url.endswith('/robots.txt') else body
        with patch('benefit_monitor.collectors.rss.fetch',side_effect=response):
            operations.check_bodies(state,[self.item],{'test':SOURCE},NOW,1)
            body=body.replace(b'1000',b'2000')
            operations.check_bodies(state,[self.item],{'test':SOURCE},NOW+timedelta(hours=1),1)
        held=operations.observe(state,[],[self.item],NOW+timedelta(hours=1))
        self.assertTrue(held[0].needs_recheck)
        self.assertEqual(state['items'][self.item.id]['hold_reason'],'body_changed')
        self.assertNotIn('Public conditions',str(state))
        with patch('benefit_monitor.collectors.rss.fetch',return_value=b'User-agent: *\nDisallow: /'):
            errors=operations.check_bodies({},[self.item],{'test':SOURCE},NOW,1)
        self.assertEqual(errors[0]['category'],'robots_denied')

    def test_body_budget_zero_does_not_claim_checked(self):
        from benefit_monitor import operations
        state={}
        self.assertEqual(operations.check_bodies(state,[self.item],{'test':SOURCE},NOW,0),[])
        self.assertEqual(state,{})

    def test_fresh_checkout_uses_restored_state_for_change_and_newness(self):
        self.run_at('Original')
        # Only hash metadata survives a runner replacement, not raw item cache.
        (self.root/'cache/verified_items.json').unlink()
        r=self.run_at('Original',NOW+timedelta(hours=1))
        self.assertEqual(len(r['new']),0)
        self.assertEqual(len(r['still_valid']),1)
        (self.root/'cache/verified_items.json').unlink()
        r=self.run_at('Changed',NOW+timedelta(hours=2))
        self.assertEqual(len(r['needs_recheck']),1)

    def test_state_schema_rejects_untrusted_data(self):
        from benefit_monitor import operations
        for state in ({'schema_version':99,'items':{}},
                      {'schema_version':1,'items':{'bad':{'source':'test'}}},
                      {'schema_version':1,'items':{self.item.id:{'source':'test','title_hash':'secret'}}}):
            with self.assertRaises(ValueError):operations.sanitize(state,{'test'},NOW)
        clean=operations.sanitize({'schema_version':1,'items':{},'profile':'private'},{'test'},NOW)
        self.assertNotIn('profile',clean)

    def test_body_budget_is_not_spent_on_expired_or_excluded_records(self):
        from benefit_monitor import operations,cost_policy
        cost_policy.reset(60);state={}
        expired=benefit(url='https://official.example/expired',valid_until='2026-10-25')
        with patch('benefit_monitor.collectors.rss.fetch',return_value=b'User-agent: *\nDisallow: /'):
            operations.check_bodies(state,[expired,self.item],{'test':SOURCE},NOW,1)
        self.assertIn(self.item.id,state['items'])
        self.assertNotIn(expired.id,state['items'])

    def test_unreviewed_candidate_stays_queued_when_missing_from_next_listing(self):
        save(self.root/'inputs/items.json',[])
        self.run_at('Unreviewed announcement')
        (self.root/'cache/verified_items.json').unlink()
        with patch('benefit_monitor.cli.collect',return_value=[]):
            result=cli.run(self.root,self.root/'inputs/items.json',True,NOW+timedelta(days=1))
        self.assertEqual(len(result['review_queue']),1)
        self.assertEqual(result['review_queue'][0]['id'],self.item.id)
