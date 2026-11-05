"""Install the pinned age release inside this checkout, never globally."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import stat
import tarfile
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener

VERSION='v1.3.2'
BASE='https://github.com/FiloSottile/age/releases/download/'+VERSION+'/'
ASSETS={
    ('Darwin','arm64'):(BASE+'age-v1.3.2-darwin-arm64.tar.gz','e2020b073c44f692685a24d6abc378817eb81ffaaf49fd0531ef8565f767f2f5'),
    ('Linux','x86_64'):(BASE+'age-v1.3.2-linux-amd64.tar.gz','cbe24006683f8eb669266162894b9a522a1af52f2665fbc63a4bb032ed26ac10'),
}
PACKAGE_ROOT=Path(__file__).resolve().parents[1]
DOWNLOAD_LIMIT=32*1024*1024
EXTRACT_LIMIT=128*1024*1024


def safe_path(root,relative):
    root=Path(root).resolve()
    if not root.is_relative_to(PACKAGE_ROOT):raise ValueError('tool path outside checkout')
    path=Path(relative)
    if not path.is_absolute():path=root/path
    try:parts=path.relative_to(root).parts
    except ValueError:raise ValueError('path outside runtime') from None
    if '..' in parts:raise ValueError('parent traversal is forbidden')
    cursor=root
    for part in parts:
        cursor=cursor/part
        if cursor.is_symlink():raise ValueError('symlink is forbidden')
    return path


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None


def fetch_release(url):
    opener=build_opener(NoRedirect)
    for _ in range(3):
        parsed=urlsplit(url)
        if parsed.scheme!='https' or parsed.hostname not in ('github.com','release-assets.githubusercontent.com','objects.githubusercontent.com'):
            raise ValueError('unapproved age release host')
        try:
            with opener.open(Request(url,headers={'User-Agent':'BenefitMonitor-age-install'}),timeout=40) as response:
                raw=response.read(DOWNLOAD_LIMIT+1)
            if len(raw)>DOWNLOAD_LIMIT:raise ValueError('age release too large')
            return raw
        except HTTPError as error:
            if error.code not in (301,302,303,307,308):
                error.close();raise ValueError('age release download failed') from None
            url=error.headers.get('Location','');error.close()
    raise ValueError('too many age release redirects')


def verify_installation(root):
    manifest=safe_path(root,'.tools/bin/age-pins.json')
    if not manifest.exists():return None
    try:
        data=json.loads(manifest.read_text());pin=ASSETS[(data['platform'],data['machine'])]
        if data['version']!=VERSION or data['archive_sha256']!=pin[1] or set(data['files'])!={'age','age-keygen'}:return None
        for name,digest in data['files'].items():
            path=safe_path(root,'.tools/bin/'+name);info=path.stat()
            if (not stat.S_ISREG(info.st_mode) or info.st_uid!=os.getuid() or info.st_mode&0o022
                    or not info.st_mode&stat.S_IXUSR or hashlib.sha256(path.read_bytes()).hexdigest()!=digest):return None
        return safe_path(root,'.tools/bin/age')
    except (KeyError,TypeError,OSError,ValueError):return None


def install(root,platform_name=None,machine=None):
    root=Path(root).resolve();system=platform_name or platform.system();arch=machine or platform.machine()
    if (system,arch) not in ASSETS:raise ValueError('unsupported age platform')
    folder=safe_path(root,'.tools/bin')
    ready=verify_installation(root)
    if ready is not None:return ready
    url,digest=ASSETS[(system,arch)];raw=fetch_release(url)
    if len(raw)>DOWNLOAD_LIMIT or hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('age release checksum mismatch')
    binaries={};total=0
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:gz') as archive:
        for item in archive:
            path=PurePosixPath(item.name)
            if path.is_absolute() or '..' in path.parts or '\\' in item.name or item.issym() or item.islnk():
                raise ValueError('unsafe age archive member')
            if item.isdir():continue
            if not item.isfile():raise ValueError('nonregular age archive member')
            total+=item.size
            if total>EXTRACT_LIMIT:raise ValueError('age archive expands beyond limit')
            if item.name in ('age/age','age/age-keygen'):
                name=path.name
                if name in binaries:raise ValueError('duplicate age binary')
                binaries[name]=archive.extractfile(item).read()
    if set(binaries)!={'age','age-keygen'}:raise ValueError('age archive lacks expected binaries')
    folder.mkdir(parents=True,exist_ok=True)
    for name,content in binaries.items():
        target=safe_path(root,'.tools/bin/'+name)
        fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o755)
        with os.fdopen(fd,'wb') as stream:stream.write(content);stream.flush();os.fsync(stream.fileno())
        target.chmod(0o755)
    data={'version':VERSION,'platform':system,'machine':arch,'archive_sha256':digest,
          'files':{name:hashlib.sha256(content).hexdigest() for name,content in binaries.items()}}
    target=safe_path(root,'.tools/bin/age-pins.json')
    fd=os.open(target,os.O_WRONLY|os.O_CREAT|os.O_TRUNC|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(data,stream)
    if verify_installation(root) is None:raise ValueError('age installation verification failed')
    return folder/'age'


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,default=PACKAGE_ROOT)
    args=parser.parse_args();install(args.root);print('Verified project-local age '+VERSION)
