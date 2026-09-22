#!/usr/bin/env python3
"""cyberweapons.py -- the two cyberweapon lever sheets, and the split that
rests on them.

WHAT THESE FILES ARE

`ckf.hardmode.d/cyberweapons-lasers.csv` and `cyberweapons-claws.csv` are
LEVER SHEETS, not direct overlays. A direct overlay's filename names one game
table and its header names that table's columns. A cyberweapon row is not a row
of one table: `TalentModel.Weapon` holds the `WeaponId`, so the weapon's combat
stats and the talent that fires it are two rows in two tables and one player
concept. There are exactly 33 non-zero `Weapon` values in the whole 384-row
`TalentModel` and they are precisely the 33 cyberweapons, one talent per weapon
per tier. [measured, sheets/raw/TalentModel.csv + WeaponModel.csv; design.md
section 6] So ONE SHEET ROW BECOMES TWO RULES -- a `WeaponModel` rule and a
`TalentModel` rule -- and the expansion happens in the plugin at load
(`mods/CKFHardMode/Cyberweapons.cs`), never here and never in the GUI.
design.md section 1, "Why the mod expands, not the GUI", is settled: hand
editing a sheet with the game and the editor closed has to work, so nothing on
disk may be a compiled mirror of one.

This script does four things, none of which is "be the loader":

  --write     regenerate both sheets from the declarations below.
  --check     the column, row, join, shared-row, collision and plugin-map
              checks below, against the dump and the sheets on disk. With
              --ruleset-3x it also compares the sheets against the 3.x rules
              the sheets were converted from (a divergence report; see
              RULESET_3X_RETIRED_WHY).
  --census    the column and row assertions, printed whether or not they find
              a fault.
  --selftest  fault injection, with a control case first.

DOUBLE APPLICATION

A 3.x install that still carries ckf.hardmode.rules.json applies the 22
converted rules AND the sheets. All 22 carry `set` and nothing else -- no
`multiply`, no `add`, no `clampMin`, no `clampMax`, no `clone` -- so applying
them and the sheets in either order and any number of times lands on the same
number, and no `(model, id, column)` triple in the converted set is written
twice with two different values. [measured, and ASSERTED by
check_double_application() when a rules file is present.] Six of the 22 are
RANGE selectors (`whereMin`/`whereMax`), so the old side is resolved against
the dump (`old_effect()`) before the two sides can be compared.

WHAT IS NOT HERE

No player/enemy partition. `gear-classes.csv` needs one because a class
selector reaches every row of a class; these sheets select by exact
`WeaponId`/`TalentId`, so they reach the 33 rows they name and nothing else.
The partition question is still ASKED, once, repo-side: P4 below asserts that
no `MonsterTypeModel` row points at any of the 33, in either the shipped or
the post-overlay pointer set. It is repo-side ONLY, because players have no dumps and design.md
section 10 forbids runtime behaviour that depends on one.
"""

import argparse
import csv
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


# ---------------------------------------------------------------------------
# The adjustment grammar.
#
# A TRANSCRIPTION of mods/CKFHardMode/MissionRewards.cs, MissionRewards.Adjust.
# Parse -- the same grammar gui/serve.py's parse_adjust and
# scripts/gear_classes.py's parse_adjust transcribe. This is deliberately NOT a
# fifth case table: ADJUST_CASES_* are imported from gear_classes so that the
# two scripts cannot drift, and --selftest checks this parser against them.
#
# THREE-STATE, not two. Blank and unparseable are different answers.
# ---------------------------------------------------------------------------

import gear_classes as _gear                       # noqa: E402

parse_adjust = _gear.parse_adjust
NONE, SET, ADD, MULTIPLY = _gear.NONE, _gear.SET, _gear.ADD, _gear.MULTIPLY
Problem = _gear.Problem
read_csv_rows = _gear.read_csv_rows


# ---------------------------------------------------------------------------
# THE COLUMN MAP. This is the substance of the phase: one sheet column names
# one column of one game table, and the sheet's friendly name is not always the
# game's.
#
# THE ALIAS RULE. docs/gotchas.md is explicit that WeaponModel's unsuffixed
# Accuracy / PureDamage / PhysicalDamage / BallisticDamage / ActionPoints are
# read-only aliases for the selected firing mode: a write to one is taken and
# discarded with no diagnostic. design.md section 6 names the sheet columns
# without the suffix, which is the right name for a player-facing grid on rows
# that HAVE no second mode (`ModeType2` is -1 on all 33 [measured]), so the
# suffix is added HERE, in the map, and the emitted rule names PureDamage1 and
# never PureDamage. Asserted by check_columns(): every WeaponModel target must
# be a real dumped header column and must not itself be an alias.
#
# Each entry is sheetColumn -> (model, gameColumn).
# ---------------------------------------------------------------------------

WEAPON_MODEL = 'WeaponModel'
TALENT_MODEL = 'TalentModel'

LASER_MAP = [
    ('PowerLevel',           (WEAPON_MODEL, 'PowerLevel')),
    ('Rarity',               (WEAPON_MODEL, 'Rarity')),
    ('Cost',                 (WEAPON_MODEL, 'Cost')),
    ('Accuracy',             (WEAPON_MODEL, 'Accuracy1')),
    ('PureDamage',           (WEAPON_MODEL, 'PureDamage1')),
    ('BallisticDamage',      (WEAPON_MODEL, 'BallisticDamage1')),
    ('CritMultiBase',        (WEAPON_MODEL, 'CritMultiBase')),
    ('CritMultiStealth',     (WEAPON_MODEL, 'CritMultiStealth')),
    ('PrecisionRule',        (WEAPON_MODEL, 'PrecisionRule')),
    ('SpecialRule',          (WEAPON_MODEL, 'SpecialRule')),
    ('Range',                (TALENT_MODEL, 'Range')),
    ('ApCost',               (TALENT_MODEL, 'ApCost')),
    ('TargetEffect',         (TALENT_MODEL, 'TargetEffect')),
    ('TargetEffectDuration', (TALENT_MODEL, 'TargetEffectDuration')),
    ('SelfEffect',           (TALENT_MODEL, 'SelfEffect')),
]

CLAW_MAP = [
    ('PowerLevel',       (WEAPON_MODEL, 'PowerLevel')),
    ('Rarity',           (WEAPON_MODEL, 'Rarity')),
    ('Cost',             (WEAPON_MODEL, 'Cost')),
    ('Accuracy',         (WEAPON_MODEL, 'Accuracy1')),
    ('PureDamage',       (WEAPON_MODEL, 'PureDamage1')),
    ('PhysicalDamage',   (WEAPON_MODEL, 'PhysicalDamage1')),
    ('CritMultiBase',    (WEAPON_MODEL, 'CritMultiBase')),
    ('CritMultiStealth', (WEAPON_MODEL, 'CritMultiStealth')),
    ('MaxCharges',       (TALENT_MODEL, 'MaxCharges')),
]

# The three identity columns. WeaponId keys the WeaponModel rule and TalentId
# keys the TalentModel rule; WeaponName is there so the file reads in a
# spreadsheet without a second document. None of the three is a lever and a
# value in one is never an adjustment.
IDENTITY = ['WeaponName', 'WeaponId', 'TalentId']

# THE LASER SHEET IS 18 COLUMNS, NOT THE 16 design.md SECTION 6 LISTS. That
# list omits SpecialRule and ApCost, the two columns the 3.x laser rules wrote:
#
#   "PLAYER - CW / all sixteen optical-laser weapons (25000-25015) -
#   SpecialRule 3 'Rapid Fire' removed" set WeaponModel SpecialRule = 0 on 16
#   of the 17;
#   the two "CW / ... talent AP cost 2 -> 1" rules set TalentModel ApCost = 10
#   on 16 of the 17.
#
# Both columns are CONSTANT across the 17 shipped rows -- SpecialRule 3,
# ApCost 20 [measured] -- which is why the "no table shows a column dead for
# its own rows" requirement would drop them. That requirement is about columns
# that carry no lever; these two are levers, and a sheet without them could not
# express the converted configuration. The claw list of 12 matches design.md.
LASER_COLUMNS = IDENTITY + [c for c, _ in LASER_MAP]
CLAW_COLUMNS = IDENTITY + [c for c, _ in CLAW_MAP]

# Columns deliberately absent, recorded so they are not re-proposed. Every one
# was measured over the sheet's OWN rows in the dump; the reason is the
# measurement, not design.md's word for it.
LASER_EXCLUDED_COLUMNS = {
    'PhysicalDamage': 'PhysicalDamage1 is 0 on all 17 laser rows',
    'MaxRange':       'MaxRange is 0 on all 17; reach is the talent Range (6/12/16/18/24)',
    'RechargeTurns':  'TalentModel RechargeTurns is a constant 4 and no rule writes it',
    'MaxCharges':     'TalentModel MaxCharges is a constant 1 and no rule writes it',
    'MatrixEffect':   'TalentModel MatrixEffect is 0 on all 17',
    'RangeAoE':       'TalentModel RangeAoE is 0 on all 17',
    'ShotVolume':     'WeaponModel ShotVolume is 0 on all 17',
    'FAShots':        'WeaponModel FAShots is 0 on all 17',
    'RecoilRate1':    'WeaponModel RecoilRate1 is 0 on all 17',
    'RecoilRate2':    'WeaponModel RecoilRate2 is 0 on all 17 -- the 24000-30016 '
                      'sweep was a no-op here and Phase 5 established it',
    'ArmorCritRate1': 'WeaponModel ArmorCritRate1 is 0 on all 17',
    'ActionPoints':   'WeaponModel ActionPoints1 is a constant 20; the AP lever '
                      'that the mod actually pulls is the TALENT ApCost, which '
                      'is a column',
}
CLAW_EXCLUDED_COLUMNS = {
    'BallisticDamage':      'BallisticDamage1 is 0 on all 16 claw rows',
    'TargetEffect':         'TalentModel TargetEffect is 0 on all 16 claw talents',
    'TargetEffectDuration': 'TalentModel TargetEffectDuration is 0 on all 16',
    'SelfEffect':           'TalentModel SelfEffect is 0 on all 16',
    'MatrixEffect':         'TalentModel MatrixEffect is 0 on all 16, and no '
                            'ImplantClass 27 row carries an ImplantEffectId',
    'Range':                'TalentModel Range is a hard constant 2',
    'ApCost':               'TalentModel ApCost is a hard constant 10',
    'MaxRange':             'WeaponModel MaxRange is a constant 2',
    'PrecisionRule':        'WeaponModel PrecisionRule is a constant 1 and no '
                            'rule writes it',
    'SpecialRule':          'WeaponModel SpecialRule is a constant 0 and no rule '
                            'writes it -- unlike the lasers, where it is the '
                            'lever the mod pulls',
    'RechargeTurns':        'TalentModel RechargeTurns is a constant 2 and no '
                            'rule writes it',
}

# ---------------------------------------------------------------------------
# THE CELLS.
#
# Every one of these is a transcription of a 3.x rule the sheet replaced. The
# table is what --write renders both sheets from and the written record of the
# values the conversion landed on. It is NOT a statement about what the sheets
# on disk must hold: the sheets are for tuning, and a sheet that has moved away
# from this table is tuning, not a defect.
#
# READ THIS BEFORE RUNNING --write. --write regenerates both sheets FROM THIS
# TABLE and will therefore overwrite every cell that has been tuned on disk.
# --check does NOT read this table for the sheet contents; it reads the sheets
# off disk. Only --write and --selftest render from here.
#
# Three of the sixteen laser damage rules set a column to the value it already
# has -- 25000 PureDamage1 90, 25004 BallisticDamage1 150, 25008 PureDamage1
# 130 -- and their comments say so ("unchanged; stated for completeness"). They
# are kept as explicit `=` cells rather than blanked, so the compiled rule set
# is equal TERM FOR TERM and not merely equal in outcome.
# ---------------------------------------------------------------------------

LASER_CELLS = {
    # weapon id -> {sheet column: adjustment}
    25000: {'SpecialRule': '=0', 'PureDamage': '=90',       'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25001: {'SpecialRule': '=0', 'PureDamage': '=120',      'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25002: {'SpecialRule': '=0', 'PureDamage': '=150',      'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25003: {'SpecialRule': '=0', 'PureDamage': '=180',      'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25004: {'SpecialRule': '=0', 'BallisticDamage': '=150', 'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25005: {'SpecialRule': '=0', 'BallisticDamage': '=200', 'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25006: {'SpecialRule': '=0', 'BallisticDamage': '=250', 'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25007: {'SpecialRule': '=0', 'BallisticDamage': '=300', 'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25008: {'SpecialRule': '=0', 'PureDamage': '=130',      'ApCost': '=10'},
    25009: {'SpecialRule': '=0', 'PureDamage': '=170',      'ApCost': '=10'},
    25010: {'SpecialRule': '=0', 'PureDamage': '=210',      'ApCost': '=10'},
    25011: {'SpecialRule': '=0', 'PureDamage': '=250',      'ApCost': '=10'},
    25012: {'SpecialRule': '=0', 'BallisticDamage': '=180', 'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25013: {'SpecialRule': '=0', 'BallisticDamage': '=240', 'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25014: {'SpecialRule': '=0', 'BallisticDamage': '=300', 'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25015: {'SpecialRule': '=0', 'BallisticDamage': '=360', 'ApCost': '=10', 'TargetEffectDuration': '=2'},
    25016: {},
}

# CLAW ROWS ARE GENERATED BLANK. The conversion carried no claw override, so
# --write leaves every claw cell empty and the generated sheet emits NO RULE AT
# ALL. check_claws_blank() (P-BLANK) walks the rules the sheet on disk produces
# and refuses if it produced one, so a tuned claw cell turns --check red.
CLAW_CELLS = {}

# ---------------------------------------------------------------------------
# THE THREE GAPS design.md SECTION 6 SAYS THIS PHASE CLOSES BY CONSTRUCTION,
# written into the rows they belong to so they are visible in a spreadsheet.
#
# Free text, and deliberately NOT load-bearing: nothing parses these, which is
# the defect proposal.md section 1 names about the old `XX /` comment prefixes.
# Each one is a measurement, and each is asserted separately -- ROW_NOTES going
# stale cannot hide the fact, because the fact is checked somewhere else.
# ---------------------------------------------------------------------------

ROW_NOTES = {
    25008: 'GAP CLOSED: Photon Lance has NO target effect at all -- TargetEffect '
           'is 0 on talents 80031-80034 [measured] -- so TargetEffectDuration is '
           'blank here on purpose and is not an omission. The "CW / debuff '
           'duration 1 -> 2" rules cover Brightshot (80007-80010), Lumen Spear '
           '(80027-80030) and Helios (80035-80038) and deliberately skip these '
           'four.',
    25009: 'GAP CLOSED: see weapon 25008. No target effect; TargetEffectDuration '
           'blank on purpose.',
    25010: 'GAP CLOSED: see weapon 25008. No target effect; TargetEffectDuration '
           'blank on purpose.',
    25011: 'GAP CLOSED: see weapon 25008. No target effect; TargetEffectDuration '
           'blank on purpose.',
    25016: 'GAP CLOSED: Luem Trident is outside every current `CW /` id range, so '
           'it keeps SpecialRule 3 and talent ApCost 20 while its fifteen '
           'siblings do not. It has a row here whether the mod tunes it or not; '
           'as generated, every cell is blank. It is also the only '
           'cyberweapon with two non-zero damage columns -- PureDamage1 45 AND '
           'BallisticDamage1 180. [measured]',
}

# ---------------------------------------------------------------------------
# THE SHARED ROW.
#
# design.md section 11: a lever sheet can target a row another item also uses.
# Within these two sheets there is exactly ONE such row and it is in the laser
# sheet: `SelfEffect 2051` is talent 80030 (Lumen Spear 4, weapon 25007) AND
# talent 80060 (Luem Trident, weapon 25016). It is the only SelfEffect value
# shared by two talents anywhere in the 384-row table. [measured]
#
# DECLARED HERE AND CHECKED AGAINST THE DUMP, so it cannot go stale in silence:
# check_shared_rows() recomputes the sharing from sheets/raw/TalentModel.csv
# and refuses if this table and the dump disagree in either direction. A game
# update that makes a second pair share an effect is a problem here before it
# is a surprise in the editor.
#
# WHAT CAN AND CANNOT DIVERGE, stated plainly rather than implied.
#
#   The laser sheet's SelfEffect / TargetEffect cells are POINTERS. Writing one
#   REPOINTS that talent at a different EffectModel row; it does not change
#   what effect 2051 does, and the two owners can be repointed independently
#   with no interaction at all. That is per-row and safe.
#
#   What is shared is the PAYLOAD of effect 2051 -- an edit to what that effect
#   does reaches both owners. This sheet carries no EffectModel column, so it
#   cannot make that edit: the divergence refusal below is BUILT AND FAULT
#   EXERCISED, and has no live subject in this phase. Said plainly because an
#   instrument with no subject that reports nothing cannot be told from one
#   that is broken (AGENTS.md).
#
# NO CLONE IS EVER EMITTED AUTOMATICALLY. `_clone` is not a control column
# either sheet accepts; the plugin's expander REFUSES THE WHOLE FILE if it sees
# one, and so does read_sheet() here. RowClone.cs is the path that produces a
# mission that will not load, which Plugin.cs already calls "the mission-hang
# shape RowClone.cs describes". The per-row opt-in that section 11 describes is
# DECLARED BELOW AND UNEXERCISED: SHARED_ROW_SPLIT_OPTIN is empty, nothing
# reads it to emit anything, and the only code that looks at it is the
# assertion that it is empty.
# ---------------------------------------------------------------------------

# (model, column, id) -> the sheet rows that own it. (table, id), never id
# alone -- see KEYS_ARE_TABLE_AND_ID below.
SHARED_ROWS = {
    ('EffectModel', 2051): {
        'sheet': 'cyberweapons-lasers.csv',
        'pointer': ('TalentModel', 'SelfEffect'),
        'owners': [(25007, 80030, 'Lumen Spear PL5'),
                   (25016, 80060, 'Luem Trident')],
        'note': ('EffectModel 2051 is the self effect of both. An edit to what '
                 'that effect does reaches both; repointing either row\'s '
                 'SelfEffect cell does not.'),
    },
}

# design.md section 11's per-row opt-in. Empty, and the expander emits no clone
# under any circumstances. Kept so that "there is no opt-in" and "the opt-in is
# empty" stay different statements.
SHARED_ROW_SPLIT_OPTIN = {}

# ---------------------------------------------------------------------------
# KEYS ARE (table, id), NEVER id ALONE.
#
# design.md section 11 names two collisions. Both reproduce, and a third,
# larger fact came out of the same measurement and is recorded because it is
# the one that makes the rule non-negotiable rather than fussy.
#
#   50000 and 50001 are EffectModel.EffectId values AND
#   MatrixEffectModel.MatrixEffectId values. [measured]
#   TalentModel.TalentId 80000-80062 (63 ids) overlaps
#   EffectModel.EffectId 80000-80018 (19 ids). [measured]
#   And table-wide: 221 ids are both a TalentId and an EffectId, and 130 are
#   both an EffectId and a MatrixEffectId. [measured] The named pairs are
#   examples of a collision that is everywhere, not three special cases.
#
# It bites here specifically: this sheet's talent ids are 80003-80010,
# 80015-80038 and 80060, and EffectModel carries rows 80000-80018. A registry
# keyed on id alone would report the laser sheet's TalentModel 80007 as
# colliding with the slot-8 implant table's EffectModel 80007 in Phase 7, and
# would show one row's value on the other's edit in a GUI.
#
# Every key in this file, in mods/CKFHardMode/Cyberweapons.cs and in the
# validate_rules.py hook is a (model, id) tuple. --selftest has one case per
# declared pair proving that an id-alone key collapses them and the (table, id)
# key does not.
# ---------------------------------------------------------------------------

COLLISION_CASES = [
    {
        'id': 'C1',
        'left': ('EffectModel', 'EffectId', 50000),
        'right': ('MatrixEffectModel', 'MatrixEffectId', 50000),
        'why': 'design.md section 11, first named pair',
    },
    {
        'id': 'C2',
        'left': ('EffectModel', 'EffectId', 50001),
        'right': ('MatrixEffectModel', 'MatrixEffectId', 50001),
        'why': 'design.md section 11, first named pair',
    },
    {
        'id': 'C4',
        'left': ('WeaponModel', 'WeaponId', 25000),
        'right': ('MonsterTypeModel', 'MonsterTypeId', 25000),
        'why': ('NOT in design.md section 11, and it is the sharpest of the four '
                'because it lands on a row THIS SHEET WRITES. WeaponId 25000 is '
                'Brightshot Optic PL2, the laser sheet\'s first row; '
                'MonsterTypeId 25000 is a monster. 137 ids are both a '
                'MonsterTypeId and a WeaponId, and 48 are both a MonsterTypeId '
                'and a TalentId. [measured] A registry keyed on the number alone '
                'would have this sheet colliding with the enemy-gear overlay on '
                'its own first line.'),
    },
    {
        'id': 'C3',
        'left': ('TalentModel', 'TalentId', 80007),
        'right': ('EffectModel', 'EffectId', 80007),
        'why': ('design.md section 11, second named pair. 80007 is chosen from '
                'the 80000-80018 overlap because it is ALSO a row of the laser '
                'sheet -- Brightshot Optic 1 -- so this case is about a key '
                'this phase actually emits, not a hypothetical one.'),
    },
]


# ---------------------------------------------------------------------------
# Sheet declarations
# ---------------------------------------------------------------------------

class Sheet(object):
    """`columns` and `header` are DERIVED from `order`, never stored beside it.
    They were stored beside it for one revision and --selftest's "drop a column"
    faults produced a header one wider than the rows, so every later cell read
    one column to the left and the fault that was supposed to be caught was
    masked by a different one. A shape that cannot disagree with itself is
    cheaper than an assertion that they agree."""

    def __init__(self, key, name, cls, colmap, cells, excluded, slice_key,
                 blank):
        self.key = key
        self.name = name
        self.cls = cls                 # WeaponClass
        self.map = dict(colmap)
        self.order = [c for c, _ in colmap]
        self.cells = cells
        self.excluded = excluded
        self.slice_key = slice_key
        self.blank = blank             # True: this sheet must emit no rule

    @property
    def columns(self):
        return IDENTITY + list(self.order)

    @property
    def header(self):
        return self.columns + ['_comment']


LASERS = Sheet('lasers', 'cyberweapons-lasers.csv', 17,
               LASER_MAP, LASER_CELLS, LASER_EXCLUDED_COLUMNS,
               'CyberweaponsLasers', blank=False)
CLAWS = Sheet('claws', 'cyberweapons-claws.csv', 16,
              CLAW_MAP, CLAW_CELLS, CLAW_EXCLUDED_COLUMNS,
              'CyberweaponsClaws', blank=True)
SHEETS = [LASERS, CLAWS]
SHEET_NAMES = {s.name for s in SHEETS}

CONTROL_PREFIX = '_'
# The one control column these sheets accept. `_clone` is REFUSED, by name, in
# both this reader and the plugin's -- see THE SHARED ROW above.
ALLOWED_CONTROL = {'_comment'}
REFUSED_CONTROL = {
    '_clone': ('a clone is never emitted from a lever sheet. RowClone.cs is the '
               'path that produces a mission that will not load, and design.md '
               'section 11 makes splitting a shared row an explicit per-row '
               'opt-in that this dialect does not carry.'),
    '_serveOn': ('serveOn belongs to a clone rule; these sheets emit none.'),
}

WEAPON_ID = 'WeaponId'
TALENT_ID = 'TalentId'
WEAPON_KEY = 'WeaponId'
TALENT_KEY = 'TalentId'
CLASS_COLUMN = 'WeaponClass'
TALENT_WEAPON_COLUMN = 'Weapon'
POINTER_FILE = 'MonsterTypeModel.csv'
POINTER_COLUMN = 'WeaponTypeId'

# The 22 rules this phase converts, identified the way Phase 4 identified
# them -- by what they select and write, not by their comment text. An
# anchored `CW /` prefix is how the five talent rules were routed in Phase 4;
# the 17 weapon rules carry `CW /` MID-comment behind a `PLAYER - ` prefix, and
# Phase 4 recorded that trap. So neither is matched on text here.
CONVERTED_MODELS = (WEAPON_MODEL, TALENT_MODEL)


# ---------------------------------------------------------------------------
# ckf.hardmode.rules.json IS NOT PART OF THE 4.0 LAYOUT, AND THAT IS DECLARED
# HERE RATHER THAN DISCOVERED BY A REFUSAL THAT THROWS AWAY THE REST OF THE RUN
#
# load_rules_json() raises Problem when the file is absent. That refusal is
# right about its own subject -- an old side that does not exist cannot be
# compiled -- but none of the other checks here needs the file, so the state
# is declared instead of raised:
#
#   "gone"    the 4.0 layout.  Absent is correct; PRESENT is the surprise, and
#             it is reported as a problem -- a plugin that reads that file
#             applies it BEFORE every overlay and every lever sheet, so a rule
#             in it lands on top of the sheet that replaced it.
#   "present" the 3.x layout.  Absent is the surprise.
#
# Either way the state is PRINTED on every run, with (expected, found) beside
# it.  A run that cannot say which layout it read has not agreed with anything.
RULES_FILE = 'ckf.hardmode.rules.json'
RULES_FILE_EXPECTED = 'gone'

# THE SIXTY TRIPLES THE 3.x RULES FILE CARRIED FOR THESE TWO TABLES
# [measured: old_effect() over the 22 converted rules -- 16 exact selectors and
# 6 range selectors -- resolved against the dumped WeaponModel and TalentModel
# into 60 (model, id, column) writes, every one a `set`]. 22 is a rule count;
# 60 is what those rules wrote.
#
# This is the OLD SIDE of --ruleset-3x when no rules file is present. It cannot
# move when the sheets move, which is the point: compared against an EMPTY old
# side, every triple would come from the new side alone, be compared against
# itself, and print "0 value(s) differ" -- green over nothing.
DECLARED_LAST_RULES_TRIPLES = [
    ((TALENT_MODEL, 80007, 'ApCost'), 10.0),                  # Brightshot Optic 1
    ((TALENT_MODEL, 80007, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80008, 'ApCost'), 10.0),                  # Brightshot Optic 2
    ((TALENT_MODEL, 80008, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80009, 'ApCost'), 10.0),                  # Brightshot Optic 3
    ((TALENT_MODEL, 80009, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80010, 'ApCost'), 10.0),                  # Brightshot Optic 4
    ((TALENT_MODEL, 80010, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80027, 'ApCost'), 10.0),                  # Lumen Spear 1
    ((TALENT_MODEL, 80027, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80028, 'ApCost'), 10.0),                  # Lumen Spear 2
    ((TALENT_MODEL, 80028, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80029, 'ApCost'), 10.0),                  # Lumen Spear 3
    ((TALENT_MODEL, 80029, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80030, 'ApCost'), 10.0),                  # Lumen Spear 4
    ((TALENT_MODEL, 80030, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80031, 'ApCost'), 10.0),                  # Photon Lance 1
    ((TALENT_MODEL, 80032, 'ApCost'), 10.0),                  # Photon Lance 2
    ((TALENT_MODEL, 80033, 'ApCost'), 10.0),                  # Photon Lance 3
    ((TALENT_MODEL, 80034, 'ApCost'), 10.0),                  # Photon Lance 4
    ((TALENT_MODEL, 80035, 'ApCost'), 10.0),                  # Helios Beam 1
    ((TALENT_MODEL, 80035, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80036, 'ApCost'), 10.0),                  # Helios Beam 2
    ((TALENT_MODEL, 80036, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80037, 'ApCost'), 10.0),                  # Helios Beam 3
    ((TALENT_MODEL, 80037, 'TargetEffectDuration'), 2.0),
    ((TALENT_MODEL, 80038, 'ApCost'), 10.0),                  # Helios Beam 4
    ((TALENT_MODEL, 80038, 'TargetEffectDuration'), 2.0),
    # The four Photon Lance talents (80031-80034) carry ApCost and NO
    # TargetEffectDuration, and that asymmetry is the file's, not a
    # transcription slip: the 80027-80038 ApCost rule is one range and the
    # TargetEffectDuration rules are two -- 80027-80030 and 80035-80038 --
    # with the Lance block deliberately outside both [measured].
    ((WEAPON_MODEL, 25000, 'PureDamage1'), 90.0),             # Brightshot Optic PL2
    ((WEAPON_MODEL, 25000, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25001, 'PureDamage1'), 120.0),            # Brightshot Optic PL3
    ((WEAPON_MODEL, 25001, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25002, 'PureDamage1'), 150.0),            # Brightshot Optic PL4
    ((WEAPON_MODEL, 25002, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25003, 'PureDamage1'), 180.0),            # Brightshot Optic PL5
    ((WEAPON_MODEL, 25003, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25004, 'BallisticDamage1'), 150.0),       # Lumen Spear PL2
    ((WEAPON_MODEL, 25004, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25005, 'BallisticDamage1'), 200.0),       # Lumen Spear PL3
    ((WEAPON_MODEL, 25005, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25006, 'BallisticDamage1'), 250.0),       # Lumen Spear PL4
    ((WEAPON_MODEL, 25006, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25007, 'BallisticDamage1'), 300.0),       # Lumen Spear PL5
    ((WEAPON_MODEL, 25007, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25008, 'PureDamage1'), 130.0),            # Photon Lance PL2
    ((WEAPON_MODEL, 25008, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25009, 'PureDamage1'), 170.0),            # Photon Lance PL3
    ((WEAPON_MODEL, 25009, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25010, 'PureDamage1'), 210.0),            # Photon Lance PL4
    ((WEAPON_MODEL, 25010, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25011, 'PureDamage1'), 250.0),            # Photon Lance PL5
    ((WEAPON_MODEL, 25011, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25012, 'BallisticDamage1'), 180.0),       # Helios Beam PL2
    ((WEAPON_MODEL, 25012, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25013, 'BallisticDamage1'), 240.0),       # Helios Beam PL3
    ((WEAPON_MODEL, 25013, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25014, 'BallisticDamage1'), 300.0),       # Helios Beam PL4
    ((WEAPON_MODEL, 25014, 'SpecialRule'), 0.0),
    ((WEAPON_MODEL, 25015, 'BallisticDamage1'), 360.0),       # Helios Beam PL5
    ((WEAPON_MODEL, 25015, 'SpecialRule'), 0.0),
]

# What DOUBLE-APPLICATION last measured against a 3.x rules file [measured].
# Recorded so the NOT-RUN line can say what it is not re-running,
# by number. It is NOT asserted against anything: there is no second
# application to measure once the file is gone, and a check with no subject is
# recorded as a non-run, never counted as a pass.
DECLARED_LAST_DOUBLE_APPLICATION = {
    'rules_in_file': 269, 'converted': 22, 'exact': 16, 'ranges': 6,
    'carry_set': 22, 'carry_banned': 0,
}


class RulesFileState(object):
    """(expected, found) for ckf.hardmode.rules.json, and what follows.

    Modelled on implants.py's LiveRules, which hit this first. The point is
    that absence is a STATE with a name rather than a branch nobody sees: a
    silent `if os.path.exists` is how a script ends up carrying on with a
    smaller view of what writes.
    """

    def __init__(self, rules_path, expected=None):
        self.rules_path = rules_path
        self.expected = RULES_FILE_EXPECTED if expected is None else expected
        self.found = os.path.isfile(rules_path)
        self.surprise = ((self.found and self.expected == 'gone')
                         or (not self.found and self.expected == 'present'))

    def state_line(self):
        if self.found:
            return (f'    RULES-FILE: {RULES_FILE} is PRESENT (expected '
                    f'{self.expected}) -- compiled as the OLD side of --check.')
        return (f'    RULES-FILE: {RULES_FILE} is NOT ON DISK (expected '
                f'{self.expected}) -- not part of the 4.0 layout. The OLD side of '
                f'--check is the {len(DECLARED_LAST_RULES_TRIPLES)} triples '
                f'transcribed into DECLARED_LAST_RULES_TRIPLES, '
                f'not an empty dict -- and that comparison is '
                f'RETIRED from --check ({RULESET_3X_RETIRED_BY}, '
                f'{RULESET_3X_RETIRED_ON}, run it with '
                f'{RULESET_3X_RETIRED_FLAG}); DOUBLE-APPLICATION is NOT RUN '
                f'and says so below.')

    def surprise_problem(self):
        if not self.surprise:
            return None
        if self.found:
            return (f'RULES-FILE: {self.rules_path} is ON DISK and '
                    f'RULES_FILE_EXPECTED is {self.expected!r}. It is not part '
                    f'of the 4.0 layout; a plugin that reads it applies it BEFORE '
                    f'every overlay and every lever sheet, so any rule in it lands on '
                    f'top of the sheet that replaced it and DOUBLE-APPLICATION '
                    f'is live again. Either it came back by accident and should '
                    f'go, or the deletion was reverted and RULES_FILE_EXPECTED '
                    f'should say so.')
        return (f'RULES-FILE: {self.rules_path} is NOT on disk and '
                f'RULES_FILE_EXPECTED is {self.expected!r}. The old side of '
                f'--check cannot be compiled and a green run would mean COULD '
                f'NOT LOOK, not agreement.')


# ---------------------------------------------------------------------------
# Reading the world
# ---------------------------------------------------------------------------

_COMMENT_RE = re.compile(r'^\s*//')


def load_rules_json(path):
    """The rules file, with // comments and trailing commas stripped. A
    transcription of what ModelRules' reader tolerates."""
    if not os.path.isfile(path):
        raise Problem(f'ckf.hardmode.rules.json is not on disk at {path}. This '
                      f'is a refusal, not an empty answer: the OLD side of '
                      f'--check cannot be compiled without it.')
    with io.open(path, encoding='utf-8') as fh:
        src = fh.read()
    out, i, n, instr, esc = [], 0, len(src), False, False
    while i < n:
        c = src[i]
        if instr:
            out.append(c)
            if esc:
                esc = False
            elif c == '\\':
                esc = True
            elif c == '"':
                instr = False
            i += 1
            continue
        if c == '"':
            instr = True
            out.append(c)
            i += 1
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '/':
            while i < n and src[i] != '\n':
                i += 1
            continue
        if c == '/' and i + 1 < n and src[i + 1] == '*':
            i += 2
            while i + 1 < n and not (src[i] == '*' and src[i + 1] == '/'):
                i += 1
            i += 2
            continue
        out.append(c)
        i += 1
    text = re.sub(r',(\s*[}\]])', r'\1', ''.join(out))
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise Problem(f'{path} did not parse after comment stripping: {e}')
    rules = doc['rules'] if isinstance(doc, dict) else doc
    return rules


def load_table(dump_dir, filename, key, what):
    rows = read_csv_rows(os.path.join(dump_dir, filename), what)
    out = {}
    for r in rows:
        try:
            out[int(r[key])] = r
        except (KeyError, ValueError) as e:
            raise Problem(f'{filename} row {r!r} has no readable {key}: {e}')
    if len(out) != len(rows):
        raise Problem(f'{filename} has {len(rows)} rows but only {len(out)} '
                      f'distinct {key} values.')
    return out


def cyber_rows(weapons, talents):
    """-> (by_sheet, pairs). pairs maps WeaponId -> TalentId for all 33.

    The join is `TalentModel.Weapon`, read from the dump. Nothing here is a
    hand list of ids: a cyberweapon the game ships tomorrow appears because
    WeaponClass 16/17 and a talent pointing at it appear, not because someone
    added a line.
    """
    by_weapon = {}
    for tid, t in talents.items():
        v = (t.get(TALENT_WEAPON_COLUMN) or '').strip()
        if not v or v == '0':
            continue
        by_weapon.setdefault(int(v), []).append(tid)
    by_sheet, pairs, problems = {s.key: [] for s in SHEETS}, {}, []
    for wid, w in sorted(weapons.items()):
        try:
            cls = int(w[CLASS_COLUMN])
        except (KeyError, ValueError):
            continue
        sheet = next((s for s in SHEETS if s.cls == cls), None)
        if sheet is None:
            continue
        tids = by_weapon.get(wid, [])
        if len(tids) != 1:
            problems.append(f'{WEAPON_KEY} {wid} ({w.get("WeaponName")!r}, class '
                            f'{cls}) is pointed at by {len(tids)} talent(s) '
                            f'{sorted(tids)}; design.md section 6 says one talent '
                            f'per weapon per tier. The sheet cannot split a row '
                            f'whose other half is ambiguous.')
            continue
        pairs[wid] = tids[0]
        by_sheet[sheet.key].append((wid, tids[0]))
    return by_sheet, pairs, problems


# ---------------------------------------------------------------------------
# The sheets
# ---------------------------------------------------------------------------

def _shipped_comment(sheet, w, t):
    """The row's shipped values, so the file reads in a spreadsheet without a
    second document. FREE TEXT AND NOT LOAD-BEARING: nothing parses this, which
    is the defect proposal.md section 1 names about the old `XX /` prefixes."""
    bits = []
    for col in sheet.order:
        model, gcol = sheet.map[col]
        src = w if model == WEAPON_MODEL else t
        v = (src.get(gcol) or '').strip()
        bits.append(f'{col} {v}')
    head = f'{w.get("WeaponName", "")} PL{w.get("PowerLevel", "")}'
    extra = ''
    for (m, rid), sr in sorted(SHARED_ROWS.items()):
        if sr['sheet'] != sheet.name:
            continue
        owners = [o for o in sr['owners'] if o[0] == int(w[WEAPON_KEY])]
        if not owners:
            continue
        others = [o for o in sr['owners'] if o[0] != int(w[WEAPON_KEY])]
        extra = (f'. SHARED: {m} {rid} via {sr["pointer"][1]} is also '
                 + ' and '.join(f'{o[2]} (weapon {o[0]}, talent {o[1]})'
                                for o in others)
                 + "'s. " + sr['note'])
    note = ROW_NOTES.get(int(w[WEAPON_KEY]), '')
    return (f'{head}. Shipped: ' + '; '.join(bits) + '.' + extra
            + (' ' + note if note else ''))


def render_sheet(sheet, weapons, talents, rows):
    buf = io.StringIO(newline='')
    wtr = csv.writer(buf, lineterminator='\n')
    wtr.writerow(sheet.header)
    for wid, tid in rows:
        w, t = weapons[wid], talents[tid]
        cells = sheet.cells.get(wid, {})
        line = [w.get('WeaponName', ''), wid, tid]
        line += [cells.get(c, '') for c in sheet.order]
        line.append(_shipped_comment(sheet, w, t))
        wtr.writerow(line)
    return buf.getvalue()


def read_sheet(sheet, path):
    rows = read_csv_rows(path, f'the {sheet.key} lever sheet')
    hdr = list(rows[0].keys())
    for bad, why in REFUSED_CONTROL.items():
        if bad in hdr:
            raise Problem(f'{path} header carries the control column {bad!r}, '
                          f'which this dialect REFUSES: {why} The whole file is '
                          f'refused rather than the column ignored.')
    if hdr != sheet.header:
        raise Problem(f'{path} header is {hdr!r}; expected {sheet.header!r}. '
                      f'Regenerate it with --write.')
    return rows


# ---------------------------------------------------------------------------
# The expander -- a transcription of Cyberweapons.Expand, deliberately
# independent of it. Phase 4's lesson: the thing that checks the writer must
# not be the writer.
# ---------------------------------------------------------------------------

class Rule(object):
    """One emitted rule: one model, one exact id, a list of (kind, column,
    value) in set/multiply/add order."""

    def __init__(self, sheet, model, key, rid):
        self.sheet = sheet
        self.model = model
        self.key = key
        self.rid = rid
        self.ops = []

    @property
    def table_id(self):
        """(table, id). NEVER id alone -- see KEYS_ARE_TABLE_AND_ID."""
        return (self.model, self.rid)

    def __repr__(self):
        return f'<Rule {self.model} {self.key}={self.rid} ops={self.ops}>'


OP_ORDER = [SET, MULTIPLY, ADD]


def expand(sheet, sheet_rows, report=None):
    """One sheet row becomes up to two rules. Returns the rules in file order,
    weapon rule before talent rule for each row.

    FAIL-CLOSED, in the same places the plugin fails closed: a row whose
    WeaponId or TalentId does not parse produces NO rule and is named; a cell
    the grammar rejects is named with sheet, row and column and does not become
    a silent no-op; and a (model, id) key claimed twice is refused rather than
    applied twice in load order.
    """
    rules, refusals = [], []
    claimed = {}
    for n, row in enumerate(sheet_rows, start=2):     # 2 = first data line
        try:
            wid = int((row.get(WEAPON_ID) or '').strip())
            tid = int((row.get(TALENT_ID) or '').strip())
        except (TypeError, ValueError):
            refusals.append(f'{sheet.name}:{n}: {WEAPON_ID}='
                            f'{row.get(WEAPON_ID)!r} / {TALENT_ID}='
                            f'{row.get(TALENT_ID)!r} is not a pair of integer '
                            f'ids; the whole row is skipped, both halves of it.')
            continue
        by_model = {}
        for col in sheet.order:
            kind, val, ok = parse_adjust(row.get(col, ''))
            if not ok:
                refusals.append(f'{sheet.name}:{n}: weapon {wid}, column {col}: '
                                f'{row.get(col)!r} is not an adjustment '
                                f'(expected blank, =N, +N, -N or xN)')
                continue
            if kind == NONE:
                continue
            model, gcol = sheet.map[col]
            by_model.setdefault(model, {}).setdefault(kind, []).append((gcol, val))
        for model, key, rid in ((WEAPON_MODEL, WEAPON_KEY, wid),
                                (TALENT_MODEL, TALENT_KEY, tid)):
            found = by_model.get(model)
            if not found:
                continue
            if (model, rid) in claimed:
                refusals.append(f'{sheet.name}:{n}: ({model}, {rid}) is already '
                                f'written by line {claimed[(model, rid)]}. One '
                                f'row, one key -- two rows writing one key is '
                                f'load order, not a merge.')
                continue
            claimed[(model, rid)] = n
            r = Rule(sheet, model, key, rid)
            for kind in OP_ORDER:
                for gcol, val in found.get(kind, []):
                    r.ops.append((kind, gcol, val))
            rules.append(r)
    if refusals and report is not None:
        report.extend(refusals)
    elif refusals:
        raise Problem('; '.join(refusals))
    return rules


# ---------------------------------------------------------------------------
# The assertions
# ---------------------------------------------------------------------------

def check_columns(sheet, weapons, talents, rows, out=print):
    """P-COL. Every mapped column is a real column of its table, is not an
    unsuffixed alias, and is live for THIS sheet's own rows -- with the two
    named exceptions, which are live because the mod writes them."""
    problems = []
    wcols = set(next(iter(weapons.values())).keys())
    tcols = set(next(iter(talents.values())).keys())
    written = written_columns(sheet)
    for col in sheet.order:
        model, gcol = sheet.map[col]
        have = wcols if model == WEAPON_MODEL else tcols
        if gcol not in have:
            problems.append(f'P-COL {sheet.name}: {col} maps to {model}.{gcol}, '
                            f'which is not in the dumped {model} header.')
            continue
        if model == WEAPON_MODEL and gcol + '1' in wcols and gcol + '2' in wcols:
            problems.append(f'P-COL {sheet.name}: {col} maps to {model}.{gcol}, '
                            f'which is an UNSUFFIXED ALIAS for the selected '
                            f'firing mode. A write to it is taken and discarded '
                            f'with no diagnostic (docs/gotchas.md). Map it to '
                            f'{gcol}1.')
        src = weapons if model == WEAPON_MODEL else talents
        idx = 0 if model == WEAPON_MODEL else 1
        vals = {(src[p[idx]].get(gcol) or '').strip() for p in rows}
        if len(vals) <= 1 and gcol not in written:
            problems.append(f'P-COL {sheet.name}: {col} ({model}.{gcol}) is '
                            f'constant {vals} across all {len(rows)} of this '
                            f'sheet\'s own rows and no rule writes it. The '
                            f'lever-sheets spec says no table shows a column '
                            f'dead for its own rows.')
    for col in sheet.excluded:
        if col in sheet.columns:
            problems.append(f'P-COL {sheet.name}: {col} is in the excluded table '
                            f'AND in the header. One or the other.')
    out(f'    P-COL {sheet.name}: {len(sheet.order)} lever column(s) checked '
        f'against the {len(wcols)}-column WeaponModel and {len(tcols)}-column '
        f'TalentModel headers; {len(sheet.excluded)} column(s) excluded by name '
        f'with a reason.')
    return problems


def written_columns(sheet):
    """The game columns this sheet's cells actually write. Two of the laser
    columns -- SpecialRule and ApCost -- are constant across the shipped rows
    and are columns ONLY because the mod writes them; this is what lets P-COL
    tell those from a genuinely dead column."""
    out = set()
    for cells in sheet.cells.values():
        for col in cells:
            out.add(sheet.map[col][1])
    return out


def check_claws_blank(rules, out=print):
    """P-BLANK. The claw sheet produces no rule at all, asserted over the
    GENERATED RULES rather than by looking at the file."""
    mine = [r for r in rules if r.sheet is CLAWS]
    problems = []
    if mine:
        problems.append(
            f'P-BLANK {CLAWS.name}: produced {len(mine)} rule(s) '
            f'({[ (r.model, r.rid, r.ops) for r in mine[:3] ]}). All 16 claws '
            f'and all 16 claw talents are untouched by the mod today and a '
            f'shipped override would be a balance change proposal.md\'s '
            f'non-goals forbid.')
    out(f'    P-BLANK {CLAWS.name}: {len(mine)} rule(s) produced '
        f'(expected 0), from {len(CLAWS.cells)} declared cell row(s) '
        f'(expected 0).')
    return problems


def check_claw_rows_present(rows, weapons, talents, out=print):
    """P-ROWS. Blank does not mean absent: all 16 claw rows are in the file and
    every one of them carries its shipped values where a reader can see them."""
    problems = []
    if len(rows) != 16:
        problems.append(f'P-ROWS {CLAWS.name}: {len(rows)} row(s), expected 16.')
    for wid, tid in rows:
        if wid not in weapons or tid not in talents:
            problems.append(f'P-ROWS {CLAWS.name}: ({wid}, {tid}) is not a '
                            f'(WeaponModel, TalentModel) pair in the dump.')
    out(f'    P-ROWS {CLAWS.name}: {len(rows)} row(s) present with shipped '
        f'values and no override.')
    return problems


def _effect_owners(talents, scope=None):
    """EffectModel row -> the set of TALENTS that point at it.

    TWO OWNERS MEANS TWO TALENTS, not two pointer columns. A talent whose
    SelfEffect and TargetEffect are the same id has one owner and cannot
    diverge from itself; counting (talent, column) pairs instead of talents
    reported five such rows as shared on this instrument's first run. The count
    it prints now is the count it claims.
    """
    owners = {}
    for tid, t in talents.items():
        if scope is not None and tid not in scope:
            continue
        for pcol in ('SelfEffect', 'TargetEffect'):
            v = (t.get(pcol) or '').strip()
            if not v or v == '0':
                continue
            owners.setdefault(('EffectModel', int(v)), set()).add(tid)
    return owners


def check_shared_rows(talents, scope, out=print):
    """P-SHARED. The declared shared rows equal what the dump says, in both
    directions, and the split opt-in is empty.

    SCOPED TO THE SHEETS' OWN 33 TALENTS, and the table-wide number is printed
    beside it rather than folded in: a row two CONSUMABLE talents share is real
    and is Phase 8's subject, and an instrument that blocks this phase on it
    would be measuring something other than what it claims.
    """
    problems = []
    measured = {k: sorted(v) for k, v in _effect_owners(talents, scope).items()
                if len(v) > 1}
    wide = {k: sorted(v) for k, v in _effect_owners(talents).items() if len(v) > 1}
    declared = set(SHARED_ROWS)
    for k in sorted(measured):
        if k not in declared:
            problems.append(f'P-SHARED: {k[0]} {k[1]} is referenced by '
                            f'{len(measured[k])} talents {measured[k]} and is '
                            f'NOT in SHARED_ROWS. A shared row nothing marks is '
                            f'a divergent edit waiting to happen.')
    for k in sorted(declared):
        if k not in measured:
            problems.append(f'P-SHARED: SHARED_ROWS declares {k[0]} {k[1]} as '
                            f'shared and the dump says {len(measured.get(k, []))} '
                            f'of this sheet\'s talents point at it. The '
                            f'declaration is stale.')
        else:
            want = {o[1] for o in SHARED_ROWS[k]['owners']}
            have = set(measured[k])
            if want != have:
                problems.append(f'P-SHARED: {k[0]} {k[1]} owners declared {sorted(want)} '
                                f'but measured {sorted(have)}.')
    if SHARED_ROW_SPLIT_OPTIN:
        problems.append(f'P-SHARED: SHARED_ROW_SPLIT_OPTIN is not empty '
                        f'({sorted(SHARED_ROW_SPLIT_OPTIN)}). No clone is ever '
                        f'emitted automatically and nothing in this change has '
                        f'opted a row in.')
    out(f'    P-SHARED: over these sheets\' {len(scope)} talent(s), '
        f'{len(measured)} effect row(s) have more than one owning talent and '
        f'{len(declared)} are declared, agreeing'
        + (': ' + '; '.join(f'{k[0]} {k[1]} <- talents {v}'
                            for k, v in sorted(measured.items())) if measured else '')
        + f'. Table-wide the same measurement finds {len(wide)} '
        + '(' + '; '.join(f'{k[1]}<-{v}' for k, v in sorted(wide.items())) + ')'
        + ' -- the others are outside this phase and are NOT graded here. '
        f'Split opt-in is '
        f'{"EMPTY -- declared and unexercised" if not SHARED_ROW_SPLIT_OPTIN else "NOT EMPTY"}.')
    return problems


def check_divergent_shared_edits(rules, out=print):
    """P-DIVERGE. Two owners of one shared row given different values for the
    same column is refused, naming both owners.

    NO LIVE SUBJECT IN THIS PHASE, and that is said rather than left as a
    silent zero: neither sheet carries an EffectModel column, so no rule here
    can write a shared row's payload at all. The check exists so that the
    refusal is in place before a payload column is, and --selftest exercises it
    by injecting one.
    """
    problems = []
    by_row = {}
    for r in rules:
        for _kind, gcol, val in r.ops:
            if r.model in ('EffectModel', 'MatrixEffectModel'):
                by_row.setdefault((r.model, r.rid, gcol), set()).add(val)
    subject = 0
    for (model, rid, gcol), vals in sorted(by_row.items()):
        sr = SHARED_ROWS.get((model, rid))
        if not sr:
            continue
        subject += 1
        if len(vals) > 1:
            owners = ' and '.join(f'{o[2]} (weapon {o[0]}, talent {o[1]})'
                                  for o in sr['owners'])
            problems.append(f'P-DIVERGE: {model} {rid}.{gcol} is given '
                            f'{sorted(vals)} by two owners of the same row -- '
                            f'{owners}. One row cannot be edited two ways. '
                            f'Opt the row into splitting, or give both owners '
                            f'the same value.')
    out(f'    P-DIVERGE: {subject} write(s) to a declared shared row in the '
        f'generated rules. 0 is the expected answer this phase -- neither sheet '
        f'carries an EffectModel column, so the refusal is BUILT AND FAULT '
        f'EXERCISED with no live subject.')
    return problems


def check_no_clone(rules, sheets_text, out=print):
    """P-CLONE. No clone, ever, automatically."""
    problems = []
    for name, text in sorted(sheets_text.items()):
        hdr = text.split('\n', 1)[0]
        for bad in REFUSED_CONTROL:
            if bad in hdr.split(','):
                problems.append(f'P-CLONE {name}: header carries {bad!r}.')
    out(f'    P-CLONE: {len(sheets_text)} sheet(s) carry no clone control '
        f'column and the expander emits no clone rule.')
    return problems


def check_enemy_carry(overlay_dir, dump_dir, pairs, out=print):
    """P4. No MonsterTypeModel row points at a cyberweapon, in either the
    shipped or the post-overlay pointer set.

    REPO-SIDE ONLY. These sheets select by exact id, so unlike gear-classes.csv
    they do not need a partition at load, and design.md section 10 forbids
    runtime behaviour that depends on a dump being present. What this check
    buys is that the day an enemy is given a Photon Lance, the gate says so
    before a player finds out.
    """
    problems = []
    counts = {}
    for label, d in (('post-overlay', overlay_dir), ('shipped', dump_dir)):
        path = os.path.join(d, POINTER_FILE)
        if not os.path.isfile(path):
            problems.append(f'P4: {path} is not on disk, so the {label} pointer '
                            f'set could not be read. This is "could not look", '
                            f'not "no enemy carries one".')
            continue
        rows = read_csv_rows(path, f'the {label} MonsterTypeModel')
        if POINTER_COLUMN not in rows[0]:
            problems.append(f'P4: {path} has no {POINTER_COLUMN} column.')
            continue
        ids = set()
        for r in rows:
            v = (r[POINTER_COLUMN] or '').strip()
            if v:
                ids.add(int(v))
        hit = sorted(ids & set(pairs))
        counts[label] = (len(rows), len(ids), hit)
        if hit:
            problems.append(f'P4: the {label} MonsterTypeModel points at '
                            f'cyberweapon(s) {hit}. A sheet row for one of those '
                            f'would tune a weapon an enemy carries.')
    for label, (nrows, nids, hit) in sorted(counts.items()):
        out(f'    P4 {label}: {nrows} monster row(s), {nids} distinct '
            f'{POINTER_COLUMN}, {len(hit)} of the {len(pairs)} cyberweapons in '
            f'the set.')
    return problems


def check_collisions(weapons, talents, dump_dir, out=print):
    """C1-C3. Each declared collision pair is real in the dump, and a key of
    (table, id) tells the two apart where a key of id alone does not."""
    problems = []
    tables = {
        'WeaponModel': (weapons, WEAPON_KEY),
        'TalentModel': (talents, TALENT_KEY),
    }
    for fn, key in (('EffectModel.csv', 'EffectId'),
                    ('MatrixEffectModel.csv', 'MatrixEffectId'),
                    ('MonsterTypeModel.csv', 'MonsterTypeId')):
        model = fn[:-4]
        try:
            tables[model] = (load_table(dump_dir, fn, key, f'the dumped {model}'), key)
        except Problem as e:
            problems.append(f'C: {e}')
    for case in COLLISION_CASES:
        for side in ('left', 'right'):
            model, key, rid = case[side]
            t = tables.get(model)
            if t is None:
                problems.append(f'{case["id"]}: {model} was not read, so this '
                                f'pair was NOT checked.')
                break
            if rid not in t[0]:
                problems.append(f'{case["id"]}: {model}.{key} {rid} is not in '
                                f'the dump, so the declared collision is stale.')
        else:
            lm, _lk, lid = case['left']
            rm, _rk, rid = case['right']
            if (lm, lid) == (rm, rid):
                problems.append(f'{case["id"]}: the (table, id) keys are equal, '
                                f'so this is not a collision case.')
            if lid != rid:
                problems.append(f'{case["id"]}: the ids differ ({lid} vs {rid}), '
                                f'so an id-alone key would NOT collapse them and '
                                f'the case proves nothing.')
    out(f'    C: {len(COLLISION_CASES)} declared (table, id) collision pair(s), '
        f'each present in both tables of its pair.')
    return problems


PLUGIN_SOURCE = os.path.join('mods', 'CKFHardMode', 'Cyberweapons.cs')
_LEVER_RE = re.compile(
    r'new\s+Lever\(\s*"([^"]+)"\s*,\s*(\w+)\s*,\s*"([^"]+)"\s*\)')
_MAP_BEGIN = 'BEGIN LEVER MAP'
_MAP_END = 'END LEVER MAP'
_ARRAY_RE = re.compile(r'(\w+)Levers\s*=')


def check_map_matches_plugin(src_root, out=print):
    """P-MAP. The column map in mods/CKFHardMode/Cyberweapons.cs equals the one
    in this file, entry for entry and in order.

    THE WHOLE PHASE RESTS ON THOSE TWO AGREEING. They are two transcriptions on
    purpose -- Phase 4's lesson is that the thing which checks the writer must
    not be the writer -- but two transcriptions with nothing between them drift,
    and the drift is invisible: the plugin would write one column and every
    repo-side gate would check another.

    THIS IS A TEXT SCRAPE, and it says so. It reads only between the two
    markers in that file and REFUSES if it cannot find them or finds no entry,
    because a scrape that matched nothing would otherwise report agreement.
    AGENTS.md.
    """
    problems = []
    path = os.path.join(src_root, PLUGIN_SOURCE)
    if not os.path.isfile(path):
        problems.append(f'P-MAP: {path} is not on disk, so the plugin-side column '
                        f'map was NOT compared. This is "could not look", not '
                        f'"they agree".')
        out(f'    P-MAP: NOT CHECKED -- {PLUGIN_SOURCE} is not at {src_root}.')
        return problems
    with io.open(path, encoding='utf-8') as fh:
        src = fh.read()
    a, b = src.find(_MAP_BEGIN), src.find(_MAP_END)
    if a < 0 or b < 0 or b < a:
        problems.append(f'P-MAP: {PLUGIN_SOURCE} has no "{_MAP_BEGIN}" / '
                        f'"{_MAP_END}" marker pair, so the map could not be '
                        f'located and NOTHING was compared.')
        out('    P-MAP: NOT CHECKED -- markers missing.')
        return problems
    block = src[a:b]
    found, current = {}, None
    for line in block.splitlines():
        m = _ARRAY_RE.search(line)
        if m:
            current = m.group(1).lower()          # Laser / Claw
            found.setdefault(current, [])
        for cm in _LEVER_RE.finditer(line):
            if current is None:
                problems.append(f'P-MAP: a Lever entry appears before any '
                                f'"...Levers =" line: {line.strip()!r}')
                continue
            col, model_token, target = cm.groups()
            found[current].append((col, model_token, target))
    if not any(found.values()):
        problems.append(f'P-MAP: the markers were found in {PLUGIN_SOURCE} and '
                        f'NO Lever entry parsed out of the block. A scrape that '
                        f'matches nothing must not report agreement.')
        out('    P-MAP: NOT CHECKED -- markers found, zero entries parsed.')
        return problems
    token = {WEAPON_MODEL: 'WeaponModel', TALENT_MODEL: 'TalentModel'}
    for sheet, arr in (('laser', LASERS), ('claw', CLAWS)):
        mine = [(c, token[arr.map[c][0]], arr.map[c][1]) for c in arr.order]
        theirs = found.get(sheet)
        if theirs is None:
            problems.append(f'P-MAP: {PLUGIN_SOURCE} has no {sheet.title()}Levers '
                            f'array inside the markers.')
            continue
        if mine != theirs:
            only_mine = [x for x in mine if x not in theirs]
            only_theirs = [x for x in theirs if x not in mine]
            problems.append(
                f'P-MAP: the {sheet} column map differs between this file '
                f'({len(mine)} entries) and {PLUGIN_SOURCE} ({len(theirs)}). '
                f'Only here: {only_mine}. Only there: {only_theirs}. '
                + ('Same entries, different order.'
                   if not only_mine and not only_theirs else ''))
    out(f'    P-MAP: {sum(len(v) for v in found.values())} Lever entry(ies) '
        f'scraped from {PLUGIN_SOURCE} between the markers and compared entry '
        f'for entry against this file\'s '
        f'{len(LASERS.order) + len(CLAWS.order)}.')
    return problems


def check_double_application(rules_path, out=print):
    """THE ANSWER TO THE PHASE'S FIRST QUESTION, asserted rather than asserted
    about. The 22 rules this phase converts must all be `set`-only for the
    rules file to stay on disk beside the sheets."""
    problems = []
    rules = load_rules_json(rules_path)
    converted = [r for r in rules if _is_converted(r)]
    banned = ('multiply', 'add', 'clampMin', 'clampMax', 'clone', 'as', 'serveOn')
    ranges = 0
    for r in converted:
        for b in banned:
            if r.get(b):
                problems.append(
                    f'DOUBLE-APPLICATION: a converted rule carries {b!r} '
                    f'({r.get("comment", "")[:70]!r}). `set` applied twice is '
                    f'`set` applied once; {b} applied twice is not. The rules '
                    f'file cannot stay on disk beside the sheets -- either this '
                    f'rule is deleted in the same commit, or it is not '
                    f'converted.')
        if not r.get('set'):
            problems.append(f'DOUBLE-APPLICATION: a converted rule has no `set` '
                            f'({r.get("comment", "")[:70]!r}).')
        if r.get('whereMin') or r.get('whereMax'):
            ranges += 1
    out(f'    DOUBLE-APPLICATION: {len(converted)} converted rule(s); '
        f'{len(converted) - ranges} exact selector(s), {ranges} range '
        f'selector(s); {len([r for r in converted if r.get("set")])} carry '
        f'`set`, 0 carry multiply/add/clampMin/clampMax/clone. So the same '
        f'triple written twice lands on the same number and '
        f'ckf.hardmode.rules.json STAYS on disk this phase.')
    return problems, converted, len(rules)


def _is_converted(r):
    """A rule this phase converts, identified by what it selects rather than by
    its comment text. Phase 4 recorded the trap: 17 of these carry `CW /`
    MID-comment behind `PLAYER - `, so an unanchored prefix search matches them
    and an anchored one does not."""
    model = r.get('model')
    if model == WEAPON_MODEL:
        return bool(_selected_ids(r, WEAPON_KEY) & set(range(24000, 25100)))
    if model == TALENT_MODEL:
        return bool(_selected_ids(r, TALENT_KEY) & set(range(80000, 80100)))
    return False


def _selected_ids(r, key, universe=None):
    """The ids a rule selects. An exact rule names one; a range rule names the
    members of the universe inside it, which is why the old side has to be
    resolved against the dump rather than compared selector to selector."""
    where = r.get('where') or {}
    if key in where:
        return {int(where[key])}
    lo = (r.get('whereMin') or {}).get(key)
    hi = (r.get('whereMax') or {}).get(key)
    if lo is None and hi is None:
        return set()
    lo = -10 ** 15 if lo is None else lo
    hi = 10 ** 15 if hi is None else hi
    if universe is None:
        return {i for i in range(int(lo), int(hi) + 1)} if hi - lo < 10 ** 5 else set()
    return {i for i in universe if lo <= i <= hi}


# ---------------------------------------------------------------------------
# --check: old side vs new side, element by element
# ---------------------------------------------------------------------------

def old_effect(rules_path, weapons, talents):
    """(model, id, column) -> value after the rules file runs. The range rules
    are RESOLVED against the dump rather than compared as selectors."""
    out = {}
    universe = {WEAPON_MODEL: (set(weapons), WEAPON_KEY),
                TALENT_MODEL: (set(talents), TALENT_KEY)}
    for r in load_rules_json(rules_path):
        if not _is_converted(r):
            continue
        uni, key = universe[r['model']]
        for rid in sorted(_selected_ids(r, key, uni)):
            for col, val in (r.get('set') or {}).items():
                out[(r['model'], rid, col)] = float(val)
    return out


def old_effect_declared():
    """The same mapping old_effect() built, typed in instead of parsed.

    (model, id, column) -> value, from DECLARED_LAST_RULES_TRIPLES. The ranges
    are already resolved here because they were resolved against the dump when
    the table was transcribed, which is what old_effect() does at runtime."""
    return {k: float(v) for k, v in DECLARED_LAST_RULES_TRIPLES}


def resolve_old_side(state, weapons, talents):
    """The OLD side of --check and the one-line description of where it came
    from, chosen by the declared rules-file state.

    THERE IS NO THIRD ARM. An old side that is neither the file nor the
    transcription would be an empty dict, and compare() over an empty old side
    reports every triple as agreeing with itself."""
    if state.found:
        return (old_effect(state.rules_path, weapons, talents),
                f'the {RULES_FILE} on disk')
    return (old_effect_declared(),
            f'DECLARED_LAST_RULES_TRIPLES -- the '
            f'{len(DECLARED_LAST_RULES_TRIPLES)} triple(s) transcribed off '
            f'the 3.x {RULES_FILE}')


def new_effect(rules, shipped=None):
    """(model, id, column) -> value after the sheets run. `multiply` and `add`
    start from the shipped value when the sheet does not also set the column;
    no cell uses either today, and the arm exists so that the day one does,
    --check measures it rather than reporting a clean zero over a branch it
    never took."""
    out = {}
    for r in rules:
        for kind, col, val in r.ops:
            key = (r.model, r.rid, col)
            if kind == SET:
                out[key] = val
                continue
            cur = out.get(key)
            if cur is None and shipped is not None:
                cur = shipped.get(key)
            if kind == MULTIPLY:
                out[key] = (1.0 if cur is None else cur) * val
            elif kind == ADD:
                out[key] = (0.0 if cur is None else cur) + val
    return out


def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def compare(old, source, weapons, talents, rules, pairs, out=print):
    """Every column EITHER SIDE touches on all 33 weapon rows and all 33 talent
    rows, old side against new side, with the shipped value standing in wherever
    a side does not write.

    RETIRED FROM THE DEFAULT --check -- see RULESET_3X_RETIRED_WHY. Reached
    only under `--ruleset-3x`. Every difference it names is a DIVERGENCE FROM
    THE 3.0 RULESET, which is not by itself a defect: these sheets are for
    tuning and a divergence is usually a tuning edit. It is
    still worth being able to ask for the list.

    THE SHIPPED BASELINE IS BUILT FROM THE UNION, not from the sheet's own
    column map, and that is the whole difference between this instrument
    working and not working. Built from the map, a column the OLD rules write
    and the NEW sheet has no column for produced `shipped[key] = None` and was
    skipped by the `o is None` guard -- so dropping SpecialRule from the laser
    sheet, which silently gives sixteen lasers back Rapid Fire, compared clean.
    Both fault cases (F2, F3) caught it. The union closes it: any triple either
    side names is looked up in the dump, so "the new side has no column for
    this" reads as a difference rather than as an absence.
    """
    new_raw = new_effect(rules)
    row_of = {WEAPON_MODEL: weapons, TALENT_MODEL: talents}
    mine = set()
    for sheet in SHEETS:
        for wid, tid in sorted(pairs.items()):
            if wid not in weapons or int(weapons[wid][CLASS_COLUMN]) != sheet.cls:
                continue
            for col in sheet.order:
                model, gcol = sheet.map[col]
                mine.add((model, wid if model == WEAPON_MODEL else tid, gcol))
    shipped = {}
    for key in mine | set(old) | set(new_raw):
        model, rid, gcol = key
        src = row_of.get(model, {}).get(rid)
        shipped[key] = _num(src.get(gcol)) if src is not None else None
    new = new_effect(rules, shipped)
    diffs, unreadable = [], []
    for key in sorted(shipped):
        base = shipped[key]
        o = old.get(key, base)
        n = new.get(key, base)
        if o is None or n is None:
            # NAMED, not skipped. A triple whose shipped value cannot be read
            # is "could not look", and counting it as agreement is the shape
            # AGENTS.md is about.
            unreadable.append(key)
            continue
        if abs(o - n) > 1e-9:
            diffs.append((key, o, n))
    out(f'    {len(diffs)} value(s) differ between the old side ({len(old)} '
        f'triple(s), from {source}) and the two sheets, over {len(shipped)} '
        f'(table, id, column) triple(s) -- the union of every column either '
        f'side touches, {len(mine)} of them from the sheets\' own column maps. '
        f'This is a DIVERGENCE COUNT against the 3.0 ruleset, not a defect '
        f'count -- a non-zero answer is expected on a tuned bench. '
        f'{len(unreadable)} triple(s) had no readable shipped value and '
        f'were NOT compared'
        + (': ' + str(unreadable[:4]) if unreadable else '.'))
    problems = []
    for (model, rid, col), o, n in diffs:
        problems.append(f'DIVERGENCE {model} {rid}.{col} {o:g} -> {n:g} '
                        f'against the 3.0 ruleset. Listed because '
                        f'{RULESET_3X_RETIRED_FLAG} was passed. This is NOT a '
                        f'defect by itself: deviation from the 3.0 ruleset is '
                        f'tuning, which is what the sheets are for '
                        f'({RULESET_3X_RETIRED_BY}, {RULESET_3X_RETIRED_ON}).')
    for key in unreadable:
        problems.append(f'UNREADABLE {key[0]} {key[1]}.{key[2]} has no shipped '
                        f'value in the dump, so old and new could not be '
                        f'compared on it.')
    return problems, diffs, len(shipped)


def check_declared_triples(rules, out=print):
    """P-GONE -- every triple the 3.x rules file carried is STILL WRITTEN by
    the sheets, with the same value, and the sheets write nothing else.

    RETIRED FROM THE DEFAULT --check -- see RULESET_3X_RETIRED_WHY. Reached
    only under `--ruleset-3x`. It cannot tell a column deliberately cleared
    from a column a converter accidentally dropped, and conversion is over, so on the default path it is a recorded
    non-run.

    WHY THIS IS NOT ALREADY compare()'s JOB, which is the only reason it
    exists. compare() substitutes the SHIPPED value wherever a side does not
    write a triple, so a declared triple whose declared value already equals
    the shipped value is invisible to it: 30 of the 60 are `SpecialRule -> 0`
    and SpecialRule ships as 0 on some of those rows, so dropping the column
    from the sheet moves no number on those rows and compare() reports nothing
    for them. P-GONE asks the different question -- is the WRITE still there --
    against new_effect(rules) with no shipped fallback at all.

    That is the Phase 9a shape, on this file's own sixty: a sheet quietly stops
    emitting a column, the value reverts to whatever the game ships, and the
    only thing that knew the column was written has been deleted.
    """
    declared = old_effect_declared()
    emitted = new_effect(rules)
    problems, equal, missing, differ = [], 0, [], []
    for key in sorted(declared):
        got = emitted.get(key)
        if got is None:
            missing.append(key)
        elif abs(got - declared[key]) > 1e-9:
            differ.append((key, declared[key], got))
        else:
            equal += 1
    extra = sorted(k for k in emitted if k not in declared)
    out(f'    P-GONE: {len(declared)} declared triple(s) from the deleted '
        f'{RULES_FILE}, asserted against what the two sheets emit: {equal} '
        f'equal, {len(missing)} MISSING, {len(differ)} DIFFER, {len(extra)} '
        f'emitted by the sheets and not declared. The declared side is typed '
        f'in, so it cannot move when the sheets move.')
    for model, rid, col in missing:
        problems.append(f'P-GONE: {model} {rid}.{col} was written by the '
                        f'deleted {RULES_FILE} and NO SHEET WRITES IT NOW, so '
                        f'the value reverts to the shipped one. Reported '
                        f'because {RULESET_3X_RETIRED_FLAG} was passed. This '
                        f'shape was the Phase 9a failure when it was an '
                        f'accident of conversion; a cleared override is the '
                        f'same shape and is tuning.')
    for (model, rid, col), want, got in differ:
        problems.append(f'P-GONE: {model} {rid}.{col} was {want:g} in the '
                        f'deleted {RULES_FILE} and is {got:g} in the sheets.')
    for model, rid, col in extra:
        problems.append(f'P-GONE: the sheets write {model} {rid}.{col}, which '
                        f'the deleted {RULES_FILE} did not. That is a balance '
                        f'change the 3.0 ruleset did not carry -- reported '
                        f'because {RULESET_3X_RETIRED_FLAG} was passed, not '
                        f'because it is wrong.')
    return problems


# ---------------------------------------------------------------------------
# THE 3.x-CONFORMANCE COMPARISON IS RETIRED FROM THE DEFAULT --check.
# ---------------------------------------------------------------------------
#
# David's rule: deviation from the 3.0 ruleset is tuning, not a mistake.
# Undoing a balance change (for example letting the eye-laser special rules
# ship as the game has them) is not a problem.
#
# WHAT IS RETIRED. Exactly two instruments, and only from the DEFAULT --check:
#
#   P-GONE               check_declared_triples(). Asserts that the sheets
#                        still WRITE every one of the 60 triples the 3.x rules
#                        file carried.
#   UNDECLARED CHANGE    the problems compare() raises. Asserts that no value
#                        moved between the transcribed 3.0 side and the sheets.
#
# Both were built to catch a value LOST BY ACCIDENT during conversion -- a
# sheet quietly dropping a column with nothing left that knew the column was
# written. They cannot tell deliberate tuning from accidental loss, so every
# tuning edit produces a problem per edited cell: clearing an override (which
# hands the column back to the game) reports one P-GONE and one UNDECLARED
# CHANGE per row [measured].
#
# THIS IS NOT A TOLERANCE LIST. Nothing was added to any allowlist. The
# comparison itself left the default suite.
#
# WHAT STILL RUNS, AND IT IS EVERY OTHER CHECK IN THIS FILE. P-COL, P-BLANK,
# P-ROWS, P-SHARED, P-DIVERGE, P-CLONE, P4, C (collisions), P-MAP, the join,
# the state declaration and RULES-FILE all run on every --check. Those ask
# questions about the sheets and the game data, not about the 3.0 ruleset.
#
# WHAT IS NOT DELETED. compare(), check_declared_triples(), old_effect(),
# old_effect_declared(), resolve_old_side() and DECLARED_LAST_RULES_TRIPLES are
# all reachable:
#
#     python scripts/cyberweapons.py --check --ruleset-3x --game <root>
#
# runs both of them, and the selftest cases that fault them run under the same
# flag. What it prints is a divergence, named and counted. A divergence is not
# a defect.
#
# HOW THE DEFAULT --check REPORTS IT. NOT RUN, by name, one line per retired
# instrument plus one per retired selftest case, never PASS and never absent.
# AGENTS.md: an instrument's silence is not evidence, and a retired check must
# SAY it is not running.

RULESET_3X_RETIRED_ON = '2026-09-15'
RULESET_3X_RETIRED_BY = "David's ruling"
RULESET_3X_RETIRED_FLAG = '--ruleset-3x'
RULESET_3X_RETIRED_WHY = (
    'RETIRED from the default --check, %s %s. Run it with '
    '`cyberweapons.py --check %s --game <root>`.'
    % (RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON, RULESET_3X_RETIRED_FLAG))

# The retired checks, NAMED not counted, each with what it measured. A reader
# has to be able to see WHICH coverage is not running.
RULESET_3X_RETIRED_CHECKS = (
    ('P-GONE -- every one of the 60 triples the 3.x '
     'ckf.hardmode.rules.json carried is STILL WRITTEN by the sheets, with the same '
     'value, and the sheets write nothing else'),
    ('UNDECLARED CHANGE -- no value moves between the transcribed 3.0 side and '
     'the sheets, over the union of every (table, id, column) either side '
     'touches, with the shipped value standing in where a side does not write'),
)

# The selftest cases that fault the two instruments above. They go with them:
# a fault case that still passes for a check the default suite no longer runs
# is the false green this file exists to refuse.
RULESET_3X_RETIRED_CASES = (
    'CONTROL: zero values differ between the old side and the sheets',
    'F2: SpecialRule dropped from the laser sheet (16 lasers regain Rapid Fire)',
    'F3: ApCost dropped from the laser sheet (16 laser talents go back to 2 AP)',
    "F4's compare() half: a shipped claw override also moves a value "
    '(check_claws_blank, the live half, STILL RUNS and still catches it)',
    'C5: the sheets write every triple the deleted rules file carried, and '
    'nothing more',
    'F17: the sheets stop writing a declared triple whose declared value '
    'EQUALS the shipped value -- P-GONE sees it where compare() cannot',
    'F18: a declared triple the sheets write with a different value',
    'F19: a write the sheets make that the deleted rules file never made',
)


def ruleset_3x_report_retired(out=print):
    """Report the 3.x comparison as a RECORDED NON-RUN on the default --check.

    Prints the reason in full once, then one NOT RUN line per retired
    instrument and per retired fault case. Returns NO problems and counts
    nothing as passed: a run that reaches this cannot be read as having
    compared anything against the 3.0 ruleset.
    """
    for line in (
        'NOT RUN. The 3.x-conformance comparison is RETIRED from --check.',
        '%s, %s. The %d check(s) and %d fault case(s) below are reported by '
        'name and never pass.'
        % (RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON,
           len(RULESET_3X_RETIRED_CHECKS), len(RULESET_3X_RETIRED_CASES)),
        '',
        'THE RULING: "Stop considering deviation from the 3.0 ruleset a',
        'mistake. Remove all consideration that this is a problem."',
        '',
        'WHY. Both instruments compare the sheets against the 3.0 ruleset they',
        'were converted from. They were built to catch a value LOST BY ACCIDENT',
        'during conversion. They cannot tell deliberate tuning from accidental',
        'loss, so every tuning edit to a lever cell produces a problem per',
        'cell -- clearing an override, which hands the column back to the',
        'game, included. Tuning is what these sheets are for.',
        '',
        'THIS IS NOT A TOLERANCE LIST. No cell, row or column was added to any',
        'allowlist. The comparison left the default suite; nothing was excused',
        'from it.',
        '',
        'NOTHING ELSE IS RETIRED. P-COL, P-BLANK, P-ROWS, P-SHARED, P-DIVERGE,',
        'P-CLONE, P4, C, P-MAP, the join and the RULES-FILE state declaration',
        'all ran on this run and all still go red. Run the two below,',
        'unchanged, with:',
        '',
        '    python scripts/cyberweapons.py --check %s --game <root>'
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


def double_application_not_run(out=print):
    """DOUBLE-APPLICATION as a RECORDED NON-RUN, which is not a pass.

    check_double_application() asks whether the 22 converted rules are all
    `set`, because `set` twice is `set` once and that is what licensed the
    rules file and the sheets sitting on disk together. There is no longer a
    second application to measure: the file is gone, the sheets apply once,
    and the question has no subject.

    So it is NOT run and NOT counted. It returns no problems, contributes no
    selftest case, and prints what it last measured as a number rather than as
    a verdict. check_double_application() itself is untouched and still
    REFUSES on a missing path -- F22 is that refusal -- so the day the file
    comes back, the check is there and the state declaration says to run it.
    """
    d = DECLARED_LAST_DOUBLE_APPLICATION
    out(f'    DOUBLE-APPLICATION: NOT RUN -- double application needs two '
        f'applications and {RULES_FILE} is not on disk, so the sheets apply '
        f'once. The last run against a rules file measured {d["converted"]} '
        f'converted rule(s) of {d["rules_in_file"]} in the file '
        f'({d["exact"]} exact, {d["ranges"]} range), {d["carry_set"]} carrying '
        f'`set` and {d["carry_banned"]} carrying '
        f'multiply/add/clampMin/clampMax/clone [measured]. That is '
        f'a record, not a result: it is asserted against nothing this run and '
        f'is NOT counted as a check that passed.')
    return []


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

class _Skip3x(Exception):
    """Raised inside a retired fault case's try/finally so the case's own
    restore still runs. It never escapes selftest() and never becomes a fail."""


def selftest(state, overlay_dir, dump_dir, src_root, weapons, talents,
             by_sheet, pairs, out=print, run_3x=False):
    # TAKES THE STATE, NOT THE PATH. The cases that compare against the OLD
    # SIDE (CONTROL x2, F2, F3, F4) get it from the state, so they run against
    # the transcription when no rules file is present and still go red on the
    # same mutations.
    fails = []
    scope = set(pairs.values())
    rules_path = state.rules_path
    old_side, old_source = resolve_old_side(state, weapons, talents)

    def ck(name, cond, detail=''):
        out(f'    {"PASS" if cond else "FAIL"}  {name}'
            + (f'   {detail}' if detail and not cond else ''))
        if not cond:
            fails.append(name)

    def skip_3x(name):
        """A retired fault case, reported by name and never passed.

        It touches neither the PASS count nor `fails`, so a green --selftest
        cannot be read as having exercised the 3.x comparison. AGENTS.md
        ."""
        out(f'    NOT RUN  {name}')
        out(f'             {RULESET_3X_RETIRED_WHY}')

    if not run_3x:
        out(f'    The {len(RULESET_3X_RETIRED_CASES)} fault case(s) over the '
            f'3.x-conformance comparison are RETIRED from this suite '
            f'({RULESET_3X_RETIRED_BY}, {RULESET_3X_RETIRED_ON}) and are '
            f'reported NOT RUN below, each by name. Every other case runs.')

    # The grammar, against the SAME case table gear_classes.py and
    # gui/serve.py use. Not a fifth copy.
    for s, k, v in _gear.ADJUST_CASES_OK:
        kind, val, ok = parse_adjust(s)
        ck(f'adjust accepts {s!r}',
           ok and kind == k and (v is None or abs(val - v) < 1e-12),
           f'{(kind, val, ok)}')
    for s in _gear.ADJUST_CASES_BAD:
        ck(f'adjust rejects {s!r}', parse_adjust(s)[2] is False)
    ck('blank and unparseable are distinguishable',
       parse_adjust('')[2] is True and parse_adjust('1.8x')[2] is False)

    texts = {s.name: render_sheet(s, weapons, talents, by_sheet[s.key])
             for s in SHEETS}
    sheets = {s.key: list(csv.DictReader(io.StringIO(texts[s.name])))
              for s in SHEETS}
    rules = []
    for s in SHEETS:
        rules += expand(s, sheets[s.key])

    # CONTROL FIRST. If the clean case does not pass, "everything is caught"
    # cannot be told from "everything fails". Phase 4's shape.
    quiet = lambda *a: None                                   # noqa: E731
    probs = []
    for s in SHEETS:
        probs += check_columns(s, weapons, talents, by_sheet[s.key], out=quiet)
    probs += check_claws_blank(rules, out=quiet)
    probs += check_claw_rows_present(by_sheet['claws'], weapons, talents, out=quiet)
    probs += check_shared_rows(talents, scope, out=quiet)
    probs += check_divergent_shared_edits(rules, out=quiet)
    probs += check_no_clone(rules, texts, out=quiet)
    probs += check_enemy_carry(overlay_dir, dump_dir, pairs, out=quiet)
    probs += check_collisions(weapons, talents, dump_dir, out=quiet)
    probs += check_map_matches_plugin(src_root, out=quiet)
    if state.found:
        dprobs, _conv, _n = check_double_application(rules_path, out=quiet)
        probs += dprobs
    # THE CONTROL IS SPLIT. Its live half -- the nine checks above,
    # which know nothing about the 3.0 ruleset -- runs on every suite. Its 3.x
    # half is retired with the instruments it controls: a control that passes
    # for a comparison nobody runs is the false green this file refuses.
    cprobs, diffs = [], []
    if run_3x:
        probs += check_declared_triples(rules, out=quiet)
        cprobs, diffs, _tr = compare(old_side, old_source, weapons, talents,
                                     rules, pairs, out=quiet)
    ck('CONTROL: the shipped sheets are clean on every LIVE check',
       not probs and not cprobs, f'{(probs + cprobs)[:2]}')
    if run_3x:
        ck(f'CONTROL: zero values differ between the old side '
           f'({old_source[:40]}) and the sheets', not diffs, f'{diffs[:3]}')
    else:
        skip_3x(RULESET_3X_RETIRED_CASES[0])

    # F1 a lever mapped to its unsuffixed alias -- the write the game takes
    # and discards with no diagnostic.
    saved = dict(LASERS.map)
    try:
        LASERS.map['PureDamage'] = (WEAPON_MODEL, 'PureDamage')
        ck('F1 caught: a lever mapped to an unsuffixed alias',
           bool(check_columns(LASERS, weapons, talents, by_sheet['lasers'], out=quiet)))
    finally:
        LASERS.map.clear()
        LASERS.map.update(saved)

    # F2 SpecialRule dropped from the laser map -- the shape design.md
    # section 6's 16-column list would have shipped. Sixteen lasers silently
    # regain Rapid Fire.
    saved_order, saved_map, saved_cells = (list(LASERS.order), dict(LASERS.map),
                                           {k: dict(v) for k, v in LASERS.cells.items()})
    try:
        if not run_3x:
            skip_3x(RULESET_3X_RETIRED_CASES[1])
            raise _Skip3x
        LASERS.order.remove('SpecialRule')
        del LASERS.map['SpecialRule']
        for c in LASERS.cells.values():
            c.pop('SpecialRule', None)
        s2 = list(csv.DictReader(io.StringIO(
            render_sheet(LASERS, weapons, talents, by_sheet['lasers']))))
        r2 = expand(LASERS, s2) + expand(CLAWS, sheets['claws'])
        c2, d2, _ = compare(old_side, old_source, weapons, talents, r2, pairs, out=quiet)
        ck('F2 caught: SpecialRule dropped from the laser sheet '
           '(16 lasers regain Rapid Fire)', bool(c2), f'{d2[:2]}')
    except _Skip3x:
        pass
    finally:
        LASERS.order[:] = saved_order
        LASERS.map.clear(); LASERS.map.update(saved_map)
        LASERS.cells.clear(); LASERS.cells.update(saved_cells)

    # F3 ApCost dropped -- the other half of the same 16-column list.
    saved_order, saved_map, saved_cells = (list(LASERS.order), dict(LASERS.map),
                                           {k: dict(v) for k, v in LASERS.cells.items()})
    try:
        if not run_3x:
            skip_3x(RULESET_3X_RETIRED_CASES[2])
            raise _Skip3x
        LASERS.order.remove('ApCost')
        del LASERS.map['ApCost']
        for c in LASERS.cells.values():
            c.pop('ApCost', None)
        s3 = list(csv.DictReader(io.StringIO(
            render_sheet(LASERS, weapons, talents, by_sheet['lasers']))))
        r3 = expand(LASERS, s3) + expand(CLAWS, sheets['claws'])
        c3, d3, _ = compare(old_side, old_source, weapons, talents, r3, pairs, out=quiet)
        ck('F3 caught: ApCost dropped from the laser sheet '
           '(16 laser talents go back to 2 AP)', bool(c3), f'{d3[:2]}')
    except _Skip3x:
        pass
    finally:
        LASERS.order[:] = saved_order
        LASERS.map.clear(); LASERS.map.update(saved_map)
        LASERS.cells.clear(); LASERS.cells.update(saved_cells)

    # F4 a claw override shipped. The whole point of the claw sheet is that it
    # produces nothing.
    saved_cl = {k: dict(v) for k, v in CLAWS.cells.items()}
    try:
        CLAWS.cells[24000] = {'PhysicalDamage': '=999'}
        s4 = list(csv.DictReader(io.StringIO(
            render_sheet(CLAWS, weapons, talents, by_sheet['claws']))))
        r4 = expand(CLAWS, s4)
        # THE LIVE HALF STILL RUNS AND IS STILL THE VERDICT. check_claws_blank
        # is not a 3.x comparison -- it asserts the claw sheet produces no
        # rule, which is a statement about the sheet, not about the 3.0
        # ruleset. Only compare()'s half of this case is retired.
        p4 = check_claws_blank(r4, out=quiet)
        if run_3x:
            c4, _d4, _ = compare(old_side, old_source, weapons, talents,
                                 expand(LASERS, sheets['lasers']) + r4, pairs,
                                 out=quiet)
            ck('F4 caught: a shipped claw override (P-BLANK and compare)',
               bool(p4) and bool(c4), f'{p4[:1]} / {c4[:1]}')
        else:
            ck('F4 caught: a shipped claw override (P-BLANK, the live half)',
               bool(p4), f'{p4[:1]}')
            skip_3x(RULESET_3X_RETIRED_CASES[3])
    finally:
        CLAWS.cells.clear(); CLAWS.cells.update(saved_cl)

    # F5 the Luem Trident row dropped -- the gap design.md section 6 says this
    # phase closes by construction. Its weapon and talent must still be in the
    # file even though nothing tunes them.
    short = [p for p in by_sheet['lasers'] if p[0] != 25016]
    ck('F5 caught: Luem Trident (25016 / 80060) missing from the laser sheet',
       len(short) == 16 and 25016 not in {p[0] for p in short}
       and 25016 in {p[0] for p in by_sheet['lasers']})

    # F6 a divergent edit to the shared row. There is no live subject, so one
    # is injected: an EffectModel column that both owners write differently.
    diverge = [Rule(LASERS, 'EffectModel', 'EffectId', 2051),
               Rule(LASERS, 'EffectModel', 'EffectId', 2051)]
    diverge[0].ops.append((SET, 'CritRate', 10.0))
    diverge[1].ops.append((SET, 'CritRate', 20.0))
    p6 = check_divergent_shared_edits(diverge, out=quiet)
    ck('F6 caught: two owners of EffectModel 2051 given different values',
       any(p.startswith('P-DIVERGE') for p in p6), f'{p6[:1]}')
    same = [Rule(LASERS, 'EffectModel', 'EffectId', 2051),
            Rule(LASERS, 'EffectModel', 'EffectId', 2051)]
    same[0].ops.append((SET, 'CritRate', 10.0))
    same[1].ops.append((SET, 'CritRate', 10.0))
    ck('F6 control: two owners given the SAME value is not a divergence',
       not check_divergent_shared_edits(same, out=quiet))

    # F7 a shared row that the declaration does not know about.
    saved_sr = dict(SHARED_ROWS)
    try:
        SHARED_ROWS.clear()
        p7 = check_shared_rows(talents, scope, out=quiet)
        ck('F7 caught: a shared row nothing declares',
           any('NOT in SHARED_ROWS' in p for p in p7), f'{p7[:1]}')
    finally:
        SHARED_ROWS.clear(); SHARED_ROWS.update(saved_sr)

    # F8 a stale shared-row declaration.
    saved_sr = dict(SHARED_ROWS)
    try:
        SHARED_ROWS[('EffectModel', 999999)] = dict(SHARED_ROWS[('EffectModel', 2051)])
        p8 = check_shared_rows(talents, scope, out=quiet)
        ck('F8 caught: a stale shared-row declaration',
           any('stale' in p for p in p8), f'{p8[:1]}')
    finally:
        SHARED_ROWS.clear(); SHARED_ROWS.update(saved_sr)

    # F9 a clone control column in the header. REFUSED, not ignored.
    try:
        bad_text = texts[LASERS.name].replace('_comment', '_clone,_comment', 1)
        import tempfile
        fd, p = tempfile.mkstemp(suffix='.csv')
        with os.fdopen(fd, 'w', newline='') as fh:
            fh.write(bad_text)
        try:
            read_sheet(LASERS, p)
            ck('F9 caught: a _clone column refuses the whole file', False)
        except Problem as e:
            ck('F9 caught: a _clone column refuses the whole file',
               '_clone' in str(e))
        os.unlink(p)
    except Exception as e:                                    # pragma: no cover
        ck('F9 caught: a _clone column refuses the whole file', False, repr(e))

    # F10 an unparseable cell is named, not swallowed.
    probe = list(csv.DictReader(io.StringIO(texts[LASERS.name])))
    probe[0]['PureDamage'] = '90x'
    rep = []
    expand(LASERS, probe, report=rep)
    ck('F10 caught: an unparseable cell names sheet, row and column',
       any('PureDamage' in m and '25000' in m for m in rep), f'{rep[:1]}')

    # F11 a row whose ids do not parse produces NEITHER rule -- not one half.
    probe2 = list(csv.DictReader(io.StringIO(texts[LASERS.name])))
    probe2[0][TALENT_ID] = ''
    rep2 = []
    r11 = expand(LASERS, probe2, report=rep2)
    ck('F11 caught: a half-readable row emits no rule at all',
       bool(rep2) and not any(x.rid == 25000 for x in r11), f'{rep2[:1]}')

    # F12 the (table, id) key. An id-alone registry collapses each declared
    # collision pair; the (table, id) key does not. One case per pair.
    for case in COLLISION_CASES:
        lm, _lk, lid = case['left']
        rm, _rk, rid = case['right']
        id_only = {lid, rid}
        table_id = {(lm, lid), (rm, rid)}
        ck(f'F12/{case["id"]}: id alone collapses {lm} {lid} and {rm} {rid}; '
           f'(table, id) does not',
           len(id_only) == 1 and len(table_id) == 2,
           f'{id_only} / {table_id}')

    # F12b the registry in expand() is (model, id): the laser sheet's
    # TalentModel 80007 must NOT collide with a WeaponModel 80007.
    probe3 = list(csv.DictReader(io.StringIO(texts[LASERS.name])))
    rep3 = []
    r12 = expand(LASERS, probe3, report=rep3)
    keys = [x.table_id for x in r12]
    ck('F12b: every emitted key is a (model, id) tuple and none repeats',
       all(isinstance(k, tuple) and len(k) == 2 for k in keys)
       and len(set(keys)) == len(keys) and not rep3)

    # F12c two rows claiming one (model, id) IS refused.
    probe4 = list(csv.DictReader(io.StringIO(texts[LASERS.name])))
    probe4[1][WEAPON_ID] = probe4[0][WEAPON_ID]
    rep4 = []
    expand(LASERS, probe4, report=rep4)
    ck('F12c caught: two rows claiming one (model, id)',
       any('already written by line' in m for m in rep4), f'{rep4[:1]}')

    # F13 a converted rule carrying multiply -- the shape that would force the
    # rules file to be deleted in the same commit.
    import tempfile
    fd, p13 = tempfile.mkstemp(suffix='.json')
    with os.fdopen(fd, 'w') as fh:
        json.dump({'rules': [{'model': 'WeaponModel',
                              'where': {'WeaponId': 25000},
                              'multiply': {'PureDamage1': 1.5}}]}, fh)
    d13, _c, _n = check_double_application(p13, out=quiet)
    ck('F13 caught: a converted rule carrying multiply',
       any('DOUBLE-APPLICATION' in x for x in d13), f'{d13[:1]}')
    os.unlink(p13)

    # F14 an enemy carrying a cyberweapon. Injected by pretending one weapon an
    # enemy DOES carry is a sheet row, which is the same arithmetic as an enemy
    # being given a Photon Lance and does not need the pointer file edited.
    carried = sorted(_pointer_ids(overlay_dir))
    fake = dict(pairs)
    fake[carried[0]] = 0
    p14 = check_enemy_carry(overlay_dir, dump_dir, fake, out=quiet)
    ck('F14 caught: a MonsterTypeModel pointer aimed at a sheet row',
       any(p.startswith('P4') for p in p14), f'{p14[:1]}')
    ck('F14 control: no enemy carries a cyberweapon today',
       not check_enemy_carry(overlay_dir, dump_dir, pairs, out=quiet))

    # F15 the plugin's column map drifts from this one. Injected on THIS side,
    # because the plugin source is not this script's to edit.
    saved_map = dict(LASERS.map)
    try:
        LASERS.map['PureDamage'] = (WEAPON_MODEL, 'PureDamage2')
        p15 = check_map_matches_plugin(src_root, out=quiet)
        ck('F15 caught: the plugin map and this map disagree',
           any(x.startswith('P-MAP') for x in p15), f'{p15[:1]}')
    finally:
        LASERS.map.clear(); LASERS.map.update(saved_map)
    ck('F15 control: they agree today',
       not check_map_matches_plugin(src_root, out=quiet))

    # F16 the scrape finds nothing and must NOT report agreement.
    p16 = check_map_matches_plugin(os.path.join(src_root, 'no-such-root'), out=quiet)
    ck('F16 caught: the plugin source is missing -- NOT CHECKED, not clean',
       any('could not look' in x for x in p16), f'{p16[:1]}')

    # ---- faults on the TRANSCRIBED OLD SIDE ----------------------------------
    #
    # F2, F3 and F4 above already fault compare() through the sheets, against
    # the transcription. These
    # fault the part of the new path those three cannot reach: P-GONE, which
    # asks whether the WRITE is still there rather than whether the NUMBER
    # moved. Both mutations are injected into the live side, because the
    # declared side is typed in and moving it would be grading the oracle.
    if not run_3x:
        for _n in RULESET_3X_RETIRED_CASES[4:]:
            skip_3x(_n)
    if run_3x:
        ck('C5 the sheets write every triple the deleted rules file carried, '
           'and nothing more', not check_declared_triples(rules, out=quiet),
           f'{check_declared_triples(rules, out=quiet)[:2]}')
    _decl = old_effect_declared()
    _k_flat = next(k for k in sorted(_decl)
                   if abs(_decl[k] - (_num((weapons if k[0] == WEAPON_MODEL
                                            else talents)[k[1]].get(k[2])) or 0.0))
                   < 1e-9)
    dropped = [r for r in rules]
    _hit = [r for r in dropped if (r.model, r.rid) == (_k_flat[0], _k_flat[1])]
    _saved_ops = [(r, list(r.ops)) for r in _hit]
    try:
        if not run_3x:
            raise _Skip3x
        for r in _hit:
            r.ops[:] = [o for o in r.ops if o[1] != _k_flat[2]]
        p17 = check_declared_triples(dropped, out=quiet)
        c17, d17, _ = compare(old_side, old_source, weapons, talents, dropped,
                              pairs, out=quiet)
        ck(f'F17 caught by P-GONE: the sheets stop writing {_k_flat[0]} '
           f'{_k_flat[1]}.{_k_flat[2]}, a declared triple whose declared value '
           f'EQUALS the shipped value -- so compare() sees nothing and P-GONE '
           f'sees it',
           any(x.startswith('P-GONE') for x in p17) and not d17,
           f'{p17[:1]} / diffs {d17[:1]}')
    except _Skip3x:
        pass
    finally:
        for r, o in _saved_ops:
            r.ops[:] = o

    _k0 = sorted(_decl)[0]
    _hit0 = [r for r in rules if (r.model, r.rid) == (_k0[0], _k0[1])]
    _saved0 = [(r, list(r.ops)) for r in _hit0]
    try:
        if not run_3x:
            raise _Skip3x
        for r in _hit0:
            r.ops[:] = [(k, c, (v + 7.0) if c == _k0[2] else v)
                        for k, c, v in r.ops]
        p18 = check_declared_triples(rules, out=quiet)
        ck('F18 caught: a declared triple the sheets write with a different '
           'value', any(x.startswith('P-GONE') for x in p18), f'{p18[:1]}')
    except _Skip3x:
        pass
    finally:
        for r, o in _saved0:
            r.ops[:] = o

    if run_3x:
        _extra = list(rules) + [Rule(LASERS, WEAPON_MODEL, WEAPON_KEY, 25000)]
        _extra[-1].ops.append((SET, 'Accuracy1', 99.0))
        ck('F19 caught: a write the sheets make that the deleted rules file '
           'never made',
           any(x.startswith('P-GONE')
               for x in check_declared_triples(_extra, out=quiet)),
           f'{check_declared_triples(_extra, out=quiet)[:1]}')

    # ---- faults on the state declaration ----------------------------------
    #
    # The state is (expected, found) and BOTH directions of surprise are
    # faulted: a file that is missing when it is declared present and a file
    # that comes back when it is declared gone are different failures, and
    # neither may be silent.
    _here = os.path.abspath(__file__)
    _nowhere = os.path.join(os.path.dirname(_here), 'no-such-rules.json')
    ck('F20 caught: a rules file that comes back when it is declared gone',
       bool(RulesFileState(_here, expected='gone').surprise_problem()))
    ck('F21 caught: a rules file that is missing when it is declared present',
       bool(RulesFileState(_nowhere, expected='present').surprise_problem()))
    ck('F21b control: neither declared-and-agreeing state is a surprise',
       not RulesFileState(_nowhere, expected='gone').surprise_problem()
       and not RulesFileState(_here, expected='present').surprise_problem())
    ck('F21c the state line names what was expected and what was found, either '
       'way',
       'expected gone' in RulesFileState(_nowhere, expected='gone').state_line()
       and 'NOT ON DISK' in RulesFileState(_nowhere, expected='gone').state_line()
       and 'PRESENT' in RulesFileState(_here, expected='present').state_line())

    # F22 the recorded non-run is a REFUSAL underneath, not a clean zero.
    # double_application_not_run() prints a record and returns nothing, and
    # that is only honest if the check it stands in for would REFUSE rather
    # than report "0 converted rule(s), none carry multiply" over a file that
    # is not there.
    try:
        check_double_application(_nowhere, out=quiet)
        ck('F22 caught: DOUBLE-APPLICATION over a missing rules file REFUSES '
           'rather than reporting a clean zero', False, 'it returned')
    except Problem as e:
        ck('F22 caught: DOUBLE-APPLICATION over a missing rules file REFUSES '
           'rather than reporting a clean zero', 'not on disk' in str(e), str(e))
    ck('F22b and the non-run it is replaced by adds no problems and says NOT '
       'RUN by name',
       not double_application_not_run(out=quiet)
       and any('NOT RUN' in m for m in _capture(double_application_not_run)))

    return fails


def _capture(fn):
    lines = []
    fn(out=lines.append)
    return lines


def _pointer_ids(overlay_dir):
    rows = read_csv_rows(os.path.join(overlay_dir, POINTER_FILE), 'the pointer file')
    return {int(r[POINTER_COLUMN]) for r in rows if (r[POINTER_COLUMN] or '').strip()}


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
    ap.add_argument('--out', help='write the sheets here instead of the config dir')
    ap.add_argument('--src', help='the repo root holding mods/CKFHardMode '
                                  '(default: this script\'s repo)')
    ap.add_argument('--write', action='store_true', help='regenerate both sheets')
    ap.add_argument('--check', action='store_true',
                    help='compare the old rules and the new sheets element by element')
    ap.add_argument('--census', action='store_true', help='print the assertions')
    ap.add_argument('--selftest', action='store_true', help='inject faults')
    ap.add_argument('--ruleset-3x', dest='ruleset_3x', action='store_true',
                    help='ALSO run the retired 3.x-conformance comparison '
                         '(P-GONE and UNDECLARED CHANGE) and the selftest '
                         'cases that fault it. Retired from the default '
                         'suite %s %s; what it prints is a divergence from the '
                         '3.0 ruleset, which is not by itself a defect.'
                         % (RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON))
    a = ap.parse_args()

    if not (a.write or a.check or a.census or a.selftest):
        ap.error('one of --write, --check, --census or --selftest is required')

    try:
        cfg, overlay, dump = resolve_dirs(a)
        weapons = load_table(dump, 'WeaponModel.csv', WEAPON_KEY,
                             'the dumped WeaponModel table')
        talents = load_table(dump, 'TalentModel.csv', TALENT_KEY,
                             'the dumped TalentModel table')
    except Problem as e:
        print(f'REFUSED  {e}')
        return 2

    by_sheet, pairs, join_problems = cyber_rows(weapons, talents)
    scope = set(pairs.values())
    rules_path = os.path.join(cfg, RULES_FILE)
    state = RulesFileState(rules_path)
    outdir = a.out or overlay

    print(f'cyberweapons: {len(weapons)} WeaponModel row(s) and {len(talents)} '
          f'TalentModel row(s) from {dump}')
    print(f'cyberweapons: {len(pairs)} weapon/talent pair(s) joined on '
          f'TalentModel.{TALENT_WEAPON_COLUMN} -- '
          + ', '.join(f'{s.name} {len(by_sheet[s.key])} (WeaponClass {s.cls})'
                      for s in SHEETS))

    problems = list(join_problems)
    print(state.state_line())
    _surprise = state.surprise_problem()
    if _surprise:
        problems.append(_surprise)

    if a.write:
        for s in SHEETS:
            text = render_sheet(s, weapons, talents, by_sheet[s.key])
            path = os.path.join(outdir, s.name)
            with io.open(path, 'w', newline='', encoding='utf-8') as fh:
                fh.write(text)
            print(f'cyberweapons: wrote {path} -- {len(by_sheet[s.key])} row(s), '
                  f'{len(s.header)} column(s) ({len(s.columns)} named + _comment), '
                  f'{len(text.encode("utf-8"))} bytes, LF')

    if a.check or a.census or a.selftest:
        sheets, rules = {}, []
        for s in SHEETS:
            path = os.path.join(outdir, s.name)
            try:
                rows = read_sheet(s, path)
            except Problem as e:
                print(f'REFUSED  {e}')
                return 2
            sheets[s.key] = rows
            rep = []
            rules += expand(s, rows, report=rep)
            problems += rep
        print(f'cyberweapons: {sum(len(v) for v in sheets.values())} sheet row(s) '
              f'expanded into {len(rules)} rule(s) '
              f'({len([r for r in rules if r.model == WEAPON_MODEL])} '
              f'{WEAPON_MODEL}, '
              f'{len([r for r in rules if r.model == TALENT_MODEL])} '
              f'{TALENT_MODEL}), '
              f'{sum(len(r.ops) for r in rules)} column write(s)')

        texts = {s.name: render_sheet(s, weapons, talents, by_sheet[s.key])
                 for s in SHEETS}
        for s in SHEETS:
            problems += check_columns(s, weapons, talents, by_sheet[s.key])
        problems += check_claws_blank(rules)
        problems += check_claw_rows_present(by_sheet['claws'], weapons, talents)
        problems += check_shared_rows(talents, scope)
        problems += check_divergent_shared_edits(rules)
        problems += check_no_clone(rules, texts)
        problems += check_enemy_carry(overlay, dump, pairs)
        problems += check_collisions(weapons, talents, dump)
        problems += check_map_matches_plugin(a.src or repo_root())

        if a.check:
            # THE OLD SIDE IS CHOSEN BY THE DECLARED STATE, NOT BY A REFUSAL
            # THAT TAKES THE WHOLE RUN WITH IT.
            #
            # Returning 2 when load_rules_json raises would throw away every
            # check above, none of which reads that file. The old side is the
            # file when the file is there and the transcription when it is
            # not, and the one thing that genuinely has no subject without it
            # -- DOUBLE-APPLICATION -- is recorded as a non-run.
            if state.found:
                try:
                    dprobs, converted, total = check_double_application(rules_path)
                except Problem as e:
                    print(f'REFUSED  {e}')
                    return 2
                problems += dprobs
                print(f'    {RULES_FILE} holds {total} rule(s); '
                      f'{len(converted)} of them are the ones the sheets '
                      f'convert (see DOUBLE-APPLICATION).')
            else:
                problems += double_application_not_run()
            # THE 3.x-CONFORMANCE COMPARISON IS RETIRED FROM HERE (David's
            # rule). See RULESET_3X_RETIRED_WHY. It is a
            # recorded non-run on the default path and runs in full under
            # --ruleset-3x; every other check above ran unconditionally.
            if a.ruleset_3x:
                print(f'    RUNNING the retired 3.x-conformance comparison '
                      f'because {RULESET_3X_RETIRED_FLAG} was passed. It was '
                      f'retired from the default --check by '
                      f'{RULESET_3X_RETIRED_BY}, {RULESET_3X_RETIRED_ON}. '
                      f'What follows is a DIVERGENCE REPORT against the 3.0 '
                      f'ruleset, not a defect list.')
                problems += check_declared_triples(rules)
                old_side, source = resolve_old_side(state, weapons, talents)
                cprobs, diffs, triples = compare(old_side, source, weapons,
                                                 talents, rules, pairs)
                problems += cprobs
            else:
                problems += ruleset_3x_report_retired()

    if a.selftest:
        # REFUSE THE SAME WAY --check DOES. selftest() reads the rules file
        # through the same loader, so its Problem is caught here too: a
        # traceback is not a verdict, and "the subject is gone" and "this
        # instrument broke" mean different things.
        try:
            fails = selftest(state, overlay, dump, a.src or repo_root(),
                             weapons, talents, by_sheet, pairs,
                             run_3x=a.ruleset_3x)
        except Problem as e:
            print(f'REFUSED  {e}')
            return 2
        problems += [f'selftest: {f}' for f in fails]

    for p in problems:
        print(f'PROBLEM  {p}')
    print(f'\n{len(problems)} problem(s).')
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
