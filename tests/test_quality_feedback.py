import unittest
from copy import deepcopy
from datetime import timedelta
from benefit_monitor.validation import validate
from benefit_monitor import publish
from test_pipeline import benefit,SOURCES,NOW

class QualityFeedbackTests(unittest.TestCase):
    def terms(self):
        return dict(method='QR 또는 페이스사인',funding_source='포인트·머니',excluded_methods='카드 재원 결제는 명시된 대상에 포함되지 않음',minimum_spend='미확인',limit='1인 1회 최대 1만 포인트',evidence_url='https://official.example/event')
    def test_payment_terms_require_funding_and_exclusions_and_official_evidence(self):
        d=benefit().data();d['payment_terms']=self.terms()
        self.assertEqual(validate(d,SOURCES,NOW).payment_terms['funding_source'],'포인트·머니')
        for key in ('funding_source','excluded_methods'):
            broken=deepcopy(d);broken['payment_terms'][key]=''
            with self.assertRaises(ValueError):validate(broken,SOURCES,NOW)
        d['payment_terms']['evidence_url']='https://evil.example/event'
        with self.assertRaises(ValueError):validate(d,SOURCES,NOW)
    def test_manual_snapshot_never_proves_scheduled_run(self):
        context=publish.run_context(NOW, NOW.replace(hour=1), 'workflow_dispatch')
        self.assertEqual(context['status'],'pre_schedule_snapshot')
        self.assertFalse(context['scheduled_run_confirmed'])
        context=publish.run_context(NOW, NOW, 'workflow_dispatch')
        self.assertEqual(context['status'],'manual_refresh')
        self.assertFalse(context['scheduled_run_confirmed'])
        self.assertTrue(publish.run_context(NOW,NOW,'schedule')['scheduled_run_confirmed'])
