"""Shared adjustment grammar and CSV input for the surviving lever sheets."""

import re

import static_data


# Mirrors MissionRewards.Adjust.Parse. Blank and invalid cells are distinct.
_NUMBER_RE = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')

NONE, SET, ADD, MULTIPLY = 'none', 'set', 'add', 'multiply'


def parse_adjust(spec):
    """-> (kind, value, ok). kind is none/set/add/multiply; ok is False only
    for a cell that carried text the grammar rejects."""
    s = (spec if spec is not None else '').strip()
    if s == '':
        return (NONE, None, True)
    kind, body = SET, s
    c = s[0]
    if c == '=':
        kind, body = SET, s[1:]
    elif c in ('x', 'X', '*'):
        kind, body = MULTIPLY, s[1:]
    elif c == '+':
        kind, body = ADD, s[1:]
    elif c == '-':
        kind, body = ADD, s          # the sign stays on the body
    body = body.strip()
    if not _NUMBER_RE.match(body):
        return (NONE, None, False)
    try:
        return (kind, float(body), True)
    except ValueError:
        return (NONE, None, False)


ADJUST_CASES_OK = [
    ('', NONE, None), ('  ', NONE, None), ('=40', SET, 40), ('40', SET, 40),
    ('=-55', SET, -55), ('+25', ADD, 25), ('-25', ADD, -25),
    ('x1.5', MULTIPLY, 1.5), ('X1.5', MULTIPLY, 1.5), ('*1.5', MULTIPLY, 1.5),
    ('x.75', MULTIPLY, 0.75), ('=0', SET, 0), ('0', SET, 0), ('+0', ADD, 0),
    ('x-2', MULTIPLY, -2), ('=1e3', SET, 1000), ('  =40  ', SET, 40),
    ('=+5', SET, 5), ('.5', SET, 0.5), ('++5', ADD, 5), ('+-5', ADD, -5),
]
ADJUST_CASES_BAD = ['abc', 'x', '=', '+', '-', '1,000', '4 2', '=4a', 'xx2',
                    '=1.2.3', '0x10', '=,', '- 25', '1 000', '%50']


class Problem(Exception):
    pass


def read_csv_rows(path, what):
    try:
        rows = static_data.read_csv(path)
    except (OSError, ValueError) as exc:
        raise Problem('%s at %s could not be read: %s' % (what, path, exc)) from exc
    if not rows:
        raise Problem('%s at %s has no data rows; this is not a complete input.' % (what, path))
    return rows
