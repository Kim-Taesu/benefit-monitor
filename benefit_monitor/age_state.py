"""Authenticated private-state encryption and allowlisted runtime archives."""
import gzip
import io
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile

from scripts.install_age import safe_path,verify_installation
from .trial_budget import secure_open

MAX_RUNTIME_BYTES=32*1024*1024
MAX_FILES=4096
CONTROL_FILES={'.tools/claude-trial/live/budget.json','cache/ai_daily/days.json'}
FOLDERS=('.tools/claude-trial/live/','.tools/ai-inputs/','.tools/ai-topic-inputs/',
         'cache/ai_review/','cache/ai_topics/','cache/ai_daily/')
FILES={'report.json','cache/operational_state.json','cache/verified_items.json',
       'cache/district_candidates.json','cache/collection_log.json'}


def _allowed(name):
    path=PurePosixPath(name)
    if path.is_absolute() or path.as_posix()!=name or '..' in path.parts or '\\' in name or name in CONTROL_FILES:return False
    if (path.name.startswith('.env') or path.name in ('token.json','identity.txt')
            or path.suffix in ('.pem','.key','.p12','.pfx')):return False
    return name in FILES or any(name.startswith(folder) for folder in FOLDERS)


def pack_runtime(root):
    root=Path(root).resolve();paths=set()
    for relative in FOLDERS:
        folder=safe_path(root,relative)
        if folder.exists():paths.update(folder.rglob('*'))
    paths.update(safe_path(root,name) for name in FILES)
    entries=[];total=0
    for path in sorted(paths):
        if path.is_symlink():raise ValueError('runtime archive cannot contain links')
        if not path.is_file():continue
        name=path.relative_to(root).as_posix()
        if name in CONTROL_FILES or path.name.startswith('.lock'):continue
        if not _allowed(name):raise ValueError('forbidden runtime path')
        total+=path.stat().st_size
        if total>MAX_RUNTIME_BYTES or len(entries)>=MAX_FILES:raise ValueError('runtime archive too large')
        entries.append((name,path))
    output=io.BytesIO()
    with tarfile.open(fileobj=output,mode='w') as archive:
        for name,path in entries:archive.add(path,arcname=name,recursive=False)
    return gzip.compress(output.getvalue())


def restore_runtime(root,raw):
    root=Path(root).resolve()
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:plain=stream.read(MAX_RUNTIME_BYTES+MAX_FILES*2048+1)
        if len(plain)>MAX_RUNTIME_BYTES+MAX_FILES*2048:raise ValueError('runtime archive expands beyond limit')
        entries={};total=0
        with tarfile.open(fileobj=io.BytesIO(plain),mode='r:') as archive:
            for item in archive:
                if (not item.isfile() or not _allowed(item.name) or item.name in entries
                        or len(entries)>=MAX_FILES):raise ValueError('unsafe runtime archive member')
                safe_path(root,item.name);total+=item.size
                if total>MAX_RUNTIME_BYTES:raise ValueError('runtime archive too large')
                entries[item.name]=archive.extractfile(item).read()
        # Validate the entire archive before restoring any file.
        for name,content in entries.items():
            path=safe_path(root,name);path.parent.mkdir(parents=True,exist_ok=True)
            with os.fdopen(secure_open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC),'wb') as stream:stream.write(content)
    except (OSError,EOFError,tarfile.TarError):raise ValueError('invalid runtime archive') from None


class AgeState:
    def __init__(self,root,identity):
        self.root=Path(root).resolve();self.identity=safe_path(self.root,identity)
        with os.fdopen(secure_open(self.identity,os.O_RDONLY)) as stream:raw=stream.read(4097)
        lines=[line for line in raw.splitlines() if line and not line.startswith('#')]
        if len(raw)>4096 or len(lines)!=1 or not re.fullmatch(r'AGE-SECRET-KEY-1[A-Z0-9]+',lines[0]):
            raise ValueError('invalid state identity')
        self.binary=verify_installation(self.root)
        if self.binary is None:raise ValueError('verified project-local age is required')
        keygen=self.binary.with_name('age-keygen')
        result=self._run([str(keygen),'-y',str(self.identity)])
        self.recipient=result.decode().strip()
        if not re.fullmatch(r'age1[a-z0-9]{20,200}',self.recipient):raise ValueError('invalid state recipient')

    @staticmethod
    def _run(args,raw=None):
        env={k:os.environ[k] for k in ('PATH','LANG','LC_ALL','TMPDIR') if k in os.environ}
        process=subprocess.run(args,input=raw,env=env,capture_output=True,timeout=60)
        if process.returncode:raise ValueError('private-state cryptographic operation failed')
        return process.stdout

    def encrypt(self,raw):
        if len(raw)>MAX_RUNTIME_BYTES:raise ValueError('private state too large')
        return self._run([str(self.binary),'--encrypt','--recipient',self.recipient],raw)

    def decrypt(self,cipher):
        if len(cipher)>MAX_RUNTIME_BYTES:raise ValueError('encrypted state too large')
        plain=self._run([str(self.binary),'--decrypt','--identity',str(self.identity)],cipher)
        if len(plain)>MAX_RUNTIME_BYTES:raise ValueError('decrypted state too large')
        return plain
