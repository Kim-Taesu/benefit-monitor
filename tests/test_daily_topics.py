from copy import deepcopy
from datetime import datetime
import unittest
from benefit_monitor.daily_topics import snapshot, fallback

class DailyTopicsTests(unittest.TestCase):
    def setUp(self):
        self.items=[{'item_id':'a','summary':'할인','conditions':'대상상품 할인','claim_ids':['ca'],'display_eligible':True,'valid_until':'2026-11-10','topic_basis':{'topic_ids':['shopping'],'title_facets':[],'evidence_claim_ids':['ca']}},
                    {'item_id':'b','summary':'예약','conditions':'선착순','claim_ids':['cb'],'display_eligible':True,'deadline_at':'2026-11-09T23:59:00+09:00'}]
        self.claims=[{'id':'ca','item_id':'a'},{'id':'cb','item_id':'b'}]
        self.previous=[{'topic_id':'shopping','title':'이번주 특별 혜택','item_links':[{'item_id':'a','evidence_claim_ids':['ca'],'reason':'구매할인','match_type':'explicit'},{'item_id':'b','evidence_claim_ids':['cb'],'reason':'예약','match_type':'contextual'}],'profile_conditions':[],'excluded_items':[],'audit':None,'schema_version':'topic-draft-v1','snapshot_id':'old'}]

    def test_day_boundary_and_deadline_keep_only_eligible(self):
        now=datetime.fromisoformat('2026-11-10T00:00:00+09:00')
        s=snapshot(self.items,self.claims,now,'review',self.previous)
        self.assertEqual([x['item_id'] for x in s['approved_items']],['a'])
        self.assertEqual(s['excluded_items'],[{'item_id':'b','reason':'closed_or_expired'}])
        self.assertEqual([c['id'] for c in s['approved_claims']],['ca'])
        later=snapshot(self.items,self.claims,datetime.fromisoformat('2026-11-11T00:00:00+09:00'),'review',self.previous)
        self.assertEqual(later['approved_items'],[])
        self.assertNotEqual(s['snapshot_id'],later['snapshot_id'])

    def test_kst_date_and_same_input_are_deterministic(self):
        now=datetime.fromisoformat('2026-11-10T15:00:00+00:00')
        a=snapshot(self.items,self.claims,now,'review',self.previous)
        b=snapshot(deepcopy(self.items),deepcopy(self.claims),now,'review',deepcopy(self.previous))
        self.assertEqual(a,b)
        self.assertEqual(a['approved_items'],[])

    def test_fallback_drops_expired_links_and_relative_titles(self):
        s=snapshot(self.items,self.claims,datetime.fromisoformat('2026-11-10T12:00:00+09:00'),'review',self.previous)
        cards=fallback(self.previous,s)
        self.assertEqual([x['item_id'] for x in cards[0]['item_links']],['a'])
        self.assertEqual(cards[0]['title'],'장보기·멤버십')
        self.assertEqual(cards[0]['snapshot_id'],s['snapshot_id'])
        s['approved_items']=[]
        self.assertEqual(fallback(self.previous,s),[])
        self.assertEqual(len(self.previous[0]['item_links']),2)

    def test_naive_timestamps_and_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):snapshot(self.items,self.claims,datetime(2026,11,5),'review',[])
        bad=deepcopy(self.items);bad[1]['deadline_at']='2026-11-09T23:59:00'
        with self.assertRaises(ValueError):snapshot(bad,self.claims,datetime.fromisoformat('2026-11-05T12:00:00+09:00'),'review',[])
        with self.assertRaises(ValueError):snapshot(self.items+self.items,self.claims,datetime.fromisoformat('2026-11-05T12:00:00+09:00'),'review',[])

    def test_fallback_does_not_resurrect_wrong_topic_membership(self):
        s=snapshot(self.items,self.claims,datetime.fromisoformat('2026-11-10T12:00:00+09:00'),'review',[])
        self.previous[0]['topic_id']='career'
        self.assertEqual(fallback(self.previous,s),[])


if __name__=='__main__':unittest.main()
