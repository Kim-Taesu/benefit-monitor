"""Bounded private runtime: prune old AI artifacts that no current record needs.

Only three growing folders are touched: run artifacts, staged AI inputs and cached official
bodies. An entry is removed only when nothing current references it (the per-candidate review
state, the decisions behind auto-published records, the official-body cache index) and its own
recorded timestamp is older than 14 days (3 days for verification runs). A missing or unreadable timestamp or reference file keeps
everything. The ledger (budget.json), its response cache and the review queue are never touched.
"""
from datetime import datetime, timedelta
import json
from pathlib import Path
import re
import shutil

KEEP_DAYS = 14
# Daily verification runs (up to 40) only feed that day's decision; their state lives in cache/ai_verify.
KEEP_VERIFY_DAYS = 3
RUNS = '.tools/claude-trial/live/runs'
INPUTS = '.tools/ai-inputs'
DOCUMENTS = 'cache/ai_review/documents'
HEX = re.compile('[0-9a-f]{64}')
DOCUMENT_NAME = re.compile('[0-9a-f]{64}-[0-9a-f]{64}[.]json')


def _json(path):
    """(value, ok): a missing file is ({}, True); unreadable JSON is (None, False)."""
    try:
        return json.loads(Path(path).read_text()), True
    except FileNotFoundError:
        return {}, True
    except (OSError, ValueError):
        return None, False


def _moment(path, key):
    value, _ = _json(path)
    try:
        moment = datetime.fromisoformat(value[key])
        return moment if moment.tzinfo is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def references(root):
    """(run ids, input files, document files) still referenced, or None when that cannot be told."""
    root = Path(root)
    state, state_ok = _json(root / 'cache/ai_review/state.json')
    approved, approved_ok = _json(root / 'cache/ai_publish/approved.json')
    decisions, decisions_ok = _json(root / 'cache/ai_publish/decisions.json')
    http, http_ok = _json(root / 'cache/ai_review/http.json')
    if not (state_ok and approved_ok and decisions_ok and http_ok):
        return None
    items = state.get('items', {}) if isinstance(state, dict) else None
    pages = http.get('pages', {}) if isinstance(http, dict) else None
    if not all(isinstance(v, dict) for v in (items, approved, decisions, pages)):
        return None
    runs, inputs, documents = set(), set(), set()
    for row in items.values():
        if isinstance(row, dict):
            runs.add(row.get('run_id'))
            inputs.add(row.get('input_file'))
            if isinstance(row.get('signature'), str):
                inputs.add(INPUTS + '/' + row['signature'] + '.json')
    for cid in approved:
        row = decisions.get(cid)
        if isinstance(row, dict):
            runs.add(row.get('run_id'))
            if isinstance(row.get('signature'), str):
                inputs.add(INPUTS + '/' + row['signature'] + '.json')
    for row in pages.values():
        if isinstance(row, dict):
            documents.add(row.get('file'))
    return runs, inputs, documents


def prune(root, now):
    """Remove unreferenced entries older than 14 days; returns the counts removed (or skipped)."""
    if now.tzinfo is None:
        raise ValueError('timezone required')
    root = Path(root)
    refs = references(root)
    if refs is None:
        return {'status': 'skipped_unreadable_references'}
    runs, inputs, documents = refs
    cutoff = now - timedelta(days=KEEP_DAYS)
    removed = {'runs': 0, 'inputs': 0, 'documents': 0}

    def old(path, key):
        moment = _moment(path, key)
        return moment is not None and moment < cutoff

    verify_cutoff = now - timedelta(days=KEEP_VERIFY_DAYS)
    folder = root / RUNS
    for path in sorted(folder.iterdir()) if folder.is_dir() else ():
        if path.is_symlink() or not path.is_dir() or not HEX.fullmatch(path.name) or path.name in runs:
            continue
        kind, _ = _json(path / 'metadata.json')
        moment = _moment(path / 'input.json', 'now')
        limit = verify_cutoff if isinstance(kind, dict) and kind.get('kind') == 'verify' else cutoff
        if moment is None or moment >= limit:
            continue
        shutil.rmtree(path)
        removed['runs'] += 1
    for relative, pattern, key, keep, count in ((INPUTS, HEX, 'now', inputs, 'inputs'),
                                                (DOCUMENTS, DOCUMENT_NAME, 'retrieved_at', documents, 'documents')):
        folder = root / relative
        for path in sorted(folder.iterdir()) if folder.is_dir() else ():
            name = path.name if pattern is DOCUMENT_NAME else path.name.removesuffix('.json')
            if (path.is_symlink() or not path.is_file() or not path.name.endswith('.json') or not pattern.fullmatch(name)
                    or relative + '/' + path.name in keep or not old(path, key)):
                continue
            path.unlink()
            removed[count] += 1
    return dict(removed, status='pruned')
