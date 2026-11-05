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
    def __init__(self):self.files={};self.blobs={};self.requests=[];self.fail_writes=False
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
            return io.BytesIO(json.dumps({'encoding':'base64','content':base64.b64encode(raw).decode(),'sha':blob_sha(raw)}).encode())
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

    def test_bad_token_is_rejected_without_sending_headers(self):
        module=self.module()
        with self.assertRaises(ValueError):module.GitHubStateStore(self.root,'bad\rvalue',self.crypto,opener=self.remote)
        self.assertEqual(self.remote.requests,[])


if __name__=='__main__':unittest.main()
