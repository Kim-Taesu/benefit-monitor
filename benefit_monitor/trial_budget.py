"""Persistent, fail-closed reservation ledger: monthly $15 cap (user-approved 2026-11-07)."""
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
import fcntl
import json
import os
from pathlib import Path
import re
import stat

# User approval 2026-11-07 ("금액은 난 월 $10~20 도 괜찮은거같음"): the cumulative $5 / 200 requests /
# 14 run days trial becomes a monthly cap. A month is the Asia/Seoul calendar month of a row's
# `started_at`. Ledgers created under the earlier approvals (LEGACY_*) stay valid, their rows are
# never reset or rewritten, and they are upgraded one way by CloudSession.apply_limit_revision().
MONTHLY_CAP = 15_000_000  # microUSD per Seoul calendar month
LEGACY_CAP = 5_000_000
LEGACY_MAX_REQUESTS = (200, 40)
MAX_LEDGER_BYTES = 8 * 1024 * 1024
SEOUL = ZoneInfo('Asia/Seoul')


def secure_open(path, flags):
    fd = os.open(path, flags | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        os.close(fd)
        raise ValueError('unsafe file owner/permissions')
    return fd


class TrialBudget:
    def __init__(self, path, checkpoint=None):
        self.path = Path(path)
        self.checkpoint = checkpoint

    @classmethod
    def initialize(cls, path, model, input_rate, output_rate):
        if not re.fullmatch(r'claude-haiku-5-5(?:[-.][a-zA-Z0-9]+)*', model):
            raise ValueError('unapproved trial model')
        if (input_rate, output_rate) != ('0.10', '0.50'):
            raise ValueError('unapproved rate card')
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        state = dict(version=1, cap_microdollars=MONTHLY_CAP, cap_kind='monthly',
                     model=model, input_rate=input_rate, output_rate=output_rate,
                     halted=False, requests=[])
        fd = secure_open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
        with os.fdopen(fd, 'w') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        return cls(path)

    @staticmethod
    def is_legacy(state):
        return state.get('cap_kind') is None

    def _validate(self, state):
        try:
            legacy = self.is_legacy(state)
            if legacy:
                if state['cap_microdollars'] != LEGACY_CAP or state['max_requests'] not in LEGACY_MAX_REQUESTS \
                        or len(state['requests']) > state['max_requests']:
                    raise ValueError
            elif state['cap_kind'] != 'monthly' or 'max_requests' in state or state['cap_microdollars'] != MONTHLY_CAP:
                raise ValueError
            if (type(state['cap_microdollars']) is not int or state['version'] != 1
                    or type(state['halted']) is not bool
                    or (state['input_rate'], state['output_rate']) != ('0.10', '0.50')
                    or not re.fullmatch(r'claude-haiku-5-5(?:[-.][a-zA-Z0-9]+)*', state['model'])
                    or not isinstance(state['requests'], list)):
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
            # Monthly ledgers: the cap is a pre-reservation check in reserve(), not an invariant over
            # past months (an overrun halts; resuming next month must stay possible). Rows still need
            # a valid started_at.
            self._month_totals(state) if not legacy else None
            if legacy and not state['halted'] and self._exposure(state) > LEGACY_CAP:
                raise ValueError
        except (KeyError, TypeError, ValueError):
            raise ValueError('invalid trial ledger; do not reset') from None

    @contextmanager
    def _locked(self):
        fd = secure_open(self.path, os.O_RDWR)
        with os.fdopen(fd, 'r+') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                text = f.read(MAX_LEDGER_BYTES + 1)
                if len(text) > MAX_LEDGER_BYTES:
                    raise ValueError('trial ledger too large')
                state = json.loads(text)
                self._validate(state)
                original = deepcopy(state)
                yield state
                self._validate(state)
                f.seek(0)
                json.dump(state, f, ensure_ascii=False, indent=2)
                f.truncate()
                f.flush()
                os.fsync(f.fileno())
                if self.checkpoint is not None and state != original:
                    self.checkpoint(deepcopy(state))
            except json.JSONDecodeError:
                raise ValueError('invalid trial ledger; do not reset') from None
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _exposure(state):
        return sum(TrialBudget._row_exposure(r) for r in state['requests'])

    @staticmethod
    def _row_exposure(row):
        return (row['charged_microdollars'] if row['status'] == 'completed'
                else max(row['reserved_microdollars'], row['charged_microdollars']))

    @staticmethod
    def _month_key(started_at):
        moment = datetime.fromisoformat(started_at)
        if moment.tzinfo is None:
            raise ValueError('timezone required')
        local = moment.astimezone(SEOUL)
        return local.year, local.month

    @classmethod
    def _month_totals(cls, state):
        totals = {}
        for row in state['requests']:
            key = cls._month_key(row['started_at'])
            totals[key] = totals.get(key, 0) + cls._row_exposure(row)
        return totals

    @classmethod
    def month_exposure(cls, state, now):
        """Exposure of rows whose started_at falls in the Seoul calendar month of `now`."""
        if now.tzinfo is None:
            raise ValueError('timezone required')
        local = now.astimezone(SEOUL)
        return cls._month_totals(state).get((local.year, local.month), 0)

    def summary(self):
        with self._locked() as state:
            now = datetime.now(timezone.utc)
            month = self.month_exposure(state, now)
            legacy = self.is_legacy(state)
            return {**state, 'request_count':len(state['requests']),
                    'exposure_microdollars':self._exposure(state),
                    'remaining_microdollars':max(0, (LEGACY_CAP - self._exposure(state)) if legacy
                                                 else MONTHLY_CAP - month),
                    'month_exposure_microdollars':month,
                    'month_remaining_microdollars':max(0, MONTHLY_CAP - month),
                    'confirmed_microdollars':sum(r['charged_microdollars'] for r in state['requests'])}

    def reserve(self, request_id, amount, now=None):
        now = now or datetime.now(timezone.utc)
        if not re.fullmatch('[0-9a-f]{64}', request_id) or type(amount) is not int or not 0 <= amount <= MONTHLY_CAP:
            raise ValueError('invalid reservation')
        with self._locked() as state:
            existing = next((r for r in state['requests'] if r['id'] == request_id), None)
            if existing:
                return dict(existing)
            if state['halted']:
                raise ValueError('trial halted; manual review required')
            if self.is_legacy(state):  # not yet revised: the original cumulative rules still bind
                if len(state['requests']) >= state['max_requests'] or self._exposure(state) + amount > LEGACY_CAP:
                    raise ValueError('trial budget exhausted')
            elif self.month_exposure(state, now) + amount > MONTHLY_CAP:
                raise ValueError('monthly budget exhausted')
            row = dict(id=request_id, status='reserved', reserved_microdollars=amount,
                       charged_microdollars=0, started_at=now.isoformat())
            state['requests'].append(row)
            return dict(row)

    def fail(self, request_id, code, detail=None, halt=True):
        """halt=False only for an unbilled grammar-probe rejection; the row is still kept."""
        with self._locked() as state:
            row = next(r for r in state['requests'] if r['id'] == request_id)
            row.update(status='failed', error_code=code)
            if detail:
                row['error_detail'] = detail[:400]
            if halt:
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

    @classmethod
    def exhausted(cls, state, now):
        if cls.is_legacy(state):
            return cls._exposure(state) >= LEGACY_CAP
        return cls.month_exposure(state, now) >= MONTHLY_CAP

    def resume_after_review(self):
        """Explicit operator review; retains every failure and reserved dollar."""
        with self._locked() as state:
            if any(r['status'] == 'reserved' for r in state['requests']) or self.exhausted(state, datetime.now(timezone.utc)):
                raise ValueError('unresolved inflight request or exhausted budget')
            state['halted'] = False
            state.setdefault('manual_reviews', []).append(datetime.now(timezone.utc).isoformat())
