#!/usr/bin/env python3
"""gear_classes.py -- the gear-class lever sheet, and the partition it rests on.

WHAT THIS FILE IS FOR

`ckf.hardmode.d/gear-classes.csv` is a LEVER SHEET, not a direct overlay: one
row is a player weapon class, the columns are tuning levers rather than game
columns, and one row expands into writes across many `WeaponModel` rows. The
expansion happens in the plugin at load (`mods/CKFHardMode/GearClasses.cs`),
never here and never in the GUI -- design.md section 1, "Why the mod expands,
not the GUI", which is settled. Hand-editing the sheet with the game and the
editor closed has to work, so nothing on disk may be a compiled mirror of it.

This script therefore does three things, none of which is "be the loader":

  --write     regenerate the sheet from the declarations below. Hand-writing
              it is how the 16 id ranges this change deletes drifted.
  --check     compile the OLD rules (the 16 `RecoilRate2` ranges still in
              ckf.hardmode.rules.json) and the NEW sheet, apply both to the
              dumped `WeaponModel`, and compare every lever column on all 535
              rows. Every difference must match a DECLARED, sanctioned
              deviation; an undeclared one is a problem and a non-zero exit.
  --census    the partition assertion, printed whether or not it finds a fault.
  --selftest  fault injection, with a control case first.

THE PARTITION, AND WHY IT IS DERIVED RATHER THAN LISTED

`WeaponModel` has no column marking a row player or enemy. The canonical
definition is `overlays/_reference/player-vs-enemy-gear.md`: a row is enemy
gear when `MonsterTypeModel` points at it, and the player set is everything
else.

WHICH `MonsterTypeModel`, THOUGH -- this is the whole of it, and reading it
wrong costs eight player assault rifles.

  The SHIPPED table (sheets/raw/MonsterTypeModel.csv) has 208 distinct
  `WeaponTypeId` values and puts class 3 at 25 player / 51 enemy. [measured]

  The table AFTER this mod's own enemy overlay (ckf.hardmode.d/
  MonsterTypeModel.csv) has 405 and puts class 3 at 33 / 43. [measured]

design.md section 5 states 33/43 for class 3 and 33/40 for class 10. Only the
second reading reproduces BOTH. The difference is the enemy-ladder split-out:
the overlay repoints every full-ladder archetype off the 46 shared sub-20000
weapons onto the cloned 900000-900199 block, which is what turned those 46 into
player gear. So the pointer set that matters is the post-overlay one, and it is
the one the plugin can actually read at load -- from a config file it already
owns, with no game-table enumeration.

That last point is not a convenience. `mods/CKFHardMode/RowClone.cs` records
why the plugin does not call bulk readers ("Do not serve into a whole-table
read ... Nothing during play enumerates a whole table", after a mission that
died on a null armour), and at plugin init there is no database instance to
call one on in any case.

A HAND LIST CANNOT DO WHAT THE ASSERTION DOES

The thing being replaced is a hand-maintained list of 16 whereMin/whereMax
pairs, copied out of player-vs-enemy-gear.md. It drifted in both directions: it
caught 30 drone weapons that did not exist when it was written, and it missed
10 player assault rifles that became player gear when the ladders were split.
Regenerating the list by hand on every game update is the same mechanism with a
shorter fuse.

So the sheet carries no ids at all, and this script asserts a PARTITION instead
-- a property that stays true as rows are added, rather than a list that has to
be rewritten when they are:

  P1  every WeaponModel row lands in exactly one bucket: a lever class's player
      set, that class's enemy set, or an excluded class. None in two, none in
      none.
  P2  the ten lever classes' player sets are pairwise disjoint.
  P3  their union is exactly the set of rows the ten generated rules touch.
  P4  no id the expander resolves is in the MonsterTypeModel pointer set.
  P5  every class is named with its counts, INCLUDING a class whose player set
      is empty -- a class that contributed nothing in silence cannot be told
      from a class the instrument failed to look at (AGENTS.md).

A weapon the game ships tomorrow lands in a named bucket on the next run, and
if it lands in none, P1 names the row and the reason.
"""

import argparse
import csv
import io
import json
import os
import re
import sys


# ---------------------------------------------------------------------------
# Declarations. The sheet is generated from these; nothing here is read back
# out of the sheet, so a hand edit to the sheet shows up as a --check
# difference rather than being silently adopted.
# ---------------------------------------------------------------------------

# design.md section 5. Ten of the sixteen classes get a lever row.
LEVER_CLASSES = [
    (1,  'Melee'),
    (2,  'Pistol'),
    (3,  'AR (Assault Rifle)'),
    (4,  'Shotgun'),
    (5,  'E-Rifle'),
    (6,  'Sniper Rifle'),
    (10, 'SMG'),
    (11, 'Revolver'),
    (12, 'UAR (Urban Assault Rifle)'),
    (14, 'Railgun'),
]

# Six do not, and the sheet says why. Asserted over the GENERATED RULES, not by
# reading the sheet: no rule the sheet produces may name a weapon in any of
# these. All sixteen classes have player rows -- the smallest is class 7 at 1
# and the largest class 1 at 61 [measured, dump] -- so the gap between 16 and
# 10 is a scope decision, not a data gap.
EXCLUDED_CLASSES = {
    7:  'Canine Attack Rig -- a single row, so a class lever is that row with extra steps',
    9:  'DroneAR -- drones are out of scope (proposal.md non-goals)',
    16: 'Cyber Weapon Claws -- tuned item by item in cyberweapons-claws.csv',
    17: 'Cyber Weapon Eyes -- tuned item by item in cyberweapons-lasers.csv',
    18: 'DroneSMG -- drones are out of scope (proposal.md non-goals)',
    19: 'DroneERifle -- drones are out of scope (proposal.md non-goals)',
}

# Ids 8, 13 and 15 carry no WeaponModel row in the dump. [measured]
# Named so that "absent" and "excluded" stay different answers.
UNUSED_CLASSES = (8, 13, 15)

# design.md section 5, in its order. Every one of the 22 is present in the
# dumped WeaponModel header and not one of them is an unsuffixed alias.
# Both facts are asserted in check_columns().
LEVERS = [
    'Accuracy1', 'Accuracy2', 'BallisticDamage1', 'BallisticDamage2',
    'PhysicalDamage1', 'PureDamage1', 'PureDamage2', 'ActionPoints1',
    'ActionPoints2', 'RecoilRate1', 'RecoilRate2', 'ArmorCritRate1',
    'ArmorCritRate2', 'MaxRange', 'OptimalRangeA1', 'OptimalRangeB1',
    'OptimalRangeA2', 'OptimalRangeB2', 'FAShots', 'CritMultiBase',
    'CritMultiStealth', 'ShotVolume',
]

# Excluded columns, recorded so they are not re-proposed. design.md section 5.
# The first three are constant across the whole table. A dump taken with
# DropConstantColumns omits them; otherwise they are in the header, so they are
# excluded here on their own merits.
EXCLUDED_COLUMNS = {
    'FiringMode':        'value 1 on all 535 rows',
    'IsHeavyWeapon':     'True on all 535 rows',
    'PhysicalDamage2':   '0 on every row',
    'FullAutoTargetMax': 'set on 18 of 535 rows and never on an AR',
    'ReloadClipMax':     'set on two classes only',
    'ReloadActionPoints': 'not a class-wide lever',
    'ReloadSize':        'not a class-wide lever',
    'AngleFire1':        'not a class-wide lever',
    'Cost':              'not a class-wide lever',
}

# THE CELLS.
#
# The generated sheet sets exactly one lever, the one the 16 deleted 3.x ranges
# expressed: x1.8 mode-2 recoil on player weapons. Everything else is
# generated blank, and a blank cell leaves the column alone.
#
# WHY ONLY FOUR ROWS CARRY IT. RecoilRate2 is zero on every player row of the
# other six lever classes in the dump, so x1.8 there is a no-op whichever way
# it is written. [measured] Classes 3, 5, 10 and 12 are the four dual-mode player
# classes. The lever-sheets spec requires that no table show a column dead for
# its own rows, so a row whose mode-2 column does not exist gets a blank and a
# _comment saying so, rather than a multiplier that would silently begin to
# bite if the game ever gave that class a second firing mode.
CELLS = {
    3:  {'RecoilRate2': '*1.8'},
    5:  {'RecoilRate2': '*1.8'},
    10: {'RecoilRate2': '*1.8'},
    12: {'RecoilRate2': '*1.8'},
}

ROW_COMMENTS = {
    1:  'Melee. No mode 2: RecoilRate2 is 0 on all 61 player rows.',
    2:  'Pistol. No mode 2: RecoilRate2 is 0 on all 26 player rows.',
    3:  'AR. Dual-mode. x1.8 mode-2 recoil, the rule the 16 deleted id ranges expressed.',
    4:  'Shotgun. No mode 2: RecoilRate2 is 0 on all 25 player rows.',
    5:  'E-Rifle. Dual-mode. x1.8 mode-2 recoil.',
    6:  'Sniper Rifle. No mode 2: RecoilRate2 is 0 on all 25 player rows.',
    10: 'SMG. Dual-mode. x1.8 mode-2 recoil.',
    11: 'Revolver. No mode 2: RecoilRate2 is 0 on all 26 player rows.',
    12: 'UAR. Dual-mode. x1.8 mode-2 recoil.',
    14: 'Railgun. No mode 2: RecoilRate2 is 0 on all 22 player rows.',
}

SHEET_NAME = 'gear-classes.csv'
ID_COLUMN = 'WeaponId'
CLASS_COLUMN = 'WeaponClass'
POINTER_FILE = 'MonsterTypeModel.csv'
POINTER_COLUMN = 'WeaponTypeId'

# The 16 whereMin/whereMax pairs the conversion deleted, as they stood in the
# 3.x ckf.hardmode.rules.json. Held here so --ruleset-3x can compile the OLD
# side without a rules file, which the 4.0 layout does not have.
OLD_RECOIL_RANGES = [
    (3, 3), (16, 16), (30, 30), (64, 64), (76, 82), (1002, 1004),
    (1006, 1013), (1017, 1017), (1022, 4024), (5017, 5034), (6002, 6002),
    (6007, 6012), (6017, 12014), (13006, 13010), (13015, 13017),
    (24000, 30016),
]
OLD_RECOIL_FACTOR = 1.8
OLD_RECOIL_COLUMN = 'RecoilRate2'

# ---------------------------------------------------------------------------
# THE DEVIATIONS THE CONVERSION APPLIED.
#
# A RECORD OF WHAT THE CONVERSION DID, NOT A CLOSED LIST OF WHAT IS ALLOWED.
# Deviation from the 3.0 ruleset is tuning, not a mistake (David's rule).
#
# This table is consulted only under --ruleset-3x (see RULESET_3X_RETIRED_WHY
# below), where it labels which divergences the conversion authored and which
# it did not. Neither label is a verdict.
# ---------------------------------------------------------------------------

DEVIATIONS = [
    {
        'id': 'D2',
        'name': 'the accidental x1.8 RecoilRate2 on 30 drone weapons stops',
        'column': 'RecoilRate2',
        'ids': list(range(26000, 26030)),
        'direction': 'loses',
        'why': ('The 24000-30016 sweep was authored when that range held only '
                'cyberweapons and Orca rifles. Classes 9, 18 and 19 did not exist '
                'then and get no lever row, so these lose the multiplier outright '
                'and gain no replacement. proposal.md section 4.'),
    },
    {
        'id': 'D4',
        'name': 'ten player assault rifles gain the x1.8 they should already have had',
        'column': 'RecoilRate2',
        'ids': [17, 1001, 1005, 1014, 1015, 1016, 1018, 1019, 1020, 1021],
        'direction': 'gains',
        'why': ('These became player gear when the enemy ladders were split into '
                '900160-900199 and every archetype was repointed. The hand-maintained '
                'range list was never regenerated, so they have been missing a '
                'multiplier the rule\'s own comment -- "PLAYER - player weapons only '
                '... heavier recoil in full auto" -- says they should have had. '
                'David\'s decision.'),
    },
]

# Rows that are INSIDE a deviation's class but do NOT move, recorded because the
# brief that authorised D4 said thirteen rows move and the measurement says ten.
# 30011-30013 are class 3 and were already inside the 3.x 24000-30016 range, so
# they carried x1.8 and KEEP it rather than gaining it. Naming them here stops
# the 13 being re-derived. [measured]
D4_UNCHANGED_SIBLINGS = [30011, 30012, 30013]

# THE COMPLETE LIST OF SANCTIONED DEVIATIONS, so that this file is the record
# rather than half of it. DEVIATIONS above holds only the two --check can see:
# it compares WeaponModel lever columns, so a deviation in another table or
# another file is outside its reach by construction, not by omission.
#
#   D1  the MonsterTypeModel PL 11+ rule is deleted -- ChasingSpeed and
#       AggroSpeed x1.1 at PowerLevel 11 and above. 118 of the 120 rows at each
#       of PL 11-20 move on both columns (the other two are 0 on both, where
#       x1.1 was already a no-op): 1,180 rows, 2,360 values, every one of them
#       back to the shipped number. Nothing else wrote those two columns at
#       conversion time [measured].
#   D2  below -- the accidental x1.8 on 30 drone weapons stops.
#   D4  below -- ten player assault rifles gain the x1.8.
#   D3  implantStressClampMin, a key that never binds; recorded here so the
#       conversion's four are readable from one place.
#
# D1-D4 are the record of what the CONVERSION did (the migrator applies them),
# not a list of the only changes permitted since: tuning is what these sheets
# are for.


# ---------------------------------------------------------------------------
# The adjustment grammar.
#
# A TRANSCRIPTION of mods/CKFHardMode/MissionRewards.cs, MissionRewards.Adjust.
# Parse, which is also what gui/serve.py's parse_adjust transcribes. Three
# copies exist on purpose and are tested against one case table; this is the
# fourth reader of that grammar and it is deliberately NOT a fourth
# implementation of the case table -- ADJUST_CASES below is the same table
# serve.py --selftest uses, and --selftest checks this against it.
#
# THREE-STATE, not two. Blank and unparseable are different answers: a two-state
# test returns "no operation" for both, which is how a typo like "1.8x" becomes
# a silent no-op. Overlays.BuildRule learned this in Phase 4 and grew a
# LineResult for it.
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Reading the world
# ---------------------------------------------------------------------------

class Problem(Exception):
    pass


def read_csv_rows(path, what):
    if not os.path.isfile(path):
        # "could not look" is not "nothing there". AGENTS.md.
        raise Problem(f'{what} is not on disk at {path}. This is a refusal, not '
                      f'an empty answer: nothing read it, so how many rows it '
                      f'holds is not known.')
    with io.open(path, newline='', encoding='utf-8') as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise Problem(f'{what} at {path} has a header and no data rows.')
    return rows


def load_weapons(dump_dir):
    rows = read_csv_rows(os.path.join(dump_dir, 'WeaponModel.csv'),
                         'the dumped WeaponModel table')
    out = []
    for r in rows:
        try:
            out.append({'id': int(r[ID_COLUMN]), 'cls': int(r[CLASS_COLUMN]),
                        'name': r.get('WeaponName', ''), 'raw': r})
        except (KeyError, ValueError) as e:
            raise Problem(f'WeaponModel row {r!r} has no readable {ID_COLUMN}/'
                          f'{CLASS_COLUMN}: {e}')
    ids = [w['id'] for w in out]
    if len(set(ids)) != len(ids):
        raise Problem(f'WeaponModel has {len(ids)} rows but only {len(set(ids))} '
                      f'distinct {ID_COLUMN} values.')
    return out


def load_pointer_set(overlay_dir):
    """The enemy set, from the mod's own MonsterTypeModel overlay -- the
    post-overlay pointer set, which is the one that reproduces design.md
    section 5's anchors. Returns (ids, rows_read)."""
    path = os.path.join(overlay_dir, POINTER_FILE)
    rows = read_csv_rows(path, 'the MonsterTypeModel enemy overlay')
    col = POINTER_COLUMN
    if col not in rows[0]:
        raise Problem(f'{path} has no {col} column, so the player/enemy partition '
                      f'cannot be resolved. Refusing rather than treating an '
                      f'unreadable pointer file as "no enemies".')
    ids, blank = set(), 0
    for r in rows:
        v = (r[col] or '').strip()
        if not v:
            blank += 1
            continue
        ids.add(int(v))
    if blank:
        raise Problem(f'{path}: {blank} row(s) have a blank {col}. Every monster '
                      f'row must name a weapon for the partition to be complete.')
    return ids, len(rows)


# ---------------------------------------------------------------------------
# The sheet
# ---------------------------------------------------------------------------

SHEET_HEADER = [CLASS_COLUMN] + LEVERS + ['_comment']


def render_sheet():
    buf = io.StringIO(newline='')
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(SHEET_HEADER)
    for cls, _name in LEVER_CLASSES:
        cells = CELLS.get(cls, {})
        w.writerow([cls] + [cells.get(c, '') for c in LEVERS]
                   + [ROW_COMMENTS.get(cls, '')])
    return buf.getvalue()


def read_sheet(path):
    rows = read_csv_rows(path, 'the gear-class lever sheet')
    hdr = list(rows[0].keys())
    if hdr != SHEET_HEADER:
        raise Problem(f'{path} header is {hdr!r}; expected {SHEET_HEADER!r}. '
                      f'Regenerate it with --write.')
    return rows


# ---------------------------------------------------------------------------
# The expander -- a transcription of GearClasses.Expand, deliberately
# independent of it. Phase 4's lesson: the thing that checks the writer must
# not be the writer.
# ---------------------------------------------------------------------------

class Rule(object):
    def __init__(self, cls):
        self.cls = cls
        self.ops = []          # (kind, column, value), in set/multiply/add order
        self.exclude = None    # the id set this rule must not touch

    def __repr__(self):
        return f'<Rule class={self.cls} ops={self.ops}>'


# The engine applies set, then multiply, then add, within one rule, whatever
# order the columns arrived in (ModelRules.Apply). Emitting one rule per class
# rather than one per cell keeps that order deterministic and keeps the rule
# count at ten rather than up to 220 -- RulePlan tests an unindexed rule against
# every row of its table.
OP_ORDER = [SET, MULTIPLY, ADD]


def expand(sheet_rows, enemy_ids, report=None):
    rules, refusals = [], []
    for row in sheet_rows:
        try:
            cls = int(row[CLASS_COLUMN])
        except (TypeError, ValueError):
            refusals.append(f'{SHEET_NAME}: row with {CLASS_COLUMN}='
                            f'{row.get(CLASS_COLUMN)!r} is not an integer class id')
            continue
        if cls in EXCLUDED_CLASSES:
            refusals.append(f'{SHEET_NAME}: class {cls} has a row but is an '
                            f'excluded class ({EXCLUDED_CLASSES[cls]})')
            continue
        found = {}
        for col in LEVERS:
            kind, val, ok = parse_adjust(row.get(col, ''))
            if not ok:
                # The scenario "An unparseable cell refuses the save" names
                # sheet, row and column. So does this.
                refusals.append(f'{SHEET_NAME}: class {cls}, column {col}: '
                                f'{row.get(col)!r} is not an adjustment '
                                f'(expected blank, =N, +N, -N or xN)')
                continue
            if kind == NONE:
                continue
            found.setdefault(kind, []).append((col, val))
        if not found:
            continue
        r = Rule(cls)
        for kind in OP_ORDER:
            for col, val in found.get(kind, []):
                r.ops.append((kind, col, val))
        r.exclude = enemy_ids
        rules.append(r)
    if refusals and report is not None:
        report.extend(refusals)
    elif refusals:
        raise Problem('; '.join(refusals))
    return rules


def resolved_ids(rule, weapons):
    """Exactly what the plugin resolves: class N minus the pointer set."""
    return {w['id'] for w in weapons
            if w['cls'] == rule.cls and w['id'] not in rule.exclude}


# ---------------------------------------------------------------------------
# P1-P5, the partition assertion
# ---------------------------------------------------------------------------

def partition(weapons, enemy_ids, rules, out=print):
    problems = []
    lever = [c for c, _ in LEVER_CLASSES]
    by_rule = {r.cls: resolved_ids(r, weapons) for r in rules}
    # A lever class with no rule still has a player set; it just has no lever
    # set on it. P3 compares against the classes, not against the rules, so a
    # class whose every cell is blank is visible rather than absent.
    player_of = {c: {w['id'] for w in weapons if w['cls'] == c and w['id'] not in enemy_ids}
                 for c in lever}
    enemy_of = {c: {w['id'] for w in weapons if w['cls'] == c and w['id'] in enemy_ids}
                for c in lever}

    # ---- P1: exactly one bucket, for every row --------------------------
    known = set(lever) | set(EXCLUDED_CLASSES)
    for w in weapons:
        buckets = []
        if w['cls'] in lever:
            buckets.append('player' if w['id'] not in enemy_ids else 'enemy')
        if w['cls'] in EXCLUDED_CLASSES:
            buckets.append('excluded')
        if len(buckets) != 1:
            problems.append(
                f'P1 {ID_COLUMN} {w["id"]} ({w["name"]!r}) has {CLASS_COLUMN} '
                f'{w["cls"]}, which is in {len(buckets)} bucket(s) {buckets}. '
                + ('That class is in neither the ten lever classes nor the six '
                   'excluded ones, so this row is tuned by nothing and named by '
                   'nothing.' if not buckets else
                   'A class cannot be both a lever class and an excluded one.'))
    out(f'P1  535-row bucket test: {len(weapons)} row(s), '
        f'{len(known)} class(es) named, '
        f'{len([w for w in weapons if w["cls"] not in known])} row(s) in no bucket.')

    # ---- P2: pairwise disjoint player sets ------------------------------
    for i, a in enumerate(lever):
        for b in lever[i + 1:]:
            both = player_of[a] & player_of[b]
            if both:
                problems.append(f'P2 classes {a} and {b} share player ids '
                                f'{sorted(both)[:8]}')
    out(f'P2  player sets pairwise disjoint across the {len(lever)} lever '
        f'classes: {len(lever) * (len(lever) - 1) // 2} pair(s) tested.')

    # ---- P3: union is exactly what the rules touch ----------------------
    union_rules = set()
    for ids in by_rule.values():
        union_rules |= ids
    union_classes = set()
    for ids in player_of.values():
        union_classes |= ids
    for cls, ids in by_rule.items():
        if ids != player_of[cls]:
            problems.append(f'P3 class {cls}: the rule resolves {len(ids)} id(s) '
                            f'but the class player set is {len(player_of[cls])}')
    out(f'P3  the {len(rules)} generated rule(s) resolve {len(union_rules)} id(s); '
        f'the ten lever classes hold {len(union_classes)} player row(s). '
        f'{len(union_classes) - len(union_rules)} player row(s) are in a class '
        f'whose every lever cell is blank.')

    # ---- P4: nothing the expander resolves is enemy gear -----------------
    bad = union_rules & enemy_ids
    if bad:
        problems.append(f'P4 the expander resolved {len(bad)} id(s) that '
                        f'MonsterTypeModel points at: {sorted(bad)[:12]}')
    out(f'P4  ids resolved that MonsterTypeModel also points at: {len(bad)}.')

    # ---- P5: every class named, including the empty ones -----------------
    out('P5  per-class census (printed whether or not anything is wrong):')
    out(f'      {"cls":>4}  {"rows":>5} {"player":>7} {"enemy":>6}  role')
    for c, name in LEVER_CLASSES:
        n = len(player_of[c]) + len(enemy_of[c])
        role = 'lever' if c in by_rule else 'lever row, every cell blank'
        if not player_of[c]:
            role += ' -- PLAYER SET IS EMPTY, this class is named and tunes nothing'
        out(f'      {c:>4}  {n:>5} {len(player_of[c]):>7} {len(enemy_of[c]):>6}  '
            f'{role} ({name})')
    for c in sorted(EXCLUDED_CLASSES):
        rows = [w for w in weapons if w['cls'] == c]
        out(f'      {c:>4}  {len(rows):>5} {"-":>7} {"-":>6}  excluded: '
            f'{EXCLUDED_CLASSES[c]}')
    for c in UNUSED_CLASSES:
        rows = [w for w in weapons if w['cls'] == c]
        if rows:
            problems.append(f'P5 class {c} was recorded as unused but carries '
                            f'{len(rows)} row(s) now')
        out(f'      {c:>4}  {0:>5} {"-":>7} {"-":>6}  unused in the dump; '
            f'no WeaponClassName')
    return problems


def check_columns(weapons, out=print):
    """The alias assertion and the header assertion, over the generated rules'
    column names rather than over the sheet."""
    problems = []
    hdr = list(weapons[0]['raw'].keys())
    missing = [c for c in LEVERS if c not in hdr]
    if missing:
        problems.append(f'levers absent from the WeaponModel header: {missing}')
    # An unsuffixed alias is a column whose name is a suffixed column minus its
    # trailing 1 or 2, present in the header in its own right. docs/gotchas.md,
    # "Some columns are computed and silently ignore writes": those writes are
    # taken and discarded, and nothing warns.
    aliases = sorted({c[:-1] for c in hdr if c and c[-1] in '12' and c[:-1] in hdr})
    named = [c for c in LEVERS if c in aliases]
    if named:
        problems.append(f'lever(s) name an unsuffixed alias: {named}')
    out(f'    22 lever(s) declared, {len(LEVERS)} unique, '
        f'{len(missing)} absent from the header, '
        f'{len(aliases)} unsuffixed alias(es) in the header, '
        f'{len(named)} lever(s) naming one.')
    return problems


ENEMY_GEAR_OVERLAY = 'WeaponModel.csv'


def check_clone_inheritance(overlay_dir, weapons, enemy_ids, rules, out=print):
    """P6 -- the one way this partition can leak, and it is not obvious.

    The enemy ladders are built by CLONE rows in ckf.hardmode.d/WeaponModel.csv.
    RowClone builds a clone by re-reading its SOURCE row through the by-id
    reader, which goes through GetRowWeaponModel -- so the source arrives with
    every rule already applied to it. ckf.hardmode.selfcheck.csv records the
    behaviour directly: "ArmorModel,990000,BallisticArmorDegraded,70,V11
    INHERITED from source 22206 -- after V7 edited it". [measured]

    Ten of the fifty-six clone sources are player assault rifles in class 3 --
    17, 1001, 1005, 1014-1016 and 1018-1021, which are precisely the ten ids
    deviation D4 gives the x1.8 to. So if a clone row left RecoilRate2 blank,
    the enemy ladder built from it would inherit the player lever, and the
    scenario "no weapon id in the MonsterTypeModel.WeaponTypeId set is modified
    by that lever" would be false by a route nothing else here looks at.

    Today it cannot happen, for two independent reasons, and BOTH are asserted
    because either one alone could be removed by a later edit:

      a) every one of the 248 clone rows sets every lever column it inherits
         explicitly, so the `as` block overwrites whatever the source carried;
      b) every clone id is in the post-overlay pointer set, so the class rule's
         own exclusion keeps it out.
    """
    problems = []
    path = os.path.join(overlay_dir, ENEMY_GEAR_OVERLAY)
    if not os.path.isfile(path):
        out(f'P6  NOT RUN: {ENEMY_GEAR_OVERLAY} is not in {overlay_dir}. The clone '
            f'inheritance path was not checked — this is a missing check, not a '
            f'clean one.')
        return [f'P6 could not read {path}, so clone inheritance was not checked']

    rows = read_csv_rows(path, 'the enemy-gear WeaponModel overlay')
    hdr = list(rows[0].keys())
    by_id = {w['id']: w for w in weapons}
    # what each lever class writes
    writes = {r.cls: {col for _k, col, _v in r.ops} for r in rules}

    clones = [r for r in rows if (r.get('_clone') or '').strip()]
    leaks, guarded_by_set, guarded_by_exclusion = [], 0, 0
    for r in clones:
        try:
            src = int(r['_clone'])
            new_id = int(r[ID_COLUMN])
        except (KeyError, ValueError):
            continue
        w = by_id.get(src)
        if w is None or src in enemy_ids:
            continue                      # source is enemy gear: no lever on it
        levers_on_source = writes.get(w['cls'], set())
        for col in sorted(levers_on_source):
            blank = col in hdr and not (r.get(col) or '').strip()
            if not blank:
                guarded_by_set += 1
                continue
            if new_id in enemy_ids:
                guarded_by_exclusion += 1
                continue
            leaks.append((new_id, src, col, w['cls'], w['name']))

    for new_id, src, col, cls, name in leaks:
        problems.append(
            f'P6 clone {new_id} is built from {ID_COLUMN} {src} ({name!r}, class '
            f'{cls}), leaves {col} blank so it INHERITS that class\'s lever, and is '
            f'not itself excluded. An enemy weapon is being tuned by a player class '
            f'lever through the clone path.')

    out(f'P6  clone inheritance: {len(clones)} clone row(s), '
        f'{len([r for r in clones if (r.get("_clone") or "").strip() and int(r["_clone"]) in by_id and int(r["_clone"]) not in enemy_ids])} '
        f'built from a player source; {guarded_by_set} lever column(s) overwritten '
        f'by the clone\'s own cell, {guarded_by_exclusion} guarded by the id '
        f'exclusion, {len(leaks)} leaking.')
    return problems


def check_two_recoil_levers(enemy_ids, out=print):
    """Setting RecoilRate1 and leaving RecoilRate2 blank modifies only the
    mode-1 column. Asserted over the generated rules, from a probe sheet."""
    probe = [{CLASS_COLUMN: '3', '_comment': ''}]
    for c in LEVERS:
        probe[0][c] = ''
    probe[0]['RecoilRate1'] = '*1.5'
    rules = expand(probe, enemy_ids)
    cols = [c for _k, c, _v in rules[0].ops]
    ok = cols == ['RecoilRate1']
    out(f'    two recoil levers: RecoilRate1=*1.5, RecoilRate2 blank -> rule '
        f'touches {cols}.')
    return [] if ok else [f'the two recoil levers are fused: rule touches {cols}']


# ---------------------------------------------------------------------------
# --check: old side vs new side, element by element
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# THE OLD-vs-NEW COMPARISON IS RETIRED FROM THE DEFAULT --check.
# ---------------------------------------------------------------------------
#
# David's rule: deviation from the 3.0 ruleset is tuning, not a mistake.
#
# WHAT IS RETIRED. One instrument, and only from the DEFAULT --check:
# compare(), together with the OLD side apply_old() compiles from
# OLD_RECOIL_RANGES (the 16 whereMin/whereMax RecoilRate2 ranges of the 3.x
# ckf.hardmode.rules.json). The problems it raises are spelled
# `UNDECLARED CHANGE`. gear-classes.csv is a lever sheet for tuning, and any
# edited cell that is not RecoilRate2 on a D2/D4 id would make it red.
#
# WHAT IS NOT RETIRED, AND IT IS THE VALUABLE HALF OF THIS FILE. partition()
# and its P1-P6 checks, check_columns(), check_two_recoil_levers(),
# check_clone_inheritance(), the per-class census and the partition's REFUSAL
# to fall back to sheets/raw for the pointer set all run on every --check and
# all still go red.
#
# WHAT IS NOT DELETED. compare(), apply_old(), apply_new(), OLD_RECOIL_RANGES
# and DEVIATIONS are untouched and reachable:
#
#     python scripts/gear_classes.py --check --ruleset-3x --game <root>
#
# and the selftest cases that fault it run under the same flag. Under that flag
# its output is a DIVERGENCE REPORT against the 3.0 ruleset. A divergence is
# not a defect.
#
# HOW THE DEFAULT --check REPORTS IT. NOT RUN, by name, never PASS and never
# absent. AGENTS.md.

RULESET_3X_RETIRED_ON = '2026-09-15'
RULESET_3X_RETIRED_BY = "David's ruling"
RULESET_3X_RETIRED_FLAG = '--ruleset-3x'
RULESET_3X_RETIRED_WHY = (
    'RETIRED from the default --check, %s %s. Run it with '
    '`gear_classes.py --check %s --game <root>`.'
    % (RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON, RULESET_3X_RETIRED_FLAG))

RULESET_3X_RETIRED_CHECKS = (
    ('UNDECLARED CHANGE -- every WeaponModel lever value either the 16 deleted '
     'RecoilRate2 ranges or the sheet moves, old side against new side, with '
     'any difference not claimed by D2 or D4 raised as a problem'),
    ('the D2 / D4 roll-call -- 30 + 10 declared id(s) each measured as having '
     'moved, and any that did not named'),
)

RULESET_3X_RETIRED_CASES = (
    'CONTROL: the shipped sheet is clean on compare()',
    'CONTROL: exactly the declared deviations moved',
    ('F4: the wrong pointer set. RETIRED WHOLE, and this one is a real loss '
     'of coverage, stated rather than glossed. It was first split like '
     "cyberweapons.py's F4 -- keep the live half, retire the compare half -- "
     'and the split was MEASURED WRONG: with the shipped-like pointer set fed '
     'to BOTH the expander and the partition, partition() returns 0 problems '
     'and compare() was the only detector [measured]. partition() '
     'grades the wrong set against itself here; F5, which grades a holed set '
     'against the TRUE set, is the case that does not have this shape and it '
     'still runs. Closing this needs a new live check, not a resurrected '
     'comparison'),
    'F7: an undeclared balance change',
)


def ruleset_3x_report_retired(out=print):
    """Report the old-vs-new comparison as a RECORDED NON-RUN.

    Returns no problems and counts nothing as passed.
    """
    for line in (
        'NOT RUN. The old-vs-new comparison against the 3.0 ruleset is '
        'RETIRED from --check.',
        '%s, %s. The %d check(s) and %d fault case(s) below are reported by '
        'name and never pass.'
        % (RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON,
           len(RULESET_3X_RETIRED_CHECKS), len(RULESET_3X_RETIRED_CASES)),
        '',
        'THE RULING: "Stop considering deviation from the 3.0 ruleset a',
        'mistake. Remove all consideration that this is a problem."',
        '',
        'WHY. It compiles the 16 deleted RecoilRate2 ranges as an OLD side and',
        'calls any difference the sheet shows that DEVIATIONS does not claim an',
        'UNDECLARED CHANGE. That was right while the question was "did the',
        'conversion lose anything". gear-classes.csv is for tuning.',
        '',
        'NOT A TOLERANCE LIST. Nothing was added to DEVIATIONS. The comparison',
        'left the default suite; no value was excused from it.',
        '',
        'THE LIVE CHECKS ALL RAN. The partition (P1-P6), its refusal to fall',
        'back to sheets/raw for the pointer set, the column check, the two',
        'recoil levers and clone inheritance are unchanged and still go red.',
        'Run the two below, unchanged, with:',
        '',
        '    python scripts/gear_classes.py --check %s --game <root>'
        % RULESET_3X_RETIRED_FLAG,
        '',
        'Skipped deliberately, not failed. A recorded non-run, not silence.',
    ):
        out(('      ' + line) if line else '')
    for name in RULESET_3X_RETIRED_CHECKS:
        out('    NOT RUN  %s' % name)
        out('             %s' % RULESET_3X_RETIRED_WHY)
    for name in RULESET_3X_RETIRED_CASES:
        out('    NOT RUN  selftest %s' % name)
        out('             %s' % RULESET_3X_RETIRED_WHY)
    return []


def apply_old(weapons):
    """The 16 ranges, compiled and applied. Independent of the sheet."""
    out = {}
    for w in weapons:
        v = float(w['raw'][OLD_RECOIL_COLUMN])
        if any(a <= w['id'] <= b for a, b in OLD_RECOIL_RANGES):
            v *= OLD_RECOIL_FACTOR
        out[(w['id'], OLD_RECOIL_COLUMN)] = v
    return out


def apply_new(weapons, rules):
    by_cls = {}
    for r in rules:
        by_cls.setdefault(r.cls, []).append(r)
    out = {}
    for w in weapons:
        vals = {c: _num(w['raw'].get(c)) for c in LEVERS if c in w['raw']}
        for r in by_cls.get(w['cls'], []):
            if w['id'] in r.exclude:
                continue
            for kind, col, val in r.ops:
                if col not in vals or vals[col] is None:
                    continue
                if kind == SET:
                    vals[col] = val
                elif kind == MULTIPLY:
                    vals[col] *= val
                elif kind == ADD:
                    vals[col] += val
        for col, v in vals.items():
            if v is not None:
                out[(w['id'], col)] = v
    return out


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def compare(weapons, rules, out=print):
    old, new = apply_old(weapons), apply_new(weapons, rules)
    by_id = {w['id']: w for w in weapons}
    diffs = []
    for key in sorted(set(old) | set(new)):
        wid, col = key
        # The old side only ever wrote RecoilRate2. Comparing the other 21
        # columns means comparing new-vs-shipped, which is the right question:
        # any movement there is also a deviation.
        o = old.get(key, _num(by_id[wid]['raw'].get(col)))
        n = new.get(key, _num(by_id[wid]['raw'].get(col)))
        if o is None or n is None:
            continue
        if abs(o - n) > 1e-9:
            diffs.append((wid, col, o, n))

    claimed, unclaimed = [], []
    for wid, col, o, n in diffs:
        hit = None
        for d in DEVIATIONS:
            if d['column'] == col and wid in d['ids']:
                hit = d
                break
        (claimed if hit else unclaimed).append((wid, col, o, n, hit))

    out(f'    {len(diffs)} value(s) differ between the old rules and the new '
        f'sheet. This is a DIVERGENCE COUNT against the 3.0 ruleset, not a '
        f'defect count -- a difference DEVIATIONS does not claim is a tuning '
        f'edit, not a mistake ({RULESET_3X_RETIRED_BY}, '
        f'{RULESET_3X_RETIRED_ON}).')
    for d in DEVIATIONS:
        mine = [c for c in claimed if c[4] is d]
        out(f'    {d["id"]}: {len(mine)} of {len(d["ids"])} declared id(s) moved '
            f'-- {d["name"]}')
        miss = sorted(set(d['ids']) - {c[0] for c in mine})
        if miss:
            out(f'         {len(miss)} declared id(s) did NOT move: {miss[:12]}'
                + ('' if len(miss) <= 12 else ' ...'))

    problems = []
    for wid, col, o, n, _h in unclaimed:
        problems.append(f'DIVERGENCE {ID_COLUMN} {wid} '
                        f'({by_id[wid]["name"]!r}, class {by_id[wid]["cls"]}) '
                        f'{col} {o:g} -> {n:g} against the 3.0 ruleset, not '
                        f'claimed by D1-D4. Listed because '
                        f'{RULESET_3X_RETIRED_FLAG} was passed. This is NOT a '
                        f'defect by itself: deviation from the 3.0 ruleset is '
                        f'tuning, which is what this sheet is for '
                        f'({RULESET_3X_RETIRED_BY}, {RULESET_3X_RETIRED_ON}).')
    return problems, claimed


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

_selftest_overlay_dir = ['']


class _Skip3x(Exception):
    """Raised inside a retired fault case's try/finally so the case's own
    restore still runs. It never escapes selftest() and never becomes a fail."""


def selftest(weapons, enemy_ids, out=print, run_3x=False):
    fails = []

    def skip_3x(name):
        """A retired fault case, reported by name and never passed. It touches
        neither the PASS count nor `fails`. AGENTS.md."""
        out(f'    NOT RUN  {name}')
        out(f'             {RULESET_3X_RETIRED_WHY}')

    def ck(name, cond, detail=''):
        out(f'    {"PASS" if cond else "FAIL"}  {name}'
            + (f'   {detail}' if detail and not cond else ''))
        if not cond:
            fails.append(name)

    # The grammar, against the same case table gui/serve.py --selftest uses.
    for s, k, v in ADJUST_CASES_OK:
        kind, val, ok = parse_adjust(s)
        ck(f'adjust accepts {s!r}',
           ok and kind == k and (v is None or abs(val - v) < 1e-12),
           f'{(kind, val, ok)}')
    for s in ADJUST_CASES_BAD:
        ck(f'adjust rejects {s!r}', parse_adjust(s)[2] is False)
    # Three-state: blank and bad are different answers.
    ck('blank and unparseable are distinguishable',
       parse_adjust('')[2] is True and parse_adjust('1.8x')[2] is False)

    # CONTROL FIRST. If the clean case does not pass, "everything is caught"
    # cannot be told from "everything fails". Phase 4's shape.
    sheet = list(csv.DictReader(io.StringIO(render_sheet())))
    rules = expand(sheet, enemy_ids)
    probs = partition(weapons, enemy_ids, rules, out=lambda *a: None)
    probs += check_columns(weapons, out=lambda *a: None)
    # THE CONTROL IS SPLIT. Its live half -- the partition and the
    # column check, which know nothing about the 3.0 ruleset -- runs on every
    # suite. Its two 3.x halves are retired with the instrument they control: a
    # control that passes for a comparison nobody runs is a false green.
    if run_3x:
        cmp_probs, claimed = compare(weapons, rules, out=lambda *a: None)
        ck('CONTROL: the shipped sheet is clean', not probs and not cmp_probs,
           f'{(probs + cmp_probs)[:2]}')
        ck('CONTROL: exactly the declared deviations moved',
           len(claimed) == sum(len(d['ids']) for d in DEVIATIONS),
           f'{len(claimed)}')
    else:
        ck('CONTROL: the shipped sheet is clean on every LIVE check', not probs,
           f'{probs[:2]}')
        skip_3x(RULESET_3X_RETIRED_CASES[0])
        skip_3x(RULESET_3X_RETIRED_CASES[1])

    # F1 a lever renamed to its unsuffixed alias
    saved = LEVERS[:]
    try:
        LEVERS[LEVERS.index('BallisticDamage1')] = 'BallisticDamage'
        ck('F1 caught: a lever naming an unsuffixed alias',
           bool(check_columns(weapons, out=lambda *a: None)))
    finally:
        LEVERS[:] = saved

    # F2 the two recoil levers fused
    probe = [dict({c: '' for c in LEVERS}, **{CLASS_COLUMN: '3', '_comment': ''})]
    probe[0]['RecoilRate1'] = '*1.5'
    probe[0]['RecoilRate2'] = '*1.5'
    fused = expand(probe, enemy_ids)
    ck('F2 caught: RecoilRate2 written when only RecoilRate1 was set',
       [c for _k, c, _v in fused[0].ops] != ['RecoilRate1'])

    # F3 a row for an excluded class
    bad = list(csv.DictReader(io.StringIO(render_sheet())))
    bad.append(dict(bad[0], **{CLASS_COLUMN: '9'}))
    rep = []
    expand(bad, enemy_ids, report=rep)
    ck('F3 caught: a lever row for an excluded class', bool(rep), f'{rep}')

    # F4 the shipped pointer set instead of the post-overlay one -- the
    # mistake that costs eight assault rifles.
    shipped_like = {i for i in enemy_ids if i < 20000 or i >= 900000}
    r4 = expand(sheet, shipped_like)
    p4 = partition(weapons, shipped_like, r4, out=lambda *a: None)
    if run_3x:
        c4, _ = compare(weapons, r4, out=lambda *a: None)
        ck('F4 caught: the wrong pointer set (partition and compare)',
           bool(p4 or c4), f'{len(p4)} partition, {len(c4)} compare')
    else:
        # RETIRED WHOLE, AND THE REASON IS A MEASUREMENT, NOT A PREFERENCE.
        # partition() alone does not catch this fault: `p4` is EMPTY here
        # [measured, "0 partition"]. F4 feeds the shipped-like pointer set to the
        # expander AND to the partition, so the partition grades the mistake
        # against itself and agrees with it; only compare(), which reads the
        # real WeaponModel values, sees it. F5 is the case built the other way
        # -- a holed set graded against the TRUE set -- and F5 still runs.
        # So this is a genuine loss of coverage and it is named as one.
        skip_3x(RULESET_3X_RETIRED_CASES[2])

    # F5 an id the expander resolves that MonsterTypeModel also points at.
    #
    # The fault is a HOLED EXCLUSION SET -- the expander told to ignore one
    # enemy id -- graded against the TRUE pointer set. Grading it against the
    # holed set too would compare the mistake with itself and pass whatever
    # happened, which is the shape AGENTS.md calls an instrument
    # built out of the constant under test.
    holed = enemy_ids - {20000}          # 20000 is a class 3 enemy AR
    r5 = expand(sheet, holed)
    p5 = partition(weapons, enemy_ids, r5, out=lambda *a: None)
    ck('F5 caught: an id the expander resolves that MonsterTypeModel points at',
       any(p.startswith('P4') for p in p5), f'{p5[:1]}')
    p5c = partition(weapons, enemy_ids, expand(sheet, enemy_ids), out=lambda *a: None)
    ck('F5 control: P4 clean on the true pointer set',
       not any(p.startswith('P4') for p in p5c))

    # F6 a class silently dropped from the excluded table
    saved_ex = dict(EXCLUDED_CLASSES)
    try:
        del EXCLUDED_CLASSES[9]
        p6 = partition(weapons, enemy_ids, rules, out=lambda *a: None)
        ck('F6 caught: a class in no bucket', any('P1' in p for p in p6), f'{p6[:1]}')
    finally:
        EXCLUDED_CLASSES.clear()
        EXCLUDED_CLASSES.update(saved_ex)

    # F7 an undeclared value change
    saved_cells = {k: dict(v) for k, v in CELLS.items()}
    try:
        if not run_3x:
            skip_3x(RULESET_3X_RETIRED_CASES[3])
            raise _Skip3x
        CELLS.setdefault(1, {})['MaxRange'] = '+3'
        s7 = list(csv.DictReader(io.StringIO(render_sheet())))
        c7, _ = compare(weapons, expand(s7, enemy_ids), out=lambda *a: None)
        ck('F7 caught: an undeclared balance change', bool(c7), f'{c7[:1]}')
    except _Skip3x:
        pass
    finally:
        CELLS.clear()
        CELLS.update(saved_cells)

    # F9 a clone row that leaves a lever blank and inherits it. Built by
    # hiding the clone's own RecoilRate2 cell for a clone whose source is one
    # of the ten class-3 assault rifles, and by dropping that clone id from the
    # exclusion set so neither guard is standing.
    import tempfile, shutil
    try:
        src_ov = os.path.join(_selftest_overlay_dir[0], ENEMY_GEAR_OVERLAY)
        tmp = tempfile.mkdtemp()
        shutil.copy(os.path.join(_selftest_overlay_dir[0], POINTER_FILE), tmp)
        rows9 = read_csv_rows(src_ov, 'x')
        hit = None
        for r9 in rows9:
            c = (r9.get('_clone') or '').strip()
            if c and int(c) in (17, 1001, 1005, 1014, 1015, 1016, 1018, 1019, 1020, 1021):
                r9['RecoilRate2'] = ''
                hit = int(r9[ID_COLUMN])
                break
        with io.open(os.path.join(tmp, ENEMY_GEAR_OVERLAY), 'w', newline='',
                     encoding='utf-8') as fh:
            wtr = csv.DictWriter(fh, fieldnames=list(rows9[0].keys()),
                                 lineterminator='\n')
            wtr.writeheader()
            wtr.writerows(rows9)
        p9 = check_clone_inheritance(tmp, weapons, enemy_ids - {hit}, rules,
                                     out=lambda *a: None)
        ck('F9 caught: a clone inheriting a player class lever',
           any(x.startswith('P6') for x in p9), f'{p9[:1]}')
        shutil.rmtree(tmp, ignore_errors=True)
    except Exception as e:
        ck('F9 caught: a clone inheriting a player class lever', False, f'{e!r}')

    ck('F9 control: no clone leaks today',
       not check_clone_inheritance(_selftest_overlay_dir[0], weapons, enemy_ids,
                                   rules, out=lambda *a: None))

    # F8 a missing pointer file is a refusal, not "no enemies"
    try:
        load_pointer_set(os.path.join(os.sep, 'nonexistent-dir-for-selftest'))
        ck('F8 caught: a missing pointer file refuses', False)
    except Problem:
        ck('F8 caught: a missing pointer file refuses', True)

    return fails


# ---------------------------------------------------------------------------

def resolve_dirs(a):
    if a.game:
        cfg = os.path.join(a.game, 'BepInEx', 'config')
    elif a.config:
        cfg = a.config
    else:
        raise Problem('one of --game or --config is required')
    overlay = os.path.join(cfg, 'ckf.hardmode.d')
    dump = a.dump or os.path.join(repo_root(), 'sheets', 'raw')
    return cfg, overlay, dump


def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', help='the game root (…/Cyber Knights Flashpoint)')
    ap.add_argument('--config', help='a BepInEx/config directory')
    ap.add_argument('--dump', help='the dumped CSV directory (default sheets/raw)')
    ap.add_argument('--write', action='store_true', help='regenerate the sheet')
    ap.add_argument('--check', action='store_true',
                    help='compare the old rules and the new sheet element by element')
    ap.add_argument('--census', action='store_true', help='print the partition assertion')
    ap.add_argument('--selftest', action='store_true', help='inject faults')
    ap.add_argument('--ruleset-3x', dest='ruleset_3x', action='store_true',
                    help='ALSO run the retired old-vs-new comparison '
                         'against the 3.0 ruleset and the selftest cases '
                         'that fault it. Retired from the default suite '
                         '%s %s; what it prints is a divergence, which is '
                         'not by itself a defect.'
                         % (RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON))
    a = ap.parse_args()

    if not (a.write or a.check or a.census or a.selftest):
        ap.error('one of --write, --check, --census or --selftest is required')

    try:
        cfg, overlay, dump = resolve_dirs(a)
        weapons = load_weapons(dump)
        enemy_ids, monster_rows = load_pointer_set(overlay)
    except Problem as e:
        print(f'REFUSED  {e}')
        return 2

    print(f'gear_classes: {len(weapons)} WeaponModel row(s) from {dump}')
    print(f'gear_classes: {monster_rows} MonsterTypeModel row(s) from the enemy '
          f'overlay, {len(enemy_ids)} distinct WeaponTypeId value(s) -- the '
          f'post-overlay pointer set')

    problems = []
    sheet_path = os.path.join(overlay, SHEET_NAME)

    if a.write:
        text = render_sheet()
        with io.open(sheet_path, 'w', newline='', encoding='utf-8') as fh:
            fh.write(text)
        print(f'gear_classes: wrote {sheet_path} -- '
              f'{len(LEVER_CLASSES)} row(s), {len(SHEET_HEADER)} column(s), '
              f'{len(text.encode("utf-8"))} bytes, LF')

    if a.check or a.census:
        try:
            sheet = read_sheet(sheet_path)
        except Problem as e:
            print(f'REFUSED  {e}')
            return 2
        rep = []
        rules = expand(sheet, enemy_ids, report=rep)
        problems += rep
        print(f'gear_classes: {len(sheet)} sheet row(s) expanded into '
              f'{len(rules)} rule(s), '
              f'{sum(len(r.ops) for r in rules)} column write(s)')

        if a.census or a.check:
            problems += partition(weapons, enemy_ids, rules)
            problems += check_columns(weapons)
            problems += check_two_recoil_levers(enemy_ids)
            problems += check_clone_inheritance(overlay, weapons, enemy_ids, rules)
        if a.check:
            # THE OLD-vs-NEW COMPARISON IS RETIRED FROM HERE (David's rule).
            # See RULESET_3X_RETIRED_WHY. Recorded non-run on the
            # default path; runs in full under --ruleset-3x. Everything above
            # ran unconditionally.
            if a.ruleset_3x:
                print(f'    RUNNING the retired old-vs-new comparison because '
                      f'{RULESET_3X_RETIRED_FLAG} was passed. It was retired '
                      f'from the default --check by {RULESET_3X_RETIRED_BY}, '
                      f'{RULESET_3X_RETIRED_ON}. What follows is a DIVERGENCE '
                      f'REPORT against the 3.0 ruleset, not a defect list.')
                cmp_problems, _claimed = compare(weapons, rules)
                problems += cmp_problems
            else:
                problems += ruleset_3x_report_retired()

    if a.selftest:
        _selftest_overlay_dir[0] = overlay
        fails = selftest(weapons, enemy_ids, run_3x=a.ruleset_3x)
        problems += [f'selftest: {f}' for f in fails]

    for p in problems:
        print(f'PROBLEM  {p}')
    print(f'\n{len(problems)} problem(s).')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
