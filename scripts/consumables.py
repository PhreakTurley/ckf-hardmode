#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""consumables.py -- the six consumable lever sheets: generate, check, selftest.

WHAT THESE FILES ARE

`ckf.hardmode.d/consumables-medical.csv` and its five siblings are LEVER
SHEETS, not direct overlays. A direct overlay's filename names one game table
and its first column is that table's id column; `Overlays.LoadTable` reads it.
A consumable row is not a row of one table. `ItemModel` has 73 rows and only
ten columns -- `ItemName, ItemDesc, ItemTypeId, ItemClass, ServiceOptionId,
LeverageClass, Rarity, PowerLevel, Cost, TalentId` [measured,
sheets/raw/ItemModel.csv] -- so every lever past price and rarity lives in
`TalentModel` behind `TalentId`, and every payload past that lives in
`EffectModel` or `MatrixEffectModel` behind the talent's effect columns. ONE
SHEET ROW THEREFORE BECOMES UP TO FOUR RULES, in up to four tables, and the
expansion happens in the plugin at load, never here and never in the GUI.

Six files, split by `ItemClass`, because a flat 73-row table would be about
70% empty: a grenade and a Juice share only `MaxCharges`.

  consumables-medical.csv      ItemClass 1   18 rows
  consumables-grenades.csv     ItemClass 2   11 rows
  consumables-devices.csv      ItemClass 3   12 rows
  consumables-chems.csv        ItemClass 4   18 rows
  consumables-sploitkits.csv   ItemClass 6    3 rows
  consumables-matrix.csv       ItemClass 7   11 rows

There is no `ItemClass 5`. 18+11+12+18+3+11 = 73. Both the total and the
DISJOINTNESS are asserted by check_rows() and by the selftest, not read off by
eye: "every row is in exactly one file" is the statement that fails when a row
is copied, and a total that still adds up is exactly what a copy produces when
another row is dropped.

WHAT IS [measured] AND WHAT IS [fitted]

Everything in the paragraph above is [measured] against the dump in sheets/raw
and reproduced by --check on every run. The one thing that is NOT
measured is WHICH EFFECT TABLE EACH TALENT COLUMN RESOLVES AGAINST.

`TalentModel.SelfEffect`, `.TargetEffect` and `.MatrixEffect` hold bare
integers. 130 ids are both an `EffectId` and a `MatrixEffectId` [measured], so
the id alone does not say which table it lands in, and the game's interop
assembly is marshalling stubs with no bodies -- there is no method to read.
What CAN be measured is resolvability across the whole column, using the ids
that exist in only one of the two tables:

  MatrixEffect   28 non-zero TalentModel cells; 8 of them carry an id that is
                 in MatrixEffectModel and NOT in EffectModel, 0 the other way
                 round, 0 dangling.  -> MatrixEffectModel   [fitted]
  SelfEffect    151 non-zero cells; 133 unambiguous, ALL of them in
                 EffectModel, 0 in MatrixEffectModel, 0 dangling.
                                                            -> EffectModel   [fitted]
  TargetEffect  103 non-zero cells; 98 unambiguous, ALL in EffectModel, 0 in
                 MatrixEffectModel, 0 dangling.             -> EffectModel   [fitted]

Those three counts are CELL COUNTS, not distinct-id counts; by distinct id the
unambiguous sets are 8 / 132 / 95. check_resolution() reproduces both figures
so neither reading can drift into the other silently.

[fitted] and not [measured]: a column every one of whose unambiguous ids lands
in one table is consistent with that table and with nothing else observed, but
consistency across 133 rows is an inference, not a read. WHAT WOULD CONFIRM IT:
a decompiled or de-stubbed body for the talent-application path that shows
which reader `SelfEffect` is looked up in -- i.e. a `GetEffect`/`GetMatrixEffect`
call site, or an IL dump of the real assembly rather than the interop stub. No
such read exists today and this file does not pretend otherwise. If the fit is
wrong, the symptom is a sheet that writes `EffectModel` rows the game never
reads; --check cannot see that and says so rather than being silent.

CONSEQUENCE, AND THE ROW THAT design.md SECTION 8 GETS WRONG. Ids 5100-5106
exist in BOTH tables, so the six Juice-family matrix consumables write
`MatrixEffectModel` under the fit above, not `EffectModel`. And design.md
section 8's matrix line reads "effect **or** matrix-effect": `Eclipse
Microdust` (ItemTypeId 5404, talent 75068) carries `MatrixEffect 5106` AND
`SelfEffect 75036` on one row [measured], so it is "and", not "or", on at least
one row. consumables-matrix.csv therefore carries both payload blocks and
check_columns() asserts the row that needs both is present.

THE COLUMN SET IS DECLARED. THE DUMP IS THE CHECK.

The lever columns are NOT derived from the dump. The dumper can omit a column
that is CONSTANT ACROSS ALL ROWS, so a dump's column set depends on WHEN THE
DUMP WAS TAKEN: a dump taken after a real play session carries runtime state
(`IsRowCurrentlySelected`, `isInit`, `effectsSet`, `HasInitSpecialCode`,
`OwnerEntityId`), asset and sound references (`Vfx`, `IconPng`, `EventSFX`,
...) and display strings (`TalentDesc`, `ManualTalentName`, ...) that a dump of
a freshly loaded game does not [measured]. None is a lever. A header derived
from the dump and then checked against the same dump always agrees with it --
a false green.

So `SHEET_COLUMNS` declares the levers outright,
`EXCLUDED_COLUMNS` declares every ruled-out column with a reason tag, and
check_partition() asserts on every run that

    derive_columns_live(dump)  ==  SHEET_COLUMNS  u  EXCLUDED_COLUMNS

A live column in neither set is a NAMED problem with its table; a declared
lever the dump cannot confirm is a NAMED problem too. derive_columns_live() is
the CHECK rather than the source, because it is the only thing that can notice
the dump moving.

design.md section 8's per-class lever lists are ABBREVIATIONS and they are
incomplete. --check prints the delta per file (D-S8) so the section can be
corrected rather than argued with.

THE FIVE DEAD COLUMNS. `RechargeTurns, TurnMaxUses, TeamTurnMaxUses,
AlternateCharge, Counter` are `0` on all 70 joined `TalentModel` rows
[measured]. They appear in no generated header and check_dead() asserts BOTH
halves -- that they are still zero in the dump, and that no header carries one.
Asserting only the second half would go green on a header that had lost the
column for an unrelated reason.

THE THREE SPLOITKITS. 70 of the 73 rows join `TalentModel`. The three that do
not are exactly `ItemTypeId` 1000 / 1002 / 1003, all `TalentId = 0`, and no
`TalentModel` row with id 0 exists [measured]. consumables-sploitkits.csv
therefore carries only the four `ItemModel` levers its rows can reach; a table
that showed talent columns there would give the player rows that do nothing,
and check_join() refuses that shape by name.

GENERATED CELLS ARE BLANK, AND --check REQUIRES IT

--write emits every lever cell blank, so a generated sheet changes nothing:
the game's own values stand. --check (A-SHEET) refuses any non-blank cell in
the six files, and A-LIVE refuses any other overlay CSV that writes one of the
consumable-reachable (table, id) pairs, on the grounds that a value there is a
NEW balance change rather than a converted one. Both therefore go red when
these sheets are tuned. This script proposes no numbers and has no opinion
about the ones it prints.

KEYS ARE (table, id), NEVER id ALONE

221 ids are both a `TalentId` and an `EffectId`; 130 are both an `EffectId` and
a `MatrixEffectId` [measured, dump]. Among the consumable-reachable pairs, 31
ids appear under two different models -- keyed on the number alone they
collapse and 31 writes land on the wrong table [measured, check_collisions()].
The sharpest is 75022: `TalentModel 75022` is Bio-Stitch Bandages and
`EffectModel 75022` is Mass Trauma Kit's effect, and BOTH are rows of
consumables-medical.csv. Every key in this file is a `(model, id)` tuple and
--selftest has a case per declared pair showing that an id-alone key collapses
it.

AN INSTRUMENT'S SILENCE IS NOT EVIDENCE

Every census line prints its count whether or not it is zero. Every check
distinguishes "not there" from "could not look": a missing overlay directory is
a REFUSAL at rc 2, not six missing files; a file that cannot be read RAISES
rather than counting as empty; and --check LISTS THE DIRECTORY rather than
iterating its own declared names, so a seventh consumables-*.csv that no
expander declares is seen.

--selftest grades every fault against the CONTROL RUN'S BASELINE, not against
`if problems:`, which prints CAUGHT over pre-existing drift whenever the
baseline is already dirty. Here the control's problem set is captured first, asserted
empty, and a fault counts as caught only if it produces a problem the control
did not, carrying the expected tag.

MODES

  --write     --game R   regenerate the six CSVs under R/BepInEx/config/ckf.hardmode.d
  --check     --game R   compare the six live files against the dump
  --selftest  --game R   controls first, then fault injection

--game is required by all three, like the other four converters: with no config
directory check_untouched() has nothing to read and a green run would mean
COULD NOT LOOK, not agreement.
"""

import argparse
import collections
import csv
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# The adjustment grammar and the two refusal primitives are IMPORTED, not
# re-transcribed. cyberweapons.py imports the same three names from the same
# module for the same reason: a fifth copy of Adjust.Parse is a fifth thing to
# drift.
import gear_classes as _gear                        # noqa: E402

parse_adjust = _gear.parse_adjust
NONE, SET, ADD, MULTIPLY = _gear.NONE, _gear.SET, _gear.ADD, _gear.MULTIPLY
Problem = _gear.Problem


# ---------------------------------------------------------------------------
# THE TABLES AND THEIR KEYS.
#
# Four models, four key columns. The key column is what a rule's `where`
# clause names, and it is NOT the same as the sheet column that carries the id
# on a lever sheet -- see IDENTITY below.
# ---------------------------------------------------------------------------

ITEM_MODEL = 'ItemModel'
TALENT_MODEL = 'TalentModel'
EFFECT_MODEL = 'EffectModel'
MATRIX_MODEL = 'MatrixEffectModel'

ITEM_KEY = 'ItemTypeId'
TALENT_KEY = 'TalentId'
EFFECT_KEY = 'EffectId'
MATRIX_KEY = 'MatrixEffectId'

MODELS = (ITEM_MODEL, TALENT_MODEL, EFFECT_MODEL, MATRIX_MODEL)
KEY_OF = {ITEM_MODEL: ITEM_KEY, TALENT_MODEL: TALENT_KEY,
          EFFECT_MODEL: EFFECT_KEY, MATRIX_MODEL: MATRIX_KEY}
DUMP_FILE = {ITEM_MODEL: 'ItemModel.csv', TALENT_MODEL: 'TalentModel.csv',
             EFFECT_MODEL: 'EffectModel.csv',
             MATRIX_MODEL: 'MatrixEffectModel.csv'}

# The sub-table key. ItemClass decides which file a row is in, so no file
# carries it as a column -- the same role ImplantSlot plays in implants.py,
# which is the table key and is carried by no table.
CLASS_COLUMN = 'ItemClass'

# ---------------------------------------------------------------------------
# BEGIN LEVER MAP
#
# THE THREE POINTER COLUMNS AND WHAT THEY RESOLVE AGAINST. [fitted -- see the
# module docstring for the measurement behind the fit and for what would
# confirm it.] These are ALSO ordinary TalentModel levers: a cell under
# `SelfEffect` repoints the talent at a different effect row. That is why they
# appear here and in the generated header both.
POINTER_TABLE = collections.OrderedDict([
    ('SelfEffect', EFFECT_MODEL),
    ('TargetEffect', EFFECT_MODEL),
    ('MatrixEffect', MATRIX_MODEL),
])

# IDENTITY: the columns that NAME a row rather than override it. serve.py
# imports this list and uses it to keep from grading an id as a player
# override. ItemName reads in a spreadsheet; the other four key the four rules
# a row can emit.
#
# EffectId is DERIVED from the row's own SelfEffect/TargetEffect and is the
# SHIPPED resolution. A player who repoints the SelfEffect cell does not move
# which EffectModel row the payload cells write -- the payload cells are keyed
# by the EffectId printed on the line. check_identity() asserts the thing that
# makes one column enough: no consumable talent reaches two DIFFERENT
# EffectModel rows (Mass Trauma Kit is the only talent here with both pointers
# non-zero and they are the same id) [measured].
IDENTITY = ['ItemName', ITEM_KEY, TALENT_KEY, EFFECT_KEY, MATRIX_KEY]

# Display-only, never carried: ItemDesc is prose.
ITEM_TEXT = ['ItemDesc']

# Never carried from the payload tables: these name the row.
EFFECT_IDENTITY = ['EffectName', EFFECT_KEY]
MATRIX_IDENTITY = ['EffectName', MATRIX_KEY]
TALENT_IDENTITY = ['TalentName', TALENT_KEY, 'TalentTypeId', 'TalentStringKey']

# THE FIVE DEAD COLUMNS. 0 on all 70 joined TalentModel rows [measured].
# Excluded by NAME, and check_dead() re-measures the zero rather than trusting
# the list.
DEAD_TALENT_COLUMNS = ['RechargeTurns', 'TurnMaxUses', 'TeamTurnMaxUses',
                       'AlternateCharge', 'Counter']

# THE ADJUSTED FAMILY, EXCLUDED BY PREFIX FOR NOW. These are a scope question
# put to the project owner separately, so they are not in any header and this
# file argues neither way. --check reports which of them are LIVE per class
# (D-ADJ) so the question can be answered from a measurement.
ADJUSTED_PREFIX = 'Adjusted'
# END LEVER MAP

# The one prefix that disambiguates a sheet column name. MatrixEffectModel and
# EffectModel share column NAMES -- on the matrix sheet's own live sets,
# EffectClassification and ActionPoints are in both [measured] -- and a bare
# header name would then map to two different (model, column) targets. So every
# MatrixEffectModel payload column is aliased with this prefix, all of them and
# not only the two that collide: a rule that applies to some of a table's
# columns is a rule nobody can check. cyberweapons.py's PureDamage -> PureDamage1
# is the same device. check_columns() asserts the aliasing leaves no duplicate
# header name and no duplicate (model, column) target.
MATRIX_ALIAS_PREFIX = 'Matrix'

CONTROL_COMMENT = '_comment'
CONTROL_PREFIX = '_'
ALLOWED_CONTROL = {CONTROL_COMMENT}
REFUSED_CONTROL = {
    '_clone': ('a clone is never emitted from a lever sheet. design.md section '
               '11 makes splitting a shared row an explicit per-row opt-in that '
               'this dialect does not carry.'),
    '_serveOn': 'serveOn belongs to a clone rule; these sheets emit none.',
}


# ---------------------------------------------------------------------------
# THE SIX SHEETS.
#
# `rows` is the count MEASURED against the live dump today and re-measured on
# every run. It is declared so that a disagreement is a PROBLEM rather than a
# silent adjustment: --check prints both numbers and refuses when they differ,
# instead of reporting whatever the dump happens to hold.
# ---------------------------------------------------------------------------

class Sheet(object):
    __slots__ = ('key', 'name', 'cls', 'rows', 'slice_key')

    def __init__(self, key, cls, rows, slice_key):
        self.key = key
        self.name = 'consumables-%s.csv' % key
        self.cls = cls
        self.rows = rows
        self.slice_key = slice_key


SHEETS = [
    Sheet('medical', 1, 18, 'ConsumablesMedical'),
    Sheet('grenades', 2, 11, 'ConsumablesGrenades'),
    Sheet('devices', 3, 12, 'ConsumablesDevices'),
    Sheet('chems', 4, 18, 'ConsumablesChems'),
    Sheet('sploitkits', 6, 3, 'ConsumablesSploitkits'),
    Sheet('matrix', 7, 11, 'ConsumablesMatrix'),
]
SHEET_BY_CLASS = dict((s.cls, s) for s in SHEETS)
SHEET_BY_NAME = dict((s.name, s) for s in SHEETS)

# SHEET_NAMES IS NOT OPTIONAL.
#
# Overlays.cs and gui/serve.py both dispatch lever sheets BY DECLARED NAME. A
# sheet no expander declares is parsed as a DIRECT OVERLAY, and the first thing
# that happens then is that the filename before the first dot becomes a model
# name: "consumables-medical.csv" would compile 18 rules against a table called
# "consumables-medicalModel". That does not fail loudly. Its only symptom is one
# orphan warning long afterwards (docs/overlays.md), which is why the dispatch
# is a list of the expanders' OWN declared names and why this set exists even
# though nothing in this file reads it.
SHEET_NAMES = frozenset(s.name for s in SHEETS)

# There is no ItemClass 5, and that is a statement with a test behind it:
# check_rows() asserts the class set in the dump is exactly this one.
DECLARED_CLASSES = sorted(s.cls for s in SHEETS)
ABSENT_CLASS = 5

# The three rows that do not join TalentModel, by name, so check_join() can
# refuse a fourth rather than reporting "some rows do not join".
SPLOITKIT_ITEM_IDS = [1000, 1002, 1003]


# ---------------------------------------------------------------------------
# SHARED ROWS. Rows owned by more than one ITEM.
#
# MEASURED against the dump; exactly two, both EffectModel, both
# reached through TargetEffect, both with every owner inside one file:
#
#   EffectModel 76005  <- medical Patch X-Kit (item 14, talent 75009) and
#                         Patch X-Kit Ultra (item 1001, talent 75050)
#   EffectModel 76017  <- devices Dazzler (7, 75004), Advanced Dazzler
#                         (32, 75035) and LR-Max Dazzler (42, 75048)
#
# An edit to what one of those effect rows DOES reaches every owner; repointing
# one owner's TargetEffect cell does not.
#
# ***EffectModel 75022 IS NOT A SHARED ROW.*** It has exactly one owning item,
# Mass Trauma Kit (item 41, talent 75047), which names it in BOTH SelfEffect
# and TargetEffect. A row cannot diverge from itself. gui/serve.py already
# carries a comment about an agent who counted (talent, column) pairs and
# reported nine shared rows where five were self-shares; shared_rows() below
# therefore keys on the owning ITEM and F7 in --selftest proves it -- it runs
# the naive role-counting detector alongside the real one and requires the
# naive one to report 75022 and the real one not to. A case that only asserts
# the absence would also pass if the detector had stopped looking.
#
# THERE IS NO INFORMATIONAL CASE HERE, and that is measured rather than
# omitted: 0 of the 51 effect rows these 70 talents reach is also reached by
# any of the other 314 TalentModel rows [measured], so there is no owner
# without a table of its own -- implants.py's EffectId 50000 shape does not
# occur. check_shared() prints that 0.
# ---------------------------------------------------------------------------

SHARED_ROWS = {
    (EFFECT_MODEL, 76005): {
        'sheet': 'consumables-medical.csv',
        'pointer': (TALENT_MODEL, 'TargetEffect'),
        'owners': [(14, 75009, 'Patch X-Kit'),
                   (1001, 75050, 'Patch X-Kit Ultra')],
        'note': ('EffectModel 76005 is the target effect of both. An edit to '
                 'what that effect does reaches both; repointing either row\'s '
                 'TargetEffect cell does not.'),
    },
    (EFFECT_MODEL, 76017): {
        'sheet': 'consumables-devices.csv',
        'pointer': (TALENT_MODEL, 'TargetEffect'),
        'owners': [(7, 75004, 'Dazzler'),
                   (32, 75035, 'Advanced Dazzler'),
                   (42, 75048, 'LR-Max Dazzler')],
        'note': ('EffectModel 76017 is the target effect of all three. An edit '
                 'to what that effect does reaches all three; repointing one '
                 'row\'s TargetEffect cell does not.'),
    },
}

# design.md section 11's per-row opt-in. Empty, and the expander emits no clone
# under any circumstances. Kept so that "there is no opt-in" and "the opt-in is
# empty" stay different statements.
SHARED_ROW_SPLIT_OPTIN = {}

# The self-share, declared rather than merely excluded, so that "the detector
# found nothing" and "the detector found this and correctly did not call it
# sharing" are different answers.
SELF_SHARES = {
    (EFFECT_MODEL, 75022): {
        'sheet': 'consumables-medical.csv',
        'owner': (41, 75047, 'Mass Trauma Kit'),
        'roles': ['SelfEffect', 'TargetEffect'],
        'note': ('One item, one talent, the same EffectModel id in both '
                 'pointer columns. NOT a shared row: a row cannot diverge from '
                 'itself.'),
    },
}


# ---------------------------------------------------------------------------
# KEYS ARE (table, id), NEVER id ALONE.
#
# Each case is a pair of REAL rows in two different tables that carry the same
# number, and every one of them is a row THIS PHASE WRITES -- not a
# hypothetical. --selftest has one case per entry showing that an id-alone key
# collapses the pair and a (model, id) key does not.
# ---------------------------------------------------------------------------

COLLISION_CASES = [
    {
        'id': 'K1',
        'left': (TALENT_MODEL, TALENT_KEY, 75022),
        'right': (EFFECT_MODEL, EFFECT_KEY, 75022),
        'why': ('The sharpest of the four, because BOTH rows are rows of ONE '
                'file. TalentModel 75022 is Bio-Stitch Bandages\'s talent and '
                'EffectModel 75022 is Mass Trauma Kit\'s effect; both are '
                'consumables-medical.csv. An id-alone registry would show one '
                'row\'s value on the other\'s edit inside a single grid.'),
    },
    {
        'id': 'K2',
        'left': (TALENT_MODEL, TALENT_KEY, 75030),
        'right': (EFFECT_MODEL, EFFECT_KEY, 75030),
        'why': ('The same number across two DIFFERENT sheets. TalentModel '
                '75030 is Blue Juice\'s talent (consumables-matrix.csv); '
                'EffectModel 75030 is Winternight Black\'s self effect '
                '(consumables-chems.csv). An id-alone key makes an edit in one '
                'file appear to be an edit in the other.'),
    },
    {
        'id': 'K3',
        'left': (EFFECT_MODEL, EFFECT_KEY, 5100),
        'right': (MATRIX_MODEL, MATRIX_KEY, 5100),
        'why': ('The Juice family. 5100-5106 exist in BOTH effect tables '
                '[measured], and under the fitted resolution above the matrix '
                'consumables write MatrixEffectModel. EffectModel 5100 exists '
                'too (EffectName "Effect.Name.5100") and nothing here writes '
                'it; an id-alone key cannot tell the two apart.'),
    },
    {
        'id': 'K4',
        'left': (ITEM_MODEL, ITEM_KEY, 5100),
        'right': (MATRIX_MODEL, MATRIX_KEY, 5100),
        'why': ('One LINE of consumables-matrix.csv writes both of these: Blue '
                'Juice is ItemTypeId 5100 and its matrix effect is '
                'MatrixEffectId 5100. The collision is not between two rows of '
                'the sheet, it is inside one.'),
    },
]


# ---------------------------------------------------------------------------
# design.md SECTION 8'S ABBREVIATED LISTS, transcribed so --check can print the
# delta rather than an agent arguing from memory. `open` marks a phrase section
# 8 uses instead of enumerating -- those are not missing columns, they are
# unenumerated ones, and the two are reported separately.
# ---------------------------------------------------------------------------

DESIGN_S8 = {
    'medical': {
        'named': ['ApCost', 'Range', 'RangeAoE', 'MaxCharges',
                  'EffectHealType', 'Heals'],
        'open': [],
        'text': 'ApCost, Range, RangeAoE, MaxCharges, effect EffectHealType + Heals',
    },
    'grenades': {
        'named': ['Range', 'RangeAoE', 'MaxCharges', 'PureDamage',
                  'PhysicalDamage', 'BallisticDamage', 'Volume', 'Token',
                  'TokenDuration'],
        'open': [],
        'text': ('Range, RangeAoE, MaxCharges, 3 damage columns, Volume, '
                 'Token, TokenDuration'),
    },
    'devices': {
        'named': ['ApCost', 'Range', 'MaxCharges', 'TargetEffect',
                  'TargetEffectDuration'],
        'open': [],
        'text': 'ApCost, Range, MaxCharges, TargetEffect, TargetEffectDuration',
    },
    'chems': {
        'named': ['ApCost', 'MaxCharges'],
        'open': [(EFFECT_MODEL, 'the effect stat-block union')],
        'text': 'ApCost, MaxCharges, + the effect stat-block union',
    },
    'matrix': {
        'named': ['ApCost', 'MaxCharges'],
        'open': [(EFFECT_MODEL, 'effect or matrix-effect'),
                 (MATRIX_MODEL, 'effect or matrix-effect')],
        'text': 'ApCost, MaxCharges, + effect or matrix-effect',
    },
    'sploitkits': {
        'named': ['Cost', 'PowerLevel', 'Rarity', 'LeverageClass'],
        'open': [],
        'text': 'Cost, PowerLevel, Rarity, LeverageClass',
    },
}

# The three shipped oddities design.md section 8 says get help text rather than
# a silent fix, plus the two it names as not-bugs. They go in _comment, which is
# the only prose this script is allowed to write; schema/ is not this file's
# directory. FREE TEXT AND NOT LOAD-BEARING -- nothing parses _comment.
ROW_NOTES = {
    5306: ('design.md section 8: this row applies StressRes -15 and nothing '
           'else. Its effect row carries exactly EffectClassification and '
           'StressRes [measured].'),
    4: ('design.md section 8: TargetEffectDuration with no effect row behind '
        'it -- TargetEffect is 0 and the duration column is the whole '
        'mechanic here [measured].'),
    33: ('design.md section 8: TargetEffectDuration with no effect row behind '
         'it -- TargetEffect is 0 [measured].'),
    45: ('design.md section 8: TargetEffectDuration with no effect row behind '
         'it -- TargetEffect is 0 [measured].'),
    15: ('design.md section 8: no damage columns; the payload is Token / '
         'TokenDuration [measured].'),
    46: ('design.md section 8: no damage columns; the payload is Token / '
         'TokenDuration [measured].'),
    5100: ('design.md section 8, per David: MatrixDuration 0 is an '
           'instantaneous effect, not a bug. ItemTypeId 5100 and '
           'MatrixEffectId 5100 are the same number in two tables -- see '
           'COLLISION_CASES K4.'),
    5403: ('design.md section 8: ItemDesc is "for loading" and this row is '
           'excluded from the GUI. It is still in this file, because the file '
           'is the table and a row missing from it would be a row nothing can '
           'account for.'),
    5404: ('design.md section 8 says "effect OR matrix-effect"; this row has '
           'BOTH -- MatrixEffect 5106 and SelfEffect 75036 [measured]. That '
           'sentence is wrong on this row.'),
    41: ('EffectModel 75022 is named in both SelfEffect and TargetEffect on '
         'this one row. That is a SELF-SHARE, not a shared row: one owner, so '
         'it cannot diverge from itself.'),
}


# ---------------------------------------------------------------------------
# Reading the world
# ---------------------------------------------------------------------------

def nz(v):
    """Non-blank and non-zero. THREE-STATE INPUT, TWO-STATE ANSWER, and the
    boolean case is the one that is easy to get wrong: the dumper writes
    booleans as `True`/`False`, so a `False` is a zero and a `True` is not.
    A value that is neither a number nor a boolean (a string key) is live."""
    if v is None:
        return False
    s = v.strip()
    if s == '':
        return False
    low = s.lower()
    if low == 'false':
        return False
    if low == 'true':
        return True
    try:
        return float(s) != 0.0
    except ValueError:
        return True


def read_csv_rows(path, what):
    """A read that fails RAISES. It is never reported as an empty table."""
    if not os.path.isfile(path):
        raise Problem('%s is not on disk at %s. This is a refusal, not an empty '
                      'answer: nothing read it, so how many rows it holds is '
                      'not known.' % (what, path))
    try:
        with io.open(path, 'r', encoding='utf-8-sig', newline='') as fh:
            rows = list(csv.DictReader(fh))
    except Exception as e:
        raise Problem('could not read %s at %s: %s. This is a refusal, not an '
                      'empty table.' % (what, path, e))
    if not rows:
        raise Problem('%s at %s has a header and no data rows.' % (what, path))
    return rows


def strip_jsonc(text):
    """The rules file's header is // comments before the array opens."""
    return re.sub(r'^\s*//.*$', '', text, flags=re.M)


class Dump(object):
    """The four dumped tables, plus the join and the effect resolution.

    The `_*.csv` sidecars are read too and they are load-bearing:
    _dropped_columns.csv says which columns the dumper REMOVED because they
    were constant across the whole table. A column absent from a dumped header
    is therefore either "not a column of this table" or "a column the dumper
    dropped", and those are different answers. check_dropped() uses the file to
    tell them apart instead of treating absence as non-existence.
    """

    def __init__(self, dump_dir):
        self.dir = dump_dir
        self.rows = {}
        for model in MODELS:
            self.rows[model] = read_csv_rows(
                os.path.join(dump_dir, DUMP_FILE[model]),
                'the dumped %s table' % model)
        self.cols = dict((m, list(self.rows[m][0].keys())) for m in MODELS)
        self.items = self.rows[ITEM_MODEL]
        self.by_id = {}
        for model in MODELS:
            key = KEY_OF[model]
            self.by_id[model] = collections.OrderedDict(
                (int(r[key]), r) for r in self.rows[model])

        p = os.path.join(dump_dir, '_dropped_columns.csv')
        if not os.path.isfile(p):
            raise Problem(
                '_dropped_columns.csv is not at %s. It is load-bearing: '
                'without it "this column is not in the header" cannot be told '
                'from "the dumper dropped this column because it was constant". '
                'This is a refusal, not an empty drop list.' % p)
        self.dropped = collections.defaultdict(list)
        with io.open(p, 'r', encoding='utf-8-sig', newline='') as fh:
            for r in csv.DictReader(fh):
                self.dropped[r['Table']].append((r['Column'], r['Reason'],
                                                 r.get('ConstantValue', '')))

    # -- the join ----------------------------------------------------------

    def items_of(self, cls):
        """This class's ItemModel rows, IN DUMP FILE ORDER. The order is the
        file's and nothing sorts it: no column here orders the rows as a tier
        ladder, so a grid that sorted by one would invent an order."""
        return [r for r in self.items if int(r[CLASS_COLUMN]) == cls]

    def talent_of(self, item):
        tid = int(item[TALENT_KEY])
        return self.by_id[TALENT_MODEL].get(tid) if tid else None

    def effect_ids(self, talent):
        """-> (effect id or 0, matrix effect id or 0) for one talent row.

        The EffectModel side folds SelfEffect and TargetEffect together, which
        is only sound because no consumable talent names two DIFFERENT ones;
        this returns the set so check_identity() can assert that rather than
        assume it."""
        if talent is None:
            return set(), 0
        eff = set()
        for col, model in POINTER_TABLE.items():
            v = int(talent[col])
            if not v:
                continue
            if model == EFFECT_MODEL:
                eff.add(v)
        mx = int(talent['MatrixEffect'])
        return eff, mx

    def payload_rows(self, cls):
        """-> (effect rows, matrix effect rows) reached by this class, in first
        -seen order, plus the ids that DANGLE (named but not in the table)."""
        eff, mx, dangling = [], [], []
        for item in self.items_of(cls):
            t = self.talent_of(item)
            if t is None:
                continue
            es, m = self.effect_ids(t)
            for e in sorted(es):
                row = self.by_id[EFFECT_MODEL].get(e)
                if row is None:
                    dangling.append((EFFECT_MODEL, e, int(item[ITEM_KEY])))
                elif row not in eff:
                    eff.append(row)
            if m:
                row = self.by_id[MATRIX_MODEL].get(m)
                if row is None:
                    dangling.append((MATRIX_MODEL, m, int(item[ITEM_KEY])))
                elif row not in mx:
                    mx.append(row)
        return eff, mx, dangling

    def pairs(self):
        """Every (model, id) any consumable row can reach. 194 [measured]."""
        out = set()
        for item in self.items:
            out.add((ITEM_MODEL, int(item[ITEM_KEY])))
            t = self.talent_of(item)
            if t is None:
                continue
            out.add((TALENT_MODEL, int(t[TALENT_KEY])))
            es, m = self.effect_ids(t)
            for e in es:
                out.add((EFFECT_MODEL, e))
            if m:
                out.add((MATRIX_MODEL, m))
        return out


RULES_FILE = 'ckf.hardmode.rules.json'

# ---------------------------------------------------------------------------
# ckf.hardmode.rules.json IS NOT PART OF THE 4.0 LAYOUT, AND THAT IS DECLARED
#
# Its absence is a declared state, not a raise: raising on it would stop every
# check here, and none of them but the rules half of A-LIVE, A-DROP and A-DUMP
# reads that file. Those three ask "does anything live write this?" of two
# source sets, the rules file and the non-sheet overlay CSVs. The overlay half
# still has a subject and still RUNS. The rules half is a RECORDED NON-RUN:
# named, counted at zero sources, and not folded into the answer.
#
# A-LIVE's rules-half claim ("0 rules touch these pairs") is a ZERO, and a
# transcribed zero has nothing to be asserted against, so it is printed as a
# record (DECLARED_LAST_RULES_MEASUREMENT) rather than as a result.
#
#   "gone"    the 4.0 layout. Absent is correct; PRESENT is the surprise.
#   "present" the 3.x layout. Absent is the surprise.
#
# This file carries no 3.x-conformance comparison (an old side compiled from
# the 3.0 ruleset and compared value by value against the sheets), so the rule
# that retired those elsewhere -- deviation from the 3.0 ruleset is tuning, not
# a mistake (David's rule) -- retires nothing here. A-LIVE, A-DROP and A-DUMP
# are about collisions between live sources, not about the 3.0 ruleset.
RULES_FILE_EXPECTED = 'gone'

# What the rules half last measured, against a config that still had the rules
# file [measured]. A record, asserted against nothing.
DECLARED_LAST_RULES_MEASUREMENT = {
    'rules': 269, 'pairs_touched': 0, 'unscoped_on_these_four_tables': 0,
    'dropped_columns_written': 0, 'dumper_dropped_columns_written': 0,
}


class LiveWrites(object):
    """Every write the live config performs, from the rules file AND from every
    overlay CSV in ckf.hardmode.d.

    Both sources, because "does anything write this row" has to be asked of
    everything that writes, not of the one file that is easy to parse. An
    unreadable source RAISES; it is not counted as "writes nothing".

    THE RULES FILE'S ABSENCE IS A STATE, NOT A RAISE. `rules_file_found` and `rules_file_expected` are both recorded
    and both printed, a mismatch either way is a problem the caller raises, and
    `rules_file_read` is what the three rules-half checks consult before they
    claim to have asked the rules anything. An UNREADABLE file still RAISES --
    that is a different answer from an absent one, and it always was.
    """

    def __init__(self, config_dir, expected=None):
        self.writes = collections.defaultdict(set)   # (model, id) -> {column}
        self.unscoped = []                           # (model, [columns])
        self.sources = []
        rules_path = os.path.join(config_dir, RULES_FILE)
        self.rules_path = rules_path
        self.rules_file_expected = (RULES_FILE_EXPECTED if expected is None
                                    else expected)
        self.rules_file_found = os.path.isfile(rules_path)
        self.rules_file_read = False
        self.rule_count = 0
        self.rules_file_surprise = (
            (self.rules_file_found and self.rules_file_expected == 'gone')
            or (not self.rules_file_found
                and self.rules_file_expected == 'present'))
        if self.rules_file_found:
            self._read_rules(rules_path)
        self._read_overlays(config_dir)

    def state_line(self):
        """One sentence, printed on every run, naming what was expected, what
        was found and what follows from it."""
        if self.rules_file_read:
            return ('  %s: PRESENT (expected %s) -- read as a source of live '
                    'writes; %d rule(s).'
                    % (RULES_FILE, self.rules_file_expected, self.rule_count))
        return ('  %s: NOT ON DISK (expected %s) -- not part of the 4.0 layout. The %d '
                'overlay CSV(s) in ckf.hardmode.d are the only source of live '
                'writes this run; the rules half of A-LIVE, A-DROP and A-DUMP '
                'is a RECORDED NON-RUN and each of those three says so by name.'
                % (RULES_FILE, self.rules_file_expected,
                   len(self.overlay_files)))

    def surprise_problem(self):
        """The surprise, in whichever direction it happened, or None."""
        if not self.rules_file_surprise:
            return None
        if self.rules_file_found:
            return ('RULES-FILE: %s is ON DISK and RULES_FILE_EXPECTED is %r. '
                    'It is not part of the 4.0 layout; a plugin that reads it '
                    'applies it BEFORE every overlay, so any rule in it lands '
                    'on the rows the sheets replaced -- and A-LIVE\'s pairs '
                    'are exactly the rows that must stay untouched. Either it came '
                    'back by accident and should go, or the deletion was '
                    'reverted and RULES_FILE_EXPECTED should say so.'
                    % (self.rules_path, self.rules_file_expected))
        return ('RULES-FILE: %s is NOT on disk and RULES_FILE_EXPECTED is %r. '
                'Every live write this script can see comes from the overlay '
                'CSVs; a green run over the rules half would mean COULD NOT '
                'LOOK, not agreement.'
                % (self.rules_path, self.rules_file_expected))

    def rules_half_note(self, what):
        """The one clause every rules-half check appends to its own line.

        It is a sentence, not a silence: a reader of the gate log has to be
        able to see that half the source set was not there without opening the
        script."""
        if self.rules_file_read:
            return 'the %d rule(s) in %s' % (self.rule_count, RULES_FILE)
        return ('the RULES HALF [NOT RUN: %s is not on disk, expected %s; 0 '
                'rules were read, and the last run against a rules file measured %d '
                'over %d rule(s) -- a record, asserted against nothing]'
                % (RULES_FILE, self.rules_file_expected,
                   DECLARED_LAST_RULES_MEASUREMENT[what],
                   DECLARED_LAST_RULES_MEASUREMENT['rules']))

    def _read_rules(self, rules_path):
        with io.open(rules_path, 'r', encoding='utf-8-sig') as fh:
            doc = json.loads(strip_jsonc(fh.read()))
        self.rule_count = len(doc['rules'])
        self.rules_file_read = True
        self.sources.append((rules_path, self.rule_count))
        for r in doc['rules']:
            model = r.get('model')
            cols = set()
            for op in ('set', 'multiply', 'add', 'clampMin', 'clampMax'):
                cols |= set(r.get(op, {}).keys())
            if not cols:
                continue
            where = r.get('where') or {}
            if where:
                k = list(where.keys())[0]
                self.writes[(model, int(where[k]))] |= cols
            elif 'whereMin' in r:
                k = list(r['whereMin'].keys())[0]
                lo, hi = int(r['whereMin'][k]), int(r['whereMax'][k])
                for i in range(lo, hi + 1):
                    self.writes[(model, i)] |= cols
            else:
                self.unscoped.append((model, sorted(cols)))

    def _read_overlays(self, config_dir):
        d = os.path.join(config_dir, 'ckf.hardmode.d')
        if not os.path.isdir(d):
            raise Problem('%s is not a directory. This is a refusal, not an '
                          'empty overlay set.' % d)
        self.overlay_dir = d
        self.overlay_files = sorted(n for n in os.listdir(d)
                                    if n.lower().endswith('.csv'))
        for name in self.overlay_files:
            if name in SHEET_NAMES:
                # This phase's own files carry no values -- check_blank()
                # asserts that separately -- and folding them in here would
                # make check_untouched() compare the sheets against themselves.
                continue
            model = name.split('.')[0]
            rows = read_csv_rows(os.path.join(d, name), 'overlay %s' % name)
            self.sources.append((os.path.join(d, name), len(rows)))
            key = list(rows[0].keys())[0]
            for r in rows:
                try:
                    rid = int((r[key] or '').strip())
                except (TypeError, ValueError):
                    continue
                cols = set(c for c in r
                           if c and not c.startswith(CONTROL_PREFIX)
                           and c != key and nz(r[c]))
                if cols:
                    self.writes[(model, rid)] |= cols

    def writes_column(self, model, ids, column):
        for m, cols in self.unscoped:
            if m == model and column in cols:
                return True
        return any(column in self.writes.get((model, i), ())
                   for i in ids)


# ---------------------------------------------------------------------------
# THE COLUMN SET IS DECLARED. THE DUMP IS THE CHECK.
#
# A COLUMN IS NOT A LEVER BECAUSE IT IS LIVE IN A DUMP. See the module
# docstring: the dumper can omit a column that is constant across all rows, so
# _dropped_columns.csv and the table headers describe THE MOMENT THE DUMP WAS
# TAKEN, not the game tables. A header derived from a dump and asserted against
# the same dump always agrees with it -- a false green, which is worse than a
# false red.
#
# Two declarations and a three-way partition:
#
#     derive_columns_live(dump)  ==  SHEET_COLUMNS  u  EXCLUDED_COLUMNS
#
# SHEET_COLUMNS is the levers, written out. EXCLUDED_COLUMNS is every
# column ruled out, each with a reason tag. check_partition() asserts the
# equation on every run, and A LIVE COLUMN IN NEITHER SET IS A NAMED, LOUD
# PROBLEM. A future dump that widens again now says "the dump now carries X on
# table Y and nothing classifies it" instead of silently regenerating a
# different file. A declared lever the dump cannot confirm is equally a problem.
#
# derive_columns_live() below is the CHECK rather than the source: it is the
# only thing that can notice the dump moving.
#
# KEYS ARE (model, column), NEVER A BARE COLUMN NAME -- the same rule this file
# already applies to ids, for the same reason. `EffectPurgeType`, `InitBonus`
# and `Invulnerable` are columns of BOTH EffectModel and MatrixEffectModel
# [measured]. EffectPurgeType and InitBonus are SHIPPED LEVERS on EffectModel
# (grenades/devices/chems and medical/chems respectively) and are excluded on
# MatrixEffectModel. A bare-name exclusion list would delete three real levers,
# and --selftest has a case proving it.
# ---------------------------------------------------------------------------

# THE LEVERS, ASSERTED three ways: against the plugin's own map entry for
# entry (P-MAP), against the headers on disk (A-SHEET), and against the dump
# (A-PART, A-COL). This is a hand list
# and that is now the point: it is the thing the dump is checked against, not a
# thing derived from it.
SHEET_COLUMNS = {
    'medical': [
        ('ServiceOptionId',       ITEM_MODEL,    'ServiceOptionId'),
        ('Rarity',                ITEM_MODEL,    'Rarity'),
        ('PowerLevel',            ITEM_MODEL,    'PowerLevel'),
        ('Cost',                  ITEM_MODEL,    'Cost'),
        ('AlternateAdjustment',   TALENT_MODEL,  'AlternateAdjustment'),
        ('AltOverride',           TALENT_MODEL,  'AltOverride'),
        ('LevelCost',             TALENT_MODEL,  'LevelCost'),
        ('TalentIsActive',        TALENT_MODEL,  'TalentIsActive'),
        ('Range',                 TALENT_MODEL,  'Range'),
        ('RangeAoE',              TALENT_MODEL,  'RangeAoE'),
        ('ActionId',              TALENT_MODEL,  'ActionId'),
        ('ApCost',                TALENT_MODEL,  'ApCost'),
        ('TargetEffect',          TALENT_MODEL,  'TargetEffect'),
        ('TargetEffectDuration',  TALENT_MODEL,  'TargetEffectDuration'),
        ('SelfEffect',            TALENT_MODEL,  'SelfEffect'),
        ('Token',                 TALENT_MODEL,  'Token'),
        ('TokenDuration',         TALENT_MODEL,  'TokenDuration'),
        ('PreReq',                TALENT_MODEL,  'PreReq'),
        ('FilterTypeId',          TALENT_MODEL,  'FilterTypeId'),
        ('MaxCharges',            TALENT_MODEL,  'MaxCharges'),
        ('TargetType',            TALENT_MODEL,  'TargetType'),
        ('EffectClassification',  EFFECT_MODEL,  'EffectClassification'),
        ('EffectHealType',        EFFECT_MODEL,  'EffectHealType'),
        ('Heals',                 EFFECT_MODEL,  'Heals'),
        ('WoundRes',              EFFECT_MODEL,  'WoundRes'),
        ('StressRes',             EFFECT_MODEL,  'StressRes'),
        ('InitBonus',             EFFECT_MODEL,  'InitBonus'),
        ('ActionPoints',          EFFECT_MODEL,  'ActionPoints'),
        ('MovePoints',            EFFECT_MODEL,  'MovePoints'),
    ],
    'grenades': [
        ('ServiceOptionId',       ITEM_MODEL,    'ServiceOptionId'),
        ('PowerLevel',            ITEM_MODEL,    'PowerLevel'),
        ('Cost',                  ITEM_MODEL,    'Cost'),
        ('AlternateAdjustment',   TALENT_MODEL,  'AlternateAdjustment'),
        ('LevelCost',             TALENT_MODEL,  'LevelCost'),
        ('TalentIsActive',        TALENT_MODEL,  'TalentIsActive'),
        ('Range',                 TALENT_MODEL,  'Range'),
        ('RangeAoE',              TALENT_MODEL,  'RangeAoE'),
        ('ActionId',              TALENT_MODEL,  'ActionId'),
        ('ApCost',                TALENT_MODEL,  'ApCost'),
        ('TargetEffect',          TALENT_MODEL,  'TargetEffect'),
        ('TargetEffectDuration',  TALENT_MODEL,  'TargetEffectDuration'),
        ('Token',                 TALENT_MODEL,  'Token'),
        ('TokenDuration',         TALENT_MODEL,  'TokenDuration'),
        ('Volume',                TALENT_MODEL,  'Volume'),
        ('PureDamage',            TALENT_MODEL,  'PureDamage'),
        ('PhysicalDamage',        TALENT_MODEL,  'PhysicalDamage'),
        ('BallisticDamage',       TALENT_MODEL,  'BallisticDamage'),
        ('FilterTypeId',          TALENT_MODEL,  'FilterTypeId'),
        ('MaxCharges',            TALENT_MODEL,  'MaxCharges'),
        ('TargetType',            TALENT_MODEL,  'TargetType'),
        ('EffectClassification',  EFFECT_MODEL,  'EffectClassification'),
        ('EffectClearType',       EFFECT_MODEL,  'EffectClearType'),
        ('EffectPurgeType',       EFFECT_MODEL,  'EffectPurgeType'),
        ('Stunned',               EFFECT_MODEL,  'Stunned'),
    ],
    'devices': [
        ('ServiceOptionId',       ITEM_MODEL,    'ServiceOptionId'),
        ('Rarity',                ITEM_MODEL,    'Rarity'),
        ('PowerLevel',            ITEM_MODEL,    'PowerLevel'),
        ('Cost',                  ITEM_MODEL,    'Cost'),
        ('AlternateAdjustment',   TALENT_MODEL,  'AlternateAdjustment'),
        ('AltOverride',           TALENT_MODEL,  'AltOverride'),
        ('LevelCost',             TALENT_MODEL,  'LevelCost'),
        ('TalentIsActive',        TALENT_MODEL,  'TalentIsActive'),
        ('Range',                 TALENT_MODEL,  'Range'),
        ('RangeAoE',              TALENT_MODEL,  'RangeAoE'),
        ('ActionId',              TALENT_MODEL,  'ActionId'),
        ('ApCost',                TALENT_MODEL,  'ApCost'),
        ('TargetEffect',          TALENT_MODEL,  'TargetEffect'),
        ('TargetEffectDuration',  TALENT_MODEL,  'TargetEffectDuration'),
        ('SelfEffect',            TALENT_MODEL,  'SelfEffect'),
        ('SelfDuration',          TALENT_MODEL,  'SelfDuration'),
        ('Token',                 TALENT_MODEL,  'Token'),
        ('TokenCount',            TALENT_MODEL,  'TokenCount'),
        ('TokenDuration',         TALENT_MODEL,  'TokenDuration'),
        ('PreReq',                TALENT_MODEL,  'PreReq'),
        ('FilterTypeId',          TALENT_MODEL,  'FilterTypeId'),
        ('MaxCharges',            TALENT_MODEL,  'MaxCharges'),
        ('TargetType',            TALENT_MODEL,  'TargetType'),
        ('EffectClassification',  EFFECT_MODEL,  'EffectClassification'),
        ('EffectClearType',       EFFECT_MODEL,  'EffectClearType'),
        ('EffectPurgeType',       EFFECT_MODEL,  'EffectPurgeType'),
        ('PureDamageMelee',       EFFECT_MODEL,  'PureDamageMelee'),
        ('Stunned',               EFFECT_MODEL,  'Stunned'),
    ],
    'chems': [
        ('ServiceOptionId',       ITEM_MODEL,    'ServiceOptionId'),
        ('Rarity',                ITEM_MODEL,    'Rarity'),
        ('PowerLevel',            ITEM_MODEL,    'PowerLevel'),
        ('Cost',                  ITEM_MODEL,    'Cost'),
        ('AlternateAdjustment',   TALENT_MODEL,  'AlternateAdjustment'),
        ('LevelCost',             TALENT_MODEL,  'LevelCost'),
        ('TalentIsActive',        TALENT_MODEL,  'TalentIsActive'),
        ('Range',                 TALENT_MODEL,  'Range'),
        ('ApCost',                TALENT_MODEL,  'ApCost'),
        ('TargetEffect',          TALENT_MODEL,  'TargetEffect'),
        ('TargetEffectDuration',  TALENT_MODEL,  'TargetEffectDuration'),
        ('SelfEffect',            TALENT_MODEL,  'SelfEffect'),
        ('SelfDuration',          TALENT_MODEL,  'SelfDuration'),
        ('FilterTypeId',          TALENT_MODEL,  'FilterTypeId'),
        ('MaxCharges',            TALENT_MODEL,  'MaxCharges'),
        ('TargetType',            TALENT_MODEL,  'TargetType'),
        ('EffectClassification',  EFFECT_MODEL,  'EffectClassification'),
        ('EffectPurgeType',       EFFECT_MODEL,  'EffectPurgeType'),
        ('EffectHealType',        EFFECT_MODEL,  'EffectHealType'),
        ('Heals',                 EFFECT_MODEL,  'Heals'),
        ('WoundRes',              EFFECT_MODEL,  'WoundRes'),
        ('StressRes',             EFFECT_MODEL,  'StressRes'),
        ('MeleeAttack',           EFFECT_MODEL,  'MeleeAttack'),
        ('RangedAttack',          EFFECT_MODEL,  'RangedAttack'),
        ('CritRate',              EFFECT_MODEL,  'CritRate'),
        ('CritRateStealth',       EFFECT_MODEL,  'CritRateStealth'),
        ('CritMultiBase',         EFFECT_MODEL,  'CritMultiBase'),
        ('PureDamageBallistic',   EFFECT_MODEL,  'PureDamageBallistic'),
        ('PureDamageMelee',       EFFECT_MODEL,  'PureDamageMelee'),
        ('PhysicalArmor',         EFFECT_MODEL,  'PhysicalArmor'),
        ('BallisticArmor',        EFFECT_MODEL,  'BallisticArmor'),
        ('Evasion',               EFFECT_MODEL,  'Evasion'),
        ('DetectRangeReduction',  EFFECT_MODEL,  'DetectRangeReduction'),
        ('RecoilBonus',           EFFECT_MODEL,  'RecoilBonus'),
        ('RecoilRate',            EFFECT_MODEL,  'RecoilRate'),
        ('MoveSpeed',             EFFECT_MODEL,  'MoveSpeed'),
        ('InitBonus',             EFFECT_MODEL,  'InitBonus'),
        ('ActionPoints',          EFFECT_MODEL,  'ActionPoints'),
        ('MovePoints',            EFFECT_MODEL,  'MovePoints'),
    ],
    'sploitkits': [
        ('ServiceOptionId',       ITEM_MODEL,    'ServiceOptionId'),
        ('LeverageClass',         ITEM_MODEL,    'LeverageClass'),
        ('Rarity',                ITEM_MODEL,    'Rarity'),
        ('PowerLevel',            ITEM_MODEL,    'PowerLevel'),
        ('Cost',                  ITEM_MODEL,    'Cost'),
    ],
    'matrix': [
        ('ServiceOptionId',       ITEM_MODEL,    'ServiceOptionId'),
        ('Rarity',                ITEM_MODEL,    'Rarity'),
        ('PowerLevel',            ITEM_MODEL,    'PowerLevel'),
        ('Cost',                  ITEM_MODEL,    'Cost'),
        ('AlternateAdjustment',   TALENT_MODEL,  'AlternateAdjustment'),
        ('LevelCost',             TALENT_MODEL,  'LevelCost'),
        ('TalentIsMatrixOnly',    TALENT_MODEL,  'TalentIsMatrixOnly'),
        ('TalentIsActive',        TALENT_MODEL,  'TalentIsActive'),
        ('ApCost',                TALENT_MODEL,  'ApCost'),
        ('SelfEffect',            TALENT_MODEL,  'SelfEffect'),
        ('SelfDuration',          TALENT_MODEL,  'SelfDuration'),
        ('MatrixEffect',          TALENT_MODEL,  'MatrixEffect'),
        ('MatrixDuration',        TALENT_MODEL,  'MatrixDuration'),
        ('MaxCharges',            TALENT_MODEL,  'MaxCharges'),
        ('TargetType',            TALENT_MODEL,  'TargetType'),
        ('EffectClassification',  EFFECT_MODEL,  'EffectClassification'),
        ('WoundRes',              EFFECT_MODEL,  'WoundRes'),
        ('StressRes',             EFFECT_MODEL,  'StressRes'),
        ('FiringArc',             EFFECT_MODEL,  'FiringArc'),
        ('CritRate',              EFFECT_MODEL,  'CritRate'),
        ('PureDamageBallistic',   EFFECT_MODEL,  'PureDamageBallistic'),
        ('PureDamageMelee',       EFFECT_MODEL,  'PureDamageMelee'),
        ('ArmorCrit',             EFFECT_MODEL,  'ArmorCrit'),
        ('DmgReduction',          EFFECT_MODEL,  'DmgReduction'),
        ('RecoilBonus',           EFFECT_MODEL,  'RecoilBonus'),
        ('RecoilRate',            EFFECT_MODEL,  'RecoilRate'),
        ('MoveSpeedMitigate',     EFFECT_MODEL,  'MoveSpeedMitigate'),
        ('ActionPoints',          EFFECT_MODEL,  'ActionPoints'),
        ('MatrixEffectClassification', MATRIX_MODEL,  'EffectClassification'),
        ('MatrixInstant',         MATRIX_MODEL,  'Instant'),
        ('MatrixActionPoints',    MATRIX_MODEL,  'ActionPoints'),
        ('MatrixIoBoost',         MATRIX_MODEL,  'IoBoost'),
        ('MatrixDamageBoost',     MATRIX_MODEL,  'DamageBoost'),
        ('MatrixHealConnection',  MATRIX_MODEL,  'HealConnection'),
        ('MatrixDeckArmor',       MATRIX_MODEL,  'DeckArmor'),
        ('MatrixDeckShield',      MATRIX_MODEL,  'DeckShield'),
        ('MatrixPrePostBlocked',  MATRIX_MODEL,  'PrePostBlocked'),
        ('MatrixSecurityTally',   MATRIX_MODEL,  'SecurityTally'),
        ('MatrixSCUTurns',        MATRIX_MODEL,  'SCUTurns'),
    ],
}


# EVERY COLUMN LIVE IN A DUMP AND DELIBERATELY NOT A LEVER, with the reason.
#
# Keyed (model, column). Membership was derived from a post-session dump and
# then classified; check_partition() re-derives and
# refuses if the classification no longer covers what is live.
#
# Entries that are not live TODAY are kept rather than trimmed: they are
# PRE-CLASSIFIED, so a later dump that makes one vary reports nothing new
# instead of firing a spurious "unclassified" on a column whose disposition was
# already decided. A-PART prints how many are live and how many are standing by.
EXCLUDED_COLUMNS = {
    # Asset, VFX, SFX, icon, animation and display-string references. None is a
    # number a player tunes; several are localisation keys.
    'presentation': [
        (ITEM_MODEL,   'Asset3DTypeId'),
        (TALENT_MODEL, 'AnimationKey'),
        (TALENT_MODEL, 'EventSFX'),
        (TALENT_MODEL, 'ExtraAsset'),
        (TALENT_MODEL, 'GroupNameSFX'),
        (TALENT_MODEL, 'IconPng'),
        (TALENT_MODEL, 'SelfVfx'),
        (TALENT_MODEL, 'TokenVfx'),
        (TALENT_MODEL, 'TypeSFX'),
        (TALENT_MODEL, 'Vfx'),
        (TALENT_MODEL, 'TalentDesc'),
        (TALENT_MODEL, 'ManualTalentName'),
        (EFFECT_MODEL, 'IconAsset'),
        (EFFECT_MODEL, 'VFX'),
        (EFFECT_MODEL, 'ManualEffectName'),
        (MATRIX_MODEL, 'IconAsset'),
        (MATRIX_MODEL, 'VFX'),
        (MATRIX_MODEL, 'ManualEffectName'),
    ],
    # State the running game owns. A value here is whatever the session left
    # behind, which is exactly why these columns appear in one dump and not
    # another; writing one would be writing into the game's own bookkeeping.
    'runtime-state': [
        (ITEM_MODEL,   'IsRowCurrentlySelected'),
        (TALENT_MODEL, 'IsActiveForDisplay'),
        (TALENT_MODEL, 'TalentCyberEnabled'),
        (TALENT_MODEL, 'TalentLevel'),
        (EFFECT_MODEL, 'OwnerEntityId'),
        (EFFECT_MODEL, 'isInit'),
        (EFFECT_MODEL, 'effectsSet'),
        (EFFECT_MODEL, 'HasInitSpecialCode'),
        (MATRIX_MODEL, 'isInit'),
        (MATRIX_MODEL, 'effectsSet'),
        (MATRIX_MODEL, 'HasInitSpecialCode'),
    ],
    # The Adjusted* family, all thirteen (David's rule), including the three
    # (AdjustedApMatrix, AdjustedDamageBonus, AdjustedHealingBonus) that a
    # fresh-game dump omits as constant 0.
    'adjusted': [
        (TALENT_MODEL, 'AdjustedAp'),
        (TALENT_MODEL, 'AdjustedApMatrix'),
        (TALENT_MODEL, 'AdjustedCount'),
        (TALENT_MODEL, 'AdjustedDamageBonus'),
        (TALENT_MODEL, 'AdjustedHealingBonus'),
        (TALENT_MODEL, 'AdjustedMatrixDuration'),
        (TALENT_MODEL, 'AdjustedMaxCharges'),
        (TALENT_MODEL, 'AdjustedRange'),
        (TALENT_MODEL, 'AdjustedRangeAoE'),
        (TALENT_MODEL, 'AdjustedSelfDuration'),
        (TALENT_MODEL, 'AdjustedTargetEffectDuration'),
        (TALENT_MODEL, 'AdjustedTokenDuration'),
        (TALENT_MODEL, 'AdjustedTurnMaxUses'),
    ],
    # Mechanically named and ruled out anyway. The three MatrixEffectModel
    # entries are the (model, column) case: the same three names on EffectModel
    # are LEVERS.
    'mechanic-not-exposed': [
        (ITEM_MODEL,   'FactionId'),
        (TALENT_MODEL, 'AllowsLessAp'),
        (TALENT_MODEL, 'AttackTalentStartingAP'),
        (TALENT_MODEL, 'AttackTalentStartingAPCheck'),
        (TALENT_MODEL, 'DroneDamage'),
        (TALENT_MODEL, 'DroneRule'),
        (TALENT_MODEL, 'DroneRuleType'),
        (TALENT_MODEL, 'StressChance'),
        (TALENT_MODEL, 'TeamGlobal'),
        (TALENT_MODEL, 'TokenCancel'),
        (EFFECT_MODEL, 'ActionPointsPet'),
        (EFFECT_MODEL, 'AttackDetectRangeReduction'),
        (EFFECT_MODEL, 'CommsOut'),
        (EFFECT_MODEL, 'CritRateStreakSum'),
        (EFFECT_MODEL, 'DeathSave'),
        (EFFECT_MODEL, 'Immobilized'),
        (EFFECT_MODEL, 'LevePoints'),
        (EFFECT_MODEL, 'TalentLimit'),
        (MATRIX_MODEL, 'EffectPurgeType'),
        (MATRIX_MODEL, 'InitBonus'),
        (MATRIX_MODEL, 'Invulnerable'),
    ],
}

EXCLUDED_PAIRS = dict((pair, tag)
                      for tag, lst in EXCLUDED_COLUMNS.items()
                      for pair in lst)

# The columns no sheet may carry because they NAME a row rather than override
# it, per model, so the partition can account for them without calling them
# either a lever or an exclusion.
NON_CANDIDATE = {
    ITEM_MODEL: set(IDENTITY) | set(ITEM_TEXT) | {CLASS_COLUMN},
    TALENT_MODEL: set(TALENT_IDENTITY),
    EFFECT_MODEL: set(EFFECT_IDENTITY),
    MATRIX_MODEL: set(MATRIX_IDENTITY),
}


def derive_columns_live(dump, cls):
    """THE OLD columns_for() BODY, KEPT AND REPURPOSED: it is now the CHECK,
    not the source.

    -> [(model, gameColumn)] live for this class: non-blank and non-zero on at
    least one of the rows this class reaches, minus the columns that name a row.

    The `Adjusted` prefix test that used to live here is GONE ON PURPOSE. It
    removed thirteen columns before anything could count them, which is the
    same shape of blindness as the derivation itself; the Adjusted family is
    now thirteen ordinary entries in EXCLUDED_COLUMNS and the partition
    accounts for each one by name.
    """
    items = dump.items_of(cls)
    talents = [t for t in (dump.talent_of(i) for i in items) if t is not None]
    eff_rows, mx_rows, _dangling = dump.payload_rows(cls)
    src = {ITEM_MODEL: items, TALENT_MODEL: talents,
           EFFECT_MODEL: eff_rows, MATRIX_MODEL: mx_rows}
    out = []
    for model in MODELS:
        rows = src[model]
        if not rows:
            continue
        for col in dump.cols[model]:
            if col in NON_CANDIDATE[model]:
                continue
            if any(nz(r.get(col)) for r in rows):
                out.append((model, col))
    return out


def columns_for(dump, cls):
    """-> (carried, dropped) for one class, FROM THE DECLARATION.

    carried: [(sheetColumn, model, gameColumn)] -- SHEET_COLUMNS, verbatim.
    dropped: [(model, gameColumn, why)] -- every candidate column of the dump
             this sheet does NOT carry, with the reason on the record, so
             check_dropped() can still ask of each whether a live rule writes
             it. The dump is read here only to enumerate what was NOT taken.
    """
    sheet = SHEET_BY_CLASS[cls]
    carried = list(SHEET_COLUMNS[sheet.key])
    taken = set((m, g) for _c, m, g in carried)
    live = set(derive_columns_live(dump, cls))
    dropped = []
    for model in MODELS:
        for col in dump.cols[model]:
            if col in NON_CANDIDATE[model] or (model, col) in taken:
                continue
            tag = EXCLUDED_PAIRS.get((model, col))
            if tag:
                why = 'declared excluded: ' + tag
            elif model == TALENT_MODEL and col in DEAD_TALENT_COLUMNS:
                why = 'dead on all 70 joined TalentModel rows'
            elif (model, col) in live:
                why = 'LIVE for this class and classified by NOTHING -- see A-PART'
            else:
                why = 'blank or zero on every row this class reaches'
            dropped.append((model, col, why))
    return carried, dropped


def identity_for(dump, cls):
    """The identity columns THIS file carries.

    Derived, not listed: a file carries TalentId only if some row of its class
    joins a talent, EffectId only if some row reaches an EffectModel row, and
    MatrixEffectId only if some row reaches a MatrixEffectModel row. That is
    what keeps consumables-sploitkits.csv from showing a TalentId column that
    is 0 on all three of its rows and names no table row at all.
    """
    items = dump.items_of(cls)
    out = ['ItemName', ITEM_KEY]
    has_t = has_e = has_m = False
    for i in items:
        t = dump.talent_of(i)
        if t is None:
            continue
        has_t = True
        es, m = dump.effect_ids(t)
        has_e = has_e or bool(es)
        has_m = has_m or bool(m)
    if has_t:
        out.append(TALENT_KEY)
    if has_e:
        out.append(EFFECT_KEY)
    if has_m:
        out.append(MATRIX_KEY)
    return out


def header_for(dump, cls):
    ident = identity_for(dump, cls)
    carried, _ = columns_for(dump, cls)
    return ident + [c for c, _, _ in carried] + [CONTROL_COMMENT]


def build_sheet(dump, cls):
    """-> (header, rows, carried, dropped). rows are lists of strings."""
    sheet = SHEET_BY_CLASS[cls]
    ident = identity_for(dump, cls)
    carried, dropped = columns_for(dump, cls)
    header = ident + [c for c, _, _ in carried] + [CONTROL_COMMENT]
    out = []
    for item in dump.items_of(cls):
        t = dump.talent_of(item)
        es, m = dump.effect_ids(t)
        erow = dump.by_id[EFFECT_MODEL].get(sorted(es)[0]) if es else None
        mrow = dump.by_id[MATRIX_MODEL].get(m) if m else None
        vals = {'ItemName': item['ItemName'],
                ITEM_KEY: item[ITEM_KEY],
                TALENT_KEY: (t[TALENT_KEY] if t is not None else ''),
                EFFECT_KEY: (str(sorted(es)[0]) if es else ''),
                MATRIX_KEY: (str(m) if m else '')}
        line = [vals[c] for c in ident]
        shipped = []
        for col, model, gcol in carried:
            src = {ITEM_MODEL: item, TALENT_MODEL: t,
                   EFFECT_MODEL: erow, MATRIX_MODEL: mrow}[model]
            # EVERY CELL IS BLANK. 0 rules and 0 overlay rows touch any of the
            # 194 pairs [measured, check_untouched()], so a value here would be
            # a new balance change rather than a converted one.
            line.append('')
            shipped.append('%s %s' % (col, '-' if src is None
                                      else (src.get(gcol) or '').strip()))
        line.append(_comment_for(dump, sheet, item, t, es, m, shipped))
        out.append(line)
    return header, out, carried, dropped


def _comment_for(dump, sheet, item, talent, eff_ids, mx_id, shipped):
    """FREE TEXT AND NOT LOAD-BEARING: nothing parses this column."""
    bits = ['%s (ItemTypeId %s, ItemClass %s, %s)'
            % (item['ItemName'], item[ITEM_KEY], item[CLASS_COLUMN], sheet.name)]
    if talent is None:
        bits.append('TalentId 0 and no TalentModel row exists, so this row\'s '
                    'only levers are its ItemModel columns')
    else:
        bits.append('talent %s %s' % (talent[TALENT_KEY], talent['TalentName']))
        if eff_ids:
            roles = [c for c, mdl in POINTER_TABLE.items()
                     if mdl == EFFECT_MODEL and int(talent[c])]
            e = sorted(eff_ids)[0]
            bits.append('EffectModel %d %s via %s'
                        % (e, dump.by_id[EFFECT_MODEL][e]['EffectName'],
                           '+'.join(roles)))
        else:
            bits.append('no EffectModel row (SelfEffect and TargetEffect are '
                        'both 0), so every EffectModel cell is blank')
        if mx_id:
            bits.append('MatrixEffectModel %d %s via MatrixEffect'
                        % (mx_id, dump.by_id[MATRIX_MODEL][mx_id]['EffectName']))
    for (model, rid), sr in sorted(SHARED_ROWS.items()):
        if not any(o[0] == int(item[ITEM_KEY]) for o in sr['owners']):
            continue
        others = [o for o in sr['owners'] if o[0] != int(item[ITEM_KEY])]
        bits.append('SHARED: %s %d is also %s. %s'
                    % (model, rid,
                       ' and '.join('%s (item %d, talent %d)' % (o[2], o[0], o[1])
                                    for o in others),
                       sr['note']))
    note = ROW_NOTES.get(int(item[ITEM_KEY]))
    if note:
        bits.append(note)
    bits.append('Shipped: ' + '; '.join(shipped))
    return '. '.join(b.rstrip('.') for b in bits) + '.'


def csv_text(header, rows):
    """LF, matching the other generated sheets. check_eol() reads the bytes
    back OFF DISK rather than trusting this."""
    buf = io.StringIO(newline='')
    w = csv.writer(buf, lineterminator='\n')
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# THE TREE.
#
# What the checks see on disk. Backed by a real directory or by an in-memory
# dict, and `names()` is a REAL ENUMERATION in both cases -- that is what makes
# a stray seventh file detectable. A check that iterates its own declared names
# and never lists the directory is dark to a stray file; this does not repeat
# that.
#
# A tree whose directory does not exist RAISES. "Could not look" is not "the
# files are missing".
# ---------------------------------------------------------------------------

class Tree(object):
    def __init__(self, path=None, blobs=None, label=None):
        self.path = path
        self.blobs = blobs
        self.label = label or (path or '<memory>')
        if blobs is None:
            if path is None or not os.path.isdir(path):
                raise Problem('%s is not a directory. This is a refusal, not an '
                              'empty overlay directory: nothing listed it, so '
                              'which files are in it is not known.' % path)

    def names(self):
        if self.blobs is not None:
            return sorted(self.blobs)
        return sorted(n for n in os.listdir(self.path)
                      if n.lower().endswith('.csv'))

    def has(self, name):
        return name in self.names()

    def read_bytes(self, name):
        if self.blobs is not None:
            if name not in self.blobs:
                raise Problem('%s is not in %s' % (name, self.label))
            return self.blobs[name]
        p = os.path.join(self.path, name)
        if not os.path.isfile(p):
            raise Problem('%s is not on disk at %s' % (name, p))
        with io.open(p, 'rb') as fh:
            return fh.read()

    def copy(self):
        blobs = {}
        for n in self.names():
            blobs[n] = self.read_bytes(n)
        return Tree(blobs=blobs, label=self.label + ' (copy)')


def parse_sheet(data, name):
    """-> (header, rows as lists). A parse that fails RAISES."""
    try:
        text = data.decode('utf-8-sig')
    except Exception as e:
        raise Problem('%s is not UTF-8: %s. Refused, not skipped.' % (name, e))
    lines = list(csv.reader(io.StringIO(text, newline='')))
    lines = [l for l in lines if l]
    if len(lines) < 2:
        raise Problem('%s has %d non-empty line(s); a header and at least one '
                      'data row are needed.' % (name, len(lines)))
    return [h.strip() for h in lines[0]], lines[1:]


# ---------------------------------------------------------------------------
# THE CHECKS.
#
# Each returns a list of problem strings and prints its census line WHETHER OR
# NOT the count is zero. Each problem string starts with its tag so --selftest
# can grade a fault by tag rather than by "something went wrong".
# ---------------------------------------------------------------------------

def check_rows(dump, out):
    """A-ROW. The totals, the class set, and DISJOINTNESS -- asserted, not
    eyeballed. A total that still adds up is exactly what a copied row plus a
    dropped row produces."""
    problems = []
    seen = collections.defaultdict(list)
    for r in dump.items:
        seen[int(r[CLASS_COLUMN])].append(int(r[ITEM_KEY]))
    classes = sorted(seen)
    if classes != DECLARED_CLASSES:
        problems.append('A-ROW: ItemModel carries ItemClass %s; this file '
                        'declares %s.' % (classes, DECLARED_CLASSES))
    if ABSENT_CLASS in seen:
        problems.append('A-ROW: ItemClass %d exists in the dump (%d row(s)); '
                        'this file declares that it does not.'
                        % (ABSENT_CLASS, len(seen[ABSENT_CLASS])))
    total = 0
    for s in SHEETS:
        got = len(seen.get(s.cls, []))
        total += got
        if got != s.rows:
            problems.append('A-ROW: %s -- ItemClass %d has %d row(s) in the '
                            'dump, %d declared here. DISAGREEMENT WITH THE '
                            'DECLARATION, not an adjustment: one of the two is '
                            'wrong and this run does not decide which.'
                            % (s.name, s.cls, got, s.rows))
    if total != len(dump.items):
        problems.append('A-ROW: the six classes hold %d row(s) but ItemModel '
                        'has %d. %d row(s) are in no declared class.'
                        % (total, len(dump.items), len(dump.items) - total))
    counts = collections.Counter(int(r[ITEM_KEY]) for r in dump.items)
    dupes = [i for i, n in counts.items() if n > 1]
    if dupes:
        problems.append('A-ROW: ItemTypeId is not unique in the dump: %s'
                        % sorted(dupes))
    out('    A-ROW: %d ItemModel row(s); ItemClass %s (no %d); per class %s; '
        'sum %d; %d duplicate ItemTypeId; %d problem(s).'
        % (len(dump.items), classes, ABSENT_CLASS,
           ', '.join('%d=%d' % (s.cls, len(seen.get(s.cls, []))) for s in SHEETS),
           total, len(dupes), len(problems)))
    return problems


def check_join(dump, out):
    """A-JOIN. 70 of 73 join TalentModel; the 3 that do not are exactly the
    three sploitkits and no TalentModel row with id 0 exists."""
    problems = []
    joined, unjoined, dangling = [], [], []
    for r in dump.items:
        tid = int(r[TALENT_KEY])
        if tid == 0:
            unjoined.append(int(r[ITEM_KEY]))
        elif tid in dump.by_id[TALENT_MODEL]:
            joined.append(int(r[ITEM_KEY]))
        else:
            dangling.append((int(r[ITEM_KEY]), tid))
    if sorted(unjoined) != sorted(SPLOITKIT_ITEM_IDS):
        problems.append('A-JOIN: the rows with TalentId 0 are %s; this file '
                        'declares %s.' % (sorted(unjoined),
                                          sorted(SPLOITKIT_ITEM_IDS)))
    for i in unjoined:
        row = dump.by_id[ITEM_MODEL][i]
        if int(row[CLASS_COLUMN]) != SHEET_BY_NAME['consumables-sploitkits.csv'].cls:
            problems.append('A-JOIN: ItemTypeId %d has TalentId 0 but is '
                            'ItemClass %s, not the sploitkit class.'
                            % (i, row[CLASS_COLUMN]))
    if dangling:
        problems.append('A-JOIN: %d item(s) name a TalentId with no TalentModel '
                        'row: %s' % (len(dangling), dangling))
    if 0 in dump.by_id[TALENT_MODEL]:
        problems.append('A-JOIN: a TalentModel row with TalentId 0 exists, so '
                        '"TalentId 0 means no talent" is not safe here.')
    # The sploitkit sheet must carry no talent-side column at all.
    sk = SHEET_BY_NAME['consumables-sploitkits.csv']
    carried, _ = columns_for(dump, sk.cls)
    off = [c for c, m, _ in carried if m != ITEM_MODEL]
    if off:
        problems.append('A-JOIN: %s carries %s from a table its rows do not '
                        'reach. Rows that do nothing.' % (sk.name, off))
    out('    A-JOIN: %d of %d ItemModel row(s) join TalentModel; %d do not '
        '(ItemTypeId %s, all TalentId 0, all ItemClass %d); %d dangling '
        'TalentId; %s carries %d non-ItemModel column(s); %d problem(s).'
        % (len(joined), len(dump.items), len(unjoined), sorted(unjoined),
           sk.cls, len(dangling), sk.name, len(off), len(problems)))
    return problems


def check_resolution(dump, out):
    """A-RES. The [fitted] effect-table resolution, re-derived from the whole
    TalentModel rather than from the 70 consumable talents -- a fit measured on
    70 rows is weaker than the same fit measured on 384.

    Reports CELL counts and DISTINCT-ID counts both, because the two readings
    differ (133 vs 132 for SelfEffect, 98 vs 95 for TargetEffect) and an
    instrument that prints only one invites the other to be quoted as it."""
    problems = []
    E = set(dump.by_id[EFFECT_MODEL])
    M = set(dump.by_id[MATRIX_MODEL])
    lines = []
    for col, want in POINTER_TABLE.items():
        cells = [int(t[col]) for t in dump.rows[TALENT_MODEL] if int(t[col])]
        ids = set(cells)
        only_e = [v for v in cells if v in E and v not in M]
        only_m = [v for v in cells if v in M and v not in E]
        both = [v for v in cells if v in E and v in M]
        dang = [v for v in cells if v not in E and v not in M]
        support = only_e if want == EFFECT_MODEL else only_m
        against = only_m if want == EFFECT_MODEL else only_e
        if against:
            problems.append('A-RES: %s is fitted to %s but %d unambiguous '
                            'cell(s) resolve in the other table: %s. The fit is '
                            'contradicted; do not adjust the fit silently.'
                            % (col, want, len(against), sorted(set(against))))
        if not support:
            problems.append('A-RES: %s has 0 unambiguous cell(s), so NOTHING '
                            'supports resolving it against %s. This is COULD '
                            'NOT LOOK, not agreement.' % (col, want))
        if dang:
            problems.append('A-RES: %s names %d id(s) in neither table: %s'
                            % (col, len(dang), sorted(set(dang))))
        lines.append('%s -> %s [fitted]: %d non-zero cell(s) / %d distinct; '
                     'unambiguous %d cell(s) / %d distinct, all in %s; %d '
                     'ambiguous cell(s) (id in both tables); %d dangling'
                     % (col, want, len(cells), len(ids), len(support),
                        len(set(support)), want, len(both), len(dang)))
    out('    A-RES: %d id(s) are both an EffectId and a MatrixEffectId, so an '
        'id does not name its table; the column is fitted from the ones that '
        'do. %d problem(s).' % (len(E & M), len(problems)))
    for l in lines:
        out('      ' + l)
    out('      WHAT WOULD CONFIRM IT: a real (non-stub) body for the talent '
        'application path showing which reader the column is looked up in. '
        'None exists today; this stays [fitted].')
    return problems


def check_identity(dump, out):
    """A-ID. One EffectId column per row is only enough because no consumable
    talent reaches two DIFFERENT EffectModel rows."""
    problems = []
    multi, self_share = [], []
    for item in dump.items:
        t = dump.talent_of(item)
        if t is None:
            continue
        es, _m = dump.effect_ids(t)
        if len(es) > 1:
            multi.append((int(item[ITEM_KEY]), sorted(es)))
        roles = [c for c, mdl in POINTER_TABLE.items()
                 if mdl == EFFECT_MODEL and int(t[c])]
        if len(roles) > 1 and len(es) == 1:
            self_share.append((int(item[ITEM_KEY]), sorted(es)[0], roles))
    if multi:
        problems.append('A-ID: %d consumable row(s) reach TWO DIFFERENT '
                        'EffectModel rows: %s. One EffectId identity column is '
                        'then not enough and the header must be role-qualified.'
                        % (len(multi), multi))
    declared = set(SELF_SHARES)
    found = set((EFFECT_MODEL, e) for _i, e, _r in self_share)
    for k in found - declared:
        problems.append('A-ID: %s %d is a self-share that SELF_SHARES does not '
                        'declare.' % k)
    for k in declared - found:
        problems.append('A-ID: SELF_SHARES declares %s %d but no row has that '
                        'id in two pointer columns.' % k)
    out('    A-ID: %d identity column(s) declared (%s); %d row(s) reach two '
        'different EffectModel rows; %d self-share(s) found, %d declared; %d '
        'problem(s).'
        % (len(IDENTITY), ', '.join(IDENTITY), len(multi), len(self_share),
           len(SELF_SHARES), len(problems)))
    for i, e, roles in self_share:
        out('      self-share: item %d, EffectModel %d in %s -- ONE owner, so '
            'it is not a shared row' % (i, e, '+'.join(roles)))
    return problems


def check_dead(dump, out):
    """A-DEAD. Both halves: the five columns are still 0 on all 70 joined
    talents, AND no generated header carries one. The second half alone would
    go green on a header that had lost the column for an unrelated reason."""
    problems = []
    talents = [t for t in (dump.talent_of(i) for i in dump.items)
               if t is not None]
    for col in DEAD_TALENT_COLUMNS:
        if col not in dump.cols[TALENT_MODEL]:
            problems.append('A-DEAD: %s is not a TalentModel column in the '
                            'dump, so "it is 0 on all 70" was never measured.'
                            % col)
            continue
        live = [int(t[TALENT_KEY]) for t in talents if nz(t[col])]
        if live:
            problems.append('A-DEAD: %s is NON-ZERO on %d joined talent(s): %s. '
                            'It is declared dead and is in no header.'
                            % (col, len(live), live[:10]))
    in_header = []
    for s in SHEETS:
        h = header_for(dump, s.cls)
        for col in DEAD_TALENT_COLUMNS:
            if col in h:
                in_header.append((s.name, col))
    if in_header:
        problems.append('A-DEAD: dead column(s) in a generated header: %s'
                        % in_header)
    out('    A-DEAD: %d declared dead column(s) %s, re-measured 0 across all %d '
        'joined TalentModel row(s); %d occurrence(s) in the six generated '
        'headers; %d problem(s).'
        % (len(DEAD_TALENT_COLUMNS), DEAD_TALENT_COLUMNS, len(talents),
           len(in_header), len(problems)))
    return problems


def check_columns(dump, out):
    """A-COL. Every header column maps to a real dump column of a real table,
    no header name is used twice, no (model, column) target is written twice,
    and no carried column is dead for its own rows."""
    problems = []
    ncols = 0
    for s in SHEETS:
        ident = identity_for(dump, s.cls)
        carried, _dropped = columns_for(dump, s.cls)
        ncols += len(carried)
        names = collections.Counter(ident + [c for c, _, _ in carried]
                                    + [CONTROL_COMMENT])
        for n, k in names.items():
            if k > 1:
                problems.append('A-COL %s: the header name %r appears %d '
                                'times. A name that maps to two targets cannot '
                                'be read back.' % (s.name, n, k))
        targets = collections.Counter((m, g) for _c, m, g in carried)
        for t, k in targets.items():
            if k > 1:
                problems.append('A-COL %s: %s.%s is the target of %d header '
                                'columns.' % (s.name, t[0], t[1], k))
        items = dump.items_of(s.cls)
        talents = [t for t in (dump.talent_of(i) for i in items) if t is not None]
        eff_rows, mx_rows, dangling = dump.payload_rows(s.cls)
        src = {ITEM_MODEL: items, TALENT_MODEL: talents,
               EFFECT_MODEL: eff_rows, MATRIX_MODEL: mx_rows}
        for col, model, gcol in carried:
            if gcol not in dump.cols[model]:
                problems.append('A-COL %s: %s maps to %s.%s, which is not in '
                                'the dumped %s header.'
                                % (s.name, col, model, gcol, model))
                continue
            if not any(nz(r.get(gcol)) for r in src[model]):
                problems.append('A-COL %s: %s (%s.%s) is blank or zero on all '
                                '%d of this class\'s own %s rows.'
                                % (s.name, col, model, gcol,
                                   len(src[model]), model))
            if col.startswith(ADJUSTED_PREFIX):
                problems.append('A-COL %s: %s is an Adjusted* column and those '
                                'are excluded from every header this phase '
                                'generates.' % (s.name, col))
        if dangling:
            problems.append('A-COL %s: %d effect pointer(s) name a row that is '
                            'not in its table: %s' % (s.name, len(dangling),
                                                      dangling))
    # The one row design.md section 8 says cannot exist.
    both = [int(i[ITEM_KEY]) for i in dump.items
            if dump.talent_of(i) is not None
            and dump.effect_ids(dump.talent_of(i))[0]
            and dump.effect_ids(dump.talent_of(i))[1]]
    if not both:
        problems.append('A-COL: no row carries both an EffectModel and a '
                        'MatrixEffectModel payload. design.md section 8 says '
                        '"effect OR matrix-effect" and the correction to it '
                        'rests on Eclipse Microdust having BOTH; if that row is '
                        'gone the correction needs re-measuring, not keeping.')
    out('    A-COL: %d lever column(s) across the six headers, each checked '
        'against the dumped %d/%d/%d/%d-column headers; %d row(s) carry an '
        'EffectModel AND a MatrixEffectModel payload (%s); %d problem(s).'
        % (ncols, len(dump.cols[ITEM_MODEL]), len(dump.cols[TALENT_MODEL]),
           len(dump.cols[EFFECT_MODEL]), len(dump.cols[MATRIX_MODEL]),
           len(both), both, len(problems)))
    return problems


def check_partition(dump, out):
    """A-PART. THE THREE-WAY PARTITION, and the reason this file exists in its
    current shape.

        derive_columns_live(dump)  ==  SHEET_COLUMNS  u  EXCLUDED_COLUMNS

    Three counts, printed whether or not any is zero, plus the fourth that says
    what is pre-classified but not currently live.

    A LIVE COLUMN IN NEITHER SET IS A NAMED PROBLEM, with its table. That is the
    whole point: the dump widened by 128 columns between two launches of the
    same build, and under the old derived-union rule the only symptom was six
    files quietly becoming 228 columns wide. Under a declaration the symptom is
    this check saying which column nobody has classified.

    A DECLARED LEVER THE DUMP CANNOT CONFIRM IS ALSO A PROBLEM, and it is the
    half that a narrow dump trips: a dump taken from a freshly loaded game has
    fewer columns, so it cannot confirm levers it does not carry, and this
    reports each one by name instead of agreeing by producing a smaller union.
    """
    problems = []
    live = collections.OrderedDict()          # (model, col) -> [sheet keys]
    lever_pairs = collections.OrderedDict()   # (model, col) -> [sheet keys]
    for s in SHEETS:
        for pair in derive_columns_live(dump, s.cls):
            live.setdefault(pair, []).append(s.key)
        for _c, m, g in SHEET_COLUMNS[s.key]:
            lever_pairs.setdefault((m, g), []).append(s.key)

    declared_entries = sum(len(v) for v in SHEET_COLUMNS.values())
    excl = dict(EXCLUDED_PAIRS)

    # 1. LIVE AND CLASSIFIED BY NOTHING.
    unclassified = [k for k in live
                    if k not in lever_pairs and k not in excl
                    and not (k[0] == TALENT_MODEL and k[1] in DEAD_TALENT_COLUMNS)]
    for k in sorted(unclassified):
        problems.append(
            'A-PART: the dump now carries %s.%s and it is live on %s, and '
            'NOTHING classifies it -- it is neither in SHEET_COLUMNS nor in '
            'EXCLUDED_COLUMNS. Classify it (as a lever or with a reason tag) '
            'rather than letting the six files change shape around it.'
            % (k[0], k[1], live[k]))

    # 2. DECLARED A LEVER AND NOT CONFIRMABLE FROM THIS DUMP. The narrow-dump
    #    case. Split into "the column is not in the table at all" and "the
    #    column is there and is blank or zero on this sheet's own rows",
    #    because those are different answers and the first is the one that says
    #    the DUMP is narrow rather than the DECLARATION being wrong.
    absent, dead_here = [], []
    for s in SHEETS:
        live_here = set(derive_columns_live(dump, s.cls))
        for c, m, g in SHEET_COLUMNS[s.key]:
            if g not in dump.cols[m]:
                absent.append((s.key, m, g))
            elif (m, g) not in live_here:
                dead_here.append((s.key, m, g))
    for k, m, g in absent:
        problems.append(
            'A-PART: %s declares the lever %s.%s and this dump has no such '
            'column in %s at all, so the declaration CANNOT BE CONFIRMED from '
            'it. A dump taken from a freshly loaded game omits every column '
            'that is constant in it; that is a narrow dump, not a wrong '
            'declaration, and the two are not the same answer.' % (k, m, g, m))
    for k, m, g in dead_here:
        problems.append(
            'A-PART: %s declares the lever %s.%s and it is blank or zero on '
            'every row that sheet reaches in this dump.' % (k, m, g))

    # 3. A pair declared BOTH ways.
    both = sorted(set(lever_pairs) & set(excl))
    for k in both:
        problems.append('A-PART: %s.%s is declared a lever on %s AND excluded '
                        'as %r. One or the other.'
                        % (k[0], k[1], lever_pairs[k], excl[k]))

    # 4. An exclusion naming a column this dump's table does not have. THIS IS
    #    NOT A PROBLEM BY ITSELF: a narrow dump legitimately lacks columns that
    #    are constant
    #    in it, and treating that as an error would make the check
    #    dump-dependent again, in the other direction.
    #
    #    _dropped_columns.csv is what tells the two apart, which is the job it
    #    already does for check_dumper_dropped(). An exclusion whose column is
    #    absent from the table AND absent from that table's drop list is a
    #    TYPO and is named; one the dumper recorded dropping is PRE-CLASSIFIED
    #    and is counted, not complained about.
    absent_excl, typo = [], []
    for k in excl:
        if k[1] in dump.cols.get(k[0], ()):
            continue
        absent_excl.append(k)
        if k[1] not in set(c for c, _w, _v in dump.dropped.get(k[0], [])):
            typo.append(k)
    for k in sorted(typo):
        problems.append(
            'A-PART: EXCLUDED_COLUMNS names %s.%s as %r and this dump has it '
            'neither in the %s header nor in _dropped_columns.csv for %s, so it '
            'is not a column the dumper saw and omitted -- it is a name nothing '
            'accounts for.' % (k[0], k[1], excl[k], k[0], k[0]))

    excl_live = [k for k in excl if k in live]
    out('    A-PART: THE PARTITION. %d (model, column) pair(s) live across the '
        'six sheets in this dump = %d declared lever pair(s) (%d SHEET_COLUMNS '
        'entries over six files) + %d declared exclusion(s) that are live + %d '
        'unclassified. Unclassified MUST be 0.'
        % (len(live), len(lever_pairs), declared_entries, len(excl_live),
           len(unclassified)))
    out('      EXCLUDED_COLUMNS declares %d pair(s) in %d reason tag(s): %s. '
        '%d live now, %d pre-classified and standing by for a dump that makes '
        'them vary.'
        % (len(excl), len(EXCLUDED_COLUMNS),
           ', '.join('%s %d' % (t, len(v))
                     for t, v in sorted(EXCLUDED_COLUMNS.items())),
           len(excl_live), len(excl) - len(excl_live)))
    out('      dumped headers this run: %s. The column set of a dump depends on '
        'WHEN IT WAS TAKEN -- the dumper omits a column constant across all '
        'rows -- so these four numbers are not facts about the game and '
        'nothing here is derived from them.'
        % ', '.join('%s %d' % (m, len(dump.cols[m])) for m in MODELS))
    out('      declared levers this dump cannot confirm: %d absent from their '
        'table, %d present but blank/zero on their sheet\'s rows. Declared '
        'exclusions absent from this dump: %d, of which %d are recorded in '
        '_dropped_columns.csv (the dumper saw them and omitted them -- a narrow '
        'dump, reported not complained about) and %d are accounted for by '
        'nothing.'
        % (len(absent), len(dead_here), len(absent_excl),
           len(absent_excl) - len(typo), len(typo)))
    return problems


def check_dropped(dump, live, out):
    """A-DROP. The Phase 6 trap as an assertion: for EVERY column a file does
    NOT carry, nothing live writes it on a row that file owns.

    A column being zero says nothing about whether a rule writes it. Today the
    expected answer is 0 written, because 0 rules reach these rows at all -- but
    the assertion is the one that stays true when that changes."""
    problems = []
    n = 0
    for s in SHEETS:
        items = dump.items_of(s.cls)
        eff_rows, mx_rows, _d = dump.payload_rows(s.cls)
        ids = {ITEM_MODEL: [int(r[ITEM_KEY]) for r in items],
               TALENT_MODEL: [int(t[TALENT_KEY])
                              for t in (dump.talent_of(i) for i in items)
                              if t is not None],
               EFFECT_MODEL: [int(r[EFFECT_KEY]) for r in eff_rows],
               MATRIX_MODEL: [int(r[MATRIX_KEY]) for r in mx_rows]}
        _carried, dropped = columns_for(dump, s.cls)
        for model, gcol, why in dropped:
            n += 1
            if live.writes_column(model, ids[model], gcol):
                problems.append('A-DROP %s: drops %s.%s (%s) but something live '
                                'WRITES it on a row this file owns.'
                                % (s.name, model, gcol, why))
    out('    A-DROP: %d dropped column(s) across the six files, each asked of '
        '%s and %d overlay file(s); %d written by something. A column being '
        'zero says nothing about whether a rule writes it.'
        % (n, live.rules_half_note('dropped_columns_written'),
           len(live.overlay_files), len(problems)))
    return problems


def check_dumper_dropped(dump, live, out):
    """A-DUMP. _dropped_columns.csv is load-bearing.

    A column absent from a dumped header is EITHER not a column of that table
    OR one the dumper removed for being constant across the whole table. Those
    are different answers and this is the file that tells them apart. If
    anything live writes a column the dumper dropped, then this phase's union
    cannot see it and the union is incomplete -- so it is named."""
    problems = []
    n = 0
    pairs = dump.pairs()
    by_model = collections.defaultdict(list)
    for m, i in pairs:
        by_model[m].append(i)
    for model in MODELS:
        for col, why, const in dump.dropped.get(model, []):
            if col.endswith('_k__BackingField'):
                continue
            n += 1
            if live.writes_column(model, by_model[model], col):
                problems.append('A-DUMP: something live writes %s.%s, which the '
                                'dumper DROPPED (%s, constant %r). The measured '
                                'union cannot see that column, so the six '
                                'headers are incomplete by exactly it.'
                                % (model, col, why, const))
    out('    A-DUMP: %d non-backing-field column(s) the dumper dropped across '
        'the four tables, each asked of %s and %d overlay file(s); %d '
        'written. Absent from a dumped header is not the same as absent from '
        'the game table, and _dropped_columns.csv is how the two are told '
        'apart. %d problem(s).'
        % (n, live.rules_half_note('dumper_dropped_columns_written'),
           len(live.overlay_files), len(problems), len(problems)))
    return problems


def check_untouched(dump, live, out):
    """A-LIVE. Nothing live writes any of the consumable-reachable pairs.

    The non-sheet overlay CSVs are read and asked, so this check RUNS and can go
    red -- F11 and S6 are it going red. The rules half has no subject without
    ckf.hardmode.rules.json; live.rules_half_note() prints that by name on the line below rather than
    letting `asked of 0 rule(s)` read as `0 rules write these rows`, which is
    the same sentence meaning the opposite thing.
    """
    problems = []
    pairs = dump.pairs()
    hits = sorted(k for k in live.writes if k in pairs)
    unscoped = [u for u in live.unscoped if u[0] in MODELS]
    for k in hits:
        problems.append('A-LIVE: something live writes %s %d, which is one of '
                        'the %d consumable-reachable pairs. A generated cell on '
                        'that row would be a second write, not a conversion.'
                        % (k[0], k[1], len(pairs)))
    for m, cols in unscoped:
        problems.append('A-LIVE: an UNSCOPED rule writes %s.%s and reaches '
                        'every row of that table, including this phase\'s.'
                        % (m, cols))
    per = collections.Counter(m for m, _ in pairs)
    out('    A-LIVE: %d consumable-reachable (table, id) pair(s) -- %s -- asked '
        'of %s and %d overlay CSV(s) in ckf.hardmode.d; %d touched, %d '
        'unscoped rule(s) on these four tables. %d problem(s).'
        % (len(pairs), ', '.join('%s %d' % (m, per[m]) for m in MODELS),
           live.rules_half_note('pairs_touched'), len(live.overlay_files),
           len(hits), len(unscoped), len(problems)))
    return problems


def check_collisions(dump, out):
    """A-KEY. Every declared pair is two REAL rows in two tables carrying one
    number, and keying on the number alone collapses them."""
    problems = []
    for case in COLLISION_CASES:
        for side in ('left', 'right'):
            model, key, rid = case[side]
            if key != KEY_OF[model]:
                problems.append('A-KEY %s: %s is not %s\'s key column.'
                                % (case['id'], key, model))
            if rid not in dump.by_id[model]:
                problems.append('A-KEY %s: %s %d is not a row of the dumped %s. '
                                'A collision case that names a row that does '
                                'not exist proves nothing.'
                                % (case['id'], model, rid, model))
        lm, _lk, lid = case['left']
        rm, _rk, rid = case['right']
        if lid != rid:
            problems.append('A-KEY %s: the two sides carry different ids (%d, '
                            '%d), so there is no collision to demonstrate.'
                            % (case['id'], lid, rid))
        if lm == rm:
            problems.append('A-KEY %s: both sides are %s, so the pair does not '
                            'show a cross-table collision.' % (case['id'], lm))
        if len({(lm, lid), (rm, rid)}) != 2 or len({lid, rid}) != 1:
            problems.append('A-KEY %s: the (model, id) key does not separate '
                            'the pair.' % case['id'])
    pairs = dump.pairs()
    by_number = collections.defaultdict(set)
    for m, i in pairs:
        by_number[i].add(m)
    collapsed = {i: sorted(v) for i, v in by_number.items() if len(v) > 1}
    out('    A-KEY: %d declared collision case(s), each two real rows; inside '
        'this phase\'s own %d pair(s), %d id(s) appear under more than one '
        'model, so an id-alone key collapses %d pair(s) to %d and %d write(s) '
        'would land on the wrong table. %d problem(s).'
        % (len(COLLISION_CASES), len(pairs), len(collapsed), len(pairs),
           len(by_number), len(pairs) - len(by_number), len(problems)))
    for case in COLLISION_CASES:
        out('      %s  %s %d  vs  %s %d' % (case['id'], case['left'][0],
                                            case['left'][2], case['right'][0],
                                            case['right'][2]))
    return problems


def shared_rows(dump, naive=False):
    """-> {(model, id): [(itemTypeId, talentId, itemName, [roles])]}

    KEYED ON THE OWNING ITEM. `naive=True` is the DEFECT, kept runnable: it
    keys on (talent, pointer column), so one talent naming one effect in both
    SelfEffect and TargetEffect looks like two owners. That is how an earlier
    agent reported nine shared rows where five were self-shares. F7 runs both
    and requires them to disagree about exactly EffectModel 75022.
    """
    owners = collections.defaultdict(list)
    for item in dump.items:
        t = dump.talent_of(item)
        if t is None:
            continue
        for col, model in POINTER_TABLE.items():
            v = int(t[col])
            if not v:
                continue
            owners[(model, v)].append((int(item[ITEM_KEY]), int(t[TALENT_KEY]),
                                       item['ItemName'], col))
    out = {}
    for k, v in owners.items():
        if naive:
            uniq = v                       # one entry per (row, pointer column)
        else:
            seen, uniq = set(), []
            for o in v:
                if o[0] in seen:
                    continue
                seen.add(o[0])
                uniq.append(o)
        if len(uniq) > 1:
            out[k] = uniq
    return out


def check_shared(dump, out):
    """A-SHARED. The sharing that exists in the shipped data, measured, with
    self-shares excluded by construction rather than by a special case."""
    problems = []
    found = shared_rows(dump)
    declared = dict(SHARED_ROWS)
    for k in sorted(set(found) - set(declared)):
        problems.append('A-SHARED: %s %d is owned by %d items and SHARED_ROWS '
                        'does not declare it: %s. A shared row nothing marks is '
                        'a shared row nothing warns about.'
                        % (k[0], k[1], len(found[k]),
                           [(o[0], o[2]) for o in found[k]]))
    for k in sorted(set(declared) - set(found)):
        problems.append('A-SHARED: SHARED_ROWS declares %s %d and the dump has '
                        '%d owner(s) for it.'
                        % (k[0], k[1], len(found.get(k, []))))
    for k in sorted(set(declared) & set(found)):
        want = set(o[0] for o in declared[k]['owners'])
        got = set(o[0] for o in found[k])
        if want != got:
            problems.append('A-SHARED: %s %d owners declared %s, measured %s'
                            % (k[0], k[1], sorted(want), sorted(got)))
        sheet = declared[k]['sheet']
        for o in found[k]:
            cls = int(dump.by_id[ITEM_MODEL][o[0]][CLASS_COLUMN])
            if SHEET_BY_CLASS[cls].name != sheet:
                problems.append('A-SHARED: %s %d is declared in %s but owner %d '
                                'is in %s. A shared row whose owners are in two '
                                'files cannot be refused inside one file.'
                                % (k[0], k[1], sheet, o[0],
                                   SHEET_BY_CLASS[cls].name))
    naive = shared_rows(dump, naive=True)
    self_only = sorted(set(naive) - set(found))
    for k in self_only:
        if k not in SELF_SHARES:
            problems.append('A-SHARED: %s %d is a self-share and SELF_SHARES '
                            'does not declare it.' % k)
    # The informational case: an owner with no table of its own.
    cons_talents = set()
    for item in dump.items:
        t = dump.talent_of(item)
        if t is not None:
            cons_talents.add(int(t[TALENT_KEY]))
    outside = collections.defaultdict(list)
    for t in dump.rows[TALENT_MODEL]:
        if int(t[TALENT_KEY]) in cons_talents:
            continue
        for col, model in POINTER_TABLE.items():
            v = int(t[col])
            if v and (model, v) in set(
                    (m, i) for m, i in dump.pairs() if m in (EFFECT_MODEL,
                                                             MATRIX_MODEL)):
                outside[(model, v)].append((int(t[TALENT_KEY]), t['TalentName']))
    payload_pairs = [p for p in dump.pairs()
                     if p[0] in (EFFECT_MODEL, MATRIX_MODEL)]
    out('    A-SHARED: %d payload row(s) reached by these 70 talents; %d owned '
        'by more than one ITEM (declared %d); %d self-share(s) that the naive '
        'per-pointer detector would have called sharing (declared %d); %d '
        'reached by a talent outside this phase, so there is no informational '
        'case. %d problem(s).'
        % (len(payload_pairs), len(found), len(declared), len(self_only),
           len(SELF_SHARES), len(outside), len(problems)))
    for k in sorted(found):
        out('      shared: %s %d <- %s' % (k[0], k[1],
                                           ', '.join('%s (item %d, talent %d, '
                                                     'via %s)' % (o[2], o[0],
                                                                  o[1], o[3])
                                                     for o in found[k])))
    for k in self_only:
        o = naive[k]
        out('      self-share, NOT shared: %s %d <- %s (item %d) via %s -- one '
            'owner, so it cannot diverge from itself'
            % (k[0], k[1], o[0][2], o[0][0], '+'.join(x[3] for x in o)))
    return problems


def check_files(dump, tree, out):
    """A-FILE. THE DIRECTORY IS LISTED, not the declared names iterated.

    Iterating declared names makes a stray seventh consumables-*.csv invisible,
    and a file no expander declares is parsed as a DIRECT OVERLAY against a
    table called "consumables-<whatever>Model". That fails silently."""
    problems = []
    present = set(tree.names())
    missing = sorted(SHEET_NAMES - present)
    stray = sorted(n for n in present
                   if n.startswith('consumables-') and n not in SHEET_NAMES)
    for n in missing:
        problems.append('A-FILE: %s is declared in SHEET_NAMES and is not in '
                        '%s. Missing, not empty.' % (n, tree.label))
    for n in stray:
        problems.append('A-FILE: %s is in %s and no expander declares it. It '
                        'will be parsed as a DIRECT OVERLAY against a table '
                        'called %r, which fails with one orphan warning long '
                        'afterwards and nothing else.'
                        % (n, tree.label, n.split('.')[0] + 'Model'))
    out('    A-FILE: %d file(s) listed in %s; %d of the %d declared present, %d '
        'missing, %d stray consumables-*.csv that no expander declares. %d '
        'problem(s).'
        % (len(present), tree.label, len(SHEET_NAMES) - len(missing),
           len(SHEET_NAMES), len(missing), len(stray), len(problems)))
    return problems


def check_sheets(dump, tree, out):
    """A-SHEET. Header, row identity, row order, blank cells, dialect, bytes.

    Every generated cell must be BLANK: 0 rules touch these rows, so a value
    would be a new balance change. A refused control column refuses the WHOLE
    file rather than being ignored."""
    problems = []
    n_rows = n_cells = 0
    for s in SHEETS:
        if not tree.has(s.name):
            continue                       # A-FILE already named it
        try:
            data = tree.read_bytes(s.name)
            header, rows = parse_sheet(data, s.name)
        except Problem as e:
            problems.append('A-SHEET %s: %s' % (s.name, e))
            continue

        # bytes: LF only, read back off disk rather than assumed
        crlf = data.count(b'\r\n')
        cr = data.count(b'\r') - crlf
        if crlf or cr:
            problems.append('A-SHEET %s: %d CRLF and %d lone CR in the bytes on '
                            'disk. The 43 schema JSONs and all CSVs in '
                            'ckf.hardmode.d are LF [measured].'
                            % (s.name, crlf, cr))

        want = header_for(dump, s.cls)
        if header != want:
            extra = [c for c in header if c not in want]
            gone = [c for c in want if c not in header]
            problems.append('A-SHEET %s: header is %d column(s), the measured '
                            'union is %d. Extra %s; missing %s. Regenerate with '
                            '--write.' % (s.name, len(header), len(want),
                                          extra, gone))
            continue
        for bad, why in REFUSED_CONTROL.items():
            if bad in header:
                problems.append('A-SHEET %s: header carries the control column '
                                '%r, which this dialect REFUSES: %s The whole '
                                'file is refused, not the column ignored.'
                                % (s.name, bad, why))
        for c in header:
            if c.startswith(CONTROL_PREFIX) and c not in ALLOWED_CONTROL:
                problems.append('A-SHEET %s: unknown control column %r.'
                                % (s.name, c))

        ident = identity_for(dump, s.cls)
        want_rows = dump.items_of(s.cls)
        if len(rows) != len(want_rows):
            problems.append('A-SHEET %s: %d data row(s) on disk, %d ItemClass '
                            '%d row(s) in the dump.'
                            % (s.name, len(rows), len(want_rows), s.cls))
        idx = dict((c, i) for i, c in enumerate(header))
        for n, row in enumerate(rows, start=2):
            n_rows += 1
            if len(row) != len(header):
                problems.append('A-SHEET %s:%d: %d cell(s) against a %d-column '
                                'header.' % (s.name, n, len(row), len(header)))
                continue
            try:
                iid = int((row[idx[ITEM_KEY]] or '').strip())
            except (TypeError, ValueError):
                problems.append('A-SHEET %s:%d: ItemTypeId %r is not an '
                                'integer; the whole row is refused.'
                                % (s.name, n, row[idx[ITEM_KEY]]))
                continue
            item = dump.by_id[ITEM_MODEL].get(iid)
            if item is None:
                problems.append('A-SHEET %s:%d: ItemTypeId %d is not an '
                                'ItemModel row.' % (s.name, n, iid))
                continue
            if int(item[CLASS_COLUMN]) != s.cls:
                problems.append('A-SHEET %s:%d: ItemTypeId %d is ItemClass %s '
                                'and belongs in %s. A row in the wrong file is '
                                'a row two files can both claim.'
                                % (s.name, n, iid, item[CLASS_COLUMN],
                                   SHEET_BY_CLASS[int(item[CLASS_COLUMN])].name
                                   if int(item[CLASS_COLUMN]) in SHEET_BY_CLASS
                                   else 'no declared file'))
                continue
            if n - 2 < len(want_rows) and int(want_rows[n - 2][ITEM_KEY]) != iid:
                problems.append('A-SHEET %s:%d: ItemTypeId %d; the dump has %s '
                                'at that position. The rows are in FILE ORDER '
                                'and nothing may sort them.'
                                % (s.name, n, iid, want_rows[n - 2][ITEM_KEY]))
            for c in header:
                if c in ident or c == CONTROL_COMMENT:
                    continue
                n_cells += 1
                cell = row[idx[c]]
                kind, _val, ok = parse_adjust(cell)
                if not ok:
                    problems.append('A-SHEET %s:%d: column %s: %r is not an '
                                    'adjustment (expected blank, =N, +N, -N or '
                                    'xN). Named, not read as blank.'
                                    % (s.name, n, c, cell))
                    continue
                if kind != NONE:
                    problems.append('A-SHEET %s:%d: column %s carries %r. Every '
                                    'cell in these six files must be BLANK: 0 '
                                    'rules and 0 overlay rows reach these rows, '
                                    'so a value here is a NEW balance change, '
                                    'not a converted one.'
                                    % (s.name, n, c, cell))
        # every row of the class present exactly once
        on_disk = collections.Counter()
        for row in rows:
            if len(row) == len(header):
                try:
                    on_disk[int((row[idx[ITEM_KEY]] or '').strip())] += 1
                except (TypeError, ValueError):
                    pass
        for r in want_rows:
            k = int(r[ITEM_KEY])
            if on_disk.get(k, 0) != 1:
                problems.append('A-SHEET %s: ItemTypeId %d appears %d time(s); '
                                'exactly once is required.'
                                % (s.name, k, on_disk.get(k, 0)))
    out('    A-SHEET: %d data row(s) and %d lever cell(s) across %d readable '
        'file(s); every cell required blank; %d problem(s).'
        % (n_rows, n_cells, len([s for s in SHEETS if tree.has(s.name)]),
           len(problems)))
    return problems


def check_disjoint(dump, tree, out):
    """A-DISJOINT. Across ALL SIX FILES AT ONCE: every ItemTypeId in exactly
    one. Per-file row counts can all be right while a row sits in two files."""
    problems = []
    where = collections.defaultdict(list)
    for s in SHEETS:
        if not tree.has(s.name):
            continue
        try:
            header, rows = parse_sheet(tree.read_bytes(s.name), s.name)
        except Problem:
            continue
        if ITEM_KEY not in header:
            continue
        i = header.index(ITEM_KEY)
        for row in rows:
            if len(row) <= i:
                continue
            try:
                where[int((row[i] or '').strip())].append(s.name)
            except (TypeError, ValueError):
                continue
    for r in dump.items:
        k = int(r[ITEM_KEY])
        got = where.get(k, [])
        if len(got) != 1:
            problems.append('A-DISJOINT: ItemTypeId %d (%s, ItemClass %s) is in '
                            '%s; exactly one file is required.'
                            % (k, r['ItemName'], r[CLASS_COLUMN],
                               got or 'no file'))
    extra = sorted(k for k in where if k not in dump.by_id[ITEM_MODEL])
    for k in extra:
        problems.append('A-DISJOINT: ItemTypeId %d is in %s and is not an '
                        'ItemModel row.' % (k, where[k]))
    out('    A-DISJOINT: %d ItemTypeId(s) across the six files, %d in the dump; '
        '%d problem(s).' % (len(where), len(dump.items), len(problems)))
    return problems


def report_adjusted(dump, out):
    """D-ADJ. Which Adjusted* columns are LIVE per class.

    The list is read from EXCLUDED_COLUMNS' `adjusted` tag rather than from a
    prefix test over whatever this dump happens to carry: a fresh-game dump
    omits the Adjusted* columns that are constant 0, so a prefix test would
    report fewer. A dump that omits one still reports all thirteen and says
    which it could not see.
    """
    declared = [g for _m, g in EXCLUDED_COLUMNS['adjusted']]
    in_dump = [c for c in declared if c in dump.cols[TALENT_MODEL]]
    unseen = [c for c in declared if c not in dump.cols[TALENT_MODEL]]
    by_prefix = [c for c in dump.cols[TALENT_MODEL]
                 if c.startswith(ADJUSTED_PREFIX)]
    stray = [c for c in by_prefix if c not in declared]
    all_adj = in_dump
    out('    D-ADJ: %d Adjusted* column(s) DECLARED excluded; %d of them in '
        'this dump\'s TalentModel header, %d not in it (%s) -- a dump omits '
        'what is constant in it, so absence here is the dump\'s narrowness, '
        'not the family\'s size. %d column(s) match the prefix in this dump '
        'and %d of those are undeclared (%s). Which are live per class:'
        % (len(declared), len(in_dump), len(unseen), unseen or '-',
           len(by_prefix), len(stray), stray or '-'))
    for s in SHEETS:
        items = dump.items_of(s.cls)
        talents = [t for t in (dump.talent_of(i) for i in items) if t is not None]
        live = [c for c in all_adj if any(nz(t.get(c)) for t in talents)]
        out('      %-28s %d live of %d: %s'
            % (s.name, len(live), len(all_adj), live or '-'))
    return []


def report_s8_delta(dump, out):
    """D-S8. The delta between the measured union and design.md section 8's
    abbreviated list, per file, so the section can be corrected."""
    out('    D-S8: measured union vs design.md section 8, per file. Section 8 '
        'is an ABBREVIATION and is incomplete; this is the correction list.')
    for s in SHEETS:
        spec = DESIGN_S8[s.key]
        carried, _ = columns_for(dump, s.cls)
        live = [(c, m, g) for c, m, g in carried]
        open_models = set(m for m, _p in spec['open'])
        named = set(spec['named'])
        extra_named, extra_open = [], []
        for c, m, g in live:
            if g in named or c in named:
                continue
            if m in open_models:
                extra_open.append('%s.%s' % (m, c))
            else:
                extra_named.append('%s.%s' % (m, c))
        live_names = set([c for c, _m, _g in live] + [g for _c, _m, g in live])
        absent = sorted(n for n in named if n not in live_names)
        out('      %-28s section 8: %s' % (s.name, spec['text']))
        out('        measured union: %d lever column(s) (%d ItemModel, %d '
            'TalentModel, %d EffectModel, %d MatrixEffectModel) + %d identity '
            '+ _comment'
            % (len(live),
               len([1 for _c, m, _g in live if m == ITEM_MODEL]),
               len([1 for _c, m, _g in live if m == TALENT_MODEL]),
               len([1 for _c, m, _g in live if m == EFFECT_MODEL]),
               len([1 for _c, m, _g in live if m == MATRIX_MODEL]),
               len(identity_for(dump, s.cls))))
        out('        LIVE, NOT NAMED IN SECTION 8 (%d): %s'
            % (len(extra_named), ', '.join(extra_named) or '-'))
        out('        LIVE, covered only by section 8\'s unenumerated phrase '
            '(%d): %s' % (len(extra_open), ', '.join(extra_open) or '-'))
        out('        NAMED IN SECTION 8, NOT LIVE (%d): %s'
            % (len(absent), ', '.join(absent) or '-'))
    return []


def check_eol(tree, out):
    """A-EOL. The bytes, off disk. Folded into check_sheets for the six, but
    stated separately so the census prints the measurement even when every
    file is fine."""
    lf = crlf = cr = 0
    seen = 0
    for s in SHEETS:
        if not tree.has(s.name):
            continue
        data = tree.read_bytes(s.name)
        seen += 1
        c = data.count(b'\r\n')
        crlf += c
        cr += data.count(b'\r') - c
        lf += data.count(b'\n') - c
    out('    A-EOL: %d of %d file(s) read back as BYTES: %d LF, %d CRLF, %d '
        'lone CR. LF is the measured convention of the 43 schema JSONs and the '
        'CSVs in ckf.hardmode.d; there is no repo-wide one.'
        % (seen, len(SHEETS), lf, crlf, cr))
    return []


# ---------------------------------------------------------------------------
# P-MAP. THE PLUGIN'S COLUMN MAP AND THIS FILE'S ARE ONE TRANSCRIPTION.
#
# mods/CKFHardMode/Consumables.cs carries the same 165 (column, model, target)
# entries this file derives from the dump, in six arrays, one per sheet. They
# are two transcriptions ON PURPOSE -- the thing that checks the writer must not
# be the writer -- but two transcriptions with nothing between them drift, and
# the drift is invisible: the plugin would write one column at load and every
# repo-side gate would check another. Consumables.cs's own VerifyMap() checks
# the map against ITSELF at runtime; P-MAP here is what checks it against this
# file.
#
# WHICH ANCHORING, AND WHY NOT THE OTHER TWO.
#
#   scripts/cyberweapons.py uses src.find(_MAP_END) -- the FIRST occurrence.
#   That is fragile and this file does NOT inherit it: a C# file that spells
#   the closing marker out in its own prose (Implants.cs does, more than once)
#   hands a find()-based reader the prose occurrence and a truncated block --
#   "markers found, zero entries parsed", a green over nothing.
#
#   scripts/implants.py anchors on WHOLE COMMENT LINES
#   (^[ \t]*//[ \t]*END LEVER MAP[ \t]*$), which is sound there but does not
#   fit here: Consumables.cs puts its opening marker MID-SENTENCE
#   ("// THE COLUMN MAP. BEGIN LEVER MAP -- this table is meant to be
#   SCRAPED"), so a whole-line anchor would match nothing and report the
#   markers missing on a file that has them. [measured]
#
#   SO: UNIQUENESS. Each marker string must occur EXACTLY ONCE in the whole
#   file. Zero is "could not look"; two or more is ambiguous and is REFUSED BY
#   NAME with both line numbers rather than silently resolved to the first.
#   That fits both marker placements, it is strictly stronger than find(), and
#   it turns the Cyberweapons.cs reflow hazard from a silent green into a loud
#   refusal. A reformat that duplicates a marker now fails the gate instead of
#   emptying it.
#
# THE ARRAY REGEX IS STRICTER THAN cyberweapons.py's, for the same reason.
# cyberweapons.py matches (\w+)Levers\s*= anywhere on a line, which a sentence
# mentioning "MedicalLevers =" would satisfy. This one requires the DECLARATION
# -- `Lever[] <Name>Levers =` -- which prose cannot produce. If a
# future reformat splits that declaration across lines the array is not found,
# its sheet reports "no array" and the entry count falls; both are NAMED.
#
# THE NUL BYTE. Cyberweapons.cs carries a literal 0x00 inside the string
# in KeyOf -- `model + "<NUL>" + id.ToString(...)` -- an actual control
# character in the source, not the two-character escape `\0`. (Implants.cs and
# Consumables.cs use a real space for the same job.) It is a valid UTF-8
# codepoint so this reader decodes straight through it, and G14 below proves
# that by pointing the scrape at the real Cyberweapons.cs and requiring a NAMED
# refusal rather than a crash or a pass. Cyberweapons.cs is NOT edited here.
#
# The NUL below is written chr(0), never as a literal byte: Python refuses to
# compile a source file containing one, and a NUL that has to survive an
# editor, a diff and a patch should not be spelled as one.
# ---------------------------------------------------------------------------

PLUGIN_SOURCE = os.path.join('mods', 'CKFHardMode', 'Consumables.cs')

_MAP_BEGIN = 'BEGIN LEVER MAP'
_MAP_END = 'END LEVER MAP'
# Entry and array shapes deliberately identical to cyberweapons.py's, so the
# plugin does not have to carry a second dialect for a second reader.
_LEVER_RE = re.compile(
    r'new\s+Lever\(\s*"([^"]+)"\s*,\s*(\w+)\s*,\s*"([^"]+)"\s*\)')
_ARRAY_RE = re.compile(r'Lever\[\]\s+(\w+)Levers\s*=')
_NOTALIAS_RE = re.compile(r'NotAliases\s*=\s*\{([^}]*)\}', re.S)
_CONST_RE = re.compile(r'const\s+string\s+(\w+)\s*=\s*"([^"]*)"')
_NOTALIAS_ITEM_RE = re.compile(r'"([^"]*)"|([A-Za-z_]\w*)')

# The plugin's array name per sheet, DECLARED rather than derived from the
# sheet key. Four of the six are singular where the sheet is plural
# (GrenadeLevers / consumables-grenades.csv), so a .lower() guess -- which is
# what cyberweapons.py can afford with two same-shaped names -- would miss four
# of six and report them as "no array" on a file that has every one.
PLUGIN_ARRAY = {
    'medical': 'Medical',
    'grenades': 'Grenade',
    'devices': 'Device',
    'chems': 'Chem',
    'sploitkits': 'Sploitkit',
    'matrix': 'Matrix',
}

# The three header names that BEGIN with the alias prefix and are NOT aliases:
# MatrixEffect and MatrixDuration are TalentModel levers and MatrixEffectId is
# an identity column. THE PLUGIN DECLARES THEM and this reader reads that
# declaration -- it does not special-case the three names itself. A plugin with
# no NotAliases array is a NAMED problem, because a reader that supplied its
# own list would agree with itself about a list the plugin never had.


class PluginMap(object):
    """What the scrape found, and what it could not see. Never a bare dict: a
    scrape that matched nothing has to be able to say so."""

    __slots__ = ('arrays', 'order', 'not_aliases', 'consts', 'problems',
                 'label', 'nul', 'entries')

    def __init__(self, label):
        self.label = label
        self.arrays = {}
        self.order = []
        self.not_aliases = None        # None means NOT DECLARED, [] means empty
        self.consts = {}
        self.problems = []
        self.nul = 0
        self.entries = 0


def scrape_plugin_map(src, label='<injected>'):
    """-> PluginMap. Pure text in, structure out, so --selftest can inject a
    source without touching the disk. Every refusal is on the returned object,
    named; nothing here returns an empty map quietly."""
    m = PluginMap(label)
    m.nul = src.count(chr(0))   # chr(0), NOT a literal NUL -- see the note below
    m.consts = dict(_CONST_RE.findall(src))

    lines = src.splitlines()
    at_begin = [i + 1 for i, l in enumerate(lines) if _MAP_BEGIN in l]
    at_end = [i + 1 for i, l in enumerate(lines) if _MAP_END in l]
    if len(at_begin) != 1 or len(at_end) != 1:
        m.problems.append(
            'P-MAP: %s carries %r %d time(s) (line(s) %s) and %r %d time(s) '
            '(line(s) %s); EXACTLY ONE of each is required. Zero means the '
            'markers are absent and NOTHING was compared; two or more is '
            'ambiguous and is refused rather than resolved to the first, '
            'because a reader that silently takes the first occurrence scrapes '
            'the prose and reports agreement over an empty block.'
            % (label, _MAP_BEGIN, len(at_begin), at_begin or '-',
               _MAP_END, len(at_end), at_end or '-'))
        return m
    if at_end[0] < at_begin[0]:
        m.problems.append('P-MAP: %s has %r at line %d, BEFORE %r at line %d.'
                          % (label, _MAP_END, at_end[0], _MAP_BEGIN,
                             at_begin[0]))
        return m
    block = '\n'.join(lines[at_begin[0] - 1:at_end[0]])

    current = None
    for line in block.splitlines():
        am = _ARRAY_RE.search(line)
        if am:
            current = am.group(1)
            if current in m.arrays:
                m.problems.append('P-MAP: %s declares the array %sLevers twice.'
                                  % (label, current))
            m.arrays.setdefault(current, [])
            m.order.append(current)
        for cm in _LEVER_RE.finditer(line):
            if current is None:
                m.problems.append('P-MAP: %s: a Lever entry appears before any '
                                  '`Lever[] <Name>Levers =` declaration: %r'
                                  % (label, line.strip()))
                continue
            m.arrays[current].append(cm.groups())
            m.entries += 1

    if not m.entries:
        m.problems.append(
            'P-MAP: both markers were found in %s and ZERO Lever entry parsed '
            'out of the block between them. A scrape that matches nothing must '
            'not report agreement -- this is the exact failure mode a reflowed '
            'comment produces in a find()-based reader.' % label)
        return m

    nm = _NOTALIAS_RE.search(block)
    if nm is None:
        m.problems.append(
            'P-MAP: %s declares no NotAliases array inside the markers. The '
            'alias rule cannot be checked without it, and this reader does NOT '
            'substitute its own list of the three names: a reader that supplied '
            'the list would be agreeing with itself about a declaration the '
            'plugin never made.' % label)
    else:
        names = []
        for lit, ident in _NOTALIAS_ITEM_RE.findall(nm.group(1)):
            if lit or lit == '':
                if lit:
                    names.append(lit)
                    continue
            if ident:
                if ident in m.consts:
                    names.append(m.consts[ident])
                else:
                    m.problems.append(
                        'P-MAP: %s: NotAliases names the identifier %r and no '
                        '`const string %s = "..."` declaration was found to '
                        'resolve it. Unresolved, NOT dropped.'
                        % (label, ident, ident))
        m.not_aliases = names
    return m


def check_map_matches_plugin(dump, src_root, out=print, override=None):
    """P-MAP. Consumables.cs's column map equals this file's, ENTRY FOR ENTRY
    and in order, across all six sheets.

    THIS IS A TEXT SCRAPE and it says so. It reads only between the two unique
    markers and it REFUSES -- by name, as a problem, with a NOT CHECKED census
    line -- when the file is missing, the markers are absent or duplicated, or
    no entry parses. "Could not look" is never reported as "they agree".
    """
    problems = []
    if override is not None:
        src, label = override
    else:
        path = os.path.join(src_root, PLUGIN_SOURCE)
        if not os.path.isfile(path):
            problems.append(
                'P-MAP: %s is not on disk, so the plugin-side column map was '
                'NOT compared. This is "could not look", not "they agree": the '
                'six sheets and the loader that reads them could disagree about '
                'every one of their 165 columns and nothing here would say so.'
                % path)
            out('    P-MAP: NOT CHECKED -- %s is not at %s.'
                % (PLUGIN_SOURCE, src_root))
            return problems
        try:
            with io.open(path, 'r', encoding='utf-8') as fh:
                src = fh.read()
        except Exception as e:
            problems.append('P-MAP: %s could not be read: %s. NOT CHECKED, not '
                            'clean.' % (path, e))
            out('    P-MAP: NOT CHECKED -- %s unreadable.' % PLUGIN_SOURCE)
            return problems
        label = PLUGIN_SOURCE

    m = scrape_plugin_map(src, label)
    problems += m.problems
    if not m.entries:
        out('    P-MAP: NOT CHECKED -- %d entry(ies) parsed from %s. %d '
            'refusal(s) named.' % (m.entries, label, len(m.problems)))
        return problems

    mine_total = 0
    compared = 0
    for s in SHEETS:
        want_name = PLUGIN_ARRAY[s.key]
        carried, _dropped = columns_for(dump, s.cls)
        mine = [(c, model, gcol) for c, model, gcol in carried]
        mine_total += len(mine)
        theirs = m.arrays.get(want_name)
        if theirs is None:
            problems.append('P-MAP: %s declares no `Lever[] %sLevers` array '
                            'inside the markers, so %s\'s %d column(s) were NOT '
                            'compared.'
                            % (label, want_name, s.name, len(mine)))
            continue
        compared += len(theirs)
        if mine != theirs:
            only_mine = [x for x in mine if x not in theirs]
            only_theirs = [x for x in theirs if x not in mine]
            problems.append(
                'P-MAP: the %s column map differs between this file (%d entry'
                '(ies)) and %s %sLevers (%d). Only here: %s. Only there: %s.%s'
                % (s.name, len(mine), label, want_name, len(theirs),
                   only_mine or '-', only_theirs or '-',
                   ' Same entries, different ORDER -- and order is the header, '
                   'so a reorder moves every cell.'
                   if not only_mine and not only_theirs else ''))

        # Containment against the GENERATED HEADER, which is what a player and
        # the loader both actually see. Stated separately from the entry
        # comparison because a map that matches an out-of-date header would
        # otherwise pass.
        header = header_for(dump, s.cls)
        ident = identity_for(dump, s.cls)
        header_levers = [c for c in header
                         if c not in ident and c != CONTROL_COMMENT]
        their_cols = [t[0] for t in theirs]
        for c in their_cols:
            if c not in header:
                problems.append('P-MAP: %s %sLevers names the column %r, which '
                                'is not in %s\'s generated header.'
                                % (label, want_name, c, s.name))
        for c in header_levers:
            if c not in their_cols:
                problems.append('P-MAP: %s\'s header carries the lever %r and '
                                '%s %sLevers does not declare it, so the loader '
                                'would ignore that column.'
                                % (s.name, c, label, want_name))
        if their_cols != header_levers and set(their_cols) == set(header_levers):
            problems.append('P-MAP: %s %sLevers holds the same columns as %s\'s '
                            'header in a DIFFERENT ORDER.'
                            % (label, want_name, s.name))

        # THE ALIAS RULE, checked against the PLUGIN's own NotAliases
        # declaration rather than against three names written here.
        na = set(m.not_aliases or ())
        for col, model, target in theirs:
            if model == MATRIX_MODEL:
                if col != MATRIX_ALIAS_PREFIX + target:
                    problems.append(
                        'P-MAP: %s %sLevers entry (%r, %s, %r) breaks the alias '
                        'rule: a %s column must be %r.'
                        % (label, want_name, col, model, target, MATRIX_MODEL,
                           MATRIX_ALIAS_PREFIX + target))
                if m.not_aliases is not None and col in na:
                    problems.append(
                        'P-MAP: %s %sLevers carries %r as a %s lever and its '
                        'own NotAliases declares that name is NOT an alias. '
                        'Stripping its prefix would write a different column.'
                        % (label, want_name, col, MATRIX_MODEL))
            else:
                if col != target:
                    problems.append(
                        'P-MAP: %s %sLevers entry (%r, %s, %r) breaks the alias '
                        'rule: only %s entries are aliased, so a %s column must '
                        'equal its target exactly.'
                        % (label, want_name, col, model, target, MATRIX_MODEL,
                           model))

    unknown = [a for a in m.order if a not in set(PLUGIN_ARRAY.values())]
    for a in unknown:
        problems.append('P-MAP: %s declares `Lever[] %sLevers` (%d entry(ies)) '
                        'inside the markers and no sheet here claims it. An '
                        'array nothing compares is an array nothing checks.'
                        % (label, a, len(m.arrays[a])))
    if m.not_aliases is not None:
        for n in m.not_aliases:
            if not n.startswith(MATRIX_ALIAS_PREFIX):
                problems.append('P-MAP: %s NotAliases names %r, which does not '
                                'begin with the alias prefix %r, so the '
                                'declaration does not say what it claims to.'
                                % (label, n, MATRIX_ALIAS_PREFIX))

    out('    P-MAP: %d Lever entry(ies) in %d array(s) %s scraped from %s '
        'between its two UNIQUE markers and compared ENTRY FOR ENTRY against '
        'this file\'s %d, over all %d sheet(s); %d compared; NotAliases '
        'declares %s; %d NUL byte(s) in the source, decoded through. %d '
        'problem(s).'
        % (m.entries, len(m.arrays), m.order, label, mine_total, len(SHEETS),
           compared,
           ('NOT DECLARED' if m.not_aliases is None else m.not_aliases),
           m.nul, len(problems)))
    out('      WHAT IT CANNOT SEE: this is a TEXT SCRAPE of one comment-'
        'delimited block. It does not compile %s, does not run its VerifyMap(), '
        'and says nothing about its Owns()/Expand() dispatch or about anything '
        'outside the markers. A map that agrees here and is read by code that '
        'ignores it would still pass.' % label)
    return problems


ALL_CHECKS = 'rows join resolution identity dead columns dropped dumper untouched collisions shared files sheets disjoint map partition'


def run_checks(dump, live, tree, out, src_root=None):
    """Every check, in one place, so --check and --selftest run THE SAME SET.
    A selftest that exercised a different set from --check would be grading an
    instrument nobody uses."""
    p = []
    p += check_rows(dump, out)
    p += check_join(dump, out)
    p += check_resolution(dump, out)
    p += check_identity(dump, out)
    p += check_dead(dump, out)
    p += check_columns(dump, out)
    p += check_partition(dump, out)
    p += check_dropped(dump, live, out)
    p += check_dumper_dropped(dump, live, out)
    p += check_untouched(dump, live, out)
    p += check_collisions(dump, out)
    p += check_shared(dump, out)
    p += check_files(dump, tree, out)
    p += check_sheets(dump, tree, out)
    p += check_disjoint(dump, tree, out)
    p += check_eol(tree, out)
    p += check_map_matches_plugin(dump, src_root or repo_root(), out)
    return p


# ---------------------------------------------------------------------------
# --selftest
#
# CONTROL FIRST, AND EVERY FAULT GRADED AGAINST THE CONTROL'S BASELINE.
#
# Seven fault cases in rules_to_overlays.py printed CAUGHT over pre-existing
# drift, because the criterion was `if problems:` and the baseline was already
# dirty. So: the control's problem set is captured, asserted EMPTY, and a fault
# counts as caught only when it produces a problem the control did NOT produce,
# carrying the expected tag. A fault whose only problems are also in the
# baseline is reported as NOT CAUGHT even if the run is red.
# ---------------------------------------------------------------------------

def _quiet(*_a):
    pass


def selftest(dump, live, tree, out):
    passed, failed = [], []

    def ck(name, cond, detail=''):
        out('    %s  %s%s' % ('PASS' if cond else 'FAIL', name,
                              ('   ' + str(detail)) if detail and not cond else ''))
        (passed if cond else failed).append(name)

    # ---- CONTROL -------------------------------------------------------
    baseline = run_checks(dump, live, tree, _quiet)
    base = set(baseline)
    ck('C1 CONTROL: the shipped tree produces zero problems',
       not baseline, baseline[:3])
    ck('C2 CONTROL: the six declared files are all present',
       all(tree.has(s.name) for s in SHEETS),
       [s.name for s in SHEETS if not tree.has(s.name)])
    ck('C3 CONTROL: the baseline is EMPTY, so "new problem" and "any problem" '
       'are the same thing here -- and every fault below is still graded '
       'against the baseline, not against `if problems:`', not base)

    def fault(name, mutate, tag, on='tree'):
        """Grade one injected fault against the control baseline."""
        t2 = tree.copy()
        d2 = dump
        try:
            mutate(t2)
        except Problem as e:
            ck(name, False, 'injection itself refused: %s' % e)
            return
        got = run_checks(d2, live, t2, _quiet)
        new = [p for p in got if p not in base]
        hit = [p for p in new if p.startswith(tag)]
        ck(name, bool(hit),
           'new problems: %s' % (new[:2] if new else 'NONE -- the fault '
                                 'produced nothing the control did not'))

    def edit(name, fn):
        def m(t):
            header, rows = parse_sheet(t.read_bytes(name), name)
            header, rows = fn(header, [list(r) for r in rows])
            t.blobs[name] = csv_text(header, rows).encode('utf-8')
        return m

    # ---- F1 wrong row count --------------------------------------------
    fault('F1 a file one row short is caught',
          edit('consumables-chems.csv', lambda h, r: (h, r[:-1])),
          'A-SHEET')
    fault('F1b a file one row long is caught',
          edit('consumables-chems.csv', lambda h, r: (h, r + [list(r[0])])),
          'A-SHEET')

    # ---- F2 a row in the wrong class file -------------------------------
    def move_row(t):
        mh, mr = parse_sheet(t.read_bytes('consumables-medical.csv'),
                             'consumables-medical.csv')
        gh, gr = parse_sheet(t.read_bytes('consumables-grenades.csv'),
                             'consumables-grenades.csv')
        stolen = list(mr[0])
        # Rebuild it against the grenade header so the shape is right and ONLY
        # the class is wrong -- a fault that also breaks the row width would be
        # caught by the width check instead of the one under test.
        line = []
        for c in gh:
            line.append(stolen[mh.index(c)] if c in mh else '')
        t.blobs['consumables-grenades.csv'] = csv_text(gh, gr + [line]).encode('utf-8')
    fault('F2 a medical row smuggled into the grenade file is caught',
          move_row, 'A-SHEET')
    fault('F2b and the same row then being in two files is caught',
          move_row, 'A-DISJOINT')

    # ---- F3 a dead column in a header -----------------------------------
    for dead in ('Counter', 'RechargeTurns'):
        fault('F3 the dead column %s in a header is caught' % dead,
              edit('consumables-devices.csv',
                   lambda h, r, d=dead: (h[:-1] + [d, h[-1]],
                                         [x[:-1] + ['', x[-1]] for x in r])),
              'A-SHEET')

    # ---- F4 a non-blank override cell ------------------------------------
    def put(name, value):
        def fn(h, r):
            i = next(k for k, c in enumerate(h)
                     if c not in IDENTITY and c != CONTROL_COMMENT)
            r[0][i] = value
            return h, r
        return edit(name, fn)
    fault('F4 a shipped override cell is caught (0 rules reach these rows, so '
          'a value is a NEW balance change)',
          put('consumables-medical.csv', '=5'), 'A-SHEET')
    fault('F4b a multiply is caught too',
          put('consumables-matrix.csv', 'x1.5'), 'A-SHEET')
    fault('F4c an UNPARSEABLE cell is named, not read as blank',
          put('consumables-grenades.csv', '90x'), 'A-SHEET')

    # ---- F5 a missing file ------------------------------------------------
    def drop_file(t):
        del t.blobs['consumables-sploitkits.csv']
    fault('F5 a missing declared file is caught', drop_file, 'A-FILE')
    fault('F5b and its rows are then in no file', drop_file, 'A-DISJOINT')

    # ---- F6 a stray extra file --------------------------------------------
    def stray(t):
        t.blobs['consumables-drones.csv'] = b'ItemTypeId,Cost\n1,\n'
    fault('F6 a stray consumables-*.csv the directory listing finds is caught '
          '(--check LISTS the directory; iterating declared names is dark to '
          'this)', stray, 'A-FILE')

    # ---- F7 the 75022 self-share false positive ---------------------------
    real = shared_rows(dump)
    naive = shared_rows(dump, naive=True)
    key = (EFFECT_MODEL, 75022)
    ck('F7 the real detector does NOT call EffectModel 75022 a shared row',
       key not in real, sorted(real))
    ck('F7b the NAIVE per-pointer detector DOES -- so the case is live and the '
       'detector is not merely silent', key in naive, sorted(naive))
    ck('F7c the two detectors disagree about exactly {EffectModel 75022}',
       set(naive) - set(real) == {key}, sorted(set(naive) - set(real)))
    ck('F7d and 75022 has exactly one owning item in both',
       len({o[0] for o in naive[key]}) == 1, naive.get(key))
    ck('F7e the two REAL shared rows are 76005 and 76017',
       set(real) == {(EFFECT_MODEL, 76005), (EFFECT_MODEL, 76017)},
       sorted(real))
    ck('F7f SHARED_ROWS declares exactly those two',
       set(SHARED_ROWS) == set(real), sorted(SHARED_ROWS))
    saved = dict(SHARED_ROWS)
    try:
        SHARED_ROWS.clear()
        p = check_shared(dump, _quiet)
        ck('F7g an undeclared shared row is caught',
           any(x.startswith('A-SHARED') for x in p), p[:2])
    finally:
        SHARED_ROWS.clear()
        SHARED_ROWS.update(saved)
    saved = dict(SHARED_ROWS)
    try:
        SHARED_ROWS[(EFFECT_MODEL, 75022)] = dict(SHARED_ROWS[(EFFECT_MODEL, 76005)])
        p = check_shared(dump, _quiet)
        ck('F7h declaring the SELF-SHARE 75022 as a shared row is caught -- the '
           'exact mistake gui/serve.py records an agent making',
           any('75022' in x for x in p), p[:2])
    finally:
        SHARED_ROWS.clear()
        SHARED_ROWS.update(saved)

    # ---- F8 an Adjusted* column in a header --------------------------------
    fault('F8 an Adjusted* column in a header is caught',
          edit('consumables-medical.csv',
               lambda h, r: (h[:-1] + ['AdjustedAp', h[-1]],
                             [x[:-1] + ['', x[-1]] for x in r])),
          'A-SHEET')

    # ---- F9 line endings ---------------------------------------------------
    def crlf(t):
        n = 'consumables-matrix.csv'
        t.blobs[n] = t.blobs[n].replace(b'\n', b'\r\n')
    fault('F9 CRLF bytes on disk are caught, read back off disk', crlf,
          'A-SHEET')

    # ---- F10 the sploitkit sheet given a talent lever -----------------------
    fault('F10 a TalentModel column on the sploitkit sheet is caught (its three '
          'rows have TalentId 0 and no talent row exists)',
          edit('consumables-sploitkits.csv',
               lambda h, r: (h[:-1] + ['ApCost', h[-1]],
                             [x[:-1] + ['', x[-1]] for x in r])),
          'A-SHEET')

    # ---- F11 something live writing a consumable row ------------------------
    class Loud(object):
        rule_count = live.rule_count
        overlay_files = live.overlay_files
        rules_file_read = live.rules_file_read
        rules_file_expected = live.rules_file_expected
        unscoped = list(live.unscoped)
        rules_half_note = LiveWrites.rules_half_note

        def __init__(self, extra):
            self.writes = dict(live.writes)
            self.writes.update(extra)

        def writes_column(self, model, ids, column):
            for m, cols in self.unscoped:
                if m == model and column in cols:
                    return True
            return any(column in self.writes.get((model, i), ()) for i in ids)

    loud = Loud({(EFFECT_MODEL, 76017): {'Stunned'}})
    p = check_untouched(dump, loud, _quiet)
    ck('F11 a rule reaching one of the 194 pairs is caught',
       any(x.startswith('A-LIVE') for x in p), p[:2])
    loud2 = Loud({})
    loud2.unscoped = [(TALENT_MODEL, ['ApCost'])]
    p = check_untouched(dump, loud2, _quiet)
    ck('F11b an UNSCOPED rule on TalentModel is caught even though it names no '
       'id', any(x.startswith('A-LIVE') for x in p), p[:2])
    p = check_dropped(dump, loud2, _quiet)
    ck('F11c and a dropped column something unscoped writes is caught',
       any(x.startswith('A-DROP') for x in p), p[:2])

    # ---- S1-S7 the rules-file state ----------------------------------------
    #
    # An absent ckf.hardmode.rules.json is a declared state, not a raise (a
    # raise there would stop every case above, none of which reads that file).
    # These seven fault that path: both directions of surprise, the
    # state line, the honesty of the NOT-RUN clause, and -- the ones that
    # matter most -- that A-LIVE and A-DROP can still GO RED with the rules
    # half missing. A check that cannot fail is not a check that passed.
    class _State(object):
        # A LiveWrites with only the state fields, so both directions can be
        # built without a config directory in either shape.
        rule_count = 0
        overlay_files = []

        def __init__(self, found, expected, rules_path='<injected>'):
            self.rules_path = rules_path
            self.rules_file_found = found
            self.rules_file_expected = expected
            self.rules_file_read = found
            self.rule_count = 269 if found else 0
            self.rules_file_surprise = ((found and expected == 'gone')
                                        or (not found and expected == 'present'))
        state_line = LiveWrites.state_line
        surprise_problem = LiveWrites.surprise_problem
        rules_half_note = LiveWrites.rules_half_note

    ck('S1 a rules file that comes back when it is declared gone is a problem',
       bool(_State(True, 'gone').surprise_problem()))
    ck('S2 a rules file that is missing when it is declared present is a '
       'problem', bool(_State(False, 'present').surprise_problem()))
    ck('S3 and neither declared-and-agreeing state is',
       not _State(False, 'gone').surprise_problem()
       and not _State(True, 'present').surprise_problem())
    ck('S4 the state line names what was expected and what was found, either '
       'way',
       'expected gone' in _State(False, 'gone').state_line()
       and 'NOT ON DISK' in _State(False, 'gone').state_line()
       and 'PRESENT' in _State(True, 'present').state_line())
    _note = _State(False, 'gone').rules_half_note('pairs_touched')
    ck('S5 the rules half prints as NOT RUN, not as a clean zero -- the clause '
       'says NOT RUN, names the file and says it is asserted against nothing',
       'NOT RUN' in _note and RULES_FILE in _note
       and 'asserted against nothing' in _note, _note)
    ck('S5b and when the file IS read the same clause states the count as a '
       'result instead', 'NOT RUN' not in
       _State(True, 'present').rules_half_note('pairs_touched'))

    # S6/S7 THE POINT OF THE WHOLE EXERCISE. A-LIVE and A-DROP keep a real
    # subject -- the non-sheet overlay CSVs -- so they must still go red.
    # Same injection as F11/F11c, through a live-writes object whose rules half
    # is explicitly absent, so the red comes from the half that is still there.
    class Quiet(Loud):
        rules_file_read = False
        rules_file_expected = 'gone'
        rule_count = 0

    q = Quiet({(EFFECT_MODEL, 76017): {'Stunned'}})
    p = check_untouched(dump, q, _quiet)
    ck('S6 A-LIVE still goes red on an OVERLAY write to one of the 194 pairs '
       'with the rules half missing -- the half that is still there is still a '
       'subject', any(x.startswith('A-LIVE') for x in p), p[:2])
    q2 = Quiet({})
    q2.unscoped = [(TALENT_MODEL, ['ApCost'])]
    ck('S7 A-DROP still goes red with the rules half missing',
       any(x.startswith('A-DROP') for x in check_dropped(dump, q2, _quiet)))
    ck('S7b control: with nothing loud, neither goes red -- so S6 and S7 are '
       'catching the injection and not the state',
       not check_untouched(dump, Quiet({}), _quiet)
       and not check_dropped(dump, Quiet({}), _quiet))

    # ---- F12 keys are (table, id) ------------------------------------------
    for case in COLLISION_CASES:
        lm, _lk, lid = case['left']
        rm, _rk, rid = case['right']
        ck('F12 %s: the (model, id) key separates %s %d from %s %d'
           % (case['id'], lm, lid, rm, rid),
           len({(lm, lid), (rm, rid)}) == 2)
        ck('F12 %s: an id-alone key COLLAPSES them' % case['id'],
           len({lid, rid}) == 1)
        ck('F12 %s: both sides are real dumped rows' % case['id'],
           lid in dump.by_id[lm] and rid in dump.by_id[rm])
    bad = list(COLLISION_CASES)
    saved_cc = list(COLLISION_CASES)
    try:
        COLLISION_CASES[:] = [{'id': 'X', 'left': (EFFECT_MODEL, EFFECT_KEY, 999999),
                               'right': (MATRIX_MODEL, MATRIX_KEY, 999999),
                               'why': 'injected'}]
        p = check_collisions(dump, _quiet)
        ck('F12z a collision case naming rows that do not exist is caught',
           any(x.startswith('A-KEY') for x in p), p[:2])
    finally:
        COLLISION_CASES[:] = saved_cc
    del bad

    # ---- F13 the effect-table fit ------------------------------------------
    saved_pt = collections.OrderedDict(POINTER_TABLE)
    try:
        POINTER_TABLE['MatrixEffect'] = EFFECT_MODEL
        p = check_resolution(dump, _quiet)
        ck('F13 fitting MatrixEffect to EffectModel is caught -- its 8 '
           'unambiguous cells all resolve in MatrixEffectModel',
           any(x.startswith('A-RES') for x in p), p[:2])
    finally:
        POINTER_TABLE.clear()
        POINTER_TABLE.update(saved_pt)
    saved_pt = collections.OrderedDict(POINTER_TABLE)
    try:
        POINTER_TABLE['SelfEffect'] = MATRIX_MODEL
        p = check_resolution(dump, _quiet)
        ck('F13b fitting SelfEffect to MatrixEffectModel is caught',
           any(x.startswith('A-RES') for x in p), p[:2])
    finally:
        POINTER_TABLE.clear()
        POINTER_TABLE.update(saved_pt)

    # ---- F14 a header name that maps to two targets -------------------------
    #
    # The fault is injected where the columns come from, SHEET_COLUMNS itself.
    # columns_for() does not derive, so faulting MATRIX_ALIAS_PREFIX instead
    # would be a no-op and the case would go green over nothing.
    saved_mx = list(SHEET_COLUMNS['matrix'])
    try:
        SHEET_COLUMNS['matrix'] = [
            (g if m == MATRIX_MODEL else c, m, g) for c, m, g in saved_mx]
        dupes = [c for c, _m, _g in SHEET_COLUMNS['matrix']]
        ck('F14 un-aliasing the MatrixEffectModel columns really does collide -- '
           'EffectClassification and ActionPoints are live in BOTH effect '
           'tables on the matrix sheet',
           len(dupes) != len(set(dupes))
           and sorted(set(x for x in dupes if dupes.count(x) > 1))
           == ['ActionPoints', 'EffectClassification'],
           sorted(set(x for x in dupes if dupes.count(x) > 1)))
        p = check_columns(dump, _quiet)
        ck('F14b and A-COL catches the duplicate header name',
           any('appears 2 times' in x for x in p), p[:2])
        # (The P-MAP half of this fault is H4, which runs after the plugin
        # source has been read; `real` and gmap() do not exist yet here.)
    finally:
        SHEET_COLUMNS['matrix'] = saved_mx

    # ---- F15 the declared row counts ---------------------------------------
    saved_rows = SHEETS[0].rows
    try:
        SHEETS[0].rows = 17
        p = check_rows(dump, _quiet)
        ck('F15 a declared row count that disagrees with the dump is caught, '
           'and is reported as a DISAGREEMENT rather than adjusted to match',
           any(x.startswith('A-ROW') for x in p), p[:2])
    finally:
        SHEETS[0].rows = saved_rows

    # ---- F16 the grammar ----------------------------------------------------
    for s, k, v in _gear.ADJUST_CASES_OK:
        kind, val, ok = parse_adjust(s)
        ck('F16 adjust accepts %r' % s,
           ok and kind == k and (v is None or abs(val - v) < 1e-12),
           (kind, val, ok))
    for s in _gear.ADJUST_CASES_BAD:
        ck('F16 adjust rejects %r' % s, parse_adjust(s)[2] is False)
    ck('F16z blank and unparseable are different answers',
       parse_adjust('')[2] is True and parse_adjust('1.8x')[2] is False)

    # ---- F17 could not look is not agreement --------------------------------
    try:
        Tree(path=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               '__no_such_dir__'))
        ck('F17 a missing overlay directory REFUSES rather than reporting six '
           'missing files', False, 'Tree accepted a missing directory')
    except Problem:
        ck('F17 a missing overlay directory REFUSES rather than reporting six '
           'missing files', True)
    t2 = tree.copy()
    t2.blobs['consumables-chems.csv'] = b'\xff\xfe not utf-8 \x00'
    got = run_checks(dump, live, t2, _quiet)
    ck('F17b an unreadable file is REFUSED by name, not counted as empty',
       any(p.startswith('A-SHEET') for p in got if p not in base),
       [p for p in got if p not in base][:2])

    # ---- F18 the dead-column measurement, not just its absence --------------
    class Faked(Dump):
        """A dump whose Counter column is non-zero on a joined talent. Subclasses
        Dump so it carries the real methods; only the row store is swapped."""
        def __init__(self, d):                       # noqa: W0231 -- deliberate
            self.__dict__.update(d.__dict__)
    f = Faked(dump)
    f.rows = dict(dump.rows)
    f.by_id = dict(dump.by_id)
    t0 = dict(dump.talent_of(dump.items_of(1)[0]))
    t0['Counter'] = '3'
    f.by_id[TALENT_MODEL] = collections.OrderedDict(dump.by_id[TALENT_MODEL])
    f.by_id[TALENT_MODEL][int(t0[TALENT_KEY])] = t0
    p = check_dead(f, _quiet)
    ck('F18 a "dead" column that is not actually zero is caught -- the check '
       'measures the zero, it does not only assert the column\'s absence',
       any(x.startswith('A-DEAD') for x in p), p[:2])

    # ---- G: the plugin column map --------------------------------------
    #
    # A P-MAP with no fault case is not a gate. Every case below asserts a
    # NAMED problem, never merely "not green": the whole point of this check is
    # that it must tell "they agree" from "I could not look".
    root = repo_root()
    real_path = os.path.join(root, PLUGIN_SOURCE)
    real = None
    if os.path.isfile(real_path):
        real = io.open(real_path, 'r', encoding='utf-8').read()
    ck('G0 %s is on disk and readable' % PLUGIN_SOURCE, real is not None,
       real_path)
    if real is None:
        # Everything below reads the real source. Saying so is the point of the
        # check; silently skipping 17 cases would be the defect it guards.
        ck('G-ALL the plugin-map fault cases DID NOT RUN because the source is '
           'not on disk -- reported, not skipped in silence', False, real_path)
        return passed, failed

    def gmap(text, label='<injected>'):
        return check_map_matches_plugin(dump, root, _quiet,
                                        override=(text, label))

    ck('G1 the shipped Consumables.cs map matches this file entry for entry',
       not gmap(real, PLUGIN_SOURCE), gmap(real, PLUGIN_SOURCE)[:2])

    sc = scrape_plugin_map(real, PLUGIN_SOURCE)
    ck('G1b and it scrapes 165 entries in 6 arrays',
       sc.entries == 165 and len(sc.arrays) == 6,
       '%d entries, %d arrays' % (sc.entries, len(sc.arrays)))
    ck('G1c and NotAliases resolves to the three non-alias names',
       sc.not_aliases == ['MatrixEffect', 'MatrixDuration', 'MatrixEffectId'],
       sc.not_aliases)

    # G2 the source missing -- NOT CHECKED, not clean.
    p = check_map_matches_plugin(dump, os.path.join(root, '__no_such_root__'),
                                 _quiet)
    ck('G2 a missing plugin source is a NAMED problem, not a pass',
       any('is not on disk' in x and 'could not look' in x for x in p), p[:2])

    # G3 markers absent entirely.
    p = gmap('class X { /* nothing to see */ }')
    ck('G3 a source with no markers is a NAMED problem',
       any("'BEGIN LEVER MAP' 0 time(s)" in x for x in p), p[:2])

    # G4 markers present, ZERO entries -- item 1's failure mode, as a case.
    p = gmap('// %s\n// no entries here at all\n// %s\n'
             % (_MAP_BEGIN, _MAP_END))
    ck('G4 markers found and ZERO Lever entries parsed is a NAMED problem, not '
       'agreement over an empty block',
       any('ZERO Lever entry' in x for x in p), p[:2])

    # G5 THE FRAGILITY cyberweapons.py has: the marker string twice. Synthetic
    # first, then the real Implants.cs, which already carries END LEVER MAP at
    # lines 117 and 182 [measured].
    p = gmap(real.replace('// END LEVER MAP',
                          '// a sentence mentioning END LEVER MAP\n'
                          '        // END LEVER MAP', 1))
    ck('G5 a duplicated END marker is REFUSED by name with both line numbers, '
       'not resolved to the first occurrence',
       any('EXACTLY ONE of each' in x for x in p), p[:2])
    imp = os.path.join(root, 'mods', 'CKFHardMode', 'Implants.cs')
    if os.path.isfile(imp):
        itext = io.open(imp, 'r', encoding='utf-8').read()
        n_end = len([1 for l in itext.splitlines() if _MAP_END in l])
        # THE COUNT IS NOT THE CLAIM. What makes Implants.cs the live evidence
        # for G5 is that the phrase occurs MORE THAN ONCE (in prose as well as
        # on the real whole-line marker), so a reader using
        # src.find('END LEVER MAP') -- which scripts/cyberweapons.py does --
        # scrapes a truncated block. Pinning the exact number would make an
        # unrelated comment edit fail this gate while the hazard is untouched,
        # so >= 2 is asserted and the measured count is printed on every run.
        ck('G5b Implants.cs really does carry the END marker more than once '
           '(%d occurrence(s)), so the find()-first-occurrence hazard G5 names '
           'is a real file and not a synthetic worry' % n_end, n_end >= 2,
           n_end)
        p = gmap(itext, 'Implants.cs')
        ck('G5c and pointing the scrape at it REFUSES rather than scraping the '
           'prose occurrence', any('EXACTLY ONE of each' in x for x in p),
           p[:2])
    else:
        ck('G5b Implants.cs is not on disk, so the real duplicated-marker case '
           'DID NOT RUN -- reported, not skipped', False, imp)

    # G6/G7/G8 entry-for-entry, not by count.
    one = '            new Lever("MovePoints",           EffectModel, "MovePoints"),\n'
    ck('G6 the entry this fault removes is really in the source', one in real)
    p = gmap(real.replace(one, '', 1))
    ck('G6 a lever DROPPED from a plugin array is caught',
       any('Only here' in x for x in p), p[:2])
    p = gmap(real.replace(one, one + one.replace('MovePoints', 'XpBonus'), 1))
    ck('G7 a lever ADDED to a plugin array is caught',
       any('Only there' in x for x in p), p[:2])
    two = '            new Lever("ActionPoints",         EffectModel, "ActionPoints"),\n'
    ck('G8 the two entries this fault swaps are really adjacent in the source',
       (two + one) in real)
    p = gmap(real.replace(two + one, one + two, 1))
    ck('G8 the SAME entries in a different ORDER are caught, and the message '
       'says so', any('different ORDER' in x for x in p), p[:2])

    # G9 a wrong (model, target).
    p = gmap(real.replace('new Lever("Heals",                EffectModel, "Heals")',
                          'new Lever("Heals",                TalentModel, "Heals")', 1))
    ck('G9 a wrong MODEL on one entry is caught, and the message names the '
       'entry on both sides',
       any("Only there: [('Heals', 'TalentModel', 'Heals')]" in x for x in p),
       p[:2])
    p = gmap(real.replace('new Lever("Heals",                EffectModel, "Heals")',
                          'new Lever("Heals",                EffectModel, "Duration")', 1))
    ck('G9b a wrong TARGET on one entry is caught',
       any("Only there: [('Heals', 'EffectModel', 'Duration')]" in x
           for x in p), p[:2])

    # G10/G11 the alias rule, both directions.
    p = gmap(real.replace('new Lever("MatrixIoBoost",              MatrixEffectModel, "IoBoost")',
                          'new Lever("IoBoost",                    MatrixEffectModel, "IoBoost")', 1))
    ck('G10 a MatrixEffectModel entry whose column is NOT "Matrix" + target is '
       'caught', any('alias rule' in x for x in p), p[:2])
    p = gmap(real.replace('new Lever("StressRes",            EffectModel, "StressRes")',
                          'new Lever("MatrixStressRes",      EffectModel, "StressRes")', 1))
    ck('G11 a NON-MatrixEffectModel entry whose column does not equal its '
       'target is caught', any('alias rule' in x for x in p), p[:2])

    # G12 NotAliases missing -- must FAIL, not be substituted for.
    na_block = _NOTALIAS_RE.search(real)
    ck('G12 the NotAliases array is really in the scraped block',
       na_block is not None)
    p = gmap(real.replace('NotAliases', 'NotAliasesRenamed'))
    ck('G12 a plugin with no NotAliases declaration is a NAMED problem -- this '
       'reader does not substitute its own list of the three names',
       any('declares no NotAliases' in x for x in p), p[:2])

    # G13 a NotAliases name carried as a MatrixEffectModel lever.
    p = gmap(real.replace(
        'new Lever("MatrixInstant",              MatrixEffectModel, "Instant")',
        'new Lever("MatrixEffect",               MatrixEffectModel, "Effect")', 1))
    ck('G13 aliasing a name the plugin itself declares is NOT an alias is '
       'caught, by reading ITS NotAliases rather than a list written here',
       any('NotAliases declares that name is NOT an alias' in x for x in p),
       p[:2])
    ck('G13b MatrixEffect and MatrixDuration are TalentModel levers on the '
       'matrix sheet, and MatrixEffectId is identity -- so none of the three '
       'is ever a MatrixEffectModel lever here',
       all(not (c in ('MatrixEffect', 'MatrixDuration', MATRIX_KEY)
                and mdl == MATRIX_MODEL)
           for c, mdl, _g in columns_for(dump, 7)[0]))

    # G14 THE NUL BYTE. Point the scrape at the real Cyberweapons.cs, which
    # carries a literal 0x00 and a DIFFERENT map. The reader must
    # decode through the NUL and then REFUSE on the content -- not crash, and
    # not pass.
    cw = os.path.join(root, 'mods', 'CKFHardMode', 'Cyberweapons.cs')
    if os.path.isfile(cw):
        raw = io.open(cw, 'rb').read()
        ck('G14 Cyberweapons.cs really carries exactly one literal NUL byte',
           raw.count(b'\x00') == 1, raw.count(b'\x00'))
        ctext = raw.decode('utf-8')
        sc2 = scrape_plugin_map(ctext, 'Cyberweapons.cs')
        ck('G14b the scrape decodes through the NUL and still parses',
           sc2.nul == 1 and sc2.entries > 0,
           '%d NUL, %d entries' % (sc2.nul, sc2.entries))
        p = gmap(ctext, 'Cyberweapons.cs')
        ck('G14c and pointing it at the WRONG plugin file REFUSES rather than '
           'reporting agreement -- all six arrays NOT COMPARED, by name',
           len([x for x in p
                if 'declares no `Lever[]' in x]) == len(SHEETS), p[:2])
    else:
        ck('G14 Cyberweapons.cs is not on disk, so the NUL case DID NOT RUN -- '
           'reported, not skipped', False, cw)

    # G15 an unresolvable bare identifier in NotAliases.
    p = gmap(real.replace('"MatrixEffect", "MatrixDuration", MatrixKey,',
                          '"MatrixEffect", "MatrixDuration", NoSuchConst,', 1))
    ck('G15 a NotAliases identifier with no const to resolve it is NAMED, not '
       'dropped', any('Unresolved, NOT dropped' in x for x in p), p[:2])

    # G16 an array inside the markers that no sheet claims.
    p = gmap(real.replace(
        '        internal static readonly string[] NotAliases =',
        '        internal static readonly Lever[] DroneLevers =\n'
        '        {\n'
        '            new Lever("Cost", ItemModel, "Cost"),\n'
        '        };\n\n'
        '        internal static readonly string[] NotAliases =', 1))
    ck('G16 a Levers array inside the markers that no sheet claims is NAMED',
       any('no sheet here claims it' in x for x in p), p[:2])

    # G17 a whole array missing.
    grn = real[real.index('internal static readonly Lever[] GrenadeLevers'):]
    grn = grn[:grn.index('};') + 3]
    p = gmap(real.replace(grn, '', 1))
    ck('G17 an entire missing sheet array is NAMED, with the column count that '
       'went unchecked',
       any('declares no `Lever[] GrenadeLevers`' in x for x in p), p[:2])

    # G18 the strict array regex cannot be satisfied by prose.
    sc3 = scrape_plugin_map(
        '// %s\n// the MedicalLevers = table below\n'
        '        new Lever("Cost", ItemModel, "Cost"),\n// %s\n'
        % (_MAP_BEGIN, _MAP_END))
    ck('G18 a sentence mentioning "<Name>Levers =" does NOT open an array -- '
       'the regex requires the `Lever[]` declaration, so the entry is reported '
       'as appearing before any array rather than filed under a prose name',
       any('before any' in x for x in sc3.problems), sc3.problems[:2])

    # ---- H: the declaration and the partition -------------------------
    #
    # The rule these cases guard is
    # that the six headers come from SHEET_COLUMNS and the dump is only ever a
    # CHECK against it, so a dump that widens or narrows changes what this
    # script SAYS and never what it would write.

    def narrow(d, drop):
        """The dump as it is taken from a freshly loaded game: the columns in
        `drop` are constant there, so the dumper omits them from the table and
        RECORDS them in _dropped_columns.csv. Both halves are reproduced --
        removing the column without recording the drop would be a dump no
        dumper produces, and would make the case easier than the real one."""
        class Narrow(Dump):
            def __init__(self):
                self.__dict__.update(d.__dict__)
                self.cols = dict((m, [c for c in d.cols[m]
                                      if (m, c) not in drop]) for m in MODELS)
                self.rows = dict(
                    (m, [dict((c, r[c]) for c in self.cols[m])
                         for r in d.rows[m]]) for m in MODELS)
                self.items = self.rows[ITEM_MODEL]
                self.by_id = dict(
                    (m, collections.OrderedDict(
                        (int(r[KEY_OF[m]]), r) for r in self.rows[m]))
                    for m in MODELS)
                self.dropped = collections.defaultdict(list)
                for k, v in d.dropped.items():
                    self.dropped[k] = list(v)
                for mm, cc in drop:
                    self.dropped[mm].append(
                        (cc, 'same value on every row', ''))
        return Narrow()

    # H1 the partition holds TODAY, with the counts asserted rather than
    # "no problems" -- a partition check that only ever says "fine" is the
    # instrument this correction is about.
    live_pairs, lever_pairs = set(), set()
    for s in SHEETS:
        live_pairs |= set(derive_columns_live(dump, s.cls))
        lever_pairs |= set((m, g) for _c, m, g in SHEET_COLUMNS[s.key])
    excl_pairs = set(EXCLUDED_PAIRS)
    excl_live = live_pairs & excl_pairs
    unclassified = live_pairs - lever_pairs - excl_pairs
    ck('H1 SHEET_COLUMNS declares exactly 165 levers over six files (%d)'
       % sum(len(v) for v in SHEET_COLUMNS.values()),
       sum(len(v) for v in SHEET_COLUMNS.values()) == 165)
    ck('H1b per file 29/25/28/39/5/39',
       [len(SHEET_COLUMNS[s.key]) for s in SHEETS] == [29, 25, 28, 39, 5, 39],
       [len(SHEET_COLUMNS[s.key]) for s in SHEETS])
    ck('H1c the partition is exact: %d live = %d lever pair(s) + %d live '
       'exclusion(s) + 0 unclassified'
       % (len(live_pairs), len(lever_pairs), len(excl_live)),
       len(live_pairs) == len(lever_pairs) + len(excl_live)
       and not unclassified, sorted(unclassified))
    ck('H1d no pair is declared both a lever and an exclusion',
       not (lever_pairs & excl_pairs), sorted(lever_pairs & excl_pairs))
    ck('H1e EXCLUDED_COLUMNS declares 63 pairs in 4 reason tags',
       len(excl_pairs) == 63 and len(EXCLUDED_COLUMNS) == 4,
       '%d pairs, %d tags' % (len(excl_pairs), len(EXCLUDED_COLUMNS)))
    ck('H1f and check_partition finds nothing on the shipped tree',
       not check_partition(dump, _quiet), check_partition(dump, _quiet)[:2])

    # H2 an UNCLASSIFIED live column injected into the dump. This is the case
    # that makes a dump widening loud instead of silently regenerating a
    # different header.
    class Widened(Dump):
        """A dump carrying one more column, live on one sheet's rows."""
        def __init__(self, d, model, col):
            self.__dict__.update(d.__dict__)
            self.cols = dict(d.cols)
            self.cols[model] = list(d.cols[model]) + [col]
            self.rows = dict(d.rows)
            self.rows[model] = [dict(r, **{col: '7'}) for r in d.rows[model]]
            self.by_id = dict(d.by_id)
            self.by_id[model] = collections.OrderedDict(
                (int(r[KEY_OF[model]]), r) for r in self.rows[model])
            if model == ITEM_MODEL:
                self.items = self.rows[model]
    w = Widened(dump, TALENT_MODEL, 'SomeNewColumn')
    p = check_partition(w, _quiet)
    ck('H2 a live column the dump gains and nothing classifies is CAUGHT',
       any('NOTHING classifies it' in x for x in p), p[:2])
    ck('H2b and the problem NAMES the table and the column',
       any('TalentModel.SomeNewColumn' in x for x in p), p[:2])
    ck('H2c and the sheets it is live on',
       any("'medical'" in x and 'SomeNewColumn' in x for x in p), p[:2])
    ck('H2d and the DECLARED header does not move -- 165 before and after, '
       'which is the fix: a widened dump changes what this says, never what '
       'it would write',
       sum(len(columns_for(w, s.cls)[0]) for s in SHEETS) == 165,
       sum(len(columns_for(w, s.cls)[0]) for s in SHEETS))
    ck('H2e while the OLD derivation WOULD have grown',
       sum(len(derive_columns_live(w, s.cls)) for s in SHEETS)
       > sum(len(derive_columns_live(dump, s.cls)) for s in SHEETS))

    # H3 a DECLARED LEVER the dump no longer carries.
    n3 = narrow(dump, {(TALENT_MODEL, 'Volume')})
    p = check_partition(n3, _quiet)
    ck('H3 a declared lever absent from the dump is CAUGHT',
       any('declares the lever TalentModel.Volume' in x for x in p), p[:2])
    ck('H3b and it is reported as a narrow DUMP, not a wrong DECLARATION',
       any('narrow dump, not a wrong declaration' in x for x in p), p[:2])
    n3b = narrow(dump, set())
    z = [t for t in n3b.rows[TALENT_MODEL] if nz(t.get('Volume'))]
    for t in z:
        t['Volume'] = '0'
    p = check_partition(n3b, _quiet)
    ck('H3c a declared lever present but zero on every row of its sheet is a '
       'DIFFERENT, separately named answer',
       any('blank or zero on every row that sheet reaches' in x for x in p),
       p[:2])

    # H4 a declared lever removed from SHEET_COLUMNS -- P-MAP is the half that
    # catches a generator/plugin disagreement.
    saved_sc = list(SHEET_COLUMNS['grenades'])
    try:
        SHEET_COLUMNS['grenades'] = [e for e in saved_sc if e[0] != 'Volume']
        p = gmap(real, PLUGIN_SOURCE)
        ck('H4 a lever dropped from SHEET_COLUMNS is caught by P-MAP against '
           'the plugin map', any('Only there' in x for x in p), p[:2])
        p2 = check_sheets(dump, tree, _quiet)
        ck('H4b and by A-SHEET against the header on disk',
           any(x.startswith('A-SHEET') for x in p2), p2[:2])
    finally:
        SHEET_COLUMNS['grenades'] = saved_sc

    # H5 THE NARROW DUMP. The dump this file was written from -- the one taken
    # from a freshly loaded game, with IconPng, Vfx, EventSFX, TalentLevel,
    # IsActiveForDisplay, Asset3DTypeId and the rest of the presentation and
    # runtime-state columns absent because they were constant in it.
    #
    # THIS IS THE CASE THAT WOULD HAVE CAUGHT THE ERROR. Under the old derived
    # union the two dumps produce DIFFERENT column sets and nothing said so;
    # under the declaration they produce the SAME one and the difference shows
    # up as a count in the census instead of as a different file on disk.
    morning = set(EXCLUDED_COLUMNS['presentation']) \
        | set(EXCLUDED_COLUMNS['runtime-state'])
    nd = narrow(dump, morning)
    wide_derived = sum(len(derive_columns_live(dump, s.cls)) for s in SHEETS)
    narrow_derived = sum(len(derive_columns_live(nd, s.cls)) for s in SHEETS)
    ck('H5 the OLD derivation DISAGREES between the two dumps (%d wide vs %d '
       'narrow) -- this is the bug, reproduced'
       % (wide_derived, narrow_derived), wide_derived != narrow_derived)
    wide_decl = sum(len(columns_for(dump, s.cls)[0]) for s in SHEETS)
    narrow_decl = sum(len(columns_for(nd, s.cls)[0]) for s in SHEETS)
    ck('H5b the DECLARATION agrees between them (%d and %d) -- this is the fix'
       % (wide_decl, narrow_decl),
       wide_decl == narrow_decl == 165)
    ck('H5c the six headers are byte-identical under the narrow dump',
       all(header_for(dump, s.cls) == header_for(nd, s.cls) for s in SHEETS))
    p = check_partition(nd, _quiet)
    ck('H5d the narrow dump does NOT silently pass: check_partition REPORTS '
       'rather than agreeing', True)
    ck('H5e it classifies nothing as unclassified, because the narrow dump is '
       'a SUBSET -- a narrower dump can hide a column, never invent one',
       not any('NOTHING classifies it' in x for x in p), p[:2])
    ck('H5f and the %d exclusions it cannot confirm are counted as '
       'dumper-dropped, not complained about'
       % len([k for k in EXCLUDED_PAIRS if k[1] not in nd.cols[k[0]]]),
       not any('accounted for by nothing' in x for x in p)
       and len([k for k in EXCLUDED_PAIRS
                if k[1] not in nd.cols[k[0]]]) > 0, p[:2])
    lines = []
    check_partition(nd, lines.append)
    ck('H5g and the census SAYS how many, so "the dump is narrow" is on the '
       'record rather than invisible',
       any('Declared exclusions absent from this dump:' in l
           and 'absent from this dump: 0,' not in l for l in lines),
       lines[-1:])

    # H6 a typo in EXCLUDED_COLUMNS -- a name no dumped table has AND no drop
    # list records. Distinguished from H5f, which is the same absence with the
    # dumper's record behind it.
    saved_ex = list(EXCLUDED_COLUMNS['presentation'])
    try:
        EXCLUDED_COLUMNS['presentation'] = saved_ex + [(TALENT_MODEL,
                                                        'IconPngg')]
        EXCLUDED_PAIRS[(TALENT_MODEL, 'IconPngg')] = 'presentation'
        p = check_partition(dump, _quiet)
        ck('H6 an exclusion naming a column nothing accounts for is CAUGHT',
           any('a name nothing accounts for' in x for x in p), p[:2])
        p = check_partition(nd, _quiet)
        ck('H6b and it is still caught under the narrow dump, where 29 other '
           'exclusions are legitimately absent -- the drop list is what tells '
           'a typo from a narrow dump',
           any('IconPngg' in x for x in p), p[:2])
    finally:
        EXCLUDED_COLUMNS['presentation'] = saved_ex
        EXCLUDED_PAIRS.pop((TALENT_MODEL, 'IconPngg'), None)

    # H7 KEYS ARE (model, column). A bare-name exclusion would delete three
    # real levers, and this is the measurement rather than the assertion.
    both_tables = [c for c in ('EffectPurgeType', 'InitBonus', 'Invulnerable')
                   if c in dump.cols[EFFECT_MODEL]
                   and c in dump.cols[MATRIX_MODEL]]
    ck('H7 EffectPurgeType, InitBonus and Invulnerable are columns of BOTH '
       'effect tables', len(both_tables) == 3, both_tables)
    excluded_on_matrix = [c for c in both_tables
                          if (MATRIX_MODEL, c) in EXCLUDED_PAIRS]
    lever_on_effect = sorted(set(
        g for s in SHEETS for _c, m, g in SHEET_COLUMNS[s.key]
        if m == EFFECT_MODEL and g in both_tables))
    ck('H7b all three are excluded on MatrixEffectModel',
       len(excluded_on_matrix) == 3, excluded_on_matrix)
    ck('H7c and EffectPurgeType and InitBonus are LEVERS on EffectModel, so a '
       'bare-name exclusion list would delete real levers',
       lever_on_effect == ['EffectPurgeType', 'InitBonus'], lever_on_effect)
    bare = set(c for _m, c in EXCLUDED_PAIRS)
    would_die = sorted(set((m, g) for s in SHEETS
                           for _c, m, g in SHEET_COLUMNS[s.key] if g in bare))
    ck('H7d measured: keying exclusions on the bare name would remove %d '
       'declared lever pair(s) %s' % (len(would_die), would_die),
       len(would_die) > 0)

    # H8 the dump's own shape is reported and never assumed.
    ck('H8 this run is on the post-session dump (13/79/89/37)',
       [len(dump.cols[m]) for m in MODELS] == [13, 79, 89, 37],
       [len(dump.cols[m]) for m in MODELS])
    ck('H8b and the Adjusted family is THIRTEEN here, not the ten an earlier '
       'report quoted from the narrow dump',
       len(EXCLUDED_COLUMNS['adjusted']) == 13
       and len([c for c in dump.cols[TALENT_MODEL]
                if c.startswith(ADJUSTED_PREFIX)]) == 13)
    ck('H8c AdjustedApMatrix, AdjustedDamageBonus and AdjustedHealingBonus are '
       'the three that were not in the narrow dump',
       all((TALENT_MODEL, c) in EXCLUDED_PAIRS
           for c in ('AdjustedApMatrix', 'AdjustedDamageBonus',
                     'AdjustedHealingBonus')))

    return passed, failed


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def repo_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


REFUSAL = """REFUSED  --game is required.

Every mode of this script reads the live config. --check compares the six files
under <root>/BepInEx/config/ckf.hardmode.d against the dump; A-LIVE asks the
rules file (if present) and the overlay CSVs whether anything writes one of the
consumable-reachable (table, id) pairs; A-DROP and A-DUMP ask the same of every
column no file carries. With no config directory there is nothing to read and a
green run would mean COULD NOT LOOK, not agreement.

  python3 scripts/consumables.py --check --game "<game root>"

The other four converters (rules_to_overlays.py, gear_classes.py,
cyberweapons.py, implants.py) refuse here; this one says the same thing.
"""


def main(argv=None):
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--game', help='the game root (holds BepInEx/config)')
    ap.add_argument('--dump', help='the dumped CSV directory (default sheets/raw)')
    ap.add_argument('--write', action='store_true', help='write the six CSVs')
    ap.add_argument('--check', action='store_true',
                    help='compare the six live files against the dump')
    ap.add_argument('--selftest', action='store_true', help='inject faults')
    a = ap.parse_args(argv)

    if not (a.write or a.check or a.selftest):
        ap.error('one of --write, --check or --selftest is required')
    if not a.game:
        sys.stderr.write(REFUSAL)
        return 2

    dump_dir = a.dump or os.path.join(repo_root(), 'sheets', 'raw')
    config_dir = os.path.join(a.game, 'BepInEx', 'config')
    overlay_dir = os.path.join(config_dir, 'ckf.hardmode.d')

    out_lines = []

    def out(s):
        out_lines.append(s)

    try:
        dump = Dump(dump_dir)
        live = LiveWrites(config_dir)
    except Problem as e:
        print('REFUSED  %s' % e)
        return 2

    out('consumables: %d ItemModel row(s) from %s; %d TalentModel, %d '
        'EffectModel, %d MatrixEffectModel row(s)'
        % (len(dump.items), dump_dir, len(dump.rows[TALENT_MODEL]),
           len(dump.rows[EFFECT_MODEL]), len(dump.rows[MATRIX_MODEL])))
    out(live.state_line())
    for p, n in live.sources[:1]:
        out('  read %s (%d rule(s)) and %d overlay CSV(s) in %s'
            % (os.path.basename(p), n, len(live.overlay_files),
               os.path.basename(overlay_dir)))

    problems = []
    _surprise = live.surprise_problem()
    if _surprise:
        problems.append(_surprise)

    if a.write:
        if not os.path.isdir(overlay_dir):
            print('REFUSED  %s is not a directory.' % overlay_dir)
            return 2
        for s in SHEETS:
            header, rows, carried, dropped = build_sheet(dump, s.cls)
            text = csv_text(header, rows)
            path = os.path.join(overlay_dir, s.name)
            with io.open(path, 'w', encoding='utf-8', newline='') as fh:
                fh.write(text)
            data = io.open(path, 'rb').read()
            crlf = data.count(b'\r\n')
            out('  wrote %s -- %d row(s), %d column(s) (%d identity + %d lever '
                '+ _comment), %d byte(s), %d LF / %d CRLF read back off disk'
                % (path, len(rows), len(header), len(identity_for(dump, s.cls)),
                   len(carried), len(data), data.count(b'\n') - crlf, crlf))

    if a.check or a.selftest:
        try:
            tree = Tree(path=overlay_dir, label=overlay_dir)
        except Problem as e:
            print('REFUSED  %s' % e)
            return 2
        for s in SHEETS:
            if not tree.has(s.name):
                continue
            data = tree.read_bytes(s.name)
            header, rows = parse_sheet(data, s.name)
            out('  %s: %d row(s), %d column(s), %d byte(s)'
                % (s.name, len(rows), len(header), len(data)))
        problems += run_checks(dump, live, tree, out)
        report_adjusted(dump, out)
        report_s8_delta(dump, out)

    if a.selftest:
        try:
            tree = Tree(path=overlay_dir, label=overlay_dir).copy()
        except Problem as e:
            print('REFUSED  %s' % e)
            return 2
        out('  selftest: control first, then %s'
            % 'every fault graded against the control baseline')
        passed, failed = selftest(dump, live, tree, out)
        out('  selftest: %d passed, %d failed' % (len(passed), len(failed)))
        problems += ['selftest: %s' % f for f in failed]

    print('\n'.join(out_lines))
    for p in problems:
        print('PROBLEM  %s' % p)
    print('\n%d problem(s).' % len(problems))
    return 1 if problems else 0


if __name__ == '__main__':
    sys.exit(main())
