"""Private regression corpus for the auto-publish gate (approved 2026-11-24).

Every research run of the daily AI run leaves its input (candidate and official page bodies) and its
normalized draft in the encrypted runtime for five days only. This keeps them longer in a separate
encrypted file on briefing-data (`ai-corpus.age`), each with the decision the gate made at the time, so
that every day the current code can decide all of them again and say how many decisions it changed.

- Page bodies are stored once per body hash; a run keeps the hash only.
- The packed corpus stays under PACKED_LIMIT: the oldest records go first, then unreferenced bodies.
- Replay uses each record's own input time and no takedowns, so only code changes move a decision.
- Nothing here is public: the summary has counts and reason codes only, never titles, URLs or text.
"""
from copy import deepcopy
from collections import Counter
from datetime import datetime
import gzip
import json
from pathlib import Path
import re

from . import auto_publish, tuning

SCHEMA_VERSION = 1
# The encrypted file cap is 8 MiB (cloud_state.MAX_CIPHER); age adds little, so keep a margin.
PACKED_LIMIT = int(tuning.value('corpus.packed_limit_mib') * 1024 * 1024)  # config/tuning.json
RUN_ID = re.compile(r'[0-9a-f]{64}')


def empty():
    return dict(schema_version=SCHEMA_VERSION, records={}, bodies={})


def pack(corpus):
    raw = json.dumps(corpus, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()
    return gzip.compress(raw, compresslevel=9, mtime=0)


def unpack(raw):
    corpus = json.loads(gzip.decompress(raw))
    if not isinstance(corpus, dict) or corpus.get('schema_version') != SCHEMA_VERSION \
            or not isinstance(corpus.get('records'), dict) or not isinstance(corpus.get('bodies'), dict):
        raise ValueError('invalid gate corpus')
    return corpus


def _decide(draft, host):
    decision = auto_publish.decide(draft, host, datetime.fromisoformat(host['now']), [])
    return dict(publish=bool(decision['publish']), reasons=sorted(decision['reasons']))


def _strip(host):
    """Host input with each document body replaced by its hash, and the bodies by hash."""
    light, bodies = deepcopy(host), {}
    for doc in light.get('documents', []):
        body = doc.pop('body', None)
        if isinstance(body, str):
            bodies[doc['body_hash']] = body
    return light, bodies


def _restore(light, bodies):
    host = deepcopy(light)
    for doc in host.get('documents', []):
        doc['body'] = bodies[doc['body_hash']]
    return host


def capture(corpus, runs, now, code_sha):
    """Add research runs not seen before; returns how many were added. Unreadable runs are skipped."""
    added = 0
    folder = Path(runs)
    if not folder.is_dir():
        return 0
    for run in sorted(folder.iterdir()):
        if not RUN_ID.fullmatch(run.name) or run.name in corpus['records'] or not run.is_dir():
            continue
        try:
            meta = json.loads((run / 'metadata.json').read_text())
            if meta.get('kind') != 'research' or not (run / 'normalized-output.json').exists():
                continue
            draft = json.loads((run / 'normalized-output.json').read_text())
            host = json.loads((run / 'input.json').read_text())
            if draft.get('schema_version') != 'research-extraction-v3':
                continue
            decision = _decide(draft, host)
            light, bodies = _strip(host)
        except (OSError, ValueError, KeyError, TypeError, IndexError):
            continue
        corpus['bodies'].update(bodies)
        corpus['records'][run.name] = dict(recorded_at=now.isoformat(), code_sha=code_sha, draft=draft,
                                           host=light, decision=decision)
        added += 1
    return added


def trim(corpus, limit=PACKED_LIMIT):
    """Drop the oldest records until the packed corpus fits; returns how many were dropped."""
    dropped = 0
    while True:
        used = {doc['body_hash'] for r in corpus['records'].values() for doc in r['host'].get('documents', [])}
        for key in set(corpus['bodies']) - used:
            del corpus['bodies'][key]
        if len(pack(corpus)) <= limit or not corpus['records']:
            return dropped
        order = sorted(corpus['records'], key=lambda k: (corpus['records'][k]['recorded_at'], k))
        for key in order[:max(1, len(order) // 10)]:
            del corpus['records'][key]
            dropped += 1


def replay(corpus):
    """Decide every record again with the current code; counts and reason codes only."""
    moved = Counter()
    reasons_added, reasons_removed = Counter(), Counter()
    failed = 0
    for record in corpus['records'].values():
        try:
            now = _decide(record['draft'], _restore(record['host'], corpus['bodies']))
        except Exception:
            failed += 1
            continue
        before = record['decision']
        if now == before:
            moved['unchanged'] += 1
            continue
        moved[('publish' if before['publish'] else 'held') + '_to_' + ('publish' if now['publish'] else 'held')] += 1
        reasons_added.update(set(now['reasons']) - set(before['reasons']))
        reasons_removed.update(set(before['reasons']) - set(now['reasons']))
    total = len(corpus['records'])
    published = sum(r['decision']['publish'] for r in corpus['records'].values())
    days = sorted(r['recorded_at'][:10] for r in corpus['records'].values())
    return dict(records=total, recorded_published=published, oldest=days[0] if days else None,
                newest=days[-1] if days else None, unchanged=moved['unchanged'],
                publish_to_held=moved['publish_to_held'], held_to_publish=moved['held_to_publish'],
                reasons_changed=moved['publish_to_publish'] + moved['held_to_held'], replay_failed=failed,
                reasons_added=dict(reasons_added), reasons_removed=dict(reasons_removed))


def daily(store, runs, now, code_sha):
    """Read, extend, trim, save and replay the corpus. A read failure other than "not created yet" stops
    here without writing, so an existing corpus is never replaced by an empty one."""
    try:
        raw, sha = store.read('corpus')
        corpus = unpack(raw)
    except ValueError as error:
        if 'http_404' not in str(error):
            return dict(status='read_failed')
        corpus, sha = empty(), None
    added = capture(corpus, runs, now, code_sha)
    dropped = trim(corpus)
    if added or dropped:
        store.write('corpus', pack(corpus), sha)
    return dict(status='ok', added=added, dropped=dropped, **replay(corpus))
