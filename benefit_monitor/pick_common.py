"""What the festival, benefit and 청약 picks share (2026-11-18): the admin mute, keeping yesterday's AI pick for a
while, the stored-pick header check and the at-most-one-paid-call-a-day draft step.

Each pick module keeps its own candidates, review() and public() policy; only the plumbing lives here. The model
call and the trial run folder are passed in by the caller, so tests that patch `<module>.invoke` and
`<module>.TRIAL_RUNS` keep working."""
from datetime import datetime, timedelta
import hashlib
import json

from .official_reader import project_path
from .store import load, save, save_text

PICK_FIELDS = {'schema_version', 'generated_at', 'day', 'source', 'summary', 'picks'}


def muted(takedowns, kind, day):
    return any(isinstance(t, dict) and t.get('kind') == kind and t.get('day') == day for t in takedowns or [])


def keep(previous, day, now, max_age_hours):
    """Whether yesterday's stored pick may stand in on a day without a new paid call."""
    try:
        if previous.get('day') == day:
            return True
        return previous.get('source') == 'ai' \
            and now - datetime.fromisoformat(previous['generated_at']) <= timedelta(hours=max_age_hours)
    except (KeyError, TypeError, ValueError):
        return False


def stored_header(pick, now):
    """The generated time of a well-formed stored pick, else None. Raises nothing for bad shapes; a bad time
    string raises ValueError like datetime.fromisoformat (callers already catch it)."""
    if not isinstance(pick, dict) or set(pick) != PICK_FIELDS or pick['schema_version'] != 1 \
            or pick['source'] not in ('ai', 'rule') or not isinstance(pick['picks'], list) \
            or not isinstance(pick['day'], str):
        return None
    generated = datetime.fromisoformat(pick['generated_at'])
    return None if generated.tzinfo is None or generated > now else generated


# Request settings for a regular daily pick (claude_trial.VARIANTS). Approved 2026-11-25 after 11 measured days
# (variant_trial): the benefit card passed the host review 10/11 with adaptive-high vs 6/11 with thinking off, at
# about $0.0025 instead of $0.0008 a request. Other kinds keep the regular request (festival passed 11/11 either way).
REGULAR_VARIANTS = {'benefit': 'adaptive-high'}


def daily_draft(root, folder, kind, current, review, now, invoke, runs):
    """At most one paid call a day for `kind`: (pick or None, model status, error codes).

    The attempt is stored before calling, so a crash cannot open a second paid attempt that day. A rejected
    draft's codes are copied from the trial CLI's validation so the run summary says why the card is a rule card."""
    day = now.date().isoformat()
    state_path = project_path(root, f'cache/{folder}/days.json')
    state = load(state_path, {'days': {}})
    digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]
    input_path = project_path(root, f'.tools/ai-{kind}-inputs/{day}-{digest}.json')
    save_text(input_path, json.dumps(current, ensure_ascii=False, separators=(',', ':')))
    state['days'][day] = {'status': 'attempted', 'input_file': str(input_path.relative_to(root))}
    save(state_path, state)
    variant = REGULAR_VARIANTS.get(kind)
    model = invoke(root, kind, input_path, variant=variant) if variant else invoke(root, kind, input_path)
    pick, errors = None, []
    if model['status'] == 'validated_draft':
        try:
            draft = load(runs / model['run_id'] / 'result.json', None)
            errors = review(draft)
            if not errors:
                pick = dict(schema_version=1, generated_at=now.isoformat(), day=day, source='ai',
                            summary=draft['summary'], picks=draft['picks'])
        except (OSError, ValueError, KeyError, TypeError):
            errors = ['draft_unreadable']
    elif model['status'] == 'rejected_draft':
        try:
            errors = [str(e)[:80] for e in load(runs / model['run_id'] / 'validation.json', {}).get('errors', [])][:20]
        except (OSError, ValueError, KeyError, TypeError):
            errors = ['rejection_unreadable']
    state['days'][day].update(model)
    save(state_path, state)
    return pick, model, errors


def already_tried(root, folder, now):
    return now.date().isoformat() in load(project_path(root, f'cache/{folder}/days.json'), {'days': {}})['days']
