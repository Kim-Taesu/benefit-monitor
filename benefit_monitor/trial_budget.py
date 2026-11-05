"""Persistent, fail-closed reservation ledger for the user-approved $5 trial."""
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import re
import stat

CAP = 5_000_000  # microUSD, across all days and restarts
MAX_REQUESTS = 40


def secure_open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise ValueError('unsafe file owner/permissions')
    return fd


class TrialBudget:
    def __init__(self, path):
        self.path = Path(path)

    @classmethod
    def initialize(cls, path, model, input_rate, output_rate):
        if not re.fullmatch(r'claude-haiku-5-5(?:[-.][a-zA-Z0-9]+)*', model):
            raise ValueError('unapproved trial model')
        if (input_rate, output_rate) != ('0.10', '0.50'):
            raise ValueError('unapproved rate card')
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        state = dict(version=1, cap_microdollars=CAP, max_requests=MAX_REQUESTS,
                     model=model, input_rate=input_rate, output_rate=output_rate,
                     halted=False, requests=[])
        fd = secure_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        return cls(path)

    def _validate(self, state):
        try:
            if (type(state['cap_microdollars']) is not int or state['cap_microdollars'] != CAP
                    or state['max_requests'] != MAX_REQUESTS or state['version'] != 1
                    or type(state['halted']) is not bool
                    or (state['input_rate'], state['output_rate']) != ('0.10', '0.50')
                    or not re.fullmatch(r'claude-haiku-5-5(?:[-.][a-zA-Z0-9]+)*', state['model'])
                    or not isinstance(state['requests'], list) or len(state['requests']) > MAX_REQUESTS):
                raise ValueError
            seen = set()
            for row in state['requests']:
                if not re.fullmatch('[0-9a-f]{64}', row['id']) or row['id'] in seen:
                    raise ValueError
                seen.add(row['id'])
                if row['status'] not in ('reserved', 'completed', 'failed', 'overrun'):
                    raise ValueError
                for key in ('reserved_microdollars', 'charged_microdollars'):
                    if type(row[key]) is not int or row[key] < 0:
                        raise ValueError
            if self._exposure(state) > CAP and not state['halted']:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError('invalid trial ledger; do not reset') from None

    @contextmanager
    def _locked(self):
        fd = secure_open(self.path, os.O_RDWR)
        with os.fdopen(fd, 'r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                text = f.read(1_048_577)
                if len(text) > 1_048_576:
                    raise ValueError('trial ledger too large')
                state = json.loads(text)
                self._validate(state)
                yield state
                self._validate(state)
                f.seek(0)
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
            except json.JSONDecodeError:
                raise ValueError('invalid trial ledger; do not reset') from None
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _exposure(state):
        return sum(r['charged_microdollars'] if r['status'] == 'completed'
                   else max(r['reserved_microdollars'], r['charged_microdollars'])
                   for r in state['requests'])

    def summary(self):
        with self._locked() as state:
            return {**state, 'request_count':len(state['requests']),
                    'exposure_microdollars':self._exposure(state),
                    'remaining_microdollars':max(0, CAP - self._exposure(state)),
                    'confirmed_microdollars':sum(r['charged_microdollars'] for r in state['requests'])}

    def reserve(self, request_id, amount):
        if not re.fullmatch('[0-9a-f]{64}', request_id) or type(amount) is not int or not 0 <= amount <= CAP:
            raise ValueError('invalid reservation')
        with self._locked() as state:
            existing = next((r for r in state['requests'] if r['id'] == request_id), None)
            if existing:
                return dict(existing)
            if state['halted']:
                raise ValueError('trial halted; manual review required')
            if len(state['requests']) >= MAX_REQUESTS or self._exposure(state) + amount > CAP:
                raise ValueError('trial budget exhausted')
            row = dict(id=request_id, status='reserved', reserved_microdollars=amount,
                       charged_microdollars=0, started_at=datetime.now(timezone.utc).isoformat())
            state['requests'].append(row)
            return dict(row)

    def fail(self, request_id, code, detail=None):
        with self._locked() as state:
            row = next(r for r in state['requests'] if r['id'] == request_id)
            row.update(status='failed', error_code=code)
            if detail:
                row['error_detail'] = detail[:400]
            state['halted'] = True

    def settle(self, request_id, amount, usage, response_hash):
        if type(amount) is not int or amount < 0 or not re.fullmatch('[0-9a-f]{64}', response_hash):
            raise ValueError('invalid settlement')
        with self._locked() as state:
            row = next(r for r in state['requests'] if r['id'] == request_id)
            if row['status'] != 'reserved':
                raise ValueError('request already settled')
            row.update(status='completed' if amount <= row['reserved_microdollars'] else 'overrun',
                       charged_microdollars=amount, usage=usage, response_sha256=response_hash)
            if row['status'] == 'overrun':
                state['halted'] = True

    def resume_after_review(self):
        """Explicit operator review; retains every failure and reserved dollar."""
        with self._locked() as state:
            if any(r['status'] == 'reserved' for r in state['requests']) or self._exposure(state) >= CAP:
                raise ValueError('unresolved inflight request or exhausted budget')
            state['halted'] = False
            state.setdefault('manual_reviews', []).append(datetime.now(timezone.utc).isoformat())
