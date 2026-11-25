"""Operational tuning values with approved ranges (2026-11-25, improvement phase G).

config/tuning.json holds numbers that operations adjusts often (candidate windows, retention days,
report thresholds). Each has an approved [min, max]; changing a value inside it is an ordinary
reviewed edit, changing a range needs a new user approval recorded in docs/ai/policy-map.md.
A missing file, an unknown or missing key, a wrong type or a value outside its range raises, so a
bad edit fails the tests and every run instead of silently using something else.

Publication-gate rules (topic keywords, auto-publish patterns), cost, model and request settings
and the daily call limits are deliberately not here.
"""
from functools import lru_cache
import json
from pathlib import Path

FILE = Path(__file__).resolve().parents[1] / 'config/tuning.json'
ENTRY_KEYS = {'value', 'min', 'max', 'unit', 'why'}


def errors(data):
    """Problems with a tuning document; empty means valid."""
    found = []
    if not isinstance(data, dict) or data.get('schema_version') != 1 or not isinstance(data.get('values'), dict):
        return ['document shape']
    for name, entry in data['values'].items():
        if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
            found.append(f'{name}: keys')
            continue
        numbers = [entry[k] for k in ('value', 'min', 'max')]
        if any(isinstance(n, bool) or not isinstance(n, (int, float)) for n in numbers):
            found.append(f'{name}: not a number')
            continue
        if isinstance(entry['min'], int) and isinstance(entry['max'], int) and not isinstance(entry['value'], int):
            found.append(f'{name}: integer range needs an integer value')
        if not entry['min'] <= entry['value'] <= entry['max']:
            found.append(f'{name}: {entry["value"]} outside [{entry["min"]}, {entry["max"]}]')
        if not isinstance(entry['why'], str) or not entry['why'] or not isinstance(entry['unit'], str):
            found.append(f'{name}: description')
    return found


@lru_cache(maxsize=1)
def _load():
    data = json.loads(FILE.read_text(encoding='utf-8'))
    problems = errors(data)
    if problems:
        raise ValueError('invalid config/tuning.json: ' + '; '.join(problems))
    return data['values']


def value(name):
    values = _load()
    if name not in values:
        raise KeyError(f'unknown tuning value {name}')
    return values[name]['value']
