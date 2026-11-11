import base64
from copy import deepcopy
import hashlib
import importlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from benefit_monitor.store import save,load
from benefit_monitor.trial_budget import TrialBudget

ROOT=Path(__file__).resolve().parents[1]
EXPIRY='2026-11-09T13:09:12.753468+09:00'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def blob_sha(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()


class FixtureCrypto:
    recipient='age1'+'a'*58
    def encrypt(self,raw):return b'age-fixture:'+raw
    def decrypt(self,raw):
        if not raw.startswith(b'age-fixture:'):raise ValueError('fixture decryption failed')
        return raw[len(b'age-fixture:'):]


class FixtureGitHub:
    # GitHub inlines contents only up to 1 MB; larger files come back with encoding "none".
    def __init__(self):self.files={};self.blobs={};self.requests=[];self.fail_writes=False;self.inline_limit=1024*1024
    def __call__(self,request):
        self.requests.append(request)
        assert request.full_url.startswith('https://api.github.com/repos/Kim-Taesu/benefit-monitor/')
        suffix=request.full_url.split('/benefit-monitor/',1)[1]
        if suffix.startswith('git/blobs/'):
            raw=self.blobs[suffix.rsplit('/',1)[1]]
            return io.BytesIO(json.dumps({'encoding':'base64','content':base64.b64encode(raw).decode(),'sha':blob_sha(raw)}).encode())
        name=suffix.split('contents/',1)[1].split('?',1)[0]
        if request.get_method()=='GET':
            if name not in self.files:raise HTTPError(request.full_url,404,'missing',{},io.BytesIO())
            raw=self.files[name]
            if len(raw)>self.inline_limit:
                return io.BytesIO(json.dumps({'type':'file','encoding':'none','content':'','sha':blob_sha(raw),'size':len(raw)}).encode())
            return io.BytesIO(json.dumps({'type':'file','encoding':'base64','content':base64.b64encode(raw).decode(),'sha':blob_sha(raw)}).encode())
        if self.fail_writes:raise HTTPError(request.full_url,503,'unavailable',{},io.BytesIO())
        data=json.loads(request.data);old=self.files.get(name)
        if data.get('sha')!=(blob_sha(old) if old is not None else None):
            raise HTTPError(request.full_url,409,'stale',{},io.BytesIO())
        raw=base64.b64decode(data['content']);self.files[name]=raw;self.blobs[blob_sha(raw)]=raw
        return io.BytesIO(json.dumps({'content':{'sha':blob_sha(raw)},'commit':{'sha':'b'*40}}).encode())


class CloudStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.budget_path=self.root/'.tools/claude-trial/live/budget.json'
        TrialBudget.initialize(self.budget_path,'claude-haiku-5-5','0.10','0.50')
        budget=load(self.budget_path,{})
        budget['requests']=[{'id':f'{i+1:064x}','status':'completed' if i<28 else 'failed',
                             'reserved_microdollars':1000,'charged_microdollars':10 if i<28 else 0,
                             'started_at':'2026-11-05T01:00:00+00:00'} for i in range(30)]
        self.policy={'schema_version':1,'approved':True,'trial_id':'2026-11-05','expires_at':EXPIRY,'model':'claude-haiku-5-5',
                     'baseline_requests':30,'baseline_requests_sha256':digest(budget['requests']),
                     'baseline_exposure_microdollars':2280,'recipient':FixtureCrypto.recipient,
                     'baseline_days':{'2026-11-05':'completed'}}
        save(self.root/'public/ai-cloud-trial.json',self.policy)
        self.control={'schema_version':1,'trial_id':'2026-11-05','active':True,'generation':0,
                      'expires_at':EXPIRY,'budget':budget,'days':{'2026-11-05':{'status':'completed'}},
                      'api_key_sha256':'f'*64,'recipient':FixtureCrypto.recipient,'runtime_sha':'a'*40}
        self.remote=FixtureGitHub();self.crypto=FixtureCrypto()

    def module(self):
        try:return importlib.import_module('benefit_monitor.cloud_state')
        except ModuleNotFoundError:self.fail('영속 cloud control이 아직 구현되지 않음')

    def store(self):return self.module().GitHubStateStore(self.root,'fake-personal-token',self.crypto,opener=self.remote)

    def session(self):
        from benefit_monitor.age_state import pack_runtime
        module=self.module();store=self.store()
        self.control['runtime_sha']=store.write('runtime',pack_runtime(self.root),None)
        raw=json.dumps(self.control).encode();store.write('control',raw,None)
        return module.CloudSession.restore(self.root,store)

    def test_repository_metadata_url_has_no_trailing_slash(self):
        import io
        store=self.store()
        def opener(request):
            self.assertEqual(request.full_url,'https://api.github.com/repos/Kim-Taesu/benefit-monitor')
            return io.BytesIO(b'{"private": false}')
        store.opener=opener
        self.assertFalse(store._api('')['private'])

    def test_storage_requires_file_sha_and_does_not_expose_plain_state(self):
        store=self.store();sha=store.write('control',b'private ledger',None)
        self.assertNotEqual(self.remote.files['ai-control.age'],b'private ledger')
        self.assertEqual(store.read('control'),(b'private ledger',sha))
        store.write('control',b'new ledger',sha)
        with self.assertRaises(ValueError):store.write('control',b'stale ledger',sha)
        with self.assertRaises(ValueError):store.read('unknown')
        with self.assertRaises(ValueError):store.read('runtime','not-a-sha')

    def test_missing_or_corrupt_control_does_not_initialize_budget(self):
        module=self.module()
        with self.assertRaises(ValueError):module.CloudSession.restore(self.root,self.store())
        self.assertEqual(load(self.budget_path,{})['requests'],[])
        self.remote.files['ai-control.age']=b'not encrypted'
        with self.assertRaises(ValueError):module.CloudSession.restore(self.root,self.store())

    def test_restore_preserves_all_30_reservations_and_completed_day(self):
        session=self.session()
        self.assertEqual(load(self.budget_path,{})['requests'],self.control['budget']['requests'])
        self.assertEqual(load(self.root/'cache/ai_daily/days.json',{})['days'],self.control['days'])
        with self.assertRaises(ValueError):session.mark_day('2026-11-05')
        session.mark_day('2026-11-06')
        remote=json.loads(self.store().read('control')[0])
        self.assertEqual(remote['days']['2026-11-06']['status'],'attempted')
        self.assertNotIn('2026-11-06',load(self.root/'cache/ai_daily/days.json',{})['days'])

    def test_remote_reservation_failure_prevents_provider_http(self):
        from benefit_monitor.claude_trial import ClaudeClient,TrialError
        session=self.session();self.remote.fail_writes=True
        budget=TrialBudget(self.budget_path,checkpoint=session.checkpoint_budget)
        with patch('benefit_monitor.claude_trial.network_open',side_effect=AssertionError('provider must not be called')):
            with self.assertRaises(TrialError):ClaudeClient(self.root/'fake-live',budget,'fake-provider-key-for-test').message('system','user')
        self.assertEqual(len(load(self.budget_path,{})['requests']),31)
        self.assertEqual(len(json.loads(self.store().read('control')[0])['budget']['requests']),30)

    def test_restart_with_unsettled_reservation_stops_even_without_sent_file(self):
        module=self.module();session=self.session()
        budget=TrialBudget(self.budget_path,checkpoint=session.checkpoint_budget);budget.reserve('e'*64,1000)
        self.assertFalse(any(self.root.rglob('*.sent')))
        with self.assertRaises(ValueError):module.CloudSession.restore(self.root,self.store())

    def test_manual_nonspending_restore_can_preserve_unsettled_reservation_for_review(self):
        import inspect
        module=self.module();session=self.session()
        budget=TrialBudget(self.budget_path,checkpoint=session.checkpoint_budget);budget.reserve('e'*64,1000)
        self.assertIn('allow_unresolved',inspect.signature(module.CloudSession.restore).parameters,'비과금 수동 복구 경로 필요')
        restored=module.CloudSession.restore(self.root,self.store(),allow_unresolved=True)
        self.assertEqual(restored.control['budget']['requests'][-1]['status'],'reserved')
        with self.assertRaises(ValueError):module.CloudSession.restore(self.root,self.store())

    def test_parent_reloads_budget_after_child_checkpoint(self):
        module=self.module();parent=self.session();parent.mark_day('2026-11-06')
        child=module.CloudSession.from_context(self.root,self.store())
        budget=TrialBudget(self.budget_path,checkpoint=child.checkpoint_budget);budget.reserve('e'*64,1000)
        budget.settle('e'*64,100,{'input_tokens':100,'output_tokens':180},'d'*64)
        parent.finish('2026-11-06','completed')
        control=json.loads(self.store().read('control')[0])
        self.assertEqual(len(control['budget']['requests']),31)
        self.assertEqual(control['budget']['requests'][-1]['charged_microdollars'],100)
        self.assertEqual(control['days']['2026-11-06']['status'],'completed')

    def test_read_only_budget_summary_does_not_checkpoint(self):
        self.module();seen=[];budget=TrialBudget(self.budget_path,checkpoint=lambda state:seen.append(state))
        budget.summary();self.assertEqual(seen,[])
        budget.reserve('e'*64,1);self.assertEqual(len(seen),1)

    def test_policy_rejects_reset_different_model_and_extended_expiry(self):
        module=self.module()
        for change in ('reset','model','model_alias','expiry','days'):
            control=deepcopy(self.control)
            if change=='reset':control['budget']['requests']=[]
            elif change=='model':control['budget']['model']='more-expensive-model'
            elif change=='model_alias':control['budget']['model']='claude-haiku-5-5-premium'
            elif change=='expiry':control['expires_at']='2099-01-01T00:00:00+09:00'
            else:control['days']={}
            with self.assertRaises(ValueError):module.validate_control(self.root,control)

    def test_reserved_amount_cannot_be_reduced_and_second_request_cannot_pass_it(self):
        session=self.session();budget=TrialBudget(self.budget_path,checkpoint=session.checkpoint_budget)
        budget.reserve('e'*64,1000)
        changed=load(self.budget_path,{})
        changed['requests'][-1]['reserved_microdollars']=1
        with self.assertRaises(ValueError):session.checkpoint_budget(changed)
        with self.assertRaises(ValueError):budget.reserve('f'*64,1000)

    def test_runtime_pointer_reads_immutable_blob_after_unreferenced_upload(self):
        session=self.session();old=session.control['runtime_sha'];store=self.store()
        _,latest=store.read('runtime')
        store.write('runtime',b'new but not yet referenced runtime',latest)
        self.assertNotEqual(store.read('runtime')[0],store.read('runtime',old)[0])
        self.module().CloudSession.restore(self.root,store)

    def test_state_files_over_the_contents_inline_limit_are_read_by_blob_sha(self):
        # The day the runtime or control cipher first passes 1 MB, saving must still work.
        session=self.session();self.remote.inline_limit=16
        raw,sha=self.store().read('control')
        self.assertEqual(json.loads(raw)['trial_id'],self.control['trial_id'])
        self.assertTrue(any(r.full_url.endswith('/git/blobs/'+sha) for r in self.remote.requests))
        session.save_runtime()
        session.mark_day('2026-11-06')
        restored=self.module().CloudSession.restore(self.root,self.store())
        self.assertEqual(restored.control['days']['2026-11-06']['status'],'attempted')
        self.assertEqual(self.store().read('runtime')[1],restored.control['runtime_sha'])
        # Lease lookups ask for the object media type, which reports the sha of large files.
        self.assertTrue(any(r.get_header('Accept')=='application/vnd.github.object+json' for r in self.remote.requests))

    def test_bad_token_is_rejected_without_sending_headers(self):
        module=self.module()
        with self.assertRaises(ValueError):module.GitHubStateStore(self.root,'bad\rvalue',self.crypto,opener=self.remote)
        self.assertEqual(self.remote.requests,[])


if __name__=='__main__':unittest.main()


class CloseUnresolvedTests(unittest.TestCase):
    setUp=CloudStateTests.setUp;module=CloudStateTests.module;store=CloudStateTests.store

    def stuck(self):
        from datetime import datetime
        budget=self.control['budget']
        budget['requests'].append({'id':'e'*64,'status':'reserved','reserved_microdollars':11673,'charged_microdollars':0,
                                   'started_at':'2026-11-10T21:31:13+00:00'})
        self.control['days']['2026-11-11']={'status':'attempted'}
        from benefit_monitor.age_state import pack_runtime
        store=self.store();self.control['runtime_sha']=store.write('runtime',pack_runtime(self.root),None)
        store.write('control',json.dumps(self.control).encode(),None)
        return self.module().CloudSession.read_control(self.root,store),datetime.fromisoformat('2026-11-11T12:00:00+09:00')

    def test_close_keeps_the_reserved_dollars_and_gives_the_stuck_day_one_retry(self):
        session,now=self.stuck()
        before=TrialBudget._exposure(session.control['budget'])
        self.assertTrue(session.close_unresolved('2026-11-11',now))
        remote=json.loads(self.store().read('control')[0])
        row=remote['budget']['requests'][-1]
        self.assertEqual((row['status'],row['error_code'],row['reserved_microdollars']),('failed','manual_closed_unverified',11673))
        self.assertEqual(TrialBudget._exposure(remote['budget']),before)  # still counted as spent
        self.assertFalse(remote['budget']['halted'])
        self.assertEqual(remote['days']['2026-11-11']['retry_of']['status'],'attempted')
        self.assertEqual(len(remote['budget']['manual_reviews']),1)
        restored=self.module().CloudSession.restore(self.root,self.store())  # no longer blocked
        self.assertEqual(restored.control['days']['2026-11-11']['status'],'attempted')
        # A crash after the paid work leaves the day 'attempted': the same input reopens it, keeping history.
        self.assertTrue(restored.close_unresolved('2026-11-11',now))
        again=json.loads(self.store().read('control')[0])['days']['2026-11-11']['retry_of']
        self.assertEqual((again['reason'],again['previous']['reason']),('manual_reopened_stuck_day','manual_closed_unverified'))
        restored=self.module().CloudSession.restore(self.root,self.store())
        data=deepcopy(restored.control);data['days']['2026-11-11']['status']='completed';restored._commit(data)
        with self.assertRaises(ValueError):restored.close_unresolved('2026-11-11',now)  # finished day: nothing to close

    def test_one_transient_github_failure_is_retried(self):
        store=self.store();calls=[]
        original=self.remote
        def flaky(request):
            calls.append(1)
            if len(calls)==1:raise HTTPError(request.full_url,502,'bad gateway',{},io.BytesIO())
            return original(request)
        store.opener=flaky
        sha=store.write('control',b'ledger',None)
        self.assertEqual(store.read('control'),(b'ledger',sha))


class SafeReasonTests(unittest.TestCase):
    def test_reason_keeps_plain_text_and_drops_tokens(self):
        from benefit_monitor.cloud_state import safe_reason
        self.assertEqual(safe_reason(ValueError('GitHub state request failed: http_403')),'ValueError: GitHub state request failed: http_403')
        self.assertEqual(safe_reason(ValueError('x sk-ant-abc')),'ValueError: redacted')
        self.assertEqual(safe_reason(ValueError('{"a":"<b>"}')),'ValueError: a:b')
