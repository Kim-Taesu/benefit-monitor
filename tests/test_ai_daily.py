import json
from datetime import datetime,timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parents[1]
NOW=datetime(2026,11,5,7,tzinfo=ZoneInfo('Asia/Seoul'))

class AIDailyTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.policy={'schema_version':1,'enabled':True,'recurring_spend_approved':False,'public_application_approved':False,
                     'hour_kst':6,'minute_kst':0,'max_ai_candidates_per_day':2}
        self.save()

    def save(self):(self.root/'ai-automation.json').write_text(json.dumps(self.policy))

    def run_daily(self,**kwargs):
        from benefit_monitor.ai_daily import daily
        return daily(self.root,now=NOW,**kwargs)

    def test_default_dry_run_and_unapproved_spending_do_not_touch_collection(self):
        with patch('benefit_monitor.ai_daily.collect',side_effect=AssertionError('no collection')):
            self.assertEqual(self.run_daily()['status'],'dry_run')
            with self.assertRaisesRegex(ValueError,'recurring'):self.run_daily(online=True,allow_spend=True)
            with self.assertRaisesRegex(ValueError,'public'):self.run_daily(online=True,publish=True)

    def test_daily_chain_runs_once_per_kst_day_with_both_explicit_gates(self):
        self.policy.update(recurring_spend_approved=True,public_application_approved=True);self.save()
        seen=[]
        def collect(root,**kw):seen.append(('collect',kw['ai_execute']));return {'ai_review':{'queued':1}}
        def refresh(root,**kw):seen.append(('topics',kw['execute']));return {'topics':[],'used_fallback':True}
        def publish(root,**kw):seen.append(('publish',True));return {'status':'awaiting_verification'}
        def grocery(root,now,execute):seen.append(('grocery',execute));return {'status':'completed','source':'ai','model':{'status':'validated_draft'}}
        with patch('benefit_monitor.ai_daily.collect',side_effect=collect),patch('benefit_monitor.ai_daily.refresh',side_effect=refresh),patch('benefit_monitor.ai_daily.publish_briefing',side_effect=publish),patch('benefit_monitor.ai_daily.grocery_refresh',side_effect=grocery):
            first=self.run_daily(online=True,allow_spend=True,publish=True)
            second=self.run_daily(online=True,allow_spend=True,publish=True)
        self.assertEqual(first['status'],'completed')
        self.assertEqual(second['status'],'already_completed_today')
        self.assertEqual(seen,[('collect',True),('topics',True),('grocery',True),('publish',True)])
        self.assertEqual(first['grocery']['source'],'ai')

    def test_grocery_pick_skips_paid_call_after_credit_runs_out(self):
        self.policy.update(recurring_spend_approved=True);self.save()
        seen=[]
        def grocery(root,now,execute):seen.append(execute);return {'status':'completed','source':'rule','model':{'status':'not_requested'}}
        with patch('benefit_monitor.ai_daily.collect',return_value={'ai_review':{'credit_exhausted':True}}),\
                patch('benefit_monitor.ai_daily.refresh',side_effect=AssertionError('no topic call')),\
                patch('benefit_monitor.ai_daily.grocery_refresh',side_effect=grocery):
            result=self.run_daily(online=True,allow_spend=True)
        self.assertEqual((result['status'],seen),('credit_exhausted',[False]))

    def test_crash_does_not_repeat_paid_daily_attempt(self):
        self.policy['recurring_spend_approved']=True;self.save()
        with patch('benefit_monitor.ai_daily.collect',side_effect=SystemExit('crash')):
            with self.assertRaises(SystemExit):self.run_daily(online=True,allow_spend=True)
        with patch('benefit_monitor.ai_daily.collect',side_effect=AssertionError('must not restart')):
            result=self.run_daily(online=True,allow_spend=True)
        self.assertEqual(result['status'],'previous_attempt_requires_review')

    def test_scheduled_run_respects_kst_due_time_and_disabled_policy(self):
        from benefit_monitor.ai_daily import daily
        self.policy['enabled']=False;self.save()
        self.assertEqual(daily(self.root,NOW,scheduled=True)['status'],'disabled')
        self.policy['enabled']=True;self.save()
        self.assertEqual(daily(self.root,NOW.replace(hour=5),scheduled=True)['status'],'not_due')

    def test_authorized_public_run_exports_failure_status_on_collection_error(self):
        self.policy['public_application_approved']=True;self.save()
        seen=[]
        def failure_export(root,**kw):seen.append(kw.get('failure'));return {'status':'collection_failed'}
        with patch('benefit_monitor.ai_daily.collect',side_effect=TimeoutError),patch('benefit_monitor.ai_daily.publish_briefing',side_effect=failure_export):
            with self.assertRaises(TimeoutError):self.run_daily(online=True,publish=True)
        self.assertEqual(seen,[True])

    def test_remote_delivery_requires_its_own_gate_and_follows_public_export(self):
        self.policy.update(public_application_approved=True,remote_delivery_approved=True);self.save()
        seen=[]
        def pub(root,**kw):seen.append('public');return {'status':'partial'}
        def remote(root,policy,**kw):seen.append('remote');return {'status':'dispatched_not_yet_verified'}
        with patch('benefit_monitor.ai_daily.collect',return_value={}),patch('benefit_monitor.ai_daily.refresh',return_value={'topics':[]}),patch('benefit_monitor.ai_daily.publish_briefing',side_effect=pub),patch('benefit_monitor.ai_daily.deliver',side_effect=remote):
            result=self.run_daily(online=True,publish=True)
        self.assertEqual(seen,['public','remote'])
        self.assertEqual(result['remote_delivery']['status'],'dispatched_not_yet_verified')

    def test_past_trial_expiry_no_longer_stops_collection(self):
        self.policy.update(recurring_spend_approved=True,trial_expires_at=(NOW-timedelta(minutes=1)).isoformat());self.save()
        with patch('benefit_monitor.ai_daily.collect',return_value={}) as collect,patch('benefit_monitor.ai_daily.refresh',return_value={'topics':[]}):
            result=self.run_daily(online=True,allow_spend=True)
        self.assertEqual(result['status'],'completed');collect.assert_called_once()

    def test_many_daily_attempts_do_not_stop_collection(self):
        from benefit_monitor.store import save
        save(self.root/'cache/ai_daily/days.json',{'days':{
            f'2026-10-{day:02d}':{'status':'completed'} for day in range(1,31)}})
        with patch('benefit_monitor.ai_daily.collect',return_value={}) as collect,patch('benefit_monitor.ai_daily.refresh',return_value={'topics':[]}):
            self.assertEqual(self.run_daily(online=True)['status'],'completed')
        collect.assert_called_once()

    def test_scheduled_public_delivery_waits_before_spending_for_existing_main_refresh(self):
        self.policy.update(recurring_spend_approved=True,public_application_approved=True,remote_delivery_approved=True);self.save()
        with patch('benefit_monitor.ai_daily.preceding_refresh',return_value={'status':'waiting_for_existing_refresh'}),patch('benefit_monitor.ai_daily.collect',side_effect=AssertionError('must wait before spending')):
            self.assertEqual(self.run_daily(scheduled=True)['status'],'waiting_for_existing_refresh')
        state=self.root/'cache/ai_daily/days.json'
        self.assertFalse(state.exists())


if __name__=='__main__':unittest.main()


class GroceryIsolationTests(unittest.TestCase):
    setUp,save,run_daily=AIDailyTests.setUp,AIDailyTests.save,AIDailyTests.run_daily

    def test_grocery_failure_does_not_fail_the_day(self):
        self.policy.update(recurring_spend_approved=True,public_application_approved=True);self.save()
        published=[]
        with patch('benefit_monitor.ai_daily.collect',return_value={'ai_review':{}}),\
                patch('benefit_monitor.ai_daily.refresh',return_value={'topics':[]}),\
                patch('benefit_monitor.ai_daily.grocery_refresh',side_effect=KeyError('days')),\
                patch('benefit_monitor.ai_daily.publish_briefing',side_effect=lambda root,**kw:published.append(1) or {'status':'ok'}):
            result=self.run_daily(online=True,allow_spend=True,publish=True)
        self.assertEqual((result['status'],result['grocery']['status'],published),('completed','failed',[1]))
