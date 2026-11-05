import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

class RemoteDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'.tools');self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.policy={'public_application_approved':True,'remote_delivery_approved':True,
                     'repository':'Kim-Taesu/benefit-monitor','deploy_ref':'docs/ai-research-playbook'}
        from test_pipeline import benefit,SOURCE,NOW
        from benefit_monitor.store import save
        from benefit_monitor.publish import run
        self.now=NOW
        item=benefit().data()
        save(self.root/'sources.yaml',{'sources':[SOURCE]})
        save(self.root/'public/verified.json',[dict(item,public_release=True)])
        save(self.root/'report.json',{'verified_at':NOW.isoformat(),'new':[item],'needs_recheck':[],'collection':{'online':True,'successful_sources':['test']}})
        run(self.root,now=NOW)
        self.events=[]

    def process(self,args,**kwargs):
        self.events.append((args,kwargs))
        if args[:3]==['git','status','--porcelain']:out=''
        elif args[:3]==['git','rev-parse','HEAD']:out='1'*40
        elif args[:3]==['gh','auth','token']:
            self.assertIsNotNone(kwargs.get('env'))
            self.assertFalse('GH_TOKEN' in kwargs['env'],'credential environment was forwarded')
            self.assertFalse('GITHUB_TOKEN' in kwargs['env'],'credential environment was forwarded')
            self.assertFalse('ANTHROPIC_API_KEY' in kwargs['env'],'credential environment was forwarded')
            self.assertFalse('OPENAI_API_KEY' in kwargs['env'],'credential environment was forwarded')
            out='test-personal-token'
        elif 'user' in args:out='Kim-Taesu'
        elif args[:2]==['gh','api']:
            if args[-1]=='repos/Kim-Taesu/benefit-monitor':out=json.dumps({'private':False})
            else:out='{}'
        elif args[:3]==['gh','workflow','run']:out=''
        else:raise AssertionError(args)
        return subprocess.CompletedProcess(args,0,out,'')

    def test_no_remote_approval_or_wrong_repository_never_reads_credentials(self):
        from benefit_monitor.remote_delivery import deliver
        with patch('benefit_monitor.remote_delivery.subprocess.run',side_effect=AssertionError('no process')):
            policy=dict(self.policy,remote_delivery_approved=False)
            with self.assertRaises(ValueError):deliver(self.root,policy)
            policy=dict(self.policy,repository='company/private')
            with self.assertRaises(ValueError):deliver(self.root,policy)

    def test_personal_identity_and_public_repository_before_mirror_then_pinned_dispatch(self):
        from benefit_monitor.remote_delivery import deliver
        def mirror(root,repo,env=None,content=None):
            self.assertEqual(repo,'Kim-Taesu/benefit-monitor')
            self.assertTrue(env.get('GH_TOKEN')=='test-personal-token','unexpected credential selected')
            self.assertFalse('ANTHROPIC_API_KEY' in env,'private environment was forwarded')
            self.assertNotIn('profile',json.loads(content))
            self.events.append(('mirror',{}));return '2'*40
        with patch('benefit_monitor.remote_delivery.subprocess.run',side_effect=self.process),patch('benefit_monitor.remote_delivery.mirror',side_effect=mirror),patch.dict('os.environ',{'PATH':'/usr/bin:/bin','HOME':str(self.root),'ANTHROPIC_API_KEY':'must-not-be-forwarded','OPENAI_API_KEY':'also-private','GH_TOKEN':'wrong-ambient-token'},clear=True):
            result=deliver(self.root,self.policy,now=self.now)
        self.assertEqual(result['snapshot_commit'],'2'*40)
        self.assertEqual(result['code_sha'],'1'*40)
        dispatch=next(args for args,kw in self.events if isinstance(args,list) and args[:3]==['gh','workflow','run'])
        self.assertIn('snapshot_commit='+'2'*40,dispatch)
        self.assertIn('expected_code_sha='+'1'*40,dispatch)
        self.assertLess(next(i for i,e in enumerate(self.events) if e[0]=='mirror'),next(i for i,e in enumerate(self.events) if isinstance(e[0],list) and e[0][:3]==['gh','workflow','run']))
        self.assertNotIn('test-personal-token',json.dumps(result))

    def test_dirty_checkout_stops_before_credentials_and_remote_write(self):
        from benefit_monitor.remote_delivery import deliver
        def dirty(args,**kwargs):
            if args[:3]==['git','status','--porcelain']:return subprocess.CompletedProcess(args,0,' M code.py','')
            raise AssertionError('must stop before auth')
        with patch('benefit_monitor.remote_delivery.subprocess.run',side_effect=dirty):
            with self.assertRaisesRegex(ValueError,'clean'):deliver(self.root,self.policy,now=self.now)

    def test_wrong_account_or_private_repository_stops_before_upload(self):
        from benefit_monitor.remote_delivery import deliver
        for wrong_account in (True,False):
            def process(args,**kwargs):
                if wrong_account and 'user' in args:
                    return subprocess.CompletedProcess(args,0,'another-account','')
                if not wrong_account and args[-1]=='repos/Kim-Taesu/benefit-monitor':
                    return subprocess.CompletedProcess(args,0,json.dumps({'private':True}),'')
                return self.process(args,**kwargs)
            with patch('benefit_monitor.remote_delivery.subprocess.run',side_effect=process),patch('benefit_monitor.remote_delivery.mirror',side_effect=AssertionError('must not upload')),patch.dict('os.environ',{'PATH':'/usr/bin:/bin'},clear=True):
                with self.assertRaises(ValueError):deliver(self.root,self.policy,now=self.now)

if __name__=='__main__':unittest.main()
