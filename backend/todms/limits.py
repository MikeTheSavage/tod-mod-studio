"""The engine and format limits (limits.json, one table for the code and for the UI). Look a number up with value('P1')."""
import json
import os

_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'limits.json')
_CACHE = {}


def table():
    if 'rows' not in _CACHE:
        with open(_FILE, encoding='utf-8') as f:
            _CACHE['rows'] = {r['id']: r for r in json.load(f)['limits']}
    return _CACHE['rows']


def get(lid):
    return table()[lid]


def value(lid):
    return table()[lid]['value']


def rows():
    return list(table().values())


# ---------------------------------------------------------------- the meter rules (one place: archives, checks and the ledger use them)
AMBER_AT = 0.70          # amber from 70 % of the limit, red above 100 %


def enforce(lid):
    """'refuse' (a crash-class limit: an install and an export are refused), 'warn' (policy: shown, never blocks)."""
    return get(lid).get('enforce', 'warn')


def meter_max(lid):
    r = get(lid)
    return r.get('meter_max', r['value'])


def is_unknown(row):
    """A limit whose confidence is UNKNOWN is never shown green: its number is not measured."""
    return str(row.get('confidence') or '').strip().upper().startswith('UNKNOWN')


def status(lid, used):
    """'ok' (green), 'amber', 'red' or 'grey' (not measured: no number to compare, a rule only, or confidence UNKNOWN)."""
    r = get(lid)
    top = meter_max(lid)
    if used is None or not isinstance(top, (int, float)) or isinstance(top, bool) or is_unknown(r):
        return 'grey'
    if used > top:
        return 'red'
    return 'amber' if used >= AMBER_AT * top else 'ok'


def level(lid, used):
    """The check-list level for a measured amount: 'ok', 'warn' or 'error' (error only for a refusing limit that is red)."""
    s = status(lid, used)
    if s == 'red':
        return 'error' if enforce(lid) == 'refuse' else 'warn'
    return 'warn' if s == 'amber' else 'ok'
