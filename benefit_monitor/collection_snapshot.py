"""Today's free collection, reused by the AI run so its HTTP budget goes to official bodies.

The free briefing run records what it collected (official public listing candidates, district
coverage, successful and failed sources) and uploads it encrypted to the approved AI recipient as
briefing-data/ai-collection.age. The plain snapshot is never published. The AI run uses it only
when it was collected today (KST); otherwise it collects again as before.
"""
import argparse
from datetime import datetime
import gzip
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .store import load, save

SNAPSHOT = 'cache/collection_snapshot.json'
FESTIVALS = 'cache/festivals.json'
GROCERIES = 'cache/groceries.json'
RECIPIENT = 'public/ai-recipient.txt'
SEOUL = ZoneInfo('Asia/Seoul')
LISTS = ('incoming', 'district_coverage', 'successful_sources', 'failures', 'handoffs')


def capture(root, now, incoming, district_coverage, successful_sources, failures, handoffs):
    root = Path(root)
    festivals = load(root/FESTIVALS, None) if 'kfes' in successful_sources else None
    groceries = load(root/GROCERIES, None) if 'groceries' in successful_sources else None
    save(root/SNAPSHOT, dict(schema_version=1, collected_at=now.isoformat(), incoming=incoming,
                             district_coverage=district_coverage, successful_sources=successful_sources,
                             failures=failures, handoffs=handoffs, festivals=festivals, groceries=groceries))


def parse_today(raw, now):
    """The snapshot dict when it is well formed and collected earlier today (KST), else None."""
    try:
        data = json.loads(raw)
        collected = datetime.fromisoformat(data['collected_at'])
        if data.get('schema_version') != 1 or collected.tzinfo is None:
            return None
        if any(not isinstance(data.get(k), list) for k in LISTS):
            return None
        if not all(isinstance(c, dict) and isinstance(c.get('source'), str) and isinstance(c.get('url'), str)
                   for c in data['incoming']):
            return None
    except (ValueError, TypeError, KeyError):
        return None
    now = now.astimezone(SEOUL)
    if collected.astimezone(SEOUL).date() != now.date() or collected > now:
        return None
    return data


def unpack(root, data):
    """(incoming, district_coverage, successful_sources, failures, handoffs); restores festivals and groceries."""
    if data.get('festivals') is not None:
        save(Path(root)/FESTIVALS, data['festivals'])
    if data.get('groceries') is not None:
        save(Path(root)/GROCERIES, data['groceries'])
    return tuple(list(data[k]) for k in LISTS)


def recipient(root):
    value = (Path(root)/RECIPIENT).read_text().strip()
    if not re.fullmatch(r'age1[a-z0-9]{20,200}', value):
        raise ValueError('invalid public AI recipient')
    return value


class RecipientCrypto:
    """Encrypt-only age wrapper for the free run, which never holds the identity."""

    def __init__(self, root):
        from scripts.install_age import verify_installation
        from .age_state import AgeState
        self.recipient = recipient(root)
        self.binary = verify_installation(Path(root).resolve())
        if self.binary is None:
            raise ValueError('verified project-local age is required')
        self._run = AgeState._run

    def encrypt(self, raw):
        return self._run([str(self.binary), '--encrypt', '--recipient', self.recipient], raw)

    def decrypt(self, cipher):
        raise ValueError('the free run cannot decrypt')


def upload(root, token, now=None):
    """Encrypt today's snapshot to briefing-data/ai-collection.age; returns the blob sha."""
    from .cloud_state import GitHubStateStore
    root = Path(root).resolve()
    now = now or datetime.now(SEOUL)
    raw = (root/SNAPSHOT).read_bytes()
    if parse_today(raw, now) is None:
        raise ValueError('no well-formed snapshot from today')
    store = GitHubStateStore(root, token, RecipientCrypto(root))
    try:
        lease, _ = store.lease('collection')
    except ValueError as error:
        if 'http_404' not in str(error):
            raise
        lease = None
    return store.write('collection', gzip.compress(raw, mtime=0), lease)


def restore(store, now):
    """Today's snapshot from briefing-data, or None when missing, stale or unreadable."""
    try:
        raw, _ = store.read('collection')
        return parse_today(gzip.decompress(raw), now)
    except (ValueError, OSError, EOFError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--upload', action='store_true', required=True)
    parser.add_argument('--root', type=Path, default=Path.cwd())
    args = parser.parse_args()
    print(json.dumps({'collection_snapshot': upload(args.root, os.environ.get('GH_TOKEN', ''))}))


if __name__ == '__main__':
    main()
