"""Claude response cache kept in half-month encrypted files on briefing-data (approved 2026-11-27).

The ledger points at every completed response (`responses/<request id>.json`): a repeated request reads
the cached answer instead of being charged again, and a missing file stops it. Those files were packed
into `ai-runtime.age` and never pruned, so the runtime reached 98% of its 8 MiB file cap (2026-11-27).

They now live in `ai-responses-YYYY-MMa.age` (days 1-15, Seoul) and `...b.age` (16-end), placed by the
ledger row's `started_at`. Nothing is deleted: restore reads every shard the ledger names and writes the
files back; save rewrites only shards that gained files and refuses to drop a file a shard already holds.
The runtime archive no longer packs this folder (age_state.EXCLUDED).
"""
from datetime import datetime
import gzip
import io
import json
from pathlib import Path
import re
import tarfile
from zoneinfo import ZoneInfo

from scripts.install_age import safe_path
from .store import save, load

RESPONSES = '.tools/claude-trial/live/responses'
CONTEXT = '.tools/cloud-state/responses.json'
SEOUL = ZoneInfo('Asia/Seoul')
NAME = re.compile('([0-9a-f]{64})[.](json|sent)')
SHARD = re.compile(r'20\d\d-(0[1-9]|1[0-2])[ab]')
MAX_BYTES = 64 * 1024 * 1024
MAX_FILES = 16384


def shard_of(moment):
    local = moment.astimezone(SEOUL)
    return f'{local.year}-{local.month:02d}{"a" if local.day <= 15 else "b"}'


def kind(shard):
    if not SHARD.fullmatch(shard):
        raise ValueError('invalid response shard')
    return 'responses-' + shard


def ledger_shards(budget):
    """Request id -> shard for every ledger row with a timezone-aware start time."""
    out = {}
    for row in (budget or {}).get('requests', []):
        try:
            moment = datetime.fromisoformat(row['started_at'])
        except (KeyError, TypeError, ValueError):
            continue
        if moment.tzinfo is not None and isinstance(row.get('id'), str):
            out[row['id']] = shard_of(moment)
    return out


def pack(files):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w') as archive:
        for name in sorted(files):
            info = tarfile.TarInfo(name)
            info.size, info.mtime, info.mode = len(files[name]), 0, 0o600
            archive.addfile(info, io.BytesIO(files[name]))
    return gzip.compress(output.getvalue(), mtime=0)


def unpack(raw):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        plain = stream.read(MAX_BYTES + MAX_FILES * 2048 + 1)
    if len(plain) > MAX_BYTES + MAX_FILES * 2048:
        raise ValueError('response archive expands beyond limit')
    files, total = {}, 0
    with tarfile.open(fileobj=io.BytesIO(plain), mode='r:') as archive:
        for item in archive:
            if not item.isfile() or not NAME.fullmatch(item.name) or item.name in files or len(files) >= MAX_FILES:
                raise ValueError('unsafe response archive member')
            total += item.size
            if total > MAX_BYTES:
                raise ValueError('response archive too large')
            files[item.name] = archive.extractfile(item).read()
    return files


def _read(store, shard):
    """(files, sha); a shard that was never written is empty."""
    try:
        raw, sha = store.read(kind(shard))
    except ValueError as error:
        if 'http_404' in str(error):
            return {}, None
        raise
    return unpack(raw), sha


def _local(root):
    folder = safe_path(root, RESPONSES)
    out = {}
    for path in sorted(folder.iterdir()) if folder.is_dir() else ():
        if path.is_symlink():
            raise ValueError('response cache cannot contain links')
        if path.is_file() and NAME.fullmatch(path.name):
            out[path.name] = path
    return out


def _write_local(root, name, raw):
    path = safe_path(root, RESPONSES + '/' + name)
    if path.is_symlink():
        raise ValueError('response cache cannot contain links')
    if path.exists():
        if path.read_bytes() != raw:
            raise ValueError('restored response differs from local copy')
        return
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.write_bytes(raw)
    path.chmod(0o600)


def _save_state(root, state):
    save(safe_path(root, CONTEXT), {'shards': {s: {'sha': v['sha'], 'names': sorted(v['names'])}
                                               for s, v in sorted(state.items())}})


def _load_state(root):
    data = load(safe_path(root, CONTEXT), {})
    out = {}
    for shard, row in (data.get('shards') or {}).items():
        if SHARD.fullmatch(shard) and isinstance(row, dict) and isinstance(row.get('names'), list):
            out[shard] = {'sha': row.get('sha'), 'names': set(row['names'])}
    return out


def restore(root, store, budget):
    """Write back every response of every shard the ledger names; returns {shard: file count}."""
    state = {}
    for shard in sorted(set(ledger_shards(budget).values())):
        files, sha = _read(store, shard)
        for name, raw in files.items():
            _write_local(root, name, raw)
        state[shard] = {'sha': sha, 'names': set(files)}
    _save_state(root, state)
    return {s: len(v['names']) for s, v in state.items()}


def save_all(root, store, budget, now):
    """Upload shards that gained files; returns {shard: file count} for the shards written."""
    ids = ledger_shards(budget)
    state = _load_state(root)
    known = {name: shard for shard, row in state.items() for name in row['names']}
    groups = {}
    for name, path in _local(root).items():
        shard = known.get(name) or ids.get(name[:64]) or shard_of(now)
        groups.setdefault(shard, {})[name] = path
    written = {}
    for shard in sorted(groups):
        if shard not in state:  # not read at restore (a new half-month): never overwrite unseen content
            files, sha = _read(store, shard)
            for name, raw in files.items():
                _write_local(root, name, raw)
                groups[shard].setdefault(name, safe_path(root, RESPONSES + '/' + name))
            state[shard] = {'sha': sha, 'names': set(files)}
        row = state[shard]
        if not row['names'] <= set(groups[shard]):
            raise ValueError('response shard would lose files')
        if set(groups[shard]) == row['names']:
            continue
        files = {name: path.read_bytes() for name, path in groups[shard].items()}
        row['sha'] = store.write(kind(shard), pack(files), row['sha'])
        row['names'] = set(files)
        written[shard] = len(files)
        _save_state(root, state)
    for shard, row in state.items():  # shards with no local file at all must still be complete on disk
        if shard not in groups and row['names']:
            raise ValueError('response shard would lose files')
    return written
