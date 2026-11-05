import gzip
import hashlib
import importlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


def archive(entries):
    out=io.BytesIO()
    with tarfile.open(fileobj=out,mode='w') as tar:
        for name,data,kind in entries:
            row=tarfile.TarInfo(name);row.type=kind
            if kind==tarfile.SYMTYPE:row.linkname='../../outside'
            else:row.size=len(data)
            tar.addfile(row,io.BytesIO(data) if kind==tarfile.REGTYPE else None)
    return out.getvalue()


class AgeStateTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)

    def module(self,name):
        try:return importlib.import_module(name)
        except ModuleNotFoundError:self.fail('암호화 상태 기능이 아직 구현되지 않음')

    def test_installer_rejects_unsupported_platform_without_download(self):
        module=self.module('scripts.install_age')
        with patch.object(module,'fetch_release',side_effect=AssertionError('must not download')):
            with self.assertRaises(ValueError):module.install(self.root,'Windows','amd64')

    def test_wrong_download_digest_never_installs_an_executable(self):
        module=self.module('scripts.install_age')
        with patch.object(module,'fetch_release',return_value=b'corrupt archive'):
            with self.assertRaises(ValueError):module.install(self.root,'Darwin','arm64')
        self.assertFalse((self.root/'.tools/bin/age').exists())

    def test_verified_archive_still_rejects_traversal_and_links(self):
        module=self.module('scripts.install_age')
        for name,kind in [('../outside',tarfile.REGTYPE),('age/age',tarfile.SYMTYPE)]:
            raw=gzip.compress(archive([(name,b'bad',kind)]))
            pin=('https://github.com/FiloSottile/age/releases/download/v1.3.2/age-v1.3.2-darwin-arm64.tar.gz',hashlib.sha256(raw).hexdigest())
            with patch.object(module,'ASSETS',{('Darwin','arm64'):pin}),patch.object(module,'fetch_release',return_value=raw):
                with self.assertRaises(ValueError):module.install(self.root,'Darwin','arm64')
        self.assertFalse((self.root/'.tools/bin/age').exists())

    def test_runtime_preserves_review_but_excludes_control_and_credentials(self):
        module=self.module('benefit_monitor.age_state')
        for name,value in [('cache/ai_review/queue/a.json','{"pending":true}'),('.tools/claude-trial/live/budget.json','{"requests":[]}'),('cache/ai_daily/days.json','{}'),('.env.claude','fake-private-input')]:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value)
        raw=module.pack_runtime(self.root)
        with tarfile.open(fileobj=io.BytesIO(gzip.decompress(raw))) as tar:names=tar.getnames()
        self.assertIn('cache/ai_review/queue/a.json',names)
        self.assertNotIn('.tools/claude-trial/live/budget.json',names)
        self.assertNotIn('cache/ai_daily/days.json',names)
        self.assertNotIn('.env.claude',names)
        target=self.root/'restore';target.mkdir();module.restore_runtime(target,raw)
        self.assertEqual((target/'cache/ai_review/queue/a.json').read_text(),'{"pending":true}')
        self.assertEqual((target/'cache/ai_review/queue/a.json').stat().st_mode&0o777,0o600)
        (self.root/'cache/ai_review/token.json').write_text('must not archive')
        with self.assertRaises(ValueError):module.pack_runtime(self.root)

    def test_restore_rejects_control_path_escape_and_links_before_writing(self):
        module=self.module('benefit_monitor.age_state')
        for name,kind in [('../outside',tarfile.REGTYPE),('.tools/claude-trial/live/budget.json',tarfile.REGTYPE),('.tools/claude-trial/live//budget.json',tarfile.REGTYPE),('cache/ai_daily/./days.json',tarfile.REGTYPE),('cache/ai_daily/days.json',tarfile.REGTYPE),('cache/ai_review/a.json',tarfile.SYMTYPE)]:
            raw=gzip.compress(archive([(name,b'bad',kind)]))
            with self.assertRaises(ValueError):module.restore_runtime(self.root,raw)
        self.assertFalse((self.root/'cache/ai_review/a.json').exists())

    def test_runtime_link_and_size_limits_are_enforced(self):
        module=self.module('benefit_monitor.age_state')
        folder=self.root/'cache/ai_review';folder.mkdir(parents=True)
        outside=self.root/'other.json';outside.write_text('private')
        link=folder/'a.json';link.symlink_to(outside)
        with self.assertRaises(ValueError):module.pack_runtime(self.root)
        link.unlink();link.write_text('too large')
        with patch.object(module,'MAX_RUNTIME_BYTES',4):
            with self.assertRaises(ValueError):module.pack_runtime(self.root)

    def test_real_age_roundtrip_tamper_and_wrong_identity(self):
        module=self.module('benefit_monitor.age_state')
        binary=ROOT/'.tools/bin/age-keygen'
        if not binary.exists():self.skipTest('실제 age 설치 후 검증')
        env={k:os.environ[k] for k in ('PATH','TMPDIR','LANG') if k in os.environ}
        identities=[]
        for name in ('first','second'):
            path=self.root/(name+'.txt')
            result=subprocess.run([str(binary),'-o',str(path)],env=env,capture_output=True)
            self.assertEqual(result.returncode,0,'identity 생성 실패')
            path.chmod(0o600);identities.append(path)
        first=module.AgeState(ROOT,identities[0]);second=module.AgeState(ROOT,identities[1])
        raw=b'private review and persistent budget'
        cipher=first.encrypt(raw);self.assertNotIn(raw,cipher)
        self.assertEqual(first.decrypt(cipher),raw)
        changed=bytearray(cipher);changed[-1]^=1
        with self.assertRaises(ValueError):first.decrypt(bytes(changed))
        with self.assertRaises(ValueError):second.decrypt(cipher)
        identities[0].chmod(0o644)
        with self.assertRaises(ValueError):module.AgeState(ROOT,identities[0])


if __name__=='__main__':unittest.main()
