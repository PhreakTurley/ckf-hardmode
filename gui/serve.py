#!/usr/bin/env python3
"""
CKF Hard Mode config GUI — the server half.

    python3 serve.py                     # bind a free port on 127.0.0.1, open a browser
    python3 serve.py --no-browser
    python3 serve.py --config DIR        # point at a BepInEx/config directory directly
    python3 serve.py --selftest          # run the verification suite, write nothing outside a temp dir

Stdlib only. This process does every byte of file I/O; app.html never names a
path. The repo is the source of truth: schemas are read from ../schema and
../scripts is imported by relative path. Nothing is copied into gui/.

WHAT THIS OWNS

  ckf.hardmode.cfg                  ONE key, [General] Enabled: its value line is
                                    replaced in place, and nothing else in the
                                    file is ever touched. 3.0 moved the other 21
                                    keys into the merged document, so the
                                    append-a-missing-key path and the two
                                    round-trip refusals it needed went with them.
  ckf.hardmode.json                 nine sections, one per subsystem
  ckf.hardmode.d/MissionPowerLevelModel.generated.json   (regenerated, see MIRROR)

WHAT IT DELIBERATELY DOES NOT OWN

  ckf.hardmode.rules.json, ckf.hardmode.d/*.csv, ckf.hardmode.selfcheck.csv.
  Bulk table authoring with its own grammar and its own editor.

CORRECTION, 2026-09-14. THE TWO BLOCKS ABOVE DESCRIBE THE 3.x LAYOUT AND THE
EDITOR'S SAVE PATH, AND BOTH ARE STILL TRUE OF THAT PATH. They are not true of
the whole file any more, and the difference matters to anyone reading them as
an inventory:

  * ckf.hardmode.cfg holds 43 keys in 4.0, not one. The SAVE path still edits
    one value line at a time and touches nothing else, which is what that
    paragraph is about. The MIGRATION path below writes the file whole, once,
    and carries the 3.x [General] block across byte for byte.
  * ckf.hardmode.json does not exist in 4.0. It is nine files under
    ckf.hardmode.d/ and a .pre-4.0-backup, and splitting it is the migration's
    first step.
  * ckf.hardmode.d/*.csv is still not EDITED here -- the expanders own those --
    but the migration WRITES them once, on conversion, and then never again.

MIGRATION (design.md section 13)

  RETIRED FROM THE DEFAULT --selftest, 2026-09-15, by David's ruling. The
  migrator and its 67 selftest cases are all still here; `--selftest
  --migration` runs them. The default suite reports them NOT RUN by name. See
  the banner above migration_report_retired.

  build_migration / run_migration convert a 3.x install to the 4.0 layout: 68
  files out of three files in, with the four sanctioned deviations applied
  DURING the conversion rather than after it. Two of the four are deletions
  with no expander to reuse, so a converter that preserves every operand of
  every rule gets them wrong; see the block above MigrationRefused for which
  and why. Every failure there is a refusal that has written nothing.

UNSET IS NOT ZERO

  Every numeric slot carries a two-state value: (present, value). Absent on
  disk round-trips as absent; 0 round-trips as 0. On the wire a cell is `null`
  for absent and a number for present, and the writer pops the key rather than
  writing a zero. This is the requirement that corrupts config silently when it
  is got wrong -- Fatigue.cs:404 (a byPowerLevel anchor's maxAffected absent =
  no ceiling, 0 = a ceiling of zero), RewardCurve.cs:249-251 (a column missing
  or negative keeps the game's number). CITATION CORRECTION, 2026-09-07: this
  cited Fatigue.cs:305-307 and the flat runningEmpty.maxAffected, which is off
  the config surface now; the field it names is an anchor's.

MIRROR (gui-plan.md 5.3)

  The "teampl" section of ckf.hardmode.json and
  ckf.hardmode.d/MissionPowerLevelModel.generated.json
  are two halves of one invariant. They are written in one transaction: every
  file is serialised to a temporary in its own directory and fsynced, a journal
  naming the pending renames is committed atomically, then the renames run
  back to back with no work between them, then the journal is removed. A crash
  between the two renames leaves the journal and the surviving temporaries on
  disk; the next start finishes them (recover_journal). The mirror is renamed
  first because it is the machine-owned, fully derivable half -- whatever state
  a crash leaves, regenerating it from whatever teampl.json then holds
  converges, and the hand-authored file is the last thing touched.

VALIDATION

  schema/check_schema.py is imported and run, not reimplemented. A save is
  staged into a temp directory, check_schema is pointed at the staging copy,
  and its four classes are parsed back out. RANGE and INVARIANT block the save.
  If check_schema could not run at all, the save is also blocked: an
  instrument's silence is not evidence (AGENTS.md section 3).
"""

import argparse
import csv
import errno
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# FROZEN OR NOT. PyInstaller one-file unpacks the read-only payload into a
# temp directory it names sys._MEIPASS and deletes on exit. The spec bundles
# gui/, schema/, scripts/ and docs/ under it with the repo's own shape, so
# every path below derives from REPO exactly as it does from a checkout and
# nothing downstream has to ask which case it is in.
#
# settings.json is the exception, because it is WRITTEN: _MEIPASS is gone the
# moment the exe exits, so frozen it lives beside the exe under a name that
# says what it belongs to, since that directory is the game root.
FROZEN = bool(getattr(sys, 'frozen', False))

if FROZEN:
    REPO = (getattr(sys, '_MEIPASS', None)
            or os.path.dirname(os.path.abspath(sys.executable)))
    GUI_DIR = os.path.join(REPO, 'gui')
    _EXE = os.path.abspath(sys.executable)
    EXE_DIR = os.path.dirname(_EXE)
    SETTINGS_PATH = os.path.join(
        EXE_DIR,
        os.path.splitext(os.path.basename(_EXE))[0] + '.settings.json')
else:
    GUI_DIR = os.path.dirname(os.path.abspath(__file__))
    REPO = os.path.dirname(GUI_DIR)
    EXE_DIR = None
    SETTINGS_PATH = os.path.join(GUI_DIR, 'settings.json')

SCHEMA_DIR = os.path.join(REPO, 'schema')
SCRIPTS_DIR = os.path.join(REPO, 'scripts')
DOCS_DIR = os.path.join(REPO, 'docs')
APP_HTML = os.path.join(GUI_DIR, 'app.html')

DEFAULT_GAME_DIR = r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint'

# The file that identifies a game folder. release/README.txt's install step is
# "extract everything into the folder holding CyberKnights.exe", so after an
# install the editor sits beside it.
GAME_MARKER = 'CyberKnights.exe'

MERGED_CONFIG = 'ckf.hardmode.json'


def default_game_dir():
    """Where to look for the game when nothing has been chosen yet.

    DEFAULT_GAME_DIR is a hardcoded path and is right for exactly one install:
    a default Steam library on C:. A second library, another drive or a
    non-Steam copy all miss it, and the editor then opens pointed at a folder
    that is not there.

    Frozen, the exe's own directory is a better answer and the install
    procedure is what makes it one -- the zip is extracted into the folder
    holding CyberKnights.exe, so the exe lands in the game root. That is
    asserted rather than assumed: the marker has to be beside the exe, so an
    exe run out of a downloads folder falls back instead of naming it as the
    game. Unfrozen there is no exe to reason from and the hardcoded path is all
    there is.

    CORRECTION, 2026-09-13. split-config-into-toggleable-slices tasks.md Phase 1
    says of this: "`serve.py:110` sets `DEFAULT_GAME_DIR` to [the Steam path]
    unconditionally and `load_settings` uses it when there is no
    `settings.json`. Frozen, the exe sits in the game root, so
    `os.path.dirname(sys.executable)` is the right answer. One line." The first
    sentence is stale and the one-line change is already made: `load_settings`
    calls THIS function, not `DEFAULT_GAME_DIR`, and this function returns
    EXE_DIR when the exe is in a game folder. What the checkbox was still owed
    is the frozen end-to-end case, which selftest section 16 now carries.

    The marker test is kept rather than dropped for `os.path.dirname(
    sys.executable)` bare: an exe run from a downloads folder would otherwise
    name that folder as the game directory, and the case
    "an exe with no CyberKnights.exe beside it does not name its own folder"
    in section 18 is what holds it.
    """
    if EXE_DIR and os.path.exists(os.path.join(EXE_DIR, GAME_MARKER)):
        return EXE_DIR
    return DEFAULT_GAME_DIR


def _read_section(config_dir, unit):
    """One unit's own object, read off disk."""
    js = check_schema.load_jsonc(os.path.join(config_dir, unit_file(unit)))
    sec = unit_section(unit)
    return js.get(sec, {}) if sec else js
TMP_SUFFIX = '.gui-new'
JOURNAL_NAME = '.ckf-gui-save-journal.json'
PROBE_PREFIX = '.ckf-gui-writeprobe-'

# The one key name this server knows by heart. No schema field marks a
# subsystem as the master gate, but Plugin.cs:133-137 returns out of Load()
# before any subsystem is initialised when this key is false, so the subsystem
# index would lie without it. Stated once, here; app.html contains no field
# names at all.
MASTER_KEY = 'General.Enabled'

# ---------------------------------------------------------------------------
# PRESENTATION TABLES. gui-plan.md 5.4: the page renders from the schema and
# app.html names nothing. These four tables are the declared exceptions --
# presentation decisions that no schema key expresses, written down once, here,
# with the reason, rather than scattered through the page. None of them changes
# what is read or written: every one is display only, and the save path is
# computed from the data in every case.
#
# Nothing else in this file names a subsystem, a field or a column.

# ONE LEVEL OF NAV GROUPING. design.md section 12 of
# split-config-into-toggleable-slices. Five groups, each holding sections; a
# section is one subsystem, or several presented together. No nesting below a
# group.
#
# WHAT THIS USED TO BE. Until 2026-09-13 this table was a MERGE table and
# nothing else:
#
#     # Two subsystems, presented as one section. They go on writing two files
#     # and two cfg keys and their schemas are untouched; only the page groups
#     # them, because they are the two halves of one question -- what a mission
#     # pays. David, 2026-09-01.
#     SECTION_GROUPS = [
#         {'id': 'mission-pay',
#          'title': 'What a Mission Pays',
#          'subsystems': ['Progression', 'RewardCurve']},
#     ]
#
# That entry is not deleted -- it is the `mission-pay` child of `systems`
# below, with the same id, the same title and the same two subsystems, so the
# merge behaviour and its selftest are unchanged. What generalised is the
# table around it: a child may now be a bare subsystem name as well as a merge,
# and every child sits under a named group.
#
# A CHILD IS EITHER:
#   'SubsystemName'                          a section of one
#   {'id','title','subsystems':[...]}        several subsystems, one section
#
# A child naming only subsystems that do not exist yet is ABSENT, not an error:
# Phases 4-8 of this change add those schemas. `nav_groups_for` reports every
# absent child by name, and a group whose children are all absent renders as
# its header plus `note` -- never as an empty shell with nothing said about it.
#
# THE MASTER SWITCH IS DELIBERATELY NOT NAMED HERE, the same way it is not
# named in SECTION_LAST: the section that goes first is by definition the one
# whose enable gate IS MASTER_KEY, and `sections_for` derives it. It therefore
# lands in `ungrouped` and is pinned above every group.
SECTION_GROUPS = [
    # design.md section 12: "Cyberware sits under Player Gear, not Talent
    # Balance. Its 11 slot tables describe items a player buys and installs,
    # which is the same kind of decision as buying a weapon or carrying a
    # grenade."
    {'id': 'player-gear', 'title': 'Player Gear', 'sections': [
        # "Weapons is one section holding three tables ... because all three
        # tune player weapons, and a player asking 'why does my gun feel
        # different' should find one place rather than three. Each table keeps
        # its own file and its own toggle." (design.md section 12)
        {'id': 'weapons', 'title': 'Player Weapons',
         'subsystems': ['GearClasses', 'CyberweaponsLasers', 'CyberweaponsClaws']},
        {'id': 'consumables', 'title': 'Consumables',
         'subsystems': ['ConsumablesChems', 'ConsumablesDevices',
                        'ConsumablesGrenades', 'ConsumablesMatrix',
                        'ConsumablesMedical', 'ConsumablesSploitkits']},
        {'id': 'cyberware', 'title': 'Cyberware',
         'subsystems': ['ImplantsGlobal',
                        'ImplantsSlot01', 'ImplantsSlot02', 'ImplantsSlot03',
                        'ImplantsSlot04', 'ImplantsSlot05', 'ImplantsSlot06',
                        'ImplantsSlot07', 'ImplantsSlot08', 'ImplantsSlot09',
                        'ImplantsSlot10', 'ImplantsSlot11']},
    ]},
    # One section per class. "A talent pack describes what a level-up grants,
    # which is not [the same kind of decision as buying a weapon]."
    {'id': 'talent-balance', 'title': 'Talent Balance', 'sections': [
        'TalentsSoldier', 'TalentsWarMachine', 'TalentsSniper',
        'TalentsSawbones', 'TalentsVanguard', 'TalentsHacker',
        'TalentsGunslinger', 'TalentsAEX', 'TalentsCyberKnight',
        'TalentsCS', 'TalentsWraith',
    ]},
    {'id': 'game-constants', 'title': 'Game Constants', 'sections': [
        'RuleModel',
    ]},
    # The nine subsystems that existed before this change, as eight sections:
    # Progression and RewardCurve are the merge above. SelfCheck is declared
    # last here and SECTION_LAST pins it last overall; the two agree, and
    # SECTION_LAST is what decides.
    {'id': 'systems', 'title': 'Systems', 'sections': [
        'Difficulty', 'Elapse', 'Fatigue', 'MissionRewards', 'PowerLevel',
        'ModelRules',
        {'id': 'mission-pay', 'title': 'What a Mission Pays',
         'subsystems': ['Progression', 'RewardCurve']},
        'SelfCheck',
    ]},
    # No children, by design rather than by accident: enemy weapons, armour and
    # monster rows are not edited in this tool. The note is here rather than in
    # app.html because it names files, and app.html names none.
    {'id': 'enemy-gear', 'title': 'Enemy Gear', 'sections': [],
     'note': 'Enemy weapons, armour and monster rows are not edited here. They '
             'are overlay CSVs in BepInEx/config/ckf.hardmode.d/, generated by '
             'scripts/make_enemy_overlays.py, and this editor does not open '
             'them.'},
]

# Sections pinned to the end. SelfCheck is a verification tool, off by default
# and deliberately so (selfcheck.schema.json's own prose), so it is the last
# thing on the page rather than the fifth. It is named here because no schema
# key says "this one is a diagnostic". The other pin -- the master switch at
# the very top -- is NOT named: it is derived from MASTER_KEY above, since the
# section that goes first is by definition the one whose enable gate IS the
# master gate. David, 2026-09-01.
SECTION_LAST = ['SelfCheck']

# A presentation-only window on a matrix axis: coordinates outside it are not
# drawn. The Team PL matrix runs MissionPowerLevel -10..10 because the game's
# own table does, and 63 cells of which 33 are unexplained negative-level rows
# and PL 0 (worth nothing, no class-0 band) make the 30 cells anyone edits hard
# to find. teampl.schema.json:table records that no negative level has ever
# been seen on an awarded row and that nothing in this repository explains
# them, so they are hidden rather than removed. David, 2026-09-01.
#
# HIDING IS NEVER DROPPING. A column outside the window that carries an
# override row is drawn anyway and called out, and the save is built from
# t.rows -- every row the file holds -- not from what is on screen. The
# selftest constructs an override outside the window and asserts it survives.
AXIS_WINDOWS = {
    ('Progression', 'MissionPowerLevel'): [1, 10],
}

# WHICH COLUMN A REFERENCE TABLE GROUPS BY. A fourth entry, and the same kind
# of decision as the three above: display only, read by nobody, written
# nowhere. rulemodel's `ruleReference` carries a GroupId per rule -- STORY 31,
# COMBAT 17, CHARACTER 15, HEAT 6, MAP 2, CONTACT 2, MATRIX 1, ECONOMY 1,
# SAFEHOUSE 1 = 76 [measured 2026-09-13 off the schema] -- and 76 constants in
# one flat list is the thing this grouping exists to avoid.
#
# It is here rather than inferred because inference would have to pick between
# GroupId and ConfigName by counting distinct values, and a tuning change that
# collapsed a group would move the grouping silently. It is here rather than in
# app.html because app.html names nothing. The selftest asserts the named
# column really is one the field declares, so a rename fails loudly instead of
# quietly ungrouping the page.
REFERENCE_GROUPING = {
    ('RuleModel', 'ruleReference'): 'GroupId',
}

# WHICH LEVER-SHEET COLUMNS ARE HIDDEN BY NAME. The seventh table in this
# family and the fifth literal one; the header block above says "four", which
# counts the literal tables it was written to describe (SECTION_GROUPS,
# SECTION_LAST, AXIS_WINDOWS, REFERENCE_GROUPING) and is still true of those.
# COST_LABELS and ROW_LABEL_SHEETS are derived, not literal, and a previous
# agent recorded the same thing rather than editing the count. THIS ONE IS
# LITERAL AND SITS HERE, after REFERENCE_GROUPING and before the import block.
# Nobody needs to recount.
#
# David, 2026-09-14, having opened the editor in a browser for the first time:
# "Suppress the ImplantLevel, Deactivated, Rarity, PowerLevel, and
# ImplactConflict columns." `ImplactConflict` is a typo for `ImplantConflictId`,
# which is the only header cell on any sheet in the live config matching
# "onflict" and appears on implants-slot02.csv and implants-slot04.csv only
# [measured 2026-09-14, every header row under ckf.hardmode.d].
#
# SCOPE IS EVERYWHERE THOSE NAMES APPEAR, not implants only -- asked and
# answered the same day. His reason: these are ITEM METADATA rather than combat
# levers, so the argument for hiding them on Quantum Rider is the same one on a
# grenade.
#
# HIDING IS NEVER DROPPING. Every column named here stays in the model, in the
# working copy and in the save, is named with its reason in the sheet's own
# notes, and comes back with one click. Same standard as AXIS_WINDOWS.
#
# THIS IS DECLARED, NOT DERIVED, and that distinction carries weight twice:
#
#   1. It is NOT the constancy suppression. That rule hides a column every row
#      agrees about and EXEMPTS a sheet of fewer than two rows, because
#      constant across one row is arithmetic rather than an observation. That
#      exemption is correct and unchanged. A column named here is hidden for a
#      reason that has nothing to do with what its cells hold, so it applies at
#      any row count, one row included.
#   2. The page must not be made to say "never changes" about a column hidden
#      for a different reason. The two travel as separate facts to the client
#      -- `constant` and `hidden` -- so the fold can give each its own sentence.
#
# BEFORE HIDING, WHAT IS BEING HIDDEN WAS COUNTED. Per column per sheet,
# non-blank cells, over the 53 declared sheets [measured 2026-09-14, live
# ckf.hardmode.d; re-derived by the selftest on every run, which prints this
# same table]:
#
#   ImplantLevel        11 sheets, 178 cells, 0 non-blank
#   Deactivated          7 sheets, 133 cells, 0 non-blank
#   ImplantConflictId    2 sheets,  49 cells, 0 non-blank
#   Rarity              17 sheets, 264 cells, 0 non-blank
#   PowerLevel          19 sheets, 283 cells, 0 non-blank
#
# Cells are counted over the rows the page DRAWS, after overlay_excluded, for
# the reason overlay_constant gives: a fact about a grid nobody sees describes
# nothing. That is one row's difference and it is in consumables-matrix.csv,
# which withholds one of its 11 rows -- so the same count taken off the raw
# file gives 265 and 284 rather than 264 and 283. The withheld row's Rarity and
# PowerLevel cells are blank too, so the non-blank total is 0 either way.
#
# Not one override is being hidden. `PowerLevel` and `Rarity` are the two that
# could have bitten -- they are real levers on sheets where somebody might have
# set one -- and both are blank everywhere the editor opens.
#
# THE TWO SHEETS THAT DO CARRY A VALUE ARE NOT THESE SHEETS. ArmorModel.csv
# (180 rows) and WeaponModel.csv (385 rows) carry a non-blank PowerLevel on
# every row. They are the enemy-gear tables, no schema declares them, and this
# editor never opens them: check_schema reports them as "unclaimed by design"
# alongside MonsterTypeModel.csv. read_overlay is only ever called for a path
# some schema's targets.overlays names, so this table cannot reach them --
# asserted below rather than assumed. Their 565 filled cells are the whole of
# the difference between 849 PowerLevel cells on disk and the 284 above.
HIDDEN_COLUMNS = {
    'ImplantLevel': 'item metadata, not a combat lever',
    'Deactivated': 'item metadata, not a combat lever',
    'Rarity': 'item metadata, not a combat lever',
    'PowerLevel': 'item metadata, not a combat lever',
    'ImplantConflictId': 'item metadata, not a combat lever',
}

for _p in (SCHEMA_DIR, SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import check_schema          # noqa: E402  schema/check_schema.py
import gen_teampl_labels     # noqa: E402  scripts/gen_teampl_labels.py


# ---------------------------------------------------------------------------
# bytes and newlines

def read_bytes(path):
    with open(path, 'rb') as f:
        return f.read()


def newline_of_bytes(raw, default='\n'):
    return '\r\n' if b'\r\n' in raw else default


def has_bom(raw):
    return raw[:3] == b'\xef\xbb\xbf'


def split_lines_keepends(text):
    """-> ([line without its ending], [that line's own ending])

    Splits on line boundaries, not on one separator sniffed from the whole
    file. A file that mixes CRLF and LF -- which is what any tool that rewrites
    a single line of a CRLF file with '\\n' produces, and AGENTS.md section 6
    has agents editing ckf.hardmode.cfg that way -- indexes one line per
    physical line, and each line keeps the ending it arrived with.

    Both lists are the same length, and the last entry's ending is always ''.
    A file that ends with a newline therefore comes back with a final empty
    line carrying no ending, which is the same shape ``text.split(nl)`` gave:
    ``'a\\r\\n'`` -> ``['a', '']``. ``''.join(l + e for l, e in zip(...))`` is
    the exact inverse, so an unedited file round-trips byte for byte however
    its endings are mixed.
    """
    lines, ends = [], []
    i, n = 0, len(text)
    while True:
        j = i
        while j < n and text[j] not in '\r\n':
            j += 1
        if j >= n:
            lines.append(text[i:])
            ends.append('')
            return lines, ends
        end = '\r\n' if text[j] == '\r' and text[j + 1:j + 2] == '\n' else text[j]
        lines.append(text[i:j])
        ends.append(end)
        i = j + len(end)


# ---------------------------------------------------------------------------
# The mission slot adjustment grammar.
#
# A transcription of MissionRewards.cs:391-414 (Adjust.Parse). Not a
# reimplementation of anything in this repo -- the only other copy is C#, and
# app.html carries a JavaScript twin so the browser can mark a cell as it is
# typed. Both are tested against the same case table in --selftest.
#
#   ""      none                    "=40"   set
#   "40"    set (bare number)       "+25"   add
#   "-25"   add, sign kept          "x1.5" / "X1.5" / "*1.5"   multiply
#
# The body is parsed with NumberStyles.Float and InvariantCulture: a leading
# sign, a decimal point and an exponent are all allowed, a thousands separator
# is not. An unparseable spec is logged and ignored by the plugin, which is a
# silent no-op -- so the GUI refuses to save one.

_NUMBER_RE = re.compile(r'^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$')


def parse_adjust(spec):
    """-> {'kind': 'none'|'set'|'add'|'multiply', 'value': float|None, 'ok': bool}"""
    s = (spec if spec is not None else '').strip()
    if s == '':
        return {'kind': 'none', 'value': None, 'ok': True}
    kind, body = 'set', s
    c = s[0]
    if c == '=':
        kind, body = 'set', s[1:]
    elif c in ('x', 'X', '*'):
        kind, body = 'multiply', s[1:]
    elif c == '+':
        kind, body = 'add', s[1:]
    elif c == '-':
        kind, body = 'add', s          # the sign stays on the body
    body = body.strip()
    if not _NUMBER_RE.match(body):
        return {'kind': 'none', 'value': None, 'ok': False}
    try:
        return {'kind': kind, 'value': float(body), 'ok': True}
    except ValueError:
        return {'kind': 'none', 'value': None, 'ok': False}


# ---------------------------------------------------------------------------
# ckf.hardmode.cfg — a value line replaced in place, or a key appended under
# its section, or a section created. Never rewritten wholesale, never
# commented.
#
# PROVENANCE OF THE CODE BELOW: IT IS A REWRITE, NOT A RESTORE. Read this
# before treating the append path as previously exercised behaviour.
#
# split-config-into-toggleable-slices tasks.md, Phase 1, asked for the
# opposite in as many words:
#
#   "Reinstate the CfgFile write path from the commit that deleted it. ...
#    Restore from the commit, do not rewrite -- the behaviour that ships
#    should be the behaviour that was already exercised. Find the commit with
#    `git log -S"_default_end" -- gui/serve.py`."
#
# That instruction cannot be carried out in this repository, so it was not.
# `git log -S"_default_end" -- gui/serve.py` returns nothing, and
# `git log --oneline -- gui/serve.py` returns exactly one commit, 14279fe
# "Initial public repo: CKF Hard Mode source, docs, release pipeline"
# [measured, 2026-09-13]. The deletion happened in the private tree that
# predates the public repo, so there is no commit to restore from. The code
# is not recorded anywhere else either: openspec/changes/
# consolidate-config-and-ship/handoff.md and that change's tasks.md both
# describe what was cut and quote none of it [measured, grep for
# `_default_end`, `insert_lines`, `delete_line`, `SaveRefused` across both].
#
# CONSEQUENCE, stated so it is not mistaken later. The behaviour below is
# pinned by the four scenarios under "Line-by-line `.cfg` editing in the GUI"
# in openspec/changes/split-config-into-toggleable-slices/specs/
# config-surface/spec.md, and by nothing else. It is NOT the behaviour that
# 3.0 exercised. Where the record named a mechanic without quoting it --
# where in a section an appended key lands, what ending a line that never had
# one gets, whether a `#` anywhere in a value is refused or only one in the
# first column -- the choice was made here and is marked `CHOICE:` at the
# member that makes it. Each of those is a place where this code may differ
# from what was deleted, and no amount of reading this repository can tell us
# whether it does.
#
# design.md section 3, "This reverses a deliberate deletion", is settled and
# is not reopened here: the toggles move to the .cfg, so every one of these
# mechanics has a caller again.
#
# ---------------------------------------------------------------------------
# LINE ENDINGS: WHAT IS OBSERVED, AND WHAT IS NOT.  (cited from here as
# "the line-endings note")
#
# Three observations of ckf.hardmode.cfg, each measured, none explained:
#
#   2026-09-03  consolidate-config-and-ship hand-wrote the file as CRLF.
#   2026-09-13  before a game launch: 162 bytes, 8 LF, 0 CRLF, 1 key.
#   2026-09-13  after a game launch:  3,238 bytes, 179 CRLF, 0 LF, 43 keys.
#
# What changed it between the first observation and the second is NOT
# established. Nothing here guesses at it.
#
# CORRECTION, 2026-09-13, after the launch. This file asserted in five places
# that BepInEx writes the .cfg with LF:
#
#   "BepInEx owns ckf.hardmode.cfg and writes it with LF"   (_cfg_line_shape)
#   "what it writes is LF"                                  (selftest [8])
#   "the endings are whatever BepInEx wrote, which today is LF on every .cfg
#    in the live config dir"                                (_default_end)
#
# and two shorter restatements. All five are wrong and are corrected in place.
# The third observation falsifies them: BepInEx wrote 179 CRLF and not one LF.
#
# HOW THE MISTAKE WAS MADE, because it is the reusable part. The 162-byte
# measurement was real and is still true of that moment. What was added to it
# was a causal claim -- that the LF came FROM BepInEx -- from a single sample
# of a file BepInEx had last written at an unknown earlier time. No run of
# this repository had ever watched BepInEx write that file. That is
# AGENTS.md section 1 exactly: an observation, and an explanation attached to
# it that nobody had measured. The tag on it should have stopped at the byte
# count.
#
# ckf.datadump.cfg after the same launch is MIXED: 24,988 bytes, 317 CRLF and
# 3 lone LF, the three sitting inside one multi-line comment block
# [measured, 2026-09-13]. A mixed .cfg is not hypothetical.
#
# NOTHING IN THE WRITER DEPENDS ON THE ANSWER, which is why the correction is
# prose only. Endings are read and written per line, an edited line keeps the
# ending it had, and an added line takes _default_end from the file it is
# joining. That behaved correctly when the file was LF and behaves correctly
# now that it is CRLF -- the post-launch CRLF file is what selftest [8b]
# scenario 4 now runs against.

class CfgFile:
    """Line-preserving reader for a BepInEx .cfg, plus one write.

    Every line the caller does not change comes back byte for byte. A value is
    only rewritten when its rendered form differs from what is on disk, so a
    save with no edits is a no-op even for keys whose value would format
    differently (3 vs 3.0).

    3.0 CUT THIS DOWN, AND split-config-into-toggleable-slices PUTS IT BACK.
    21 of the 22 keys had moved into ckf.hardmode.json, leaving [General]
    Enabled, a bool on a key BepInEx binds on every launch and therefore
    always writes; so `set_value` replaced a value line and did nothing else,
    and a key the file did not carry was refused rather than created.

    One key per slice puts a caller back on all of it. `set_value` now has
    four outcomes -- 'unchanged', 'replaced', 'appended', 'section-created' --
    and the two round-trip refusals the append path needs are back with it
    (a value starting with `#`; a value carrying a line break).

    The append path here is a REWRITE. The header comment above this class
    says why it could not be the restore that tasks.md asked for, and lists
    the choices it had to make that the record did not fix.

    Line endings are per line, not per file. `self.lines` holds line contents
    with no ending and `self.ends` holds each line's own ending, so a file that
    mixes CRLF and LF -- one LF-only line in a CRLF file is enough -- still
    indexes one line per physical line. Splitting on a single sniffed separator
    merged such lines into one string, which lost a key or swallowed a
    `[Section]` header and filed every key beneath it under the section before
    it; the write then landed in the wrong block. An edited line keeps the
    ending it had, and a line this class ADDS gets `_default_end`.
    """

    KEY_RE = re.compile(r'^([A-Za-z]\w*) = ?(.*)$')

    def __init__(self, raw):
        self.bom = has_bom(raw)
        self.newline = newline_of_bytes(raw)
        text = raw.decode('utf-8-sig')
        self.lines, self.ends = split_lines_keepends(text)
        self._index()

    @classmethod
    def load(cls, path):
        return cls(read_bytes(path))

    def _index(self):
        self.keys = {}        # 'Section.Key' -> line index
        self.sections = {}    # 'Section' -> header line index
        section = None
        for i, line in enumerate(self.lines):
            s = line.strip()
            if s.startswith('[') and s.endswith(']'):
                section = s[1:-1]
                self.sections.setdefault(section, i)
                continue
            m = self.KEY_RE.match(line)
            if m and section:
                self.keys['%s.%s' % (section, m.group(1))] = i

    def raw_value(self, dotted):
        i = self.keys.get(dotted)
        if i is None:
            return None
        return self.KEY_RE.match(self.lines[i]).group(2)

    def all_keys(self):
        return dict((k, self.raw_value(k)) for k in self.keys)

    # -- the write path. Rewritten, not restored; see the header comment.

    def _default_end(self, at=None):
        """The ending a line this class ADDS gets. -> '\\n' | '\\r\\n'

        A line already in the file keeps its own ending. A line being added has
        none to keep, so one has to be chosen, and spec.md's fourth scenario
        rules out choosing it by assumption.

        CORRECTION, 2026-09-13. This paragraph read "the endings are whatever
        BepInEx wrote, which today is LF on every .cfg in the live config dir
        [measured: ckf.hardmode.cfg 162 bytes / 8 LF / 0 CRLF, ckf.datadump.cfg
        448 bytes / 23 LF / 0 CRLF]". The byte counts were right for that
        morning; "which BepInEx wrote" was an inference, and a launch that
        afternoon rewrote ckf.hardmode.cfg as 3,238 bytes with 179 CRLF and no
        LF. See the line-endings note above this class. The first sentence is
        the part that survives, and it is the part this function needs: the
        endings are whatever is in the file, and this reads them off it.

        CHOICE: search UPWARD from the insertion point for the nearest real
        ending, then anywhere in the file, and only then fall back to
        `self.newline`. The upward search is what makes a mixed-ending file
        give a new line the ending of the region it joins rather than the
        ending of whichever line happens to sit last. The record named
        `_default_end` and did not say what it computed, so this may not be
        what 3.0 did.

        `self.newline` is reached only by a file with no line ending at all --
        a single line and no trailing newline -- and it is itself a whole-file
        sniff, which is why it is last and not first.
        """
        head = self.ends if at is None else self.ends[:at]
        for e in reversed(head):
            if e:
                return e
        for e in self.ends:
            if e:
                return e
        return self.newline

    def insert_lines(self, at, lines, ends=None):
        """Splice lines in at index `at`, then reindex. -> the number added.

        `ends` defaults to `_default_end(at)` for every added line.

        The line ABOVE the insertion point is given an ending if it has none.
        Without that, appending to a file whose last line has no trailing
        newline concatenates the two: 'Enabled = true' + 'Foo = false' on one
        line, which is a silent wrong write rather than an error. The last
        entry of `self.ends` is always '' by split_lines_keepends' contract, so
        this case is reached by every append at end of file, not just by an
        unterminated one.
        """
        if not (0 <= at <= len(self.lines)):
            raise ValueError('insert_lines: index %r outside 0..%d' % (at, len(self.lines)))
        lines = list(lines)
        ends = [self._default_end(at)] * len(lines) if ends is None else list(ends)
        if len(ends) != len(lines):
            raise ValueError('insert_lines: %d lines but %d endings'
                             % (len(lines), len(ends)))
        if at > 0 and self.ends[at - 1] == '':
            self.ends[at - 1] = self._default_end(at)
        self.lines[at:at] = lines
        self.ends[at:at] = ends
        self._index()
        return len(lines)

    def _last_content_line(self, start, stop):
        """The index of the last line in [start, stop) that is not blank, or
        start - 1 when they all are."""
        last = start - 1
        for i in range(start, stop):
            if self.lines[i].strip():
                last = i
        return last

    def _section_end(self, section):
        """Where a new key for `section` goes. -> a line index.

        CHOICE: after the section's last non-blank line, which is after its
        last key and before the blank line BepInEx leaves above the next
        header. The alternatives were directly under the header, which puts a
        new key above the comment block of the first existing one, and
        directly before the next header, which puts it below the separating
        blank and makes it read as belonging to nothing. The record did not say
        which 3.0 used.

        Blank-line handling matters at end of file too: split_lines_keepends
        always returns a final entry with an empty ending, so a file ending in
        a newline has a trailing '' line that must not be inserted after.
        """
        start = self.sections[section]
        stop = start + 1
        while stop < len(self.lines):
            s = self.lines[stop].strip()
            if s.startswith('[') and s.endswith(']'):
                break
            stop += 1
        # An empty section gives an empty range, which reports start and so
        # places the key directly under its header.
        return self._last_content_line(start + 1, stop) + 1

    def _file_end(self):
        """Where a new section goes: after the file's last non-blank line."""
        return self._last_content_line(0, len(self.lines)) + 1

    def _refuse_round_trip(self, dotted, rendered):
        """The two values that would not survive being written and read back.

        Both raise SaveRefused rather than asserting, so `python -O` -- which
        strips asserts -- cannot turn either into a silent bad write. That
        property is what `_refuses_under_O` in the selftest exists to check;
        an assert here would leave it checking nothing.
        """
        if '\n' in rendered or '\r' in rendered:
            raise SaveRefused({
                'summary': '%s: a .cfg value cannot carry a line break' % dotted,
                'detail': 'Every value in a BepInEx .cfg sits on one line '
                          '(docs/gotchas.md, "Every .cfg value must sit on one line"). '
                          'Written as given, the tail would read back as a separate '
                          'line and the key would lose everything after the break. '
                          'Nothing was written.'})
        # CHOICE: lstrip() first, so ' #off' is refused as well as '#off'. The
        # record says the refusal is for "a value starting with `#`"; a value
        # whose first non-blank character is `#` is the same hazard and the
        # narrower test would let it through. This may be wider than 3.0's.
        if rendered.lstrip().startswith('#'):
            raise SaveRefused({
                'summary': '%s: a .cfg value cannot start with #' % dotted,
                'detail': 'A `#` opens a comment in a BepInEx .cfg, so this value would '
                          'not read back as the value that was written. Nothing was '
                          'written.'})

    def set_value(self, dotted, rendered):
        """Write one key. -> 'unchanged' | 'replaced' | 'appended' | 'section-created'.

        Replacement is unchanged from what ships: the value line is rewritten
        in place, keeping its own line ending, and an identical value is a
        no-op so that a save with no edits writes nothing.

        A key the file does not carry is now APPENDED rather than refused --
        under its section header if the section exists, in a section this
        creates if it does not. What changed is not the file format but which
        keys exist: 43 schemas declare a .cfg key and ckf.hardmode.cfg carries
        one of them [measured, 2026-09-13 morning: 162 bytes holding [General]
        Enabled and no [Slices] section at all], because the other 42 only
        reach the file when BepInEx next writes it.

        UPDATE, 2026-09-13 afternoon: the game has since been launched and the
        file now carries all 43 [measured: 3,238 bytes, [General] and
        [Slices]]. That does not retire the append path -- it is the state a
        fresh install, a deleted .cfg or a newly added slice is in, and it is
        what the editor meets before the first launch after any build that
        adds a slice. Refusing was right while the file held every key the
        plugin bound. It is wrong now, and
        `docs/gotchas.md` says why in one line: "Deleting a key while its bind
        still exists brings it back at the code default." Slices.Init binds all
        43, so a toggle this editor declines to write is not left undecided --
        the next launch writes it at the code default, which for every slice is
        true. Declining to append would silently turn a slice the player
        switched off back on.

        Appending is safe in the other direction too: BepInEx preserves a key
        it did not bind (same section of gotchas.md), so a key appended here
        for a slice a later build drops is orphaned, not destroyed.
        """
        if '.' not in dotted:
            raise SaveRefused({
                'summary': 'cfg key %r has no section' % dotted,
                'detail': 'A .cfg key is written as Section.Key. Nothing was written.'})
        self._refuse_round_trip(dotted, rendered)
        section, key = dotted.split('.', 1)
        i = self.keys.get(dotted)
        if i is not None:
            if self.KEY_RE.match(self.lines[i]).group(2) == rendered:
                return 'unchanged'
            self.lines[i] = '%s = %s' % (key, rendered)
            return 'replaced'
        line = '%s = %s' % (key, rendered)
        if section in self.sections:
            self.insert_lines(self._section_end(section), [line])
            return 'appended'
        at = self._file_end()
        # A blank line above the new header, unless the line above is already
        # blank or there is no line above. No comment is written: spec.md's
        # first scenario says so, and BepInEx writes its own comment block for
        # the key on the next launch anyway.
        lead = [''] if at > 0 else []
        self.insert_lines(at, lead + ['[%s]' % section, line])
        return 'section-created'

    # NOT REINSTATED: delete_line.
    #
    # tasks.md lists it beside insert_lines and _default_end as part of what
    # Phase 3 cut. It is deliberately left out. No scenario under
    # "Line-by-line `.cfg` editing in the GUI" removes a key, no caller in this
    # file wants one, and gotchas.md records that deleting a key whose bind
    # still exists brings it back at the code default -- so a delete here would
    # be undone by the next launch while looking like it had worked. Bringing
    # it back with no caller would also be code no case exercises.
    #
    # This is the one item on that checkbox's list not implemented. Flagged for
    # David rather than quietly dropped: if the GUI is meant to be able to
    # remove a key from ckf.hardmode.cfg, say what the removal is supposed to
    # mean given that the plugin will write it back, and it can be added.

    def to_bytes(self):
        text = ''.join(l + e for l, e in zip(self.lines, self.ends))
        data = text.encode('utf-8')
        return (b'\xef\xbb\xbf' + data) if self.bom else data


def render_cfg_value(typ, value):
    """A typed value -> the string that goes on the right of the '='."""
    if typ == 'bool':
        return 'true' if value else 'false'
    if typ == 'int':
        return str(int(value))
    if typ in ('float', 'floatOrNaN'):
        if isinstance(value, str):
            value = float(value)
        if value != value:
            return 'NaN'
        f = float(value)
        if f == int(f) and abs(f) < 1e15:
            return str(int(f))
        return repr(f)
    if typ == 'stringList':
        if isinstance(value, str):
            items = [p.strip() for p in value.split(',')]
        else:
            items = [str(p).strip() for p in value]
        items = [p for p in items if p != '']
        return ', '.join(items)
    return '' if value is None else str(value)


def parse_cfg_value(typ, raw):
    """The on-disk string -> a typed value for the browser. -> (value, ok)"""
    if typ == 'stringList':
        return [p.strip() for p in raw.split(',') if p.strip() != ''], True
    v, ok = check_schema.coerce(raw, typ)
    if typ in ('float', 'floatOrNaN') and ok and isinstance(v, float) and v != v:
        return 'NaN', True
    return v, ok


# ---------------------------------------------------------------------------
# sidecar helpers

def dig(obj, dotted):
    return check_schema.dig(obj, dotted)


def put(obj, dotted, value, present):
    """Set or remove a dotted path. Absent means absent: the key is popped, and
    a container that had to be invented for a value that is not present is not
    invented at all."""
    parts = dotted.split('.')
    if not present:
        node = obj
        for p in parts[:-1]:
            if not isinstance(node, dict) or p not in node:
                return
            node = node[p]
        if isinstance(node, dict):
            node.pop(parts[-1], None)
        return
    node = obj
    for p in parts[:-1]:
        nxt = node.get(p)
        if not isinstance(nxt, dict):
            nxt = {}
            node[p] = nxt
        node = nxt
    node[parts[-1]] = value


def numeric_equal(a, b):
    """True when two JSON scalars mean the same thing. Used to keep an unedited
    value in its on-disk representation, so 1.0 does not become 1 on the way
    through a browser that has one number type."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return float(a) == float(b)
    return a == b


# ---------------------------------------------------------------------------
# schemas

def load_schemas():
    out = []
    for fn in sorted(os.listdir(SCHEMA_DIR)):
        if fn.endswith('.schema.json'):
            sch = check_schema.load_jsonc(os.path.join(SCHEMA_DIR, fn))
            sch['_file'] = fn
            out.append(sch)
    if not out:
        raise RuntimeError('no *.schema.json in %s' % SCHEMA_DIR)
    return out


# ---------------------------------------------------------------------------
# UNITS
#
# One physical JSON file can hold several subsystems, each under its own
# top-level "section". Everything below the I/O boundary still thinks in terms
# of one subsystem's own object, exactly as it did when each had a file to
# itself -- so a UNIT is the pair, written "file#section", and it is what keys
# doc.sidecars, json_fields and the edit payload. Only read_document and
# render_file_bytes know that several units share a file.
#
# A schema with a "json" target and no "section" is still legal and its unit is
# just the filename.

def sidecar_unit(sch):
    t = sch.get('targets') or {}
    j = t.get('json')
    if not j:
        return None
    sec = t.get('section')
    return '%s#%s' % (j, sec) if sec else j


def unit_file(unit):
    return unit.split('#', 1)[0]


def unit_section(unit):
    parts = unit.split('#', 1)
    return parts[1] if len(parts) > 1 else None


def sidecar_names(schemas):
    """The units, in schema order."""
    names = []
    for sch in schemas:
        u = sidecar_unit(sch)
        if u and u not in names:
            names.append(u)
    return names


def sidecar_files(schemas):
    """-> {physical file: [units]}, in schema order."""
    out = {}
    for u in sidecar_names(schemas):
        out.setdefault(unit_file(u), []).append(u)
    return out


# ---------------------------------------------------------------------------
# overlays: the bulk authoring format, as the editor READS it
#
# The dialect is Overlays.cs's, and this reader follows LoadTable and
# ParseHeader rather than a summary of them:
#
#   separator     '\t' for .tsv, ',' otherwise
#   skipped       a BOM on the first line, a blank line, a line whose trimmed
#                 start is '#', and a row whose every cell is blank (a spacer)
#   header        the first line that survives those skips
#   operator      lives in the HEADER, not the cell: Column, Column*, Column+,
#                 Column>, Column<  ->  set, multiply, add, clampMin, clampMax
#   control       a column whose name starts with '_' -- _clone, _comment,
#                 _serveOn -- lowercased, and carrying no operator
#   key column    the first column, which must not be a control. Overlays.cs
#                 ignores the whole file otherwise, and warns rather than
#                 applying an operator to it, "which is meaningless -- it
#                 selects the row"
#   blank cell    leave that column alone
#
# THE EDITOR DOES NOT WRITE THESE FILES. scripts/rules_to_overlays.py is the
# only thing that may, so every overlay reaches the page read-only and no save
# path touches one. That is asserted, not merely intended: an overlay path may
# never appear in a save's `proposed`.

OVERLAY_OPS = {'*': 'multiply', '+': 'add', '>': 'clampMin', '<': 'clampMax'}


def overlay_paths(sch):
    """The relative CSV/TSV paths a schema declares. -> [rel]

    `targets.overlays` is a LIST, which is what made it the first target value
    that is not a string; see hardcoded_names_in_app_html for what that broke.
    """
    t = (sch.get('targets') or {}).get('overlays') or []
    return list(t) if isinstance(t, list) else [t]


def overlay_paths_all(schemas):
    """Every declared overlay path, in schema order, without duplicates."""
    out = []
    for sch in schemas:
        for rel in overlay_paths(sch):
            if rel not in out:
                out.append(rel)
    return out


def overlay_table_name(rel):
    """The game table a file targets: the basename up to its first dot, with
    'Model' appended when it is not already there. Overlays.ModelFor."""
    base = os.path.basename(rel).split('.')[0]
    return base if base.endswith('Model') else base + 'Model'


def parse_overlay_header(cell):
    """One header cell -> {'name', 'op', 'control'}. Overlays.ParseHeader."""
    s = (cell or '').strip()
    if not s:
        return {'name': '', 'op': 'set', 'control': True}
    if s[0] == '_':
        return {'name': s.lower(), 'op': 'set', 'control': True}
    op = OVERLAY_OPS.get(s[-1])
    if op:
        return {'name': s[:-1].strip(), 'op': op, 'control': False}
    return {'name': s, 'op': 'set', 'control': False}


# ROWS THAT ARE ON DISK AND ARE NOT DRAWN, AND WHICH PRODUCT THAT IS.
#
# A row hidden in the editor but still writable on disk, and a row that is in
# neither, are DIFFERENT PRODUCTS. This is the first: the row stays in the CSV,
# scripts/consumables.py keeps writing it, the plugin keeps expanding it, and
# only this editor declines to draw an override line for it. The exclusion is
# implemented HERE and nowhere else -- consumables.py's own ROW_NOTES[5403]
# says the row "is excluded from the GUI. It is still in this file, because the
# file is the table and a row missing from it would be a row nothing can
# account for", which is prose, not a switch. So the switch is this map, and
# `entry['excluded']` carries what was withheld rather than dropping it in
# silence: a grid that is quietly one row short looks exactly like a grid whose
# reader broke.
#
# KEYED BY (file, id column, id value), never by row number: row numbers move
# when the dump moves, and an exclusion that silently slid onto the next row
# would hide a row nobody decided to hide.
#
# WHAT IS NOT CLAIMED. Nothing here has read what ItemDesc "for loading" means
# to the game. The reason recorded is design.md section 8's decision as
# consumables.py states it, not a mechanic anyone has read [unverified as a
# mechanic; the decision itself is quoted].
# ---------------------------------------------------------------------------
# WRITING ONE CELL OF A SHEET WITHOUT REWRITING THE LINE IT IS IN.
#
# read_overlay THROWS AWAY everything a writer would need to put a file back:
# it strips every cell, drops the quoting, drops each line's own ending, drops
# the blank and `#` lines it counts into `skipped`, and keeps no note of
# whether the file ended with a newline. A writer that rebuilt a line out of
# `entry['rows']` would therefore DELETE all of that -- silently, and only on
# the rows it touched, which is the worst shape for it.
#
# So nothing is rebuilt. The original bytes are kept (Document.overlay_raw),
# the line the edited row came from is found by its index, and exactly one
# field's CHARACTER SPAN inside that line is replaced. Every other byte of the
# file -- the header, the other fields of the same row, the `_comment` prose
# the "ships 130" hint is parsed out of, the quoting, the column order, the
# per-line endings, the blank lines, the trailing newline -- is carried through
# untouched because it is never re-rendered.
#
# MEASURED, 2026-09-14, over all 57 .csv in the live ckf.hardmode.d: zero `#`
# comment lines, zero blank lines, zero CRLF, zero BOM, and every file ends in
# one LF. The brief for this change described the `Shipped:` prose as living in
# "per-row `#` comments"; it does not -- it is the last FIELD of each data row,
# in the `_comment` control column, and it is quoted on the sheets whose prose
# carries a comma (RuleModel.csv). The span writer preserves both cases without
# knowing which it is looking at, and the blank/`#`/CRLF handling below is kept
# for the day one appears rather than because one does today.

def csv_field_spans(line, sep=','):
    """-> [(start, end)] per field of one CSV line, or None if it does not parse.

    The span INCLUDES the quotes of a quoted field, so line[start:end] is the
    field exactly as it was written. Deliberately NOT built on csv.reader: the
    stdlib gives values and no offsets, and a writer that re-rendered from the
    values would be the thing this exists to avoid. The selftest cross-checks
    every span against csv.reader on every line of every shipped sheet -- two
    independent readers, which is the only way this one being wrong shows up.

    None means "this line is not something to edit in place": an unterminated
    quote, or a quoted field with text after its closing quote. Refusing is the
    point; guessing a span would move the wrong bytes.
    """
    if line is None:
        return None
    spans = []
    i, n = 0, len(line)
    start = 0
    while True:
        if i < n and line[i] == '"':
            j = i + 1
            while True:
                if j >= n:
                    return None                 # unterminated quote
                if line[j] == '"':
                    if j + 1 < n and line[j + 1] == '"':
                        j += 2
                        continue
                    break
                j += 1
            j += 1                              # past the closing quote
            if j < n and line[j] != sep:
                return None                     # junk after a quoted field
            i = j
        else:
            while i < n and line[i] != sep:
                i += 1
        spans.append((start, i))
        if i >= n:
            return spans
        i += 1                                  # past the separator
        start = i


def csv_render_cell(value, sep=','):
    """One cell's text -> the bytes to put in its span.

    A blank writes a blank -- not `0`, not `""`. "Leave the game's column
    alone" is what an empty field means to Overlays.LoadTable (`if (v.Length
    == 0) continue;` -- Overlays.cs, the value loop), and an empty QUOTED field
    would read the same to the parser while looking, in the file, like someone
    had decided something. Quoting is added only where the grammar forces it.
    """
    s = '' if value is None else str(value)
    if s == '':
        return ''
    if sep in s or '"' in s:
        return '"' + s.replace('"', '""') + '"'
    return s


GUI_EXCLUDED_ROWS = {
    ('consumables-matrix.csv', 'ItemTypeId', '5403'): (
        'Striatum Catalyst NMF',
        'design.md section 8: this row\'s ItemDesc is "for loading", so the '
        'editor draws no override line for it. It is STILL IN THE FILE on '
        'disk, and still expanded by the plugin — hidden here, not removed '
        'there.'),
}


def overlay_excluded(rel, names, rows):
    """Split off the rows this editor declines to draw.

    -> (kept, [{'row', 'column', 'id', 'name', 'why'}])

    Never guesses: a file with no entry in GUI_EXCLUDED_ROWS, or one whose id
    column is not in this header, keeps every row it has. The withheld rows are
    RETURNED, not discarded, so the count is reportable and the selftest can
    assert which product this is.
    """
    base = os.path.basename(rel)
    want = dict((k[1:], v) for k, v in GUI_EXCLUDED_ROWS.items() if k[0] == base)
    if not want:
        return rows, []
    kept, gone = [], []
    for ri, r in enumerate(rows):
        hit = None
        for (col, val), (nm, why) in sorted(want.items()):
            if col in names and (r['cells'][names.index(col)] or '').strip() == val:
                hit = {'row': ri, 'column': col, 'id': val, 'name': nm, 'why': why}
                break
        (gone if hit else kept).append(hit or r)
    return kept, gone


def read_overlay(path, rel):
    """One overlay file -> the entry the page renders from.

    Never raises: an unreadable or headerless file comes back with `error` set
    and `present` saying whether it was there at all, because "not there" and
    "could not read" are different facts and a grid drawn from an empty rows
    list looks identical to both.

    A THIN WRAPPER FOR ONE REASON. _read_overlay_entry returns early from five
    places -- not on disk, OSError, not UTF-8, no id column, no header row --
    and a `writable` graded only on the path that reaches the bottom left the
    error entries carrying the placeholder 'not read', which says nothing
    about why and would have to be interpreted rather than read. Grading here
    means every entry the page or the save path ever sees has been graded,
    whichever way it came out.
    """
    entry = _read_overlay_entry(path, rel)
    entry['writable'], entry['writableWhy'] = overlay_writable(entry)
    return entry


def _read_overlay_entry(path, rel):
    """read_overlay's body. Call read_overlay, not this."""
    entry = {'path': rel, 'table': overlay_table_name(rel), 'present': False,
             'error': None, 'columns': [], 'keyColumn': None, 'rows': [],
             'skipped': 0, 'kind': None, 'kindSource': None,
             # `form` WAS HERE, and was `kind == 'expanded' and one row`. See
             # the correction at the assignment site below: David overruled the
             # one-row form on 2026-09-14 and the key is gone rather than left
             # always-false for a future reader to think is live.
             'fileOrder': False, 'roles': [], 'adjustCells': [],
             'shared': {}, 'sharedSource': SHEET_SOURCE_ERROR, 'labels': {},
             # What this sheet's KEY CELLS are called, id -> name, from
             # ROW_LABEL_SHEETS. {} on every sheet that has no name map and on
             # every entry that never reaches the labelling below, so the key
             # is always present and an absent map is an empty one.
             'rowLabels': {},
             'expanderMarks': [], 'sharedBlind': None, 'shipped': {},
             'shippedMissing': 0, 'notes': [], 'excluded': [],
             # THE WRITE SIDE (2026-09-14). `editable` is the server's grading
             # and the client does not repeat it; `identityColumns` is how a
             # cell edit names its row; `sep`, `lineCount` and each row's
             # `line` are what lets one field be replaced in place without the
             # file being rebuilt. `writable` is false, with `writableWhy`
             # saying which of the several reasons it is, whenever an edit to
             # this sheet would be a guess.
             # `hidden` is the DECLARED half of suppression, per column: a
             # reason string, or None where the column is drawn. Always
             # present, [] on an entry that never reaches the grading, so the
             # client never has to tell "no hidden columns" from "no such key".
             'editable': [], 'constant': [], 'hidden': [],
             'identityColumns': [],
             'sep': ',', 'lineCount': 0,
             'writable': False,
             'writableWhy': 'not read'}
    if not os.path.exists(path):
        entry['error'] = 'not on disk'
        return entry
    entry['present'] = True
    try:
        raw = read_bytes(path)
    except OSError as e:
        entry['error'] = '%s: %s' % (type(e).__name__, e)
        return entry
    try:
        text = raw.decode('utf-8-sig')
    except ValueError as e:
        entry['error'] = 'not UTF-8: %s' % e
        return entry
    sep = '\t' if rel.lower().endswith('.tsv') else ','
    entry['sep'] = sep
    _src_lines = text.splitlines()
    entry['lineCount'] = len(_src_lines)
    header = None
    for _li, line in enumerate(_src_lines):
        if not line.strip() or line.lstrip().startswith('#'):
            entry['skipped'] += 1
            continue
        cells = next(csv.reader([line], delimiter=sep))
        if all(not (c or '').strip() for c in cells):
            entry['skipped'] += 1              # a spacer names no row
            continue
        if header is None:
            header = [parse_overlay_header(c) for c in cells]
            entry['columns'] = header
            if header and not header[0]['control']:
                entry['keyColumn'] = header[0]['name']
            else:
                entry['error'] = ('the first column is not an id column, so '
                                  'the plugin ignores this file')
                return entry
            continue
        # `line` is the row's index in THIS file's own line list, which is
        # what the writer replaces a span inside. It is not a row ordinal and
        # not an address: the address is the identity tuple below, and the
        # writer re-derives `line` from the bytes it is about to edit rather
        # than trusting this copy.
        entry['rows'].append({'cells': [(c or '').strip() for c in cells],
                              'line': _li})
    if header is None:
        entry['error'] = 'no header row'
        return entry
    # Withheld BEFORE anything is computed from the rows, so that every count
    # below -- the form discriminator, the shipped map, the shared marks, the
    # legend -- describes the grid the page actually draws. `excluded` keeps
    # what was withheld, so "not drawn" never has to be inferred from a total.
    entry['rows'], entry['excluded'] = overlay_excluded(
        rel, [c['name'] for c in header], entry['rows'])
    entry['kind'] = overlay_kind(entry)
    entry['kindSource'] = overlay_kind_source(entry)
    entry['roles'] = overlay_roles(entry)
    # CORRECTION, 2026-09-14. THE ONE-ROW FORM IS GONE. This line was:
    #
    #     # design.md section 7: slot 11 renders as a form, not a grid. THE ROW
    #     # COUNT IS THE DISCRIMINATOR AND IT IS IN THE FILE -- an editor that
    #     # has read the sheet in order to draw it has already counted -- so
    #     # nothing declares it and no schema field carries it.
    #     entry['form'] = entry['kind'] == 'expanded' and len(entry['rows']) == 1
    #
    # and app.html branched on it into a stack of labelled values instead of a
    # grid, with the matching reason: "a header row above a single line is a
    # table of one, which is a worse way to read four values."
    #
    # DAVID OVERRULED THAT ON 2026-09-14, having opened the editor in a browser
    # for the first time and looked at the page it produced. He wants slot 11
    # drawn as a table like every other implant slot. The reasoning above is
    # kept rather than deleted because it was not wrong about anything it
    # measured -- the row count IS in the file, and nothing did declare the
    # shape -- it was wrong about which of two readable layouts a reader who
    # has eleven slot tables in front of him would rather have for the twelfth.
    # That is not a thing a measurement decides.
    #
    # FIXED SERVER-SIDE, NOT CLIENT-SIDE. Dropping the branch in app.html would
    # have left this key computed, published and asserted over with no subject
    # -- dead payload that reads as live. So the key is gone, the branch is
    # gone, and the form path has no remaining subject anywhere: `overlayBlock`
    # draws one grid for every sheet at every row count. The other `form` in
    # this file is unrelated and stays -- a schema FIELD's `ui: 'form'`, which
    # is how a scalar is drawn, and is why implants-global.json's three numbers
    # are a form and not a table.
    #
    # An expanded sheet's rows are in FILE ORDER and must stay there. In slots
    # 3 and 7 ImplantLevel is not a tier index -- all six class-16 rows in slot
    # 3 are level 1 and all five class-41 rows in slot 7 are level 1 -- so a
    # grid that sorted by it would silently reorder tiers no column orders.
    entry['fileOrder'] = entry['kind'] == 'expanded'
    entry['adjustCells'] = ['%d,%d' % rc for rc in overlay_adjust_cells(entry)]
    entry['shared'] = overlay_shared_marks(entry)
    entry['sharedSource'] = SHEET_SOURCE_ERROR
    entry['labels'] = overlay_labels(entry)
    entry['rowLabels'] = ROW_LABEL_SHEETS.get(os.path.basename(rel), {})
    entry['expanderMarks'], entry['sharedBlind'] = expander_shared_marks(entry)
    shipped, missing = overlay_shipped(entry)
    entry['shipped'] = dict((str(k), v) for k, v in shipped.items())
    entry['shippedMissing'] = missing
    entry['notes'] = overlay_notes(entry)
    entry['editable'] = overlay_editable(entry)
    entry['constant'] = overlay_constant(entry)
    entry['hidden'] = overlay_hidden(entry)
    entry['identityColumns'] = overlay_identity_columns(entry)
    for _r in entry['rows']:
        _r['key'] = overlay_row_key(entry, _r)
    return entry


def read_overlays(config_dir, schemas):
    """-> {rel: entry} for every declared overlay, in schema order."""
    out = {}
    for rel in overlay_paths_all(schemas):
        out[rel] = read_overlay(os.path.join(config_dir, rel), rel)
    return out


# ---------------------------------------------------------------------------
# TWO KINDS OF SHEET LIVE IN targets.overlays, AND THEY ARE NOT THE SAME THING.
#
#   direct    Overlays.LoadTable reads it. The filename carries the game table
#             before its first dot, the first column IS that table's id column,
#             and the operator lives in the header (Column*, Column+, ...).
#             33 of them [measured 2026-09-13].
#   expanded  A slice's own expander reads it -- GearClasses.cs, Cyberweapons.cs
#             -- and turns one row into several rules. Its filename carries no
#             game table, its first column need not be an id at all
#             (cyberweapons-lasers.csv leads with WeaponName), and its cells
#             carry the operator instead of the header (=90, *1.25). 3 of them.
#
# `targets.overlays` deliberately does not say which: nothing in check_schema.py
# infers a dialect from it, and existence and claiming are all it asserts. So
# the kind is DERIVED here, from the only property that separates them without
# naming a file: a direct overlay's filename table, with Model swapped for Id,
# is its own first column. That splits the 36 exactly 33/3 [measured].
#
# THIS MATTERS BECAUSE AN ASSERTION WAS SILENTLY MIS-DESCRIBING THEM. Phase 4's
# case read
#
#     'every overlay has an id column as its first column, which is what
#      Overlays.LoadTable requires before it will read a line'
#     all(v['keyColumn'] for v in ov_read.values())
#
# whose test is only that the first column has a name that is not a control
# column. WeaponName passes it. So the case went green over three sheets that
# have no id column, are not read by Overlays.LoadTable at all, and to which
# the sentence in its own name does not apply [measured, Phase 6]. The name
# claimed more than the test did, which is the shape AGENTS.md section 3 is
# about, and it was in a case written to guard exactly that.


def overlay_kind_derived(entry):
    """'direct' or 'expanded', inferred from the file's own two declarations."""
    tbl = entry.get('table') or ''
    want = tbl[:-len('Model')] + 'Id' if tbl.endswith('Model') else None
    return 'direct' if want and want == entry.get('keyColumn') else 'expanded'


def overlay_kind(entry):
    """'direct' or 'expanded'. The expander's declaration wins; the inference
    covers a sheet whose expander declares no names, and the selftest asserts
    the two never disagree."""
    if os.path.basename(entry.get('path') or '') in DECLARED_EXPANDED:
        return 'expanded'
    return overlay_kind_derived(entry)


def _family_of(rel):
    """Which expander declares this sheet. -> str

    The families are the expanders' own name lists; a sheet no expander claims
    by name is reported as such rather than folded into one of them.
    """
    base = os.path.basename(rel)
    for mod, name in ((_cyberweapons if 'cyberweapons' in _sheet_sources else None,
                       'cyberweapons'),
                      (_implants if 'implants' in _sheet_sources else None,
                       'implants'),
                      (_gear_classes if 'gear_classes' in _sheet_sources else None,
                       'gear_classes'),
                      (_consumables if 'consumables' in _sheet_sources else None,
                       'consumables')):
        if mod is not None and base in (getattr(mod, 'SHEET_NAMES', ()) or ()):
            return name
    return 'declared by no expander'


def overlay_kind_source(entry):
    return ('declared'
            if os.path.basename(entry.get('path') or '') in DECLARED_EXPANDED
            else 'derived')


# The expander's own declarations, consumed rather than re-derived. An agent
# re-deriving the sharing counted (talent, column) pairs and reported nine
# shared rows where five were one talent whose SelfEffect and TargetEffect are
# the same id, which cannot diverge from itself. So the numbers come from the
# module that owns them.
#
# NEVER SILENT IF IT IS NOT THERE. A build without scripts/ on the path draws
# no shared-row marks at all, and a page that quietly stops marking a row two
# owners share is worse than one that says it cannot.
SHEET_IDENTITY, SHARED_ROWS, COLLISION_CASES = [], {}, []
SHEET_SOURCE_ERROR = None
_sheet_sources = []
try:
    import cyberweapons as _cyberweapons      # noqa: E402  scripts/cyberweapons.py
    SHEET_IDENTITY += list(_cyberweapons.IDENTITY)
    SHARED_ROWS.update(_cyberweapons.SHARED_ROWS)
    COLLISION_CASES += list(_cyberweapons.COLLISION_CASES)
    _sheet_sources.append('cyberweapons')
except Exception as _e:                        # pragma: no cover - reported
    SHEET_SOURCE_ERROR = '%s: %s' % (type(_e).__name__, _e)
try:
    # Each expander declares the identity of its own sheet. gear_classes names
    # one column; cyberweapons names three. Collecting them rather than
    # picking one is why a sheet added by a fourth expander does not silently
    # have its key column graded as an override.
    import gear_classes as _gear_classes      # noqa: E402  scripts/gear_classes.py
    SHEET_IDENTITY.append(_gear_classes.CLASS_COLUMN)
    _sheet_sources.append('gear_classes')
except Exception as _e:                        # pragma: no cover - reported
    SHEET_SOURCE_ERROR = ((SHEET_SOURCE_ERROR + '; ') if SHEET_SOURCE_ERROR
                          else '') + '%s: %s' % (type(_e).__name__, _e)
try:
    import implants as _implants              # noqa: E402  scripts/implants.py
    SHEET_IDENTITY += list(_implants.IMPLANT_IDENTITY) + list(_implants.EFFECT_IDENTITY)
    _sheet_sources.append('implants')
except Exception as _e:                        # pragma: no cover - reported
    _implants = None
    SHEET_SOURCE_ERROR = ((SHEET_SOURCE_ERROR + '; ') if SHEET_SOURCE_ERROR
                          else '') + '%s: %s' % (type(_e).__name__, _e)
try:
    # The fourth expander, Phase 8. It declares the same four names the other
    # three do between them -- SHEET_NAMES, IDENTITY, SHARED_ROWS,
    # COLLISION_CASES -- so it is consumed the same way and nothing here
    # re-derives any of them. Its SHARED_ROWS carry a `sheet` key, which is
    # what keeps its two rows from being looked for on a cyberweapon sheet.
    import consumables as _consumables        # noqa: E402  scripts/consumables.py
    SHEET_IDENTITY += list(_consumables.IDENTITY)
    SHARED_ROWS.update(_consumables.SHARED_ROWS)
    COLLISION_CASES += list(_consumables.COLLISION_CASES)
    _sheet_sources.append('consumables')
except Exception as _e:                        # pragma: no cover - reported
    _consumables = None
    SHEET_SOURCE_ERROR = ((SHEET_SOURCE_ERROR + '; ') if SHEET_SOURCE_ERROR
                          else '') + '%s: %s' % (type(_e).__name__, _e)
SHEET_IDENTITY = sorted(set(SHEET_IDENTITY))

# WHICH FILES ARE EXPANDED SHEETS, TAKEN FROM THE EXPANDERS THEMSELVES.
#
# CORRECTION TO PHASE 6. That phase derived the kind -- "a direct overlay's
# filename table with Model swapped for Id is its own first column" -- and the
# derivation is sound, but it is inference where a DECLARATION exists.
# implants.py says so itself, in the comment above its own SHEET_NAMES: a
# filename the validator does not recognise as a lever sheet "is parsed as a
# DIRECT OVERLAY, and the first thing that happens then is that the filename
# before the first dot becomes a model name ... That does not fail loudly. Its
# only symptom is an orphan warning long afterwards, which is why
# is_lever_sheet() is a list of the expanders' OWN declared names."
#
# So the declaration decides, and the derivation is kept as a CROSS-CHECK: the
# selftest asserts the two agree on every file, which is what catches an
# expander that ships a sheet and forgets to declare it. gear_classes declares
# no SHEET_NAMES today [measured], so its one sheet is still classified by
# derivation, and the census says which route each file took rather than
# leaving that invisible.
DECLARED_EXPANDED = set()
for _m in (_cyberweapons if 'cyberweapons' in _sheet_sources else None,
           _implants if 'implants' in _sheet_sources else None,
           _gear_classes if 'gear_classes' in _sheet_sources else None,
           _consumables if 'consumables' in _sheet_sources else None):
    if _m is not None:
        DECLARED_EXPANDED |= set(getattr(_m, 'SHEET_NAMES', ()) or ())


# What `Cost` means, per expander. design.md section 7: in the eleven slot
# tables it is the implant's clinic price; in the two cyberweapon sheets it is
# the weapon's valuation. Same column name, two quantities, both on screen at
# once. The label is chosen by WHICH EXPANDER DECLARES THE SHEET, so no file
# name appears here and app.html names nothing.
#
# PHASE 8: A THIRD QUANTITY, AND ITS SCOPE IS ALL SIX SHEETS, NOT ONE.
#
# On the consumable sheets `Cost` is the ItemModel shop price -- what the row's
# item is bought for, a number the player meets in a shop rather than at a
# clinic and which is not a valuation of anything they already own. The brief
# for this change described it as the price on `consumables-sploitkits.csv`;
# that sheet is simply the one where it is easiest to see, because Cost is one
# of only eight columns there. MEASURED against the six headers in
# CONTRACT-phase8.md: `Cost` is on medical, grenades, devices, chems,
# sploitkits AND matrix -- six of six. Labelling only sploitkits would have
# drawn one sheet's Cost as a shop price and five sheets' identical column as
# an unexplained `Cost`, which is the silent-mislabel shape this map exists to
# prevent. So the whole family is labelled, exactly as the other two are.
#
# WHAT THIS COMMENT DOES NOT CLAIM. Nothing here has read what the game does
# with ItemModel.Cost at runtime; the interop assembly is marshalling stubs.
# The quantity is named from the sheets' own `Shipped:` lines and from
# scripts/consumables.py's declaration that Cost is an ItemModel column
# [measured], not from a mechanic anyone here has read.
COST_LABELS = {}


def _declare_cost_labels():
    pairs = []
    if 'implants' in _sheet_sources:
        pairs.append((getattr(_implants, 'SHEET_NAMES', ()) or (),
                      'Install cost', 'the implant\'s price at the clinic'))
    if 'cyberweapons' in _sheet_sources:
        pairs.append((getattr(_cyberweapons, 'SHEET_NAMES', ()) or (),
                      'Item value', 'what the weapon is worth'))
    if 'consumables' in _sheet_sources:
        pairs.append((getattr(_consumables, 'SHEET_NAMES', ()) or (),
                      'Shop price',
                      'what the item is bought for (ItemModel.Cost)'))
    for names, label, why in pairs:
        for n in names:
            COST_LABELS[n] = (label, why)


_declare_cost_labels()


# WHAT A ROW'S KEY CELL IS CALLED, WHERE THE KEY IS AN ID AND THE NAME IS IN
# THE GAME'S OWN DATA.
#
# A presentation table, in the family declared at the top of this file. Like
# COST_LABELS above it is DERIVED rather than typed, so it adds no name to the
# four LITERAL tables that block counts, and app.html still names nothing.
#
# gear-classes.csv's first column is `WeaponClass` and its ten cells are the
# ids 1, 2, 3, 4, 5, 6, 10, 11, 12 and 14. Drawn bare they are ten numbers
# beside twenty-two levers, and nothing on the page says which row is the
# shotgun. The names are not a choice made here. They are MEASURED, TWICE,
# against the game's own tables:
#
#   sheets/raw/WeaponModel.csv carries a `WeaponClassName` column, and over all
#   535 rows each WeaponClass id has EXACTLY ONE distinct name -- 1 Melee,
#   2 Pistol, 3 `AR (Assault Rifle)`, 4 Shotgun, 5 E-Rifle, 6 Sniper Rifle,
#   10 SMG, 11 Revolver, 12 `UAR (Urban Assault Rifle)`, 14 Railgun
#   [measured 2026-09-14, re-derived off the dump for this table].
#
#   sheets/raw/WeaponClassModModel.csv carries the same ten ids under the
#   DESIGNER-SIDE spelling -- 3 `Assault Rifle`, 5 `Energy Rifle`,
#   12 `Bullpup Assault` -- so two independent tables agree on WHICH id is
#   which weapon and differ only in how it is written [measured 2026-09-14].
#
# WHY WeaponModel'S SPELLING AND NOT WeaponClassModModel'S. WeaponModel's is
# the string that has been through localisation; WeaponClassModModel's is the
# designer's label. The witness is in the six ids this sheet does NOT carry: in
# WeaponModel, classes 9, 17, 18 and 19 read `Gear.WeaponClass.DroneAR`,
# `Gear.WeaponClass.CyberWeaponEyes`, `Gear.WeaponClass.DroneSMG` and
# `Gear.WeaponClass.DroneERifle` -- raw localisation keys that did not resolve
# -- while all ten lever ids read as plain English [measured 2026-09-14]. So
# this is the column the game itself puts a player-readable string in. WHAT IS
# NOT CLAIMED: nobody here has read the UI code that draws it, and the
# interop assembly is marshalling stubs, so "the string the player sees" is
# an inference from the data and not something anyone has watched happen
# [unverified].
#
# THERE IS NO CONSTANT TABLE FOR THIS, AND THAT WAS CHECKED. The route the rest
# of the editor uses to put a name on an id is sheets/raw/_id_constants.csv.
# It declares 454 constants over 26 classes -- ModuleClassId, RewardTypes,
# EffectSpecialCode and twenty-three others -- and NOT ONE of them is
# WeaponClass [measured 2026-09-14]. That route is empty here, which is why the
# name has to come off the dump's own name column.
#
# DERIVED, NOT TYPED. Both the filename and the ten pairs come from
# scripts/gear_classes.py -- SHEET_NAME and LEVER_CLASSES -- the module that
# GENERATES the sheet and the same one this file already reads the sheet's
# identity column from. A class renamed or added there moves this table on the
# next run; a literal here would go stale in silence. The sheet's own
# `_comment` column carries the names too, in prose ("Melee. No mode 2: ..."),
# but reading a label out of a sentence is parsing, not consuming.
#
# EMPTY IS A VALUE, NOT AN ABSENCE. `rowLabels` is initialised to {} in
# _read_overlay_entry, so every overlay entry carries the key -- a sheet with
# no name map, an entry that errored before its labels were computed, and a
# build with scripts/ off the path (where 'gear_classes' is not in
# _sheet_sources and this table is empty) all send an EMPTY MAP rather than no
# key at all. The page can index it without first testing for it.
ROW_LABEL_SHEETS = {}
if 'gear_classes' in _sheet_sources:
    ROW_LABEL_SHEETS[_gear_classes.SHEET_NAME] = dict(
        (str(cls), name) for cls, name in _gear_classes.LEVER_CLASSES)


def overlay_labels(entry):
    """Column name -> the label to draw, where it differs from the name."""
    base = os.path.basename(entry.get('path') or '')
    out = {}
    lab = COST_LABELS.get(base)
    if lab and any(c['name'] == 'Cost' for c in (entry.get('columns') or [])):
        out['Cost'] = {'label': lab[0], 'why': lab[1]}
    return out


def expander_shared_marks(entry):
    """The shared-row marks a slice's own expander finds in this sheet.

    -> ([{kind, id, owners, note}], blind_note or None)

    CONSUMED, NOT RE-DERIVED: implants.expand is called with the sheet's own
    header and rows and asked for its marks, the same call the plugin's
    expansion makes.

    WHAT IT CANNOT SEE, SAID OUT LOUD. `expand` takes the owners that have no
    table as an argument, and those come from the dump. Nothing at runtime may
    depend on a dump being present, and no sheet carries them -- measured: the
    slot 1 sheet mentions no drone module anywhere. So an INFORMATIONAL mark
    for a row whose other owners have no table cannot be produced here at all,
    and this returns a note saying that rather than a shorter list of marks
    that looks complete.
    """
    if _implants is None or not entry.get('rows'):
        return [], None
    base = os.path.basename(entry.get('path') or '')
    if base not in (getattr(_implants, 'SHEET_NAMES', ()) or ()):
        return [], None
    header = [c['name'] for c in (entry.get('columns') or [])]
    rows = [list(r['cells']) for r in entry['rows']]
    marks = []
    try:
        _implants.expand(header, rows, base, [], marks, {})
    except Exception as e:                     # pragma: no cover - reported
        return [], ('The expander could not read this sheet (%s: %s), so no '
                    'shared row is marked below. That is this saying it could '
                    'not look, not a sheet with nothing shared in it.'
                    % (type(e).__name__, e))
    out = [{'kind': m[0], 'id': m[1], 'owners': list(m[2]), 'note': m[4]}
           for m in marks]
    blind = ('A shared row whose other owners have no table of their own '
             'cannot be seen from the config directory: the expander takes '
             'those owners as an input and they come from a table dump, which '
             'nothing here reads and a player does not have. Such a row would '
             'carry an informational marker and block nothing; none is drawn '
             'below, and that is a limit of what is readable rather than a '
             'count of zero.')
    return out, blind


def overlay_roles(entry):
    """Per column: 'identity', 'control' or 'lever'. -> [role]

    An IDENTITY column names the rows a line expands into; it is not an
    override and a value in it is not an edit. A LEVER column is an override,
    and a blank one means "ship as-is". Telling them apart is what stops 32
    filled identity cells reading as 32 overrides on a sheet whose whole point
    is that it overrides nothing.
    """
    ident = set(SHEET_IDENTITY)
    out = []
    for i, c in enumerate(entry.get('columns') or []):
        if c['control']:
            out.append('control')
        elif c['name'] in ident or (i == 0 and overlay_kind(entry) == 'direct'):
            out.append('identity')
        else:
            out.append('lever')
    return out


def overlay_editable(entry):
    """Per column: may the editor write this cell? -> [bool]

    TRUE ONLY WHERE THE SERVER GRADED THE COLUMN `lever`, AND NEVER AT INDEX 0.

    David reversed the read-only rule on 2026-09-14 and scoped the reversal
    himself: lever and override columns only. The three classes that stay
    read-only are each read-only for a different reason, and none of them is
    "it would be awkward":

      identity  names the rows a line expands into. Changing one does not
                change what the row does, it changes WHICH row the line is
                about -- for the eleven implant sheets and the two cyberweapon
                sheets that is the join the expander makes against the game
                table, and a typo there silently produces a rule that matches
                nothing. overlay_roles already tells them apart, from the
                expanders' own declared IDENTITY lists.
      control   `_comment`, `_clone` and anything else whose header starts
                with `_`. `_comment` is the prose `_SHIPPED_RE` parses the
                "ships 130" hint out of; `_clone` is Overlays.cs's row-clone
                source id. Neither is an override.
      index 0   the key column. On a direct overlay it is the game table's own
                id and Overlays.LoadTable refuses the line without it
                (`long.TryParse(idText, ...)`); on an expanded sheet it is the
                first identity column. Held out explicitly as well as by role,
                so a sheet whose first column ever grades `lever` still cannot
                have its key rewritten.

    THE CLIENT DOES NOT DECIDE THIS. app.html names no column and no file -- a
    selftest enforces that -- so the affordance has to arrive as data.
    """
    roles = entry.get('roles') or []
    return [bool(r == 'lever' and i != 0) for i, r in enumerate(roles)]


def overlay_constant(entry):
    """Per column: None if it varies, else {'value': text, 'rows': n}.

    David asked for columns that never change within a table to be suppressed.
    This is the FACT, not the affordance: the page decides what to do with a
    column every row agrees about, and a column that is blank on every row
    reports value '' rather than being confused with one that is absent.

    Computed over the rows the page DRAWS -- after overlay_excluded -- because
    a column that is constant across 18 drawn rows and differs only on the one
    withheld row would otherwise be described by a fact about a grid nobody
    sees.

    READ THIS BEFORE SUPPRESSING A COLUMN BECAUSE IT IS CONSTANT.
    A LEVER COLUMN THAT IS BLANK ON EVERY ROW IS CONSTANT, AND SUPPRESSING IT
    IS THE STATE DAVID COMPLAINED ABOUT.

    Measured 2026-09-14 over the 53 declared sheets: 563 editable columns, of
    which 169 vary, 3 are constant at a non-blank value, and 391 are constant
    ONLY BECAUSE EVERY CELL IN THEM IS BLANK. On 19 of the 53 sheets not one
    editable column varies. A blank override cell does not mean "this column
    has nothing to say" -- it means NO OVERRIDE IS SET, which is exactly the
    thing an editor exists to change, and `entry['shipped']` carries the game's
    own value for it so the blank can be drawn with "ships 130" beside it.

    The fact is reported as it was asked for and the affordance is still the
    client's: `value` is '' precisely when the column is blank everywhere, so a
    suppression rule can be written to exclude that case without a second
    source. Nothing here decides it, and the selftest counts the 391 so that
    the trap cannot become invisible.
    """
    cols = entry.get('columns') or []
    rows = entry.get('rows') or []
    out = []
    for ci in range(len(cols)):
        seen = set()
        for r in rows:
            seen.add(r['cells'][ci] if ci < len(r['cells']) else '')
            if len(seen) > 1:
                break
        out.append(None if len(seen) != 1
                   else {'value': next(iter(seen)), 'rows': len(rows)})
    return out


def overlay_hidden(entry):
    """Per column: None, or the reason this column is hidden by name. -> [str|None]

    THE DECLARED HALF OF SUPPRESSION, and the counterpart to overlay_constant.
    overlay_constant reports a FACT ABOUT THE CELLS ("every row agrees, and the
    value is X"); this reports a DECISION ABOUT THE COLUMN, taken by David on
    2026-09-14 over the five names in HIDDEN_COLUMNS and independent of what
    any cell holds.

    The two are published separately rather than merged into one boolean
    because the page has to be able to say WHY each column is off the screen,
    and "this column never changes" is a false statement about a column that
    does change and was hidden for another reason. A reader who is told the
    wrong reason cannot tell that they were.

    NEVER INDEX 0. The key column is the row's name; hiding it leaves a grid of
    nothing. None of the five is a key column on any sheet in the live config,
    so the guard costs nothing today and is here for the sheet that ships
    tomorrow.

    ROW COUNT DOES NOT ENTER INTO IT. The constancy rule exempts a sheet of
    fewer than two rows because constant-across-one-row is arithmetic; a
    declared hide is not an observation about the data at all, so it applies at
    one row exactly as at twenty-seven.
    """
    cols = entry.get('columns') or []
    out = []
    for i, c in enumerate(cols):
        out.append(None if i == 0 else HIDDEN_COLUMNS.get(c['name']))
    return out


def overlay_identity_columns(entry):
    """The column names whose cells, together, address a row. -> [name]

    ROWS ARE ADDRESSED BY KEY, NOT BY ORDINAL, and the key is the whole
    identity tuple rather than the first column alone. Measured 2026-09-14 over
    the 53 declared sheets in the live config: the FIRST COLUMN alone is not
    unique on 9 of them -- cyberweapons-lasers.csv carries "Brightshot Optic"
    five times over 17 rows, implants-slot02.csv has 24 distinct names over 27
    rows -- while the identity tuple is unique on 53 of 53.

    An ordinal was rejected for the reason fingerprints already states about
    table rows: it is stable only until the file moves, and a file that gained
    a row between the read and the save would send the edit to its neighbour
    with nothing downstream noticing. The tuple either matches one row or the
    save refuses.
    """
    roles = entry.get('roles') or []
    cols = entry.get('columns') or []
    return [cols[i]['name'] for i, r in enumerate(roles) if r == 'identity']


def overlay_row_key(entry, row):
    """One row's address: its identity cells, in column order."""
    roles = entry.get('roles') or []
    return [(row['cells'][i] if i < len(row['cells']) else '')
            for i, r in enumerate(roles) if r == 'identity']


def overlay_writable(entry):
    """May the save path edit ANY cell of this sheet? -> (bool, why)

    AN INSTRUMENT THAT CANNOT SEE MUST NOT WRITE. overlay_roles grades identity
    from SHEET_IDENTITY, which is collected from the four expander modules at
    import. When one of those imports fails, SHEET_SOURCE_ERROR is set and
    SHEET_IDENTITY is SHORT -- and a column that is really an identity column
    then grades `lever` and would become editable. The same import feeds
    SHARED_ROWS, so the repoint marks go missing at the same moment.

    So the whole write path is refused for every sheet while that error is set,
    rather than writing against a grading that is quietly one expander short.
    That is the `ov.sharedSource` case the brief names, and it is handled by
    refusing rather than by trusting the marks.
    """
    if entry.get('error'):
        return False, 'the file did not read: %s' % entry['error']
    if SHEET_SOURCE_ERROR:
        return False, ('an expander did not import (%s), so identity columns '
                       'and shared-row marks are both graded from a short '
                       'list. No cell of any sheet is editable until that is '
                       'fixed -- a lever cell here could be an identity column '
                       'this run cannot see.' % SHEET_SOURCE_ERROR)
    if not entry.get('rows'):
        return False, 'the sheet has no rows to address'
    if not entry.get('identityColumns'):
        return False, ('no column of this sheet grades identity, so no row in '
                       'it can be addressed by key')
    if not any(entry.get('editable') or []):
        return False, 'no column of this sheet grades lever'
    return True, ''


def overlay_adjust_cells(entry):
    """Cells carrying an operator rather than a bare value. -> [(row, col)]

    A direct overlay puts the operator in the header and never here; an
    expanded sheet puts it in the cell. Measured per file rather than assumed
    from the kind, so a sheet that changes dialect is visible.
    """
    roles = overlay_roles(entry)
    out = []
    for ri, r in enumerate(entry.get('rows') or []):
        for ci, cell in enumerate(r['cells']):
            if ci >= len(roles) or roles[ci] != 'lever' or not cell:
                continue
            if cell.strip()[0] in '=+*xX':
                out.append((ri, ci))
    return out


def overlay_shared_marks(entry):
    """Cells whose value points at a row more than one owner points at.

    -> {'<row>,<col>': {'owners': [...], 'note': str, 'pointer': str,
                        'repoint': True}}

    NOTE WHAT THE CELL IS. Neither sheet carries an EffectModel column, so no
    edit here changes what the shared effect DOES -- these cells are REPOINTS,
    changing which effect row a talent uses. A repoint and an edit read
    identically in a grid, so the mark says which it is.
    """
    if not SHARED_ROWS:
        return {}
    roles = overlay_roles(entry)
    names = [c['name'] for c in (entry.get('columns') or [])]
    base = os.path.basename(entry.get('path') or '')
    out = {}
    for (model, rid), sr in SHARED_ROWS.items():
        if sr.get('sheet') and sr['sheet'] != base:
            continue
        _pm, pcol = sr.get('pointer') or (None, None)
        if pcol not in names:
            continue
        ci = names.index(pcol)
        if roles[ci] != 'lever':
            continue
        # THE SHARING IS NOT IN THE SHEET. Every SelfEffect cell on the laser
        # sheet is blank -- the sheet overrides none of them -- so a page
        # deriving the sharing from the file would find nothing at all
        # [measured 2026-09-13]. Which rows share is a fact about the SHIPPED
        # data, and SHARED_ROWS is where it is declared. A row is matched by
        # its identity cells against the declared owners, never by what its
        # pointer cell happens to contain.
        owners = [o for o in (sr.get('owners') or [])]
        ids = [i for i, r2 in enumerate(roles) if r2 == 'identity']
        for ri, r in enumerate(entry.get('rows') or []):
            have = set((r['cells'][i] or '').strip() for i in ids)
            mine = [o for o in owners
                    if all(str(part) in have for part in o[:2])]
            if not mine:
                continue
            other = [o for o in owners if o not in mine]
            out['%d,%d' % (ri, ci)] = {
                'owners': [list(o) for o in owners],
                'others': [list(o) for o in other],
                'note': sr.get('note') or '',
                'target': '%s %s' % (model, rid),
                'column': pcol,
                'repoint': True,
            }
    return out


_SHIPPED_RE = re.compile(r'Shipped:\s*(.*?)\.\s')
_SHIPPED_PAIR_RE = re.compile(r'^([A-Za-z][A-Za-z0-9]*)\s+(-?\d+(?:\.\d+)?)$')


def overlay_shipped(entry):
    """What the game ships for each lever cell, out of the row's own _comment.

    -> ({row index: {column: text}}, rows_without_one)

    The sheets state it themselves -- "Shipped: PowerLevel 2; Rarity 2; ..." --
    so the page can put the shipped value beside a blank override without a
    dump and without a second copy anywhere. Rows whose comment does not carry
    one are COUNTED and reported: a page that silently showed nothing for them
    would look exactly like a page whose parser had stopped working.
    """
    names = [c['name'] for c in (entry.get('columns') or [])]
    ci = names.index('_comment') if '_comment' in names else None
    out, missing = {}, 0
    if ci is None:
        return out, len(entry.get('rows') or [])
    for ri, r in enumerate(entry.get('rows') or []):
        m = _SHIPPED_RE.search((r['cells'][ci] or '') + ' ')
        if not m:
            missing += 1
            continue
        pairs = {}
        for part in m.group(1).split(';'):
            mm = _SHIPPED_PAIR_RE.match(part.strip())
            if mm:
                pairs[mm.group(1)] = mm.group(2)
        if pairs:
            out[ri] = pairs
        else:
            missing += 1
    return out, missing


def overlay_exclusive_pairs(entry):
    """Lever columns that are never both filled on the same row. -> [(a, b)]

    MEASURED, NEVER NAMED. Two columns qualify only if each is filled on at
    least one row and no row fills both: a pair where one is always blank is
    not an exclusion, it is an unused column, and reporting it as an exclusion
    would be a claim the data does not support.
    """
    roles = overlay_roles(entry)
    names = [c['name'] for c in (entry.get('columns') or [])]
    lev = [i for i, r in enumerate(roles) if r == 'lever']
    filled = {}
    for i in lev:
        filled[i] = set(ri for ri, r in enumerate(entry.get('rows') or [])
                        if (r['cells'][i] or '').strip())
    out = []
    for a in lev:
        for b in lev:
            if b <= a or not filled[a] or not filled[b]:
                continue
            if not (filled[a] & filled[b]):
                out.append((names[a], names[b]))
    return out


def _nonzero(text):
    try:
        return float(text or '0') != 0.0
    except ValueError:
        return False


def shipped_exclusive_pairs(entry, shipped):
    """Lever columns where every row ships exactly one of the two non-zero.

    Both halves are required -- never both, and never neither -- so a pair of
    columns that are simply unused together does not qualify. Measured over the
    rows that state a shipped value; with none, there is nothing to claim and
    this returns nothing rather than claiming it vacuously.
    """
    if not shipped:
        return []
    roles = overlay_roles(entry)
    names = [c['name'] for c in (entry.get('columns') or [])]
    lev = [names[i] for i, r in enumerate(roles) if r == 'lever']

    out = []
    for ai in range(len(lev)):
        for bi in range(ai + 1, len(lev)):
            a, b = lev[ai], lev[bi]
            rows = [p for p in shipped.values() if a in p and b in p]
            if len(rows) != len(shipped) or not rows:
                continue
            if all(_nonzero(p.get(a)) != _nonzero(p.get(b)) for p in rows):
                out.append((a, b))
    return out


def overlay_notes(entry):
    """The legend a sheet earns from its own contents. -> [str]

    Every line is computed from this file, so a sheet that changes says
    something different rather than carrying a sentence somebody typed once.
    """
    notes = []
    roles = overlay_roles(entry)
    names = [c['name'] for c in (entry.get('columns') or [])]
    rows = entry.get('rows') or []
    lev = [i for i, r in enumerate(roles) if r == 'lever']
    ident = [names[i] for i, r in enumerate(roles) if r == 'identity']
    filled = sum(1 for r in rows for i in lev if (r['cells'][i] or '').strip())
    if ident:
        notes.append(
            '%s %s. They are identity, not overrides: a value there is which '
            'row is being described, never a change to it.'
            % (', '.join(ident),
               'selects the row this line edits'
               if entry.get('kind') == 'direct'
               else 'name the rows each line expands into'))
    if entry.get('adjustCells'):
        notes.append(
            '%d cell(s) carry an operator — =N sets, +N adds, *N or xN '
            'multiplies, and a bare number sets. On these sheets the operator '
            'is in the CELL; on a direct overlay it is in the header instead.'
            % len(entry['adjustCells']))
    if rows and filled == 0:
        notes.append(
            'Every override cell on this sheet is blank, on all %d row(s). '
            'That is the sheet stating that these rows ship as they are — it '
            'is not an omission and nothing here is missing.' % len(rows))
    for a, b in overlay_exclusive_pairs(entry):
        notes.append(
            '%s and %s are never both set on one row — measured across all %d '
            'row(s) of this sheet. A blank in one is the expected value for a '
            'row that uses the other, not a gap.' % (a, b, len(rows)))
    shipped, missing = overlay_shipped(entry)
    # THE SAME EXCLUSION, ON THE SHIPPED VALUES. Two columns can be mutually
    # exclusive in what the GAME ships while this sheet overrides neither, and
    # then the pair above finds nothing because both override columns are
    # empty -- which is exactly the case on these sheets. That is the one a
    # reader needs: a blank is not an omission, it is the column this row's
    # family does not use.
    # ONE NOTE, NOT ONE PER PAIR. On a sheet whose rows fall into two families
    # every family-specific column alternates with every other one, so the
    # pairwise list is accurate and unreadable -- 5 near-identical lines on a
    # 17-row sheet [measured]. The columns are grouped by WHICH rows they are
    # non-zero on instead, which is the fact underneath all those pairs.
    fam = {}
    for a, b in shipped_exclusive_pairs(entry, shipped):
        fam.setdefault(a, set()).add(b)
        fam.setdefault(b, set()).add(a)
    if fam:
        groups = {}
        for col in fam:
            key = tuple(sorted(ri for ri, p in shipped.items()
                               if _nonzero(p.get(col))))
            groups.setdefault(key, []).append(col)
        if len(groups) == 2:
            halves = [sorted(v) for v in groups.values()]
            notes.append(
                'These rows fall into two families and the columns follow '
                'them: %s on one, %s on the other. Measured over all %d row(s) '
                'that state a shipped value — no row ships a non-zero value in '
                'both halves, and none ships zero in both. A zero is what the '
                'family that does not use that column ships, not a gap.'
                % (', '.join(halves[0]), ', '.join(halves[1]), len(shipped)))
        else:
            for a in sorted(fam):
                notes.append(
                    '%s is never non-zero on a row where %s is, over the %d '
                    'row(s) that state a shipped value.'
                    % (a, ', '.join(sorted(fam[a])), len(shipped)))
    zero = {}
    for ri, pairs in shipped.items():
        for i in lev:
            if not (rows[ri]['cells'][i] or '').strip() and pairs.get(names[i]) in ('0', '0.0'):
                zero.setdefault(names[i], 0)
                zero[names[i]] += 1
    if zero:
        notes.append(
            'A blank cell whose shipped value is 0 is shown as 0, not as '
            'unknown: %s. The game ships nothing there, so there is nothing '
            'for this sheet to leave alone.'
            % ', '.join('%s on %d row(s)' % kv for kv in sorted(zero.items())))
    if shipped:
        notes.append(
            'The shipped value beside each cell is read from that row\'s own '
            'comment, on %d of %d row(s)%s.'
            % (len(shipped), len(rows),
               '' if not missing else '; %d row(s) carry no parseable one and '
               'show a dash rather than a number' % missing))
    # WHAT IS NOT ON SCREEN, SAID ON SCREEN. A grid quietly one row short is
    # indistinguishable from a grid whose reader broke, so the withheld rows
    # are named here with the reason and with the fact that the file still
    # carries them.
    for ex in (entry.get('excluded') or []):
        notes.append(
            '%s (%s %s) is in this file on disk and is not drawn above. %s'
            % (ex['name'], ex['column'], ex['id'], ex['why']))
    return notes


def reference_fields(schemas):
    """-> {(subsystem, path): (schema, field)} for fields with `in: reference`.

    A reference field's rows live IN THE SCHEMA, not on disk: rulemodel's
    `ruleReference` carries all 76 rows with the GroupId each rule belongs to
    and the value the game ships. Nothing at runtime may depend on a dump being
    present, and GroupId could not go in the overlay header because it is a
    real game column -- a header naming it would be a `set` over all 76 rows.
    So it is neither a cfg field nor a json field, it is never sent in an edit
    set, and no save can write it.
    """
    out = {}
    for sch in schemas:
        for f in sch['fields']:
            if f['in'] == 'reference':
                out[(sch['subsystem'], f['path'])] = (sch, f)
    return out


def cfg_fields(schemas):
    out = {}
    for sch in schemas:
        for f in sch['fields']:
            if f['in'] == 'cfg':
                out[f['path']] = (sch, f)
    return out


def json_fields(schemas):
    """-> {(unit, path): (schema, field)}"""
    out = {}
    for sch in schemas:
        j = sidecar_unit(sch)
        if not j:
            continue
        for f in sch['fields']:
            if f['in'] == 'json':
                out[(j, f['path'])] = (sch, f)
    return out


# ---------------------------------------------------------------------------
# prose: what the page shows above the controls
#
# A schema's section text is an array of lines. A "" entry is a paragraph
# break; consecutive non-empty lines are ONE paragraph and are joined with a
# space. The page used to render one <div> per source line, which turned a
# hard-wrapped source array into a column of short lines with a blank between
# every one of them -- the airiness David asked to lose. Field help is a single
# string and is always one paragraph.
#
# uiDoc is the player-facing array. It is optional: a schema that has one is
# rendered from it, a schema that does not falls back to `doc`, so the page
# works either way.

# A source citation, parenthetical only: the WHOLE parenthetical has to be
# citations -- File.ext:NNN, optionally more line ranges after commas -- or it
# is left alone. "(RewardCurve.cs:249-251, and the C# initialiser is -1)"
# therefore survives untouched, which is the intended direction: a regex that
# eats half a sentence is worse than one that leaves a citation behind.
_CITE = (r'[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)*'
         r'\.(?:cs|json|md|py|csv|tsv)\s*:\s*\d+(?:\s*-\s*\d+)?')
_LINES = r'\d+(?:\s*-\s*\d+)?'
CITATION_RE = re.compile(r'\s*\(\s*%s(?:\s*,\s*(?:%s|%s))*\s*\)' % (_CITE, _CITE, _LINES))

# A trailing citation with no parentheses, at the very end of the string. No
# field doc carries one today; the pattern is here because a citation that ends
# a sentence is the other shape the convention takes, and anchoring it to the
# end is what keeps it from eating "Fatigue.cs:93-96 carries none of the ..."
# mid-sentence, where the citation IS the subject.
TRAILING_CITE_RE = re.compile(r'[\s,;:]*[-–—]?\s*%s(?:\s*,\s*%s)*\s*\.?\s*$'
                              % (_CITE, _LINES))

# An evidence tag, AGENTS.md section 4. Only the four declared words: the field
# docs also carry [PowerLevel], [RewardCurve], [Diagnostics] and
# [JsonPropertyName("missions")], which are a column, two cfg sections and a C#
# attribute, and none of them is a maintainer mark.
EVIDENCE_TAG_RE = re.compile(r'\s*\[(?:measured|fitted|closed|unverified)\b[^\]]*\]')


def strip_maintainer_marks(text):
    """Drop source citations and evidence tags from prose the player reads.

    docs/config-reference.md keeps rendering the unstripped `doc`; this is a
    render-time decision for the GUI only, and it touches no file.
    """
    if not text:
        return text
    out = EVIDENCE_TAG_RE.sub('', text)
    out = CITATION_RE.sub('', out)
    out = TRAILING_CITE_RE.sub('', out)
    # tidy what the removal left behind, and nothing else
    out = re.sub(r'[ \t]{2,}', ' ', out)
    # Close the gap a removal left in front of sentence punctuation -- and only
    # there. The punctuation has to END a word: "none appears in any .cs in
    # this tree" and "deserialised at :318" both keep their space, which an
    # unanchored \s+([.,;:]) rule silently ate.
    out = re.sub(r' +([.,;:!?])(?=\s|$)', r'\1', out)
    return out.strip()


def paragraphs(lines):
    """['a', 'b', '', 'c'] -> ['a b', 'c']. A "" is the only paragraph break."""
    out, cur = [], []
    for ln in (lines or []):
        s = str(ln).strip()
        if s == '':
            if cur:
                out.append(' '.join(cur))
                cur = []
        else:
            cur.append(s)
    if cur:
        out.append(' '.join(cur))
    cleaned = [strip_maintainer_marks(p) for p in out]
    return [p for p in cleaned if p]


def field_doc_text(doc):
    """Field help is one paragraph, whatever whitespace the source used."""
    if not doc:
        return ''
    return strip_maintainer_marks(' '.join(str(doc).split()))


def field_help(field):
    """The one paragraph of help a field shows, from `uiDoc` where it has one.

    Same split as a subsystem's: `doc` is the maintainer record and
    docs/config-reference.md renders it, `uiDoc` is that field written for
    someone playing the game. A field with no `uiDoc` shows its `doc` with the
    maintainer marks stripped, which is what every field did before the key
    existed.
    """
    return field_doc_text(field.get('uiDoc') or field.get('doc'))


def section_prose(sch):
    """-> (paragraphs, which array they came from)."""
    if sch.get('uiDoc'):
        return paragraphs(sch['uiDoc']), 'uiDoc'
    return paragraphs(sch.get('doc')), 'doc'


# ---------------------------------------------------------------------------
# presentation: order, grouping, the collapsed enable pair, axis windows

# REMOVED IN 3.0: enable_pair, and the one checkbox that stood for two gates.
#
# Elapse and Fatigue were gated twice -- a cfg key read before the sidecar was
# opened, and the sidecar's own "enabled" read after it loaded -- and the page
# collapsed the pair into one control so a player was not asked to hold a
# distinction that only existed because two files were read in a fixed order.
# Phase 3 deleted the outer gate: [Elapse] Enabled and [Fatigue] Enabled are
# gone from ckf.hardmode.cfg and the section's own "enabled" is the whole
# chain. No subsystem declares both halves any more, so the pair, its
# `displayGates`/`pairDisagrees` payload, `pairRow` in app.html and the
# 'mixed' state they existed to render have all gone with it.


def axis_windows_for(sch):
    """-> {axis column name: [lo, hi]} for this subsystem, from AXIS_WINDOWS."""
    out = {}
    for (sub, col), win in AXIS_WINDOWS.items():
        if sub == sch['subsystem']:
            out[col] = list(win)
    return out


def declared_children():
    """SECTION_GROUPS flattened -> [(group, child)] in declared order.

    Stated once so `sections_for` and `nav_groups_for` cannot disagree about
    what a group holds.
    """
    return [(g, child) for g in SECTION_GROUPS for child in g.get('sections', [])]


def child_id(child):
    """The id a declared child will carry if any of it is present."""
    return child if isinstance(child, str) else child['id']


def resolve_child(child, by_sub):
    """One declared child against the schemas that exist -> section, or None.

    None means ABSENT: every subsystem the child names is a schema Phases 4-8
    have not added yet. The caller reports that by name; nothing here treats it
    as an error and nothing drops it silently.

    A merge that resolves to a single present member is that member's own
    section, not a one-member group -- the rule the merge table has had since
    2026-09-01 ("a group of one is not a group"), kept.
    """
    members = [child] if isinstance(child, str) else list(child['subsystems'])
    members = [m for m in members if m in by_sub]
    if not members:
        return None
    if len(members) == 1:
        s = by_sub[members[0]]
        return {'id': members[0], 'title': s.get('title', members[0]),
                'subsystems': members}
    return {'id': child['id'], 'title': child['title'], 'subsystems': members}


def sections_for(schemas):
    """-> [{'id', 'title', 'subsystems': [...], 'group', 'groupTitle'}] in the
    order the page shows.

    SECTION_GROUPS order is the default. The master switch is first because it
    is the first thing anyone checks when the mod appears to do nothing; a
    group's children present in the order they are declared; SECTION_LAST goes
    last. Every subsystem appears exactly once -- the selftest asserts it.

    A subsystem no group names still gets a section, with `group` None. That is
    the case a new schema lands in, and it must show up rather than vanish:
    `nav_groups_for` returns it under `ungrouped` and the selftest names every
    one that is not the master switch.
    """
    by_sub = dict((s['subsystem'], s) for s in schemas)

    out, seen = [], set()
    for g, child in declared_children():
        sec = resolve_child(child, by_sub)
        if sec is None or any(m in seen for m in sec['subsystems']):
            continue
        seen.update(sec['subsystems'])
        out.append(dict(sec, group=g['id'], groupTitle=g['title']))
    for s in schemas:
        sub = s['subsystem']
        if sub in seen:
            continue
        seen.add(sub)
        out.append({'id': sub, 'title': s.get('title', sub), 'subsystems': [sub],
                    'group': None, 'groupTitle': None})

    def is_master(sec):
        return any((by_sub[m].get('enable') or {}).get('cfg') == MASTER_KEY
                   for m in sec['subsystems'])

    def is_last(sec):
        return any(m in SECTION_LAST for m in sec['subsystems'])

    first = [s for s in out if is_master(s)]
    last = [s for s in out if not is_master(s) and is_last(s)]
    mid = [s for s in out if not is_master(s) and not is_last(s)]
    return first + mid + last


def nav_groups_for(schemas, sections=None):
    """The nav's one level of grouping, as the page renders it.

    -> {'groups': [{'id', 'title', 'note', 'sections': [section id],
                    'absent': [child id]}],
        'ungrouped': [section id]}

    `sections` is `sections_for(schemas)`; passing the list that was already
    built keeps the two from being computed against different schema sets.

    ABSENCE IS NAMED, NEVER IMPLIED. `absent` carries every declared child none
    of whose subsystems exist yet, so a group with an empty `sections` says
    which pages have not arrived -- a group that renders as a bare header with
    nothing said about it is the failure mode this key exists to prevent
    (AGENTS.md section 3). A group that declares no children at all has an empty
    `absent` and a `note` instead.
    """
    secs = list(sections if sections is not None else sections_for(schemas))
    by_sub = dict((s['subsystem'], s) for s in schemas)
    order = dict((s['id'], i) for i, s in enumerate(secs))

    groups, claimed = [], set()
    for g in SECTION_GROUPS:
        ids, absent = [], []
        for child in g.get('sections', []):
            sec = resolve_child(child, by_sub)
            if sec is None:
                absent.append(child_id(child))
            elif sec['id'] in order and sec['id'] not in claimed:
                claimed.add(sec['id'])
                ids.append(sec['id'])
        groups.append({'id': g['id'], 'title': g['title'],
                       'note': g.get('note'),
                       'sections': sorted(ids, key=lambda i: order[i]),
                       'absent': absent})
    ungrouped = [s['id'] for s in secs if s['id'] not in claimed]
    return {'groups': groups, 'ungrouped': ungrouped}


def decorate_schemas(schemas):
    """A copy of the schemas with the presentation keys the page renders from.

    Derived every time the model is built and never written anywhere: the files
    under schema/ are the source of truth and this process does not edit them.
    """
    out = []
    for sch in schemas:
        c = json.loads(json.dumps(sch))
        prose, src = section_prose(sch)
        c['docParagraphs'] = prose
        c['docSource'] = src
        win = axis_windows_for(sch)
        if win:
            c['axisWindows'] = win
        for f in c['fields']:
            f['docText'] = field_help(f)
            g = REFERENCE_GROUPING.get((c['subsystem'], f['path']))
            if g:
                f['groupBy'] = g
            # `absent` is shown to the player too, under the control it belongs
            # to, so it goes through the same strip as the help above.
            if f.get('absent'):
                f['absent'] = strip_maintainer_marks(' '.join(str(f['absent']).split()))
        out.append(c)
    return out


# ---------------------------------------------------------------------------
# table shape and column formats

def table_shape(value, field):
    """Which of the two serialisation shapes a table field is in on disk.

    keyedBy says what the key column is; it does not by itself decide the
    shape. missionrewards declares keyedBy "type" and ships an array, which
    MissionRewards.cs:298 deserialises as List<MissionOverride>. So the shape
    is read from the data and preserved, and keyedBy only picks the shape for a
    field with nothing on disk yet.
    """
    if isinstance(value, dict):
        return 'object'
    if isinstance(value, list):
        return 'array'
    return 'object' if field.get('keyedBy') else 'array'


def key_as_declared(key, field):
    """An object-shaped table's key is a JSON string; the schema says what it is.

    fatigue's byPowerLevel blocks are objects keyed by the power level, so the
    key arrives as "7" while every other cell in the row is a number. The curve
    chart plots a point only where both coordinates are numbers, so the whole
    series read as unset and the chart said so. Typing in that same cell
    produced a real int, so the column held two types depending on whether the
    value had been edited yet. Coerced once here, at the seam where the row is
    built, so the rest of the program sees the column the schema declares.

    Writing back is unaffected: rows_to_value stringifies the key on the way
    out whatever type it holds.
    """
    t = key_col_type(field)
    if t not in ('int', 'float'):
        return key
    try:
        n = float(key)
    except (TypeError, ValueError):
        return key                     # not a number after all; leave it alone
    if t == 'int':
        return int(n) if n == int(n) else n
    return n


def key_col_type(field):
    key_col = field.get('keyedBy')
    if not key_col:
        return None
    for c in field.get('row', []):
        if c['name'] == key_col:
            return c.get('type')
    return None


def rows_from(value, field, shape):
    """-> [(cells, extras, key)] with cells carrying None for every absent column."""
    cols = [c['name'] for c in field.get('row', [])]
    key_col = field.get('keyedBy')
    out = []
    if shape == 'object':
        items = list((value or {}).items())
        for k, sub in items:
            sub = sub if isinstance(sub, dict) else {}
            cells = {}
            for c in cols:
                if c == key_col:
                    cells[c] = key_as_declared(k, field)
                else:
                    cells[c] = sub.get(c, None)
            extras = dict((kk, vv) for kk, vv in sub.items() if kk not in cols)
            out.append((cells, extras, k))
    else:
        for row in (value or []):
            row = row if isinstance(row, dict) else {}
            cells = dict((c, row.get(c, None)) for c in cols)
            extras = dict((kk, vv) for kk, vv in row.items() if kk not in cols)
            out.append((cells, extras, None))
    return out


def infer_column_formats(field, rows):
    """Which string columns carry the adjustment grammar.

    A column is 'adjust' when the schema says so ("format": "adjust" on the row
    column), otherwise by inference from the file: the table must show at least
    one non-empty value that parses as an adjustment, and every non-empty value
    in this column must parse. A prose column disqualifies itself on its first
    row; a column that is empty everywhere inherits the table's verdict.

    CORRECTION, 2026-08-31. This docstring used to say "no schema carries that
    today" and to suggest adding the key to the five slot columns of
    missionrewards.schema.json as future work. That has been done: those five
    now declare "format": "adjust" and take the declared branch above, so the
    inference no longer decides them. It still decides every other string
    column, and is kept because it is the fallback for a table whose schema
    says nothing.
    """
    cols = field.get('row', [])
    key_col = field.get('keyedBy')
    fmt = {}
    candidates = []
    for c in cols:
        if c.get('format'):
            fmt[c['name']] = c['format']
            continue
        if c.get('type') == 'string' and c['name'] != key_col:
            candidates.append(c['name'])
    evidence = False
    per_col_ok = {}
    for name in candidates:
        ok = True
        seen = False
        for cells, _extras, _k in rows:
            v = cells.get(name)
            if not isinstance(v, str) or v.strip() == '':
                continue
            seen = True
            if parse_adjust(v)['ok']:
                evidence = True
            else:
                ok = False
        per_col_ok[name] = (ok, seen)
    for name in candidates:
        ok, _seen = per_col_ok[name]
        fmt[name] = 'adjust' if (evidence and ok) else 'text'
    for c in cols:
        fmt.setdefault(c['name'], 'text' if c.get('type') == 'string' else '')
    if key_col:
        fmt[key_col] = 'key'
    return fmt


# ---------------------------------------------------------------------------
# the document: everything read off disk, in one object

class Document:
    def __init__(self, config_dir, schemas):
        self.config_dir = config_dir
        self.schemas = schemas
        self.cfg = None
        self.cfg_error = None
        self.sidecars = {}       # unit -> that section's parsed dict
        self.sidecar_errors = {}  # unit -> str
        self.sidecar_raw = {}    # unit -> bytes of its physical file
        self.file_docs = {}      # physical file -> whole parsed document
        self.file_raw = {}       # physical file -> bytes
        # rel -> the entry read_overlay built.
        #
        # CORRECTION, 2026-09-14. This said, in this position:
        #
        #   "READ ONLY: no save path writes one, because
        #    scripts/rules_to_overlays.py is the only thing that may."
        #
        # Both halves are now wrong and they stopped being wrong at different
        # times. The REASON lapsed first: rules_to_overlays.py was retired in
        # Phase 9 together with its subject, ckf.hardmode.rules.json, so from
        # that day the sentence named no live writer at all and the rule it
        # justified had nothing holding it up. The RULE went on standing
        # anyway, unexamined, until David ruled on 2026-09-14 that the write
        # path opens for lever and override columns -- he could not edit any of
        # the cells this change had just created and wants them to save the way
        # Fatigue and Elapse already do.
        #
        # HOW THE MISTAKE WAS MADE, because it is the reusable part: a
        # constraint was recorded together with its reason in one sentence, and
        # when the reason was deleted the constraint was not re-read. Nothing
        # pointed at it from rules_to_overlays.py's side, so retiring that
        # script could not have surfaced this.
        #
        # What is true now: identity columns, control columns and the key
        # column are still never written (overlay_editable says which is
        # which); a lever cell is written by replacing ONE FIELD'S SPAN inside
        # the line it is in, in the same atomic commit and the same journal as
        # every .cfg and sidecar edit.
        self.overlays = {}
        # rel -> the bytes read_overlay parsed, kept for exactly the reason
        # file_raw is kept for the JSON files: apply_edits is pure and may not
        # open a file, and the writer needs the original bytes to splice into.
        # NOT a substitute for the fingerprint -- api_save still compares the
        # on-disk digest against the one the browser was shown before anything
        # is written.
        self.overlay_raw = {}


def read_document(config_dir, schemas):
    doc = Document(config_dir, schemas)
    cfg_path = os.path.join(config_dir, 'ckf.hardmode.cfg')
    try:
        doc.cfg = CfgFile.load(cfg_path)
    except OSError as e:
        doc.cfg_error = '%s: %s' % (type(e).__name__, e)
    for fname, units in sidecar_files(schemas).items():
        p = os.path.join(config_dir, fname)
        try:
            raw = read_bytes(p)
            parsed = check_schema.load_jsonc(p)
        except OSError as e:
            for u in units:
                doc.sidecar_errors[u] = '%s: %s' % (type(e).__name__, e)
            continue
        except ValueError as e:
            for u in units:
                doc.sidecar_errors[u] = 'not parseable as JSON/JSONC: %s' % e
            continue
        doc.file_raw[fname] = raw
        doc.file_docs[fname] = parsed
        for u in units:
            sec = unit_section(u)
            if sec is None:
                doc.sidecars[u] = parsed
            elif isinstance(parsed, dict) and sec in parsed:
                doc.sidecars[u] = parsed[sec]
            else:
                # Not an error the GUI invents a blank section for: a missing
                # section is the same class of thing as a missing file, and the
                # subsystem's controls must read as unreadable rather than as
                # empty-and-ready-to-save.
                doc.sidecar_errors[u] = 'no "%s" section in %s' % (sec, fname)
                continue
            doc.sidecar_raw[u] = raw
    doc.overlays = read_overlays(config_dir, schemas)
    for rel in doc.overlays:
        p = os.path.join(config_dir, rel)
        try:
            doc.overlay_raw[rel] = read_bytes(p)
        except OSError:
            pass                      # the entry already carries the error
    return doc


# ---------------------------------------------------------------------------
# the model the browser renders from

def build_model(doc):
    schemas = doc.schemas
    values_cfg = {}
    for path, (_sch, f) in cfg_fields(schemas).items():
        if doc.cfg is None:
            values_cfg[path] = {'present': False, 'value': None, 'raw': None,
                                'error': doc.cfg_error or 'cfg not read'}
            continue
        raw = doc.cfg.raw_value(path)
        if raw is None:
            values_cfg[path] = {'present': False, 'value': None, 'raw': None}
        else:
            v, ok = parse_cfg_value(f['type'], raw)
            values_cfg[path] = {'present': True, 'value': v, 'raw': raw,
                                'error': None if ok else 'not a %s' % f['type']}

    values_json = {}
    tables = {}
    extras_store = {}
    for (name, path), (_sch, f) in json_fields(schemas).items():
        js = doc.sidecars.get(name)
        slot = values_json.setdefault(name, {})
        if js is None:
            slot[path] = {'present': False, 'value': None,
                          'error': doc.sidecar_errors.get(name, 'sidecar not read')}
            continue
        val, found = dig(js, path)
        if f['type'] == 'table':
            shape = table_shape(val if found else None, f)
            rows = rows_from(val if found else None, f, shape)
            fmt = infer_column_formats(f, rows)
            key = '%s|%s' % (name, path)
            extras_store[key] = {}
            out_rows = []
            for i, (cells, extras, _k) in enumerate(rows):
                extras_store[key][i] = extras
                out_rows.append({'id': i, 'cells': cells,
                                 'extraKeys': sorted(extras.keys())})
            tables[key] = {'sidecar': name, 'path': path, 'shape': shape,
                           'present': found, 'keyColumn': f.get('keyedBy'),
                           'formats': fmt, 'rows': out_rows}
            slot[path] = {'present': found, 'table': key}
        else:
            slot[path] = {'present': found, 'value': val if found else None}

    unknown_top = {}
    declared_top = {}
    for sch in schemas:
        j = sidecar_unit(sch)
        if not j:
            continue
        for f in sch['fields']:
            if f['in'] == 'json':
                declared_top.setdefault(j, set()).add(f['path'].split('.')[0])
    for name, js in doc.sidecars.items():
        unknown_top[name] = sorted(k for k in js.keys()
                                   if k not in declared_top.get(name, set()))

    # A `reference` field's rows come out of the SCHEMA, not off disk, so it
    # gets a table entry like any other grid and no slot in values_json -- it
    # belongs to no file, is in no edit set, and no save can write it. Keyed by
    # subsystem rather than by unit; every unit is a path carrying a dot, so
    # the two key spaces cannot collide.
    for (sub, path), (_sch, f) in reference_fields(schemas).items():
        rows = rows_from(f.get('rows') or [], f, 'array')
        key = '%s|%s' % (sub, path)
        extras_store[key] = {}
        out_rows = []
        for i, (cells, extras, _k) in enumerate(rows):
            extras_store[key][i] = extras
            out_rows.append({'id': i, 'cells': cells,
                             'extraKeys': sorted(extras.keys())})
        tables[key] = {'sidecar': None, 'subsystem': sub, 'path': path,
                       'shape': 'array', 'present': bool(f.get('rows')),
                       'keyColumn': f.get('keyedBy'), 'readonly': True,
                       'formats': infer_column_formats(f, rows),
                       'rows': out_rows}

    return {'cfg': values_cfg, 'json': values_json, 'tables': tables,
            'overlays': doc.overlays,
            'unknownTopLevel': unknown_top}, extras_store


def enable_index(doc, model):
    """Effective enable state per subsystem: its own gate AND every block gate,
    AND'd, with the master switch on top. A gate that cannot be read is
    'unknown', not false -- AGENTS.md section 3.

    Since 3.0 exactly one subsystem is gated by a cfg key -- General, the master
    switch itself -- and every other gate is a path in ckf.hardmode.json."""
    master = model['cfg'].get(MASTER_KEY)
    if master and master.get('present') and master.get('error') is None:
        master_state = bool(master['value'])
        master_known = True
    else:
        master_state, master_known = None, False

    out = []
    for sch in doc.schemas:
        en = sch.get('enable') or {}
        gates = []
        if en.get('cfg'):
            v = model['cfg'].get(en['cfg'], {})
            gates.append({'kind': 'cfg', 'name': en['cfg'],
                          'state': (bool(v.get('value')) if v.get('present') and not v.get('error') else None),
                          'detail': v.get('error') or (None if v.get('present') else 'key absent from the cfg')})
        name = sidecar_unit(sch)
        if en.get('json') and name:
            v = model['json'].get(name, {}).get(en['json'], {})
            gates.append({'kind': 'json', 'name': '%s: %s' % (name, en['json']),
                          'state': (bool(v.get('value')) if v.get('present') and not v.get('error') else None),
                          'detail': v.get('error') or (None if v.get('present') else 'path absent from the sidecar')})
        blocks = []
        if name:
            seen = set()
            for f in sch['fields']:
                eb = f.get('enabledBy')
                if not eb or eb in seen or f['in'] != 'json':
                    continue
                seen.add(eb)
                v = model['json'].get(name, {}).get(eb, {})
                blocks.append({'kind': 'block', 'name': '%s: %s' % (name, eb),
                               'state': (bool(v.get('value')) if v.get('present') else None),
                               'detail': None if v.get('present') else 'path absent from the sidecar'})

        states = [g['state'] for g in gates]
        if not states:
            effective = 'n/a'
        elif any(s is None for s in states):
            effective = 'unknown'
        elif all(states):
            effective = 'on'
        else:
            effective = 'off'
        gated_by_master = False
        if en.get('cfg') != MASTER_KEY:          # the master does not gate itself
            if master_known and master_state is False:
                gated_by_master = True
            elif not master_known:
                if effective == 'on':
                    effective = 'unknown'

        out.append({
            'subsystem': sch['subsystem'],
            'title': sch.get('title', sch['subsystem']),
            'gates': gates,
            'blocks': blocks,
            'effective': effective,
            'gatedByMaster': gated_by_master,
            'masterKnown': master_known,
        })
    return out


# ---------------------------------------------------------------------------
# validation via check_schema

def files_check_schema_reads(schemas):
    """Every path check_schema looks at under the config dir, derived from the
    schemas rather than guessed, so a staging copy is complete.

    CORRECTION, 2026-09-14: THE OVERLAYS WERE MISSING FROM THIS AND IT SHOWED.
    This returned 12 paths and none of them was an overlay, on the reading that
    check_schema "opens" only the documents it parses. It does not only open:
    it stats every declared overlay and grades an absent one MISSING, and it
    censuses ckf.hardmode.d for sheets no schema claims and grades those STALE.
    Because stage_and_validate copies exactly this list, every validate and
    every save has been running check_schema over a staging directory with no
    overlay in it, and getting back 53 MISSING problems -- one per declared
    sheet -- for files that were all present on disk [measured 2026-09-14: 53
    problems, all kind MISSING, on a no-op save against the live config].
    MISSING is not in BLOCKING so no save was ever refused by it, which is
    exactly why it survived: the editor showed the player 53 false problems on
    every save and nothing failed.

    The same omission meant `fingerprints` did not cover the sheets either, so
    an overlay edited on disk between the browser's read and the save could not
    be detected. Both are fixed by the sheets being in this list.
    """
    rel = {'ckf.hardmode.cfg'}
    rel.update(overlay_paths_all(schemas))
    for sch in schemas:
        j = sch.get('targets', {}).get('json')
        if j:
            rel.add(j)
        for inv in sch.get('invariants', []):
            if inv.get('kind') == 'mirror':
                rel.add(inv['source'].split('#')[0])
                rel.add(inv['target'])
                if inv.get('mergeWith'):
                    rel.add(inv['mergeWith'].split('#')[0])
    return sorted(rel)


CHECK_SCHEMA_PY = os.path.join(SCHEMA_DIR, 'check_schema.py')
CHECK_SCHEMA_TIMEOUT = 120

# The re-entry flag. main() dispatches on it before argparse exists, so it has
# to be argv[1] and nothing else may claim the name.
RUN_CHECK_SCHEMA = '--run-check-schema'


def check_schema_argv(config_dir, frozen=None):
    """The argv that runs check_schema in its own process.

    Unfrozen, sys.executable is a Python interpreter and gets handed the script
    path. That is what this has always done and it is unchanged.

    Frozen, sys.executable IS this exe. Handing it a script path would relaunch
    the GUI and open a browser instead of validating anything, so the exe
    re-enters itself through RUN_CHECK_SCHEMA. --schema is deliberately left
    off: the child then resolves its own bundle rather than borrowing the
    parent's _MEIPASS, which stops existing the moment the parent exits, and
    `CKF-Config-Editor.exe --run-check-schema --config DIR` works standalone.

    `frozen` is a parameter only so --selftest can build both shapes on one
    machine. Every caller in the server passes None.
    """
    if FROZEN if frozen is None else frozen:
        return [sys.executable, RUN_CHECK_SCHEMA, '--config', config_dir]
    return [sys.executable or 'python3', CHECK_SCHEMA_PY,
            '--config', config_dir, '--schema', SCHEMA_DIR]


def run_check_schema_entry(args):
    """The RUN_CHECK_SCHEMA re-entry. -> check_schema's own exit code.

    check_schema.main() reads sys.argv, so the flag is stripped and the rest is
    handed over verbatim. A caller that named no --schema gets THIS process's
    SCHEMA_DIR, which frozen is the bundle and unfrozen is ../schema -- so
    `serve.py --run-check-schema --config DIR` and the exe's version of it do
    the same thing, and --selftest can exercise the dispatch on a machine with
    no PyInstaller on it.

    THE --schema DEFAULT LOOKS DEAD AND IS NOT. check_schema.py's own default
    is dirname(its own __file__), and two things independently make that land
    on a real schema directory, so removing EITHER changes nothing and a fault
    sweep removing one at a time catches neither: [measured 2026-09-04]

      check_schema.py shipped as a data file at schema/check_schema.py makes
      the frozen module's __file__ read <_MEIPASS>/schema/check_schema.py, so
      its own default resolves.

      this line makes it resolve wherever __file__ lands.

    Drop both and the exe prints `no *.schema.json in <_MEIPASS>` and validates
    nothing, which is the state every save is then refused from. The sweep
    removes both together, because that is the only edit that can fail.

    Nothing is caught. check_schema.main() ends in sys.exit() on a usage error
    and argparse exits 2; either reaches run_check_schema as a returncode
    outside (0, 1), which is already read as a run that did not happen.
    """
    rest = list(args)
    if '--schema' not in rest:
        rest += ['--schema', SCHEMA_DIR]
    saved = sys.argv
    sys.argv = [saved[0]] + rest
    try:
        return check_schema.main()
    finally:
        sys.argv = saved

# check_schema's last line. Its presence proves the run reached the end and the
# pipe carries the whole of it; its count proves no problem line was lost.
_CHECK_SUMMARY_RE = re.compile(r'^(\d+) problem\(s\)\.', re.M)
_CHECK_PROBLEM_RE = re.compile(r'^(STALE|MISSING|RANGE|INVARIANT)\s+(.*)$')


def run_check_schema(config_dir):
    """-> {'ran': bool, 'problems': [...], 'error': str|None}

    check_schema.py is the implementation of all four drift classes. It is run,
    not copied, and it is run in a CHILD PROCESS reading its own pipe.

    It used to be imported and called in-process, with `sys.argv` and
    `sys.stdout` swapped around the call. Both are process globals and
    ThreadingHTTPServer runs handlers in parallel: two overlapping requests --
    a save and a second browser tab's /api/model is enough -- redirected each
    other's stdout, so one call's problem lines landed in the other call's
    buffer. The save then saw an empty buffer, read `ran: True, problems: []`,
    and wrote a value its own validator had rejected. A lock around today's
    callers would have closed it until the next caller was added; a child
    process has no shared stdout to corrupt, so concurrency cannot reach the
    result at all.

    A run that could not run is reported as could-not-run. That is not only the
    exception path: the summary line must be there and its count must match the
    problem lines parsed, because a truncated pipe reads exactly like a clean
    file otherwise. An instrument's silence is not evidence (AGENTS.md
    section 3).

    WHAT the child is differs frozen and not -- see check_schema_argv -- and
    nothing else here changes with it. That is the property --selftest section
    16 asserts: freezing must not turn a broken child process into a clean
    file, so every could-not-run shape is re-run over the re-entry command.
    """
    cmd = check_schema_argv(config_dir)
    try:
        r = subprocess.run(cmd, stdin=subprocess.DEVNULL,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=CHECK_SCHEMA_TIMEOUT)
    except subprocess.TimeoutExpired:
        return {'ran': False, 'problems': [],
                'error': 'check_schema did not finish within %ds' % CHECK_SCHEMA_TIMEOUT}
    except Exception:
        return {'ran': False, 'problems': [],
                'error': 'check_schema could not be run:\n' + traceback.format_exc()}

    out = r.stdout.decode('utf-8', 'replace')
    err = r.stderr.decode('utf-8', 'replace').strip()
    # 0 = clean, 1 = problems found. Anything else, including the argparse and
    # sys.exit() paths, is a run that did not happen.
    if r.returncode not in (0, 1):
        return {'ran': False, 'problems': [],
                'error': 'check_schema exited: %s\n%s' % (r.returncode, err or out)}

    problems = []
    for line in out.splitlines():
        m = _CHECK_PROBLEM_RE.match(line)
        if m:
            problems.append({'kind': m.group(1), 'message': m.group(2)})

    m = _CHECK_SUMMARY_RE.search(out)
    if m is None:
        return {'ran': False, 'problems': [],
                'error': 'check_schema printed no summary line, so its output is '
                         'incomplete and cannot be read as clean.\n'
                         'stdout:\n%s\nstderr:\n%s' % (out, err)}
    if int(m.group(1)) != len(problems):
        return {'ran': False, 'problems': [],
                'error': 'check_schema reported %s problem(s) but %d line(s) came '
                         'back; the output is incomplete.\nstdout:\n%s'
                         % (m.group(1), len(problems), out)}
    return {'ran': True, 'problems': problems, 'error': None}


BLOCKING = ('RANGE', 'INVARIANT')


# ---------------------------------------------------------------------------
# building the proposed bytes for a save

class SaveRefused(Exception):
    def __init__(self, payload):
        super().__init__(payload.get('summary', 'refused'))
        self.payload = payload


# ---------------------------------------------------------------------------
# the `requires` invariant, enforced by the editor in both directions
#
# design.md section 4, "Enforcement is asymmetric on purpose": turning a slice
# ON auto-enables what it needs, with a note naming what changed; turning a
# slice OFF that a live slice needs is refused, naming the dependent.
#
# This pass runs BEFORE apply_edits renders any bytes and before
# stage_and_validate runs check_schema, so the refusal the player sees is the
# editor's -- which knows which key was just moved and can therefore name the
# dependent -- and not check_schema's INVARIANT, which knows only the final
# state. The INVARIANT is still the backstop, and it is the ONLY thing that
# catches a ckf.hardmode.cfg edited outside this editor.


# Top-level keys beginning with this are the repo's own metadata, written
# deliberately and read by nobody's schema: _version (Phase 3 stamps every
# slice file with one), _doc, _readme. check_schema exempts _version by name in
# its own stray-key guard; the prefix is the same convention, stated once.
METADATA_PREFIX = '_'


def stray_keys(doc, schemas):
    """Top-level keys in a slice file that no schema declares. -> {unit: [key]}

    THE EDITOR IS THE ONLY GATE THAT CAN SEE THESE. check_schema's own
    stray-key guard runs only `if claimed.get(fname)`, and `claimed` is filled
    in only for a schema that declares a `targets.section`; the Phase 3 split
    removed `section` from all nine, so the guard now `continue`s on every file
    and a leftover key is invisible to it. Measured 2026-09-13 against the live
    directory with implantStressClampMin still in implants-global.json after
    its field was deleted from the schema: `check_schema --game` printed
    0 problem(s), rc 0. The C# side still refuses it at launch through
    ConfigDoc.ReadSection, so it is caught eventually -- but by nothing a
    developer runs before shipping.

    NOTHING HERE IS GRADED, AND THAT IS DELIBERATE. Three different things look
    identical from disk:

      _version, _doc     repo metadata, excluded by prefix
      enabled            a RETIRED key, on eight slice files ON PURPOSE --
                         teampl.schema.json records that they are "still on
                         disk by design so an upgraded section is not refused
                         for an unknown key"
      implantStressClampMin
                         a key whose field was deleted from the schema and
                         which nothing has removed from the file yet

    Only the first is distinguishable, by the prefix. Nothing on disk marks the
    second, so calling either of the last two an error would be a false alarm
    on eight files to catch one -- and the spec's "An unknown key survives"
    requires exactly that an unknown key be "read, hidden from the editor, and
    written back untouched", which this does not change. So they are NAMED and
    counted, and nothing is called wrong. Grading them needs a schema that
    declares which retired keys it expects, which lives under schema/.
    """
    declared = {}
    for sch in schemas:
        u = sidecar_unit(sch)
        if not u:
            continue
        declared.setdefault(u, set())
        for f in sch['fields']:
            if f['in'] == 'json':
                declared[u].add(f['path'].split('.')[0])
    out = {}
    for unit, js in sorted(doc.sidecars.items()):
        if not isinstance(js, dict):
            continue
        extra = sorted(k for k in js
                       if not k.startswith(METADATA_PREFIX)
                       and k not in declared.get(unit, set()))
        if extra:
            out[unit] = extra
    return out


def stray_notes(doc, schemas):
    """One note per file carrying an undeclared key, and a census either way.

    Printed on every save and every validate. "No file carries one" and "this
    did not look" are different facts, and the guard that used to answer this
    question stopped running without either of them being said.
    """
    sk = stray_keys(doc, schemas)
    notes = []
    for unit, keys in sorted(sk.items()):
        notes.append(
            'undeclared: %s carries %d top-level key(s) no schema declares: %s. '
            'They are read, given no control, and written back untouched. That '
            'is what the spec asks for, and it is also what a misspelled key '
            'looks like — nothing on disk tells the two apart.'
            % (unit, len(keys), ', '.join(keys)))
    notes.append('undeclared: %d of %d file(s) carry a top-level key no schema '
                 'declares (%d key(s) in total; keys beginning "%s" are the '
                 'repo\'s own metadata and are not counted).'
                 % (len(sk), len(doc.sidecars), sum(len(v) for v in sk.values()),
                    METADATA_PREFIX))
    return notes


def canonical_bytes(raw):
    """The bytes this editor would write for a document whose current bytes are
    `raw`, with no value changed. Same three decisions render_file_bytes makes:
    two-space JSON, the file's own newline, the file's own BOM.
    """
    obj = json.loads(check_schema.strip_jsonc(raw.decode('utf-8-sig')))
    nl = newline_of_bytes(raw)
    text = json.dumps(obj, indent=2, ensure_ascii=False) + '\n'
    if nl != '\n':
        text = text.replace('\n', nl)
    data = text.encode('utf-8')
    return (b'\xef\xbb\xbf' + data) if has_bom(raw) else data


def noncanonical_files(doc):
    """Files on disk that are not in the form this editor writes.

    -> {rel: {'disk': n, 'canonical': n, 'jsonc': bool}}

    THE SLICE FILES ARE MEANT TO BE HAND-EDITED with the game and the editor
    closed (design.md section 1). The writer reproduces a canonical form -- two
    spaces, one trailing newline, no blank lines between members, Python's own
    number rendering -- and keeps three things about the file it found: its
    newline style, its BOM, and the order of its keys, including keys no schema
    declares. What it cannot reproduce is anything the canonical form has no
    place for, and a player who hand-edits a file gets that back reformatted on
    the next save even when no value moved.

    Measured 2026-09-13, by writing each variation into a slice file and taking
    a no-op save:

      PRESERVED   key order, including a hand-reordered file; keys no schema
                  declares; CRLF; a BOM; both together; a float written 3.0
      NORMALISED  blank lines between members; // and /* */ comments; trailing
                  commas; any indent but two spaces; a one-line compact file; a
                  missing or doubled trailing newline; 3.00 and 3e0 -> 3.0;
                  a \\uXXXX escape -> the character it names

    The whitespace half of that list is a canonical form, not a loss, and the
    shipped files are expected to match it -- ten of the eleven do.  The JSONC
    half is different in kind: load_jsonc ACCEPTS comments and trailing commas,
    so a player may legitimately write them, and the writer then deletes them.
    That is content, not formatting, and `jsonc` marks it so the note can say so
    rather than letting it go quietly. Preserving comments would need a
    comment-preserving writer, which this is not; being told is the fix here.
    """
    out = {}
    for rel, raw in sorted(doc.file_raw.items()):
        try:
            canon = canonical_bytes(raw)
        except ValueError:
            continue                      # unparseable; already an error
        if canon == raw:
            continue
        text = raw.decode('utf-8-sig')
        out[rel] = {'disk': len(raw), 'canonical': len(canon),
                    'jsonc': check_schema.strip_jsonc(text) != text}
    return out


def reformat_notes(doc):
    """One note per file a save would reformat, and a census line either way.

    Printed on every save and every validate, including a run with nothing to
    report: "no file needs reformatting" and "this instrument did not look" are
    different facts.
    """
    nc = noncanonical_files(doc)
    notes = []
    for rel, info in sorted(nc.items()):
        notes.append(
            'formatting: %s on disk is not the form this editor writes '
            '(%d bytes vs %d). Saving rewrites it with no value changed: two '
            'spaces, one trailing newline, no blank line between members.%s'
            % (rel, info['disk'], info['canonical'],
               '  IT ALSO CARRIES COMMENTS OR TRAILING COMMAS, which are read '
               'but cannot be written back, so saving deletes them.'
               if info['jsonc'] else ''))
    notes.append('formatting: %d of %d file(s) read are already in the form '
                 'this editor writes.'
                 % (len(doc.file_raw) - len(nc), len(doc.file_raw)))
    return notes


def requires_groups(schemas):
    """Every declared `requires`, as (subsystem, dependent, [needs], reason).

    Keys are normalised through check_schema.inv_key rather than re-parsed
    here: an invariant may name a cfg key bare ("Section.Key") or with the
    .cfg's own file name in front of it, which is the spelling design.md
    section 4 uses, and the two are the same key. Re-implementing that
    normalisation is how the two sides drift.
    """
    out = []
    for sch in schemas:
        for inv in sch.get('invariants', []):
            if inv.get('kind') != 'requires':
                continue
            out.append((sch['subsystem'],
                        check_schema.inv_key(inv['key']),
                        [check_schema.inv_key(k) for k in (inv.get('needs') or [])],
                        inv.get('reason', '')))
    return out


def requires_pass(schemas, doc, edits):
    """Enforce `requires` over one proposed edit set. -> (edits, notes).

    Raises SaveRefused for the downward direction. `edits` is copied, never
    mutated in place, so a caller that retries sees what it sent.

    THE TWO DIRECTIONS ARE NOT THE SAME CHECK.

      down  A save that turns a needed key OFF while a dependent stays on is
            refused, and the message names the dependent. "Stays on" is read
            from the state the save would leave behind, so turning a dependent
            and its need off together is legal -- which is also what
            check_schema says, where a false dependent is vacuously fine.

      up    A save that turns a dependent ON pulls every key its `requires`
            names on with it, transitively, and names every key it changed.

    THE UPWARD CLOSURE IS SEEDED ONLY BY THE KEYS THIS SAVE TURNS ON. A
    dependent already true on disk whose need is already false is a hand-edited
    violation; enabling the need here would silently widen a config the player
    did not touch, so it is left alone and goes to check_schema, which grades
    it INVARIANT and blocks the save.

    A KEY ABSENT FROM THE .cfg IS NOT "OFF". Its schema declares a `default`
    and that is what applies until the key is written -- every slice schema on
    disk today declares `"default": true`. check_schema cannot use that: it
    grades what is in the file and reports an absent key SKIPPED. So on a fresh
    install the editor is the stricter of the two, deliberately, and the
    linkedEnable hole recorded in tasks.md Phase 1 -- "the editor cannot protect
    a linked group on a fresh install" -- is not reproduced here.
    """
    groups = requires_groups(schemas)
    cfgs = cfg_fields(schemas)
    notes, skipped = [], []
    total = len(groups)
    compared = 0
    auto = []

    def declared_cfg(key):
        return key in cfgs

    def on_disk(key):
        """(effective, in_the_file) for one cfg key. effective is None when the
        question cannot be answered -- the .cfg did not parse, the key is not a
        bool, or it is absent with no bool default to fall back on."""
        if doc.cfg is None:
            return None, False
        raw = doc.cfg.raw_value(key)
        if raw is None:
            d = cfgs[key][1].get('default')
            return (d if isinstance(d, bool) else None), False
        v, ok = parse_cfg_value(cfgs[key][1]['type'], raw)
        return (v if (ok and isinstance(v, bool)) else None), True

    def proposed(key):
        spec = (edits.get('cfg') or {}).get(key)
        if isinstance(spec, dict) and 'value' in spec:
            return spec['value'] if isinstance(spec['value'], bool) else None
        return on_disk(key)[0]

    # Which keys this save moves, and in which direction. A key absent from
    # `edits` is a key the page did not send, which means it is not present in
    # the file and was not touched -- its default still applies.
    def moved_off(key):
        return on_disk(key)[0] is True and proposed(key) is False

    # ---- every key both directions will read, graded once
    live = []
    for sub, dep, needs, reason in groups:
        bad = [k for k in [dep] + needs if not declared_cfg(check_schema.inv_key(k))]
        if bad:
            # check_schema already grades these MISSING (the dependent) or
            # STALE (a need). Saying nothing here would make the editor look
            # like it enforced a declaration it never read.
            skipped.append('%s: %s names %s, which no schema declares as a cfg '
                           'key, so the editor enforced nothing for it'
                           % (sub, dep, ', '.join(bad)))
            continue
        if not needs:
            skipped.append('%s: %s declares no needs, so nothing was compared'
                           % (sub, dep))
            continue
        unknown = [k for k in [dep] + needs if on_disk(k)[0] is None]
        if unknown:
            skipped.append('%s: %s -- %s could not be read as a true/false key, '
                           'so the group was not compared'
                           % (sub, dep, ', '.join(unknown)))
            continue
        live.append((sub, dep, needs, reason))
        compared += 1

    # ---- down: a need turned off under a dependent that stays on
    for sub, dep, needs, reason in live:
        if proposed(dep) is not True:
            continue                      # the dependent is off or going off
        for n in needs:
            if not moved_off(n):
                continue
            in_file = on_disk(dep)[1]
            raise SaveRefused({
                'summary': '%s cannot be turned off while %s is on'
                           % (n, dep),
                'detail': '%s needs %s. %s\n\nNothing was written. Turning a '
                          'slice on is a widening and the editor does it for '
                          'you; turning one off underneath something that '
                          'needs it is a breakage, so it is refused here '
                          'rather than left for the checker to call an '
                          'INVARIANT. Turn %s off first, then %s.%s'
                          % (dep, n, reason, dep, n,
                             '' if in_file else
                             '\n\n%s is not in ckf.hardmode.cfg, so its '
                             'schema default applies and it counts as on.'
                             % dep),
                'requires': {'need': n, 'dependent': dep, 'subsystem': sub},
            })

    # ---- up: transitive closure, seeded only by what this save turns on
    #
    # A shallow copy with its own cfg block: keys are added here, none of the
    # specs already in it are touched, and the json side -- which carries whole
    # tables -- is not copied. `proposed` reads this same name, so a key added
    # in one round is seen by the next, which is what makes the closure
    # transitive rather than one hop.
    edits = dict(edits)
    edits['cfg'] = dict(edits.get('cfg') or {})
    frontier = set()
    for sub, dep, needs, reason in live:
        if on_disk(dep)[0] is not True and proposed(dep) is True:
            frontier.add(dep)
    # A key enters the frontier only by flipping false -> true, and can flip at
    # most once, so this terminates on a cycle as well as on a chain. The cap
    # is a true bound plus one; if it is ever reached that is a defect, and the
    # note says so rather than truncating in silence.
    rounds = 0
    while frontier and rounds <= len(live) + 1:
        rounds += 1
        nxt = set()
        for sub, dep, needs, reason in live:
            if dep not in frontier or proposed(dep) is not True:
                continue
            for n in needs:
                if proposed(n) is True:
                    continue
                edits['cfg'][n] = {'value': True}
                auto.append((n, dep, on_disk(n)[1], reason))
                nxt.add(n)
        frontier = nxt
    if frontier:
        skipped.append('the requires closure did not settle in %d round(s); '
                       '%s was not followed' % (rounds, ', '.join(sorted(frontier))))

    for n, dep, in_file, reason in auto:
        notes.append('requires: turned on %s because %s needs it%s. %s'
                     % (n, dep,
                        '' if in_file else ' (the key was not in the file; the '
                                           'save adds it)',
                        reason))
    for s in skipped:
        notes.append('requires: SKIPPED -- %s' % s)
    # Printed on every save and every validate, including one with no requires
    # declared at all: "0 declared" and "2 declared, 0 compared" are different
    # facts, and a line that appeared only when something happened could not
    # tell them apart. The same census check_schema prints.
    notes.append('requires: %d declared, %d compared, %d turned on, %d skipped.'
                 % (total, compared, len(auto), len(skipped)))
    return edits, notes


def render_file_bytes(fname, working, doc):
    """Rebuild one physical JSON file from the sections that live in it.

    Only the sections that were edited are in `working` as new objects; every
    other section, and every top-level key no section claims -- "_version", and
    whatever a later version adds -- is carried over from what was read, in the
    order it was read. A save that touches one subsystem must not drop a key
    belonging to another that shares its file.
    """
    units = [u for u in working if unit_file(u) == fname]
    sectioned = [u for u in units if unit_section(u)]
    if not sectioned:
        obj = working[units[0]] if units else {}
    else:
        base = doc.file_docs.get(fname)
        obj = json.loads(json.dumps(base)) if isinstance(base, dict) else {}
        for u in units:
            obj[unit_section(u)] = working[u]
    raw = doc.file_raw.get(fname)
    nl = newline_of_bytes(raw) if raw else '\n'
    bom = has_bom(raw) if raw else False
    text = json.dumps(obj, indent=2, ensure_ascii=False) + '\n'
    if nl != '\n':
        text = text.replace('\n', nl)
    data = text.encode('utf-8')
    return (b'\xef\xbb\xbf' + data) if bom else data


def apply_edits(doc, extras_store, edits, strip_readme=True):
    """-> ({relpath: bytes}, notes). Pure: touches no file on disk."""
    schemas = doc.schemas
    cfgs = cfg_fields(schemas)
    jsons = json_fields(schemas)
    notes = []
    proposed = {}

    # ---- cfg
    if doc.cfg is None:
        if edits.get('cfg'):
            raise SaveRefused({'summary': 'the cfg could not be read, so it cannot be edited',
                               'detail': doc.cfg_error})
    else:
        cfg = CfgFile(doc.cfg.to_bytes())
        for path, spec in (edits.get('cfg') or {}).items():
            if path not in cfgs:
                raise SaveRefused({'summary': 'no schema declares the cfg key %r' % path})
            _sch, f = cfgs[path]
            value = spec.get('value')
            try:
                rendered = render_cfg_value(f['type'], value)
            except (TypeError, ValueError) as e:
                raise SaveRefused({'summary': '%s: %r is not a %s (%s)'
                                   % (path, value, f['type'], e)})
            if f['type'] == 'stringList' and '\n' in rendered:
                raise SaveRefused({'summary': '%s: a stringList must stay on one line' % path})
            what = cfg.set_value(path, rendered)
            if what != 'unchanged':
                notes.append('%s %s = %s' % (what, path, rendered))
        proposed['ckf.hardmode.cfg'] = cfg.to_bytes()

    # ---- sidecars
    touched_sidecars = set()
    working = {}
    for name in sidecar_names(schemas):
        if name in doc.sidecars:
            working[name] = json.loads(json.dumps(doc.sidecars[name]))

    for name, block in (edits.get('json') or {}).items():
        if name not in working:
            raise SaveRefused({'summary': 'unknown or unreadable sidecar %r' % name,
                               'detail': doc.sidecar_errors.get(name)})
        js = working[name]
        touched_sidecars.add(name)

        for path, spec in (block.get('scalars') or {}).items():
            if (name, path) not in jsons:
                raise SaveRefused({'summary': 'no schema declares %s path %r' % (name, path)})
            _sch, f = jsons[(name, path)]
            present = bool(spec.get('present', True))
            value = spec.get('value')
            if present:
                value = coerce_scalar(f['type'], value, '%s:%s' % (name, path))
                old, found = dig(js, path)
                if found and numeric_equal(old, value):
                    value = old          # keep the on-disk representation
            put(js, path, value, present)

        for path, spec in (block.get('tables') or {}).items():
            if (name, path) not in jsons:
                raise SaveRefused({'summary': 'no schema declares %s path %r' % (name, path)})
            _sch, f = jsons[(name, path)]
            if f['type'] != 'table':
                raise SaveRefused({'summary': '%s:%s is not a table' % (name, path)})
            key = '%s|%s' % (name, path)
            old_val, found = dig(js, path)
            rows = spec.get('rows') or []
            if not found and not rows:
                # A table the schema declares and the file does not have. An
                # empty grid is what "absent" looks like in the browser, and
                # writing {} or [] back would turn an absent key into a present
                # empty one -- the same class of mistake as writing 0 for
                # unset. Left alone; check_schema goes on reporting it MISSING,
                # which is the true state.
                continue
            shape = spec.get('shape') or table_shape(old_val, f)
            built = build_table(f, rows, shape,
                                extras_store.get(key, {}),
                                '%s:%s' % (name, path))
            put(js, path, built, True)

        if strip_readme and '_readme' in js:
            js.pop('_readme')
            notes.append('%s: removed the _readme block (gui-plan.md 3.1)' % name)

    for fname in sorted({unit_file(u) for u in touched_sidecars}):
        proposed[fname] = render_file_bytes(fname, working, doc)

    # ---- lever sheets, in the SAME proposal as the cfg and the sidecars
    #
    # Not beside the transaction: in it. commit() writes every rel in
    # `proposed` through one journal, so a sheet edit and a .cfg edit either
    # both land or both do not, and recover_journal() finishes either of them
    # after a crash. A sheet that is not named by an edit is not in `proposed`
    # at all -- a save that changes no cell of it cannot move its bytes because
    # nothing ever offers them.
    proposed.update(apply_overlay_edits(doc, edits, notes))

    # ---- the mirror, in the same transaction as its source
    for sch in schemas:
        for inv in sch.get('invariants', []):
            if inv.get('kind') != 'mirror':
                continue
            sfile, spath = inv['source'].split('#', 1)
            # Which unit owns that path: the one whose section is its first
            # segment. With no section the unit is the file itself.
            src = None
            for u in working:
                if unit_file(u) != sfile:
                    continue
                sec = unit_section(u)
                if sec is None or spath == sec or spath.startswith(sec + '.'):
                    src = u
                    break
            if src is None or src not in touched_sidecars:
                continue
            teampl = working[src]
            merged, stock = gen_teampl_labels.merged_cells(teampl)
            rules = gen_teampl_labels.rules_for(merged, stock)
            # The same label gen_teampl_labels.main() writes, or a no-op save
            # would rewrite the mirror for no reason but a differing string.
            text = gen_teampl_labels.render(
                rules, '%s#%s' % (sfile, unit_section(src)) if unit_section(src) else sfile)
            tgt = inv['target']
            cur = None
            p = os.path.join(doc.config_dir, tgt)
            if os.path.exists(p):
                cur = read_bytes(p)
            nl = newline_of_bytes(cur) if cur else '\n'
            data = text.replace('\n', nl).encode('utf-8') if nl != '\n' else text.encode('utf-8')
            proposed[tgt] = data
            notes.append('%s: regenerated, %d rule(s)' % (tgt, len(rules)))

    return proposed, notes


# ---------------------------------------------------------------------------
# WRITING A LEVER CELL.
#
# WHAT CAN BE VALIDATED HERE AND WHAT CANNOT, SAID BEFORE THE CODE.
#
# check_schema.py declares NO COLUMNS for these sheets. It checks that a
# declared overlay exists and that no unclaimed sheet is sitting in the slice
# directory, and it never parses one -- its own comment says so: "A direct
# overlay is NOT a JSON document ... so it is checked for EXISTENCE and never
# parsed." So the range and type checking every .cfg key and every sidecar
# field gets is NOT AVAILABLE for a cell here, and no amount of staging will
# make it available. There is no schema to consult.
#
# What IS available is the grammar of the cell, and it differs by kind:
#
#   expanded  The operator is in the CELL. scripts/implants.py, gear_classes.py
#             and cyberweapons.py each carry a parse_adjust with the same
#             grammar this file's parse_adjust implements -- blank, =N, +N, -N,
#             xN, *N, or a bare number -- and an expander hands a cell that
#             fails it to `problems` rather than applying it. Measured
#             2026-09-14 over the 20 expanded sheets in the live config: 6,242
#             lever cells, 6,169 blank, and all 73 filled ones parse. So the
#             grammar is enforced, as a REFUSAL, by check_adjust_cell.
#
#   direct    The operator is in the HEADER and the cell is a bare value.
#             Overlays.cs decides what to do with it by trying
#             double.TryParse(v, NumberStyles.Float, InvariantCulture):
#               - parses         -> a numeric term under the header's operator.
#               - does not parse, header op is Set -> kept as a text literal.
#                 Real: 11 of the 379 filled direct lever cells in the live
#                 config are IconPng strings like "Charge-Max-Boost"
#                 [measured 2026-09-14].
#               - does not parse, header op is anything else -> the plugin
#                 LOGS A WARNING AND DROPS THE CELL. A silent no-op as far as
#                 the player is concerned.
#             So a non-numeric cell under a non-Set operator is REFUSED, quoting
#             the code; a non-numeric cell under Set is ACCEPTED and carries a
#             note naming the sheet, the column and the fact that nothing
#             range-checked it.
#
# EVERY overlay edit carries a note saying what was not checked. "Warn by name
# rather than accept silently" is the whole requirement, and a save whose notes
# said nothing would look exactly like a save that had been validated.

_OVERLAY_NUMBER_RE = re.compile(r'^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$')


def _overlay_is_number(text):
    """What Overlays.cs's double.TryParse(..., NumberStyles.Float,
    InvariantCulture) accepts, to the precision that matters here: an optional
    sign, digits with an optional point, an optional exponent. Deliberately
    NOT parse_adjust -- that one accepts a leading =, + or x, which on a direct
    sheet is part of the VALUE and not an operator."""
    return bool(_OVERLAY_NUMBER_RE.match((text or '').strip()))


def overlay_key_index(entry):
    """identity tuple -> [row index]. Built once per file, not per cell."""
    idx = {}
    for i, r in enumerate(entry.get('rows') or []):
        idx.setdefault(tuple(r.get('key') or ()), []).append(i)
    return idx


def overlay_find_row(entry, key, rel, index=None):
    """-> the index of the one row whose identity tuple is `key`.

    Refuses on zero matches and on more than one. There is no nearest match and
    no first match: an address that does not resolve to exactly one row is an
    address written against a different version of the file, and writing to a
    guess is the failure this key shape exists to prevent.
    """
    if not isinstance(key, (list, tuple)):
        raise SaveRefused({'summary': '%s: a row key must be a list of its '
                                      'identity cells, got %r' % (rel, key)})
    want = [str(k) for k in key]
    cols = entry.get('identityColumns') or []
    if len(want) != len(cols):
        raise SaveRefused({'summary': '%s: this sheet is keyed by %s (%d '
                                      'cell(s)); the edit sent %d'
                                      % (rel, ', '.join(cols), len(cols),
                                         len(want))})
    if index is None:
        index = overlay_key_index(entry)
    hits = index.get(tuple(want), [])
    if not hits:
        raise SaveRefused({'summary': '%s: no row has %s = %s'
                           % (rel, ', '.join(cols), ', '.join(want)),
                           'detail': 'Nothing was written. Reload the editor: '
                                     'the sheet on disk does not carry the row '
                                     'this edit was written against.'})
    if len(hits) > 1:
        raise SaveRefused({'summary': '%s: %d rows carry %s = %s, so the edit '
                                      'names no single row'
                                      % (rel, len(hits), ', '.join(cols),
                                         ', '.join(want)),
                           'detail': 'Nothing was written. Rows here are '
                                     'addressed by their identity cells, which '
                                     'are unique on all 53 shipped sheets '
                                     '[measured 2026-09-14]; this file is not, '
                                     'and the save refuses rather than picking '
                                     'one of them.'})
    return hits[0]


def overlay_check_cell(entry, ci, value, rel, notes):
    """Grade one proposed cell. Raises SaveRefused, or appends a warning."""
    col = entry['columns'][ci]
    name = col['name']
    if not isinstance(value, str):
        raise SaveRefused({'summary': '%s.%s: a cell is text, got %r'
                           % (rel, name, value)})
    if '\n' in value or '\r' in value:
        raise SaveRefused({'summary': '%s.%s: a cell may not contain a line '
                                      'break -- the plugin reads this file one '
                                      'line at a time' % (rel, name)})
    text = value.strip()
    if text == '':
        return                              # a blank is always legal: see below
    if entry.get('kind') == 'expanded':
        check_adjust_cell(text, rel, name)
        return
    if _overlay_is_number(text):
        return
    if col.get('op') != 'set':
        raise SaveRefused({'summary': '%s.%s: %r is not a number, and this '
                                      'column carries the %s operator'
                                      % (rel, name, value, col.get('op')),
                           'detail': 'Overlays.cs logs "is not a number, so '
                                     'the operator in its header cannot apply" '
                                     'and DROPS the cell -- the save would look '
                                     'like it worked and change nothing. Only a '
                                     'plain-set column takes text.'})
    notes.append('%s.%s: %r is text, not a number. A plain-set column takes '
                 'text (Overlays.cs keeps it as a literal), but NOTHING '
                 'RANGE-CHECKED IT: check_schema.py declares no columns for '
                 'these sheets, so the value is written as typed.'
                 % (rel, name, text))


def apply_overlay_edits(doc, edits, notes):
    """-> {rel: bytes} for every sheet a lever-cell edit names.

    Pure: reads doc.overlay_raw, opens nothing. A sheet with no edit is not in
    the result at all, which is what makes "a save that changes no overlay cell
    leaves every sheet byte-identical" true by construction rather than by a
    comparison that could be wrong.
    """
    out = {}
    for rel, block in sorted((edits.get('overlays') or {}).items()):
        entry = doc.overlays.get(rel)
        if entry is None:
            raise SaveRefused({'summary': 'no schema declares the overlay %r' % rel,
                               'detail': 'Only a sheet some schema names in '
                                         'targets.overlays can be edited. '
                                         'Nothing was written, and no file was '
                                         'created.'})
        ok, why = entry.get('writable'), entry.get('writableWhy')
        if not ok:
            raise SaveRefused({'summary': '%s is not editable' % rel,
                               'detail': why})
        raw = doc.overlay_raw.get(rel)
        if raw is None:
            raise SaveRefused({'summary': '%s: its bytes were not read, so it '
                                          'cannot be edited' % rel,
                               'detail': entry.get('error') or 'no bytes kept'})
        bom = has_bom(raw)
        try:
            text = raw.decode('utf-8-sig')
        except ValueError as e:
            raise SaveRefused({'summary': '%s is not UTF-8: %s' % (rel, e)})
        lines, ends = split_lines_keepends(text)
        sep = entry.get('sep') or ','
        names = [c['name'] for c in entry['columns']]
        index = overlay_key_index(entry)
        spans_of = {}
        moved = []
        for spec in (block.get('cells') or []):
            if not isinstance(spec, dict):
                raise SaveRefused({'summary': '%s: a cell edit is an object '
                                              'with key, column and value; got '
                                              '%r' % (rel, spec)})
            ri = overlay_find_row(entry, spec.get('key'), rel, index)
            name = spec.get('column')
            if name not in names:
                raise SaveRefused({'summary': '%s has no column %r' % (rel, name),
                                   'detail': 'Its columns are: %s'
                                             % ', '.join(n for n in names if n)})
            if names.count(name) > 1:
                raise SaveRefused({'summary': '%s carries %d columns called %r, '
                                              'so the edit names no single one'
                                              % (rel, names.count(name), name)})
            ci = names.index(name)
            if not (entry['editable'][ci] if ci < len(entry['editable']) else False):
                role = (entry['roles'][ci] if ci < len(entry['roles']) else '?')
                raise SaveRefused({
                    'summary': '%s.%s is not editable: it is %s column %d'
                               % (rel, name, 'the key' if ci == 0 else
                                  'an identity' if role == 'identity' else
                                  'a control' if role == 'control' else
                                  'a non-lever', ci),
                    'detail': 'This editor writes lever and override columns '
                              'and nothing else. An identity cell names WHICH '
                              'row a line is about and a control cell (_comment, '
                              '_clone) is not an override; the key column is the '
                              'id Overlays.LoadTable refuses the line without. '
                              'Nothing was written.'})
            overlay_check_cell(entry, ci, spec.get('value'), rel, notes)
            new = csv_render_cell((spec.get('value') or '').strip(), sep)

            li = entry['rows'][ri].get('line')
            if not isinstance(li, int) or li >= len(lines):
                raise SaveRefused({'summary': '%s: row %s has no line on record'
                                   % (rel, spec.get('key'))})
            spans = spans_of.get(li)
            if spans is None:
                spans = spans_of[li] = csv_field_spans(lines[li], sep)
            if spans is None:
                raise SaveRefused({'summary': '%s line %d does not parse as '
                                              'CSV, so no field in it can be '
                                              'replaced in place'
                                              % (rel, li + 1)})
            if ci >= len(spans):
                raise SaveRefused({'summary': '%s line %d has %d field(s); the '
                                              'edit names field %d'
                                              % (rel, li + 1, len(spans), ci + 1)})
            a, b = spans[ci]
            old = lines[li][a:b]
            if old == new:
                continue                 # nothing to move; not an error
            # THE ONE PLACE BYTES CHANGE. Everything outside [a, b) of this one
            # line is carried, including the line's own ending, which lives in
            # `ends` and is never rebuilt.
            lines[li] = lines[li][:a] + new + lines[li][b:]
            spans_of.pop(li, None)         # the line moved; its spans did too
            moved.append('%s.%s [%s] %s -> %s'
                         % (rel, name, ', '.join(str(k) for k in spec['key']),
                            old or '(blank)', new or '(blank)'))

        data = ''.join(l + e for l, e in zip(lines, ends)).encode('utf-8')
        if bom:
            data = b'\xef\xbb\xbf' + data
        out[rel] = data
        for m in moved:
            notes.append(m)
        if not moved:
            notes.append('%s: every cell in the edit already held that value; '
                         'the file is byte-identical and the commit skips it'
                         % rel)
        else:
            notes.append('%s: %d cell(s) moved. NOT VALIDATED AGAINST A SCHEMA '
                         '-- check_schema.py declares no columns for the lever '
                         'sheets, so nothing here range-checked the value or '
                         'its type beyond the cell grammar.' % (rel, len(moved)))
    return out


def coerce_scalar(typ, value, where):
    if typ == 'bool':
        if isinstance(value, bool):
            return value
        raise SaveRefused({'summary': '%s: %r is not a bool' % (where, value)})
    if typ == 'int':
        if isinstance(value, bool):
            raise SaveRefused({'summary': '%s: %r is not an int' % (where, value)})
        if isinstance(value, int):
            return value
        if isinstance(value, float) and value == int(value):
            return int(value)
        if isinstance(value, str) and re.match(r'^[+-]?\d+$', value.strip()):
            return int(value.strip())
        raise SaveRefused({'summary': '%s: %r is not an int' % (where, value)})
    if typ in ('float', 'floatOrNaN'):
        if isinstance(value, bool):
            raise SaveRefused({'summary': '%s: %r is not a number' % (where, value)})
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            try:
                return float(value.strip())
            except ValueError:
                pass
        raise SaveRefused({'summary': '%s: %r is not a number' % (where, value)})
    if typ == 'stringList':
        if isinstance(value, list):
            return [str(v) for v in value]
        if isinstance(value, str):
            return [p.strip() for p in value.split(',') if p.strip()]
        raise SaveRefused({'summary': '%s: %r is not a list' % (where, value)})
    if value is None:
        return ''
    return value if isinstance(value, str) else str(value)


def build_table(field, rows, shape, extras, where):
    """Rows from the browser -> the on-disk shape.

    A cell that arrives as null is an absent key, not a zero. Unknown keys the
    browser never saw are restored from `extras`, keyed by the row id the model
    handed out, so nothing outside the schema is lost.
    """
    cols = {c['name']: c for c in field.get('row', [])}
    order = [c['name'] for c in field.get('row', [])]
    key_col = field.get('keyedBy')
    fmt_declared = dict((c['name'], c.get('format')) for c in field.get('row', []))

    built_rows = []
    for r in rows:
        rid = r.get('id')
        cells = r.get('cells') or {}
        for cname in cells:
            if cname not in cols:
                raise SaveRefused({'summary': '%s: no such column %r' % (where, cname)})
        obj = {}
        for cname in order:
            if cname not in cells:
                continue
            v = cells[cname]
            if v is None:
                continue                      # absent, deliberately
            col = cols[cname]
            v = coerce_scalar(col.get('type', 'string'), v, '%s.%s' % (where, cname))
            if col.get('type') == 'string' and fmt_declared.get(cname) == 'adjust':
                check_adjust_cell(v, where, cname)
            obj[cname] = v
        extra = extras.get(rid) if isinstance(rid, int) else None
        if extra:
            for k, v in extra.items():
                obj.setdefault(k, v)
        built_rows.append((rid, obj))

    if shape == 'object':
        if not key_col:
            raise SaveRefused({'summary': '%s: an object-shaped table needs keyedBy' % where})
        out = {}
        for rid, obj in built_rows:
            k = obj.pop(key_col, None)
            if k is None or str(k).strip() == '':
                raise SaveRefused({'summary': '%s: a row has no %s' % (where, key_col)})
            k = str(k)
            if k in out:
                raise SaveRefused({'summary': '%s: duplicate key %r' % (where, k)})
            out[k] = obj
        return out
    return [obj for _rid, obj in built_rows]


def check_adjust_cell(value, where, col):
    if not isinstance(value, str):
        return
    r = parse_adjust(value)
    if not r['ok']:
        raise SaveRefused({'summary': '%s.%s: %r is not a valid adjustment. '
                                      'Expected blank, =N, +N, -N, xN, *N or a bare number. '
                                      'MissionRewards.cs:405-411 logs an unparseable spec and '
                                      'ignores it, which is a silent no-op.'
                                      % (where, col, value)})


def apply_table_formats(doc, extras_store, model, edits):
    """Server-side grammar check for columns the model marked 'adjust' by
    inference (build_table only enforces columns the schema declares)."""
    for name, block in (edits.get('json') or {}).items():
        for path, spec in (block.get('tables') or {}).items():
            key = '%s|%s' % (name, path)
            tbl = model['tables'].get(key)
            if not tbl:
                continue
            for cname, fmt in tbl['formats'].items():
                if fmt != 'adjust':
                    continue
                for r in (spec.get('rows') or []):
                    v = (r.get('cells') or {}).get(cname)
                    if isinstance(v, str):
                        check_adjust_cell(v, '%s:%s' % (name, path), cname)


# ---------------------------------------------------------------------------
# the save transaction

def stage_and_validate(doc, proposed):
    """Copy everything check_schema reads into a temp dir, overlay the proposed
    bytes, and run check_schema there."""
    staging = tempfile.mkdtemp(prefix='ckf-gui-stage-')
    try:
        for rel in files_check_schema_reads(doc.schemas):
            src = os.path.join(doc.config_dir, rel)
            dst = os.path.join(staging, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            if os.path.exists(src):
                shutil.copy2(src, dst)
        for rel, data in proposed.items():
            dst = os.path.join(staging, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            with open(dst, 'wb') as f:
                f.write(data)
        return run_check_schema(staging)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def fingerprints(config_dir, schemas):
    """A digest per file the GUI reads, so a save can prove it is editing the
    same bytes the browser was shown. Row ids are positional: a file edited on
    disk between load and save would attach preserved unknown keys to the wrong
    row, and nothing downstream would notice."""
    out = {}
    for rel in files_check_schema_reads(schemas):
        p = os.path.join(config_dir, rel)
        try:
            out[rel] = hashlib.sha256(read_bytes(p)).hexdigest()
        except OSError:
            out[rel] = None
    return out


def probe_writable(d):
    """Distinguish 'not there' from 'could not look'. Never assumes."""
    if not d:
        return {'state': 'unset', 'detail': 'no directory chosen yet'}
    if not os.path.isdir(d):
        return {'state': 'missing', 'detail': 'not a directory: %s' % d}
    p = os.path.join(d, PROBE_PREFIX + str(os.getpid()))
    try:
        with open(p, 'wb') as f:
            f.write(b'ckf-gui write probe')
        os.remove(p)
        return {'state': 'ok', 'detail': 'created and removed %s' % os.path.basename(p)}
    except PermissionError as e:
        return {'state': 'denied', 'detail': '%s' % e}
    except OSError as e:
        if e.errno in (errno.EACCES, errno.EPERM, errno.EROFS):
            return {'state': 'denied', 'detail': '%s' % e}
        return {'state': 'error', 'detail': '%s: %s' % (type(e).__name__, e)}


def journal_path(config_dir):
    return os.path.join(config_dir, JOURNAL_NAME)


def recover_journal(config_dir):
    """Finish a save that a crash interrupted between two renames.

    -> {'found': bool, 'completed': [...], 'missing': [...], 'error': str|None}
    """
    jp = journal_path(config_dir)
    if not os.path.exists(jp):
        return {'found': False, 'completed': [], 'missing': [], 'error': None}
    try:
        with open(jp, encoding='utf-8') as f:
            j = json.load(f)
    except Exception as e:
        return {'found': True, 'completed': [], 'missing': [],
                'error': 'journal unreadable: %s' % e}
    completed, missing = [], []
    root = os.path.realpath(config_dir)

    def inside(p):
        rp = os.path.realpath(os.path.dirname(os.path.abspath(p)))
        return rp == root or rp.startswith(root + os.sep)

    try:
        for tmp, final in j.get('renames', []):
            # A journal is a file in a directory the GUI does not own outright.
            # Only renames that stay inside the config directory, and whose two
            # halves share a directory, are followed.
            if not (inside(tmp) and inside(final)):
                missing.append(final)
                continue
            if os.path.dirname(os.path.abspath(tmp)) != os.path.dirname(os.path.abspath(final)):
                missing.append(final)
                continue
            if os.path.exists(tmp):
                os.replace(tmp, final)
                completed.append(final)
            else:
                missing.append(final)      # already renamed, or lost
        os.remove(jp)
    except OSError as e:
        return {'found': True, 'completed': completed, 'missing': missing,
                'error': '%s: %s' % (type(e).__name__, e)}
    return {'found': True, 'completed': completed, 'missing': missing, 'error': None}


def _fsync_dir(d):
    try:
        fd = os.open(d, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def commit(config_dir, proposed, current_bytes, force=False):
    """Write every proposed file in one transaction.

    Phase 1 writes and fsyncs a temporary beside each target.
    Phase 2 commits a journal naming the pending renames.
    Phase 3 runs the renames back to back, with nothing between them.
    Phase 4 removes the journal.

    A crash in phase 1 leaves only temporaries: the config is untouched. A
    crash in phase 3 leaves the journal and the temporaries the renames have
    not reached, which recover_journal() finishes on the next start.
    """
    targets = []
    for rel, data in sorted(proposed.items()):
        if not force and current_bytes.get(rel) == data:
            continue
        targets.append((rel, data))
    if not targets:
        return {'written': [], 'skipped': sorted(proposed.keys())}

    pairs = []
    try:
        for rel, data in targets:
            final = os.path.join(config_dir, rel)
            os.makedirs(os.path.dirname(final), exist_ok=True)
            tmp = final + TMP_SUFFIX + '-' + str(os.getpid())
            with open(tmp, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            pairs.append((tmp, final))
        for tmp, _final in pairs:
            _fsync_dir(os.path.dirname(tmp))
    except OSError:
        for tmp, _final in pairs:
            try:
                os.remove(tmp)
            except OSError:
                pass
        raise

    jp = journal_path(config_dir)
    jtmp = jp + '-' + str(os.getpid())
    with open(jtmp, 'w', encoding='utf-8') as f:
        json.dump({'pid': os.getpid(), 'time': time.time(),
                   'renames': [[t, fi] for t, fi in pairs]}, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(jtmp, jp)
    _fsync_dir(config_dir)

    # Nothing between these but the renames themselves.
    order = mirror_first(pairs, config_dir)
    for tmp, final in order:
        os.replace(tmp, final)

    _fsync_dir(config_dir)
    try:
        os.remove(jp)
    except OSError:
        pass
    return {'written': [rel for rel, _d in targets], 'skipped': []}


def mirror_first(pairs, config_dir):
    """Rename the generated mirror before its source.

    Both orders leave a detectable disagreement if a crash lands between them,
    and the journal is what actually makes the pair recoverable. The mirror
    goes first because it is the machine-owned half: whatever a crash leaves,
    regenerating it from whatever teampl.json then holds converges, and the
    hand-authored source of truth is the last file touched.
    """
    root = os.path.normpath(os.path.abspath(config_dir))

    def rank(pair):
        d = os.path.normpath(os.path.dirname(os.path.abspath(pair[1])))
        return 0 if d != root else 1        # anything under a subdirectory is generated
    return sorted(pairs, key=rank)


# ---------------------------------------------------------------------------
# 3.x -> 4.0 migration
#
# WHAT THIS CONVERTS, AND WHAT IT REFUSES TO CONVERT.
#
# A 3.x install is three files: ckf.hardmode.json (the merged settings
# document), ckf.hardmode.rules.json (287 rules, JSONC) and ckf.hardmode.cfg
# (one key). A 4.0 install is 67 files under ckf.hardmode.d/ plus a 43-key
# .cfg, with BOTH 3.x files gone -- ConfigDoc.BothLayouts refuses to apply any
# rule at all for a launch that finds both layouts, so a half-finished
# migration turns the whole mod off.
#
# THE INVARIANT (design.md section 13, as corrected): a converted install and a
# fresh install produce byte-identical files ONCE THE FOUR DEVIATIONS ARE
# APPLIED DURING CONVERSION. That last clause is the whole thing, and it is a
# different statement from "use the expanders' mapping", because two of the
# four are DELETIONS WITH NO EXPANDER TO REUSE:
#
#   D1  the MonsterTypeModel PowerLevel 11+ ChasingSpeed/AggroSpeed x1.1 sweep
#       -- 1 rule in, NOTHING out. 1,180 rows / 2,360 values revert. No file
#       consumes it; a converter that routes every rule by model writes it to a
#       68th file and reconstructs the balance Phase 5 deleted.
#   D2+D4  the 16 WeaponModel RecoilRate2 x1.8 id ranges -- 16 rules in, the
#       TEN gear-classes.csv rows out, DERIVED FROM THE LIVE PARTITION.
#       Transcribing the ranges re-applies x1.8 to the 30 drone weapons D2
#       removes it from and withholds it from the 10 player ARs D4 adds it to.
#   D3  clampMin ImplantStress 1 on the unscoped ImplantModel rule -- 1 operand
#       in, NOTHING out. It binds on 0 of 198 rows and implants-global.json's
#       own _doc says in so many words that the migrator must not carry it.
#
# A CONVERTER WRITTEN TO "PRESERVE EVERY OPERAND OF EVERY RULE" REINTRODUCES D3
# AND RECONSTRUCTS D1, both silently. Neither is a rule this file forgets to
# copy; each is a rule this file must decline to copy, on purpose, by name.
#
# WHICH MonsterTypeModel THE PARTITION READS. gear-classes.csv's ten rows
# resolve at load as "class N minus the MonsterTypeModel.WeaponTypeId set", and
# that set comes from the POST-OVERLAY ckf.hardmode.d/MonsterTypeModel.csv --
# 405 distinct WeaponTypeId, class 3 = 33 player / 43 enemy [measured,
# 2026-09-14] -- not from sheets/raw/MonsterTypeModel.csv, which gives 208 and
# class 3 = 25/51 and misclassifies eight class-3 player ARs as enemy gear.
# mods/CKFHardMode/GearClasses.cs makes that choice and refuses to emit if the
# file is unreadable; so does this, and it does NOT fall back to the dump.
#
# THE SIX CONSUMABLE TABLES ARE NOT CONVERTED AT ALL. 0 of the 73 ItemModel
# rows are touched by the mod and 0 of the rules reach any of the 194
# consumable-reachable (table, id) pairs (design.md section 13). They are
# written from the expander's declarations, like the eleven implant slot
# tables and the two cyberweapon sheets -- those carry converted VALUES that
# the expanders already declare, and re-deriving them from the rules would be
# a second opinion about numbers scripts/implants.py and scripts/cyberweapons.py
# already own and gate.
#
# KEY ON (table, id), NEVER ON AN id ALONE. Nothing here keys on a bare id: the
# pack router keys on (model, comment prefix), the rule-to-row conversion keys
# on (model, selector value), and the partition keys on (WeaponClass,
# WeaponId). 130 ids are both an EffectId and a MatrixEffectId and 221 are both
# a TalentId and an EffectId, so an id-alone key would merge rows of different
# tables.


class MigrationRefused(Exception):
    """The migration did not run and wrote nothing. Never an empty result."""


MIGRATION_BACKUP_SUFFIX = '.pre-4.0-backup'

# The 3.x files, in the order the report names them.
MIGRATION_INPUTS = ('ckf.hardmode.json', 'ckf.hardmode.rules.json',
                    'ckf.hardmode.cfg')

# The three files a 3.x install already has under ckf.hardmode.d/. They are
# carried across untouched -- design.md section 2's "enemy gear, unchanged, no
# toggle" -- and this file neither derives nor edits them.
MIGRATION_CARRIED = ('ArmorModel.csv', 'WeaponModel.csv', 'MonsterTypeModel.csv')

# Any one of these on disk means the 4.0 layout is already there. Checked
# because ConfigDoc.BothLayouts refuses the launch, so converting into a
# half-migrated directory would leave a state the mod will not start on.
MIGRATION_4X_MARKERS = ('difficulty.json', 'elapse.json', 'fatigue.json',
                        'missions.json', 'rewardcurve.json', 'teampl.json',
                        'powerlevel.json', 'modelrules.json', 'selfcheck.json',
                        'implants-global.json')

MIGRATION_DIR = 'ckf.hardmode.d'

# The "_version" the produced 4.0 layout carries. DECLARED HERE, NOT CARRIED
# ACROSS FROM THE 3.x DOCUMENT.
#
# CORRECTION, 2026-09-15 (Phase 10). This was `version = doc['_version']`: the
# converter stamped every slice it wrote with the stamp of the merged document
# it had just read. That was invisible for as long as the two numbers were
# equal, and both were "1.0.0" from Phase 3 until today. Phase 10 moves
# Defaults.DocVersion to 4.0.0 and the ten live slices with it, while the 3.x
# fixture keeps the "1.0.0" it shipped with -- so carrying the input's stamp
# forward writes a 4.0 layout stamped at the version it was converted FROM.
#
# Two things that breaks, and only one of them is a gate. ConfigDoc.ReportStamps
# compares every slice to Defaults.DocVersion at launch and names the ones
# behind, so every migrating player's first launch would report all ten slices
# behind; and make_release.check_doc_version refuses a build whose slices
# disagree with the C#.
# [measured, 2026-09-15: with Defaults.DocVersion and the live slices both at
# 4.0.0 and this line still reading the input's stamp, section 19c reported
# "58 identical, 10 differ" and its control case "68 of 68" FAILED.]
#
# A LITERAL, NOT A PARSE OF Defaults.cs. mods/CKFHardMode/Defaults.cs is not in
# the PyInstaller bundle -- gui/ckf-config-editor.spec lists gui/, schema/,
# scripts/ and docs/ -- and `--migrate` runs from the frozen exe, so reading it
# here would refuse a migration in the one build a player actually has. The
# case in section 19c reads the C# and asserts the two agree, which is the shape
# make_release.py uses for cs_expected: the constant is declared, and something
# derived somewhere else is what checks it. It is NOT RUN, never PASS, when
# Defaults.cs is absent.
MIGRATION_DOC_VERSION = '4.0.0'

# The plugin version the produced .cfg's BepInEx header is STAMPED with.
# DECLARED HERE, NOT CARRIED ACROSS FROM THE 3.x FILE.
#
# CORRECTION, 2026-09-15 (Phase 10). migration_cfg built the 4.0 .cfg as
# `head = raw_cfg` plus an appended [Slices] block, so the produced file
# inherited the 3.x fixture's own header line -- "## Settings file was created
# by plugin CKF Hard Mode v1.0.0". That was invisible for as long as the live
# .cfg carried the same line, and it did until David relaunched on 4.0.0 and
# BepInEx rewrote the live header to v4.0.0. Nothing about the converter
# changed; a latent assertion went false.
# [measured 2026-09-15: with this stamp not applied, section 19c reported
# "67 identical, 1 differ" -- ckf.hardmode.cfg, 3238 bytes on both sides -- and
# four cases FAILED, including the control case. Reverting the live header's
# one version token to v1.0.0 turned the same run green, which is what
# identified the single differing line.]
#
# It is a release gate and not only a selftest. make_release.build runs
# serve.py --selftest against the snapshot it is about to zip, and that
# snapshot's .cfg is release/ckf.hardmode.cfg.in rendered with @VERSION@ ->
# the real plugin version, so a migrator that stamps the input's version
# refuses the build the same way.
#
# A LITERAL, NOT A PARSE OF Plugin.cs, for the same reason
# MIGRATION_DOC_VERSION is one: mods/CKFHardMode/Plugin.cs is not in the
# PyInstaller bundle -- gui/ckf-config-editor.spec's `datas` lists gui/,
# schema/, scripts/ and docs/, and no mods/ entry [measured 2026-09-15] -- and
# `--migrate` runs from the frozen exe, so reading it here would refuse a
# migration in the one build a player actually has. The case in section 19c
# reads the C# and asserts the two agree. It is NOT RUN, never PASS, when
# Plugin.cs is absent.
MIGRATION_PLUGIN_VERSION = '4.0.0'

# The BepInEx header line, as BepInEx itself writes it: the plugin name, then
# " v" and the version. Anchored to the WHOLE first line, so a line that only
# contains the phrase does not match. Group 1 is everything up to and including
# the "v", group 2 the version token, group 3 any trailing whitespace -- the
# rewrite replaces group 2 and nothing else, which is why the plugin name and
# the line's own ending survive untouched.
_MIGRATION_CFG_HEADER = re.compile(
    rb'^(## Settings file was created by plugin .+ v)'
    rb'([0-9][0-9A-Za-z.+-]*)([ \t]*)$')

MIGRATION_POINTER_FILE = 'MonsterTypeModel.csv'
MIGRATION_POINTER_COLUMN = 'WeaponTypeId'

# The id column each converted model is selected on. Asserted, never inferred:
# a model whose rules arrive and whose id column is not here is a refusal.
MIGRATION_ID_COLUMN = {
    'EffectModel': 'EffectId',
    'JobNodeModel': 'JobNodeId',
    'TalentModel': 'TalentId',
    'MatrixEffectModel': 'MatrixEffectId',
    'RuleModel': 'RuleId',
}

# The eleven talent packs, by the prefix their rules' comments carry. Nothing
# in the game data names a pack, so this is the routing key and a comment
# whose prefix is not here is NOT routed to a default -- it falls to the
# disposition table below.
MIGRATION_PACKS = ('sol', 'wm', 'sn', 'sc', 'vg', 'hkr', 'gs', 'aex', 'ck',
                   'cs', 'wg')
MIGRATION_PREFIX_PACK = dict((p.upper(), p) for p in MIGRATION_PACKS)

# Anchored at the start of the comment. Seventeen WeaponModel rules carry a
# 'CW /' token in the MIDDLE of their comment; an unanchored search would route
# them by it.
MIGRATION_PREFIX_RE = re.compile(r'^([A-Za-z0-9_\-]+)\s*/')

# RuleModel is 76 rows, ids 1-76 contiguous (design.md section 9).
MIGRATION_RULEMODEL_ROWS = 76

# Every model whose rules are NOT pack rules needs a NAMED destination.
# Routing an unrecognised rule to a default file silently is the failure this
# table exists to make impossible.
#
#   model             what happens to its rules             why
MIGRATION_DISPOSITION = {
    'RuleModel': ('convert', 'RuleModel.csv'),
    'WeaponModel': ('declared', 'the 16 RecoilRate2 ranges become gear-classes.csv '
                                '(D2+D4); the 16 exact laser rules and the one '
                                '25000-25015 SpecialRule range are already the two '
                                'cyberweapons-*.csv sheets\' rows'),
    'TalentModel': ('declared', 'the 5 CW / talent rules are already the two '
                                'cyberweapons-*.csv sheets\' rows'),
    'EffectModel': ('declared', 'the 9 implant-effect rules are already '
                                'implants-slot08.csv\'s rows'),
    'ImplantModel': ('deviation', 'D3 -- the three multipliers become '
                                  'implants-global.json; clampMin ImplantStress 1 '
                                  'is NOT carried across'),
    'MonsterTypeModel': ('deviation', 'D1 -- the PowerLevel 11+ sweep converts to '
                                      'NOTHING'),
}

# THE FOUR SANCTIONED DEVIATIONS, as this file applies them. proposal.md's
# non-goal is that every value shipping today ships after this change; these
# four are the whole of the exception list, and each is a POSITIVE assertion
# here rather than an omission.
MIGRATION_DEVIATIONS = ('D1', 'D2', 'D3', 'D4')

# D3's operand, named so that carrying it across is a change to this line
# rather than a change to a loop.
D3_OPERAND = ('clampMin', 'ImplantStress')
# D1's rule, likewise.
D1_MODEL = 'MonsterTypeModel'

# gear-classes.csv's row comment for a class with no live mode-2 column states
# the class's PLAYER ROW COUNT. That number comes out of the partition, so it
# is the byte-level witness that the post-overlay pointer file was the one
# read: reading sheets/raw instead moves four of the six counts (61->35,
# 25->15, 22->25, 33->25) [measured, 2026-09-14].
MIGRATION_ROWCOUNT_RE = re.compile(r'on all (\d+) player rows')

# WHERE BYTE-IDENTITY DOES NOT HOLD TODAY, AND EXACTLY HOW FAR IT MISSES.
#
# SUPERSEDED, 2026-09-14, SAME DAY. The heading above and everything under it
# down to the next dated block described three files that did not convert
# byte-identically. THEY DO NOW: 68 of 68. The text is kept, not deleted,
# because it is the record of a real defect and of the one instrument that
# could see it.
#
# WHAT IT SAID, AND IT WAS RIGHT WHEN IT SAID IT:
#
#   scripts/implants.py derives each slot table's EffectModel columns from
#   `dump.eff_cols`, which is every column of sheets/raw/EffectModel.csv. It
#   had a declared text-exclusion list for ImplantModel columns (IMPLANT_TEXT)
#   and NONE for EffectModel columns. The dump was re-taken on 2026-09-14 and
#   EffectModel went 74 -> 89 columns (scripts/consumables.py says so in its own
#   header, and handled the same columns by declaring them 'presentation'). One
#   of the new columns is `IconAsset`, an art asset name. It is non-zero and
#   varies across the effect rows of slots 1, 3 and 8, so implants.py carried it
#   into those three tables; the shipping files were written before the re-dump
#   and do not have it.
#
#   MEASURED, 2026-09-14: the divergence was EXACTLY one column and nothing
#   else -- 1,130 bytes over three files (5,859 -> 6,135; 9,854 -> 10,269;
#   11,486 -> 11,925). Removing `IconAsset` from the generated header, the one
#   blank cell it added to every row, and the `; IconAsset <value>` fragment it
#   added to every row's `Shipped:` comment made all three byte-identical.
#
# WHAT FIXED IT. scripts/implants.py gained EFFECT_PRESENTATION -- IconAsset,
# VFX, ManualEffectName, OwnerEntityId, isInit, effectsSet, HasInitSpecialCode
# -- the EffectModel equivalent of IMPLANT_TEXT, and columns_for() skips them.
# No shipped byte moved: the three files never carried them.
#
# WHY THIS MATTERS BEYOND THE THREE FILES. Nothing else in the repository
# compares BUILT BYTES against DISK BYTES. implants.py --check compares
# expansion semantics over sheets it builds itself; check_schema.py declares no
# columns for these files; the schemas name the files and not their headers. So
# the dump moving under a generator was invisible, and the same instability had
# already taken a gate down once on the owner's machine. That is the reason the
# successor assertion below is a live tripwire and not a retired comment.

# The record of the closed divergence, kept so the three per-file cases in the
# selftest can name what they used to measure. EMPTY IS THE ANSWER TODAY, and
# the selftest asserts the difference set equals it rather than reading its
# emptiness as agreement.
MIGRATION_CLOSED_DIVERGENCES = {
    'ckf.hardmode.d/implants-slot01.csv': ('IconAsset', 'EffectModel'),
    'ckf.hardmode.d/implants-slot03.csv': ('IconAsset', 'EffectModel'),
    'ckf.hardmode.d/implants-slot08.csv': ('IconAsset', 'EffectModel'),
}
MIGRATION_DIVERGENCES_CLOSED_ON = '2026-09-14'
MIGRATION_DIVERGENCES_CLOSED_BY = 'scripts/implants.py EFFECT_PRESENTATION'

# The layout's shape, asserted; its SIZE is measured on both sides instead.
#
# 68 is a count of files and it is declared: a file the conversion silently
# never produced is a missing key, not an absence nothing looked for.
#
# THE BYTE TOTAL IS DELIBERATELY NOT DECLARED. It moved today -- 586,634 ->
# 585,504 -- when a generator stopped carrying a column, and it moves again
# every time the game dump does. A literal there is a case that fails for the
# wrong reason and gets re-typed until nobody reads it. What the case actually
# has to prove is that the comparison is over a REAL layout and not an empty
# directory, so what is declared is a FLOOR, and the exact total is measured on
# BOTH sides and required to agree -- which is a stronger statement than any
# literal, and one that cannot be typed in wrong.
MIGRATION_EXPECTED_FILES = 68
MIGRATION_MIN_BYTES = 500000

# The eight 3.x sections whose TOP-LEVEL "enabled" is a retired subsystem gate.
#
# In 3.x each section carried its own gate. In 4.0 the gate is [Slices].<Name>
# in ckf.hardmode.cfg, because a gate cannot live inside the file it gates
# (design.md section 3). Until 2026-09-15 this conversion carried the 3.x
# section body across verbatim and the retired key came with it, so every
# migrated install was born with eight keys no schema declares and the editor
# opened on a banner naming all eight.
#
# THE EIGHT ARE NAMED, NOT FOUND. A walk for any key called "enabled" would
# also take elapse.json's credits.enabled and stress.enabled and fatigue.json's
# woundResist.enabled, none of which are retired -- Elapse.cs and Fatigue.cs say
# so in the same comments that retire the top-level one: "They gate blocks
# inside this subsystem rather than the subsystem, so they are settings."
# woundResist.enabled is additionally a DECLARED FIELD of fatigue.schema.json
# (in: json, bool, "Wound Resist mitigation"). All three live one level down, so
# only a TOP-LEVEL pop on a NAMED section can tell them apart, and this is that
# list. [measured, the three keys are still on disk after this change,
# 2026-09-15]
#
# "difficulty" is absent on purpose: it never carried the key, so an "enabled"
# appearing at its top level is a stray and is carried through to be reported
# as one -- the same reading ConfigDoc.cs's Declared table takes.
#
# The C# side is unchanged and stays that way. Every one of these eight
# subsystems still parses the key into a `bool? RetiredEnabled` and still hands
# it to Slices.ReportRetiredGate, because a player who upgrades a 3.x install
# by hand still has it on disk and must get that warning rather than a
# stray-key Error. [measured, mods/CKFHardMode/{Elapse,Fatigue,MissionRewards,
# ModelRules,PowerLevelCap,Progression,RewardCurve,SelfCheck}.cs, 2026-09-15]
MIGRATION_RETIRED_GATE_SECTIONS = frozenset((
    'elapse', 'fatigue', 'missions', 'modelrules',
    'powerlevel', 'rewardcurve', 'selfcheck', 'teampl',
))
MIGRATION_RETIRED_GATE_KEY = 'enabled'


def migration_divergence_is_one_column(*_a, **_k):
    """RETIRED, 2026-09-14. IT LOST ITS SUBJECT, NOT ITS CORRECTNESS.

    It answered "is `new_bytes` `live_bytes` with exactly one extra column?",
    and on 2026-09-14 it answered True for all three implants-slot tables over
    1,130 bytes -- which is what bounded that divergence to EffectModel's
    IconAsset and nothing else. scripts/implants.py then gained
    EFFECT_PRESENTATION and the divergence is gone.

    IT IS NOT LEFT CALLABLE. With the column gone it would return False from
    its first guard -- `column not in new_rows[0]` -- and a case reading that
    False as "no divergence" would be green over a subject that does not
    exist: an instrument agreeing with nothing, which is the exact shape this
    repository keeps finding (AGENTS.md section 3). So it raises, the way
    scripts/rules_to_overlays.py exits 1, and the selftest asserts the raise.

    WHAT REPLACED IT: migration_presentation_columns() below. That is a LIVE
    tripwire rather than a retired comment -- it asserts that every name
    scripts/implants.py declares presentation-only is present in the dump (so
    there is something to exclude) and appears in NONE of the generated overlay
    headers (so the exclusion is working). It fires if the exclusion is ever
    removed, and it fires on a header column the next re-dump adds that slips
    through, which is the class of defect the original found.
    """
    raise RuntimeError(
        'migration_divergence_is_one_column is RETIRED (%s, closed by %s). '
        'The one-column divergence it measured no longer exists, so it would '
        'answer False over an absent subject. Use '
        'migration_presentation_columns() instead.'
        % (MIGRATION_DIVERGENCES_CLOSED_ON, MIGRATION_DIVERGENCES_CLOSED_BY))


def migration_presentation_columns(files):
    """-> (declared, in_dump, headers_scanned, hits).

    The successor tripwire. `declared` is scripts/implants.py's own
    EFFECT_PRESENTATION -- asset paths, display strings and runtime instance
    state that appeared in the EffectModel dump on 2026-09-14 and are not
    levers. `in_dump` is how many of them the dump header actually carries: a
    name that is NOT there has nothing to exclude, and reporting 0 hits over 0
    reachable names would be agreement with nothing. `hits` is every
    (file, header cell) in the produced layout naming one, operator suffix
    stripped, and the expected answer is none.
    """
    declared = list(_implants.EFFECT_PRESENTATION)
    dump_cols = set(_implants.Dump(migration_dump_dir()).eff_cols)
    in_dump = [c for c in declared if c in dump_cols]
    scanned, hits = 0, []
    for rel in sorted(files):
        if not rel.endswith('.csv'):
            continue
        header = next(csv.reader(io.StringIO(files[rel].decode('utf-8'))), [])
        scanned += 1
        for cellname in header:
            if cellname.rstrip('*+><') in declared:
                hits.append('%s %s' % (rel, cellname))
    return declared, in_dump, scanned, hits


# FAULT INJECTION. Set by --selftest only, never by any other path. Every hook
# is in the conversion, because a fault injected into the FIXTURE would move
# both sides of the comparison equally and stay green.
MIGRATION_FAULT = None
MIGRATION_FAULTS = (
    ('drop-section', 'one of the nine settings sections never reaches a file'),
    ('range-short', 'RuleModel.csv is built one id short (1-75, not 1-76)'),
    ('cfg-key-dropped', 'the 3.x [General] block is rebuilt from defaults '
                        'instead of carried across'),
    ('backup-clobber', 'an existing .pre-4.0-backup is overwritten'),
    ('d1-reconstructed', 'the MonsterTypeModel PL 11+ sweep is kept as a rules '
                         '.json under ckf.hardmode.d, which Overlays.Load reads '
                         'as rules -- what a "preserve every operand of every '
                         'rule" converter does with a range selector'),
    ('d3-carried', 'clampMin ImplantStress 1 is carried into '
                   'implants-global.json as a fourth number'),
    ('shipped-monstertype', 'the partition reads sheets/raw/MonsterTypeModel.csv '
                            'instead of the post-overlay file'),
)


def _mfault(name):
    return MIGRATION_FAULT == name


# =====================================================================
# SECTION 19 IS RETIRED FROM THE DEFAULT SUITE. David's ruling, 2026-09-15.
# =====================================================================
#
# THE RULING, VERBATIM:
#
#     "The migration check was only to make sure nothing was lost when
#     building the new version here. Players will simply download a new zip
#     and overwrite everything, inheriting whatever tuning I've decided upon.
#     They don't need to migrate their files and migration is no longer
#     important. Any further refactors will share this feature: Migration for
#     me but not for end users."
#
# WHAT THE BLOCK IS. Section 19 of selftest() converts the frozen 3.x install
# in tests/fixture-3.0.0/ into the 4.0 slice layout and compares the result,
# byte for byte, against the LIVE 4.0 config --selftest was pointed at. 67
# cases: the fixture's own shape, which MonsterTypeModel the partition reads,
# two version stamps read out of the C#, the conversion and its 68-file
# comparison, the directory afterwards, the four sanctioned deviations, the
# .cfg, five refusals and seven injected faults.
#
# WHAT IT CAUGHT, AND THIS IS WHY IT IS RETIRED RATHER THAN DELETED. Two real
# defects, both of which reached a player-facing artefact:
#
#   * the "_version" stamp. The conversion carried the 3.x document's stamp
#     forward, so a migrated install was born reporting all ten slices behind.
#     Closed by MIGRATION_DOC_VERSION, checked against Defaults.DocVersion.
#   * the .cfg header stamp. The conversion carried the 3.x header byte for
#     byte, so a converted ckf.hardmode.cfg announced the version it was
#     converted FROM. Closed by migration_cfg_stamp_header and
#     MIGRATION_PLUGIN_VERSION, checked against Plugin.PluginVersion.
#
# WHY ITS PREMISE LAPSED. The comparison's premise is "a converted install and
# a fresh install produce byte-identical files". That held only while the live
# config WAS the shipped defaults. It is not any more and never will be again:
# the live BepInEx\config is David's tuning bench and he edits it daily. Every
# edit to a file the conversion authors puts the comparison red -- on
# 2026-09-15 two editor saves, ckf.hardmode.d/cyberweapons-lasers.csv and
# ckf.hardmode.d/fatigue.json, took it to "66 identical, 2 differ" and it
# cannot come back on its own. And scripts/make_release.py runs
# `serve.py --selftest` as the gate before it writes any zip, so a permanently
# red block means the release cannot be cut WHILE HE HAS TUNING, which is the
# exact opposite of what the instrument is for.
#
# THIS IS NOT A PAPERED-OVER DIVERGENCE, AND SAYING SO PRECISELY MATTERS.
# MIGRATION_CLOSED_DIVERGENCES is NOT touched by this retirement and the two
# differing files were NOT added to it. Note what that dict is and is not: it
# holds three entries, the three implants-slot tables whose divergence was
# CLOSED on 2026-09-14, and it is a RECORD, not a tolerance list -- _mig_diff
# filters nothing through it and the selftest asserts the measured difference
# set is EMPTY rather than that it equals this dict. So the set of TOLERATED
# divergences is empty and stays empty. That emptiness is what caught the .cfg
# header stamp, and an entry added to buy a green would spend exactly the thing
# that made the instrument worth keeping. What is retired is the block's place
# in the DEFAULT suite, not the block.
#
# WHAT STILL RUNS. Everything. `serve.py --selftest --migration` runs all 67
# cases unchanged, including _mfault / MIGRATION_FAULTS and the fault
# injections. build_migration, run_migration, migration_cfg, the --migrate CLI
# path and tests/fixture-3.0.0/ are all untouched: the migrator is David's own
# tool and he must be able to exercise it deliberately. Only the DEFAULT
# suite's gating is gone.
#
# HOW THE DEFAULT SUITE REPORTS IT. NOT RUN, by name, twelve entries -- one per
# named subsection -- through _T.skip, so they appear inline AND in the report
# tail. Never PASS, and never absent. A reader of the default output can tell
# "this passed" from "this was retired by a ruling on 2026-09-15" without
# opening this file. AGENTS.md section 3: an instrument's silence is not
# evidence, and a retired check must SAY it is not running.
MIGRATION_RETIRED_ON = '2026-09-15'
MIGRATION_RETIRED_BY = "David's ruling"
MIGRATION_RETIRED_FLAG = '--migration'
# One line, because it is repeated once per case in the report tail and the
# full reason is printed once, in full, by migration_report_retired above it.
# It still has to carry the three things that distinguish a retirement from a
# pass on its own: that it is retired, WHO ruled and WHEN, and how to run it.
MIGRATION_RETIRED_WHY = (
    'RETIRED from the default suite, %s %s. Run it with '
    '`serve.py --selftest %s --config <dir>`.'
    % (MIGRATION_RETIRED_BY, MIGRATION_RETIRED_ON, MIGRATION_RETIRED_FLAG))

# The twelve named subsections of section 19, in the order they run, each with
# what it measures. NAMED, NOT COUNTED: a reader of the default output has to
# be able to see WHICH coverage is not running, and "67 migration cases" does
# not say that. The list is the one thing that has to move if a subsection is
# added to or removed from section 19.
MIGRATION_RETIRED_CASES = (
    ('19a: the frozen 3.x fixture is the artefact design.md section 13 '
     'describes -- 82,478 bytes, 287 rules, 263 exact'),
    ('19b: which MonsterTypeModel the gear partition reads (post-overlay, not '
     'sheets/raw), and the two version stamps read out of the C#'),
    ('19c: the conversion runs and all 68 produced files are byte-identical '
     'to the live 4.0 layout, sized on both sides'),
    ('19d: the converted directory afterwards -- both originals renamed to '
     '.pre-4.0-backup, 67 slice files, not in ConfigDoc.BothLayouts state'),
    ('19e: D1 -- the MonsterTypeModel PL 11+ sweep converts to nothing, '
     'measured positively rather than inferred from an absence'),
    ('19f: D2 + D4 -- the 16 WeaponModel RecoilRate2 ranges reach '
     'gear-classes.csv'),
    ('19g: D3 -- the unscoped ImplantModel clampMin is dropped, not carried '
     'into implants-global.json'),
    ('19h: the converted ckf.hardmode.cfg -- 1 key in, 43 keys out, and the '
     'header stamped with Plugin.PluginVersion'),
    ('19i: a .cfg value the player actually set is carried across, not reset '
     'to the shipped default'),
    ('19i-2: a .cfg header line this converter cannot read is a REFUSAL, not '
     'a rewrite and not an append'),
    ('19j: the five refusals -- missing input, both layouts, existing backup, '
     'unreadable MonsterTypeModel, blank WeaponTypeId -- each writing nothing'),
    ('19k: fault injection -- a control run, then seven faults each of which '
     'must go red'),
)


def migration_report_retired(t):
    """Report section 19 as a RECORDED NON-RUN on the default suite.

    Prints the reason in full once, then one _T.skip per named subsection so
    that every case lands in the report tail too. Nothing here can pass: skip()
    touches neither t.passed nor t.failed, so a suite that reaches this cannot
    be read as having covered the migrator.
    """
    for line in (
        'NOT RUN. This whole block is RETIRED from the default suite.',
        '%s, %s. The %d cases below are reported by name and never pass.'
        % (MIGRATION_RETIRED_BY, MIGRATION_RETIRED_ON,
           len(MIGRATION_RETIRED_CASES)),
        '',
        'WHY. The block converts the frozen tests/fixture-3.0.0 and compares',
        'the result byte for byte against the LIVE config this run was pointed',
        'at. That premise -- "a converted install and a fresh install produce',
        'byte-identical files" -- held only while the live config WAS the',
        'shipped defaults. It is a tuning bench now, so every tuning edit to a',
        'file the migrator authors puts this red permanently. And',
        'scripts/make_release.py gates every zip on this suite, so the release',
        'could not be cut while there was tuning on disk.',
        '',
        'THIS IS NOT A PAPERED-OVER DIVERGENCE. The set of TOLERATED',
        'divergences is empty and stays empty: MIGRATION_CLOSED_DIVERGENCES is',
        'a RECORD of three already-closed ones, nothing is filtered through',
        'it, and the differing files were NOT added to it.',
        '',
        'THE MIGRATOR ITSELF IS NOT RETIRED AND NOT DELETED. build_migration,',
        'run_migration, migration_cfg, MIGRATION_FAULTS, tests/fixture-3.0.0/',
        'and the --migrate CLI path are all unchanged. Run every case below,',
        'unchanged, with:',
        '',
        '    python gui/serve.py --selftest %s --config <dir>'
        % MIGRATION_RETIRED_FLAG,
        '',
        'Skipped deliberately, not failed. A recorded non-run, not silence.',
    ):
        print(('      ' + line) if line else '')
    for name in MIGRATION_RETIRED_CASES:
        t.skip(name, MIGRATION_RETIRED_WHY)


def migration_strip_jsonc(text):
    """// comments and trailing commas out, string literals respected.

    A regex over the whole text is wrong the moment a comment field holds '//'
    or ', }'. Deliberately a local copy rather than an import: an instrument
    assembled out of the module under test cannot see that module fail
    (AGENTS.md section 3), and the retired scripts/rules_to_overlays.py is not
    callable.
    """
    out = []
    i, n, in_str = 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == '\\' and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == '/' and i + 1 < n and text[i + 1] == '/':
            while i < n and text[i] != '\n':
                i += 1
            continue
        out.append(c)
        i += 1
    s = ''.join(out)
    res = []
    i, n, in_str = 0, len(s), False
    while i < n:
        c = s[i]
        if in_str:
            res.append(c)
            if c == '\\' and i + 1 < n:
                res.append(s[i + 1])
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            res.append(c)
            i += 1
            continue
        if c == ',':
            j = i + 1
            while j < n and s[j].isspace():
                j += 1
            if j < n and s[j] in '}]':
                i += 1
                continue
        res.append(c)
        i += 1
    return ''.join(res)


def _mig_fmt(v):
    if isinstance(v, bool):
        return 'true' if v else 'false'
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v) if v != int(v) else str(int(v))
    return str(v)


def _mig_cell(s):
    """RFC-4180-ish, matching Overlays.SplitLine: a field is quoted only when
    the quote is the FIRST character, so nothing here pads a cell."""
    if s is None:
        return ''
    if any(ch in s for ch in ',"\r\n') or s != s.strip():
        return '"' + s.replace('"', '""') + '"'
    return s


def _mig_csv(header, rows):
    buf = io.StringIO()
    buf.write(','.join(_mig_cell(c) for c in header))
    buf.write('\n')
    for r in rows:
        buf.write(','.join(_mig_cell(c) for c in r))
        buf.write('\n')
    return buf.getvalue()


def migration_prefix(rule):
    m = MIGRATION_PREFIX_RE.match(rule.get('comment') or '')
    return m.group(1) if m else None


def migration_selector(rule):
    if 'where' in rule:
        return 'exact'
    if 'whereMin' in rule or 'whereMax' in rule:
        return 'range'
    return 'unscoped'


# implants-global.json's _doc, which is DEFAULTS CONTENT, not converted content.
#
# The file is new in 4.0: a 3.x install has no copy of this prose to carry
# across, and no schema, dump or expander holds it either -- it exists only in
# the file the release ships. So the migrator carries it, and the invariant in
# design.md section 13 is why: without it a converted install and a fresh
# install differ by one key, on a file whose own text is the clearest statement
# anywhere that D3 must not be carried across.
#
# It is a LITERAL, transcribed from the shipping file on 2026-09-14, and it is
# the only prose block in this migration that is not derived from something.
# Everything else here is built from the player's own three files, from the
# schemas, or from the four expander modules.
IMPLANTS_GLOBAL_DOC = [
    "The blanket implant multipliers, transcribed from the ONE unscoped",
    "ImplantModel rule in ckf.hardmode.rules.json: Cost *0.5, InstallTime *0.5,",
    "ImplantStress *3. Three scalars, so a form, not a table (design.md",
    "section 7).",
    "",
    "WHAT THESE APPLY TO: EVERY IMPLANT ROW, INCLUDING ROWS NO TABLE SHOWS.",
    "",
    "The source rule carries no \"where\" clause, so it reaches ALL 198",
    "ImplantModel rows -- the 178 in character slots 1-11 that the eleven",
    "implants-slotNN.csv tables show, AND THE 20 DRONE MODULES in slots 100-107",
    "that no table shows and the editor does not render. That reach is ACCEPTED,",
    "NOT A BUG AND NOT TO BE FIXED. Scoping it to \"ImplantSlot <= 11\" would",
    "change Cost, InstallTime and ImplantStress on 20 rows that ship today, which",
    "is a balance change on rows nobody can play with yet; proposal.md's",
    "non-goals allow exactly four balance changes and all four are spoken for.",
    "Drones are not in the game yet, per David, and the question is revisited",
    "when they ship (design.md section 7).",
    "",
    "CORRECTION: THERE ARE THREE NUMBERS HERE, NOT FOUR.",
    "",
    "This file's own _doc used to describe \"the four numbers\" and list",
    "clampMin ImplantStress 1 among them. The floor was REMOVED per David",
    "because it PROVABLY NEVER BINDS: ImplantStress ships as 1 on 197 rows",
    "(1 -> 3) and 5 on Quantum Rider (5 -> 15), so nothing lands below 1 for the",
    "clamp to lift [measured, sheets\\raw 2026-09-12; re-derived on every run by",
    "scripts\\implants.py's D-CLAMP]. Dropping it moves no value. PHASE 9'S",
    "MIGRATOR MUST NOT CARRY IT ACROSS.",
    "",
    "CORRECTION TO THE CORRECTION, 2026-09-14 (Phase 9): THE SPEC SENTENCE HAS",
    "ALREADY CHANGED, AND THIS PARAGRAPH WAS THE LAST PLACE STILL SAYING IT HAD",
    "NOT.",
    "",
    "The paragraph above used to go on: \"and specs\\lever-sheets\\spec.md still",
    "says the global block 'holds Cost, InstallTime, ImplantStress and the",
    "stress floor as four fields' ... and the spec sentence is what should",
    "change, not this file.\" IT DOES NOT SAY THAT AND HAS NOT SINCE PHASE 3.",
    "Under \"Scenario: The blanket implant settings are a form\" the spec reads",
    "\"THEN it holds Cost, InstallTime and ImplantStress as three fields\", and",
    "its next clause is \"AND it does NOT hold the stress floor, because that",
    "clamp provably never binds\" -- three fields, counted in the spec itself",
    "[measured 2026-09-14, specs\\lever-sheets\\spec.md]. So all three artefacts",
    "say three: the spec, schema\\implantsglobal.schema.json (corrected the same",
    "day, in its own voice) and this file.",
    "",
    "This was flagged before Phase 8 and stayed open through it. It is corrected",
    "in writing rather than quietly deleted because a claim ABOUT ANOTHER",
    "DOCUMENT is the kind that goes stale in silence: nothing recompiles it, no",
    "gate reads it, and the document it describes can be fixed without anyone",
    "coming back here. This sidecar is transcribed verbatim into gui\\serve.py as",
    "IMPLANTS_GLOBAL_DOC, so the two move together or the migration's",
    "68-of-68 byte-identity case goes red.",
    "",
    "THESE NUMBERS ARE LIVE. EDITING THIS FILE NOW CHANGES THE GAME.",
    "",
    "CORRECTION, 2026-09-14 (Phase 9). This heading used to read \"NOTHING",
    "APPLIES THESE NUMBERS YET, AND THE REASON CHANGED IN PHASE 7\", and under it",
    "this file said the expander \"REFUSES to emit from this file, on purpose,",
    "saying so by name on every launch (Implants.RefuseGlobal)\" and that \"the",
    "implant multipliers in effect this launch are the ones in",
    "ckf.hardmode.rules.json, unchanged\". Both were true when written and are",
    "false now. THERE IS NO RefuseGlobal: the method is Implants.ExpandGlobal",
    "(mods\\CKFHardMode\\Implants.cs) and it emits the one unscoped ImplantModel",
    "rule these three values describe [measured 2026-09-14, read off",
    "Implants.cs, which keeps the old name's reasoning in its header rather than",
    "deleting it]. ckf.hardmode.rules.json is no longer in the config directory",
    "[measured 2026-09-14, the live directory].",
    "",
    "WHY BOTH HALVES HAD TO SHIP IN ONE COMMIT. The operation is a MULTIPLY, and",
    "multiply is not idempotent. A live expander beside the old rule would apply",
    "these numbers ON TOP OF it: Cost and InstallTime would land on x0.25",
    "instead of x0.5 and ImplantStress on x9 instead of x3, across all 198 rows.",
    "So deleting the rule and replacing the refusal are one change, and either",
    "half alone is a balance change. That is the wall Phase 5 hit, and the",
    "reason the nine EffectModel CritMultiBase rules in implants-slot08.csv",
    "could ship a phase earlier than these three: `set` IS idempotent.",
    "",
    "ConfigDoc reads this file, stamps it and runs the stray-key guard over it;",
    "Overlays does not parse it as rules and says so by name.",
]



class Migration(object):
    """What a migration WOULD do, before anything is written.

    `files` is every file the 4.0 layout holds, as bytes -- not a diff. The
    comparison the selftest runs is against this whole set, so a file the
    conversion silently never produced is a missing key rather than an absence
    nothing looked for.
    """

    def __init__(self, config_dir):
        self.config_dir = config_dir
        self.files = {}         # rel -> bytes
        self.renames = []       # (rel src, rel dst)
        self.deletes = []       # rel
        self.notes = []
        self.measured = {}
        self.source = {}        # rel -> 'converted' | 'derived' | 'carried'

    def put(self, rel, data, how):
        self.files[rel] = data
        self.source[rel] = how

    def bytes_total(self):
        return sum(len(v) for v in self.files.values())


def migration_dump_dir():
    """sheets/raw -- the dumped game tables the lever sheets are built over.

    REFUSED rather than defaulted if it is not there: the eleven implant slot
    tables, the two cyberweapon sheets, the six consumable sheets and
    RuleModel.csv's untouched-row comments are all built over it, and a
    migration that could not read it would write a layout missing most of its
    rows and say nothing.
    """
    d = os.path.join(REPO, 'sheets', 'raw')
    if not os.path.isdir(d):
        raise MigrationRefused(
            'the dumped game tables are not on disk at %s.\n'
            'This is a refusal, not an empty conversion: the implant, '
            'cyberweapon, consumable and RuleModel files are built over that '
            'dump, and writing them without it would produce a layout whose '
            'rows are missing rather than blank.' % d)
    return d


def _migration_expanders():
    """The four expander modules, or a refusal naming the ones that are not
    importable. A build without scripts/ on the path converts NOTHING here --
    it does not quietly ship a layout with 19 files missing."""
    missing = []
    for name, mod in (('scripts/gear_classes.py', _gear_classes if 'gear_classes' in _sheet_sources else None),
                      ('scripts/cyberweapons.py', _cyberweapons if 'cyberweapons' in _sheet_sources else None),
                      ('scripts/implants.py', _implants if 'implants' in _sheet_sources else None),
                      ('scripts/consumables.py', _consumables if 'consumables' in _sheet_sources else None)):
        if mod is None:
            missing.append(name)
    if missing:
        raise MigrationRefused(
            'these expander modules are not importable, so the sheets they own '
            'cannot be written: %s.\n'
            'Import error: %s\n'
            'Refusing rather than emitting a layout without them.'
            % (', '.join(missing), SHEET_SOURCE_ERROR or '(none recorded)'))
    return _gear_classes, _cyberweapons, _implants, _consumables


def migration_pointer_set(config_dir, dump_dir):
    """The enemy-gear pointer set, from the POST-OVERLAY
    ckf.hardmode.d/MonsterTypeModel.csv.

    -> (ids, rows_read, path). RAISES if that file is unreadable. It does NOT
    fall back to sheets/raw/MonsterTypeModel.csv: the shipped dump gives 208
    distinct WeaponTypeId and class 3 = 25 player / 51 enemy, the post-overlay
    file gives 405 and 33/43, and only the second reproduces design.md
    section 5. A migrator that reads the dump misclassifies eight class-3
    player assault rifles as enemy gear and withholds D4's x1.8 from them.
    mods/CKFHardMode/GearClasses.cs makes the same choice and refuses the same
    way.
    """
    path = os.path.join(config_dir, MIGRATION_DIR, MIGRATION_POINTER_FILE)
    if _mfault('shipped-monstertype'):
        # INJECTED FAULT: the shipped dump, which is the fallback this function
        # exists to refuse.
        path = os.path.join(dump_dir, MIGRATION_POINTER_FILE)
    if not os.path.isfile(path):
        raise MigrationRefused(
            '%s is not on disk.\n'
            'The player/enemy partition gear-classes.csv rests on is "class N '
            'minus the MonsterTypeModel.WeaponTypeId set", and that set must '
            'come from the post-overlay file, not from sheets/raw. Refusing '
            'rather than falling back to the shipped dump, which would '
            'misclassify eight class-3 player assault rifles as enemy gear.'
            % path)
    try:
        with open(path, newline='', encoding='utf-8-sig') as fh:
            rows = list(csv.DictReader(fh))
    except (OSError, UnicodeDecodeError) as e:
        raise MigrationRefused('%s could not be read: %s: %s'
                               % (path, type(e).__name__, e))
    if not rows:
        raise MigrationRefused('%s has a header and no data rows.' % path)
    if MIGRATION_POINTER_COLUMN not in rows[0]:
        raise MigrationRefused(
            '%s has no %s column, so the player/enemy partition cannot be '
            'resolved. Refusing rather than treating an unreadable pointer '
            'file as "no enemies" -- that reading would make every weapon '
            'player gear.' % (path, MIGRATION_POINTER_COLUMN))
    ids, blank = set(), 0
    for r in rows:
        v = (r[MIGRATION_POINTER_COLUMN] or '').strip()
        if not v:
            blank += 1
            continue
        try:
            ids.add(int(v))
        except ValueError:
            raise MigrationRefused('%s: %s %r is not an integer.'
                                   % (path, MIGRATION_POINTER_COLUMN, v))
    if blank:
        raise MigrationRefused(
            '%s: %d row(s) have a blank %s. Every monster row must name a '
            'weapon for the partition to be complete.'
            % (path, blank, MIGRATION_POINTER_COLUMN))
    return ids, len(rows), path


def migration_gear_classes(config_dir, dump_dir, gc, measured):
    """D2 + D4: the 16 RecoilRate2 id ranges become the ten gear-classes.csv
    rows, DERIVED -- never transcribed.

    The cells are derived: a class carries `RecoilRate2 *1.8` iff at least one
    of ITS OWN PLAYER ROWS has a non-zero RecoilRate2. The row comment's player
    count is derived from the same partition, which is what makes the choice of
    pointer file visible in the bytes rather than only in the expansion.

    scripts/gear_classes.py's ROW_COMMENTS is the declared prose; the count
    inside it is re-derived here and the two are CROSS-CHECKED. A disagreement
    is a refusal naming both numbers -- that is the check that fires when the
    shipped dump is read instead of the post-overlay file.
    """
    enemy, mrows, ppath = migration_pointer_set(config_dir, dump_dir)
    wpath = os.path.join(dump_dir, 'WeaponModel.csv')
    if not os.path.isfile(wpath):
        raise MigrationRefused('the dumped WeaponModel table is not at %s.' % wpath)
    with open(wpath, newline='', encoding='utf-8-sig') as fh:
        weapons = list(csv.DictReader(fh))
    measured['pointer_file'] = ppath
    measured['pointer_rows'] = mrows
    measured['pointer_ids'] = len(enemy)
    measured['weapon_rows'] = len(weapons)

    header = [gc.CLASS_COLUMN] + list(gc.LEVERS) + ['_comment']
    rows, stats = [], {}
    for cls, _name in gc.LEVER_CLASSES:
        players = [w for w in weapons
                   if int(w[gc.CLASS_COLUMN]) == cls
                   and int(w[gc.ID_COLUMN]) not in enemy]
        live2 = sum(1 for w in players
                    if (w.get('RecoilRate2') or '').strip()
                    and float(w['RecoilRate2']) != 0)
        stats[cls] = (len(players), live2)
        declared = gc.ROW_COMMENTS.get(cls)
        if declared is None:
            raise MigrationRefused(
                'scripts/gear_classes.py declares no row comment for '
                'WeaponClass %d, so the sheet cannot be rendered.' % cls)
        if live2:
            cells = dict(gc.CELLS.get(cls) or {})
            if not cells:
                raise MigrationRefused(
                    'WeaponClass %d has %d player row(s) with a live '
                    'RecoilRate2 and scripts/gear_classes.py declares no cell '
                    'for it. D2/D4 cannot be applied to a class the expander '
                    'does not carry.' % (cls, live2))
            comment = declared
        else:
            cells = {}
            m = MIGRATION_ROWCOUNT_RE.search(declared)
            if not m:
                raise MigrationRefused(
                    'WeaponClass %d has no live RecoilRate2 on any of its %d '
                    'player rows, but its declared comment %r states no player '
                    'row count, so the derived partition has nothing to be '
                    'checked against.' % (cls, len(players), declared))
            if int(m.group(1)) != len(players):
                raise MigrationRefused(
                    'WeaponClass %d: the partition resolved from %s gives %d '
                    'player row(s); scripts/gear_classes.py\'s declared row '
                    'comment states %s. These must agree.\n'
                    'THE USUAL CAUSE IS THE WRONG MonsterTypeModel: the '
                    'shipped sheets/raw dump gives 208 distinct %s and class 3 '
                    '= 25/51, the post-overlay ckf.hardmode.d file gives 405 '
                    'and 33/43. This run read %d distinct %s out of %s.'
                    % (cls, ppath, len(players), m.group(1),
                       MIGRATION_POINTER_COLUMN, len(enemy),
                       MIGRATION_POINTER_COLUMN, ppath))
            comment = MIGRATION_ROWCOUNT_RE.sub(
                'on all %d player rows' % len(players), declared)
        rows.append([str(cls)] + [cells.get(c, '') for c in gc.LEVERS] + [comment])
    measured['gear_partition'] = stats
    return _mig_csv(header, rows).encode('utf-8')


def build_migration(config_dir, dump_dir=None):
    """-> Migration. Reads; writes nothing, anywhere.

    Every refusal below is a MigrationRefused naming what could not be read or
    what disagreed. None of them returns a partial layout: a migration that
    half-converts leaves ConfigDoc.BothLayouts' refusal state behind.
    """
    gc, cw, imp, con = _migration_expanders()
    dump_dir = dump_dir or migration_dump_dir()
    mig = Migration(config_dir)
    d_dir = os.path.join(config_dir, MIGRATION_DIR)

    # ---- the inputs
    missing = [n for n in MIGRATION_INPUTS
               if not os.path.isfile(os.path.join(config_dir, n))]
    if missing:
        raise MigrationRefused(
            'this is not a 3.x install: %s is not in %s.\n'
            'Refusing rather than converting what is there -- a layout built '
            'from two of the three inputs is missing rows, not defaulted.'
            % (', '.join(missing), config_dir))

    already = [n for n in MIGRATION_4X_MARKERS
               if os.path.isfile(os.path.join(d_dir, n))]
    if already:
        raise MigrationRefused(
            'the 4.0 layout is already present: %s in %s, beside the 3.x '
            'files.\nConfigDoc.BothLayouts refuses to apply ANY rule for a '
            'launch that finds both, so this directory is already in the state '
            'the migration exists to leave. Converting into it would not fix '
            'that; rename or remove one layout by hand first.'
            % (', '.join(already), d_dir))

    # ---- backups, before anything is built
    for name in MIGRATION_INPUTS[:2]:
        bak = os.path.join(config_dir, name + MIGRATION_BACKUP_SUFFIX)
        if os.path.exists(bak) and not _mfault('backup-clobber'):
            raise MigrationRefused(
                '%s already exists (%d bytes).\n'
                'The migration renames the 3.x originals to %s and MUST NOT '
                'overwrite an existing backup -- that backup is the only copy '
                'of whatever a previous run moved aside. Refusing.'
                % (bak, os.path.getsize(bak), MIGRATION_BACKUP_SUFFIX))
        mig.renames.append((name, name + MIGRATION_BACKUP_SUFFIX))

    # ---- read
    raw_doc = read_bytes(os.path.join(config_dir, 'ckf.hardmode.json'))
    raw_rules = read_bytes(os.path.join(config_dir, 'ckf.hardmode.rules.json'))
    raw_cfg = read_bytes(os.path.join(config_dir, 'ckf.hardmode.cfg'))
    try:
        doc = json.loads(migration_strip_jsonc(raw_doc.decode('utf-8-sig')))
    except ValueError as e:
        raise MigrationRefused('ckf.hardmode.json is not parseable: %s' % e)
    try:
        rules = json.loads(migration_strip_jsonc(raw_rules.decode('utf-8-sig')))['rules']
    except (ValueError, KeyError, TypeError) as e:
        raise MigrationRefused('ckf.hardmode.rules.json is not parseable: %s' % e)
    if '_version' not in doc:
        raise MigrationRefused('ckf.hardmode.json carries no "_version" stamp; '
                               'every 4.0 settings slice has to carry it.')
    # The input must be stamped -- that is what the refusal above is for, and an
    # unstamped ckf.hardmode.json is not a 3.x settings document. What gets
    # written is the 4.0 layout's own stamp, NOT the one just read; see
    # MIGRATION_DOC_VERSION for what carrying the input's stamp forward broke.
    version = MIGRATION_DOC_VERSION

    mig.measured['rules'] = len(rules)
    shapes = {'exact': 0, 'range': 0, 'unscoped': 0}
    per_model, nonexact = {}, {}
    for r in rules:
        s = migration_selector(r)
        shapes[s] += 1
        per_model[r['model']] = per_model.get(r['model'], 0) + 1
        if s != 'exact':
            nonexact[r['model']] = nonexact.get(r['model'], 0) + 1
    mig.measured['selectors'] = shapes
    mig.measured['per_model'] = per_model
    mig.measured['nonexact'] = nonexact

    unknown = sorted(m for m in per_model
                     if m not in MIGRATION_DISPOSITION and m not in MIGRATION_ID_COLUMN)
    if unknown:
        raise MigrationRefused(
            'these models have rules and no declared disposition: %s.\n'
            'An unrecognised rule is not routed to a default file -- that is '
            'how D1 would come back. Declare where it goes first.'
            % ', '.join(unknown))

    # ---- 1. the merged document splits into one slice per subsystem
    sections = [k for k in doc if k != '_version']
    if _mfault('drop-section'):
        # INJECTED FAULT: a section that had a file has none. The mod would
        # start with that subsystem at stock and log nothing about it.
        sections = sections[1:]
    for key in sections:
        body = doc[key]
        if not isinstance(body, dict):
            raise MigrationRefused('ckf.hardmode.json section %r is a %s, not an '
                                   'object.' % (key, type(body).__name__))
        obj = {'_version': version}
        obj.update(body)
        # The retired subsystem gate, dropped at the TOP LEVEL of a NAMED
        # section only. See MIGRATION_RETIRED_GATE_SECTIONS for why the eight
        # are listed rather than searched for, and why difficulty is not one of
        # them. Nested gates -- credits.enabled and stress.enabled inside
        # elapse, woundResist.enabled inside fatigue -- are settings and are
        # untouched: this pops off `obj`, which is the section's own top level,
        # and never descends.
        if key in MIGRATION_RETIRED_GATE_SECTIONS:
            obj.pop(MIGRATION_RETIRED_GATE_KEY, None)
        mig.put('%s/%s.json' % (MIGRATION_DIR, key),
                (json.dumps(obj, indent=2, ensure_ascii=False) + '\n').encode('utf-8'),
                'converted')
    mig.measured['sections'] = len(sections)

    # ---- 2. the Team PL mirror, from the slice this conversion just wrote
    teampl = doc.get('teampl')
    if not isinstance(teampl, dict):
        raise MigrationRefused('ckf.hardmode.json has no "teampl" section, so the '
                               'victory-screen label mirror cannot be generated. '
                               'Leaving it out would ship a stock award with a '
                               'lying label.')
    merged, stock = gen_teampl_labels.merged_cells(teampl)
    mirror_rules = gen_teampl_labels.rules_for(merged, stock)
    mig.put('%s/MissionPowerLevelModel.generated.json' % MIGRATION_DIR,
            gen_teampl_labels.render(
                mirror_rules, '%s/teampl.json' % MIGRATION_DIR).encode('utf-8'),
            'converted')
    mig.measured['mirror_rules'] = len(mirror_rules)

    # ---- 3. the exact-selector rules become overlay rows
    dest = {}
    for i, r in enumerate(rules):
        model = r['model']
        p = migration_prefix(r)
        if p in MIGRATION_PREFIX_PACK:
            dest[i] = '%s.%s.csv' % (model, MIGRATION_PREFIX_PACK[p])
        elif model == 'RuleModel':
            dest[i] = 'RuleModel.csv'
    by_file = {}
    for i in sorted(dest):
        by_file.setdefault(dest[i], []).append(i)

    shipped_rule, rule_name = {}, {}
    rpath = os.path.join(dump_dir, 'RuleModel.csv')
    if not os.path.isfile(rpath):
        raise MigrationRefused('the dumped RuleModel table is not at %s, so '
                               'RuleModel.csv\'s untouched rows cannot be '
                               'named.' % rpath)
    with open(rpath, newline='', encoding='utf-8-sig') as fh:
        for row in csv.DictReader(fh):
            rid = int(row['RuleId'])
            shipped_rule[rid] = row['Value']
            rule_name[rid] = row.get('ConfigName') or ''

    converted = 0
    for fn in sorted(by_file, key=lambda s: s.encode('utf-8')):
        idxs = by_file[fn]
        if fn == 'RuleModel.csv':
            touched = {}
            for i in idxs:
                touched[int(list(rules[i]['where'].values())[0])] = rules[i]
            last = MIGRATION_RULEMODEL_ROWS
            if _mfault('range-short'):
                # INJECTED FAULT: a range expanded one id short. Row 76 is
                # never written and nothing says so.
                last -= 1
            header, out_rows = ['RuleId', 'Value', '_comment'], []
            for rid in range(1, last + 1):
                r = touched.get(rid)
                if r is not None:
                    out_rows.append([str(rid), _mig_fmt(r['set']['Value']),
                                     r.get('comment') or ''])
                else:
                    note = rule_name.get(rid, '')
                    if shipped_rule.get(rid) is not None:
                        note = ('%s — ships %s, untouched'
                                % (note, shipped_rule[rid])).strip(' —')
                    out_rows.append([str(rid), '', note])
        else:
            model = fn.split('.')[0]
            idcol = MIGRATION_ID_COLUMN.get(model)
            if idcol is None:
                raise MigrationRefused(
                    '%s would be written for model %s, and no id column is '
                    'declared for it. Key on (table, id): guessing the column '
                    'would key on an id alone.' % (fn, model))
            cols = []
            for i in idxs:
                if migration_selector(rules[i]) != 'exact':
                    raise MigrationRefused(
                        '%s would carry a %s-selector rule (%r). Only exact '
                        'selectors convert to overlay rows; a range or '
                        'unscoped rule has a declared disposition instead.'
                        % (fn, migration_selector(rules[i]),
                           rules[i].get('comment', '')[:60]))
                for c in rules[i].get('set', {}):
                    if c not in cols:
                        cols.append(c)
            header = [idcol] + cols + ['_comment']
            out_rows = []
            for i in idxs:
                r = rules[i]
                cells = [str(int(list(r['where'].values())[0]))]
                cells += [_mig_fmt(r['set'][c]) if c in r.get('set', {}) else ''
                          for c in cols]
                cells.append(r.get('comment') or '')
                out_rows.append(cells)
        converted += len(idxs)
        mig.put('%s/%s' % (MIGRATION_DIR, fn),
                _mig_csv(header, out_rows).encode('utf-8'), 'converted')
    mig.measured['converted_rules'] = converted
    mig.measured['converted_files'] = len(by_file)

    # ---- 4. D1. Stated as a positive measurement, not as an absence.
    d1 = [r for r in rules if r['model'] == D1_MODEL]
    if _mfault('d1-reconstructed') and d1:
        # INJECTED FAULT: D1 RECONSTRUCTED. A range selector cannot become an
        # overlay ROW, so a converter written to "preserve every operand of
        # every rule" keeps it as rules -- and a .json in ckf.hardmode.d IS a
        # rules file to Overlays.Load (Overlays.cs:38-45). That is the faithful
        # shape of this failure: 1,180 rows / 2,360 values of Phase 5's
        # deletion come back, and nothing in the game or the gates says so.
        mig.put('%s/%s.elites.json' % (MIGRATION_DIR, D1_MODEL),
                (json.dumps({'rules': d1}, indent=2, ensure_ascii=False)
                 + '\n').encode('utf-8'), 'converted')
    mig.measured['D1'] = {
        'rules_in': len(d1),
        'files_out': len([f for f in by_file if f.startswith(D1_MODEL + '.')]),
        'operands': sorted(set(c for r in d1 for op in ('multiply', 'set', 'add',
                                                        'clampMin', 'clampMax')
                               for c in r.get(op, {}))),
    }

    # ---- 5. D3. implants-global.json carries THREE numbers, not four.
    unscoped = [r for r in rules
                if r['model'] == 'ImplantModel' and migration_selector(r) == 'unscoped']
    if len(unscoped) != 1:
        raise MigrationRefused(
            '%d unscoped ImplantModel rule(s) in the 3.x rules file; exactly 1 '
            'is expected and implants-global.json holds its multipliers. '
            'Refusing rather than guessing which one is the blanket rule.'
            % len(unscoped))
    ur = unscoped[0]
    mult = ur.get('multiply') or {}
    for col in ('Cost', 'InstallTime', 'ImplantStress'):
        if col not in mult:
            raise MigrationRefused(
                'the unscoped ImplantModel rule does not multiply %s, and '
                'implants-global.json has a field for it. Refusing rather than '
                'writing a default over a number the player may have edited.' % col)
    glob = {'_version': version, '_doc': list(IMPLANTS_GLOBAL_DOC),
            'costMultiply': mult['Cost'],
            'installTimeMultiply': mult['InstallTime'],
            'implantStressMultiply': mult['ImplantStress']}
    d3_op, d3_col = D3_OPERAND
    d3_present = d3_col in (ur.get(d3_op) or {})
    if _mfault('d3-carried'):
        # INJECTED FAULT: D3 carried across. A converter that preserves every
        # operand writes this, and it binds on 0 of 198 rows -- so it changes
        # no value and every gate stays green while the file grows a fourth
        # number the design says must not be there.
        glob['implantStressClampMin'] = (ur.get(d3_op) or {}).get(d3_col)
    mig.put('%s/implants-global.json' % MIGRATION_DIR,
            (json.dumps(glob, indent=2, ensure_ascii=False) + '\n').encode('utf-8'),
            'converted')
    mig.measured['D3'] = {'in_source': d3_present,
                          'written': 'implantStressClampMin' in glob,
                          'operand': '%s %s' % (d3_op, d3_col)}

    # ---- 6. D2 + D4
    d2d4 = [r for r in rules if r['model'] == 'WeaponModel'
            and migration_selector(r) == 'range'
            and 'RecoilRate2' in (r.get('multiply') or {})]
    mig.measured['D2D4'] = {'ranges_in': len(d2d4)}
    mig.put('%s/%s' % (MIGRATION_DIR, gc.SHEET_NAME),
            migration_gear_classes(config_dir, dump_dir, gc, mig.measured),
            'converted')

    # ---- 7. the three enemy-gear overlays, carried across untouched
    for name in MIGRATION_CARRIED:
        p = os.path.join(d_dir, name)
        if not os.path.isfile(p):
            raise MigrationRefused(
                '%s is not in %s. A 3.x install ships it (design.md section 1: '
                '"Three such files shipped before this change"), and it is also '
                'what the gear-class partition is resolved against. Refusing '
                'rather than writing a 4.0 layout without it.' % (name, d_dir))
        mig.put('%s/%s' % (MIGRATION_DIR, name), read_bytes(p), 'carried')

    # ---- 8. the lever sheets no rule feeds
    cdump = con.Dump(dump_dir)
    for sheet in con.SHEETS:
        header, rows_, _carried, _dropped = con.build_sheet(cdump, sheet.cls)
        mig.put('%s/%s' % (MIGRATION_DIR, sheet.name),
                con.csv_text(header, rows_).encode('utf-8'), 'derived')
    weapons = cw.load_table(dump_dir, 'WeaponModel.csv', 'WeaponId', 'WeaponModel')
    talents = cw.load_table(dump_dir, 'TalentModel.csv', 'TalentId', 'TalentModel')
    by_sheet, _pairs, problems = cw.cyber_rows(weapons, talents)
    if problems:
        raise MigrationRefused('the cyberweapon join is ambiguous: %s'
                               % '; '.join(problems))
    for sheet in cw.SHEETS:
        mig.put('%s/%s' % (MIGRATION_DIR, sheet.name),
                cw.render_sheet(sheet, weapons, talents,
                                by_sheet[sheet.key]).encode('utf-8'), 'derived')

    # The eleven implant slot tables are built LAST and over the staged layout,
    # because implants.LiveRules reads implants-global.json and the EffectModel
    # pack files to decide which columns a table carries. Reading the 3.x
    # directory instead would find the unscoped rule that D3 belongs to and the
    # rules file this migration is deleting.
    stage = tempfile.mkdtemp(prefix='ckf-migrate-')
    try:
        os.makedirs(os.path.join(stage, MIGRATION_DIR))
        for rel, data in mig.files.items():
            with open(os.path.join(stage, rel), 'wb') as fh:
                fh.write(data)
        idump = imp.Dump(dump_dir)
        ilive = imp.LiveRules(stage)
        sheets, _drops = imp.build_all(idump, ilive)
        for name, (header, rows_) in sheets.items():
            mig.put('%s/%s' % (MIGRATION_DIR, name),
                    imp.csv_text(header, rows_).encode('utf-8'), 'derived')
    finally:
        shutil.rmtree(stage, ignore_errors=True)

    # ---- 9. the .cfg
    mig.put('ckf.hardmode.cfg', migration_cfg(raw_cfg, load_schemas()), 'converted')

    mig.deletes = []
    mig.notes.append('%d rule(s) read: %d exact, %d range, %d unscoped'
                     % (len(rules), shapes['exact'], shapes['range'], shapes['unscoped']))
    mig.notes.append('%d rule(s) converted into %d overlay file(s)'
                     % (converted, len(by_file)))
    mig.notes.append('deviations applied during conversion: %s'
                     % ', '.join(MIGRATION_DEVIATIONS))
    return mig


def migration_cfg_stamp_header(raw_cfg):
    """The 3.x .cfg with its BepInEx header line restamped to this plugin.

    ONE TOKEN ON ONE LINE. Group 2 of _MIGRATION_CFG_HEADER -- the version --
    is replaced with MIGRATION_PLUGIN_VERSION; the plugin name, the trailing
    whitespace, that line's own ending and every byte after it are returned
    exactly as they arrived. The newline convention is therefore not a
    parameter here: the rewrite never spans a line ending, so a CRLF file stays
    CRLF and an LF file stays LF without this function knowing which it has.

    A HEADER THAT IS NOT THAT SHAPE IS A REFUSAL, not a rewrite and not an
    append. This function exists because a .cfg carrying a version other than
    the running plugin's is the defect [measured 2026-09-15]; guessing which of
    "replace the whole line", "insert a header above it" or "leave it" a
    stranger first line wants would put back exactly the silent disagreement
    the stamp removes. The refusal writes nothing -- build_migration raises
    before commit -- and the message names the line, so restoring it or
    deleting the .cfg and letting BepInEx regenerate it are both open.
    """
    i = raw_cfg.find(b'\n')
    first = raw_cfg if i < 0 else raw_cfg[:i]
    rest = b'' if i < 0 else raw_cfg[i:]
    eol = b''
    if first.endswith(b'\r'):
        first, eol = first[:-1], b'\r'
    m = _MIGRATION_CFG_HEADER.match(first)
    if not m:
        raise MigrationRefused(
            'the first line of ckf.hardmode.cfg is %r, which is not the header '
            'BepInEx writes ("## Settings file was created by plugin <name> '
            'v<version>"). The 4.0 .cfg carries that line with the version '
            'restamped to %s, and there is no correct way to stamp a line this '
            'converter cannot read. Restore the line, or delete '
            'ckf.hardmode.cfg and let BepInEx write a fresh one, and run the '
            'migration again -- nothing has been written.'
            % (first.decode('utf-8', 'replace')[:120], MIGRATION_PLUGIN_VERSION))
    return (m.group(1) + MIGRATION_PLUGIN_VERSION.encode('utf-8') + m.group(3)
            + eol + rest)


def migration_cfg(raw_cfg, schemas):
    """The 43-key .cfg: the 3.x file carried across, with [Slices] appended.

    The 3.x [General] block is CARRIED ACROSS, not rebuilt: a player who
    switched the mod off has to stay switched off. BepInEx rewrites this file
    from the keys the plugin binds on the next launch, so what matters here is
    that every key is present with the right value before that launch, not that
    this file wrote it.

    CORRECTION, 2026-09-15: this docstring used to read "the 3.x file kept BYTE
    FOR BYTE, with [Slices] appended", and the code matched it -- `head =
    raw_cfg`. That is now true of everything EXCEPT one token on the first
    line: the BepInEx header's version is restamped to
    MIGRATION_PLUGIN_VERSION, because carrying the input's forward produced a
    4.0 .cfg announcing the version it was converted FROM, which BepInEx
    overwrites on the next launch and which the byte-identity gate in section
    19c had already gone red on. See migration_cfg_stamp_header and
    MIGRATION_PLUGIN_VERSION. Every other byte of the 3.x file, [General] and
    the player's own values included, still arrives unchanged.
    """
    nl = b'\r\n' if b'\r\n' in raw_cfg else b'\n'
    head = migration_cfg_stamp_header(raw_cfg)
    if _mfault('cfg-key-dropped'):
        # INJECTED FAULT: the [General] block rebuilt from defaults. Enabled
        # goes back to true whatever the player set, and nothing logs it.
        head = (b'## Settings file was created by plugin CKF Hard Mode' + nl
                + b'## Plugin GUID: ckf.hardmode' + nl + nl
                + b'[General]' + nl + nl)
    if not head.endswith(nl + nl):
        head = head.rstrip(b'\r\n') + nl + nl
    out = [head, b'[Slices]' + nl + nl]
    fields = cfg_fields(schemas)
    slices = sorted(p for p in fields if p.startswith('Slices.'))
    if not slices:
        raise MigrationRefused(
            'no schema declares a Slices.* key, so the 4.0 .cfg would carry '
            'the 3.x single key and every slice would take its compiled-in '
            'default. Refusing rather than writing a one-key file.')
    for path in slices:
        _sch, f = fields[path]
        if f['type'] != 'bool':
            raise MigrationRefused('%s is declared as %r; every slice toggle is '
                                   'a Boolean.' % (path, f['type']))
        val = render_cfg_value(f['type'], f.get('default')).encode('utf-8')
        out.append(b'# Setting type: Boolean' + nl
                   + b'# Default value: ' + val + nl
                   + path.split('.', 1)[1].encode('utf-8') + b' = ' + val + nl + nl)
    return b''.join(out)


def run_migration(config_dir, dump_dir=None):
    """Build, then commit through the same journalled transaction a save uses.

    -> the Migration. Raises MigrationRefused without having written anything.
    """
    mig = build_migration(config_dir, dump_dir)
    current = {}
    for rel in mig.files:
        p = os.path.join(config_dir, rel)
        if os.path.exists(p):
            current[rel] = read_bytes(p)
    commit(config_dir, mig.files, current, force=True)
    for src, dst in mig.renames:
        sp = os.path.join(config_dir, src)
        dp = os.path.join(config_dir, dst)
        if os.path.exists(dp) and not _mfault('backup-clobber'):
            raise MigrationRefused('%s appeared while the migration ran; the '
                                   'new layout is written and the 3.x originals '
                                   'are still in place.' % dp)
        os.replace(sp, dp)
    _fsync_dir(config_dir)
    return mig

# ---------------------------------------------------------------------------
# settings

def load_settings():
    try:
        with open(SETTINGS_PATH, encoding='utf-8') as f:
            s = json.load(f)
    except Exception:
        s = {}
    # A BLANK gameDir IS NOT A CHOICE. setdefault only fills a key that is
    # absent, so a settings file carrying "gameDir": "" -- which is what
    # clearing the box in the page writes -- came back blank forever, and a
    # re-extract of the zip did not fix it because the zip does not carry this
    # file. config_dir_for on an empty gameDir yields the relative path
    # "BepInEx/config", which resolves against the working directory and names
    # nothing. Absent and blank are therefore the same state, and both take the
    # default. Reported by David, 2026-09-07.
    if not str(s.get('gameDir') or '').strip():
        s['gameDir'] = default_game_dir()
    s.setdefault('configDirOverride', None)
    s.setdefault('stripReadme', True)
    return s


def save_settings(s):
    tmp = SETTINGS_PATH + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(s, f, indent=2)
    os.replace(tmp, SETTINGS_PATH)


def config_dir_for(settings):
    if settings.get('configDirOverride'):
        return settings['configDirOverride']
    return os.path.join(settings.get('gameDir') or '', 'BepInEx', 'config')


# ---------------------------------------------------------------------------
# mission reference (gui-plan.md 4.2) — read if it is there, say so if not

def read_mission_reference():
    p = os.path.join(DOCS_DIR, 'mission-reference.json')
    if not os.path.exists(p):
        return {'state': 'absent', 'path': p, 'byType': {},
                'detail': 'not written yet; gui-plan.md 4.2 assigns it to '
                          'refresh_mission_roster.py'}
    try:
        data = check_schema.load_jsonc(p)
    except Exception as e:
        return {'state': 'error', 'path': p, 'byType': {}, 'detail': str(e)}
    if isinstance(data, dict) and isinstance(data.get('byType'), dict):
        by = data['byType']
    elif isinstance(data, dict):
        by = data
    else:
        return {'state': 'error', 'path': p, 'byType': {},
                'detail': 'expected an object keyed by mission type'}
    return {'state': 'loaded', 'path': p, 'byType': by, 'detail': None}


# ---------------------------------------------------------------------------
# the application object the HTTP layer talks to

class App:
    def __init__(self, settings, token):
        self.settings = settings
        self.token = token
        self.schemas = load_schemas()
        self.lock = threading.Lock()

    def snapshot(self):
        cd = config_dir_for(self.settings)
        recovery = recover_journal(cd) if os.path.isdir(cd) else {
            'found': False, 'completed': [], 'missing': [], 'error': None}
        doc = read_document(cd, self.schemas)
        model, extras = build_model(doc)
        return doc, model, extras, cd, recovery

    def api_model(self):
        doc, model, _extras, cd, recovery = self.snapshot()
        secs = sections_for(self.schemas)
        check = run_check_schema(cd) if os.path.isdir(cd) else {
            'ran': False, 'problems': [], 'error': 'config directory does not exist'}
        return {
            'token': self.token,
            'gameDir': self.settings.get('gameDir'),
            'configDir': cd,
            'configDirOverride': self.settings.get('configDirOverride'),
            'stripReadme': bool(self.settings.get('stripReadme', True)),
            'defaultGameDir': default_game_dir(),
            'probe': {'config': probe_writable(cd),
                      'overlays': probe_writable(os.path.join(cd, 'ckf.hardmode.d'))
                      if os.path.isdir(cd) else {'state': 'unset', 'detail': 'config dir not readable'}},
            'schemas': decorate_schemas(self.schemas),
            'sections': secs,
            'navGroups': nav_groups_for(self.schemas, secs),
            'values': model,
            'enableIndex': enable_index(doc, model),
            'masterKey': MASTER_KEY,
            'strayKeys': stray_keys(doc, self.schemas),
            'cfgError': doc.cfg_error,
            'sidecarErrors': doc.sidecar_errors,
            'check': check,
            'missionReference': read_mission_reference(),
            'recovery': recovery,
            'fieldCount': sum(len(s['fields']) for s in self.schemas),
            'fingerprints': fingerprints(cd, self.schemas) if os.path.isdir(cd) else {},
        }

    def api_validate(self, edits, strip_readme=None):
        with self.lock:
            doc, model, extras, cd, _rec = self.snapshot()
            if strip_readme is None:
                strip_readme = bool(self.settings.get('stripReadme', True))
            try:
                apply_table_formats(doc, extras, model, edits)
                edits, notes = requires_pass(doc.schemas, doc, edits)
                proposed, more = apply_edits(doc, extras, edits, strip_readme)
                notes = (reformat_notes(doc) + stray_notes(doc, doc.schemas)
                         + notes + more)
            except SaveRefused as e:
                return {'ok': False, 'refused': e.payload, 'check': None, 'notes': []}
            check = stage_and_validate(doc, proposed)
            blocking = [p for p in check['problems'] if p['kind'] in BLOCKING]
            ok = check['ran'] and not blocking
            return {'ok': ok, 'refused': None, 'check': check,
                    'blocking': blocking, 'notes': notes,
                    'wouldWrite': sorted(proposed.keys())}

    def api_save(self, edits, strip_readme=None, force=False, expect=None):
        with self.lock:
            doc, model, extras, cd, _rec = self.snapshot()
            if not os.path.isdir(cd):
                return {'ok': False, 'refused': {'summary': 'config directory does not exist',
                                                 'detail': cd}}
            if strip_readme is None:
                strip_readme = bool(self.settings.get('stripReadme', True))
            if expect:
                now = fingerprints(cd, self.schemas)
                moved = sorted(k for k, v in expect.items()
                               if k in now and now[k] != v)
                if moved:
                    return {'ok': False, 'refused': {
                        'summary': 'the config changed on disk since it was loaded; '
                                   'nothing was written',
                        'detail': 'changed: %s\n\nReload before saving. Row identity here '
                                  'is positional, so writing against a stale read could '
                                  'attach preserved keys to the wrong row.'
                                  % ', '.join(moved)}, 'stale': moved}
            try:
                apply_table_formats(doc, extras, model, edits)
                # Before anything is rendered and before check_schema is run:
                # the downward refusal has to be the editor's, because only the
                # editor knows which key the player just moved and can name the
                # dependent. See requires_pass.
                edits, notes = requires_pass(doc.schemas, doc, edits)
                proposed, more = apply_edits(doc, extras, edits, strip_readme)
                notes = (reformat_notes(doc) + stray_notes(doc, doc.schemas)
                         + notes + more)
            except SaveRefused as e:
                return {'ok': False, 'refused': e.payload}

            check = stage_and_validate(doc, proposed)
            if not check['ran']:
                return {'ok': False, 'refused': {
                    'summary': 'validation could not run, so the save is refused',
                    'detail': check['error']}, 'check': check}
            blocking = [p for p in check['problems'] if p['kind'] in BLOCKING]
            if blocking:
                return {'ok': False, 'refused': {
                    'summary': '%d blocking problem(s); nothing was written' % len(blocking),
                    'detail': '\n'.join('%s %s' % (p['kind'], p['message']) for p in blocking)},
                    'check': check, 'blocking': blocking}

            current = {}
            for rel in proposed:
                p = os.path.join(cd, rel)
                if os.path.exists(p):
                    current[rel] = read_bytes(p)
            try:
                result = commit(cd, proposed, current, force=force)
            except OSError as e:
                denied = isinstance(e, PermissionError) or getattr(e, 'errno', None) in (
                    errno.EACCES, errno.EPERM, errno.EROFS)
                if denied:
                    return {'ok': False, 'refused': {
                        'summary': 'the config directory refused the write',
                        'detail': '%s: %s\n\nNothing was written. That path is normally '
                                  'under Program Files, and this tool does not assume an '
                                  'unelevated account can write there. Run it from an '
                                  'account that can, or point it at a copy.'
                                  % (type(e).__name__, e)}}
                return {'ok': False, 'refused': {
                    'summary': 'the write failed; see the detail before retrying',
                    'detail': '%s: %s' % (type(e).__name__, e)}}

            after = run_check_schema(cd)
            return {'ok': True, 'written': result['written'],
                    'skipped': result['skipped'],
                    'notes': notes, 'check': check, 'checkAfter': after,
                    'relaunch': 'Every subsystem reads its config once in Plugin.Load(). '
                                'Restart Cyber Knights Flashpoint for these values to take effect.'}


# ---------------------------------------------------------------------------
# HTTP

class Handler(BaseHTTPRequestHandler):
    server_version = 'ckf-gui'
    protocol_version = 'HTTP/1.1'
    app = None
    expected_host = None

    def log_message(self, fmt, *args):
        sys.stderr.write('  %s\n' % (fmt % args))

    # -- guards ------------------------------------------------------------
    def _host_ok(self):
        host = (self.headers.get('Host') or '').strip()
        return host in self.expected_host

    def _origin_ok(self):
        origin = self.headers.get('Origin')
        if origin is None:
            return True
        return any(origin == 'http://%s' % h for h in self.expected_host)

    def _token_ok(self):
        return secrets.compare_digest(self.headers.get('X-CKF-Token') or '', self.app.token)

    def _send(self, code, body, ctype='application/json; charset=utf-8'):
        if isinstance(body, str):
            body = body.encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy',
                         "default-src 'none'; script-src 'self' 'unsafe-inline'; "
                         "style-src 'self' 'unsafe-inline'; connect-src 'self'; "
                         "img-src 'self' data:; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, obj):
        self._send(code, json.dumps(obj, ensure_ascii=False))

    # -- routes ------------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            return self._send(421, 'bad host', 'text/plain; charset=utf-8')
        path = self.path.split('?', 1)[0]
        if path in ('/', '/app.html'):
            try:
                with open(APP_HTML, 'rb') as f:
                    html = f.read()
            except OSError as e:
                return self._send(500, 'app.html: %s' % e, 'text/plain; charset=utf-8')
            html = html.replace(b'__CKF_TOKEN__', self.app.token.encode('ascii'))
            return self._send(200, html, 'text/html; charset=utf-8')
        if path == '/api/model':
            if not (self._token_ok() and self._origin_ok()):
                return self._send(403, 'forbidden', 'text/plain; charset=utf-8')
            try:
                return self._json(200, self.app.api_model())
            except Exception:
                return self._json(500, {'error': traceback.format_exc()})
        return self._send(404, 'no such route', 'text/plain; charset=utf-8')

    def do_POST(self):
        if not self._host_ok():
            return self._send(421, 'bad host', 'text/plain; charset=utf-8')
        if not self._origin_ok():
            return self._send(403, 'cross-origin post refused', 'text/plain; charset=utf-8')
        if not self._token_ok():
            return self._send(403, 'forbidden', 'text/plain; charset=utf-8')
        path = self.path.split('?', 1)[0]
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            return self._send(400, 'bad length', 'text/plain; charset=utf-8')
        if n > 32 * 1024 * 1024:
            return self._send(413, 'too large', 'text/plain; charset=utf-8')
        raw = self.rfile.read(n) if n else b'{}'
        try:
            body = json.loads(raw.decode('utf-8'))
        except Exception as e:
            return self._json(400, {'error': 'body is not JSON: %s' % e})
        if not isinstance(body, dict):
            return self._json(400, {'error': 'body must be an object'})
        try:
            if path == '/api/validate':
                return self._json(200, self.app.api_validate(body.get('edits') or {},
                                                             body.get('stripReadme')))
            if path == '/api/save':
                return self._json(200, self.app.api_save(body.get('edits') or {},
                                                         body.get('stripReadme'),
                                                         bool(body.get('force')),
                                                         body.get('fingerprints')))
            if path == '/api/settings':
                s = self.app.settings
                if 'gameDir' in body:
                    s['gameDir'] = str(body['gameDir'] or '')
                if 'configDirOverride' in body:
                    v = body['configDirOverride']
                    s['configDirOverride'] = str(v) if v else None
                if 'stripReadme' in body:
                    s['stripReadme'] = bool(body['stripReadme'])
                save_settings(s)
                return self._json(200, self.app.api_model())
            if path == '/api/quit':
                threading.Thread(target=self.server.shutdown, daemon=True).start()
                return self._json(200, {'ok': True})
        except Exception:
            return self._json(500, {'error': traceback.format_exc()})
        return self._send(404, 'no such route', 'text/plain; charset=utf-8')


def serve(app, open_browser=True, host='127.0.0.1', port=0):
    # port 0 is the normal case and picks a free one. A caller that names a
    # port does so because it needs to know it in advance -- --selftest starts
    # the frozen exe and has to reach it, and reading the number back out of a
    # redirected pipe depends on how the platform buffers one.
    httpd = ThreadingHTTPServer((host, port), Handler)
    port = httpd.server_address[1]
    Handler.app = app
    Handler.expected_host = {'%s:%d' % (host, port), 'localhost:%d' % port}
    url = 'http://%s:%d/' % (host, port)
    print('CKF Hard Mode config GUI')
    print('  repo        %s' % REPO)
    print('  config dir  %s' % config_dir_for(app.settings))
    print('  listening   %s  (127.0.0.1 only)' % url)
    print('  stop with Ctrl-C')
    if open_browser:
        threading.Thread(target=lambda: (time.sleep(0.3), webbrowser.open(url)),
                         daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print('\nstopped')
    finally:
        httpd.server_close()
    return port


def free_port_check(host='127.0.0.1'):
    s = socket.socket()
    s.bind((host, 0))
    p = s.getsockname()[1]
    s.close()
    return p


# ---------------------------------------------------------------------------
# main

# ---------------------------------------------------------------------------
# verification
#
# Everything here writes only inside a temp directory. --config names a config
# directory to COPY; the original is never touched, never probed and never
# written to.

class _T:
    def __init__(self):
        self.passed = 0
        self.failed = []
        # Cases with no sampling moment on this machine. Not a pass, not a
        # failure, and never silent: the report names each one and why, so a
        # green run cannot be read as covering something it never reached.
        self.notrun = []

    def check(self, name, cond, detail=''):
        if cond:
            self.passed += 1
            print('  PASS  %s' % name)
        else:
            self.failed.append((name, detail))
            print('  FAIL  %s%s' % (name, ('\n        ' + str(detail)) if detail else ''))

    def skip(self, name, why):
        self.notrun.append((name, why))
        print('  NOT RUN  %s\n           %s' % (name, why))

    def report(self, title):
        tail = (', %d not run' % len(self.notrun)) if self.notrun else ''
        print('\n%s: %d passed, %d failed%s'
              % (title, self.passed, len(self.failed), tail))
        for name, why in self.notrun:
            print('  NOT RUN  %s -- %s' % (name, why))
        return 0 if not self.failed else 1


def _semantic_diff(a, b, path='$'):
    out = []
    if type(a) is not type(b) and not (isinstance(a, (int, float)) and isinstance(b, (int, float))):
        return ['%s: %s vs %s' % (path, type(a).__name__, type(b).__name__)]
    if isinstance(a, dict):
        for k in a:
            if k not in b:
                out.append('%s.%s: present on the left, ABSENT on the right' % (path, k))
        for k in b:
            if k not in a:
                out.append('%s.%s: ABSENT on the left, present on the right' % (path, k))
        for k in a:
            if k in b:
                out += _semantic_diff(a[k], b[k], '%s.%s' % (path, k))
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append('%s: %d rows vs %d rows' % (path, len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            out += _semantic_diff(x, y, '%s[%d]' % (path, i))
    elif isinstance(a, float) or isinstance(b, float):
        if float(a) != float(b):
            out.append('%s: %r vs %r' % (path, a, b))
    elif a != b:
        out.append('%s: %r vs %r' % (path, a, b))
    return out


def _sandbox(src_config, dst):
    shutil.copytree(src_config, dst)
    return dst


# Fixture builders for a .cfg in a known key state.
#
# REPLACES _cfg_add_keys, 2026-09-13 (split-config-into-toggleable-slices).
# That helper appended a `[Slices]` header unconditionally and raised
# AssertionError when the file already had one:
#
#   AssertionError: ...\slice-keys\ckf.hardmode.cfg already has a [Slices]
#   section; this helper appends one and would file its keys under the wrong
#   header
#
# Its docstring said "ckf.hardmode.cfg only carries a key after the game has
# been launched with that build. Until then the live file holds one key". The
# game was then launched, the live file went to 43 keys, every sandbox copy
# arrived already carrying [Slices], and the assertion ended the run with no
# report line -- the third time this file did that in one day.
#
# TWO DEFECTS, both fixed here.
#
#  1. The helper could not build its own target state from a source that was
#     already in it. It now edits whatever it is given into the state asked
#     for, whichever state that is.
#
#  2. A FIXTURE BUILDER MUST NOT BE ABLE TO END THE RUN. A fixture that cannot
#     build its condition is a FAIL naming why, not a traceback: a traceback
#     costs every later section as well, and reports nothing about the code
#     under test. Both builders return (ok, reason) and raise nothing. The
#     caller turns a False into t.check(..., False, reason).
#
# Deliberately built out of split_lines_keepends and a local regex rather than
# out of CfgFile: an instrument assembled from the thing under test cannot see
# the thing under test fail (AGENTS.md section 3). The caller then asserts,
# through the ordinary read path, that the fixture really is in the state it
# asked for -- which is the check that catches a builder and a reader agreeing
# with each other and both being wrong.

_FIXTURE_KEY_RE = re.compile(r'^([A-Za-z]\w*)\s*=')
_FIXTURE_SEC_RE = re.compile(r'^\[([^\]]+)\]\s*$')


def _cfg_fixture_parse(raw):
    """-> (lines, ends, {section: header index}, {'Sec.Key': index})"""
    text = raw.decode('utf-8-sig')
    lines, ends = split_lines_keepends(text)
    secs, keys, cur = {}, {}, None
    for i, ln in enumerate(lines):
        m = _FIXTURE_SEC_RE.match(ln.strip())
        if m:
            cur = m.group(1)
            secs.setdefault(cur, i)
            continue
        mk = _FIXTURE_KEY_RE.match(ln)
        if mk and cur:
            keys['%s.%s' % (cur, mk.group(1))] = i
    return lines, ends, secs, keys


def _cfg_fixture_write(cfg_path, raw, lines, ends):
    with open(cfg_path, 'wb') as fh:
        fh.write((b'\xef\xbb\xbf' if has_bom(raw) else b'')
                 + ''.join(l + e for l, e in zip(lines, ends)).encode('utf-8'))


def _cfg_fixture_end(ends, at, raw):
    """The ending a line added at `at` takes: the nearest real one above it,
    then any in the file, then the file-level sniff. Same rule as
    CfgFile._default_end, restated rather than imported for the reason in the
    block comment above."""
    for e in reversed(ends[:at]):
        if e:
            return e
    for e in ends:
        if e:
            return e
    return newline_of_bytes(raw)


def _cfg_with_keys(cfg_path, keys, value='true'):
    """Put every key in `keys` in the file at `value`. -> (ok, reason)

    The after-a-launch shape, built from whatever the file is in now: a key
    that is absent is added under its section (creating the section if it has
    none), and a key that is already there has its value line replaced, so the
    result is the same whether the source was launched or not.

    Only ever called on a copy under a TemporaryDirectory.
    """
    try:
        raw = read_bytes(cfg_path)
        lines, ends, secs, have = _cfg_fixture_parse(raw)
        for k in sorted(keys):
            if '.' not in k:
                return False, 'fixture key %r has no section' % k
            sec, name = k.split('.', 1)
            if k in have:
                i = have[k]
                lines[i] = '%s = %s' % (name, value)
                continue
            if sec in secs:
                start = secs[sec]
                stop = start + 1
                while stop < len(lines) and not _FIXTURE_SEC_RE.match(lines[stop].strip()):
                    stop += 1
                at = start
                for i in range(start + 1, stop):
                    if lines[i].strip():
                        at = i
                at += 1
            else:
                at = 0
                for i, ln in enumerate(lines):
                    if ln.strip():
                        at = i
                at += 1
                nl = _cfg_fixture_end(ends, at, raw)
                if at > 0 and ends[at - 1] == '':
                    ends[at - 1] = nl
                lines[at:at] = ['', '[%s]' % sec]
                ends[at:at] = [nl, nl]
                secs[sec] = at + 1
                at += 2
            nl = _cfg_fixture_end(ends, at, raw)
            if at > 0 and ends[at - 1] == '':
                ends[at - 1] = nl
            lines[at:at] = ['%s = %s' % (name, value)]
            ends[at:at] = [nl]
            _l, _e, secs, have = _cfg_fixture_parse(
                ''.join(l + e for l, e in zip(lines, ends)).encode('utf-8'))
        _cfg_fixture_write(cfg_path, raw, lines, ends)
        return True, ''
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return False, '%s: %s' % (type(e).__name__, e)


def _cfg_without_keys(cfg_path, keys):
    """Remove every key in `keys`, and any section they leave with no keys at
    all. -> (ok, reason)

    The before-a-launch shape, built from a file that may already have been
    launched against. The key's own `# Setting type:` / `# Default value:`
    comment block goes with it, because BepInEx writes the pair together and a
    fixture that left the comments behind would not look like either state.

    Only ever called on a copy under a TemporaryDirectory.
    """
    try:
        raw = read_bytes(cfg_path)
        lines, ends, secs, have = _cfg_fixture_parse(raw)
        drop = set()
        for k in keys:
            i = have.get(k)
            if i is None:
                continue
            drop.add(i)
            j = i - 1
            while j >= 0 and lines[j].lstrip().startswith('#'):
                drop.add(j)
                j -= 1
        for sec, hdr in secs.items():
            stop = hdr + 1
            while stop < len(lines) and not _FIXTURE_SEC_RE.match(lines[stop].strip()):
                stop += 1
            kept = [i for i in range(hdr + 1, stop)
                    if i not in drop and _FIXTURE_KEY_RE.match(lines[i])]
            if not kept and any(i in drop for i in range(hdr + 1, stop)):
                drop.add(hdr)
                for i in range(hdr + 1, stop):
                    if not lines[i].strip():
                        drop.add(i)
        keep = [i for i in range(len(lines)) if i not in drop]
        nl, ne = [lines[i] for i in keep], [ends[i] for i in keep]
        if ne:
            ne[-1] = ends[-1]
        _cfg_fixture_write(cfg_path, raw, nl, ne)
        return True, ''
    except (OSError, ValueError, UnicodeDecodeError) as e:
        return False, '%s: %s' % (type(e).__name__, e)


class _paths:
    """Swap REPO and SETTINGS_PATH for one block.

    selftest_source reads both as module globals, which is what lets the cases
    below construct all four of its outcomes on one machine without copying the
    tree. Same shape as _child_cmd.
    """

    def __init__(self, repo, settings_path):
        self.new = (repo, settings_path)

    def __enter__(self):
        global REPO, SETTINGS_PATH
        self.old = (REPO, SETTINGS_PATH)
        REPO, SETTINGS_PATH = self.new
        return self

    def __exit__(self, *exc):
        global REPO, SETTINGS_PATH
        REPO, SETTINGS_PATH = self.old
        return False


class _exe_at:
    """Swap EXE_DIR for one block.

    default_game_dir reads it as a module global, which is what lets the frozen
    branch be exercised from an unfrozen run. Same shape as _paths.
    """

    def __init__(self, d):
        self.new = d

    def __enter__(self):
        global EXE_DIR
        self.old = EXE_DIR
        EXE_DIR = self.new
        return self

    def __exit__(self, *exc):
        global EXE_DIR
        EXE_DIR = self.old
        return False


def _kill_tree(proc, timeout=30):
    """Kill a PyInstaller one-file process AND the application it launched.

    A one-file exe is TWO processes: the bootloader unpacks the bundle and runs
    the real application as a child. On Windows a surviving child keeps the exe
    image mapped and the file cannot be unlinked, which crashed the whole run
    out of `TemporaryDirectory` cleanup on 2026-09-04 after every case had
    passed.

    THE TREE KILL GOES FIRST, and that is the whole point. The first fix here
    tried `terminate()` and fell back to `taskkill` only on a timeout --
    but `terminate()` is `TerminateProcess` on the BOOTLOADER, which returns
    immediately, so `wait(5)` succeeded, the fallback never ran, and the
    application child was still holding the image. The run got further and
    failed on the delete instead. [measured, David, 2026-09-04]

    The return value says only that the handle this process owns has been
    reaped. It does NOT say the tree is gone -- nothing here can see the
    grandchildren -- so the caller asks `_procs_from` rather than trusting it.
    """
    if proc.poll() is not None:
        return True
    if os.name == 'nt':
        try:
            subprocess.run(['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=timeout)
        except Exception:
            pass
    else:
        try:
            os.killpg(os.getpgid(proc.pid), 15)     # SIGTERM to the group
        except Exception:
            pass
    try:
        proc.wait(timeout=10)
        return True
    except Exception:
        pass
    if os.name != 'nt':
        try:
            os.killpg(os.getpgid(proc.pid), 9)      # SIGKILL to the group
        except Exception:
            pass
    proc.kill()
    try:
        proc.wait(timeout=timeout)
        return True
    except Exception:
        return False


def _procs_from(exe_path):
    """-> the pids still running that executable, [] for none, None if it
    could not look.

    None is not zero. An instrument's silence is not evidence (AGENTS.md
    section 3), and this one is the only thing that can see a grandchild the
    Popen handle knows nothing about.

    On Windows `tasklist` filters by image NAME, so it would also count a copy
    of the same exe running from somewhere else. Nothing else in this suite is
    running one by then, and the error is toward a false FAIL rather than a
    false green.
    """
    try:
        if os.name == 'nt':
            r = subprocess.run(
                ['tasklist', '/FI', 'IMAGENAME eq %s' % os.path.basename(exe_path),
                 '/NH', '/FO', 'CSV'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
            if r.returncode != 0:
                return None
            out = r.stdout.decode('utf-8', 'replace').strip()
            if not out or 'No tasks' in out:
                return []
            return [ln.split('","')[1] for ln in out.splitlines() if ln.startswith('"')]
        r = subprocess.run(['pgrep', '-f', exe_path],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=60)
        if r.returncode not in (0, 1):
            return None
        return r.stdout.decode('utf-8', 'replace').split()
    except Exception:
        return None


def _procs_settle(exe_path, exclude=(), tries=60, delay=0.5):
    """-> the pids running exe_path that were NOT already running before, [] once
    there are none, None if the instrument could never look.

    Asking `_procs_from` once, immediately after the kill, is wrong twice, and
    both errors make the answer about something other than the check's name.

      **Windows tears a process down asynchronously.** `taskkill /F /T` returns
      when it has issued the terminations, not when they are complete, and
      `proc.wait` covers the bootloader only. `_rmtree_retry` already retries
      for exactly this reason and says so in its own docstring; the process
      question was the one place that did not, so it sampled in the middle of
      the teardown it had just started. On David's first Windows run this check
      FAILED while the delete beside it PASSED — and a running exe cannot be
      unlinked on Windows, so whatever it saw was gone within the delete's own
      30 seconds. [measured 2026-09-04]

      **`tasklist` filters by image NAME, not by path.** Any other
      CKF-Config-Editor.exe on the machine counts: the one in `dist/`, a
      player's, a previous case's. The caller takes a baseline before it
      launches anything and passes it here to be subtracted, so what is left is
      from THIS copy.

    The budget is the same 30 seconds `_rmtree_retry(tries=60)` gets, because
    the two are asking about the same teardown.

    None is still not zero (`AGENTS.md` §3). A `_procs_from` that never
    succeeded returns None from here and the caller fails the check on it,
    rather than reading could-not-look as none.
    """
    exclude = set(exclude or ())
    rest = None
    for i in range(tries):
        pids = _procs_from(exe_path)
        if pids is not None:
            rest = [p for p in pids if p not in exclude]
            if not rest:
                return rest
        if i < tries - 1:
            time.sleep(delay)
    return rest


def _rmtree_retry(path, tries=20, delay=0.5):
    """-> True if it is gone. Windows releases the lock on a just-killed
    process's image asynchronously, so a delete straight after the kill can
    still fail. Never raises: a directory left in the temp folder is worth a
    printed line, not a failed run."""
    for i in range(tries):
        try:
            shutil.rmtree(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if i == tries - 1:
                shutil.rmtree(path, ignore_errors=True)
                return not os.path.exists(path)
            time.sleep(delay)
    return not os.path.exists(path)


class _child_cmd:
    """Swap the argv builder run_check_schema uses, for one block.

    run_check_schema resolves check_schema_argv by name at call time, so this
    reaches every caller below it -- api_save's stage_and_validate included.
    That is the point: the save-blocking rules are asserted over the same code
    the server runs, with only the child process substituted.
    """

    def __init__(self, fn):
        self.fn = fn

    def __enter__(self):
        global check_schema_argv
        self.old = check_schema_argv
        check_schema_argv = self.fn
        return self

    def __exit__(self, *exc):
        global check_schema_argv
        check_schema_argv = self.old
        return False


# Three ways a check_schema child can lie, ONE PER GUARD in run_check_schema,
# each shaped so that it trips its own guard and no other. That is not a
# detail: the first version had 'crash' print nothing at all, so the
# missing-summary guard caught it, and removing the exit-code guard changed no
# result -- the fault never reached the thing under test. 'crash' now prints a
# perfectly clean summary and exits 3, so the exit code is the only thing
# wrong with it.
#
# 'clean' is the control: the same stub telling the truth about an empty
# problem set, so a refusal under the other three cannot be the stub itself
# being unrunnable.
_CHILD_STUB = '''\
import sys
mode = sys.argv[1]
SUMMARY = "%d problem(s). 1 cfg key(s) on disk, 1 declared across 10 schema file(s)."
PROBLEM = "RANGE      teampl.override[0].PowerLevelFraction 99.0 outside [0, 5]"
if mode == "crash":
    print()
    print(SUMMARY % 0)
    sys.stderr.write("the child died after printing a clean summary\\n")
    sys.exit(3)
if mode == "nosummary":
    print(PROBLEM)
    sys.exit(1)
if mode == "miscount":
    print(PROBLEM)
    print()
    print(SUMMARY % 3)
    sys.exit(1)
print()
print(SUMMARY % 0)
'''


def selftest_source(config_arg):
    """-> (path, how). The config the suite copies its fixtures from.

    It is READ and copied, never written; every case works inside a temp
    directory. So pointing this at the live game config is safe and is what a
    developer machine should do -- `<repo>/live-config` exists only in the tree
    a cloud session assembles by staging the game's config beside the checkout,
    and until 2026-09-04 it was the unconditional default, so `--selftest` with
    no `--config` died on a FileNotFoundError anywhere else. Reported by David.

    Order: what was asked for, then the assembled tree, then the game config
    that settings.json already points at.
    """
    if config_arg:
        return os.path.abspath(config_arg), 'given with --config'
    staged = os.path.join(REPO, 'live-config')
    if os.path.isdir(staged):
        return staged, 'the staged copy beside the checkout'
    try:
        live = config_dir_for(load_settings())
    except Exception:
        live = ''
    if live and os.path.isdir(live):
        return os.path.abspath(live), "the game's own config, from settings.json"
    raise SystemExit(
        'serve.py --selftest: no config to copy fixtures from.\n'
        '  looked for: %s\n'
        '              %s\n'
        'Both are read-only here -- every case runs in a temp directory -- so\n'
        'point it at the live one:\n'
        '  python gui/serve.py --selftest --config "<game>/BepInEx/config"'
        % (staged, live or '(settings.json names no game directory)'))


def selftest(config_arg, frozen_exe=None, migration=False):
    src, how = selftest_source(config_arg)
    print('CKF Hard Mode config GUI — verification')
    print('  source config (copied, never written): %s' % src)
    print('  (%s)' % how)
    t = _T()
    schemas = load_schemas()

    # Units, derived rather than spelled. Which physical file holds which
    # section is the schema's business; the checks below only need to name a
    # subsystem's own object, exactly as they did when each had a file.
    def _unit(section):
        for u in sidecar_names(schemas):
            if unit_section(u) == section:
                return u
            if unit_section(u) is None and u == 'ckf.hardmode.%s.json' % section:
                return u
            # THE THIRD LAYOUT, from Phase 3: one file per slice under
            # ckf.hardmode.d/, with no section at all. A subsystem's object is
            # now the whole file, and the name these cases ask for is the
            # file's own stem. Matched on the stem rather than on a directory
            # written down here, so the slice directory can move again without
            # this needing to know its name.
            if unit_section(u) is None and \
                    os.path.splitext(os.path.basename(u))[0] == section:
                return u
        raise KeyError('no unit for section %r' % section)

    def _sec(payload, unit):
        """The section object out of one proposed physical file's bytes."""
        d = json.loads(payload[unit_file(unit)].decode('utf-8-sig'))
        sec = unit_section(unit)
        return d[sec] if sec else d

    U_ELAPSE, U_FATIGUE = _unit('elapse'), _unit('fatigue')
    U_MISSION, U_CURVE = _unit('missions'), _unit('rewardcurve')
    U_TEAMPL = _unit('teampl')
    # U_MODELRULES was here until 2026-09-13. Its only reader was the
    # linkedEnable block in section 7, which now derives the group's keys from
    # the schema instead of naming the two units by hand.
    F_TEAMPL = unit_file(U_TEAMPL)
    F_MISSION = unit_file(U_MISSION)
    F_ELAPSE = unit_file(U_ELAPSE)

    # ---- 1. the adjustment grammar, against MissionRewards.cs:391-414
    print('\n[1] mission slot grammar')
    cases = [
        ('',        'none', None),      ('   ',      'none', None),
        ('=40',     'set', 40.0),       ('40',       'set', 40.0),
        ('=-55',    'set', -55.0),      ('+25',      'add', 25.0),
        ('-25',     'add', -25.0),      ('x1.5',     'multiply', 1.5),
        ('X1.5',    'multiply', 1.5),   ('*1.5',     'multiply', 1.5),
        ('x.75',    'multiply', 0.75),  ('=0',       'set', 0.0),
        ('0',       'set', 0.0),        ('+0',       'add', 0.0),
        ('x-2',     'multiply', -2.0),  ('=1e3',     'set', 1000.0),
        ('  =40  ', 'set', 40.0),       ('=+5',      'set', 5.0),
        ('.5',      'set', 0.5),
        # '+' strips to a body that itself carries a sign, which
        # NumberStyles.Float accepts. The C# parser takes both; so do we.
        ('++5',     'add', 5.0),   ('+-5', 'add', -5.0),
    ]
    for spec, kind, val in cases:
        r = parse_adjust(spec)
        t.check('accepts %r -> %s %s' % (spec, kind, val),
                r['ok'] and r['kind'] == kind and (val is None or abs(r['value'] - val) < 1e-12), r)
    for spec in ('abc', 'x', '=', '+', '-', '1,000', '4 2', '=4a', 'xx2', '=1.2.3',
                 '0x10', '=,', '- 25', '1 000', '%50'):
        r = parse_adjust(spec)
        t.check('rejects %r' % spec, not r['ok'], r)
    # A stated deviation, in the strict direction. .NET recognises the culture's
    # NaN and Infinity symbols in double.TryParse regardless of NumberStyles, so
    # C# would take these and hand (long)Math.Round(NaN) to the reward. Refusing
    # them here is narrower than the plugin, never wider.
    for spec in ('NaN', '=NaN', 'Infinity', '-Infinity', 'inf'):
        r = parse_adjust(spec)
        t.check('refuses %r (stricter than C#, deliberately)' % spec, not r['ok'], r)
    t.check('an unparseable spec is a hard refusal, not a warning',
            _raises(lambda: check_adjust_cell('abc', 'x', 'y'), SaveRefused))

    # ---- 2. every schema field renders
    print('\n[2] coverage: every schema field gets a control')
    with tempfile.TemporaryDirectory() as td:
        cd = _sandbox(src, os.path.join(td, 'config'))
        doc = read_document(cd, schemas)
        model, extras = build_model(doc)
        total = sum(len(s['fields']) for s in schemas)
        rendered, missed = 0, []
        for sch in schemas:
            name = sidecar_unit(sch)
            for f in sch['fields']:
                ui = f.get('ui', 'form')
                if ui == 'hidden':
                    rendered += 1
                    continue
                if f['in'] == 'cfg':
                    ok = f['path'] in model['cfg']
                elif f['in'] == 'reference':
                    # A third kind since Phase 4. Its rows are in the schema,
                    # it belongs to no unit, and it reaches the page as a table
                    # keyed by subsystem. Without this branch it landed in the
                    # json lookup, found no slot, and was reported missing --
                    # which is the coverage check doing its job on a field kind
                    # it had never been told about.
                    ok = ('%s|%s' % (sch['subsystem'], f['path'])) in model['tables']
                else:
                    slot = model['json'].get(name, {}).get(f['path'])
                    ok = slot is not None
                    if ok and f['type'] == 'table':
                        ok = slot.get('table') in model['tables']
                if ok:
                    rendered += 1
                else:
                    missed.append('%s %s' % (sch['subsystem'], f['path']))
        t.check('all %d schema fields across %d schemas are in the model'
                % (total, len(schemas)), rendered == total and not missed,
                'missing: %s' % missed)
        # The rule that keeps the renderer schema-driven, asserted rather than
        # promised: no field path, column name, cfg key or sidecar filename may
        # appear as a literal in app.html. Only `ui` values may -- those ARE the
        # dispatch. A key added to a schema gets a control because nothing here
        # was ever typed by hand.
        hits = hardcoded_names_in_app_html(schemas)
        t.check('no schema field name appears as a literal in app.html', not hits, hits)

        # The other thing a browser finds and node does not: a strict-mode
        # assignment to a name nothing declares.
        stray = undeclared_globals_in_app_html()
        t.check('every global app.html assigns to is declared', not stray, stray)

        uis = sorted(set(f.get('ui', 'form') for s in schemas for f in s['fields']))
        t.check('every ui value in use has a renderer: %s' % uis,
                set(uis) <= {'form', 'table', 'curve', 'matrix', 'readonly', 'hidden'}, uis)

        # ---- 3. round-trip
        print('\n[3] round-trip: load, save back unedited, diff')
        edits = {'cfg': {}, 'json': {}}
        for path, (_s, f) in cfg_fields(schemas).items():
            v = model['cfg'][path]
            if v['present']:
                edits['cfg'][path] = {'value': v['value']}
        for (name, path), (_s, f) in json_fields(schemas).items():
            slot = model['json'].get(name, {}).get(path)
            if not slot or not slot.get('present'):
                continue
            blk = edits['json'].setdefault(name, {'scalars': {}, 'tables': {}})
            if f['type'] == 'table':
                tbl = model['tables'][slot['table']]
                blk['tables'][path] = {'shape': tbl['shape'], 'rows': tbl['rows']}
            else:
                blk['scalars'][path] = {'present': True, 'value': slot['value']}

        # HOW MANY FILES THIS ROUND TRIP ACTUALLY REACHES, said out loud.
        # Every check below is inside a loop over the declared units. With no
        # units the loops run zero times, every one of them reports nothing,
        # and the section passes having compared no file at all -- the shape
        # AGENTS.md section 3 is about, and the shape seven instruments in this
        # repo have been caught in. Phase 3 turned one file into nine, so the
        # count is asserted rather than left to be however many there are.
        _rt_units = sidecar_names(schemas)
        _rt_files = sorted({unit_file(u) for u in _rt_units})
        _rt_versioned = sorted(
            f for f in _rt_files
            if '_version' in check_schema.load_jsonc(os.path.join(cd, f)))
        print('        round trip covers %d unit(s) in %d file(s); %d carry a '
              '_version stamp' % (len(_rt_units), len(_rt_files),
                                  len(_rt_versioned)))
        t.check('the round trip has more than one file to compare — one merged '
                'document is not what is on disk since Phase 3',
                len(_rt_files) > 1, _rt_files)
        t.check('and every declared unit resolves to a file it can read, so '
                'none of the comparisons below is skipped',
                all(os.path.exists(os.path.join(cd, unit_file(u)))
                    for u in _rt_units),
                [u for u in _rt_units
                 if not os.path.exists(os.path.join(cd, unit_file(u)))])

        for strip in (False, True):
            proposed, _notes = apply_edits(doc, extras, edits, strip_readme=strip)
            label = 'stripReadme=%s' % strip
            cfg_before = read_bytes(os.path.join(cd, 'ckf.hardmode.cfg'))
            t.check('[%s] cfg is byte-identical after an unedited save' % label,
                    proposed['ckf.hardmode.cfg'] == cfg_before,
                    _first_line_diff(cfg_before, proposed['ckf.hardmode.cfg']))
            for unit in sidecar_names(schemas):
                fname, sec = unit_file(unit), unit_section(unit)
                if fname not in proposed:
                    t.check('[%s] %s was proposed' % (label, fname), False, 'not in proposal')
                    continue
                before = check_schema.load_jsonc(os.path.join(cd, fname))
                after = json.loads(proposed[fname].decode('utf-8-sig'))
                if sec:
                    before, after = before.get(sec, {}), after.get(sec, {})
                if strip:
                    before.pop('_readme', None)
                d = _semantic_diff(before, after)
                t.check('[%s] %s round-trips semantically (absent keys still absent)'
                        % (label, unit), not d, d[:8])
            # A key belonging to no section must survive a save untouched --
            # "_version" is the one that exists today, and the migration adds
            # more. Losing it would be invisible in every per-section check
            # above, because none of them looks outside its own section.
            for fname in sorted({unit_file(u) for u in sidecar_names(schemas)}):
                if fname not in proposed:
                    continue
                b = check_schema.load_jsonc(os.path.join(cd, fname))
                a = json.loads(proposed[fname].decode('utf-8-sig'))
                claimed = {unit_section(u) for u in sidecar_names(schemas)
                           if unit_file(u) == fname}
                outside_b = dict((k, v) for k, v in b.items() if k not in claimed)
                outside_a = dict((k, v) for k, v in a.items() if k not in claimed)
                t.check('[%s] %s: keys outside every section survive the save'
                        % (label, fname), outside_b == outside_a,
                        (sorted(outside_b), sorted(outside_a)))

        # The same round trip, but actually written to disk with force=True so
        # every file really is re-serialised and replaced, not skipped as
        # unchanged. This is the version that exercises commit().
        cfg_bytes_before = read_bytes(os.path.join(cd, 'ckf.hardmode.cfg'))
        sidecar_physical = sorted({unit_file(u) for u in sidecar_names(schemas)})
        parsed_before = dict((n, check_schema.load_jsonc(os.path.join(cd, n)))
                             for n in sidecar_physical)
        check_before = run_check_schema(cd)
        proposed, _n = apply_edits(doc, extras, edits, strip_readme=False)
        commit(cd, proposed, {}, force=True)
        cfg_after = read_bytes(os.path.join(cd, 'ckf.hardmode.cfg'))
        t.check('forced write: the cfg on disk is byte-identical',
                cfg_after == cfg_bytes_before,
                _first_line_diff(cfg_bytes_before, cfg_after))
        t.check('the forced write covered every physical file, and there is '
                'more than one of them', len(sidecar_physical) > 1,
                sidecar_physical)
        for name in sidecar_physical:
            after = check_schema.load_jsonc(os.path.join(cd, name))
            dd = _semantic_diff(parsed_before[name], after)
            t.check('forced write: %s on disk is semantically identical' % name, not dd, dd[:8])
            # Phase 3 stamps each slice file with its own top-level _version.
            # It belongs to no section, so every per-section comparison above
            # is blind to it; losing it would be invisible everywhere else.
            t.check('forced write: %s keeps its _version exactly as it was'
                    % name,
                    parsed_before[name].get('_version') == after.get('_version'),
                    (parsed_before[name].get('_version'), after.get('_version')))
            # "Pure JSON" proved by strict json.loads, which rejects // comments
            # and trailing commas. A // inside a string literal is data and stays.
            t.check('forced write: %s is strict JSON (no comments, no trailing commas)' % name,
                    _strict_json(os.path.join(cd, name)))
        check_after = run_check_schema(cd)
        t.check('forced write: check_schema says exactly what it said before',
                check_after['ran'] and
                set((q['kind'], q['message']) for q in check_after['problems'])
                == set((q['kind'], q['message']) for q in check_before['problems']),
                check_after['problems'])
        doc = read_document(cd, schemas)
        model, extras = build_model(doc)

        # ---- 4. unset is not zero
        print('\n[4] unset vs zero')
        fatigue = U_FATIGUE
        # This pair used to drive runningEmpty.maxAffected, which 2026-09-07
        # removed along with every other flat fatigue value that had a
        # byPowerLevel analogue. apply_edits REFUSES a path no schema declares,
        # so the old case did not fail -- it raised and took the rest of the
        # suite with it. woundResist.minChancePercent is the same distinction
        # in a field that still exists: 0 lets Wound Resist cancel a chance
        # outright, absent means the mod's own 5.
        e2 = {'json': {fatigue: {'scalars': {'woundResist.minChancePercent':
                                             {'present': False, 'value': None}},
                                 'tables': {}}}}
        p2, _ = apply_edits(doc, extras, e2, strip_readme=False)
        js2 = _sec(p2, fatigue)
        t.check('unset scalar -> the key is absent',
                'minChancePercent' not in js2['woundResist'], sorted(js2['woundResist']))
        e3 = {'json': {fatigue: {'scalars': {'woundResist.minChancePercent':
                                             {'present': True, 'value': 0}},
                                 'tables': {}}}}
        p3, _ = apply_edits(doc, extras, e3, strip_readme=False)
        js3 = _sec(p3, fatigue)
        t.check('zero scalar -> the key is present with value 0',
                js3['woundResist'].get('minChancePercent') == 0
                and 'minChancePercent' in js3['woundResist'], js3['woundResist'])

        # Find a genuinely sparse row rather than assuming one. This block used
        # to hardcode runningEmpty.byPowerLevel row "1" and durationDays. That
        # row stopped being sparse when the fatigue curves were retuned, so the
        # check failed on the data rather than on the code -- and a reader would
        # have read the failure as a regression in the GUI. Search both curves,
        # and say plainly if neither has a sparse row instead of passing quietly.
        # Sparse rows: MAKE one rather than hoping the live config has one.
        #
        # A declared column with no key in the row comes back as null -- that
        # is the contract, and it is what this checks. This block used
        # to assume runningEmpty.byPowerLevel row "1" had no durationDays. That
        # was true of the config it was written against; the fatigue retune
        # filled every declared column of every curve, and today NO row in any
        # of the four curves is sparse. Depending on the data meant the check
        # failed for a reason that had nothing to do with the reader.
        #
        # So: drop a column from the sandbox copy, re-read, and assert the
        # reader reports it absent. The condition is created here, so the check
        # exercises the same path whatever the live numbers happen to be.
        curve_path, curve_block, sparse_col = 'runningEmpty.byPowerLevel', 'runningEmpty', 'durationDays'
        _fp = os.path.join(cd, unit_file(fatigue))
        _fj = check_schema.load_jsonc(_fp)
        _fsec = _fj[unit_section(fatigue)] if unit_section(fatigue) else _fj
        _curve = _fsec[curve_block]['byPowerLevel']
        row_key = sorted(_curve, key=lambda k: int(k))[0]
        t.check('the fixture row carries the column before it is removed',
                sparse_col in _curve[row_key], _curve[row_key])
        _curve[row_key].pop(sparse_col, None)
        with open(_fp, 'wb') as _fh:
            _fh.write((json.dumps(_fj, indent=2, ensure_ascii=False) + '\n').encode('utf-8'))
        doc = read_document(cd, schemas)
        model, extras = build_model(doc)

        key = '%s|%s' % (fatigue, curve_path)
        tbl = model['tables'][key]
        t.check('a keyedBy table is read as an object', tbl['shape'] == 'object', tbl['shape'])
        # A JSON object key is a string; the schema says the column is an int.
        # Left as read, the key column held a string until the cell was typed
        # in, and the curve chart -- which plots a point only where both
        # coordinates are numbers -- reported every point unset.
        key_types = set(type(r['cells']['powerLevel']).__name__ for r in tbl['rows'])
        t.check('the key column arrives as the type the schema declares, not a string',
                key_types == {'int'}, sorted(key_types))
        rows = json.loads(json.dumps(tbl['rows']))
        r1 = [r for r in rows if str(r['cells']['powerLevel']) == row_key][0]
        t.check('a sparse row arrives with null for the absent column',
                r1['cells'][sparse_col] is None, r1['cells'])
        r1['cells'][sparse_col] = 0
        e4 = {'json': {fatigue: {'scalars': {},
                                 'tables': {curve_path:
                                            {'shape': 'object', 'rows': rows}}}}}
        p4, _ = apply_edits(doc, extras, e4, strip_readme=False)
        js4 = _sec(p4, fatigue)
        t.check('cell set to 0 -> key present, value 0',
                js4[curve_block]['byPowerLevel'][row_key].get(sparse_col) == 0,
                js4[curve_block]['byPowerLevel'][row_key])
        r1['cells'][sparse_col] = None
        p5, _ = apply_edits(doc, extras, e4, strip_readme=False)
        js5 = _sec(p5, fatigue)
        t.check('cell set back to unset -> key absent again',
                sparse_col not in js5[curve_block]['byPowerLevel'][row_key],
                js5[curve_block]['byPowerLevel'][row_key])

        mk = U_MISSION + '|missions'
        mrows = json.loads(json.dumps(model['tables'][mk]['rows']))
        mrows[0]['cells']['BonusPayment'] = 'x1.5'
        good = {'json': {U_MISSION:
                         {'scalars': {}, 'tables': {'missions': {'shape': 'array', 'rows': mrows}}}}}
        apply_table_formats(doc, extras, model, good)
        pg, _ = apply_edits(doc, extras, good, strip_readme=False)
        t.check('a valid adjustment is accepted',
                _sec(pg, U_MISSION)['missions'][0]['BonusPayment']
                == 'x1.5')
        mrows[0]['cells']['BonusPayment'] = 'about half'
        t.check('an unparseable adjustment is refused before anything is written',
                _raises(lambda: apply_table_formats(doc, extras, model, good), SaveRefused))
        mrows[0]['cells']['BonusPayment'] = ''
        apply_table_formats(doc, extras, model, good)
        pe, _ = apply_edits(doc, extras, good, strip_readme=False)
        t.check('an empty adjustment stays an empty string, not unset',
                _sec(pe, U_MISSION)['missions'][0]['BonusPayment']
                == '')
        mrows[0]['cells']['BonusPayment'] = None
        pn, _ = apply_edits(doc, extras, good, strip_readme=False)
        t.check('an explicitly unset text cell drops the key',
                'BonusPayment' not in
                _sec(pn, U_MISSION)['missions'][0])
        # CORRECTION, 2026-08-31. This pair used to be one check asserting
        # 'shipped' in the row -- the pre-migration world, where the sidecar
        # carried annotation keys the schema does not declare and the round
        # trip had to preserve them. gui-plan.md 4.2 moved 'shipped',
        # 'roomFlags', 'objectivePayments' and 'secondaryObjectives' out to
        # docs/mission-reference.json, so the row now carries only what
        # MissionRewards.cs:264-283 deserialises. The old assertion was
        # testing for data that is deliberately no longer there; the two
        # checks below assert where it went instead.
        declared_cols = {'type', 'note', 'BonusPayment', 'BonusExperience',
                         'PowerLevelBonus', 'ObjectivePayment', 'SecondaryPayment'}
        row0 = _sec(pn, U_MISSION)['missions'][0]
        t.check('the row carries only the keys the schema declares — no '
                'annotation key survives the round trip',
                set(row0) <= declared_cols and {'type', 'note'} <= set(row0),
                sorted(set(row0) - declared_cols) or sorted(row0))
        ref = read_mission_reference()
        t.check('and read_mission_reference() finds "shipped" for that same '
                'type in docs/mission-reference.json (gui-plan.md 4.2)',
                ref['state'] == 'loaded'
                and 'shipped' in ref['byType'].get(row0['type'], {}),
                (ref['state'], row0['type'],
                 sorted(ref['byType'].get(row0['type'], {}))))

        ek = U_ELAPSE + '|tiers'
        erows = json.loads(json.dumps(model['tables'][ek]['rows']))
        std = [r for r in erows if r['cells']['name'] == 'standard'][0]
        t.check('a keyed row missing a column arrives as null',
                std['cells']['patterns'] is None, std['cells'])
        ee = {'json': {U_ELAPSE:
                       {'scalars': {}, 'tables': {'tiers': {'shape': 'object', 'rows': erows}}}}}
        pt, _ = apply_edits(doc, extras, ee, strip_readme=False)
        tiers = _sec(pt, U_ELAPSE)['tiers']
        t.check('it round-trips back as an absent key, not an empty list',
                'patterns' not in tiers['standard'], tiers['standard'])
        t.check('the key column becomes the object key, not a column',
                'name' not in tiers['standard'] and set(tiers) == {'soloHack', 'story', 'standard'},
                list(tiers))

        # ---- 5. both table shapes
        print('\n[5] two serialisation shapes behind one type')
        shapes = dict((k, v['shape']) for k, v in model['tables'].items())
        want = {
            U_ELAPSE + '|tiers': 'object',
            U_FATIGUE + '|runningEmpty.byPowerLevel': 'object',
            U_ELAPSE + '|credits.byPowerLevel': 'array',
            U_CURVE + '|curve': 'array',
            U_TEAMPL + '|override': 'array',
        }
        for k, v in want.items():
            t.check('%s is %s' % (k, v), shapes.get(k) == v, shapes.get(k))
        # The wording used to read "despite keyedBy": the schema declared
        # "keyedBy": "type" on this field while the reader correctly produced
        # an array. The keyedBy was a mistake and has been dropped
        # (SCHEMA-FORMAT.md, "keyedBy, and its one correction"), so schema and
        # reader now agree rather than disagree.
        t.check('missions is read as the array MissionRewards.cs:298 '
                'deserialises, and the schema declares no keyedBy against it',
                shapes.get(U_MISSION + '|missions') == 'array',
                shapes.get(U_MISSION + '|missions'))

        # ---- 6. column format inference
        print('\n[6] adjustment-column inference')
        mf = model['tables'][U_MISSION + '|missions']['formats']
        for c in ('BonusPayment', 'BonusExperience', 'PowerLevelBonus',
                  'ObjectivePayment', 'SecondaryPayment'):
            t.check('%s inferred as an adjustment column' % c, mf.get(c) == 'adjust', mf)
        t.check('note stays free text', mf.get('note') == 'text', mf)
        # CORRECTION, 2026-08-31. This asserted mf['type'] == 'key', which was
        # true only while missionrewards.schema.json carried "keyedBy": "type"
        # -- infer_column_formats stamps 'key' on the keyedBy column. That
        # keyedBy was wrong and was dropped, so `type` is now an ordinary
        # string column and falls to the same verdict as `note`. Nothing in
        # the GUI changed; the assertion was describing the dropped key.
        t.check('the type column is ordinary free text now that no keyedBy '
                'claims it', mf.get('type') == 'text', mf)

    # ---- 7. server, transaction, mirror, validation, backups
    print('\n[7] server and save transaction')
    with tempfile.TemporaryDirectory() as td:
        cd = _sandbox(src, os.path.join(td, 'config'))
        settings = {'gameDir': '', 'configDirOverride': cd, 'stripReadme': False}
        app = App(settings, 'test-token')

        m = app.api_model()
        declared = sum(len(sc['fields']) for sc in app.schemas)
        t.check('the model exposes all %d schema fields' % declared,
                m['fieldCount'] == declared, m['fieldCount'])
        t.check('write probe reports ok on a writable dir',
                m['probe']['config']['state'] == 'ok', m['probe']['config'])
        # Not "reports 0": the repo's own baseline is whatever check_schema says
        # about the untouched copy. Three fatigue fields were added to the schema
        # while this was being written and are not in the live sidecar, so the
        # baseline is 3 MISSING. What matters is that the GUI does not add to it.
        baseline = m['check']
        t.check('check_schema runs against the untouched copy', baseline['ran'], baseline)
        t.check('the baseline carries nothing blocking',
                not [p for p in baseline['problems'] if p['kind'] in BLOCKING],
                baseline['problems'])
        base_set = set((p['kind'], p['message']) for p in baseline['problems'])
        if base_set:
            print('        baseline (pre-existing, not caused by the GUI):')
            for k, msg in sorted(base_set):
                print('          %-10s %s' % (k, msg))

        # ---- the layout the schemas point at, whatever it is
        #
        # Phase 3 split one merged document into a file per slice under
        # ckf.hardmode.d/. Nothing below names a file or a directory: the
        # editor resolves `targets.json` against the config dir, so the split
        # needed no code change here, and THAT is what these cases assert --
        # that every declared target really resolves to a file on disk, that
        # more than one physical file is in play, and that no field went
        # quietly absent in the move. A run against a layout where they all
        # still share one file passes these too.
        units = sidecar_names(app.schemas)
        files_seen = sorted({unit_file(u) for u in units})
        owned_now = files_check_schema_reads(app.schemas)
        print('        layout: %d unit(s) across %d physical file(s); %d path(s) '
              'the editor owns' % (len(units), len(files_seen), len(owned_now)))
        print('        files: %s' % ', '.join(owned_now))
        t.check('every unit the schemas declare resolves to a file that is '
                'actually on disk — a target naming a file that is not there '
                'is the whole failure mode of a layout change',
                all(os.path.exists(os.path.join(cd, unit_file(u))) for u in units),
                [u for u in units
                 if not os.path.exists(os.path.join(cd, unit_file(u)))])
        t.check('more than one physical file holds them, so the merged-document '
                'assumption is gone rather than merely unused',
                len(files_seen) > 1, files_seen)
        t.check('every unit is readable — a unit whose file failed to parse '
                'reads as an error, not as an empty object',
                not m['sidecarErrors'], m['sidecarErrors'])
        absent_fields = [(u, p) for (u, p) in json_fields(app.schemas)
                         if not (m['values']['json'].get(u, {}).get(p) or {})
                         .get('present')]
        t.check('every json field a schema declares is present in the file its '
                'target names — %d declared' % len(json_fields(app.schemas)),
                not absent_fields, absent_fields[:8])
        # Files that are in the config directory and that NOTHING the editor
        # reads points at. Reported rather than asserted away: a slice file no
        # schema targets is invisible to this editor and to check_schema, and
        # silence about it is how it stays invisible.
        _d = os.path.join(cd, 'ckf.hardmode.d')
        _names = sorted(os.listdir(_d)) if os.path.isdir(_d) else []
        orphans = sorted(
            'ckf.hardmode.d/' + n for n in _names
            if n.lower().endswith('.json')
            and 'ckf.hardmode.d/' + n not in owned_now)
        print('        .json files in the slice directory that NO schema '
              'targets (%d): %s' % (len(orphans), ', '.join(orphans) or 'none'))
        # AND THE CSVs, WHICH THIS CENSUS DID NOT COVER UNTIL PHASE 4. It
        # filtered on `.json`, so the 33 overlay files that landed that day were
        # outside it and a reader of the line above would have had no way to
        # know. They are named here -- and NOT graded.
        #
        # WHY NOT GRADED. check_schema.py owns this answer and answers it
        # properly: it prints "overlays: N declared across M schema file(s), K
        # csv/tsv on disk, 0 unclaimed, 3 unclaimed by design (...)", carrying
        # the by-design list. Grading them here would need a second copy of that
        # list, kept in step by hand, which is the thing AGENTS.md section 9
        # forbids. SECTION_GROUPS already says in its `enemy-gear` note that
        # this editor does not open those files. So the editor names what it
        # sees and points at the gate that decides.
        csv_all = ['ckf.hardmode.d/' + n for n in _names
                   if n.lower().endswith(('.csv', '.tsv'))]
        csv_undeclared = sorted(set(csv_all) - set(overlay_paths_all(app.schemas)))
        print('        csv/tsv in the slice directory: %d, of which %d are '
              'declared by a schema as an overlay and %d are not (%s). The '
              'undeclared ones are not graded here: check_schema.py carries '
              'the list of which are unclaimed by design.'
              % (len(csv_all), len(csv_all) - len(csv_undeclared),
                 len(csv_undeclared), ', '.join(csv_undeclared) or 'none'))
        t.check('every overlay a schema declares is actually in the slice '
                'directory — a declared file that is not there draws nothing '
                'and the census above would not have said so',
                not (set(overlay_paths_all(app.schemas)) - set(csv_all)),
                sorted(set(overlay_paths_all(app.schemas)) - set(csv_all)))
        # A slice file no schema targets is invisible to this editor AND to
        # check_schema: nothing reads it, nothing validates it, and nothing
        # says so. It was 1 until 2026-09-13 -- implants-global.json, which
        # Phase 3 wrote before implantsglobal.schema.json declared a json
        # target for it -- and naming them here is what closed that gap.
        t.check('every .json file in the slice directory is reachable by some '
                'schema — one that is not is read by nothing and validated by '
                'nothing', not orphans, orphans)

        # A target naming a file that is not there: named, never invented, and
        # never allowed to take the other files down with it.
        cdmiss = _sandbox(src, os.path.join(td, 'missing-slice'))
        drop = sorted(u for u in units
                      if unit_file(u) not in
                      set(inv['source'].split('#')[0] for sc in app.schemas
                          for inv in sc.get('invariants', [])
                          if inv.get('kind') == 'mirror'))[:1]
        t.check('there is a unit to remove that is not a mirror source, so the '
                'case below measures an absent slice and not an absent pair',
                drop, [unit_file(u) for u in units])
        if drop:
            gone = unit_file(drop[0])
            os.remove(os.path.join(cdmiss, gone))
            appmiss = App({'gameDir': '', 'configDirOverride': cdmiss,
                           'stripReadme': False}, 'x')
            mmiss = appmiss.api_model()
            t.check('a target naming a file that is not there is reported by '
                    'name, as an error against that unit',
                    gone in mmiss['sidecarErrors'], mmiss['sidecarErrors'])
            t.check('and check_schema reports it MISSING, naming the file',
                    any(q['kind'] == 'MISSING' and gone in q['message']
                        for q in mmiss['check']['problems']),
                    mmiss['check']['problems'])
            t.check('and its fingerprint is null rather than absent from the '
                    'map — "could not read" and "not asked for" are different',
                    gone in mmiss['fingerprints']
                    and mmiss['fingerprints'][gone] is None,
                    mmiss['fingerprints'].get(gone, '<not in the map>'))
            t.check('and every other unit still reads',
                    sorted(mmiss['sidecarErrors']) == [gone],
                    sorted(mmiss['sidecarErrors']))
            rmiss = appmiss.api_save(_edits_for(appmiss.schemas, mmiss))
            t.check('a save with one slice file missing still succeeds for the '
                    'rest', rmiss['ok'], rmiss.get('refused'))
            t.check('and does not invent the missing file — an absent slice '
                    'stays absent rather than being created empty',
                    not os.path.exists(os.path.join(cdmiss, gone)), gone)



        # ---- overlays: declared, read, drawn, and -- since 2026-09-14 --
        #      WRITTEN, in their lever columns and nowhere else
        #
        # CORRECTION. THIS BLOCK ASSERTED THE OPPOSITE. Verbatim, as it stood:
        #
        #   "---- overlays: declared, read, drawn, and NEVER written
        #
        #    scripts/rules_to_overlays.py is the only thing that may write
        #    these files. The editor reads them to draw them and must not touch
        #    one, so that is asserted against the save path rather than left as
        #    an intention -- an overlay path may not appear in a save's
        #    proposal, and its bytes may not move across a save that rewrites
        #    everything else."
        #
        # DAVID REVERSED IT ON 2026-09-14: he could not edit any of the cells
        # this change had just created, and wants them to save the way Fatigue
        # and Elapse already do. He scoped the reversal himself -- lever and
        # override columns only; identity columns, control columns and the key
        # column stay read-only.
        #
        # THE REASON THE OLD RULE GAVE HAD ALREADY LAPSED. Phase 9 retired
        # scripts/rules_to_overlays.py together with its subject,
        # ckf.hardmode.rules.json. From that day "rules_to_overlays.py is the
        # only thing that may" named no live writer at all, so the sentence was
        # justifying the rule with a fact that had stopped being one. Nothing
        # pointed at this block from the retired script's side, so retiring it
        # could not have surfaced this; the rule went on standing unexamined
        # until David read the grid and could not type in it.
        #
        # WHAT IS ASSERTED NOW, below and in the write-path block further down:
        #   - a save that edits no cell leaves every sheet byte-identical;
        #   - a save that edits exactly one lever cell moves exactly that cell
        #     and nothing else in the file;
        #   - an identity column, a control column and the key column are still
        #     unwritable, asserted by ATTEMPTING each and requiring a refusal;
        #   - an absent or unparseable sheet is still never invented, created
        #     empty, or written.
        ov_decl = overlay_paths_all(app.schemas)
        ov_owners = [s for s in app.schemas if overlay_paths(s)]
        print('        overlays: %d path(s) declared by %d schema(s)'
              % (len(ov_decl), len(ov_owners)))
        t.check('more than one schema declares overlays, and they declare more '
                'than one file — a loop over nothing draws nothing and says so '
                'to nobody', len(ov_decl) > 1 and len(ov_owners) > 1,
                (len(ov_decl), len(ov_owners)))
        ov_read = m['values']['overlays']
        t.check('every declared overlay reached the model, keyed by its own '
                'path', sorted(ov_read) == sorted(ov_decl),
                (sorted(set(ov_decl) - set(ov_read)),
                 sorted(set(ov_read) - set(ov_decl))))
        unread = {k: v['error'] for k, v in ov_read.items() if v['error']}
        t.check('and every one of them parsed — a file that did not is named, '
                'never drawn as an empty grid', not unread, unread)
        t.check('every sheet names its first column, whatever that column '
                'turns out to be — what it has to BE is asserted per kind '
                'below, because the two kinds do not agree about it',
                all(v['keyColumn'] for v in ov_read.values()),
                [k for k, v in ov_read.items() if not v['keyColumn']])
        t.check('and every one carries at least one row, so none of the grids '
                'below is empty for want of data',
                all(v['rows'] for v in ov_read.values()),
                [k for k, v in ov_read.items() if not v['rows']])

        # ---- PHASE 8: the six consumable sheets.
        #
        # WHAT THIS BLOCK USED TO SAY, AND WHY IT DOES NOT SAY IT ANY MORE.
        #
        # Written 2026-09-14 against a tree where the six files were in the
        # slice directory and NO schema's targets.overlays named one of them.
        # `read_overlays` therefore never opened them, `ov_read` did not
        # contain them, and the page drew no grid for any of them: this file's
        # Phase 8 wiring -- the import, _family_of, DECLARED_EXPANDED and the
        # Cost label -- was live and reached no rendered sheet. The cases below
        # read the six files DIRECTLY for that reason, and three of them pinned
        # the undeclared state with their own names saying they would go red
        # the day it changed.
        #
        # It changed the same day: unit C landed targets.overlays in all six
        # schema/consumables*.schema.json, and the three pins went red exactly
        # as written [measured: rc=1, 1182 passed, 4 failed]. That was the pins
        # working, not the pins being wrong. They are restated below as what is
        # true now, and the cases that read the files directly now read THE
        # MODEL, which is what they were always about -- except the two that
        # are about the bytes on disk, which still read the bytes and say so.
        _cons_names = sorted(getattr(_consumables, 'SHEET_NAMES', ()) or ())
        _cons_rel = ['ckf.hardmode.d/' + n for n in _cons_names]
        # THE MODEL'S OWN ENTRIES, not a second read of the same files. A
        # private read_overlay call here would keep passing if api_model ever
        # stopped carrying these sheets, which is the failure the cases are
        # now positioned to catch. The direct read survives only as a FALLBACK
        # for a sheet the model does not carry, so that such a regression is
        # reported by the case below rather than ending the suite in a
        # KeyError; `_cons_from_model` says whether the fallback was used.
        _cons_from_model = [rel for rel in _cons_rel if rel in ov_read]
        _cons_read = dict(
            (rel, ov_read[rel] if rel in ov_read
             else read_overlay(os.path.join(cd, rel), rel))
            for rel in _cons_rel)
        # THE SET THE THREE CROSS-FILE CASES BELOW RUN OVER, NAMED EXACTLY.
        #
        # It is every sheet the MODEL carries, plus every sheet an EXPANDER
        # declares that the model does not. That is 53 of the 56 csv in the
        # slice directory [measured 2026-09-14]; the three it leaves out are
        # ArmorModel, MonsterTypeModel and WeaponModel, which no schema
        # declares, no expander declares, and this editor never opens --
        # check_schema owns them, as SECTION_GROUPS' enemy-gear note says.
        #
        # CORRECTION, 2026-09-14. Last round this map was introduced with three
        # case names and comments saying "every file on disk". It never was
        # that: it was ov_read plus the six, and it excluded those three enemy
        # tables then as it does now. The names have been narrowed to what is
        # measured, and the case below states which files the map omits and
        # why, instead of a sentence that rounds 53 up to 56. This is the third
        # time this phase that a set was described by a name one size larger
        # than the set.
        #
        # The extra half is still built from the DIRECTORY LISTING rather than
        # from ov_read, so that "declared by an expander but routed by no
        # schema" -- the state all six consumable sheets were in this morning
        # -- cannot become invisible again by being absent from the model.
        _extra_rel = sorted('ckf.hardmode.d/' + n for n in _names
                            if n in DECLARED_EXPANDED
                            and 'ckf.hardmode.d/' + n not in ov_read)
        _all_sheets = dict(ov_read)
        for _r in _extra_rel:
            _all_sheets[_r] = read_overlay(os.path.join(cd, _r), _r)
        print('        consumable sheets: %d declared by scripts/consumables.py, '
              '%d of them reachable through a schema\'s targets.overlays; '
              'expanded sheets on disk that the model does not carry: %d %s'
              % (len(_cons_rel), len(set(_cons_rel) & set(ov_decl)),
                 len(_extra_rel), _extra_rel or 'none'))
        t.check('scripts/consumables.py imported and declares its six sheet '
                'names — with the import broken every case below would be '
                'measuring an empty list and would pass by having nothing to '
                'look at', _consumables is not None and len(_cons_names) == 6,
                (_consumables is not None, _cons_names))
        # RESTATED, 2026-09-14. This asserted "NONE of the six is declared by a
        # schema, so the editor reads and draws no grid for them ... it goes
        # red the day one of them is declared, at which point the cases below
        # must move onto the model". Unit C declared all six; it went red; the
        # cases below moved onto the model. What is asserted now is the state
        # that replaced it, and it is the stronger of the two: a sheet that is
        # declared but does not reach the model draws nothing while every
        # census says it should.
        t.check('ALL SIX are declared by a schema and all six reached the '
                'model, keyed by their own paths — this replaces the pin that '
                'asserted none of them was declared, which went red when unit '
                'C declared them, which is what it was for',
                len(set(_cons_rel) & set(ov_decl)) == 6
                and _cons_from_model == _cons_rel,
                (sorted(set(_cons_rel) - set(ov_decl)),
                 sorted(set(_cons_rel) - set(ov_read))))
        t.check('and all six parsed — a sheet that did not is named here '
                'rather than reaching the cases below as an empty grid',
                all(e['present'] and not e['error']
                    for e in _cons_read.values()) and len(_cons_read) == 6,
                [(k, v['error']) for k, v in _cons_read.items()
                 if v['error'] or not v['present']])
        # RESTATED, 2026-09-14. This asserted the six were AMONG the undeclared
        # csv/tsv the census prints. They are not any more, and the useful half
        # of the sentence -- nothing has gone undeclared unnoticed -- survives
        # as its opposite.
        t.check('and not one of the six is in the census\'s undeclared list '
                'any more: the csv/tsv this editor can see and no schema '
                'claims are now only the enemy-gear tables it never opens '
                '(%d of them)' % len(set(csv_undeclared) - set(_cons_rel)),
                not (set(_cons_rel) & set(csv_undeclared)),
                sorted(set(_cons_rel) & set(csv_undeclared)))
        t.check('the merged map the three cross-file cases below run over is '
                'the model\'s %d sheets plus every expander-declared sheet on '
                'disk the model does not carry — %d of those today, so the '
                'two sets coincide, and this says so out loud rather than '
                'letting a coincidence pass for a property'
                % (len(ov_read), len(_extra_rel)),
                len(_all_sheets) == len(ov_read) + len(_extra_rel)
                and not _extra_rel, (_extra_rel, len(_all_sheets), len(ov_read)))
        _omitted = sorted(set(csv_all) - set(_all_sheets))
        t.check('and the %d csv in the slice directory that map leaves out are '
                'exactly the ones NO schema declares and NO expander declares '
                'either — the enemy-gear tables this editor never opens and '
                'check_schema owns. A sheet somebody meant to be edited '
                'falling outside the map turns this red' % len(_omitted),
                all(r not in ov_decl
                    and os.path.basename(r) not in DECLARED_EXPANDED
                    for r in _omitted), _omitted)
        _vals = sum(1 for v in ov_read.values()
                    for i, c in enumerate(v['columns'])
                    if i and not c['control'])
        _ctl = sum(1 for v in ov_read.values() for c in v['columns'] if c['control'])
        _ops = sum(1 for v in ov_read.values() for c in v['columns']
                   if c['op'] != 'set')
        _rows = sum(len(v['rows']) for v in ov_read.values())
        print('        overlay census: %d row(s), %d value column(s) beyond the '
              'id, %d control column(s), %d operator-suffixed column(s)'
              % (_rows, _vals, _ctl, _ops))
        t.check('the reader recognises control columns by their leading '
                'underscore, as Overlays.ParseHeader does — %d found' % _ctl,
                _ctl == len(ov_read), (_ctl, len(ov_read)))

        # ---- the two kinds of sheet, and the four (table, id) collisions
        _kinds = {}
        for rel, e in sorted(ov_read.items()):
            _kinds.setdefault(e['kind'], []).append(rel)
        print('        sheet kinds: %s'
              % ', '.join('%s %d' % (k, len(v)) for k, v in sorted(_kinds.items())))
        t.check('both kinds are on disk, so neither branch of the renderer is '
                'untested', len(_kinds) == 2, sorted(_kinds))
        # CORRECTION. Phase 4 asserted "every overlay has an id column as its
        # first column, which is what Overlays.LoadTable requires" and tested
        # only `all(v['keyColumn'])` -- that the first column has a name which
        # is not a control column. WeaponName passes that. Three expanded
        # sheets went green under a sentence that does not describe them and a
        # requirement they are not subject to [measured, Phase 6]. Each kind is
        # now asserted for what is actually true of it.
        for rel in _kinds.get('direct', []):
            e = ov_read[rel]
            want = e['table'][:-len('Model')] + 'Id'
            t.check('%s is a direct overlay: its first column is its own '
                    'table\'s id column, which is what Overlays.LoadTable '
                    'requires before it will read a line'
                    % rel.split('/')[-1], e['keyColumn'] == want,
                    (e['keyColumn'], want))
        for rel in _kinds.get('expanded', []):
            e = ov_read[rel]
            t.check('%s is an expanded sheet: its own expander reads it, so '
                    'its first column is whatever the sheet declares and need '
                    'not be an id at all' % rel.split('/')[-1],
                    bool(e['keyColumn']) and e['roles']
                    and e['roles'][0] == 'identity',
                    (e['keyColumn'], e['roles'][:1]))
            t.check('%s: and its identity columns come from the expander\'s '
                    'own declaration, not from this file guessing'
                    % rel.split('/')[-1],
                    SHEET_SOURCE_ERROR is None, SHEET_SOURCE_ERROR)

        t.check('the expander module was importable, so SHARED_ROWS, the '
                'identity columns and the collision cases are the ones it '
                'declares rather than empty defaults',
                SHEET_SOURCE_ERROR is None and SHEET_IDENTITY and SHARED_ROWS
                and COLLISION_CASES,
                (SHEET_SOURCE_ERROR, len(SHEET_IDENTITY), len(SHARED_ROWS),
                 len(COLLISION_CASES)))
        # C1-C4, copied from scripts/cyberweapons.py rather than re-derived.
        print('        (table, id) collision cases: %s'
              % ', '.join('%s %s/%s' % (c['id'], c['left'][0], c['left'][2])
                          for c in COLLISION_CASES))
        t.check('there are collision cases to exercise', COLLISION_CASES,
                len(COLLISION_CASES))
        for case in COLLISION_CASES:
            lt, _lc, lid = case['left']
            rt, _rc, rid = case['right']
            t.check('%s: %s %s and %s %s are the same NUMBER'
                    % (case['id'], lt, lid, rt, rid), lid == rid, (lid, rid))
            t.check('%s: and a key of the number alone collapses them, which '
                    'is why nothing here is keyed that way'
                    % case['id'], len({lid, rid}) == 1, (lid, rid))
            t.check('%s: while a (table, id) key keeps them apart'
                    % case['id'], len({(lt, lid), (rt, rid)}) == 2,
                    [(lt, lid), (rt, rid)])
        # Every key this editor builds for a sheet row is (file, row), and a
        # file belongs to one table -- so two tables' rows can never land on
        # one key. Asserted against the collision ids specifically.
        _ids = set()
        for rel, e in ov_read.items():
            for ri, r in enumerate(e['rows']):
                _ids.add((rel, ri))
        t.check('every sheet row the model carries is keyed by (file, row), so '
                'the %d id(s) the cases above share cannot collapse two rows '
                'into one' % len(COLLISION_CASES),
                len(_ids) == sum(len(e['rows']) for e in ov_read.values()),
                (len(_ids), sum(len(e['rows']) for e in ov_read.values())))
        _collide = set(str(c['left'][2]) for c in COLLISION_CASES)
        # OVER THE MERGED MAP -- the model's sheets plus any expander-declared
        # sheet the model does not carry -- not over `ov_read` alone. Phase 8's
        # four collision ids are all on consumable sheets, and while no schema
        # declared those, scanning `ov_read` would have found none of them and
        # the case would have gone green on the cyberweapon ids while claiming
        # to be about the whole list. Unit C has since declared them, so the
        # two sets now coincide; the map is kept because the coincidence is
        # what changed, not the requirement.
        _hits = sorted(set(
            (rel, e['columns'][ci]['name'])
            for rel, e in _all_sheets.items() for r in e['rows']
            for ci, cell in enumerate(r['cells'])
            if (cell or '').strip().lstrip('=+*xX').strip() in _collide))
        print('        cells carrying one of the colliding ids: %d %s'
              % (len(_hits), _hits[:4]))
        t.check('at least one of those ids is really on a sheet, so the cases '
                'above are about a key this build emits rather than a '
                'hypothetical one', _hits, _collide)


        # ---- the kind split, and the declaration the derivation now defers to
        _src = {}
        for rel, e in sorted(ov_read.items()):
            _src.setdefault((e['kind'], e['kindSource']), []).append(rel)
        print('        kind split: %s'
              % ', '.join('%s/%s %d' % (k[0], k[1], len(v))
                          for k, v in sorted(_src.items())))
        # EXTENDED IN PHASE 8 to the merged map rather than to `ov_read` alone.
        # The six consumable sheets are exactly the case this cross-check
        # exists for -- an expander shipping sheets that nothing else routes --
        # and while nothing routed them, measuring only `ov_read` would have
        # left them out of the one case whose whole subject they are.
        # NAME NARROWED 2026-09-14: it said "every file on disk", and the map
        # is 53 of the 56 csv there, the three enemy-gear tables excluded.
        _disagree = [rel for rel, e in _all_sheets.items()
                     if e['kind'] != overlay_kind_derived(e)]
        t.check('the expanders\' declared names and the filename derivation '
                'agree on every sheet this editor reads and on every sheet an '
                'expander declares, the six consumable sheets included — a '
                'disagreement means an expander '
                'shipped a sheet and did not declare it, which is parsed as a '
                'direct overlay against a table that does not exist and whose '
                'only symptom is an orphan warning long afterwards',
                not _disagree, _disagree)
        t.check('both routes are in use, so neither is untested: %d file(s) '
                'classified by an expander\'s own list, %d by the derivation'
                % (sum(len(v) for k, v in _src.items() if k[1] == 'declared'),
                   sum(len(v) for k, v in _src.items() if k[1] == 'derived')),
                any(k[1] == 'declared' for k in _src)
                and any(k[1] == 'derived' for k in _src), sorted(_src))
        # CORRECTION, PHASE 8. This measured DECLARED_EXPANDED against the
        # basenames in `ov_read` -- the sheets a SCHEMA declares -- under a
        # name that says "on disk". While every declared sheet was also a
        # schema target the two sets coincided and the proxy was invisible.
        # consumables.py declares six sheets that are on disk and that no
        # schema targets, and the proxy answers "missing" for all six [measured
        # 2026-09-14]. What the sentence says is what is now measured: the
        # slice directory listing. The gap the proxy was accidentally covering
        # -- declared, on disk, and reachable by nothing -- is a separate case
        # directly below, so it is stated rather than smuggled into this one.
        _on_disk = set(_names)
        t.check('every expander that declares sheet names has all of them on '
                'disk', not (DECLARED_EXPANDED - _on_disk),
                sorted(DECLARED_EXPANDED - _on_disk))
        _undrawn = sorted(DECLARED_EXPANDED
                          - set(os.path.basename(r) for r in ov_read))
        print('        sheets an expander declares that no schema targets, so '
              'the editor draws no grid for them: %d %s'
              % (len(_undrawn), _undrawn))
        # RESTATED, 2026-09-14. This asserted `_undrawn == the six consumable
        # sheets` -- "the ones on disk that this editor opens for nobody are
        # exactly these six and nothing else. Pinned, not accepted: the day a
        # seventh appears, OR ONE OF THESE SIX IS DECLARED, this goes red and
        # somebody looks." Unit C declared all six on the day it was written,
        # the case went red, and somebody looked. That is the whole of what it
        # was for, and its useful half is kept rather than deleted: the set is
        # still printed, and an expander sheet that reaches no schema is still
        # a thing this goes red over -- the expected size of that set is simply
        # 0 now instead of 6.
        t.check('every sheet an expander declares is not only on disk but '
                'reachable through some schema\'s targets.overlays, so none of '
                'them is a file the editor opens for nobody. The day a seventh '
                'is shipped without a schema to route it, this goes red and '
                'somebody looks — which is exactly what it did when it held '
                'these six',
                _undrawn == [], _undrawn)

        # ---- a one-row sheet is a grid like any other
        #
        # WAS, until 2026-09-14, under the heading "one row is a form":
        #
        #   _forms = sorted(rel for rel, e in ov_read.items() if e['form'])
        #   _multi = [rel for rel, e in ov_read.items()
        #             if e['kind'] == 'expanded' and not e['form']]
        #   t.check('exactly the one-row expanded sheet(s) are drawn as a
        #           form, and the discriminator is the row count in the file
        #           -- nothing declares it and no schema field carries it', ...)
        #   t.check('and there is one of each, so neither the form nor the
        #           grid branch is untested', _forms and _multi, ...)
        #
        # David overruled the one-row form on 2026-09-14 after seeing the page.
        # The two cases above are not LOOSENED to fit -- they had a subject and
        # it is gone, so they are replaced by cases stating the new truth: a
        # one-row sheet renders through the same grid path as every other
        # sheet, with editable lever cells, and NOTHING anywhere still carries
        # the old discriminator.
        _one = sorted(rel for rel, e in ov_read.items()
                      if e['kind'] == 'expanded' and len(e['rows']) == 1)
        _multi = sorted(rel for rel, e in ov_read.items()
                        if e['kind'] == 'expanded' and len(e['rows']) != 1)
        print('        expanded sheets of exactly one row: %s'
              % (', '.join(r.split('/')[-1] for r in _one) or 'none'))
        t.check('no entry carries a `form` key any more — the key is gone from '
                'the payload as well as from the page, so there is no dead '
                'field for a later reader to think is live',
                all('form' not in e for e in ov_read.values()),
                sorted(r for r, e in ov_read.items() if 'form' in e))
        t.check('there is still a one-row expanded sheet and a multi-row one, '
                'so "renders like the others" has something to be about and '
                'something to be compared against: %d one-row, %d multi-row'
                % (len(_one), len(_multi)), bool(_one) and bool(_multi),
                (len(_one), len(_multi)))
        # The complaint that started the thread was a lever cell that could not
        # be typed into. A one-row sheet has to offer the same boxes as any
        # other, so the grading is asserted here and the INPUTS themselves are
        # asserted in the DOM render.
        for rel in _one:
            e = ov_read[rel]
            _ed = [i for i, b in enumerate(e['editable']) if b]
            t.check('%s: one row, and its lever columns are graded editable on '
                    'the same terms as a sheet of twenty-seven — %d of %d '
                    'column(s), never index 0, never identity, never control'
                    % (rel.split('/')[-1], len(_ed), len(e['columns'])),
                    e['writable'] and _ed and 0 not in _ed
                    and all(e['roles'][i] == 'lever' for i in _ed),
                    (_ed, e['roles']))

        # ---- five columns hidden by name, at every row count
        #
        # DAVID, 2026-09-14: "Suppress the ImplantLevel, Deactivated, Rarity,
        # PowerLevel, and ImplactConflict columns." HIDDEN_COLUMNS is the
        # declared table; this is the measurement that had to come back clean
        # before anything was hidden, re-derived on every run rather than
        # quoted from the day it was taken.
        #
        # HIDING AN EDIT DAVID MADE IS THE FAILURE MODE. `Rarity` and
        # `PowerLevel` are real levers on sheets where an override could
        # plausibly sit, and he asked for this having looked at one page. So
        # the non-blank cells are counted, per column per sheet, and a single
        # one goes red.
        _hid_seen, _hid_filled, _hid_cells = {}, {}, {}
        for rel, e in sorted(ov_read.items()):
            names = [c['name'] for c in e['columns']]
            for i, n in enumerate(names):
                if i == 0 or n not in HIDDEN_COLUMNS:
                    continue
                _hid_seen.setdefault(n, []).append(rel)
                _hid_cells[n] = _hid_cells.get(n, 0) + len(e['rows'])
                filled = sum(1 for r in e['rows']
                             if i < len(r['cells']) and r['cells'][i].strip())
                if filled:
                    _hid_filled.setdefault(n, []).append((rel, filled))
        for n in sorted(HIDDEN_COLUMNS):
            print('        hidden %-18s %2d sheet(s), %4d cell(s), %d non-blank'
                  % (n, len(_hid_seen.get(n, [])), _hid_cells.get(n, 0),
                     sum(c for _, c in _hid_filled.get(n, []))))
        t.check('every name in the declared hide table is on at least one sheet '
                'this editor opens — a name that matches nothing is a typo '
                'nobody would ever see fail',
                all(_hid_seen.get(n) for n in HIDDEN_COLUMNS),
                sorted(n for n in HIDDEN_COLUMNS if not _hid_seen.get(n)))
        t.check('and not one cell being hidden carries an override. Rarity and '
                'PowerLevel are genuine levers on these sheets; hiding a value '
                'somebody set is the failure this counts for',
                not _hid_filled, _hid_filled)
        t.check('the hide reaches a one-row sheet as well as multi-row ones — '
                'it is DECLARED, not derived from constancy, so the fewer-than-'
                'two-rows exemption that the constancy rule needs does not '
                'apply to it',
                any(len(ov_read[r]['rows']) == 1
                    for rels in _hid_seen.values() for r in rels),
                {n: len(v) for n, v in _hid_seen.items()})
        t.check('no hidden column is a key column: overlay_hidden never marks '
                'index 0, so no sheet can be hidden down to nothing',
                all(e['hidden'][0] is None for e in ov_read.values()
                    if e.get('hidden')),
                sorted(r for r, e in ov_read.items()
                       if e.get('hidden') and e['hidden'][0] is not None))
        # The two sheets that DO carry a PowerLevel on every row are the enemy
        # gear tables, which no schema declares and this editor never opens.
        # Asserted rather than assumed: read_overlay is only ever reached for a
        # path some schema names, so the hide cannot touch them.
        _unclaimed = ['ckf.hardmode.d/ArmorModel.csv',
                      'ckf.hardmode.d/WeaponModel.csv',
                      'ckf.hardmode.d/MonsterTypeModel.csv']
        t.check('the sheets check_schema reports unclaimed by design are not '
                'read by this editor at all, so no column of theirs is hidden, '
                'drawn, or written: %s' % ', '.join(r.split('/')[-1]
                                                    for r in _unclaimed),
                all(r not in ov_read for r in _unclaimed),
                [r for r in _unclaimed if r in ov_read])
        # HIDING IS NOT DROPPING, and this is where that is a fact rather than
        # a promise: the column is still in the entry the page renders from,
        # still carries its role and its editability, and a save is built from
        # the file rather than from what is on screen.
        _hidden_any = [(rel, i) for rel, e in sorted(ov_read.items())
                       for i, h in enumerate(e.get('hidden') or []) if h]
        t.check('a hidden column is still a column: %d of them across the '
                'config, every one still in the payload with its name, its '
                'role and its editability intact' % len(_hidden_any),
                _hidden_any and all(
                    ov_read[rel]['columns'][i]['name'] in HIDDEN_COLUMNS
                    and ov_read[rel]['roles'][i]
                    and isinstance(ov_read[rel]['editable'][i], bool)
                    for rel, i in _hidden_any),
                len(_hidden_any))
        t.check('and the reason travels with it, so the page never has to say '
                '"never changes" about a column hidden for another reason',
                all(isinstance(ov_read[rel]['hidden'][i], str)
                    and ov_read[rel]['hidden'][i]
                    for rel, i in _hidden_any),
                sorted(set(ov_read[rel]['hidden'][i] for rel, i in _hidden_any)))
        # The declared hide and the constancy fact are SEPARATE facts. A column
        # can be both; the page must still be able to tell them apart.
        t.check('`hidden` and `constant` are published as two independent '
                'per-column facts of the same length, so neither can be read '
                'off the other',
                all(len(e['hidden']) == len(e['columns'])
                    and len(e['constant']) == len(e['columns'])
                    for e in ov_read.values() if e.get('columns')),
                [(r, len(e['columns']), len(e.get('hidden') or []),
                  len(e.get('constant') or []))
                 for r, e in ov_read.items()
                 if e.get('columns') and (len(e.get('hidden') or [])
                                          != len(e['columns']))][:4])

        # ---- file order, and a sort that would silently break it
        _ordered = [rel for rel, e in ov_read.items() if e['fileOrder']]
        t.check('every expanded sheet is marked as file-ordered',
                len(_ordered) == len([1 for e in ov_read.values()
                                      if e['kind'] == 'expanded']),
                len(_ordered))
        _would_move = []
        for rel in sorted(_ordered):
            e = ov_read[rel]
            names = [c['name'] for c in e['columns']]
            sh = e['shipped']
            if len(sh) != len(e['rows']):
                continue
            for ci, cn in enumerate(names):
                if e['roles'][ci] != 'lever':
                    continue
                vals = []
                for ri in range(len(e['rows'])):
                    v = sh.get(str(ri), {}).get(cn)
                    if v is None:
                        vals = None
                        break
                    try:
                        vals.append(float(v))
                    except ValueError:
                        vals = None
                        break
                if vals and vals != sorted(vals):
                    _would_move.append((rel.split('/')[-1], cn))
        print('        (sheet, column) pairs where sorting by the column would '
              'move rows off file order: %d' % len(_would_move))
        t.check('at least one expanded sheet has a numeric column that does '
                'NOT order its rows — that is the case file order exists for, '
                'and a grid that sorted by a numeric column would silently '
                'reorder tiers no column orders', _would_move,
                [r for r in _ordered])

        # ---- the same column name, THREE quantities
        _labelled = sorted((rel, n, v['label'])
                           for rel, e in ov_read.items()
                           for n, v in (e['labels'] or {}).items())
        _by_label = {}
        for rel, n, lab in _labelled:
            _by_label.setdefault((n, lab), []).append(rel.split('/')[-1])
        # Every sheet that CARRIES the column, labelled or not. The census
        # above counts the labelled ones and cannot see a bare one, which is
        # the whole failure mode: the column drawn under its own bare name on a
        # sheet where it means something else again.
        _cost_sheets = sorted(rel.split('/')[-1] for rel, e in ov_read.items()
                              if any(c['name'] == 'Cost' for c in e['columns']))
        _cost_bare = sorted(set(_cost_sheets)
                            - set(f for v in _by_label.values() for f in v))
        print('        columns relabelled by the expander that owns the sheet: '
              '%s; sheets carrying Cost: %d, of which %d draw it bare %s'
              % (', '.join('%s -> %s on %d sheet(s)' % (k[0], k[1], len(v))
                           for k, v in sorted(_by_label.items())),
                 len(_cost_sheets), len(_cost_bare), _cost_bare or ''))
        # WAS `len(set(labels)) == 2`, under the name "two different labels".
        # Correct until Phase 8 gave Cost a third meaning on the six consumable
        # sheets; then the data said three and the case said two, and it went
        # red [measured 2026-09-14]. THREE is the true number and checking it
        # is stronger than checking "more than one", so the count is asserted
        # exactly -- per label as well as in total. A label that silently
        # gained or lost a sheet is the drift this repo keeps getting bitten
        # by, and `>= 2` would not see it.
        _lab_n = dict((k[1], len(v)) for k, v in _by_label.items())
        t.check('one column name is drawn under THREE different labels, '
                'because it is three different quantities and all three are on '
                'screen at once: Install cost on 11 implant slot sheets, Item '
                'value on 2 cyberweapon sheets, Shop price on 6 consumable '
                'sheets — 19 sheets, counted per label, not merely more than '
                'one',
                len(set(k[0] for k in _by_label)) == 1
                and _lab_n == {'Install cost': 11, 'Item value': 2,
                               'Shop price': 6}, sorted(_by_label))
        t.check('and NO sheet draws Cost bare: all %d sheets that carry the '
                'column carry a label for it, so the column never appears '
                'explained on some sheets and unexplained on others'
                % len(_cost_sheets),
                _cost_sheets and not _cost_bare, _cost_bare)
        t.check('and the label is chosen by which expander declares the sheet, '
                'not by the file name — every sheet of a family gets the same '
                'label',
                all(len(set(_family_of('x/' + f) for f in v)) == 1
                    for v in _by_label.values()), sorted(_by_label))

        # ---- the shared rows the expander itself finds
        _em = sorted((rel, m['kind'], m['id'], tuple(m['owners']))
                     for rel, e in ov_read.items() for m in e['expanderMarks'])
        print('        marks the expanders found in the sheets: %s' % (_em or 'none'))
        t.check('the expander found a shared row in a sheet, consumed from its '
                'own expand() rather than re-derived here', _em, _em)
        for rel, kind, eid, owners in _em:
            t.check('%s: effect %d is marked %s and names %d owner(s), so a '
                    'divergent edit can be refused naming both'
                    % (rel.split('/')[-1], eid, kind, len(owners)),
                    kind == 'blocking' and len(owners) > 1, (kind, owners))
        # AND WHAT IT CANNOT FIND, MEASURED RATHER THAN ASSUMED. The other
        # disposition -- informational, for a row whose other owners have no
        # table -- needs those owners as an input, and they come from a dump.
        _blind = sorted(rel for rel, e in ov_read.items() if e['sharedBlind'])
        t.check('every sheet the expander reads carries the note saying which '
                'shared rows it cannot see from the config directory',
                len(_blind) == len([1 for rel in ov_read
                                    if _family_of(rel) == 'implants']),
                (len(_blind), sorted(_blind)[:2]))
        if _implants is not None:
            _e1 = [e for rel, e in ov_read.items()
                   if _family_of(rel) == 'implants' and e['rows']][0]
            _hdr = [c['name'] for c in _e1['columns']]
            _rws = [list(r['cells']) for r in _e1['rows']]
            _m_no, _m_yes = [], []
            _implants.expand(_hdr, _rws, os.path.basename(_e1['path']), [], _m_no, {})
            # The column the expander resolves an effect against is its own
            # EFFECT_KEY, not a member of EFFECT_IDENTITY -- those are the
            # EffectModel table's own columns and these sheets carry none of
            # them. Reading the wrong one found no effect id, produced no mark
            # either way, and the case compared 0 against 0 [measured]: an
            # assertion that passes on a broken mechanism and a missing input
            # alike. It names the key the expander names.
            _ekey = getattr(_implants, 'EFFECT_KEY', None)
            _eidc = _hdr.index(_ekey) if _ekey in _hdr else None
            _any_eid = next((int(r[_eidc]) for r in _rws
                             if _eidc is not None
                             and (r[_eidc] or '').strip().isdigit()
                             and int(r[_eidc])), None)
            t.check('an effect id was found in the sheet to drive the case '
                    'below — without one it compares nothing against nothing',
                    _any_eid, (_ekey, _eidc))
            if _any_eid:
                _implants.expand(_hdr, _rws, os.path.basename(_e1['path']), [],
                                 _m_yes, {_any_eid: [(1, 'a row with no table', 100)]})
            t.check('the informational disposition is missing because its '
                    'INPUT is missing, not because the mechanism is broken: '
                    'the same call produces %d mark(s) with no unshown owners '
                    'and %d when one is supplied'
                    % (len(_m_no), len(_m_yes)),
                    len(_m_yes) > len(_m_no)
                    and any(m[0] == 'informational' for m in _m_yes),
                    ([m[0] for m in _m_no], [m[0] for m in _m_yes]))


        # ---- the help sentences the rows themselves do not show
        #
        # A row-level fact a reader can check is one thing; a table-level fact
        # that is TRUE BECAUSE OF WHAT IS NOT IN THE TABLE is another, and only
        # the help text can carry it. These assert the sentence is present and
        # that the rows it makes an exception of are actually on the page --
        # a sentence naming an exception that is not drawn is worse than none.
        _by_sub = dict((sc['subsystem'], sc) for sc in app.schemas)
        _doc_of = lambda sub: ' '.join(_by_sub[sub].get('doc') or []).lower()
        _crit_rows = []
        for rel, e in sorted(ov_read.items()):
            if _family_of(rel) != 'implants':
                continue
            names = [c['name'] for c in e['columns']]
            crit = [n for n in names if n.startswith('CritMulti')]
            for ri, r in enumerate(e['rows']):
                sh = e['shipped'].get(str(ri), {})
                nz = dict((c, sh[c]) for c in crit if c in sh and _nonzero(sh[c]))
                if nz:
                    _crit_rows.append((rel.split('/')[-1], r['cells'][0], nz))
        _kept = [x for x in _crit_rows if not all(k.endswith('Base') for k in x[2])]
        print('        implant rows shipping a non-zero crit multiplier: %d, '
              'of which %d keep one no rule touches: %s'
              % (len(_crit_rows), len(_kept),
                 ', '.join('%s (%s)' % (x[1], ', '.join('%s %s' % kv
                                                        for kv in sorted(x[2].items())))
                           for x in _kept)))
        t.check('there are implant rows shipping a non-zero crit multiplier at '
                'all, so the sentence below has a subject', _crit_rows,
                len(_crit_rows))
        t.check('and more than one of them keeps a multiplier of the kind no '
                'rule zeroes — those rows must be visible rather than absent, '
                'because the help text makes them the exception',
                len(_kept) > 1, _kept)
        t.check('every one of those rows is drawn with its value rather than '
                'dropped', all(any(r['cells'][0] == name
                                   for r in ov_read['ckf.hardmode.d/' + f]['rows'])
                               for f, name, _v in _kept),
                [x[1] for x in _kept])
        # the sentence itself, matched case-insensitively: it is written in
        # capitals in the schema and a lowercase substring test missed it here
        # before this line was written [measured, and corrected before it was
        # reported as an absence].
        _sub_of = {}
        for sch in app.schemas:
            for rel in overlay_paths(sch):
                _sub_of[os.path.basename(rel)] = sch['subsystem']
        _crit_files = sorted(set(x[0] for x in _crit_rows))
        _carriers = [f for f in _crit_files
                     if 'every implant effect in the game' in _doc_of(_sub_of[f])]
        print('        sheets whose help carries the table-level crit '
              'sentence: %s' % (', '.join(_carriers) or 'none'))
        t.check('the table-level sentence — that after the rules run the '
                'multiplier is zero on EVERY implant effect in the game, which '
                'no row shows — is in the help of the slice that owns those '
                'rows', _carriers, _crit_files)
        # file order, said in the help of the slices whose rows it reorders
        _fo = sorted(os.path.basename(r) for r, e in ov_read.items()
                     if e['fileOrder'] and os.path.basename(r) in _sub_of
                     and 'file order' in _doc_of(_sub_of[os.path.basename(r)]))
        print('        sheets whose help says the rows are in file order: %d %s'
              % (len(_fo), _fo))
        t.check('the slices whose numeric column does not order their rows say '
                'so in their help, so a reader is not left to infer it from a '
                'grid that looks sorted', _fo, _fo)

        # ---- the sheets that override nothing
        for rel, e in sorted(ov_read.items()):
            if e['kind'] != 'expanded':
                continue
            lev = [i for i, r in enumerate(e['roles']) if r == 'lever']
            idc = [i for i, r in enumerate(e['roles']) if r == 'identity']
            filled = [(r['cells'][0], e['columns'][i]['name'])
                      for r in e['rows'] for i in lev if (r['cells'][i] or '').strip()]
            idfilled = sum(1 for r in e['rows'] for i in idc
                           if (r['cells'][i] or '').strip())
            print('        %s: %d row(s), %d override cell(s) filled, %d '
                  'identity cell(s) filled'
                  % (rel.split('/')[-1], len(e['rows']), len(filled), idfilled))
            t.check('%s: its identity columns are graded as identity rather '
                    'than counted as overrides — %d identity cell(s) carry a '
                    'value, and every one of them would have been a phantom '
                    'override without the roles'
                    % (rel.split('/')[-1], idfilled), idc, (idc, idfilled))
            if filled:
                continue
            # A SHEET THAT OVERRIDES NOTHING. Every lever cell blank on every
            # row is a statement, not an omission, and the page has to say so
            # or 16 empty rows read as 16 rows somebody forgot.
            # WAS `len(e['rows']) > 1`, as a proxy for "there is more than
            # one row to lose". Phase 7 landed a sheet with exactly one row --
            # slot 11, which design.md section 7 then drew as a form for that
            # reason -- and the proxy failed on a sheet that is correct. What
            # the case is for is that every row the file carries reaches the
            # page, so that is what it counts. (The form is gone as of
            # 2026-09-14, David having overruled it; the past tense above is
            # the correction, and the case itself never depended on the shape.)
            t.check('%s: all %d of its row(s) reach the page even though it '
                    'overrides nothing'
                    % (rel.split('/')[-1], len(e['rows'])),
                    len(e['rows']) >= 1
                    and len(e['shipped']) == len(e['rows']), len(e['rows']))
            t.check('%s: and the page says the blanks are deliberate rather '
                    'than leaving %d empty rows to speak for themselves'
                    % (rel.split('/')[-1], len(e['rows'])),
                    any('not an omission' in n for n in e['notes']), e['notes'])
            t.check('%s: and every row still states what it ships, so a blank '
                    'cell shows a number rather than nothing'
                    % rel.split('/')[-1],
                    len(e['shipped']) == len(e['rows']),
                    (len(e['shipped']), len(e['rows'])))

        # ---- the shared row: consumed, not re-derived
        # OVER THE MERGED MAP. SHARED_ROWS gained consumables.py's two rows
        # this phase, and while their sheets were not schema targets the
        # owner-count case below would have compared 4 marks against 9 declared
        # owners and failed -- correctly, because it would have been measuring
        # marks over a set of sheets smaller than the set of declarations it
        # was counting against. It measures both over the same set now, and
        # that stays true whether or not a schema routes the sheet: the
        # declarations come from the expanders, so the marks must be looked for
        # everywhere an expander's sheet is, not only where a schema points.
        _marked = sorted((rel, k) for rel, e in _all_sheets.items()
                         for k in (e['shared'] or {}))
        print('        shared-row marks: %d %s' % (len(_marked), _marked))
        t.check('the declared shared row is marked on the sheet that owns it',
                _marked, sorted(SHARED_ROWS))
        for rel, key in _marked:
            mark = _all_sheets[rel]['shared'][key]
            t.check('%s %s: the mark names the OTHER owner, not this row'
                    % (rel.split('/')[-1], key), mark['others']
                    and len(mark['others']) < len(mark['owners']),
                    (mark['others'], mark['owners']))
            t.check('%s %s: and says the cell is a repoint — neither sheet '
                    'carries a column for what the shared row does, so no '
                    'edit here can make the two diverge in that'
                    % (rel.split('/')[-1], key),
                    mark['repoint'] and mark['column']
                    and mark['column'] not in [c['name'] for c in
                                               _all_sheets[rel]['columns']
                                               if c['name'] == mark['target'].split()[0]],
                    (mark['repoint'], mark['column'], mark['target']))
        t.check('one mark per declared owner — %d owner(s), %d mark(s). '
                'Counting (row, column) pairs instead is how an agent reported '
                'nine shared rows where five were one talent whose two pointer '
                'columns hold the same id and cannot diverge from itself'
                % (sum(len(v.get('owners') or []) for v in SHARED_ROWS.values()),
                   len(_marked)),
                len(_marked) == sum(len(v.get('owners') or [])
                                    for v in SHARED_ROWS.values()),
                (len(_marked), sorted(SHARED_ROWS)))

        # ---- PHASE 8: WHAT THE SIX CONSUMABLE SHEETS HAVE TO BE.
        #
        # Graded against THE MODEL -- these entries are the ones api_model
        # carries and the page draws -- and against consumables.py's own
        # declarations. Nothing below retypes a header, a row count or an id.
        # Each case says in its own name what it could not look at.
        #
        # MOVED ONTO THE MODEL 2026-09-14. Every case here read the six files
        # directly while no schema declared them; unit C declared them and they
        # now read `ov_read`. THE TWO EXCEPTIONS ARE DELIBERATE AND ARE ABOUT
        # THE BYTES: the per-file row total below, and the Striatum
        # on-disk-versus-drawn case further down. Both exist to say that the
        # file and the grid differ by exactly one row, and a claim about the
        # file cannot be settled by asking the thing that parsed it.
        _cons_sheets = getattr(_consumables, 'SHEETS', ()) or ()
        # ROWS DRAWN + ROWS WITHHELD, out of the model.
        _cons_model_rows = dict((rel, len(e['rows']) + len(e['excluded']))
                                for rel, e in _cons_read.items())
        # AND THE SAME COUNT OUT OF THE BYTES, parsed here and not by the entry
        # under test. Counting only the model's drawn rows would make the
        # withheld row disappear from the census as well as from the grid,
        # which is the failure this phase is guarding; counting only the
        # model's own total would take the parser's word for what the file
        # holds.
        _cons_on_disk = {}
        for rel in _cons_rel:
            _b = list(csv.reader(read_bytes(os.path.join(cd, rel))
                                 .decode('utf-8-sig').splitlines()))
            _cons_on_disk[rel] = len([r for r in _b[1:]
                                      if any((c or '').strip() for c in r)])
        _cons_declared = dict(('ckf.hardmode.d/' + s.name, s.rows)
                              for s in _cons_sheets)
        print('        consumable rows per sheet (bytes on disk / model drawn '
              '+ withheld / declared by consumables.py): %s'
              % ', '.join('%s %d/%d/%s'
                          % (r.split('/')[-1], _cons_on_disk[r],
                             _cons_model_rows[r], _cons_declared.get(r, '-'))
                          for r in _cons_rel))
        t.check('the rows the MODEL carries for each sheet — drawn plus '
                'withheld — are the rows the FILE holds, counted from the '
                'bytes by this case rather than taken from the entry that is '
                'under test',
                _cons_model_rows == _cons_on_disk,
                [(r, _cons_model_rows[r], _cons_on_disk[r]) for r in _cons_rel
                 if _cons_model_rows[r] != _cons_on_disk[r]])
        t.check('exactly six consumable sheets, and consumables.py declares a '
                'row count for every one of them — without that the total '
                'below would be a sum over whatever happened to be there',
                len(_cons_read) == 6
                and sorted(_cons_declared) == sorted(_cons_rel),
                (len(_cons_read), sorted(set(_cons_rel) ^ set(_cons_declared))))
        t.check('73 data rows across exactly those six files, AND each sheet '
                'holds the count consumables.py measured — a total that came '
                'out right while two sheets had swapped rows does not pass '
                'this. WHAT IT CANNOT LOOK AT: the dump is not in a config '
                'directory and is not read here, so the 73 is consumables.py\'s '
                'declared per-sheet count, which its own --check re-measures '
                'against the dump on every run',
                sum(_cons_on_disk.values()) == 73
                and _cons_on_disk == _cons_declared,
                (sum(_cons_on_disk.values()),
                 [(r, _cons_on_disk[r], _cons_declared.get(r))
                  for r in _cons_rel if _cons_on_disk[r] != _cons_declared.get(r)]))

        # ---- the six ItemTypeId sets: disjoint, and 73 between them
        _cons_ids = {}
        for rel, e in sorted(_cons_read.items()):
            _n = [c['name'] for c in e['columns']]
            _i = _n.index('ItemTypeId') if 'ItemTypeId' in _n else None
            _cons_ids[rel] = ([] if _i is None else
                              [(r['cells'][_i] or '').strip() for r in e['rows']]
                              + [x['id'] for x in e['excluded']
                                 if x['column'] == 'ItemTypeId'])
        _seen, _overlap = {}, []
        for rel in _cons_rel:
            for v in _cons_ids[rel]:
                if v in _seen and _seen[v] != rel:
                    _overlap.append((v, _seen[v], rel))
                _seen[v] = rel
        print('        consumable ItemTypeId sets: %s; union %d; overlaps %s'
              % (', '.join('%s %d' % (r.split('/')[-1], len(_cons_ids[r]))
                           for r in _cons_rel), len(_seen), _overlap or 'none'))
        t.check('every consumable row carries an ItemTypeId, no sheet repeats '
                'one of its own, and the six sets are pairwise disjoint — two '
                'sheets carrying one id would put two different items on one '
                'editor key',
                all(len(_cons_ids[r]) == _cons_on_disk[r] and all(_cons_ids[r])
                    and len(set(_cons_ids[r])) == len(_cons_ids[r])
                    for r in _cons_rel) and not _overlap,
                (_overlap, dict((r, len(_cons_ids[r])) for r in _cons_rel)))
        t.check('and their union is 73 ids, the same 73 as the row count — so '
                'the six sets PARTITION the rows rather than merely summing to '
                'the right number',
                len(_seen) == 73 and len(_seen) == sum(_cons_on_disk.values()),
                (len(_seen), sum(_cons_on_disk.values())))

        # ---- the columns that must not be there
        _dead = list(getattr(_consumables, 'DEAD_TALENT_COLUMNS', ()) or ())
        _dead_hits = sorted((rel.split('/')[-1], c['name'])
                            for rel, e in _cons_read.items()
                            for c in e['columns'] if c['name'] in _dead)
        t.check('consumables.py declares the five dead columns, so the case '
                'below is measured against a list rather than against an empty '
                'one that nothing can fail', len(_dead) == 5, _dead)
        t.check('none of the five dead columns — %s — is in ANY of the six '
                'generated headers' % ', '.join(_dead), not _dead_hits,
                _dead_hits)
        _adj = getattr(_consumables, 'ADJUSTED_PREFIX', 'Adjusted')
        _adj_hits = sorted((rel.split('/')[-1], c['name'])
                           for rel, e in _cons_read.items() for c in e['columns']
                           if c['name'].startswith(_adj))
        t.check('and no %s* column is in any of the six headers either — that '
                'family is a scope question put to the project owner and this '
                'build answers it neither way. (AlternateAdjustment is not one '
                'of them and is expected to be present)' % _adj,
                not _adj_hits, _adj_hits)

        # ---- expanded, by declaration, with the derivation agreeing
        print('        consumable kind/source: %s'
              % ', '.join('%s %s/%s' % (r.split('/')[-1], _cons_read[r]['kind'],
                                        _cons_read[r]['kindSource'])
                          for r in _cons_rel))
        t.check('all six classify as EXPANDED and by DECLARATION — '
                'consumables.py names them, so none is parsed as a direct '
                'overlay against a table called "consumables-medicalModel", '
                'whose only symptom would be an orphan warning long afterwards',
                all(_cons_read[r]['kind'] == 'expanded'
                    and _cons_read[r]['kindSource'] == 'declared'
                    for r in _cons_rel),
                [(r, _cons_read[r]['kind'], _cons_read[r]['kindSource'])
                 for r in _cons_rel])
        t.check('and the filename derivation independently reaches expanded '
                'for all six, which is the cross-check the '
                'declared-vs-derived case above now runs over these files too',
                all(overlay_kind_derived(_cons_read[r]) == 'expanded'
                    for r in _cons_rel),
                [(r, overlay_kind_derived(_cons_read[r])) for r in _cons_rel])
        t.check('_family_of returns consumables for all six, so the fourth '
                'branch is taken and not one of them falls through to '
                '"declared by no expander"',
                all(_family_of(r) == 'consumables' for r in _cons_rel),
                [(r, _family_of(r)) for r in _cons_rel])

        # ---- Cost, the third quantity, and its scope
        _cons_cost = dict(
            (rel, (overlay_labels(e).get('Cost') or {}).get('label'))
            for rel, e in _cons_read.items())
        _has_cost = sorted(r for r in _cons_rel
                           if any(c['name'] == 'Cost'
                                  for c in _cons_read[r]['columns']))
        print('        Cost: on %d of the six headers, labelled on %d, as %s'
              % (len(_has_cost), len([v for v in _cons_cost.values() if v]),
                 sorted(set(v for v in _cons_cost.values() if v)) or 'nothing'))
        t.check('Cost is live on ALL SIX consumable headers, not only on '
                'sploitkits — measured from the headers themselves, which is '
                'what decides the label\'s scope',
                len(_has_cost) == 6, _has_cost)
        t.check('and every one of the six draws it under one label: a column '
                'that means a shop price drawn labelled on one sheet and bare '
                'on five is the silent-mislabel shape',
                all(_cons_cost[r] for r in _cons_rel)
                and len(set(_cons_cost.values())) == 1, _cons_cost)
        t.check('and that label is neither of the two this column already had '
                '— three families\' worth of "Cost" are three different '
                'quantities and the page says which is which',
                len(set(v[0] for v in COST_LABELS.values())) == 3
                and set(_cons_cost.values()).isdisjoint(
                    set(v[0] for k, v in COST_LABELS.items()
                        if k not in _cons_names)),
                sorted(set(v[0] for v in COST_LABELS.values())))

        # ---- the two shared rows, and the one that only looks like one
        _cons_marked = sorted(set(
            e['shared'][k]['target'] for e in _cons_read.values()
            for k in (e['shared'] or {})))
        _cons_mark_n = sum(len(e['shared'] or {}) for e in _cons_read.values())
        print('        consumable shared-row marks: %d, on %s'
              % (_cons_mark_n, ', '.join(_cons_marked) or 'nothing'))
        t.check('EffectModel 76005 and 76017 are marked as shared, one mark '
                'per declared owner — 2 owners on medical, 3 on devices, 5 '
                'marks',
                _cons_marked == ['EffectModel 76005', 'EffectModel 76017']
                and _cons_mark_n == 5, (_cons_marked, _cons_mark_n))
        _self = getattr(_consumables, 'SELF_SHARES', {}) or {}
        t.check('consumables.py DECLARES the self-share, so "the detector '
                'found nothing" and "the detector found this and correctly did '
                'not call it sharing" stay different answers',
                len(_self) == 1 and ('EffectModel', 75022) in _self,
                sorted(_self))
        t.check('EffectModel 75022 is NOT marked as shared and is not in '
                'SHARED_ROWS — one talent carries it in SelfEffect and '
                'TargetEffect both, and a row cannot diverge from itself. '
                'Counting (talent, column) pairs instead is how an agent '
                'reported nine shared rows where five were self-shares',
                'EffectModel 75022' not in _cons_marked
                and ('EffectModel', 75022) not in SHARED_ROWS,
                (_cons_marked, ('EffectModel', 75022) in SHARED_ROWS))
        _ss = _self.get(('EffectModel', 75022)) or {}
        _ss_e = _cons_read.get('ckf.hardmode.d/' + (_ss.get('sheet') or ''))
        _ss_ship = None
        if _ss_e:
            _ss_n = [c['name'] for c in _ss_e['columns']]
            for _ri, _r in enumerate(_ss_e['rows']):
                if ((_r['cells'][_ss_n.index('ItemTypeId')] or '').strip()
                        == str((_ss.get('owner') or (None,))[0])):
                    _ss_ship = _ss_e['shipped'].get(str(_ri)) or {}
        t.check('and the row it would have been marked on is really drawn, '
                'with the SAME id in both pointer columns — without this the '
                'case above would pass just as well on a row that is not '
                'there at all',
                _ss_ship is not None
                and _ss_ship.get('SelfEffect') == _ss_ship.get('TargetEffect')
                == '75022', (_ss.get('sheet'), _ss_ship))

        # ---- the row that is on disk and is not on the page
        _ex = [(rel, x) for rel in _cons_rel
               for x in _cons_read[rel]['excluded']]
        print('        consumable rows on disk the editor does not draw: %d %s'
              % (len(_ex), [(r.split('/')[-1], x['name'], x['id'])
                            for r, x in _ex]))
        t.check('exactly one consumable row is withheld from the editor, and '
                'it is Striatum Catalyst NMF, ItemTypeId 5403, on the matrix '
                'sheet',
                len(_ex) == 1
                and _ex[0][0] == 'ckf.hardmode.d/consumables-matrix.csv'
                and _ex[0][1]['name'] == 'Striatum Catalyst NMF'
                and _ex[0][1]['id'] == '5403', _ex)
        _mx = _cons_read['ckf.hardmode.d/consumables-matrix.csv']
        _mx_i = [c['name'] for c in _mx['columns']].index('ItemTypeId')
        t.check('it is in none of the rows the page draws — the matrix sheet '
                'draws %d of the %d rows the file holds'
                % (len(_mx['rows']), len(_mx['rows']) + len(_mx['excluded'])),
                not any((r['cells'][_mx_i] or '').strip() == '5403'
                        for r in _mx['rows']),
                (len(_mx['rows']), len(_mx['excluded'])))
        # WHICH OF THE TWO PRODUCTS THIS IS. Read back from the BYTES, because
        # the entry is the thing under test and cannot be its own witness.
        _raw = list(csv.reader(read_bytes(os.path.join(
            cd, 'ckf.hardmode.d/consumables-matrix.csv'))
            .decode('utf-8-sig').splitlines()))
        _raw_i = _raw[0].index('ItemTypeId')
        _raw_hit = [r for r in _raw[1:]
                    if len(r) > _raw_i and r[_raw_i].strip() == '5403']
        t.check('and it IS still in consumables-matrix.csv on disk, read back '
                'from the file\'s own bytes: HIDDEN IN THE EDITOR AND STILL '
                'WRITABLE ON DISK is a different product from ABSENT FROM '
                'BOTH, and this is the first of the two',
                len(_raw_hit) == 1
                and _raw_hit[0][0] == 'Striatum Catalyst NMF', len(_raw_hit))
        t.check('and the page SAYS it withheld a row rather than being quietly '
                'one row short — a grid one row short and a grid whose reader '
                'broke look identical',
                any('Striatum Catalyst NMF' in n and 'on disk' in n
                    for n in _mx['notes']), _mx['notes'][-1:])

        # ---- the shipped oddities: help text, not a silent fix
        _cmt_of, _ship_of, _rel_of = {}, {}, {}
        for rel in _cons_rel:
            e = _cons_read[rel]
            _n = [c['name'] for c in e['columns']]
            for _ri, _r in enumerate(e['rows']):
                _cmt_of[_r['cells'][0]] = _r['cells'][_n.index('_comment')] or ''
                _ship_of[_r['cells'][0]] = e['shipped'].get(str(_ri)) or {}
                _rel_of[_r['cells'][0]] = rel
        _id_cmt = {}
        for rel in _cons_rel:
            e = _cons_read[rel]
            _n = [c['name'] for c in e['columns']]
            for _r in e['rows']:
                _id_cmt[(_r['cells'][_n.index('ItemTypeId')] or '').strip()] = (
                    _r['cells'][_n.index('_comment')] or '')
        _decl_notes = getattr(_consumables, 'ROW_NOTES', {}) or {}
        _note_missing = sorted(str(k) for k, v in _decl_notes.items()
                               if str(k) in _id_cmt and v not in _id_cmt[str(k)])
        _note_undrawn = sorted(str(k) for k in _decl_notes
                               if str(k) not in _id_cmt)
        t.check('every row consumables.py wrote a note for is drawn and '
                'carries that note VERBATIM in its own _comment, and the only '
                'one that is not drawn is 5403, the row the editor withholds. '
                'WHAT IT CANNOT LOOK AT: the six schemas carry no sentence '
                'about any of these rows [measured — none of their doc or '
                'uiDoc mentions one], so the row comment is the only help '
                'text there is and schema/ was out of scope for this change',
                not _note_missing and _note_undrawn == ['5403'] and _decl_notes,
                (_note_missing, _note_undrawn, len(_decl_notes)))
        t.check('ODDITY 1 — Winternight Black is drawn, ships StressRes -15, '
                'and its help text says that is the whole of what it applies. '
                'WHAT IT CANNOT LOOK AT: "and nothing else" is a claim about '
                'the OTHER columns of its EffectModel row, which no sheet '
                'carries; consumables.py measured that against the dump and '
                'this checks the value and the sentence, not the absence',
                _ship_of.get('Winternight Black', {}).get('StressRes') == '-15'
                and 'StressRes -15 and nothing else'
                in _cmt_of.get('Winternight Black', ''),
                (_rel_of.get('Winternight Black'),
                 _ship_of.get('Winternight Black', {}).get('StressRes')))
        _cut = {'Echo-Cutter': '3', 'Boosted Echo-Cutter': '4',
                'Ping-Cutter': '4'}
        t.check('ODDITY 2 — Echo-Cutter, Boosted Echo-Cutter and Ping-Cutter '
                'are drawn, ship TargetEffectDuration 3/4/4 AND ship '
                'TargetEffect 0: a duration with no effect row behind it. '
                'Their help text says so. The 0 is asserted too, or the case '
                'would pass on three rows that simply have a duration',
                all(_ship_of.get(n, {}).get('TargetEffectDuration') == v
                    and _ship_of.get(n, {}).get('TargetEffect') == '0'
                    and 'no effect row behind it' in _cmt_of.get(n, '')
                    for n, v in sorted(_cut.items())),
                [(n, _ship_of.get(n, {}).get('TargetEffectDuration'),
                  _ship_of.get(n, {}).get('TargetEffect'))
                 for n in sorted(_cut)])
        _smoke = ['Smoke Grenade', 'Smokebang XS']
        _dmg = ['PureDamage', 'PhysicalDamage', 'BallisticDamage']
        t.check('ODDITY 3 — Smoke Grenade and Smokebang XS are drawn, ship 0 '
                'in every damage column their sheet carries (%s), and ship '
                'Token 2 / TokenDuration 2: the token IS the payload, and '
                'their help text says so' % ', '.join(_dmg),
                all(all(_ship_of.get(n, {}).get(c) in ('0', '0.0')
                        for c in _dmg)
                    and _ship_of.get(n, {}).get('Token') == '2'
                    and _ship_of.get(n, {}).get('TokenDuration') == '2'
                    and 'the payload is Token / TokenDuration'
                    in _cmt_of.get(n, '') for n in _smoke),
                [(n, dict((c, _ship_of.get(n, {}).get(c))
                          for c in _dmg + ['Token', 'TokenDuration']))
                 for n in _smoke])
        t.check('NOT A BUG AND NOT SILENTLY FIXED — Blue Juice is drawn with '
                'its MatrixDuration 0 intact, and the help text carries the '
                'project owner\'s ruling that a 0 there is an instantaneous '
                'effect',
                _ship_of.get('Blue Juice', {}).get('MatrixDuration') == '0'
                and 'instantaneous effect, not a bug'
                in _cmt_of.get('Blue Juice', ''),
                (_rel_of.get('Blue Juice'),
                 _ship_of.get('Blue Juice', {}).get('MatrixDuration')))
        _odd = (['Winternight Black'] + sorted(_cut) + _smoke + ['Blue Juice'])
        _odd_over = []
        for rel in _cons_rel:
            e = _cons_read[rel]
            for _r in e['rows']:
                if _r['cells'][0] not in _odd:
                    continue
                _odd_over += [(_r['cells'][0], e['columns'][i]['name'])
                              for i, _ro in enumerate(e['roles'])
                              if _ro == 'lever' and (_r['cells'][i] or '').strip()]
        t.check('and NO RULE TOUCHES ANY OF THE %d ODDITY ROWS — every lever '
                'cell on every one of them is blank, so what they get is help '
                'text and not a quiet correction' % len(_odd),
                len(set(_odd) & set(_cmt_of)) == len(_odd) and not _odd_over,
                (sorted(set(_odd) - set(_cmt_of)), _odd_over))

        # ---- the exclusion, over BOTH sheets rather than one
        # MEASURED PER EXPANDER FAMILY, NOT ACROSS EVERY EXPANDED SHEET.
        #
        # CORRECTION, Phase 7. This intersected the columns of every expanded
        # sheet on disk. With three sheets from one expander that was the
        # cyberweapon pair; with fourteen from three expanders the intersection
        # collapses to {PowerLevel, Cost, _comment} and no pair survives
        # [measured], so a case about the crit columns failed on a directory
        # that had simply grown. A claim about two columns of one dialect is
        # measured over the sheets of that dialect.
        _fams = {}
        for rel, e in sorted(ov_read.items()):
            if e['kind'] != 'expanded' or not e['shipped']:
                continue
            _fams.setdefault(tuple(sorted(c['name'] for c in e['columns']))[:0]
                             or _family_of(rel), []).append(e)
        _found = []
        for fam, sheets in sorted(_fams.items()):
            cols = set.intersection(*[set(c['name'] for c in e['columns'])
                                      for e in sheets])
            rows = [p for e in sheets for p in e['shipped'].values()]
            excl = sorted(
                (a, b) for a in cols for b in cols if a < b
                and all(a in p and b in p for p in rows)
                and all(_nonzero(p[a]) != _nonzero(p[b]) for p in rows))
            print('        %s: %d sheet(s), %d row(s) stating a shipped value, '
                  '%d shared column(s); mutually exclusive pair(s): %s'
                  % (fam, len(sheets), len(rows), len(cols), excl or 'none'))
            if excl:
                _found.append((fam, excl, sheets))
        t.check('there is more than one expander family on disk, so a pair '
                'found in one is not a property of every sheet there is',
                len(_fams) > 1, sorted(_fams))
        t.check('at least one family has a pair of columns every one of its '
                'rows uses exactly one of — 0 rows with both, 0 with neither',
                _found, sorted(_fams))
        for fam, excl, sheets in _found:
            t.check('%s: and every sheet in it says so in its own legend, so a '
                    'blank does not read as an omission' % fam,
                    all(any('not a gap' in n for n in e['notes'])
                        for e in sheets),
                    [e['path'] for e in sheets
                     if not any('not a gap' in n for n in e['notes'])])

        # ---- a column whose shipped value is zero on some rows and not on
        #      others, which is the case the legend has to explain. Over every
        #      expanded sheet that states a shipped value, not one family.
        _stating = [e for e in ov_read.values()
                    if e['kind'] == 'expanded' and e['shipped']]
        t.check('there are expanded sheets stating a shipped value to look at',
                _stating, [e['path'] for e in ov_read.values()
                           if e['kind'] == 'expanded'])
        t.check('at least one column ships zero on some rows and non-zero on '
                'others, and the sheet that has one says so',
                any(n.startswith('A blank cell whose shipped value is 0')
                    for e in _stating for n in e['notes']),
                [e['path'] for e in _stating])

        # ---- THE WRITE PATH, AND THE FOUR CLASSES IT STILL REFUSES
        #
        # CORRECTION, 2026-09-14. Everything between here and the nav-group
        # block used to assert that no save could reach a sheet. What it said,
        # verbatim, was:
        #
        #   'a save proposes no overlay file at all'
        #   'and not one of their bytes moved'
        #   'and the six consumable sheets did not move either -- the row this
        #    editor hides is still on disk, byte for byte, after a save that
        #    rewrote everything the editor does own'
        #   'and no save proposed one of them, so "not written" is a property
        #    of the save path and not of a file it happens not to reach'
        #   'an overlay is in no edit set the page can build, so there is
        #    nothing for a save to carry'
        #   'and an overlay is not a fingerprinted path either -- the editor
        #    does not claim to own a file it will not write'
        #
        # David reversed the rule those six cases guarded (see the block header
        # above). Three of the six survive UNCHANGED in meaning and are kept
        # below, because they were never about the rule: a save with no cell
        # edit in it still moves no byte, the withheld Striatum row is still on
        # disk byte for byte, and an undeclared sheet is still not written. The
        # other three are replaced by their opposites, and the LAST of them --
        # "an overlay is not a fingerprinted path" -- was a defect in its own
        # right and not only a consequence of the rule: because
        # files_check_schema_reads omitted the sheets, stage_and_validate never
        # copied them either, and every validate and every save was reporting
        # 53 MISSING problems for files that were all present [measured
        # 2026-09-14]. MISSING is not in BLOCKING, so nothing failed.
        cdov = _sandbox(src, os.path.join(td, 'overlays-write'))
        appov = App({'gameDir': '', 'configDirOverride': cdov,
                     'stripReadme': False}, 'x')
        mov = appov.api_model()
        hov = _hashes_of(cdov, ov_decl)
        hcons = _hashes_of(cdov, _cons_rel)
        t.check('the overlay fixture really carries the files, or the next '
                'case passes by having nothing to protect',
                all(v is not None for v in hov.values()),
                [k for k, v in hov.items() if v is None])
        t.check('and it carries the six consumable sheets too, so the case '
                'below is protecting files that are there',
                all(v is not None for v in hcons.values()),
                [k for k, v in hcons.items() if v is None])

        # (1) A SAVE THAT EDITS NOTHING LEAVES EVERY SHEET BYTE-IDENTICAL.
        #     Not by proposing nothing -- _edits_for now sends every lever cell
        #     of every writable sheet back at the value it already holds, so
        #     this runs the whole writer and then compares hashes taken by an
        #     independent hasher either side.
        eov = _edits_for(appov.schemas, mov)
        _ov_cells = sum(len((b.get('cells') or []))
                        for b in (eov.get('overlays') or {}).values())
        print('        no-op overlay edit set: %d cell(s) across %d sheet(s)'
              % (_ov_cells, len(eov.get('overlays') or {})))
        t.check('the no-op edit set really reaches the sheets -- an edit set '
                'with no cell in it would prove nothing below',
                _ov_cells > 1000 and len(eov.get('overlays') or {}) == len(ov_decl),
                (_ov_cells, len(eov.get('overlays') or {}), len(ov_decl)))
        rov = appov.api_save(eov)
        t.check('a save that changes no cell is accepted', rov['ok'],
                rov.get('refused'))
        t.check('and not one byte of any sheet moved, across all %d of them, '
                'even though every lever cell was sent back through the writer'
                % len(ov_decl),
                _hashes_of(cdov, ov_decl) == hov,
                [k for k in ov_decl if _hashes_of(cdov, ov_decl)[k] != hov[k]])
        t.check('and the save wrote none of them, while REPORTING every one as '
                'skipped -- a save that had proposed no sheet would also have '
                'written zero bytes, and the two are different facts',
                not (set(rov.get('written') or []) & set(ov_decl))
                and set(ov_decl) <= set(rov.get('skipped') or []),
                (sorted(set(rov.get('written') or []) & set(ov_decl)),
                 sorted(set(ov_decl) - set(rov.get('skipped') or []))))
        # UNCHANGED IN MEANING. The withheld Striatum row is not drawn, so no
        # edit set can name it; it has to survive a save of the file it is in.
        t.check('and the row this editor hides is still on disk, byte for '
                'byte, after a save that ran the writer over every sheet it '
                'does draw',
                _hashes_of(cdov, _cons_rel) == hcons,
                [k for k in _cons_rel
                 if _hashes_of(cdov, _cons_rel)[k] != hcons[k]])

        # (2) ONE LEVER CELL MOVES, AND NOTHING ELSE IN THE FILE DOES.
        #
        # The expected bytes are NOT built by the writer. The file is read
        # before and after, split on lines by a local split, and the two are
        # compared line by line: exactly one line may differ, and inside that
        # line only the one field. Building the expectation with the function
        # under test is the failure the brief for this change names -- two
        # things derived from one source always agree.
        _w_rel = sorted(r for r in ov_decl
                        if mov['values']['overlays'][r]['kind'] == 'expanded'
                        and mov['values']['overlays'][r]['writable'])[0]
        _w_ent = mov['values']['overlays'][_w_rel]
        _w_ci = [i for i, e in enumerate(_w_ent['editable']) if e][0]
        _w_col = _w_ent['columns'][_w_ci]['name']
        _w_row = _w_ent['rows'][0]
        _w_path = os.path.join(cdov, _w_rel)
        _w_before = read_bytes(_w_path).decode('utf-8-sig').split('\n')
        _w_old = _w_row['cells'][_w_ci]
        print('        one-cell case: %s row %s column %s, %r -> "=7"'
              % (_w_rel, _w_row['key'], _w_col, _w_old))
        r1 = appov.api_save({'cfg': {}, 'json': {}, 'overlays': {
            _w_rel: {'cells': [{'key': _w_row['key'], 'column': _w_col,
                                'value': '=7'}]}}})
        t.check('a save that edits one lever cell is accepted', r1['ok'],
                r1.get('refused'))
        t.check('and it names that file, and only that file, as written',
                sorted(set(r1.get('written') or []) & set(ov_decl)) == [_w_rel],
                r1.get('written'))
        _w_after = read_bytes(_w_path).decode('utf-8-sig').split('\n')
        _w_diff = [i for i in range(max(len(_w_before), len(_w_after)))
                   if (_w_before[i:i + 1] or [None]) != (_w_after[i:i + 1] or [None])]
        t.check('exactly one line of the file differs -- the header, every '
                'other row, the per-row _comment prose and the trailing '
                'newline are all still there',
                len(_w_diff) == 1, (_w_diff[:5], len(_w_before), len(_w_after)))
        if len(_w_diff) == 1:
            _a = next(csv.reader([_w_before[_w_diff[0]]]))
            _b = next(csv.reader([_w_after[_w_diff[0]]]))
            _moved = [i for i in range(max(len(_a), len(_b)))
                      if (_a[i:i + 1] or [None]) != (_b[i:i + 1] or [None])]
            t.check('and inside that line exactly one field moved, the one the '
                    'edit named', _moved == [_w_ci] and _b[_w_ci] == '=7',
                    (_moved, _b[_w_ci:_w_ci + 1]))
        t.check('and every OTHER declared sheet is still byte for byte what it '
                'was',
                all(_hashes_of(cdov, ov_decl)[k] == hov[k]
                    for k in ov_decl if k != _w_rel),
                [k for k in ov_decl
                 if k != _w_rel and _hashes_of(cdov, ov_decl)[k] != hov[k]])
        # AND BACK. A cleared cell must restore a blank -- not 0, not an empty
        # quoted field -- so the file returns to the bytes it started with.
        r2 = appov.api_save({'cfg': {}, 'json': {}, 'overlays': {
            _w_rel: {'cells': [{'key': _w_row['key'], 'column': _w_col,
                                'value': _w_old}]}}})
        t.check('clearing the cell back to what it held restores the file byte '
                'for byte -- a blank writes a blank, not 0 and not \'\'',
                r2['ok'] and _hashes_of(cdov, ov_decl)[_w_rel] == hov[_w_rel],
                (r2.get('refused'), _w_old))

        # (3) THE THREE UNWRITABLE CLASSES, EACH ATTEMPTED AND EACH REFUSED.
        #
        # Attempted, not merely absent from an edit set: a column nothing
        # offers and a column the server rejects are different products, and
        # only the second survives a client that sends more than it should.
        _u_ent = _w_ent
        _u_roles = _u_ent['roles']
        _u_key = _u_ent['rows'][0]['key']
        _u_cases = []
        _u_cases.append(('the key column', _u_ent['columns'][0]['name']))
        _ident = [i for i, r in enumerate(_u_roles) if r == 'identity' and i != 0]
        if _ident:
            _u_cases.append(('an identity column',
                             _u_ent['columns'][_ident[0]]['name']))
        _ctrl = [i for i, r in enumerate(_u_roles) if r == 'control']
        if _ctrl:
            _u_cases.append(('a control column',
                             _u_ent['columns'][_ctrl[0]]['name']))
        t.check('the sheet under test carries all three unwritable classes, or '
                'the cases below pass by having nothing to try',
                len(_u_cases) == 3, [c[0] for c in _u_cases])
        _u_h = _hashes_of(cdov, ov_decl)
        for _why, _cname in _u_cases:
            _r = appov.api_save({'cfg': {}, 'json': {}, 'overlays': {
                _w_rel: {'cells': [{'key': _u_key, 'column': _cname,
                                    'value': '9'}]}}})
            t.check('%s (%s) is REFUSED, and the refusal names it'
                    % (_why, _cname),
                    not _r['ok'] and _cname in (_r.get('refused') or {}).get('summary', '')
                    and 'not editable' in (_r.get('refused') or {}).get('summary', ''),
                    _r.get('refused') or _r.get('written'))
        t.check('and the three refusals wrote nothing at all',
                _hashes_of(cdov, ov_decl) == _u_h,
                [k for k in ov_decl if _hashes_of(cdov, ov_decl)[k] != _u_h[k]])

        # (4) AN ABSENT OR UNDECLARED SHEET IS NEVER INVENTED.
        #
        # The sibling of 'does not invent the missing file' in the slice-file
        # block above. Two shapes: a path no schema declares, and a declared
        # path whose file has been removed from under the editor.
        _inv = appov.api_save({'cfg': {}, 'json': {}, 'overlays': {
            'ckf.hardmode.d/not-a-sheet.csv': {
                'cells': [{'key': ['1'], 'column': 'x', 'value': '1'}]}}})
        t.check('a sheet no schema declares is refused, not created',
                not _inv['ok']
                and not os.path.exists(os.path.join(cdov, 'ckf.hardmode.d/not-a-sheet.csv')),
                _inv.get('refused') or _inv.get('written'))
        # NARROWED, same run: this said 'no save proposed one of the six
        # consumable sheets by accident' and went red because the sheet the
        # one-cell case picks -- the first writable expanded sheet in path
        # order -- IS one of the six. The set it should have named all along is
        # the five it did not edit; naming all six made the case's own subject
        # a counterexample to it.
        t.check('and every consumable sheet the one-cell edit did NOT name is '
                'unwritten -- a sheet is written only when an edit names it',
                set(r1.get('written') or []).isdisjoint(set(_cons_rel) - {_w_rel}),
                (r1.get('written'), _w_rel))
        cdgone = _sandbox(src, os.path.join(td, 'overlay-gone'))
        _gone_rel = _w_rel
        os.remove(os.path.join(cdgone, _gone_rel))
        appgone = App({'gameDir': '', 'configDirOverride': cdgone,
                       'stripReadme': False}, 'x')
        mgone = appgone.api_model()
        t.check('a declared sheet that is not on disk reads as an error, not '
                'as an empty grid',
                mgone['values']['overlays'][_gone_rel]['error'] == 'not on disk',
                mgone['values']['overlays'][_gone_rel]['error'])
        t.check('and it is not writable, with the reason naming the read '
                'failure rather than a generic no',
                not mgone['values']['overlays'][_gone_rel]['writable']
                and 'not on disk' in mgone['values']['overlays'][_gone_rel]['writableWhy'],
                mgone['values']['overlays'][_gone_rel]['writableWhy'])
        _rg = appgone.api_save({'cfg': {}, 'json': {}, 'overlays': {
            _gone_rel: {'cells': [{'key': _w_row['key'], 'column': _w_col,
                                   'value': '=7'}]}}})
        t.check('a save naming the absent sheet is refused and does NOT '
                'recreate it -- the sibling of the missing-slice-file case '
                'above',
                not _rg['ok'] and not os.path.exists(os.path.join(cdgone, _gone_rel)),
                _rg.get('refused') or _rg.get('written'))
        _rg2 = appgone.api_save(_edits_for(appgone.schemas, mgone))
        t.check('and a whole no-op save with that sheet missing still succeeds '
                'for the rest, without creating it',
                _rg2['ok'] and not os.path.exists(os.path.join(cdgone, _gone_rel)),
                _rg2.get('refused'))

        # (5) A SHEET EDIT RIDES THE SAME JOURNAL AS A .cfg EDIT.
        #
        # The requirement is that a sheet edit and a .cfg edit either both land
        # or neither does. Caught mid-transaction, because a completed save
        # removes the journal.
        cdjo = _sandbox(src, os.path.join(td, 'overlay-journal'))
        appjo = App({'gameDir': '', 'configDirOverride': cdjo,
                     'stripReadme': False}, 'x')
        mjo = appjo.api_model()
        _jo_ent = mjo['values']['overlays'][_w_rel]
        _jo_cfg = sorted(k for k, v in mjo['values']['cfg'].items()
                         if v['present'] and v.get('value') in (True, False))[0]
        _jo_edits = {'cfg': {_jo_cfg: {'value': not mjo['values']['cfg'][_jo_cfg]['value']}},
                     'json': {},
                     'overlays': {_w_rel: {'cells': [
                         {'key': _jo_ent['rows'][0]['key'], 'column': _w_col,
                          'value': '=11'}]}}}
        _seen = {}
        _real_replace = os.replace

        def _spy(a, b):
            if os.path.basename(str(b)) == JOURNAL_NAME and os.path.exists(a):
                try:
                    _seen['j'] = json.loads(read_bytes(a).decode('utf-8'))
                except Exception as _e:      # pragma: no cover - reported
                    _seen['err'] = str(_e)
            return _real_replace(a, b)
        os.replace = _spy
        try:
            _rjo = appjo.api_save(_jo_edits)
        finally:
            os.replace = _real_replace
        _jrel = sorted(os.path.relpath(f, cdjo).replace(os.sep, '/')
                       for _t2, f in (_seen.get('j') or {}).get('renames', []))
        t.check('a save that moves a .cfg key and a lever cell together is '
                'accepted', _rjo['ok'], _rjo.get('refused'))
        t.check('and ONE journal named both of them -- the sheet is in the '
                'same transaction as the .cfg, not beside it',
                _jrel == sorted(['ckf.hardmode.cfg', _w_rel]), _jrel)
        t.check('and the journal is gone once the save finished',
                not os.path.exists(journal_path(cdjo)), journal_path(cdjo))

        # (6) A CRASH BETWEEN THE TWO RENAMES IS FINISHED BY recover_journal.
        cdjr = _sandbox(src, os.path.join(td, 'overlay-journal-recover'))
        appjr = App({'gameDir': '', 'configDirOverride': cdjr,
                     'stripReadme': False}, 'x')
        mjr = appjr.api_model()
        _jr_ent = mjr['values']['overlays'][_w_rel]
        _jr_edits = {'cfg': {}, 'json': {}, 'overlays': {_w_rel: {'cells': [
            {'key': _jr_ent['rows'][0]['key'], 'column': _w_col, 'value': '=13'}]}}}
        _calls = {'n': 0}

        def _flaky(a, b):
            _calls['n'] += 1
            if os.path.basename(str(b)) != JOURNAL_NAME:
                raise PermissionError(13, 'Permission denied', b)
            return _real_replace(a, b)
        os.replace = _flaky
        try:
            _bad = appjr.api_save(_jr_edits)
        finally:
            os.replace = _real_replace
        t.check('a sheet write that fails at the rename is reported refused, '
                'not as a success', not _bad['ok'], _bad)
        t.check('and it left a journal naming the sheet',
                os.path.exists(journal_path(cdjr)), journal_path(cdjr))
        _rec = recover_journal(cdjr)
        t.check('which the next start finishes',
                _rec['found'] and _rec['completed'], _rec)
        _fin = read_overlay(os.path.join(cdjr, _w_rel), _w_rel)
        t.check('and the cell the interrupted save was moving is now in the '
                'file -- the recovery covers a sheet exactly as it covers a '
                'sidecar',
                _fin['rows'][0]['cells'][_w_ci] == '=13',
                _fin['rows'][0]['cells'][_w_ci])

        # (7) THE FINGERPRINT. Inverted: the editor DOES claim these files now,
        #     which is what lets a save refuse when one moved under it.
        t.check('every declared sheet is a fingerprinted path -- the editor '
                'claims the files it will write, so a sheet edited on disk '
                'between the read and the save is caught',
                set(ov_decl) <= set(mov['fingerprints']),
                sorted(set(ov_decl) - set(mov['fingerprints'])))
        cdst = _sandbox(src, os.path.join(td, 'overlay-stale'))
        appst = App({'gameDir': '', 'configDirOverride': cdst,
                     'stripReadme': False}, 'x')
        mst = appst.api_model()
        _st_ent = mst['values']['overlays'][_w_rel]
        _st_edit = {'cfg': {}, 'json': {}, 'overlays': {_w_rel: {'cells': [
            {'key': _st_ent['rows'][0]['key'], 'column': _w_col, 'value': '=5'}]}}}
        _ok1 = appst.api_save(_st_edit, expect=mst['fingerprints'])
        t.check('a sheet edit against a current read is accepted',
                _ok1['ok'], _ok1.get('refused'))
        _st2 = appst.api_save(_st_edit, expect=mst['fingerprints'])
        t.check('and the same edit against the now-stale fingerprint is '
                'refused, naming the sheet that moved',
                not _st2['ok'] and _w_rel in (_st2.get('stale') or []),
                (_st2.get('stale'), _st2.get('refused')))

        # (8) THE CELL GRAMMAR: what is checked, and what cannot be.
        _g_bad = appov.api_save({'cfg': {}, 'json': {}, 'overlays': {
            _w_rel: {'cells': [{'key': _w_row['key'], 'column': _w_col,
                                'value': '90x'}]}}})
        t.check('an expanded sheet\'s lever cell is held to the expanders\' own '
                'adjust grammar -- \'90x\' is refused, and the refusal quotes '
                'what an unparseable spec does at runtime',
                not _g_bad['ok']
                and 'not a valid adjustment' in (_g_bad.get('refused') or {}).get('summary', ''),
                _g_bad.get('refused'))
        _g_nl = appov.api_save({'cfg': {}, 'json': {}, 'overlays': {
            _w_rel: {'cells': [{'key': _w_row['key'], 'column': _w_col,
                                'value': '1\n2'}]}}})
        t.check('and a cell carrying a line break is refused -- the plugin '
                'reads these files one line at a time',
                not _g_nl['ok'], _g_nl.get('refused'))
        # THE DIRECT DIALECT, tested against overlay_check_cell directly: no
        # shipped sheet carries a non-set header operator today [measured
        # 2026-09-14: all 563 editable columns across the 53 declared sheets
        # are Op.Set], so the refusal below has no subject on disk and would
        # otherwise be untested code guarding the day one appears.
        _d_entry = {'kind': 'direct',
                    'columns': [{'name': 'Id', 'op': 'set', 'control': False},
                                {'name': 'Scaled', 'op': 'multiply', 'control': False},
                                {'name': 'Plain', 'op': 'set', 'control': False}]}
        _d_notes = []
        t.check('a non-numeric cell under a non-set header operator is '
                'REFUSED: Overlays.cs logs and drops it, which would look to '
                'the player like a save that worked and changed nothing',
                _raises(lambda: overlay_check_cell(_d_entry, 1, 'Charge-Max-Boost',
                                                   'x.csv', _d_notes),
                        SaveRefused))
        overlay_check_cell(_d_entry, 2, 'Charge-Max-Boost', 'x.csv', _d_notes)
        t.check('the same text under a plain-set column is ACCEPTED -- 11 of '
                'the 379 filled direct lever cells on disk are exactly this '
                '(IconPng) -- and it WARNS BY NAME that nothing range-checked '
                'it, because check_schema declares no columns for these sheets',
                len(_d_notes) == 1 and 'x.csv.Plain' in _d_notes[0]
                and 'NOTHING RANGE-CHECKED IT' in _d_notes[0], _d_notes)
        overlay_check_cell(_d_entry, 1, '2.5', 'x.csv', _d_notes)
        overlay_check_cell(_d_entry, 1, '', 'x.csv', _d_notes)
        t.check('and a number, and a blank, pass under either operator without '
                'a warning', len(_d_notes) == 1, _d_notes)

        # (9) THE SPAN SCANNER, CROSS-CHECKED AGAINST A SECOND READER.
        #
        # csv_field_spans is the only thing standing between an edit and the
        # rest of the line. It is compared against csv.reader -- a different
        # implementation, not a second call to the same one -- over every line
        # of every sheet in the fixture.
        _sp_lines = _sp_bad = 0
        for _rel in ov_decl:
            for _ln in read_bytes(os.path.join(cdov, _rel)).decode('utf-8-sig').splitlines():
                _sp_lines += 1
                _sp = csv_field_spans(_ln, ',')
                if _sp is None:
                    _sp_bad += 1
                    continue
                _got = [next(csv.reader([_ln[a:b]]))[0] if _ln[a:b] else ''
                        for a, b in _sp]
                if _got != (next(csv.reader([_ln])) if _ln else ['']):
                    _sp_bad += 1
        # THE LINE COUNT IS DERIVED, NOT GUESSED. A threshold of "more than
        # N" would have passed over a loop that read one file: what the sheets
        # hold is one header plus every row the reader kept plus every row it
        # withheld, and the scanner has to have been over all of them.
        _sp_want = sum(1 + len(mov['values']['overlays'][r]['rows'])
                       + len(mov['values']['overlays'][r]['excluded'])
                       for r in ov_decl)
        print('        span scanner vs csv.reader: %d line(s) (%d expected), '
              '%d disagreement(s)' % (_sp_lines, _sp_want, _sp_bad))
        t.check('csv_field_spans agrees with csv.reader on every line of every '
                'sheet -- %d lines, one header plus every drawn and withheld '
                'row of all %d sheets, and the two are independent readers'
                % (_sp_lines, len(ov_decl)),
                _sp_lines == _sp_want and _sp_bad == 0,
                (_sp_lines, _sp_want, _sp_bad))
        t.check('and it refuses a line it cannot place rather than guessing a '
                'span', csv_field_spans('a,"unterminated', ',') is None
                and csv_field_spans('a,"x"junk,b', ',') is None,
                (csv_field_spans('a,"unterminated', ','),
                 csv_field_spans('a,"x"junk,b', ',')))
        t.check('and a value needing quotes gets them, while a blank gets '
                'nothing at all -- not 0 and not an empty quoted field',
                csv_render_cell('a,b', ',') == '"a,b"'
                and csv_render_cell('say "hi"', ',') == '"say ""hi"""'
                and csv_render_cell('', ',') == ''
                and csv_render_cell('3', ',') == '3',
                [csv_render_cell(v, ',') for v in ('a,b', 'say "hi"', '', '3')])

        # (10) SHARED-ROW CELLS ARE WRITABLE, AND THE BLIND CASE REFUSES.
        #
        # overlay_shared_marks calls these cells REPOINTS: neither sheet
        # carries an EffectModel column, so an edit here changes WHICH effect
        # row a talent uses and not what that effect does. They stay writable --
        # a repoint is a legitimate override and refusing it would make a lever
        # column read-only on some rows and not others, for a reason the grid
        # cannot show. What is NOT allowed is writing them while the marking is
        # unavailable: SHEET_IDENTITY and SHARED_ROWS come from the same four
        # expander imports, so an import failure both hides the repoint marks
        # AND mis-grades identity columns as levers. overlay_writable refuses
        # every sheet in that state rather than trusting a short list.
        _shared_cells = [(rel, k) for rel in ov_decl
                         for k in (mov['values']['overlays'][rel]['shared'] or {})]
        print('        shared-row (repoint) cells marked: %d; sharedSource: %s'
              % (len(_shared_cells),
                 mov['values']['overlays'][ov_decl[0]]['sharedSource'] or 'available'))
        t.check('there are shared-row cells to have an opinion about',
                len(_shared_cells) > 0, _shared_cells[:3])
        for _srel, _sk in _shared_cells[:1]:
            _sri, _sci = (int(x) for x in _sk.split(','))
            _sent = mov['values']['overlays'][_srel]
            t.check('a shared-row cell is a LEVER cell and is editable -- the '
                    'mark says it is a repoint, it does not make it read-only',
                    _sent['editable'][_sci] and _sent['roles'][_sci] == 'lever',
                    (_srel, _sk, _sent['roles'][_sci]))
            t.check('and the server sends the repoint mark with it, so the '
                    'page can say which it is',
                    _sent['shared'][_sk].get('repoint') is True,
                    _sent['shared'][_sk])
        _blind = dict(mov['values']['overlays'][_w_rel])
        _blind['writable'], _blind['writableWhy'] = overlay_writable(_blind)
        t.check('control: with the expanders imported the sheet IS writable, '
                'or the blind case below proves nothing', _blind['writable'],
                _blind['writableWhy'])
        _sse = SHEET_SOURCE_ERROR
        try:
            globals()['SHEET_SOURCE_ERROR'] = 'ImportError: injected'
            _bw, _bwhy = overlay_writable(dict(mov['values']['overlays'][_w_rel]))
        finally:
            globals()['SHEET_SOURCE_ERROR'] = _sse
        t.check('and with an expander import broken NO sheet is writable, and '
                'the reason says it is identity grading that cannot be '
                'trusted -- a writer that trusted a short SHEET_IDENTITY '
                'would offer an identity column as a lever',
                not _bw and 'identity' in _bwhy and 'injected' in _bwhy, _bwhy)
        t.check('SHEET_SOURCE_ERROR is back to what it was after the injection',
                SHEET_SOURCE_ERROR == _sse, (SHEET_SOURCE_ERROR, _sse))

        # (11) THE CLIENT CONTRACT, ASSERTED AS A SHAPE.
        for _rel in ov_decl:
            _e = mov['values']['overlays'][_rel]
            t.check('%s: editable and constant are parallel to columns, and '
                    'every row carries its key' % os.path.basename(_rel),
                    len(_e['editable']) == len(_e['columns'])
                    and len(_e['constant']) == len(_e['columns'])
                    and all(isinstance(r.get('key'), list)
                            and len(r['key']) == len(_e['identityColumns'])
                            for r in _e['rows']),
                    (len(_e['editable']), len(_e['constant']),
                     len(_e['columns']), len(_e['identityColumns'])))
        t.check('index 0 is editable on no sheet at all, whatever its role '
                'grades as',
                not any(mov['values']['overlays'][r]['editable'][0] for r in ov_decl),
                [r for r in ov_decl if mov['values']['overlays'][r]['editable'][0]])
        t.check('no control column is editable on any sheet',
                not any(e for r in ov_decl
                        for i, e in enumerate(mov['values']['overlays'][r]['editable'])
                        if mov['values']['overlays'][r]['roles'][i] == 'control'),
                'a control column graded editable')
        t.check('no identity column is editable on any sheet',
                not any(e for r in ov_decl
                        for i, e in enumerate(mov['values']['overlays'][r]['editable'])
                        if mov['values']['overlays'][r]['roles'][i] == 'identity'),
                'an identity column graded editable')
        _dupkeys = [(r, len(mov['values']['overlays'][r]['rows']))
                    for r in ov_decl
                    if len({tuple(x['key']) for x in mov['values']['overlays'][r]['rows']})
                    != len(mov['values']['overlays'][r]['rows'])]
        t.check('the identity tuple is unique on every declared sheet, which is '
                'why a row is addressed by it and not by an ordinal -- the '
                'FIRST COLUMN alone is not unique on %d of them'
                % len([r for r in ov_decl
                       if len({x['cells'][0] for x in mov['values']['overlays'][r]['rows']})
                       != len(mov['values']['overlays'][r]['rows'])]),
                not _dupkeys, _dupkeys)
        _constsup = [(r, c['name']) for r in ov_decl
                     for i, c in enumerate(mov['values']['overlays'][r]['columns'])
                     if mov['values']['overlays'][r]['constant'][i] is not None]
        print('        columns constant within their own sheet: %d of %d'
              % (len(_constsup),
                 sum(len(mov['values']['overlays'][r]['columns']) for r in ov_decl)))
        t.check('`constant` finds some columns that never vary and leaves the '
                'rest null -- an all-null or all-set answer would be the '
                'derivation not running',
                0 < len(_constsup) < sum(len(mov['values']['overlays'][r]['columns'])
                                         for r in ov_decl),
                len(_constsup))
        # THE SUPPRESSION TRAP, COUNTED SO IT CANNOT GO QUIET. A lever column
        # that is blank on every row is constant, and a client that suppressed
        # every constant column would suppress most of the override surface --
        # which is the state David could not type into.
        _lev_all = _lev_var = _lev_blank = _lev_val = 0
        _dead_sheets = []
        for _r in ov_decl:
            _e2 = mov['values']['overlays'][_r]
            _v = 0
            for _i, _ed in enumerate(_e2['editable']):
                if not _ed:
                    continue
                _lev_all += 1
                _c = _e2['constant'][_i]
                if _c is None:
                    _lev_var += 1
                    _v += 1
                elif _c['value'] == '':
                    _lev_blank += 1
                else:
                    _lev_val += 1
            if not _v:
                _dead_sheets.append(_r)
        print('        editable columns: %d total, %d vary, %d constant ONLY '
              'because every cell is blank, %d constant at a real value; '
              'sheets where no editable column varies: %d'
              % (_lev_all, _lev_var, _lev_blank, _lev_val, len(_dead_sheets)))
        t.check('most editable columns are constant only because no override '
                'is set in them -- `constant.value` is \'\' for exactly those, '
                'so a client can suppress a repeated LABEL without suppressing '
                'an empty OVERRIDE column, which would put the grid back in '
                'the state that could not be typed into',
                _lev_blank > _lev_var and _lev_val < _lev_var
                and len(_dead_sheets) > 0,
                (_lev_all, _lev_var, _lev_blank, _lev_val, len(_dead_sheets)))
        t.check('and every one of those blank-everywhere columns still grades '
                'editable and still has a shipped value to draw beside the '
                'blank, so nothing about it is missing',
                all(mov['values']['overlays'][r]['shipped']
                    for r in _dead_sheets
                    if mov['values']['overlays'][r]['kind'] == 'expanded'),
                [r for r in _dead_sheets
                 if mov['values']['overlays'][r]['kind'] == 'expanded'
                 and not mov['values']['overlays'][r]['shipped']])
        t.check('and the probe already reports whether ckf.hardmode.d can be '
                'written, which is now a question about the save path and not '
                'only about the directory',
                (mov['probe']['overlays'] or {}).get('state') == 'ok',
                mov['probe']['overlays'])

        # ---- the two nav groups Phase 4 fills
        _sub_map = dict((sc['subsystem'], sc) for sc in app.schemas)
        _secs = sections_for(app.schemas)
        _groups = nav_groups_for(app.schemas, _secs)['groups']
        _by_id = dict((g['id'], g) for g in _groups)
        _sec_by_id = dict((s['id'], s) for s in _secs)
        _pack_groups = [g for g in _groups
                        if g['sections'] and all(
                            overlay_paths(_sub_map[sub])
                            for sid in g['sections']
                            for sub in _sec_by_id[sid]['subsystems'])]
        print('        nav groups whose every section owns overlays: %s'
              % ', '.join('%s (%d section(s))' % (g['id'], len(g['sections']))
                          for g in _pack_groups))
        t.check('two groups are filled entirely by overlay-owning sections — '
                'the packs and the constants', len(_pack_groups) == 2,
                [g['id'] for g in _pack_groups])
        _packs = max(_pack_groups, key=lambda g: len(g['sections']))
        _consts = min(_pack_groups, key=lambda g: len(g['sections']))
        t.check('the pack group holds one section per class, each its own '
                'subsystem, and none of them is absent',
                len(_packs['sections']) == 11 and not _packs['absent']
                and all(len(_sec_by_id[s]['subsystems']) == 1
                        for s in _packs['sections']),
                (len(_packs['sections']), _packs['absent']))
        t.check('the constants group holds exactly one section',
                len(_consts['sections']) == 1 and not _consts['absent'],
                (_consts['sections'], _consts['absent']))
        _pack_files = dict(
            (sid, overlay_paths(_sub_map[_sec_by_id[sid]['subsystems'][0]]))
            for sid in _packs['sections'])
        print('        pack file counts: %s'
              % ', '.join('%s %d' % (k, len(v))
                          for k, v in sorted(_pack_files.items())))
        t.check('every pack owns two or three files, never one and never none',
                all(2 <= len(v) <= 3 for v in _pack_files.values()),
                {k: len(v) for k, v in _pack_files.items()
                 if not 2 <= len(v) <= 3})
        t.check('and both shapes are present, so neither branch is untested',
                len(set(len(v) for v in _pack_files.values())) == 2,
                sorted(set(len(v) for v in _pack_files.values())))
        # The two packs whose file set is not the usual three. Found from the
        # data, not named: one pack's tables differ from every other's.
        _tables = dict((sid, sorted(overlay_table_name(r) for r in v))
                       for sid, v in _pack_files.items())
        _common = [t2 for t2 in set(x for v in _tables.values() for x in v)
                   if sum(1 for v in _tables.values() if t2 in v) > len(_tables) / 2]
        _odd = sorted(sid for sid, v in _tables.items()
                      if sorted(v) != sorted(_common))
        print('        tables most packs carry: %s; packs that differ: %s'
              % (', '.join(sorted(_common)), ', '.join(_odd) or 'none'))
        t.check('exactly two packs carry a different set of tables from the '
                'rest, and the page renders whatever each declares rather than '
                'a shape it assumed', len(_odd) == 2, _odd)

        # ---- the reference field, its grouping and its pairs
        for (sub, path), (_sch2, fref2) in sorted(reference_fields(app.schemas).items()):
            key2 = '%s|%s' % (sub, path)
            rows2 = m['values']['tables'][key2]['rows']
            gcol = REFERENCE_GROUPING.get((sub, path))
            t.check('%s.%s reached the model as a table with every row the '
                    'schema declares' % (sub, path),
                    len(rows2) == len(fref2.get('rows') or []),
                    (len(rows2), len(fref2.get('rows') or [])))
            if not gcol:
                continue
            counts = {}
            for r in rows2:
                counts[r['cells'][gcol]] = counts.get(r['cells'][gcol], 0) + 1
            print('        %s.%s groups: %s = %d'
                  % (sub, path,
                     ', '.join('%s %d' % kv for kv in
                               sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))),
                     sum(counts.values())))
            t.check('%s.%s splits into more than one group and fewer than one '
                    'per row — a grouping that does neither is not a grouping'
                    % (sub, path), 1 < len(counts) < len(rows2), len(counts))
            # THE PAIRS. A row whose label is another row's label plus a
            # remainder is that row's variant. Derived, so nothing here spells
            # the suffix; the page derives it the same way.
            lab = [c['name'] for c in (fref2.get('row') or [])
                   if c.get('type') == 'string' and c['name'] != gcol]
            t.check('%s.%s has a label column the pairing can read'
                    % (sub, path), lab, [c['name'] for c in (fref2.get('row') or [])])
            if not lab:
                continue
            names = dict((r['cells'][lab[0]], r) for r in rows2)
            variants = []
            for n2, r in names.items():
                for b2 in names:
                    if b2 != n2 and n2.startswith(b2):
                        variants.append((b2, n2, n2[len(b2):].strip()))
            # A NAME PREFIX ALONE IS NOT A PAIRING. Measured: two remainders
            # exist in these 76 rows, ' for PL 3' on twelve pairs and
            # ' Distance' on two -- the second is a penalty and that penalty's
            # distance, two separate constants that happen to share a prefix.
            # So the pairing is the LARGEST family sharing one remainder, and
            # that it is strictly largest is what is asserted; a tie would mean
            # the page had no principled way to choose and must not guess.
            tally = {}
            for _b, _n, suf in variants:
                tally[suf] = tally.get(suf, 0) + 1
            ranked = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
            valcol = [c['name'] for c in (fref2.get('row') or [])
                      if c.get('type') == 'int' and c['name'] != fref2.get('sortBy')]
            fam = [v for v in variants if ranked and v[2] == ranked[0][0]]
            differ = sum(1 for b2, n2, _s in fam
                         if valcol and names[b2]['cells'][valcol[0]]
                                    != names[n2]['cells'][valcol[0]])
            print('        %s.%s name remainders: %s'
                  % (sub, path, ', '.join('%r x%d' % kv for kv in ranked)))
            t.check('%s.%s carries variant pairs at all' % (sub, path),
                    variants, len(variants))
            t.check('%s.%s: one remainder is strictly the most common, so the '
                    'page has a family to pair on rather than a guess between '
                    'two' % (sub, path),
                    len(ranked) > 0 and (len(ranked) == 1
                                         or ranked[0][1] > ranked[1][1]), ranked)
            t.check('%s.%s: a second, smaller remainder exists and is '
                    'deliberately NOT paired — a prefix is not a variant'
                    % (sub, path), len(ranked) > 1, ranked)
            t.check('%s.%s: the pair members disagree on the shipped value on '
                    'most of the family (%d of %d), which is why they stay two '
                    'rows rather than being folded into one'
                    % (sub, path, differ, len(fam)),
                    differ > 0 and differ < len(fam), (differ, len(fam)))

        # ---- keys no schema declares, in a slice file
        #
        # THE CHECKER CANNOT SEE THESE ANY MORE. check_schema's stray-key guard
        # runs only for a file some schema `claimed`, and `claimed` is filled in
        # only for a schema declaring a `targets.section`. The Phase 3 split
        # removed `section` from all nine, so the guard continues on every file.
        # Measured 2026-09-13 against the live directory carrying a real
        # leftover key: `check_schema` returned 0 problems, rc 0. The C# side
        # still refuses it at launch through ConfigDoc.ReadSection, so it is
        # caught eventually -- but by nothing a developer runs first, which
        # makes this editor the only gate that can report it.
        #
        # Nothing is graded here and nothing should be: a retired key left on
        # disk on purpose and a misspelled one are the same bytes. The spec's
        # "An unknown key survives" requires both to be read, left without a
        # control and written back untouched, and that is asserted too.
        sk_live = stray_keys(doc, app.schemas)
        print('        top-level keys no schema declares (%d file(s), %d key(s)): %s'
              % (len(sk_live), sum(len(v) for v in sk_live.values()),
                 '; '.join('%s: %s' % (k, ', '.join(v))
                           for k, v in sorted(sk_live.items())) or 'none'))
        # CORRECTION, made during this change. This first read
        #
        #   not [k for v in sk_live.values() for k in v
        #        if k.startswith(METADATA_PREFIX)]
        #
        # which uses the constant under test to say what the constant should
        # do: setting METADATA_PREFIX to a string nothing starts with left the
        # case PASSING over a census that had stopped filtering anything
        # [measured, mutation run 2026-09-13]. An assertion that cannot fail is
        # the thing this file exists to catch, and it was in the case written
        # to catch it. It now names the key off disk instead: every slice file
        # carries a _version stamp that no schema declares as a field, so it is
        # in the raw undeclared set and must be out of the census.
        raw_undeclared = build_model(doc)[0]['unknownTopLevel']
        stamped = sorted(u for u, keys in raw_undeclared.items()
                         if '_version' in keys)
        t.check('every slice file carries a _version no schema declares as a '
                'field, so there is something for the census to exclude',
                len(stamped) == len(doc.sidecars), (len(stamped),
                                                    len(doc.sidecars)))
        t.check('and the census excludes it — the repo\'s own metadata is not '
                'reported as an undeclared key',
                not [u for u in stamped if '_version' in sk_live.get(u, [])],
                [u for u in stamped if '_version' in sk_live.get(u, [])])
        t.check('and the census is a subset of the raw undeclared set, never '
                'something it invented',
                all(set(v) <= set(raw_undeclared.get(u, []))
                    for u, v in sk_live.items()),
                {u: sorted(set(v) - set(raw_undeclared.get(u, [])))
                 for u, v in sk_live.items()
                 if not set(v) <= set(raw_undeclared.get(u, []))})
        # An injected key, so the instrument cannot go quiet when the live
        # directory happens to be clean.
        cdsk = _sandbox(src, os.path.join(td, 'strays'))
        sk_unit = sorted(sidecar_names(app.schemas))[0]
        sk_file = os.path.join(cdsk, unit_file(sk_unit))
        _sk_txt = read_bytes(sk_file).decode('utf-8')
        _at = _sk_txt.index('\n  "') + 3
        MISSPELT = 'thisKeyIsMisspelt'
        with open(sk_file, 'wb') as _f:
            _f.write((_sk_txt[:_at] + '"%s": 7,\n  ' % MISSPELT
                      + _sk_txt[_at:]).encode('utf-8'))
        appsk = App({'gameDir': '', 'configDirOverride': cdsk,
                     'stripReadme': False}, 'x')
        msk = appsk.api_model()
        docsk = read_document(cdsk, appsk.schemas)
        t.check('a key no schema declares is found, and named, in the file '
                'that carries it',
                MISSPELT in stray_keys(docsk, appsk.schemas).get(sk_unit, []),
                stray_keys(docsk, appsk.schemas))
        t.check('and it reaches the page, which is the only place it is '
                'visible at all',
                MISSPELT in (msk.get('strayKeys') or {}).get(sk_unit, []),
                msk.get('strayKeys'))
        t.check('and the note names it too, so a save and a revalidate both '
                'say it',
                any(MISSPELT in n for n in stray_notes(docsk, appsk.schemas)),
                stray_notes(docsk, appsk.schemas)[:3])
        t.check('THE CHECKER DOES NOT SEE IT — this is the gap the census '
                'covers, and if check_schema ever grows the guard back this '
                'case is how that is noticed',
                not [q for q in msk['check']['problems']
                     if MISSPELT in q['message']],
                [q['message'] for q in msk['check']['problems']])
        t.check('it is given no control on the page — the spec says an '
                'unknown key is hidden from the editor',
                not any(f['path'] == MISSPELT
                        for s2 in msk['schemas'] for f in s2['fields']),
                MISSPELT)
        rsk = appsk.api_save(_edits_for(appsk.schemas, msk))
        t.check('and a save keeps it exactly — named is not the same as '
                'touched, and the spec requires it written back untouched',
                rsk['ok'] and check_schema.load_jsonc(sk_file).get(MISSPELT) == 7,
                rsk.get('refused') or check_schema.load_jsonc(sk_file).get(MISSPELT))

        # ---- fingerprints are per file, and there are as many as there are files
        t.check('there is one fingerprint per path the editor owns, and no '
                'other', sorted(m['fingerprints']) == owned_now,
                (sorted(m['fingerprints']), owned_now))
        cdfp = _sandbox(src, os.path.join(td, 'fingerprints'))
        appfp = App({'gameDir': '', 'configDirOverride': cdfp,
                     'stripReadme': False}, 'x')
        mfp = appfp.api_model()
        # Two different files: one edited through the editor, one moved on disk
        # underneath it. With ten files instead of one there are ten times as
        # many chances for the second to happen, so what the check covers is
        # worth stating: it is every owned file, not only the ones the save
        # touches.
        edit_unit = drop[0] if drop else units[0]
        other = sorted(u for u in units if u != edit_unit)[0]
        with open(os.path.join(cdfp, unit_file(other)), 'ab') as _f:
            _f.write(b'\n')
        efp = _edits_for(appfp.schemas, mfp)
        hfp = _hashes_of(cdfp, owned_now)
        rfp = appfp.api_save(efp, expect=mfp['fingerprints'])
        t.check('a file moving on disk refuses the save even though the save '
                'does not touch it — the fingerprint check is over every owned '
                'file, not over the touched ones',
                not rfp['ok'], rfp)
        t.check('and the refusal names exactly the file that moved',
                (rfp.get('stale') or []) == [unit_file(other)],
                rfp.get('stale'))
        t.check('and nothing was written',
                _hashes_of(cdfp, owned_now) == hfp,
                [k for k in owned_now if _hashes_of(cdfp, owned_now)[k] != hfp[k]])
        os.remove(os.path.join(cdfp, unit_file(other)))
        rfp2 = appfp.api_save(efp, expect=mfp['fingerprints'])
        t.check('a file DELETED on disk is caught by the same check — a null '
                'fingerprint where there was a digest is a move',
                not rfp2['ok'] and (rfp2.get('stale') or []) == [unit_file(other)],
                rfp2.get('stale') or rfp2)


        # ---- what the writer reproduces, and what it normalises away
        #
        # The slice files are meant to be hand-editable with the game and the
        # editor closed (design.md section 1), so a save that silently
        # reformats a player's file is a defect even when no value moves. What
        # the writer actually does is not argued here; each variation is
        # written into a real slice file and taken through a real no-op save.
        #
        # The split is deliberate. WHITESPACE AND NUMBER SPELLING are a
        # canonical form, and the shipped files are expected to match it.
        # COMMENTS AND TRAILING COMMAS are not: load_jsonc accepts them, so a
        # player may legitimately write them, and the writer then deletes them.
        # That asymmetry is not fixed by making the writer preserve
        # whitespace -- it is a comment-preserving writer or a warning, and
        # this is the warning.
        cdc2 = _sandbox(src, os.path.join(td, 'canonical'))
        canon_unit = None
        for u in sidecar_names(schemas):
            raw_u = read_bytes(os.path.join(cdc2, unit_file(u)))
            if canonical_bytes(raw_u) == raw_u and len(raw_u) < 4000:
                canon_unit = u
                break
        t.check('a slice file that is already in canonical form was found to '
                'mutate — starting from one that is not would confound every '
                'case below', canon_unit, sidecar_names(schemas))
        if canon_unit:
            cpath = os.path.join(cdc2, unit_file(canon_unit))
            base_bytes = read_bytes(cpath)
            print('        normalisation probe drives %s (%d bytes)'
                  % (unit_file(canon_unit), len(base_bytes)))

            def _roundtrip(data):
                """Write `data` into the slice file, take a no-op save, return
                the bytes that came back. -> (ok, bytes_or_reason)"""
                with open(cpath, 'wb') as _f:
                    _f.write(data)
                ap = App({'gameDir': '', 'configDirOverride': cdc2,
                          'stripReadme': False}, 'x')
                mm = ap.api_model()
                if unit_file(canon_unit) in mm['sidecarErrors']:
                    return False, mm['sidecarErrors'][unit_file(canon_unit)]
                rr = ap.api_save(_edits_for(ap.schemas, mm))
                if not rr['ok']:
                    return False, (rr.get('refused') or {}).get('summary', '')
                return True, read_bytes(cpath)

            _txt = base_bytes.decode('utf-8')
            _first = _txt.index('\n  "') + 3        # the first member's quote
            keep = [
                ('a CRLF slice file', base_bytes.replace(b'\n', b'\r\n')),
                ('a slice file with a BOM', b'\xef\xbb\xbf' + base_bytes),
                ('a slice file with both', b'\xef\xbb\xbf'
                 + base_bytes.replace(b'\n', b'\r\n')),
                ('a key no schema declares',
                 (_txt[:_first] + '"aKeyNobodyDeclares": "hands off",\n  '
                  + _txt[_first:]).encode('utf-8')),
            ]
            lose = [
                ('a blank line between members',
                 (_txt[:_first - 3] + '\n' + _txt[_first - 3:]).encode('utf-8')),
                ('a // line comment',
                 (_txt[:_first - 2] + '// a note from the player\n  '
                  + _txt[_first - 2:]).encode('utf-8'), True),
                ('a /* */ block comment',
                 (_txt[:_first - 2] + '/* a note */\n  '
                  + _txt[_first - 2:]).encode('utf-8'), True),
                ('four-space indent',
                 (json.dumps(json.loads(_txt), indent=4, ensure_ascii=False)
                  + '\n').encode('utf-8')),
                ('no trailing newline', base_bytes.rstrip(b'\n')),
                ('a doubled trailing newline', base_bytes + b'\n'),
            ]
            for name, data in keep:
                ok, got = _roundtrip(data)
                t.check('the writer keeps %s exactly' % name,
                        ok and got == data,
                        got if not ok else 'in %d bytes -> out %d'
                        % (len(data), len(got)))
            for entry in lose:
                name, data = entry[0], entry[1]
                is_jsonc = len(entry) > 2 and entry[2]
                with open(cpath, 'wb') as _f:
                    _f.write(data)
                ap = App({'gameDir': '', 'configDirOverride': cdc2,
                          'stripReadme': False}, 'x')
                doc_c = read_document(cdc2, ap.schemas)
                nc = noncanonical_files(doc_c)
                t.check('%s is reported as not the form this editor writes, '
                        'BEFORE a save removes it' % name,
                        unit_file(canon_unit) in nc, sorted(nc))
                if is_jsonc:
                    t.check('%s is reported as content, not formatting — it is '
                            'read and cannot be written back' % name,
                            nc.get(unit_file(canon_unit), {}).get('jsonc'),
                            nc.get(unit_file(canon_unit)))
                ok, got = _roundtrip(data)
                t.check('%s does not survive the save, which is why it is '
                        'reported first' % name, ok and got != data,
                        got if not ok else 'survived')
                t.check('and what came back is the canonical form of the same '
                        'document — nothing but the formatting moved (%s)' % name,
                        ok and got == canonical_bytes(data),
                        'differs from canonical' if ok else got)
            with open(cpath, 'wb') as _f:
                _f.write(base_bytes)

        # Which shipped files are already in the form the writer produces.
        # Named either way: "none of them is" and "this did not look" are
        # different facts, and the one that is not is the one a first save
        # rewrites.
        nc_src = noncanonical_files(read_document(src, schemas))
        print('        shipped files NOT in the form this editor writes (%d of '
              '%d): %s' % (len(nc_src), len(read_document(src, schemas).file_raw),
                           ', '.join('%s (%d vs %d bytes%s)'
                                     % (k, v['disk'], v['canonical'],
                                        ', carries JSONC' if v['jsonc'] else '')
                                     for k, v in sorted(nc_src.items())) or 'none'))
        t.check('no shipped file carries comments or trailing commas — those '
                'are read and cannot be written back, so a shipped file '
                'carrying one loses it on the first save',
                not [k for k, v in nc_src.items() if v['jsonc']],
                [k for k, v in nc_src.items() if v['jsonc']])

        # ---- line endings, per file, both ways
        #
        # Phase 1 found the live .cfg CRLF that afternoon and LF that morning,
        # so nothing here assumes an ending anywhere. With one document there
        # was one ending to preserve; with a file per slice there are as many
        # as there are files, and a writer that normalised them all to one
        # would still pass a census taken over a directory that happens to be
        # uniform. So one file is forced the OTHER way and both are asserted in
        # the same save.
        cdnl = _sandbox(src, os.path.join(td, 'endings'))

        def _ends(path):
            raw = read_bytes(path)
            crlf = raw.count(b'\r\n')
            return crlf, raw.count(b'\n') - crlf

        nl_units = [u for u in units
                    if json_fields(app.schemas) and any(
                        f['type'] in ('int', 'float')
                        for (uu, _p), (_s, f) in json_fields(app.schemas).items()
                        if uu == u)]
        t.check('at least two units carry a numeric scalar, so one can be '
                'forced to CRLF and another left LF in the same save',
                len(nl_units) >= 2, nl_units)
        if len(nl_units) >= 2:
            u_crlf, u_lf = nl_units[0], nl_units[1]
            p_crlf = os.path.join(cdnl, unit_file(u_crlf))
            p_lf = os.path.join(cdnl, unit_file(u_lf))
            raw = read_bytes(p_crlf)
            with open(p_crlf, 'wb') as _f:
                _f.write(raw.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n'))
            t.check('the fixture really did turn %s into a CRLF file, and left '
                    '%s alone' % (unit_file(u_crlf), unit_file(u_lf)),
                    _ends(p_crlf)[1] == 0 and _ends(p_crlf)[0] > 0
                    and _ends(p_lf)[0] == 0 and _ends(p_lf)[1] > 0,
                    (_ends(p_crlf), _ends(p_lf)))
            appnl = App({'gameDir': '', 'configDirOverride': cdnl,
                         'stripReadme': False}, 'x')
            mnl = appnl.api_model()
            enl = _edits_for(appnl.schemas, mnl)
            moved_any = False
            for uu in (u_crlf, u_lf):
                for (u2, p2), (_s2, f2) in sorted(json_fields(appnl.schemas).items()):
                    if u2 != uu or f2['type'] not in ('int', 'float'):
                        continue
                    slot = mnl['values']['json'].get(u2, {}).get(p2)
                    if slot and slot.get('present') and isinstance(
                            slot.get('value'), (int, float)):
                        enl['json'][u2]['scalars'][p2] = {
                            'present': True, 'value': slot['value'] + 1}
                        moved_any = True
                        break
            t.check('both files really are being edited, so neither passes by '
                    'not being written', moved_any, (u_crlf, u_lf))
            rnl = appnl.api_save(enl)
            t.check('the two-file edit saved',
                    rnl['ok'] and unit_file(u_crlf) in rnl['written']
                    and unit_file(u_lf) in rnl['written'],
                    rnl.get('written') or rnl.get('refused'))
            t.check('the CRLF file came back CRLF, with no LF-only line left '
                    'in it', _ends(p_crlf)[1] == 0 and _ends(p_crlf)[0] > 0,
                    _ends(p_crlf))
            t.check('and the LF file beside it came back LF — the writer keeps '
                    'an ending per file, not one for the directory',
                    _ends(p_lf)[0] == 0 and _ends(p_lf)[1] > 0, _ends(p_lf))
            others = [unit_file(u) for u in units
                      if u not in (u_crlf, u_lf)]
            t.check('and every file the save did not touch kept its own ending',
                    all(_ends(os.path.join(cdnl, o))[0] == 0 for o in others),
                    [(o, _ends(os.path.join(cdnl, o))) for o in others
                     if _ends(os.path.join(cdnl, o))[0] != 0])
        by_sub_m = dict((sc['subsystem'], sc) for sc in app.schemas)
        # WAS, until 2026-09-13, under the comment "One gate each since 3.0, and
        # it is a path in the merged document. Elapse had two -- a cfg key and
        # the section's own 'enabled' -- and the cfg half is gone.":
        #
        #   t.check('the enable index reports effective state per subsystem',
        #           idx['Elapse']['effective'] == 'on'
        #           and len(idx['Elapse']['gates']) == 1
        #           and idx['Elapse']['gates'][0]['kind'] == 'json', ...)
        #   t.check('SelfCheck reads as deliberately off, from its own section',
        #           idx['SelfCheck']['effective'] == 'off', ...)
        #
        # split-config-into-toggleable-slices makes both gates cfg keys, and a
        # slice key is not in ckf.hardmode.cfg until the game has been launched
        # once, so both subsystems correctly read 'unknown' and both checks
        # failed. They asserted a VALUE that depends on whether the game has
        # run. The three-state contract is asserted against a built model
        # instead -- which is launch-independent and is the thing the nav toggle
        # relies on -- and the live reading is reported rather than asserted.
        class _FakeDoc:
            def __init__(self, schemas):
                self.schemas = schemas

        def _fixture_entry(slot, master=None):
            """enable_index over one made-up cfg-gated subsystem. -> its entry."""
            gated = {'subsystem': 'Fixture', 'title': 'Fixture',
                     'targets': {'cfg': 'ckf.hardmode.cfg'},
                     'enable': {'cfg': 'Slices.Fixture'}, 'fields': []}
            mast = {'subsystem': 'Master', 'title': 'Master',
                    'targets': {'cfg': 'ckf.hardmode.cfg'},
                    'enable': {'cfg': MASTER_KEY}, 'fields': []}
            model = {'cfg': {'Slices.Fixture': slot,
                             MASTER_KEY: master if master is not None
                             else {'present': True, 'value': True, 'error': None}},
                     'json': {}}
            out = enable_index(_FakeDoc([mast, gated]), model)
            return [e for e in out if e['subsystem'] == 'Fixture'][0]

        ON = {'present': True, 'value': True, 'error': None}
        OFF = {'present': True, 'value': False, 'error': None}
        ABSENT = {'present': False, 'value': None, 'raw': None}
        BROKEN = {'present': True, 'value': None, 'raw': 'yes', 'error': 'not a bool'}
        t.check('a gate that reads true is on', _fixture_entry(ON)['effective'] == 'on',
                _fixture_entry(ON))
        t.check('a gate that reads false is off', _fixture_entry(OFF)['effective'] == 'off',
                _fixture_entry(OFF))
        t.check('a gate whose key is not in the file is unknown, not off — '
                'design.md section 3, "an unreadable gate is unknown, never off"',
                _fixture_entry(ABSENT)['effective'] == 'unknown',
                _fixture_entry(ABSENT))
        t.check('and it says why rather than just saying unknown',
                _fixture_entry(ABSENT)['gates'][0]['detail'],
                _fixture_entry(ABSENT)['gates'])
        t.check('a gate whose value will not parse is unknown too, with the '
                'parse error as the reason',
                _fixture_entry(BROKEN)['effective'] == 'unknown'
                and _fixture_entry(BROKEN)['gates'][0]['detail'] == 'not a bool',
                _fixture_entry(BROKEN)['gates'])
        t.check('the master switch being off is reported separately from the '
                'subsystem\'s own gate, which still reads true',
                _fixture_entry(ON, OFF)['gatedByMaster'] is True
                and _fixture_entry(ON, OFF)['gates'][0]['state'] is True,
                _fixture_entry(ON, OFF))
        t.check('a master that cannot be read pulls an on subsystem to unknown '
                'rather than leaving it reading on',
                _fixture_entry(ON, ABSENT)['effective'] == 'unknown'
                and _fixture_entry(ON, ABSENT)['masterKnown'] is False,
                _fixture_entry(ON, ABSENT))

        # ...and against the config on disk, whatever state it is in.
        t.check('the enable index carries one entry per schema',
                len(m['enableIndex']) == len(app.schemas),
                (len(m['enableIndex']), len(app.schemas)))
        unreadable = [e for e in m['enableIndex']
                      if any(g['state'] is None for g in e['gates'])]
        print('        gates this config could not read (%d): %s'
              % (len(unreadable),
                 ', '.join(sorted(e['subsystem'] for e in unreadable)) or 'none'))
        t.check('no gate that could not be read is reported as off',
                all(e['effective'] == 'unknown' for e in unreadable),
                [(e['subsystem'], e['effective']) for e in unreadable
                 if e['effective'] != 'unknown'])
        t.check('every gate that could not be read names a reason',
                all(g['detail'] for e in m['enableIndex'] for g in e['gates']
                    if g['state'] is None),
                [(e['subsystem'], g) for e in m['enableIndex'] for g in e['gates']
                 if g['state'] is None and not g['detail']])
        t.check('every gate the index reports matches the spelling its schema '
                'declares',
                all(g['kind'] == ('cfg' if (by_sub_m[e['subsystem']].get('enable')
                                            or {}).get('cfg') else 'json')
                    for e in m['enableIndex'] for g in e['gates']),
                [(e['subsystem'], [g['kind'] for g in e['gates']])
                 for e in m['enableIndex']])
        t.check('retroactive fields are flagged in the schema the GUI renders',
                any(f.get('retroactive') for s in app.schemas for f in s['fields']))

        # a teampl override edit rewrites the mirror in the same save
        tk = U_TEAMPL + '|override'
        rows = json.loads(json.dumps(m['values']['tables'][tk]['rows']))
        # Pick a value that is NOT what the cell already holds. A literal
        # constant here is a trap: write_files skips a target whose proposed
        # bytes equal the current bytes, so once the live config happened to
        # carry the same number the save became a no-op, nothing was written,
        # no backup was taken, and the two backup checks below failed for a
        # reason that had nothing to do with the code. That is what a retune of
        # the Team PL table did on 2026-09-03 -- override[0] became 0.25, which
        # was the constant this test wrote. Derive it instead, and keep it
        # inside the column's declared [-5.0, 5.0] so the edit stays legal.
        _cur = rows[0]['cells'].get('PowerLevelFraction')
        NEW_FRACTION = 0.25 if not isinstance(_cur, (int, float)) or abs(_cur - 0.25) > 1e-12 else 0.26
        rows[0]['cells']['PowerLevelFraction'] = NEW_FRACTION
        edits = {'json': {U_TEAMPL:
                          {'scalars': {}, 'tables': {'override': {'shape': 'array', 'rows': rows}}}}}
        t.check('the teampl edit actually changes the cell, so the save is not a no-op',
                not isinstance(_cur, (int, float)) or abs(_cur - NEW_FRACTION) > 1e-12,
                (_cur, NEW_FRACTION))
        # What is in the directory before the save, so the cases below can name
        # what the SAVE left rather than what the fixture arrived carrying. The
        # fixtures are a copy of a real config directory, and a real one can
        # hold a .pre-gui-backup written by a build that still made them.
        before_files = set(_walk_rel(cd))
        res = app.api_save(edits)
        t.check('a teampl override save succeeds', res['ok'], res.get('refused'))
        t.check('the mirror was rewritten in the same save',
                'ckf.hardmode.d/MissionPowerLevelModel.generated.json' in res.get('written', []),
                res.get('written'))
        mir = check_schema.load_jsonc(os.path.join(
            cd, 'ckf.hardmode.d', 'MissionPowerLevelModel.generated.json'))
        hit = [r for r in mir['rules']
               if r['where']['ActionClass'] == rows[0]['cells']['ActionClass']
               and r['where']['MissionPowerLevel'] == rows[0]['cells']['MissionPowerLevel']]
        t.check('the mirror carries the new value for the edited cell',
                len(hit) == 1 and abs(hit[0]['set']['PowerLevelFraction'] - NEW_FRACTION) < 1e-12, hit)
        t.check('teampl.json carries the same value — the two halves agree',
                abs(_teampl_first_fraction(cd) - NEW_FRACTION) < 1e-12, _teampl_first_fraction(cd))
        after_set = set((p['kind'], p['message']) for p in res['checkAfter']['problems'])
        t.check('check_schema after the save matches the baseline exactly — '
                'the mirror invariant included',
                res['checkAfter']['ran'] and after_set == base_set,
                sorted(after_set ^ base_set))
        t.check('a save of a declared-but-absent table does not invent an empty one',
                'offDuty' not in json.dumps(  # any absent table would show up as {} or []
                    _read_section(cd, U_FATIGUE)
                    .get('offDuty', {}).get('byPowerLevel', 'ABSENT')))
        t.check('a relaunch reminder comes back with the save', bool(res.get('relaunch')))

        # REMOVED, 2026-09-07: the .pre-gui-backup copy every first save used
        # to leave beside the file it wrote, and the three cases that asserted
        # it appeared, matched the pre-save bytes, and survived a second save.
        # David's ruling: the editor writes the file the player asked it to
        # write and leaves nothing else in BepInEx/config. The transaction is
        # what makes that safe -- a crash cannot leave a half-written file --
        # and the reset is re-extracting BepInEx\config from the zip. These
        # two cases replace them: the directory after a save holds the config
        # and nothing else.
        new_after_save = sorted(set(_walk_rel(cd)) - before_files)
        t.check('a save creates no file except the ones it wrote',
                new_after_save == [], new_after_save)

        rows[0]['cells']['PowerLevelFraction'] = NEW_FRACTION + 0.05
        res2 = app.api_save(edits)
        t.check('a second save succeeds', res2['ok'], res2.get('refused'))
        new_after_second = sorted(set(_walk_rel(cd)) - before_files)
        t.check('a second save creates none either',
                new_after_second == [], new_after_second)
        t.check('no journal is left behind', not os.path.exists(journal_path(cd)))
        t.check('no temporaries are left behind',
                not [f for f in os.listdir(cd) if TMP_SUFFIX in f], os.listdir(cd))

        # a RANGE violation is refused
        rows[0]['cells']['PowerLevelFraction'] = 99.0     # declared range [0, 5]
        bad = app.api_save(edits)
        t.check('a RANGE violation is refused', not bad['ok'], bad)
        t.check('the refusal names RANGE',
                any(p['kind'] == 'RANGE' for p in (bad.get('blocking') or [])), bad.get('blocking'))
        t.check('nothing was written by the refused save',
                abs(_teampl_first_fraction(cd) - (NEW_FRACTION + 0.05)) < 1e-12,
                _teampl_first_fraction(cd))

        # an INVARIANT violation is refused
        #
        # WAS, until 2026-09-13: a json edit writing `enabled` in the teampl
        # section, under the comment "3.0 moved both halves of the linkedEnable
        # group out of the cfg and into the merged document, so this is a json
        # edit now." split-config-into-toggleable-slices moves them back --
        # teampl.schema.json's group now names `Slices.Progression` and
        # `Slices.ModelRules`, both cfg keys -- and the json paths this wrote
        # no longer exist in any schema.
        #
        # THE FIRST OF THE THREE WENT ON PASSING WHILE MEASURING NOTHING. It
        # asked only `not badinv['ok']`, and the save WAS refused: with "no
        # schema declares ckf.hardmode.json#teampl path 'enabled'", which has
        # nothing to do with the invariant. A refusal check that does not read
        # the reason cannot fail. Both halves read the kind now.
        #
        # The group's keys are read off the schema rather than spelled, so this
        # follows them wherever the next phase puts them, and the fixture
        # carries them because the live .cfg does not yet.
        linked_groups = [inv for sc in schemas for inv in sc.get('invariants', [])
                         if inv.get('kind') == 'linkedEnable']
        t.check('at least one linkedEnable group is declared to exercise',
                linked_groups, [sc['subsystem'] for sc in schemas])
        if linked_groups:
            lg = linked_groups[0]
            units = sidecar_names(schemas)

            def _key_parts(k):
                """One invariant key -> ('cfg', key) or ('json', unit, path)."""
                if '#' not in k:
                    return ('cfg', k)
                for u in units:
                    if k.startswith(u + '.'):
                        return ('json', u, k[len(u) + 1:])
                raise KeyError('no unit for linkedEnable key %r' % k)

            def _edits_for_keys(keys, val):
                out = {'cfg': {}, 'json': {}}
                for k in keys:
                    p = _key_parts(k)
                    if p[0] == 'cfg':
                        out['cfg'][p[1]] = {'value': val}
                    else:
                        blk = out['json'].setdefault(p[1], {'scalars': {}, 'tables': {}})
                        blk['scalars'][p[2]] = {'present': True, 'value': val}
                return out

            def _live_value(cd_, k):
                p = _key_parts(k)
                if p[0] == 'cfg':
                    raw = CfgFile.load(os.path.join(cd_, 'ckf.hardmode.cfg')).raw_value(p[1])
                    return None if raw is None else raw.strip().lower() == 'true'
                return dig(_read_section(cd_, p[1]), p[2])[0]

            def _file_of(k):
                p = _key_parts(k)
                return 'ckf.hardmode.cfg' if p[0] == 'cfg' else unit_file(p[1])

            cdl = _sandbox(src, os.path.join(td, 'linked'))
            lcfg = CfgFile.load(os.path.join(cdl, 'ckf.hardmode.cfg'))
            missing_keys = [k for k in lg['keys']
                            if _key_parts(k)[0] == 'cfg' and k not in lcfg.keys]
            if missing_keys:
                okl, whyl = _cfg_with_keys(os.path.join(cdl, 'ckf.hardmode.cfg'),
                                           missing_keys)
                t.check('the linkedEnable fixture supplies the keys the source '
                        'does not carry', okl, whyl)
            print('        linkedEnable group under test: %s' % ', '.join(lg['keys']))
            print('        keys the live cfg does not carry, supplied by the '
                  'fixture (%d): %s'
                  % (len(missing_keys), ', '.join(missing_keys) or 'none'))
            appl = App({'gameDir': '', 'configDirOverride': cdl,
                        'stripReadme': False}, 'x')
            t.check('every key of the group is readable in the fixture before '
                    'anything is written to it',
                    all(_live_value(cdl, k) is not None for k in lg['keys']),
                    [(k, _live_value(cdl, k)) for k in lg['keys']])

            badinv = appl.api_save(_edits_for_keys(lg['keys'][:1], False))
            t.check('a half-on linkedEnable group is refused', not badinv['ok'], badinv)
            t.check('the refusal names INVARIANT',
                    any(p['kind'] == 'INVARIANT' for p in (badinv.get('blocking') or [])),
                    badinv.get('blocking') or badinv.get('refused'))
            t.check('and the half that was moved is unchanged on disk',
                    _live_value(cdl, lg['keys'][0]) is True,
                    _live_value(cdl, lg['keys'][0]))

            okinv = appl.api_save(_edits_for_keys(lg['keys'], False))
            t.check('the linked group moving together is accepted',
                    okinv['ok'], okinv.get('refused'))
            t.check('and every key of the group is false on disk',
                    all(_live_value(cdl, k) is False for k in lg['keys']),
                    [(k, _live_value(cdl, k)) for k in lg['keys']])
            t.check('and the only files written are the ones the group\'s keys '
                    'live in',
                    set(okinv.get('written') or [])
                    == set(_file_of(k) for k in lg['keys']),
                    (okinv.get('written'), sorted(set(_file_of(k) for k in lg['keys']))))

        # ---- requires, the directed invariant, over the save path
        #
        # split-config-into-toggleable-slices Phase 2, checkboxes 4 and 5, and
        # design.md section 4: "Enforcement is asymmetric on purpose."
        #
        # WHICH OF THE TWO FIRES FIRST IS ASSERTED, NOT ASSUMED. The editor's
        # own refusal runs before apply_edits renders any bytes and before
        # stage_and_validate runs check_schema, so its payload carries neither
        # 'check' nor 'blocking'; check_schema's INVARIANT refusal carries
        # both. Every refusal below is read for which one it is.
        rq = requires_groups(schemas)
        t.check('at least one requires group is declared to exercise — a loop '
                'over none is not a pass', rq,
                [sc['subsystem'] for sc in schemas])
        cfg_declared = cfg_fields(schemas)
        rq_cfg = [g for g in rq
                  if g[1] in cfg_declared
                  and all(k in cfg_declared for k in g[2]) and g[2]]
        print('        requires groups declared: %d, of which %d name only cfg '
              'keys this build declares' % (len(rq), len(rq_cfg)))
        t.check('at least one of them names only cfg keys, which is what the '
                'cases below drive', rq_cfg, rq)
        if rq_cfg:
            RSUB, RDEP, RNEEDS, RREASON = rq_cfg[0]
            RNEED = RNEEDS[0]
            cdq = _sandbox(src, os.path.join(td, 'requires'))
            cfgq = os.path.join(cdq, 'ckf.hardmode.cfg')
            okq, whyq = _cfg_with_keys(cfgq, [RDEP, RNEED])
            t.check('the requires fixture carries both keys of the group',
                    okq, whyq)
            appq = App({'gameDir': '', 'configDirOverride': cdq,
                        'stripReadme': False}, 'x')

            def _rv(k):
                raw = CfgFile.load(cfgq).raw_value(k)
                return None if raw is None else raw.strip().lower() == 'true'

            def _rnotes(res):
                return [n for n in (res.get('notes') or [])
                        if n.startswith('requires:')]

            # (a) the census prints on every save, whatever happened
            r0 = appq.api_validate({'cfg': {}, 'json': {}})
            t.check('a validate with no edits still reports the requires '
                    'census — "0 declared" and "2 declared, 0 compared" are '
                    'different facts and a line that appeared only on a '
                    'change could not tell them apart',
                    any('declared' in n and 'compared' in n for n in _rnotes(r0)),
                    _rnotes(r0))

            # (b) down: the need turned off under a live dependent
            t.check('the fixture starts with the dependent on, or the refusal '
                    'below proves nothing', _rv(RDEP) is True, _rv(RDEP))
            rdown = appq.api_save({'cfg': {RNEED: {'value': False}}})
            t.check('turning off a key an enabled slice requires is refused',
                    not rdown['ok'], rdown)
            t.check('and the refusal is the EDITOR\'s, not the checker\'s: it '
                    'reached neither check_schema nor the blocking list',
                    'check' not in rdown and 'blocking' not in rdown,
                    sorted(rdown.keys()))
            t.check('and it names the dependent, which is the whole point — '
                    'check_schema can only say INVARIANT',
                    RDEP in ((rdown.get('refused') or {}).get('summary') or ''),
                    rdown.get('refused'))
            t.check('and carries it as data as well as prose, so a caller does '
                    'not have to parse the sentence',
                    ((rdown.get('refused') or {}).get('requires') or {})
                    .get('dependent') == RDEP, rdown.get('refused'))
            t.check('and nothing was written', _rv(RNEED) is True, _rv(RNEED))

            # (c) the dependent and its need going off together is legal, which
            #     is also what check_schema says: a false dependent is vacuous
            rboth = appq.api_save({'cfg': {RDEP: {'value': False},
                                           RNEED: {'value': False}}})
            t.check('turning the dependent and what it needs off together is '
                    'accepted — off is refused only while something needs it',
                    rboth['ok'], rboth.get('refused'))
            t.check('and both are off on disk',
                    _rv(RDEP) is False and _rv(RNEED) is False,
                    (_rv(RDEP), _rv(RNEED)))

            # (d) up: turning the dependent back on pulls the need with it
            rup = appq.api_save({'cfg': {RDEP: {'value': True}}})
            t.check('turning the dependent on is accepted', rup['ok'],
                    rup.get('refused'))
            t.check('and the key it needs went on with it, in the same save',
                    _rv(RNEED) is True, _rv(RNEED))
            t.check('and a note names the key that changed',
                    any(RNEED in n for n in _rnotes(rup)), _rnotes(rup))
            t.check('and names the slice that caused it — an auto-enable '
                    'nobody is told about is a config changed behind the '
                    'player\'s back',
                    any(RNEED in n and RDEP in n for n in _rnotes(rup)),
                    _rnotes(rup))
            t.check('and the census counts it rather than only the prose',
                    any('1 turned on' in n for n in _rnotes(rup)), _rnotes(rup))
            t.check('and check_schema is clean afterwards, which is the state '
                    'the auto-enable exists to produce',
                    rup['checkAfter']['ran']
                    and not [p for p in rup['checkAfter']['problems']
                             if p['kind'] in BLOCKING],
                    rup['checkAfter'])

            # (e) a violation already on disk is NOT papered over
            #
            # The upward closure is seeded only by what the save turns on. A
            # dependent already true with its need already false was made by a
            # hand edit, and widening it here would change a config the player
            # never touched. It goes to check_schema instead, which is the
            # scenario "A hand-edited violation blocks the save".
            cdh = _sandbox(src, os.path.join(td, 'requires-hand'))
            okh2, whyh2 = _cfg_with_keys(os.path.join(cdh, 'ckf.hardmode.cfg'),
                                         [RDEP, RNEED])
            t.check('the hand-edit fixture builds', okh2, whyh2)
            apph2 = App({'gameDir': '', 'configDirOverride': cdh,
                         'stripReadme': False}, 'x')
            rseed = apph2.api_save({'cfg': {RDEP: {'value': False},
                                            RNEED: {'value': False}}})
            t.check('the hand-edit fixture reaches both-off first', rseed['ok'],
                    rseed.get('refused'))
            # now the hand edit: the dependent alone goes back on, written
            # through the cfg writer rather than through a save, so the editor
            # never sees the flip.
            hcfg = CfgFile.load(os.path.join(cdh, 'ckf.hardmode.cfg'))
            hcfg.set_value(RDEP, 'true')
            with open(os.path.join(cdh, 'ckf.hardmode.cfg'), 'wb') as _f:
                _f.write(hcfg.to_bytes())
            apph3 = App({'gameDir': '', 'configDirOverride': cdh,
                         'stripReadme': False}, 'x')
            mh = apph3.api_model()
            t.check('check_schema grades the hand-edited state INVARIANT',
                    any(p['kind'] == 'INVARIANT' and RNEED in p['message']
                        for p in mh['check']['problems']), mh['check'])
            rh2 = apph3.api_save({'cfg': {}, 'json': {}})
            t.check('and a save that touches nothing else is blocked by it, '
                    'not quietly widened by the editor',
                    not rh2['ok']
                    and any(p['kind'] == 'INVARIANT'
                            for p in (rh2.get('blocking') or [])),
                    rh2.get('blocking') or rh2.get('refused'))
            t.check('and that refusal IS the checker\'s: it carries the check '
                    'and the blocking list the editor\'s refusal does not',
                    'check' in rh2 and 'blocking' in rh2, sorted(rh2.keys()))

            # (f) a chain, and a cycle. NEITHER IS DECLARED ON DISK -- the two
            #     declarations are one hop each -- so transitivity would be an
            #     untested claim. The chain is wired into a copy of the schema
            #     list in memory; nothing under schema/ is read differently or
            #     written. A one-hop closure fails the chain case, and a
            #     closure with no termination bound hangs on the cycle.
            free_keys = [k for k in sorted(cfg_declared)
                         if k != MASTER_KEY
                         and not any(k == g[1] or k in g[2] for g in rq)
                         and not any(k in inv['keys'] for sc in schemas
                                     for inv in sc.get('invariants', [])
                                     if inv.get('kind') == 'linkedEnable')]
            t.check('three unencumbered cfg keys are available to wire into a '
                    'chain', len(free_keys) >= 3, len(free_keys))
            if len(free_keys) >= 3:
                KA, KB, KC = free_keys[:3]
                cdc = _sandbox(src, os.path.join(td, 'requires-chain'))
                okc, whyc = _cfg_with_keys(os.path.join(cdc, 'ckf.hardmode.cfg'),
                                           [KA, KB, KC])
                t.check('the chain fixture builds', okc, whyc)
                appc = App({'gameDir': '', 'configDirOverride': cdc,
                            'stripReadme': False}, 'x')
                rc0 = appc.api_save({'cfg': {KA: {'value': False},
                                             KB: {'value': False},
                                             KC: {'value': False}}})
                t.check('the chain fixture starts with all three off',
                        rc0['ok'], rc0.get('refused'))
                docc = read_document(cdc, schemas)

                def _wired(pairs):
                    syn = json.loads(json.dumps(schemas))
                    syn[0]['invariants'] = (syn[0].get('invariants') or []) + [
                        {'kind': 'requires', 'key': a, 'needs': [b],
                         'reason': 'wired by the self-test, not declared on disk'}
                        for a, b in pairs]
                    return syn

                ec, nc = requires_pass(_wired([(KA, KB), (KB, KC)]), docc,
                                       {'cfg': {KA: {'value': True}}, 'json': {}})
                t.check('a chain is followed past the first hop',
                        ec['cfg'].get(KB, {}).get('value') is True, ec['cfg'])
                t.check('and past the second — a one-hop closure fails here',
                        ec['cfg'].get(KC, {}).get('value') is True, ec['cfg'])
                t.check('and both hops are named, not just the first',
                        any(KB in n for n in nc) and any(KC in n for n in nc),
                        [n for n in nc if n.startswith('requires:')])
                ecy, ncy = requires_pass(_wired([(KA, KB), (KB, KA)]), docc,
                                         {'cfg': {KA: {'value': True}},
                                          'json': {}})
                t.check('a cycle settles instead of spinning',
                        ecy['cfg'].get(KB, {}).get('value') is True, ecy['cfg'])
                t.check('and is not reported as an unsettled closure, because '
                        'it settled',
                        not any('did not settle' in n for n in ncy), ncy)

                # (g) a declaration naming a key nothing declares is SKIPPED
                #     OUT LOUD. check_schema grades it STALE; the editor must
                #     not look like it enforced a declaration it never read.
                syn2 = json.loads(json.dumps(schemas))
                bogus = 'Slices.' + 'NoSuchSliceKey'
                syn2[0]['invariants'] = [{'kind': 'requires', 'key': KA,
                                          'needs': [bogus], 'reason': 'r'}]
                _e3, n3 = requires_pass(syn2, docc,
                                        {'cfg': {KA: {'value': True}},
                                         'json': {}})
                t.check('a requires naming an undeclared key is reported '
                        'SKIPPED by name, never silently ignored',
                        any('SKIPPED' in n and bogus in n for n in n3), n3)
                t.check('and the census counts the skip',
                        any('1 skipped' in n for n in n3), n3)
                syn3 = json.loads(json.dumps(schemas))
                syn3[0]['invariants'] = [{'kind': 'requires', 'key': KA,
                                          'needs': [], 'reason': 'r'}]
                _e4, n4 = requires_pass(syn3, docc,
                                        {'cfg': {KA: {'value': True}},
                                         'json': {}})
                t.check('a requires with no needs compares nothing and says so '
                        '— the exact shape of an instrument reporting success '
                        'over an empty input',
                        any('SKIPPED' in n and 'no needs' in n for n in n4), n4)

        # REMOVED IN 3.0, with the code they tested:
        #
        #   "a declared key that is absent is appended"
        #   "the appended key lands under its own section header"
        #   "the appended line carries no comment"
        #   "a cfg value carrying a newline is refused, not an AssertionError"
        #   "a cfg value that would read back as a comment is refused"
        #   "the guards are refusals, not assertions - they survive python -O"
        #
        # All six drove CfgFile.set_value's append-under-a-section-header path
        # and the two round-trip refusals it needed, through [SelfCheck] File --
        # a cfg key that is now selfcheck.file in ckf.hardmode.json. The one
        # key left in the cfg is a bool on a key BepInEx always writes, so
        # neither an appended line nor a value carrying a '#' or a newline can
        # be reached. Section 13(d) is where the writer that is left is tested,
        # including that a key the file does not carry is refused rather than
        # created.

        # ---- 8. a .cfg whose line endings are mixed
        #
        # AGENTS.md section 6 has agents editing this file line by line, and a
        # tool that rewrites one line of a CRLF file with an LF ending produces
        # exactly this. Splitting the whole file on one sniffed separator
        # merged the LF-ended line into the next one, and what came out was a
        # silent WRONG WRITE, not a read error.
        #
        # CORRECTION, 2026-09-13 morning. This fixture used to be the live
        # ckf.hardmode.cfg exactly as read, guarded by a check named
        # 'the fixture source really is CRLF' and followed by
        # `clean_raw.rindex(b'\r\n', 0, gj)` to find an ending to flip. The
        # file was LF that morning -- 162 bytes, 8 LF, 0 CRLF -- so the check
        # FAILed and the rindex two lines under it raised
        # `ValueError: subsection not found`, which ended the whole run before
        # its report line -- no pass count at all. Reported by David.
        #
        # Same defect class as the three checks TASKS.md records on
        # 2026-09-03: a check written against live data stops testing the code
        # the moment the data moves, and then fails as if the code regressed.
        # The fix is the same one -- MAKE the condition in the fixture instead
        # of hoping the source supplies it. The source file's content is still
        # what is read, so the section still indexes the real sections and the
        # real key, but every ending is normalised to CRLF here and exactly one
        # of them is flipped to LF here.
        #
        # SECOND CORRECTION, 2026-09-13 afternoon. THE FIX ABOVE STANDS; ITS
        # STATED REASON DID NOT. The paragraph above used to continue: "That
        # claim is not true of this file and was never true of a file BepInEx
        # had written. BepInEx owns ckf.hardmode.cfg and rewrites it from the
        # keys the plugin binds on game exit, and what it writes is LF ...
        # ckf.datadump.cfg beside it measured 448 bytes, 23 LF, 0 CRLF", and
        # ended "What BepInEx writes no longer decides whether this section
        # runs."
        #
        # A launch that afternoon rewrote ckf.hardmode.cfg as 3,238 bytes,
        # 179 CRLF, 0 LF, and ckf.datadump.cfg as 24,988 bytes, 317 CRLF and 3
        # lone LF [measured]. So "what it writes is LF" was false, and the
        # original 'the fixture source really is CRLF' check would now PASS --
        # not because it was right, but because the data moved back underneath
        # it. That is the whole argument for building the condition here: this
        # section was correct to stop depending on the source's endings, and it
        # would have gone on running unchanged through both states. Only the
        # sentence explaining why was wrong. See the line-endings note above
        # class CfgFile for the three observations and for what is not known.
        print('\n[8] a .cfg with mixed line endings')

        def _lone_lf(b):
            """LF bytes that are not the second half of a CRLF."""
            return b.replace(b'\r\n', b'').count(b'\n')

        # every ending forced to CRLF, whatever the source arrived with
        clean_raw = (read_bytes(os.path.join(src, 'ckf.hardmode.cfg'))
                     .replace(b'\r\n', b'\n').replace(b'\r', b'\n')
                     .replace(b'\n', b'\r\n'))
        clean = CfgFile(clean_raw)

        # the ending of the line ABOVE [General]'s Enabled. find/rfind rather
        # than index/rindex: a source that has lost the key must read as a
        # FAIL below, not as a traceback that ends the run.
        gi = clean_raw.find(b'[General]')
        gj = clean_raw.find(b'Enabled', gi) if gi >= 0 else -1
        gk = clean_raw.rfind(b'\r\n', 0, gj) if gj >= 0 else -1
        t.check('the fixture this section builds is all-CRLF and carries the key it edits',
                b'\r\n' in clean_raw and _lone_lf(clean_raw) == 0 and gk >= 0,
                (clean_raw.count(b'\r\n'), _lone_lf(clean_raw), gi, gj, gk))

        # that one ending rewritten as LF
        mixed = (clean_raw[:gk] + b'\n' + clean_raw[gk + 2:]) if gk >= 0 else clean_raw
        t.check('the mixed fixture differs from the all-CRLF one by exactly one ending',
                len(mixed) == len(clean_raw) - 1
                and b'\r\n' in mixed and _lone_lf(mixed) == 1,
                (len(clean_raw) - len(mixed), mixed.count(b'\r\n'), _lone_lf(mixed)))
        cm = CfgFile(mixed)
        t.check('a mixed-ending cfg indexes every section the CRLF one does',
                cm.sections == clean.sections,
                sorted(set(cm.sections) ^ set(clean.sections)))
        t.check('a mixed-ending cfg indexes every key, at the same line',
                cm.keys == clean.keys,
                sorted(set(cm.keys) ^ set(clean.keys)))
        t.check('and reads the same value for every one of them',
                cm.all_keys() == clean.all_keys())
        t.check('the master switch is not among the keys that go missing',
                MASTER_KEY in cm.keys, sorted(cm.keys))
        t.check('a no-op save of a mixed-ending cfg is byte-identical',
                cm.to_bytes() == mixed, _first_line_diff(cm.to_bytes(), mixed))

        cm2 = CfgFile(mixed)
        try:
            placed = cm2.set_value(MASTER_KEY, 'false')
        except SaveRefused as e:
            # A regression that merges the LF-ended line into the Enabled line
            # loses the key, and set_value REFUSES a key it cannot see. That is
            # this section's subject failing, so it has to read as a FAIL here
            # rather than as a traceback that ends the run before its report.
            placed = 'refused: %s' % e.payload.get('summary', '')
        t.check('the master switch is replaced in place, not appended a second time',
                placed == 'replaced', placed)
        wrote = cm2.to_bytes()
        t.check('and the file still carries exactly one line for it',
                _cfg_key_line_count(wrote, 'General', 'Enabled') == 1,
                _cfg_key_line_count(wrote, 'General', 'Enabled'))
        t.check('the rewritten line keeps the CRLF ending it had',
                b'Enabled = false\r\n' in wrote)
        t.check('every other line of the file is untouched',
                _one_line_changed(mixed, wrote), _first_line_diff(mixed, wrote))

        # the other half: an LF-only line above a header swallows the header,
        # and every key below it lands in the section before it.
        swallow = b'[Alpha]\r\nEnabled = true\r\n## a note\n[Beta]\r\nEnabled = false\r\n'
        cs = CfgFile(swallow)
        t.check('an LF-only line above a header does not swallow the header',
                sorted(cs.sections) == ['Alpha', 'Beta'], sorted(cs.sections))
        t.check('the key under the swallowed header is not filed under the one before it',
                cs.all_keys() == {'Alpha.Enabled': 'true', 'Beta.Enabled': 'false'},
                cs.all_keys())
        t.check('a mixed-ending file with no trailing newline round-trips too',
                CfgFile(swallow[:-2]).to_bytes() == swallow[:-2])
        try:
            cs.set_value('Beta.Enabled', 'true')
        except SaveRefused:
            # Same reason as the refusal caught above: a swallowed [Beta] means
            # set_value cannot see the key, and the two checks under this have
            # to report that rather than the run ending on a traceback.
            pass
        t.check('the write lands in its own section, not in the one above it',
                cs.to_bytes()
                == b'[Alpha]\r\nEnabled = true\r\n## a note\n[Beta]\r\nEnabled = true\r\n',
                cs.to_bytes())
        t.check('and no duplicate section header was appended',
                cs.to_bytes().count(b'[Beta]') == 1)

        # ---- 8b. the four scenarios of "Line-by-line `.cfg` editing in the GUI"
        #
        # openspec/changes/split-config-into-toggleable-slices/specs/
        # config-surface/spec.md. Those four scenarios ARE the specification
        # for the write path -- the code implementing them is a rewrite, not a
        # restore, because the commit tasks.md named does not exist in this
        # repository (see the header comment above class CfgFile). So there is
        # no prior implementation to compare against and the scenarios are the
        # only thing pinning the behaviour. One named case per scenario,
        # spelled the way the scenario is, so the mapping can be read off the
        # output without opening the spec.
        print('\n[8b] the `.cfg` editing scenarios, one case per scenario')

        # SCENARIO 1: "A toggle change rewrites one line"
        #   THEN that key's value line is replaced in place
        #   AND every other line keeps its exact bytes, including its ending
        #   AND no comment is written and no key is appended that already exists
        # THE SOURCE IS READ; ITS SHAPE IS NOT ASSUMED.
        #
        # CORRECTION, 2026-09-13 afternoon. As first written this section took
        # the live ckf.hardmode.cfg and assumed two things about it: that it
        # had no [Slices] section, and that Slices.RuleModel was not in it.
        # Both held that morning (162 bytes, one key) and neither held after
        # the launch (3,238 bytes, 43 keys), so eight cases here FAILed --
        # including one named 'the live .cfg really has no [Slices] section'.
        #
        # That is the SAME defect this file corrected in section [8] earlier
        # the same day, written into a new section hours later by the agent
        # that had just written the correction. The guard caught it and said
        # so rather than the run dying, which is the only part that worked as
        # intended. The fix is the one section [8] already uses: BUILD the
        # condition. `s8_nosec` below is the source with [Slices] removed
        # whatever it arrived with, and `s8_withsec` is that plus one seeded
        # key, so the create-a-section half and the append-under-a-header half
        # both run in either state.
        s1_src = read_bytes(os.path.join(src, 'ckf.hardmode.cfg'))
        _s8_dir = os.path.join(td, 'cfg-scen')
        os.makedirs(_s8_dir, exist_ok=True)
        _s8_p = os.path.join(_s8_dir, 'ckf.hardmode.cfg')

        def _s8_build(without=(), with_=()):
            """-> (raw, ok, reason). Never raises: a fixture that cannot be
            built is a FAIL naming why, not a traceback."""
            with open(_s8_p, 'wb') as fh:
                fh.write(s1_src)
            ok, why = (True, '')
            if without:
                ok, why = _cfg_without_keys(_s8_p, without)
            if ok and with_:
                for k, v in with_:
                    ok, why = _cfg_with_keys(_s8_p, [k], v)
                    if not ok:
                        break
            return read_bytes(_s8_p), ok, why

        _s8_slice_keys = sorted(k for k in cfg_fields(schemas)
                                if k.split('.', 1)[0] == 'Slices')
        s8_nosec, s8_ok, s8_why = _s8_build(without=_s8_slice_keys)
        t.check('the scenario fixtures build from the source, in whichever '
                'state it arrived', s8_ok, s8_why)
        t.check('and the derived source really has no [Slices] section, so the '
                'create-a-section cases below exercise a creation',
                'Slices' not in CfgFile(s8_nosec).sections,
                sorted(CfgFile(s8_nosec).sections))
        t.check('and it still carries the master switch, so removing the slice '
                'keys removed only those',
                MASTER_KEY in CfgFile(s8_nosec).keys, sorted(CfgFile(s8_nosec).keys))

        # A FIXTURE BUILDER THAT CANNOT BUILD ITS CONDITION RETURNS A REASON.
        # It does not raise. _cfg_add_keys, the helper these two replace, threw
        # AssertionError when handed a file already in the target state, and on
        # 2026-09-13 that ended the whole run with no report line -- the third
        # time this file did that in a day. The property is checked here rather
        # than assumed, because the mutation that puts the raise back changes
        # only an error branch and every other case in this suite would stay
        # green.
        _s8_bad = os.path.join(_s8_dir, 'no-such-dir', 'nope.cfg')
        for _fn, _name, _args in (
                (_cfg_with_keys, '_cfg_with_keys', (_s8_bad, ['Slices.X'])),
                (_cfg_without_keys, '_cfg_without_keys', (_s8_bad, ['Slices.X'])),
                (_cfg_with_keys, '_cfg_with_keys', (_s8_p, ['NoSectionInThisKey']))):
            try:
                _ok, _why = _fn(*_args)
                _res = ('returned', _ok, _why)
            except BaseException as e:          # noqa: BLE001 -- that IS the defect
                _res = ('raised', type(e).__name__, str(e)[:120])
            t.check('%s returns a reason instead of raising when it cannot '
                    'build the fixture (%s)'
                    % (_name, 'unwritable path' if _args[0] is _s8_bad else 'malformed key'),
                    _res[0] == 'returned' and _res[1] is False and bool(_res[2]),
                    _res)
        s1 = CfgFile(s1_src)
        s1_was = s1.raw_value(MASTER_KEY)
        s1_what = s1.set_value(MASTER_KEY, 'false' if s1_was != 'false' else 'true')
        s1_out = s1.to_bytes()
        t.check('scenario 1: a toggle change replaces the key\'s value line in place',
                s1_what == 'replaced', s1_what)
        t.check('scenario 1: and every other line keeps its exact bytes and its ending',
                _one_line_changed(s1_src, s1_out), _first_line_diff(s1_src, s1_out))
        t.check('scenario 1: and no key that already exists is appended a second time',
                _cfg_key_line_count(s1_out, 'General', 'Enabled') == 1,
                _cfg_key_line_count(s1_out, 'General', 'Enabled'))
        t.check('scenario 1: and no comment line is written',
                s1_out.count(b'#') == s1_src.count(b'#'),
                (s1_src.count(b'#'), s1_out.count(b'#')))
        t.check('scenario 1: and writing the same value back is a no-op, so a '
                'save with no edits writes nothing',
                CfgFile(s1_src).set_value(MASTER_KEY, s1_was) == 'unchanged')

        # SCENARIO 2: "A new key is appended under its section"
        #   THEN the key is appended under that section header
        #   AND a section that does not exist is created with the key under it
        #
        # Both halves are driven off the live file's own bytes. [Slices] is the
        # section every slice toggle lands in and the live file has no such
        # section [measured, 2026-09-13: 162 bytes, [General] only], so the
        # second half is the state the editor is actually in today, not an
        # edge case built for the test.
        s2a = CfgFile(s8_nosec)
        s2a_what = s2a.set_value('General.Appended', 'true')
        t.check('scenario 2: a key whose section exists is appended, not refused',
                s2a_what == 'appended', s2a_what)
        t.check('scenario 2: and it is indexed under that section header, '
                'below it and above any header that follows',
                s2a.keys.get('General.Appended', -1) > s2a.sections['General'],
                (s2a.keys.get('General.Appended'), s2a.sections))
        t.check('scenario 2: and the lines that were already there are '
                'untouched — content and endings both',
                _is_pure_insertion(s8_nosec, s2a.to_bytes()),
                _first_line_diff(s8_nosec, s2a.to_bytes()))
        t.check('scenario 2: and the appended line carries no comment',
                s2a.to_bytes().count(b'#') == s8_nosec.count(b'#'),
                (s8_nosec.count(b'#'), s2a.to_bytes().count(b'#')))

        # The live file has ONE section, so in it "under [General]" and "at the
        # end of the file" are the same line and the check above cannot tell
        # them apart -- it passes for a writer that appends everything to the
        # end. A section with another one after it is what makes the two
        # distinguishable, so the placement is pinned here instead.
        s2m_src = (b'## header comment\n'
                   b'[Alpha]\n'
                   b'\n'
                   b'# Setting type: Boolean\n'
                   b'One = 1\n'
                   b'\n'
                   b'[Beta]\n'
                   b'Two = 2\n')
        s2m = CfgFile(s2m_src)
        t.check('scenario 2: the placement fixture really has a section after '
                'the one being appended to — without that, "under its header" '
                'and "at the end of the file" are the same line',
                sorted(s2m.sections) == ['Alpha', 'Beta']
                and s2m.sections['Beta'] > s2m.sections['Alpha'],
                s2m.sections)
        s2m.set_value('Alpha.Three', '3')
        t.check('scenario 2: a key appended to a section that is not the last '
                'one lands inside it, above the next header',
                s2m.to_bytes()
                == (b'## header comment\n[Alpha]\n\n# Setting type: Boolean\n'
                    b'One = 1\nThree = 3\n\n[Beta]\nTwo = 2\n'),
                s2m.to_bytes())
        t.check('scenario 2: and re-reading files it under its own section, '
                'not under the one below it',
                CfgFile(s2m.to_bytes()).all_keys()
                == {'Alpha.One': '1', 'Alpha.Three': '3', 'Beta.Two': '2'},
                CfgFile(s2m.to_bytes()).all_keys())
        t.check('scenario 2: and the blank line that separated the sections is '
                'still there, so the new key did not land below the separator',
                _is_pure_insertion(s2m_src, s2m.to_bytes()),
                _first_line_diff(s2m_src, s2m.to_bytes()))
        s2e = CfgFile(b'[Alpha]\n[Beta]\nTwo = 2\n')
        s2e.set_value('Alpha.One', '1')
        t.check('scenario 2: and a section with no keys at all takes the key '
                'directly under its header',
                s2e.to_bytes() == b'[Alpha]\nOne = 1\n[Beta]\nTwo = 2\n',
                s2e.to_bytes())

        s2b = CfgFile(s8_nosec)
        s2b_what = s2b.set_value('Slices.RuleModel', 'false')
        t.check('scenario 2: a section that does not exist is created',
                s2b_what == 'section-created', s2b_what)
        t.check('scenario 2: and the key is under it, and reads back',
                s2b.raw_value('Slices.RuleModel') == 'false'
                and s2b.keys['Slices.RuleModel'] > s2b.sections['Slices'],
                (s2b.raw_value('Slices.RuleModel'), s2b.keys.get('Slices.RuleModel'),
                 s2b.sections.get('Slices')))
        t.check('scenario 2: and creating it left every existing line alone',
                _is_pure_insertion(s8_nosec, s2b.to_bytes()),
                _first_line_diff(s8_nosec, s2b.to_bytes()))
        s2b_what2 = s2b.set_value('Slices.Elapse', 'true')
        t.check('scenario 2: a second key for that section appends under the '
                'header just created, rather than creating it again',
                s2b_what2 == 'appended' and s2b.to_bytes().count(b'[Slices]') == 1,
                (s2b_what2, s2b.to_bytes().count(b'[Slices]')))
        t.check('scenario 2: and the whole result re-reads as the two keys it '
                'was given — the write survives a round trip',
                CfgFile(s2b.to_bytes()).all_keys().get('Slices.RuleModel') == 'false'
                and CfgFile(s2b.to_bytes()).all_keys().get('Slices.Elapse') == 'true',
                CfgFile(s2b.to_bytes()).all_keys())

        # SCENARIO 3: "A value that would not survive a round trip is refused"
        #   THEN the save is refused with SaveRefused naming the key
        #   AND no file on disk is modified
        #
        # Both refusals are checked on BOTH paths. The record says these two
        # existed because the APPEND path needed them; the scenario says "a
        # value would be written", which covers replacement too, so both are
        # driven through a key that exists and a key that does not.
        for s3_key, s3_how in ((MASTER_KEY, 'replacing an existing key'),
                               ('Slices.RuleModel', 'appending a new key')):
            for s3_val, s3_why in (('#off', 'a value that would read back as a comment'),
                                   ('  #off', 'a value whose first non-blank character is #'),
                                   ('a\nb', 'a value carrying a line feed'),
                                   ('a\r\nb', 'a value carrying a CRLF'),
                                   ('a\rb', 'a value carrying a bare CR')):
                s3 = CfgFile(s8_nosec)
                try:
                    s3.set_value(s3_key, s3_val)
                    s3_out = 'NOT REFUSED'
                except SaveRefused as e:
                    s3_out = e.payload.get('summary', '')
                t.check('scenario 3: %s is refused when %s, and the refusal names the key'
                        % (s3_why, s3_how),
                        s3_out != 'NOT REFUSED' and s3_key in s3_out, s3_out)
                t.check('scenario 3: and nothing in the file moved — %s, %s'
                        % (s3_why, s3_how),
                        s3.to_bytes() == s8_nosec,
                        _first_line_diff(s8_nosec, s3.to_bytes()))

        # The refusals are refusals, not asserts: `python -O` strips asserts,
        # and a guard that vanished under -O would turn the frozen exe's own
        # optimisation setting into a silent bad write. Checked in a CHILD
        # interpreter actually started with -O, because an assert in THIS
        # process was compiled before any of this ran.
        #
        # REINSTATED with the guards, as tasks.md asks. The 3.0 version of
        # _refuses_under_O is not recoverable either -- same missing commit --
        # so this is a rewrite of it against the same stated property.
        s3o = _refuses_under_O()
        if s3o is None:
            t.skip('scenario 3: the two guards survive `python -O`',
                   'no interpreter to re-enter: sys.executable is %r and this build '
                   'is frozen, so -O cannot be passed. Re-run unfrozen to cover it.'
                   % sys.executable)
        else:
            t.check('scenario 3: the two guards are refusals, not asserts — '
                    'they still refuse under `python -O`', s3o is True, s3o)

        # SCENARIO 4: "A fixture derives the file's line endings, it does not
        #              assume them"
        #   THEN it reads the endings off the source file rather than searching
        #        for a sequence it expects to find
        #   AND it reports which endings the source actually had
        #
        # This is the scenario that section [8] above was failing on David's
        # machine: it asserted 'the fixture source really is CRLF' against a
        # file BepInEx had written with LF, and the rindex under it ended the
        # run with ValueError before any report line. What follows checks the
        # property the scenario states, rather than re-checking [8]'s fixture:
        # a line this writer ADDS takes its ending from the file, whatever the
        # file uses, and the census is printed rather than assumed.
        s4_crlf = s8_nosec.replace(b'\r\n', b'\n').replace(b'\n', b'\r\n')
        s4_lf = s8_nosec.replace(b'\r\n', b'\n')
        print('        source ckf.hardmode.cfg census: %d byte(s), %d CRLF, %d lone LF'
              % (len(s1_src), s1_src.count(b'\r\n'), _lone_lf(s1_src)))
        print('        derived no-[Slices] fixture:    %d byte(s), %d CRLF, %d lone LF'
              % (len(s8_nosec), s8_nosec.count(b'\r\n'), _lone_lf(s8_nosec)))
        for s4_raw, s4_name, s4_end in ((s4_lf, 'an all-LF file', b'\n'),
                                        (s4_crlf, 'an all-CRLF file', b'\r\n')):
            s4 = CfgFile(s4_raw)
            s4.set_value('Slices.RuleModel', 'false')
            s4_out = s4.to_bytes()
            t.check('scenario 4: a created section and key take the file\'s own '
                    'endings — %s' % s4_name,
                    s4_out.endswith(b'RuleModel = false' + s4_end), s4_out[-40:])
            t.check('scenario 4: and %s gains no ending of the other kind' % s4_name,
                    (_lone_lf(s4_out) == 0) if s4_end == b'\r\n'
                    else (s4_out.count(b'\r\n') == 0),
                    (s4_out.count(b'\r\n'), _lone_lf(s4_out)))
            t.check('scenario 4: and every line it already had is unchanged — %s' % s4_name,
                    _is_pure_insertion(s4_raw, s4_out), _first_line_diff(s4_raw, s4_out))

        # A mixed file: the added line takes the ending of the region it joins,
        # which is what _default_end searching UPWARD from the insertion point
        # buys. A whole-file sniff would give it the other one here.
        s4_mixed = b'[Alpha]\r\nOne = 1\r\n\r\n[Beta]\nTwo = 2\n'
        s4m = CfgFile(s4_mixed)
        s4m.set_value('Beta.Three', '3')
        t.check('scenario 4: in a mixed-ending file the appended line takes the '
                'ending of the section it joins, not the file\'s predominant one',
                s4m.to_bytes() == s4_mixed + b'Three = 3\n', s4m.to_bytes())
        s4m2 = CfgFile(s4_mixed)
        s4m2.set_value('Alpha.Four', '4')
        t.check('scenario 4: and a line appended into the other section takes '
                'that section\'s ending instead',
                s4m2.to_bytes()
                == b'[Alpha]\r\nOne = 1\r\nFour = 4\r\n\r\n[Beta]\nTwo = 2\n',
                s4m2.to_bytes())
        t.check('scenario 4: and neither append disturbed a line that was there',
                _is_pure_insertion(s4_mixed, s4m.to_bytes())
                and _is_pure_insertion(s4_mixed, s4m2.to_bytes()),
                (_first_line_diff(s4_mixed, s4m.to_bytes()),
                 _first_line_diff(s4_mixed, s4m2.to_bytes())))

        # A file with no trailing newline. The line above the insertion point
        # has to be terminated or the two run together on one line, which is a
        # wrong write that reads back as a lost key rather than as an error.
        s4_nt = b'[General]\nEnabled = true'
        s4n = CfgFile(s4_nt)
        s4n.set_value('General.Other', 'false')
        t.check('scenario 4: appending after an unterminated last line '
                'terminates it instead of running the two together',
                s4n.to_bytes() == b'[General]\nEnabled = true\nOther = false\n',
                s4n.to_bytes())
        t.check('scenario 4: and both keys are still readable afterwards',
                CfgFile(s4n.to_bytes()).all_keys()
                == {'General.Enabled': 'true', 'General.Other': 'false'},
                CfgFile(s4n.to_bytes()).all_keys())

        # ---- 9. two requests at once cannot empty the validator
        #
        # api_model takes no lock and ThreadingHTTPServer runs handlers in
        # parallel, so a second browser tab, a reload, or Apply directory
        # during a save used to redirect check_schema's stdout out of the
        # save's own buffer. The save then saw no RANGE line and wrote a value
        # its validator had rejected. The reproduction is the test.
        print('\n[9] a concurrent request cannot empty the validator')
        cdc = _sandbox(src, os.path.join(td, 'concurrent'))
        appc = App({'gameDir': '', 'configDirOverride': cdc, 'stripReadme': False}, 'x')
        mc = appc.api_model()
        rowsc = json.loads(json.dumps(mc['values']['tables'][tk]['rows']))
        rowsc[0]['cells']['PowerLevelFraction'] = 99.0        # declared range [0, 5]
        ec = {'json': {U_TEAMPL:
                       {'scalars': {}, 'tables': {'override': {'shape': 'array', 'rows': rowsc}}}}}
        teampl_c = os.path.join(cdc, F_TEAMPL)
        mirror_c = os.path.join(cdc, 'ckf.hardmode.d', 'MissionPowerLevelModel.generated.json')
        before_c = (read_bytes(teampl_c), read_bytes(mirror_c))

        stop = threading.Event()
        reader_errors = []

        def _reader():
            while not stop.is_set():
                try:
                    appc.api_model()
                except Exception:
                    reader_errors.append(traceback.format_exc())
                    return

        readers = [threading.Thread(target=_reader, daemon=True) for _ in range(4)]
        for th_ in readers:
            th_.start()
        attempts, accepted, named_range = 20, [], 0
        try:
            for _ in range(attempts):
                r = appc.api_save(ec)
                if r['ok']:
                    accepted.append(r.get('written'))
                elif any(p['kind'] == 'RANGE' for p in (r.get('blocking') or [])):
                    named_range += 1
        finally:
            stop.set()
            for th_ in readers:
                th_.join(timeout=30)
        t.check('an out-of-range save is refused every time, with four readers running',
                not accepted, '%d of %d saves were ACCEPTED: %s'
                % (len(accepted), attempts, accepted[:2]))
        t.check('every one of the %d refusals named RANGE — the validator was never '
                'silently empty' % attempts, named_range == attempts,
                '%d of %d named RANGE' % (named_range, attempts))
        t.check('nothing was written to teampl.json by any refused save',
                read_bytes(teampl_c) == before_c[0])
        t.check('nothing was written to the mirror either',
                read_bytes(mirror_c) == before_c[1])
        t.check('the concurrent readers all ran without raising',
                not reader_errors, (reader_errors or [''])[0])
        t.check('and the readers saw a complete validator result every time',
                appc.api_model()['check']['ran'])

        # journal recovery
        print('\n[10] crash between the two renames')
        cd2 = _sandbox(src, os.path.join(td, 'crash'))
        final = os.path.join(cd2, F_TEAMPL)
        tmp = final + TMP_SUFFIX + '-999'
        shutil.copy2(final, tmp)
        with open(tmp, 'ab') as f:
            f.write(b'')
        with open(journal_path(cd2), 'w') as f:
            json.dump({'pid': 999, 'time': 0, 'renames': [[tmp, final]]}, f)
        rec = recover_journal(cd2)
        t.check('an interrupted save is completed from its journal on the next start',
                rec['found'] and rec['completed'] == [final], rec)
        t.check('the journal is removed once it is finished',
                not os.path.exists(journal_path(cd2)))
        t.check('a journal naming a path outside its own directory is not followed',
                _journal_escape_refused(td))

        # a save written against a stale read is refused
        cds = _sandbox(src, os.path.join(td, 'stale'))
        apps = App({'gameDir': '', 'configDirOverride': cds, 'stripReadme': False}, 'x')
        ms = apps.api_model()
        rs = json.loads(json.dumps(ms['values']['tables'][tk]['rows']))
        rs[0]['cells']['PowerLevelFraction'] = 0.11
        es = {'json': {U_TEAMPL:
                       {'scalars': {}, 'tables': {'override': {'shape': 'array', 'rows': rs}}}}}
        okstale = apps.api_save(es, expect=ms['fingerprints'])
        t.check('a save against a current read is accepted', okstale['ok'], okstale.get('refused'))
        stale = apps.api_save(es, expect=ms['fingerprints'])   # fingerprints are now old
        t.check('a save against a stale read is refused', not stale['ok'], stale)
        t.check('the refusal names the file that moved',
                F_TEAMPL in (stale.get('stale') or []), stale.get('stale'))

        # a write that fails partway leaves a journal the next start finishes
        cd3 = _sandbox(src, os.path.join(td, 'midrename'))
        app3 = App({'gameDir': '', 'configDirOverride': cd3, 'stripReadme': False}, 'x')
        m3 = app3.api_model()
        rows3 = json.loads(json.dumps(m3['values']['tables'][tk]['rows']))
        rows3[0]['cells']['PowerLevelFraction'] = 0.42
        e3 = {'json': {U_TEAMPL:
                       {'scalars': {}, 'tables': {'override': {'shape': 'array', 'rows': rows3}}}}}
        real_replace, calls = os.replace, {'n': 0}

        def flaky(a, b):
            calls['n'] += 1
            if calls['n'] == 3:          # journal commit, mirror, then fail on teampl
                raise PermissionError(13, 'Permission denied', b)
            return real_replace(a, b)
        os.replace = flaky
        try:
            bad3 = app3.api_save(e3)
        finally:
            os.replace = real_replace
        t.check('a write that fails partway is reported as refused, not as a success',
                not bad3['ok'], bad3)
        t.check('the refusal says plainly that the directory refused the write',
                'refused the write' in (bad3.get('refused') or {}).get('summary', ''),
                bad3.get('refused'))
        t.check('a journal is left behind naming the unfinished rename',
                os.path.exists(journal_path(cd3)))
        rec3 = recover_journal(cd3)
        t.check('the next start finishes it', rec3['found'] and rec3['completed'], rec3)
        t.check('and the two halves agree once it has',
                abs(_teampl_first_fraction(cd3) - 0.42) < 1e-12, _teampl_first_fraction(cd3))
        t.check('check_schema agrees after the recovery',
                set((q['kind'], q['message']) for q in run_check_schema(cd3)['problems'])
                == base_set)

        # the server actually serves
        print('\n[11] the server')
        import urllib.request
        import urllib.error
        # Its own App, with the token the requests below send. It used to be a
        # handle left over from the cfg-append case in section 7, which went
        # with that case.
        appsrv = App({'gameDir': '', 'configDirOverride': cd, 'stripReadme': False}, 'x')
        httpd = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        port = httpd.server_address[1]
        Handler.app = appsrv
        Handler.expected_host = {'127.0.0.1:%d' % port, 'localhost:%d' % port}
        th = threading.Thread(target=httpd.serve_forever, daemon=True)
        th.start()
        base = 'http://127.0.0.1:%d' % port
        try:
            html = urllib.request.urlopen(base + '/').read().decode('utf-8')
            t.check('GET / serves app.html', '<html' in html.lower() or '<!doctype' in html.lower())
            t.check('the token is substituted into the page', '__CKF_TOKEN__' not in html)
            req = urllib.request.Request(base + '/api/model', headers={'X-CKF-Token': 'x'})
            j = json.loads(urllib.request.urlopen(req).read().decode('utf-8'))
            t.check('GET /api/model with the token returns the model',
                    j['fieldCount'] == sum(len(sc['fields']) for sc in appsrv.schemas),
                    j.get('fieldCount'))
            t.check('an api GET without the token is refused',
                    _status(base + '/api/model') == 403)
            t.check('a POST without the token is refused',
                    _status(base + '/api/save', b'{}') == 403)
            t.check('a POST from another origin is refused',
                    _status(base + '/api/save', b'{}',
                            {'X-CKF-Token': 'x', 'Origin': 'http://evil.example'}) == 403)
            t.check('a request with a foreign Host header is refused',
                    _status(base + '/', None, {'Host': 'evil.example'}) == 421)
            for p in ('/../serve.py', '/settings.json', '/etc/passwd', '/serve.py',
                      '/api/../serve.py'):
                t.check('no route serves %s' % p, _status(base + p) == 404, p)
        finally:
            httpd.shutdown()
            httpd.server_close()

    # ---- 12. presentation: order, grouping, and the prose above the controls
    #
    # All of these are display decisions, and the point of every check here is
    # that the display is the ONLY thing they change: two subsystems shown
    # together still write two separate sections with two separate gates, and a
    # windowed axis still saves every row the file holds. Section 13 is where
    # that last claim is tested against real bytes.
    print('\n[12] presentation: order, grouping, prose')
    secs = sections_for(schemas)
    by_sub = dict((s['subsystem'], s) for s in schemas)
    t.check('every subsystem lands in exactly one section',
            sorted(m for sec in secs for m in sec['subsystems']) == sorted(by_sub),
            [sec['subsystems'] for sec in secs])
    t.check('the master switch is the first section on the page',
            (by_sub[secs[0]['subsystems'][0]].get('enable') or {}).get('cfg') == MASTER_KEY,
            secs[0])
    t.check('the regression suite is the last',
            [m for m in secs[-1]['subsystems'] if m in SECTION_LAST] == SECTION_LAST,
            secs[-1])
    # THE MERGE. A section holding more than one subsystem used to be unique --
    # "the two halves of what a mission pays" -- and this check found it by
    # being the only one. It is not unique any more: SECTION_GROUPS declares
    # Weapons, Consumables and Cyberware as merges too. So the merge under test
    # is named by its declared id rather than found by counting.
    merges = [sec for sec in secs if len(sec['subsystems']) > 1]
    t.check('every merged section the page draws was declared as a merge, and '
            'nothing merged itself',
            all(sec['id'] in [child_id(c) for _g, c in declared_children()]
                for sec in merges),
            [(sec['id'], sec['subsystems']) for sec in merges])
    declared_merges = [c for _g, c in declared_children() if not isinstance(c, str)]
    t.check('%d merge(s) are declared and %d are drawn — a merge whose members '
            'are all absent draws nothing, which is not the same as one that '
            'went missing' % (len(declared_merges), len(merges)),
            len(merges) <= len(declared_merges),
            ([c['id'] for c in declared_merges], [sec['id'] for sec in merges]))
    paysec = [sec for sec in secs if sec['id'] == 'mission-pay']
    t.check('the two halves of what a mission pays are still one section',
            len(paysec) == 1
            and paysec[0]['subsystems'] == ['Progression', 'RewardCurve'],
            paysec)
    gsch = [by_sub[m] for m in paysec[0]['subsystems']] if paysec else []
    # WAS: `.get('enable').get('json')` on both halves. Both gates are cfg keys
    # since this change, so that comparison was None against None -- it read as
    # "two separate gates" while measuring nothing. The gate is compared
    # whatever its spelling now.
    gate_of = lambda s: (('cfg', (s.get('enable') or {}).get('cfg'))
                         if (s.get('enable') or {}).get('cfg')
                         else ('json', (s.get('enable') or {}).get('json')))
    t.check('and they still write two separate units and carry two separate '
            'enable gates — nothing merged but the presentation',
            len(set(sidecar_unit(s) for s in gsch)) == 2
            and len(set(gate_of(s) for s in gsch)) == 2
            and all(gate_of(s)[1] for s in gsch),
            [(sidecar_unit(s), gate_of(s)) for s in gsch])
    # READONLY TABLES COME IN TWO KINDS SINCE PHASE 4, and the difference is
    # how they are drawn, so they are separated here rather than counted
    # together. An UNDERLAY is declared by a control as its `over`, and is
    # drawn on that control's axes. A REFERENCE FIELD carries its own rows in
    # the schema, belongs to no file, and is drawn beside the overlay whose key
    # column it shares. Until this change every readonly table was the first
    # kind and these cases asserted that of all of them; with rulemodel's
    # ruleReference on disk that assertion failed on a field that is correct.
    ro = [(s['subsystem'], f['path']) for s in schemas for f in s['fields']
          if f.get('ui') == 'readonly']
    ro_ref = [(s['subsystem'], f['path']) for s in schemas for f in s['fields']
              if f.get('ui') == 'readonly' and f['in'] == 'reference']
    ro_under = [x for x in ro if x not in ro_ref]
    print('        readonly tables: %d underlay(s) %s, %d reference field(s) %s'
          % (len(ro_under), ro_under, len(ro_ref), ro_ref))
    t.check('there is at least one of each kind, so neither branch below is a '
            'loop over nothing', ro_under and ro_ref, (ro_under, ro_ref))
    t.check('every underlay sits in the section its owner does — the '
            'mission-pay merge is the one that has them',
            all(sub in paysec[0]['subsystems'] for sub, _p in ro_under),
            ro_under)
    # an underlay is drawn on the axes of the field that declares it as its
    # underlay -- which is what app.html derives, so the schema has to carry it
    for sub, path in ro_under:
        owners = [g for g in by_sub[sub]['fields'] if g.get('over') == path and g.get('axes')]
        t.check('%s.%s has an owner field whose axes it can be drawn on'
                % (sub, path), len(owners) == 1, owners)
    # a reference field has no owner and needs none; what it needs is rows in
    # the schema and a key column some overlay of the same schema selects on.
    for sub, path in ro_ref:
        fref = [g for g in by_sub[sub]['fields'] if g['path'] == path][0]
        cols = [c['name'] for c in fref.get('row') or []]
        t.check('%s.%s carries its rows in the schema, so nothing at runtime '
                'depends on a dump being present'
                % (sub, path), len(fref.get('rows') or []) > 0,
                len(fref.get('rows') or []))
        # Read from `src`, the source config this suite copies from: section
        # 12 has no sandbox of its own, and reading a path that is not there
        # comes back keyColumn None, which would make this case pass or fail on
        # where it looked rather than on what the schemas say.
        keys = [read_overlay(os.path.join(src, rel), rel)['keyColumn']
                for rel in overlay_paths(by_sub[sub])]
        t.check('%s.%s shares a column with an overlay its own schema '
                'declares, which is the join the page draws it on'
                % (sub, path), any(k in cols for k in keys), (cols, keys))
        g = REFERENCE_GROUPING.get((sub, path))
        t.check('%s.%s groups by a column it actually declares — a grouping '
                'naming a column that is not there would silently draw one '
                'group of everything' % (sub, path),
                g is None or g in cols, (g, cols))

    # 3.0: no subsystem is gated twice any more, so nothing collapses. The
    # check is not deleted, it is inverted -- a schema that grows a second gate
    # would go back to needing a collapsed control, and this is what says so.
    twice_gated = sorted(s['subsystem'] for s in schemas
                         if (s.get('enable') or {}).get('cfg')
                         and (s.get('enable') or {}).get('json'))
    t.check('no subsystem declares two enable gates: the outer cfg gate is gone',
            twice_gated == [], twice_gated)
    # WAS, until 2026-09-13: "exactly one subsystem is gated by a cfg key, and
    # it is the master", asserting `len(gated_by_cfg) == 1`. That was a
    # consolidate-config-and-ship statement -- 21 of 22 keys had moved into the
    # merged document and [General] Enabled was the only cfg key left.
    # split-config-into-toggleable-slices reverses it: every slice toggle is a
    # cfg key again. What is asserted now is the property that outlives the
    # count -- exactly one cfg gate is the master, and every other one is not.
    gated_by_cfg = sorted(s['subsystem'] for s in schemas
                          if (s.get('enable') or {}).get('cfg'))
    masters = [s for s in schemas
               if (s.get('enable') or {}).get('cfg') == MASTER_KEY]
    t.check('exactly one subsystem is gated by the master key, and %d others '
            'are gated by a cfg key of their own' % (len(gated_by_cfg) - 1),
            len(masters) == 1 and len(gated_by_cfg) >= 1,
            gated_by_cfg)

    # THE NAV GROUPING. One level, no nesting; every section in exactly one
    # group or explicitly ungrouped; the master switch is the ungrouped one.
    ng = nav_groups_for(schemas, secs)
    placed = [i for g in ng['groups'] for i in g['sections']]
    t.check('no section is placed in two groups', len(placed) == len(set(placed)),
            sorted(i for i in set(placed) if placed.count(i) > 1))
    t.check('every section is in one group or named as ungrouped',
            sorted(placed + ng['ungrouped']) == sorted(s['id'] for s in secs),
            (sorted(placed + ng['ungrouped']), sorted(s['id'] for s in secs)))
    t.check('the only ungrouped section is the master switch — every other '
            'section a group forgot would land here and be drawn last, '
            'unexplained',
            [i for i in ng['ungrouped']
             if not any((by_sub[m].get('enable') or {}).get('cfg') == MASTER_KEY
                        for m in next(s for s in secs if s['id'] == i)['subsystems'])] == [],
            ng['ungrouped'])
    t.check('a group with no sections carries a note or names what is absent — '
            'a bare empty header is what this forbids',
            all(g['note'] or g['absent'] for g in ng['groups'] if not g['sections']),
            [g['id'] for g in ng['groups'] if not g['sections']
             and not (g['note'] or g['absent'])])
    empty_groups = [g['id'] for g in ng['groups'] if not g['sections']]
    print('        groups drawing no section today (%d): %s'
          % (len(empty_groups), ', '.join(empty_groups) or 'none'))
    t.check('every declared group id is unique',
            len(set(g['id'] for g in SECTION_GROUPS)) == len(SECTION_GROUPS),
            [g['id'] for g in SECTION_GROUPS])
    # SECTION_GROUPS names subsystems by hand; a name that matches no schema is
    # a typo, and a schema no group names is a page that would be drawn with no
    # heading over it. Both are reported by name rather than tolerated.
    declared_subs = [m for _g, c in declared_children()
                     for m in ([c] if isinstance(c, str) else c['subsystems'])]
    t.check('no group names a subsystem twice', len(declared_subs) == len(set(declared_subs)),
            sorted(m for m in set(declared_subs) if declared_subs.count(m) > 1))
    absent_children = sorted(set(
        child_id(c) for _g, c in declared_children()
        if resolve_child(c, by_sub) is None))
    print('        declared sections naming no schema yet (%d): %s'
          % (len(absent_children), ', '.join(absent_children) or 'none'))
    unnamed = sorted(set(by_sub) - set(declared_subs)
                     - set(s['subsystem'] for s in schemas
                           if (s.get('enable') or {}).get('cfg') == MASTER_KEY))
    t.check('every schema except the master switch is named by a group',
            unnamed == [], unnamed)

    t.check('a windowed axis is declared for one matrix only',
            list(AXIS_WINDOWS) == [('Progression', 'MissionPowerLevel')], list(AXIS_WINDOWS))
    t.check('the window names an axis the schema actually declares',
            all(col in [(f.get('axes') or {}).get('col') for f in by_sub[sub]['fields']]
                + [(f.get('axes') or {}).get('row') for f in by_sub[sub]['fields']]
                for (sub, col) in AXIS_WINDOWS), list(AXIS_WINDOWS))

    t.check('a blank line is a paragraph break and consecutive lines are one paragraph',
            paragraphs(['one', 'two', '', 'three']) == ['one two', 'three'],
            paragraphs(['one', 'two', '', 'three']))
    t.check('runs of blank lines do not make empty paragraphs',
            paragraphs(['a', '', '', 'b']) == ['a', 'b'])
    t.check('field help is one paragraph whatever the source did',
            field_doc_text('one\n  two\tthree') == 'one two three')
    t.check('a field with a uiDoc shows it instead of its doc',
            field_help({'uiDoc': 'player text', 'doc': 'maintainer text'}) == 'player text')
    t.check('a field without one still shows its stripped doc',
            field_help({'doc': 'maintainer text (Elapse.cs:1)'}) == 'maintainer text')
    t.check('uiDoc is rendered when the schema has one',
            section_prose({'uiDoc': ['player text'], 'doc': ['maintainer text']})
            == (['player text'], 'uiDoc'))
    t.check('doc is the fallback when it does not — the page works either way',
            section_prose({'doc': ['maintainer text']}) == (['maintainer text'], 'doc'))
    t.check('every schema renders prose today', all(section_prose(s)[0] for s in schemas),
            [s['subsystem'] for s in schemas if not section_prose(s)[0]])
    t.check('every schema carries a uiDoc of its own — no player reads the '
            'maintainer text as a fallback',
            all(section_prose(s)[1] == 'uiDoc' for s in schemas),
            [s['subsystem'] for s in schemas if section_prose(s)[1] != 'uiDoc'])
    # SCHEMA-FORMAT.md: a uiDoc carries no citation and no evidence tag. The
    # strip is the safety net for `doc`; for `uiDoc` there should be nothing to
    # strip in the first place.
    dirty = []
    for sc in schemas:
        blocks = [(sc['subsystem'], ' '.join(sc.get('uiDoc') or []))]
        blocks += [('%s.%s' % (sc['subsystem'], f['path']), f['uiDoc'])
                   for f in sc['fields'] if f.get('uiDoc')]
        for where, text in blocks:
            if strip_maintainer_marks(' '.join(text.split())) != ' '.join(text.split()):
                dirty.append(where)
    t.check('no uiDoc carries a citation or an evidence tag', not dirty, dirty)
    small = {'a', 'an', 'the', 'of', 'and', 'or', 'to', 'by', 'for', 'in', 'on'}
    lower = [s['title'] for s in schemas
             for i, w in enumerate(s['title'].split())
             if w[:1].islower() and (i == 0 or w.lower() not in small)]
    t.check('every section title is Title Case', not lower, sorted(set(lower)))
    # Both levels: the group headers and the titles of the merges under them.
    # Before this change SECTION_GROUPS held only merges, so one loop covered
    # everything it had.
    nav_titles = ([g['title'] for g in SECTION_GROUPS]
                  + [c['title'] for _g, c in declared_children()
                     if not isinstance(c, str)])
    grp = [ttl for ttl in nav_titles
           for i, w in enumerate(ttl.split())
           if w[:1].islower() and (i == 0 or w.lower() not in small)]
    t.check('so is every group and merged-section title', not grp, sorted(set(grp)))

    t.check('a parenthetical source citation is stripped',
            strip_maintainer_marks('Off, and the tier affects credits only '
                                   '(Elapse.cs:833-835).')
            == 'Off, and the tier affects credits only.',
            strip_maintainer_marks('Off, and the tier affects credits only (Elapse.cs:833-835).'))
    t.check('a citation carrying extra line ranges is stripped whole',
            strip_maintainer_marks('x (Fatigue.cs:152, 161, 1423-1426). y') == 'x. y')
    t.check('an evidence tag is stripped',
            strip_maintainer_marks('a claim [measured] and more') == 'a claim and more')
    t.check('a long [unverified: ...] tag is stripped whole',
            strip_maintainer_marks('kept. [unverified: a long note about a dump.]') == 'kept.')
    t.check('a bracket that is not an evidence tag is left alone',
            strip_maintainer_marks('the one [PowerLevel] lifts, '
                                   '[JsonPropertyName("missions")], [Diagnostics]')
            == 'the one [PowerLevel] lifts, [JsonPropertyName("missions")], [Diagnostics]')
    t.check('a parenthetical that is not only a citation is left alone — the '
            'conservative direction',
            strip_maintainer_marks('keep (RewardCurve.cs:249-251, and the C# initialiser '
                                   'is -1) here')
            == 'keep (RewardCurve.cs:249-251, and the C# initialiser is -1) here')
    t.check('a citation that is the subject of its sentence survives',
            strip_maintainer_marks('Fatigue.cs:93-96 carries none of the three.')
            == 'Fatigue.cs:93-96 carries none of the three.')
    t.check('a space before a file extension is not eaten',
            strip_maintainer_marks('none appears in any .cs in this tree')
            == 'none appears in any .cs in this tree')

    # every field doc, checked one at a time. A regex that eats a sentence is
    # worse than one that leaves a citation behind, so the assertions below are
    # about what SURVIVED, not about how much came out.
    all_docs = [(s['subsystem'], f['path'], f['doc'])
                for s in schemas for f in s['fields'] if f.get('doc')]
    # 58 before Phase 3. The two cfg gates it deleted -- [Elapse] Enabled and
    # [Fatigue] Enabled -- took their `doc` with them; the prose was folded into
    # the section's own "enabled" field, which already had one.
    # 48 since 2026-09-07, which removed the eight flat fatigue fields --
    # runningEmpty chancePercent, durationDays, minAffected and maxAffected,
    # the two knight ones under it, offDuty.durationDays and
    # offDuty.knight.durationDays -- each of which carried a doc.
    # 82 since 2026-09-13: split-config-into-toggleable-slices declared the
    # slice set in the schemas, which added 34 slice-stub schemas carrying one
    # documented cfg field each, and deleted the eight subsystem `enabled` json
    # fields whose docs moved to the cfg gates that replaced them. 48 + 34 = 82.
    # 86 since 2026-09-13, later the same day: implantsglobal.schema.json stopped
    # being a slice stub. Phase 3 gave it a file of its own,
    # ckf.hardmode.d/implants-global.json, and it now declares the four json
    # fields that file carries -- costMultiply, installTimeMultiply,
    # implantStressMultiply and implantStressClampMin -- each with a doc, on top
    # of the cfg gate it already had. 82 + 4 = 86.
    # 85 since 2026-09-13, later again: David had implantStressClampMin deleted
    # as useless, and the measurement is that the clamp never binds --
    # ImplantStress is 1 on 197 of the 198 rows and 5 on Quantum Rider, so
    # after the x3 nothing lands below the floor of 1 for it to lift. The field
    # went with it. 86 - 1 = 85, across 43 schemas: 43 cfg fields and 42 json.
    # 86 since Phase 4: rulemodel.schema.json gained `ruleReference`, a
    # documented field of a third kind -- `"in": "reference"`, rows in the
    # schema, on no file and in no edit set. 85 + 1 = 86, across 43 schemas:
    # 43 cfg, 42 json and 1 reference.
    t.check('there are %d field docs to check' % len(all_docs), len(all_docs) == 86, len(all_docs))
    emptied, unbalanced, mangled, changed = [], [], [], []
    for sub, path, doc in all_docs:
        flat = ' '.join(doc.split())
        out = field_doc_text(doc)
        if not out:
            emptied.append('%s.%s' % (sub, path))
        if out.count('(') != out.count(')') or out.count('[') != out.count(']'):
            unbalanced.append('%s.%s' % (sub, path))
        # what came out must be what the two patterns took, and nothing else
        rebuilt = TRAILING_CITE_RE.sub('', CITATION_RE.sub('', EVIDENCE_TAG_RE.sub('', flat)))
        rebuilt = re.sub(r'\s+', ' ', rebuilt).strip()
        if rebuilt != out:
            mangled.append('%s.%s' % (sub, path))
        if out != flat:
            changed.append('%s.%s' % (sub, path))
    t.check('no field doc is emptied by the strip', not emptied, emptied)
    t.check('no field doc comes out with unbalanced brackets', not unbalanced, unbalanced)
    t.check('nothing is removed but the two declared patterns (%d of %d docs changed)'
            % (len(changed), len(all_docs)), not mangled, mangled)
    left = [(sub, path) for sub, path, doc in all_docs
            if re.search(r'[A-Za-z_][\w.]*\.(?:cs|json|md|py|csv)\s*:\s*\d',
                         field_doc_text(doc))]
    print('        citations deliberately left in place (mid-sentence, where the '
          'citation is the subject): %d' % len(left))
    for sub, path in left:
        print('          %s.%s' % (sub, path))

    # ---- 13. the data behind the display: nothing is dropped by hiding it
    print('\n[13] hidden, collapsed and cleared — what reaches the disk')
    with tempfile.TemporaryDirectory() as td:
        # (a) A NO-OP SAVE WRITES ZERO BYTES -- ACROSS EVERY FILE THE EDITOR
        #     OWNS, NOT JUST THE ONE IT USED TO BE.
        #
        # This is the check that caught the generated-mirror defect in
        # consolidate-config-and-ship Phase 2. Until Phase 3 the editor owned
        # one document and one mirror, so it had one real chance to catch
        # something; it now owns a file per slice and has one chance per file.
        # `written` is the editor's own account of what it did, so the bytes
        # are hashed independently either side of the save as well -- a writer
        # that reported [] while replacing a file would pass on the first half
        # alone.
        cdn = _sandbox(src, os.path.join(td, 'noop'))
        owned = files_check_schema_reads(schemas)
        present = [rel for rel in owned if os.path.exists(os.path.join(cdn, rel))]
        mirrors = sorted({inv['target'] for sch in schemas
                          for inv in sch.get('invariants', [])
                          if inv.get('kind') == 'mirror'})
        print('        files the editor owns: %d, of which %d are in the '
              'sandbox; generated mirrors: %s'
              % (len(owned), len(present), ', '.join(mirrors) or 'none'))
        # A no-op over one file, or over none, is not the case this is for.
        t.check('the no-op case has more than one file to be a no-op over — '
                'one document is what it used to prove and is no longer what '
                'is on disk', len(present) > 1, present)
        t.check('and every file the schemas point at is actually there, so '
                'none of them is a no-op by being absent',
                len(present) == len(owned),
                sorted(set(owned) - set(present)))

        def _hashes(root, rels):
            out = {}
            for rel in rels:
                p = os.path.join(root, rel)
                out[rel] = (hashlib.sha256(read_bytes(p)).hexdigest()
                            if os.path.exists(p) else None)
            return out

        appn = App({'gameDir': '', 'configDirOverride': cdn, 'stripReadme': False}, 'x')
        mn = appn.api_model()
        # 2026-09-14: `owned` now includes the 53 lever sheets, and the
        # no-op edit set reaches them too -- every lever cell sent back at the
        # value it already holds. Before the write path opened this compared
        # the sidecars and the .cfg only; a sheet was not in `owned` and no
        # edit set could name one.
        _noop = _edits_for(appn.schemas, mn)
        t.check('the no-op edit set covers every file the editor owns — an '
                'edit set that reached none of them would write zero bytes '
                'for the wrong reason',
                sorted(set(unit_file(u) for u in _noop['json'])
                       | set(_noop.get('overlays') or {})
                       | {'ckf.hardmode.cfg'})
                == sorted(set(owned) - set(mirrors)),
                (sorted(set(unit_file(u) for u in _noop['json'])
                        | set(_noop.get('overlays') or {})),
                 sorted(set(owned) - set(mirrors))))
        h0 = _hashes(cdn, owned)
        rn = appn.api_save(_edits_for(appn.schemas, mn))
        h1 = _hashes(cdn, owned)
        settled = sorted(rn.get('written') or [])
        moved1 = sorted(k for k in owned if h0[k] != h1[k])
        t.check('a no-op save reports the same set of files it actually '
                'changed on disk', settled == moved1, (settled, moved1))
        # THE ONLY THING A NO-OP SAVE MAY LEGALLY WRITE is a generated mirror
        # the directory handed over stale, and only its provenance header may
        # differ -- the rules it carries must be identical. A mirror whose
        # VALUES move on a no-op save is the defect this whole case exists for,
        # and that is still a failure.
        t.check('a no-op save writes nothing but, at most, a generated mirror '
                'the directory handed over stale',
                rn['ok'] and not (set(settled) - set(mirrors)),
                settled or rn.get('refused'))
        # The generator's provenance block names the file it read. That name
        # changed when teampl moved out of the merged document, so a mirror
        # generated before the migration differs from one generated after it by
        # those lines and nothing else. Dropping them is what lets the RULES be
        # compared; dropping them silently would let a rule change hide behind
        # a header change, so the keys dropped are named and what is left is
        # asserted to be non-empty.
        PROVENANCE = ('_comment', '_readme')
        stale_mirrors = []
        for rel in settled:
            a = json.loads(read_bytes(os.path.join(src, rel)).decode('utf-8-sig'))
            b = json.loads(read_bytes(os.path.join(cdn, rel)).decode('utf-8-sig'))
            dropped = sorted(k for k in PROVENANCE if k in a or k in b)
            for k in PROVENANCE:
                a.pop(k, None)
                b.pop(k, None)
            stale_mirrors.append(rel)
            t.check('%s: what is left after dropping %s is not an empty '
                    'document — a comparison of two empty objects passes '
                    'without comparing anything'
                    % (rel, ', '.join(dropped) or 'nothing'), a and b,
                    (len(a), len(b)))
            t.check('%s: the no-op rewrite changed only its own provenance '
                    'header — every rule it carries is unchanged' % rel,
                    _semantic_diff(a, b) == [], _semantic_diff(a, b)[:6])
        print('        generated mirror(s) the source directory handed over '
              'stale (%d): %s' % (len(stale_mirrors),
                                  ', '.join(stale_mirrors) or 'none — nothing '
                                  'needed settling'))
        # AND THEN, FROM A SETTLED DIRECTORY, ZERO BYTES. This is the assertion
        # the checkbox asks for, and it is made over every owned file at once.
        appn2 = App({'gameDir': '', 'configDirOverride': cdn,
                     'stripReadme': False}, 'x')
        mn2 = appn2.api_model()
        h2 = _hashes(cdn, owned)
        rn2 = appn2.api_save(_edits_for(appn2.schemas, mn2))
        h3 = _hashes(cdn, owned)
        t.check('a no-op save of a settled config writes zero bytes, across '
                'all %d files the editor owns' % len(owned),
                rn2['ok'] and rn2['written'] == []
                and all(h2[k] == h3[k] for k in owned),
                (rn2.get('written') or rn2.get('refused'),
                 [k for k in owned if h2[k] != h3[k]]))
        t.check('and it reports every one of them as skipped rather than '
                'reporting nothing at all — a save that proposed no file '
                'would also write zero bytes',
                sorted(rn2.get('skipped') or []) == sorted(owned),
                (sorted(rn2.get('skipped') or []), sorted(owned)))
        t.check('and left no journal behind',
                not os.path.exists(journal_path(cdn)), journal_path(cdn))
        # A FLOAT WRITTEN WITH A TRAILING .0 IS THE ONE THAT GOES WRONG. Python
        # renders 3.0 as 3.0 and 3 as 3, so a value that round-trips through
        # float() and back is safe -- but a value that is re-parsed and
        # re-emitted by anything less careful comes back as 3, and every
        # semantic comparison in this file would call that identical. Zero
        # bytes across every file is what actually rules it out, so the tokens
        # that would show it are counted and named rather than assumed to be
        # there.
        _dotzero = {}
        for rel in owned:
            hits = re.findall(rb'-?\d+\.0(?=[,\s\]}])',
                              read_bytes(os.path.join(cdn, rel)))
            if hits:
                _dotzero[rel] = len(hits)
        print('        trailing-.0 float tokens the zero-byte result protects: '
              '%s' % (', '.join('%s x%d' % (k, v)
                                for k, v in sorted(_dotzero.items())) or 'none'))
        t.check('at least one file carries a float written with a trailing .0, '
                'so "zero bytes" is protecting a token that a careless '
                're-serialise would visibly change', _dotzero, sorted(owned))

        # (a2) THE JOURNAL COVERS ONLY THE FILES A SAVE TOUCHED.
        #
        # Usually one or two. One scalar is moved in one slice file; every
        # other file the editor owns must be byte-identical afterwards, and the
        # journal -- captured mid-transaction, because a completed save removes
        # it -- must name that file and nothing else.
        cdj = _sandbox(src, os.path.join(td, 'journal-one'))
        # Settled first, for the same reason as above: a directory whose
        # generated mirror is stale writes that mirror on ANY save, and this
        # case is about which files a save touches, not about that.
        app_settle = App({'gameDir': '', 'configDirOverride': cdj,
                          'stripReadme': False}, 'x')
        m_settle = app_settle.api_model()
        r_settle = app_settle.api_save(_edits_for(app_settle.schemas, m_settle))
        t.check('the one-file fixture settles first, writing nothing but a '
                'stale mirror',
                r_settle['ok'] and not (set(r_settle['written']) - set(mirrors)),
                r_settle.get('written') or r_settle.get('refused'))
        appj = App({'gameDir': '', 'configDirOverride': cdj, 'stripReadme': False}, 'x')
        mj = appj.api_model()
        # A numeric scalar in a file that is NOT the mirror's source, so this
        # measures one file and not the pair.
        pick = None
        for (unit, path), (_s, fj) in sorted(json_fields(appj.schemas).items()):
            if fj['type'] not in ('int', 'float'):
                continue
            if unit_file(unit) in set(inv['source'].split('#')[0]
                                      for sch in schemas
                                      for inv in sch.get('invariants', [])
                                      if inv.get('kind') == 'mirror'):
                continue
            slot = mj['values']['json'].get(unit, {}).get(path)
            if slot and slot.get('present') and isinstance(slot.get('value'),
                                                           (int, float)):
                pick = (unit, path, slot['value'])
                break
        t.check('a numeric scalar was found in a file that is not a mirror '
                'source, to drive the one-file save', pick, pick)
        if pick:
            junit, jpath, jval = pick
            print('        one-file save drives %s in %s' % (jpath, junit))
            ej = _edits_for(appj.schemas, mj)
            ej['json'][junit]['scalars'][jpath] = {'present': True,
                                                   'value': jval + 1}
            hj0 = _hashes(cdj, owned)
            rj = appj.api_save(ej, expect=mj['fingerprints'])
            hj1 = _hashes(cdj, owned)
            t.check('a save that moves one value writes exactly one file',
                    rj['ok'] and rj['written'] == [unit_file(junit)],
                    rj.get('written') or rj.get('refused'))
            t.check('and every other file the editor owns is byte-identical',
                    [k for k in owned if hj0[k] != hj1[k]] == [unit_file(junit)],
                    [k for k in owned if hj0[k] != hj1[k]])
            t.check('and the journal is gone once the save completed',
                    not os.path.exists(journal_path(cdj)), journal_path(cdj))

            # What the journal NAMED, captured from inside the transaction.
            # A completed save removes it, so the only way to read it is to
            # take a copy at the moment it exists.
            seen = {}
            real_replace = os.replace

            def _spy(a, b):
                jp = journal_path(cdj)
                if not seen and os.path.exists(jp):
                    try:
                        seen.update(json.loads(read_bytes(jp).decode('utf-8')))
                    except ValueError:
                        pass
                return real_replace(a, b)

            appj2 = App({'gameDir': '', 'configDirOverride': cdj,
                         'stripReadme': False}, 'x')
            mj2 = appj2.api_model()
            ej2 = _edits_for(appj2.schemas, mj2)
            ej2['json'][junit]['scalars'][jpath] = {'present': True,
                                                    'value': jval + 2}
            os.replace = _spy
            try:
                rj2 = appj2.api_save(ej2, expect=mj2['fingerprints'])
            finally:
                os.replace = real_replace
            t.check('the second one-file save also succeeded, so the journal '
                    'below is a real one', rj2['ok'], rj2.get('refused'))
            named = sorted(os.path.relpath(f, cdj).replace(os.sep, '/')
                           for _t, f in (seen.get('renames') or []))
            t.check('the journal named the one file the save touched and no '
                    'other — it does not cover the files the save left alone',
                    named == [unit_file(junit)], (named, unit_file(junit)))

        # (b) THE ONE THAT MATTERS. An override in a column the matrix does not
        # draw survives a save untouched. None exists on disk, so one is built:
        # the window is [1, 10] and this sits at MissionPowerLevel 0, which the
        # game's own table prices at 0.04 for ActionClass 2.
        cdh = _sandbox(src, os.path.join(td, 'hidden'))
        apph = App({'gameDir': '', 'configDirOverride': cdh, 'stripReadme': False}, 'x')
        mh = apph.api_model()
        tkey = None
        for k, v in mh['values']['tables'].items():
            fld = json_fields(apph.schemas).get((v['sidecar'], v['path']))
            if fld and fld[1].get('ui') == 'matrix':
                tkey = k
                axes = fld[1]['axes']
                win = AXIS_WINDOWS[(fld[0]['subsystem'], axes['col'])]
        t.check('the windowed matrix is found from the schema, not by name', tkey is not None)
        rows_h = json.loads(json.dumps(mh['values']['tables'][tkey]['rows']))
        before_n = len(rows_h)
        outside = win[0] - 1                      # one step below the window
        rows_h.append({'id': None, 'cells': {axes['row']: 2, axes['col']: outside,
                                             axes['value']: 0.02}})
        eh = {'json': {mh['values']['tables'][tkey]['sidecar']:
                       {'scalars': {}, 'tables': {mh['values']['tables'][tkey]['path']:
                                                  {'shape': 'array', 'rows': rows_h}}}}}
        rh = apph.api_save(eh)
        t.check('an override in a hidden column saves', rh['ok'], rh.get('refused'))
        mh2 = apph.api_model()
        rows2 = mh2['values']['tables'][tkey]['rows']
        hit = [r for r in rows2 if r['cells'][axes['col']] == outside]
        t.check('the row outside the drawn window is on disk, with its value',
                len(rows2) == before_n + 1 and len(hit) == 1
                and abs(hit[0]['cells'][axes['value']] - 0.02) < 1e-12,
                (len(rows2), hit))
        mirror = check_schema.load_jsonc(os.path.join(
            cdh, 'ckf.hardmode.d', 'MissionPowerLevelModel.generated.json'))
        mrule = [r for r in mirror['rules'] if r['where'][axes['col']] == outside]
        t.check('the mirror is computed from the data, not from what is on screen: '
                'it carries a rule for the hidden cell too',
                len(mrule) == 1 and abs(mrule[0]['set'][axes['value']] - 0.02) < 1e-12, mrule)
        t.check('check_schema is still clean after it', rh['checkAfter']['ran']
                and not [p for p in rh['checkAfter']['problems'] if p['kind'] in BLOCKING],
                rh['checkAfter']['problems'])
        # and a second, untouched save does not quietly drop it again
        m3 = apph.api_model()
        r3 = apph.api_save(_edits_for(apph.schemas, m3))
        t.check('a later no-op save does not drop the hidden row',
                r3['ok'] and r3['written'] == [], r3.get('written'))

        # (c) every subsystem gate, whatever it is spelled in, and writing one
        #     off is what turns the subsystem off
        #
        # WAS, until 2026-09-13: "every subsystem gate is a path in the merged
        # document now", asserting `len(cfg_gated) == 1 and len(ungated) <= 1`
        # with the comment "Phase 3 deleted the outer cfg gate, so there is no
        # pair to collapse and no pair to disagree." That was a
        # consolidate-config-and-ship statement.
        # split-config-into-toggleable-slices reverses it: every slice toggle is
        # a cfg key again, so on 2026-09-13 the counts were 0 json-gated / 10
        # cfg-gated / 33 ungated [measured].
        #
        # THE LOOP UNDER IT WENT QUIET AND NOTHING SAID SO. `json_gated` fell to
        # zero, so the twenty per-subsystem assertions below stopped executing
        # and the run got twenty checks shorter with no FAIL, no NOT RUN and no
        # line naming what had stopped -- exactly the defect AGENTS.md section 3
        # is about, and the fourth of that shape found this phase. The loop now
        # runs over every gated schema whatever the spelling, and
        # `gates_to_exercise` fails loudly if that set is ever empty.
        json_gated = [sc for sc in apph.schemas
                      if (sc.get('enable') or {}).get('json') and sidecar_unit(sc)]
        cfg_gated = [sc for sc in apph.schemas if (sc.get('enable') or {}).get('cfg')]
        ungated = [sc for sc in apph.schemas if not (sc.get('enable') or {})]
        # The partition, stated rather than counted: it is exhaustive, it is
        # disjoint, and exactly one member of it is the master switch. The three
        # sizes are printed on every run so a change in them is visible without
        # being a failure.
        print('        gate spelling census: %d json, %d cfg, %d with no gate '
              'declared, of %d schemas'
              % (len(json_gated), len(cfg_gated), len(ungated), len(apph.schemas)))
        t.check('every schema is gated by a json path, by a cfg key, or by '
                'nothing — and by exactly one of the three',
                len(json_gated) + len(cfg_gated) + len(ungated) == len(apph.schemas),
                ([sc['subsystem'] for sc in json_gated],
                 [sc['subsystem'] for sc in cfg_gated],
                 [sc['subsystem'] for sc in ungated]))
        t.check('exactly one gate is the master switch',
                len([sc for sc in cfg_gated
                     if sc['enable']['cfg'] == MASTER_KEY]) == 1,
                [sc['subsystem'] for sc in cfg_gated])
        # A slice stub declares a Slices.* cfg field but no `enable` pointing at
        # it, so enable_index has no chain to compute and reports 'n/a' -- the
        # nav draws no toggle for it. That is a schema/ matter, outside this
        # file, so it is reported by name rather than fixed here or tolerated
        # in silence.
        unpointed = sorted(
            sc['subsystem'] for sc in ungated
            for f in sc['fields']
            if f['in'] == 'cfg'
            and not any((s2.get('enable') or {}).get('cfg') == f['path']
                        for s2 in apph.schemas))
        print('        cfg toggles no schema declares as its own enable gate '
              '(%d): %s' % (len(unpointed), ', '.join(unpointed) or 'none'))

        gates_to_exercise = json_gated + [sc for sc in cfg_gated
                                          if sc['enable']['cfg'] != MASTER_KEY]
        t.check('there are %d subsystem gates to exercise — a loop over an '
                'empty set is not a pass' % len(gates_to_exercise),
                len(gates_to_exercise) > 0,
                [sc['subsystem'] for sc in apph.schemas])
        req_refused, inv_refused, moved_alone = [], [], []
        for sch in gates_to_exercise:
            sub = sch['subsystem']
            cdp = _sandbox(src, os.path.join(td, 'gate-' + sub))
            appp = App({'gameDir': '', 'configDirOverride': cdp, 'stripReadme': False}, 'x')
            en = sch['enable']
            if en.get('json'):
                gate, unit = en['json'], sidecar_unit(sch)
                rp = appp.api_save({'json': {unit: {'scalars': {
                    gate: {'present': True, 'value': False}}, 'tables': {}}}})
            else:
                gate, unit = en['cfg'], None
                # Read before the save: what the save is expected to write
                # depends on whether the key already holds the value being
                # written. See the block under `if unit:` below.
                was_raw = CfgFile.load(
                    os.path.join(cdp, 'ckf.hardmode.cfg')).raw_value(gate)
                rp = appp.api_save({'cfg': {gate: {'value': False}}})
            # Two ways this can end, and each one is asserted rather than
            # skipped:
            #   - refused because a linkedEnable group will not move alone;
            #   - written, in which case the gate reads back off.
            #
            # A THIRD WAY WAS HERE AND IS NOW A FAILURE. Until
            # split-config-into-toggleable-slices a cfg gate whose key the file
            # did not carry was refused, and this branch asserted that refusal
            # and `continue`d. Every slice key is in that state on the live file
            # -- it carries [General] Enabled and nothing else [measured,
            # 2026-09-13] -- so for every slice gate this loop asserted the
            # refusal and never reached the write.
            #
            # set_value appends such a key now, so that branch would simply
            # stop running, and a check that stops running with nothing said is
            # the defect AGENTS.md section 3 is about. It is kept as an explicit
            # FAIL instead: if the refusal ever comes back, this says so by name
            # rather than going quiet and leaving the write untested.
            if not rp['ok']:
                summary = (rp.get('refused') or {}).get('summary', '')
                if 'is not in ckf.hardmode.cfg' in summary:
                    t.check('%s: a gate whose key is absent is appended, not '
                            'refused — the pre-slices refusal is back' % sub,
                            False, summary)
                    continue
                # A FOURTH WAY, ADDED BY PHASE 2. The editor now refuses
                # downward itself when an enabled slice's `requires` names the
                # key being turned off, and it does so BEFORE check_schema is
                # reached -- so that refusal carries no `blocking` list and no
                # `check` at all, which is what distinguishes it from the
                # linkedEnable one below and is asserted as such. Widening the
                # branch without reading the reason is how a refusal check
                # stops measuring anything; see the note in the linkedEnable
                # block of section 7.
                req = (rp.get('refused') or {}).get('requires')
                if req:
                    req_refused.append(sub)
                    t.check('%s: a gate an enabled slice requires is refused by '
                            'the editor, naming the dependent, before the '
                            'checker is reached' % sub,
                            bool(req.get('dependent'))
                            and req['dependent'] in (rp['refused'].get('summary') or '')
                            and 'blocking' not in rp and 'check' not in rp,
                            rp.get('refused'))
                    continue
                inv_refused.append(sub)
                t.check('%s: a gate that will not move alone is refused for a '
                        'stated INVARIANT, not silently' % sub,
                        any(q['kind'] == 'INVARIANT' for q in (rp.get('blocking') or [])),
                        rp.get('blocking') or rp.get('refused'))
                continue
            if unit:
                side, _found = dig(_read_section(cdp, unit), gate)
                t.check('%s: the gate is false in its own section on disk' % sub,
                        side is False, side)
                t.check('%s: only its own physical file was written' % sub,
                        'ckf.hardmode.cfg' not in rp['written'], rp['written'])
            else:
                side = CfgFile.load(os.path.join(cdp, 'ckf.hardmode.cfg')).raw_value(gate)
                t.check('%s: the gate is false in the cfg on disk' % sub,
                        str(side).strip().lower() == 'false',
                        'read back %r, wanted false' % (side,))
                # WHAT IS ASSERTED DEPENDS ON WHAT WAS ON DISK BEFORE THE SAVE.
                #
                # This read `rp['written'] == ['ckf.hardmode.cfg']` for every
                # gate, which says a save must always write. It must not:
                # writing the value a key already holds is a no-op, the
                # proposed bytes equal the current bytes, commit() puts the
                # file in `skipped`, and `written` is []. Section 13(a)
                # asserts that property directly -- 'a no-op save of an
                # untouched config writes zero bytes' -- so the two cases
                # contradicted each other and only one could be right.
                #
                # It went unnoticed while every slice gate defaulted true.
                # Slices.SelfCheck is the one slice whose declared default is
                # false; after the 2026-09-13 launch BepInEx wrote
                # `SelfCheck = false`, turning it off became a no-op, and this
                # FAILed alone out of 42 [measured]. The writer was correct
                # throughout. And it printed no DETAIL, because the check
                # passed no `detail` argument -- the same silence that cost a
                # round trip on make_release.py the same day. Both fixed.
                # THREE cases, because there are three things the save can
                # correctly do, and only one of them was being allowed for:
                #   key absent   -> appended, so the file IS written
                #   key != false -> replaced, so the file IS written
                #   key == false -> nothing to change, so NOTHING is written
                if was_raw is None:
                    t.check('%s: its key was not in the cfg, so the save '
                            'appended it and wrote the file' % sub,
                            rp['written'] == ['ckf.hardmode.cfg'],
                            'before=absent written=%r notes=%r'
                            % (rp.get('written'), rp.get('notes')))
                elif str(was_raw).strip().lower() == 'false':
                    t.check('%s: the gate was already false on disk, so the '
                            'save correctly wrote nothing' % sub,
                            rp['written'] == [],
                            'before=%r written=%r skipped=%r notes=%r'
                            % (was_raw, rp.get('written'), rp.get('skipped'),
                               rp.get('notes')))
                else:
                    t.check('%s: and only the cfg was written' % sub,
                            rp['written'] == ['ckf.hardmode.cfg'],
                            'before=%r written=%r skipped=%r notes=%r'
                            % (was_raw, rp.get('written'), rp.get('skipped'),
                               rp.get('notes')))
            appp2 = App({'gameDir': '', 'configDirOverride': cdp, 'stripReadme': False}, 'x')
            ent = [e for e in appp2.api_model()['enableIndex']
                   if e['subsystem'] == sub][0]
            moved_alone.append(sub)
            t.check('%s: and the enable index reads it back as off' % sub,
                    ent['effective'] == 'off', ent)

        # Which of the three endings each gate reached, printed on every run.
        # A census is the only thing that separates "no gate was refused by a
        # requires declaration" from "the branch that reads them stopped being
        # reached" -- the shape AGENTS.md section 3 is about, and the shape
        # check_schema's own `requires:` line exists for.
        print('        gate-off census: %d written off, %d refused by a '
              'requires declaration (%s), %d refused by a linkedEnable '
              'INVARIANT (%s)'
              % (len(moved_alone), len(req_refused),
                 ', '.join(req_refused) or 'none', len(inv_refused),
                 ', '.join(inv_refused) or 'none'))
        t.check('every gate reached one of the three endings — none fell '
                'through the loop untested',
                len(moved_alone) + len(req_refused) + len(inv_refused)
                == len(gates_to_exercise),
                (len(moved_alone), len(req_refused), len(inv_refused),
                 len(gates_to_exercise)))
        t.check('and the requires branch was actually reached: %d gate(s) are '
                'named by a live declaration' % len(req_refused),
                len(req_refused) == len([1 for _s, _d, _n, _r
                                         in requires_groups(apph.schemas)
                                         for _k in _n
                                         if _k in [sc['enable']['cfg']
                                                   for sc in cfg_gated]]),
                (req_refused, requires_groups(apph.schemas)))

        # (c2) the same gates, against a .cfg that carries their keys, AND
        #      against one that does not -- both derived, neither assumed
        #
        # REWRITTEN 2026-09-13 after the launch. This block used to open "The
        # block above measures the live file, where every slice key is still
        # absent, so every cfg gate lands in the 'not in the file yet' branch
        # and the WRITE path is never reached", and called _cfg_add_keys to
        # build "the after-a-launch shape". Both halves of that were bets on
        # the live file's contents. The game was launched, the live file went
        # from 1 key to 43, _cfg_add_keys hit its own AssertionError on the
        # [Slices] section that was now there, and the run ended with no
        # report line.
        #
        # Neither state is assumed now. Both are built from the source with
        # _cfg_with_keys and _cfg_without_keys, so this runs the same either
        # way and the source's own state is reported rather than relied on.
        slice_keys = sorted(set(sc['enable']['cfg'] for sc in cfg_gated
                                if sc['enable']['cfg'] != MASTER_KEY))
        if slice_keys:
            src_cfg = CfgFile.load(os.path.join(src, 'ckf.hardmode.cfg'))
            src_have = [k for k in slice_keys if k in src_cfg.keys]
            print('        source ckf.hardmode.cfg carries %d of the %d slice '
                  'gate key(s); both states are built from it either way'
                  % (len(src_have), len(slice_keys)))

            # ---- the after-a-launch shape
            cdk = _sandbox(src, os.path.join(td, 'slice-keys'))
            okk, whyk = _cfg_with_keys(os.path.join(cdk, 'ckf.hardmode.cfg'),
                                       slice_keys)
            t.check('the with-keys fixture builds, whatever state the source '
                    'was in', okk, whyk)
            appk = App({'gameDir': '', 'configDirOverride': cdk, 'stripReadme': False}, 'x')
            mk = appk.api_model()
            t.check('the fixture carries every slice gate key: %d'
                    % len(slice_keys),
                    all(mk['values']['cfg'][k]['present'] for k in slice_keys),
                    [k for k in slice_keys if not mk['values']['cfg'][k]['present']])
            t.check('and every one of them now reads as ON rather than unknown '
                    '— a gate that can be read is never reported unknown',
                    all(e['effective'] in ('on', 'off')
                        for e in mk['enableIndex']
                        if (by_sub[e['subsystem']].get('enable') or {}).get('cfg')),
                    [(e['subsystem'], e['effective'], e['gates'])
                     for e in mk['enableIndex']
                     if (by_sub[e['subsystem']].get('enable') or {}).get('cfg')
                     and e['effective'] not in ('on', 'off')])

            # ---- the before-a-launch shape, which is what a fresh install, a
            #      deleted .cfg and a newly added slice all look like
            cdn = _sandbox(src, os.path.join(td, 'slice-nokeys'))
            okn, whyn = _cfg_without_keys(os.path.join(cdn, 'ckf.hardmode.cfg'),
                                          slice_keys)
            t.check('the without-keys fixture builds, whatever state the '
                    'source was in', okn, whyn)
            appn2 = App({'gameDir': '', 'configDirOverride': cdn,
                         'stripReadme': False}, 'x')
            mn2 = appn2.api_model()
            t.check('the without-keys fixture carries none of the %d slice '
                    'gate keys' % len(slice_keys),
                    not any(mn2['values']['cfg'][k]['present'] for k in slice_keys),
                    [k for k in slice_keys if mn2['values']['cfg'][k]['present']])
            t.check('and the master switch survived removing them — the '
                    'builder took out the slice keys and nothing else',
                    mn2['values']['cfg'][MASTER_KEY]['present'] is True,
                    mn2['values']['cfg'][MASTER_KEY])
            t.check('and every slice gate reads unknown there, never off — a '
                    'gate that cannot be read is not a gate that is off',
                    all(e['effective'] == 'unknown' for e in mn2['enableIndex']
                        if (by_sub[e['subsystem']].get('enable') or {}).get('cfg')
                        in slice_keys),
                    [(e['subsystem'], e['effective']) for e in mn2['enableIndex']
                     if (by_sub[e['subsystem']].get('enable') or {}).get('cfg')
                     in slice_keys and e['effective'] != 'unknown'])

            # ---- the write, driven through BOTH shapes
            req_shape = {'present': [], 'absent': []}
            for shape, builder in (('present', _cfg_with_keys),
                                   ('absent', _cfg_without_keys)):
                written_off, appended, refused = 0, 0, 0
                for sch in [sc for sc in cfg_gated
                            if sc['enable']['cfg'] != MASTER_KEY]:
                    sub, gate = sch['subsystem'], sch['enable']['cfg']
                    cdg = _sandbox(src, os.path.join(td, 'slice-%s-%s' % (shape, sub)))
                    okg, whyg = builder(os.path.join(cdg, 'ckf.hardmode.cfg'),
                                        slice_keys)
                    if not okg:
                        t.check('%s [%s]: its fixture builds' % (sub, shape),
                                False, whyg)
                        continue
                    before_g = read_bytes(os.path.join(cdg, 'ckf.hardmode.cfg'))
                    had = gate in CfgFile(before_g).keys
                    appg = App({'gameDir': '', 'configDirOverride': cdg,
                                'stripReadme': False}, 'x')
                    rg = appg.api_save({'cfg': {gate: {'value': False}}})
                    if not rg['ok']:
                        refused += 1
                        # The requires refusal reaches the [absent] pass too,
                        # and that is the point of running it: with every slice
                        # key removed the dependent is not in the file at all,
                        # its schema default applies, and the editor still
                        # refuses. tasks.md records the opposite for
                        # linkedEnable -- "the editor cannot protect a linked
                        # group on a fresh install" -- because check_schema has
                        # nothing to compare. requires does not inherit that
                        # hole HERE; the checker still has it, and says SKIPPED.
                        reqg = (rg.get('refused') or {}).get('requires')
                        if reqg:
                            req_shape[shape].append(sub)
                            t.check('%s [%s]: a gate an enabled slice requires '
                                    'is refused by the editor, naming the '
                                    'dependent' % (sub, shape),
                                    bool(reqg.get('dependent'))
                                    and reqg['dependent'] in
                                        (rg['refused'].get('summary') or '')
                                    and 'blocking' not in rg,
                                    rg.get('refused'))
                            continue
                        t.check('%s [%s]: a gate its linkedEnable group will '
                                'not let move alone is refused for a stated '
                                'INVARIANT' % (sub, shape),
                                any(q['kind'] == 'INVARIANT'
                                    for q in (rg.get('blocking') or [])),
                                rg.get('blocking') or rg.get('refused'))
                        continue
                    written_off += 1
                    after_g = read_bytes(os.path.join(cdg, 'ckf.hardmode.cfg'))
                    if had:
                        t.check('%s [%s]: writing its cfg gate off changes '
                                'exactly one line' % (sub, shape),
                                _one_line_changed(before_g, after_g),
                                _first_line_diff(before_g, after_g))
                    else:
                        appended += 1
                        t.check('%s [%s]: writing its cfg gate off appends the '
                                'key and disturbs no line that was there'
                                % (sub, shape),
                                _is_pure_insertion(before_g, after_g),
                                _first_line_diff(before_g, after_g))
                    t.check('%s [%s]: and only ckf.hardmode.cfg was written'
                            % (sub, shape),
                            rg['written'] == ['ckf.hardmode.cfg'],
                            'had=%s written=%r notes=%r'
                            % (had, rg.get('written'), rg.get('notes')))
                    appg2 = App({'gameDir': '', 'configDirOverride': cdg,
                                 'stripReadme': False}, 'x')
                    entg = [e for e in appg2.api_model()['enableIndex']
                            if e['subsystem'] == sub][0]
                    t.check('%s [%s]: and the enable index reads the written '
                            'gate as off' % (sub, shape),
                            entg['effective'] == 'off', entg)
                t.check('[%s] %d of %d slice gates were actually written off '
                        '(%d by appending), %d refused by a named INVARIANT'
                        % (shape, written_off, len(slice_keys), appended, refused),
                        written_off > 0,
                        'written_off=%d appended=%d refused=%d'
                        % (written_off, appended, refused))
                print('        [%s] refused by a requires declaration (%d): %s'
                      % (shape, len(req_shape[shape]),
                         ', '.join(req_shape[shape]) or 'none'))
                if shape == 'absent':
                    t.check('[absent] every write in that pass was an append — '
                            'the fixture really had removed the keys, so this '
                            'pass is not a second copy of the present one',
                            appended == written_off,
                            'appended=%d of %d written' % (appended, written_off))
            t.check('the requires refusal fires in BOTH shapes, including the '
                    'one where no slice key is in the file at all — that is '
                    'the fresh install, and it is the case linkedEnable '
                    'cannot cover',
                    req_shape['present'] and req_shape['absent']
                    and req_shape['present'] == req_shape['absent'],
                    req_shape)
        else:
            t.skip('a cfg gate is exercised through the write path',
                   'no schema declares a cfg gate other than %s, so there is '
                   'no slice key to write' % MASTER_KEY)

        # (d) the one cfg key left is still writable, in place
        #
        # [General] Enabled stays a BepInEx bind because it is the switch that
        # has to work when ckf.hardmode.json does not exist at all. The writer
        # that serves it is now value-line replacement and nothing else, so
        # what is asserted is exactly that: one line changed, no comment
        # written, no second line for the key, and the rest of the file byte
        # for byte.
        cdm = _sandbox(src, os.path.join(td, 'master'))
        appm = App({'gameDir': '', 'configDirOverride': cdm, 'stripReadme': False}, 'x')
        cfg_before_m = read_bytes(os.path.join(cdm, 'ckf.hardmode.cfg'))
        rm = appm.api_save({'cfg': {MASTER_KEY: {'value': False}}})
        t.check('the master switch saves', rm['ok'], rm.get('refused'))
        cfg_after_m = read_bytes(os.path.join(cdm, 'ckf.hardmode.cfg'))
        t.check('exactly one line of the cfg changed',
                _one_line_changed(cfg_before_m, cfg_after_m),
                _first_line_diff(cfg_before_m, cfg_after_m))
        t.check('and the file still carries exactly one line for the key',
                _cfg_key_line_count(cfg_after_m, 'General', 'Enabled') == 1,
                _cfg_key_line_count(cfg_after_m, 'General', 'Enabled'))
        t.check('no comment was written',
                _cfg_line_shape(os.path.join(src, 'ckf.hardmode.cfg'),
                                os.path.join(cdm, 'ckf.hardmode.cfg')))
        appm2 = App({'gameDir': '', 'configDirOverride': cdm, 'stripReadme': False}, 'x')
        mm = appm2.api_model()
        t.check('the master switch reads back false',
                mm['values']['cfg'][MASTER_KEY]['value'] is False,
                mm['values']['cfg'][MASTER_KEY])
        t.check('and every other subsystem is reported as gated by it',
                all(e['gatedByMaster'] for e in mm['enableIndex']
                    if e['subsystem'] != 'General'),
                [(e['subsystem'], e['gatedByMaster']) for e in mm['enableIndex']])

        # A key the file does not carry is APPENDED through the whole save, not
        # refused. This is the end-to-end half of scenario 2; section [8b]
        # drives CfgFile directly. The fixture strips [General] Enabled out of
        # a sandbox copy, which is the one absent-key state that can be built
        # from the live file without inventing a key no schema declares.
        #
        # REPLACED, split-config-into-toggleable-slices. The two cases here
        # were 'a cfg key the file does not carry is refused, not appended' and
        # 'and nothing was written by that refusal'.
        cdx = _sandbox(src, os.path.join(td, 'nokey'))
        cx = CfgFile.load(os.path.join(cdx, 'ckf.hardmode.cfg'))
        gone = [ln for i, ln in enumerate(cx.lines) if i != cx.keys[MASTER_KEY]]
        gone_ends = [e for i, e in enumerate(cx.ends) if i != cx.keys[MASTER_KEY]]
        if gone_ends:
            gone_ends[-1] = ''
        with open(os.path.join(cdx, 'ckf.hardmode.cfg'), 'wb') as fh:
            fh.write(''.join(l + e for l, e in zip(gone, gone_ends)).encode('utf-8'))
        before_x = read_bytes(os.path.join(cdx, 'ckf.hardmode.cfg'))
        t.check('the fixture really has lost the key it is about to have '
                'appended — a fixture that still carries it would test the '
                'replace path under the append path\'s name',
                MASTER_KEY not in CfgFile(before_x).keys, sorted(CfgFile(before_x).keys))
        appx = App({'gameDir': '', 'configDirOverride': cdx, 'stripReadme': False}, 'x')
        rx = appx.api_save({'cfg': {MASTER_KEY: {'value': False}}})
        t.check('a cfg key the file does not carry is appended by a save, '
                'not refused', rx['ok'], rx.get('refused'))
        cx2 = CfgFile.load(os.path.join(cdx, 'ckf.hardmode.cfg'))
        t.check('and the appended key reads back with the value that was saved',
                cx2.raw_value(MASTER_KEY) == 'false', cx2.raw_value(MASTER_KEY))
        t.check('and it landed under [General], not at the end of the file '
                'under whatever header sat above it',
                MASTER_KEY in cx2.keys
                and cx2.keys[MASTER_KEY] > cx2.sections['General'],
                (cx2.keys.get(MASTER_KEY), cx2.sections.get('General')))
        t.check('and exactly one line carries it',
                _cfg_key_line_count(cx2.to_bytes(), 'General', 'Enabled') == 1,
                _cfg_key_line_count(cx2.to_bytes(), 'General', 'Enabled'))
        t.check('and every line the fixture already had is still there, '
                'byte for byte and ending for ending',
                _is_pure_insertion(before_x,
                                   read_bytes(os.path.join(cdx, 'ckf.hardmode.cfg'))),
                _first_line_diff(before_x,
                                 read_bytes(os.path.join(cdx, 'ckf.hardmode.cfg'))))
        appx2 = App({'gameDir': '', 'configDirOverride': cdx, 'stripReadme': False}, 'x')
        t.check('and the editor reads the appended key back as present',
                appx2.api_model()['values']['cfg'][MASTER_KEY]['present'] is True,
                appx2.api_model()['values']['cfg'][MASTER_KEY])

        # (d2) A TOGGLE CHANGE WRITES THE .cfg AND NOTHING ELSE.
        #
        # split-config-into-toggleable-slices tasks.md, Phase 1, tenth
        # checkbox: "flip one toggle, save, and every other file in
        # BepInEx/config/ is byte-identical, including its line endings."
        #
        # Byte comparison is what carries the line-ending half: two files that
        # differ only in their endings differ in their bytes, so there is no
        # separate ending check to forget. Every file under the directory is
        # compared, walked rather than listed, so a file a later phase adds is
        # covered without anyone remembering to add it here. The four-phase
        # journalled transaction, the fingerprints SHA-256 check and the
        # per-file commit are not touched by any of this; what is asserted is
        # that the toggle write rides on them and drags nothing else along.
        #
        # The toggle flipped is a SLICE gate, not the master switch, and the
        # fixture REMOVES its key first, so this covers the append path end to
        # end through commit() and not just the replacement that already
        # shipped.
        #
        # CORRECTION, 2026-09-13 afternoon: the removal is new. This block
        # asserted 'the toggle being flipped is a key the .cfg does not carry'
        # against the live file, which carried one key that morning and 43
        # after the launch, so the assertion FAILed and the insertion check
        # under it FAILed with it. Same defect as section [8b]'s: the state was
        # read off the source instead of built. It is built now, so the append
        # is exercised whichever state the source is in.
        cdt = _sandbox(src, os.path.join(td, 'only-the-cfg'))
        slice_gates = [sc for sc in apph.schemas
                       if (sc.get('enable') or {}).get('cfg')
                       and sc['enable']['cfg'] != MASTER_KEY]
        if not slice_gates:
            t.skip('a toggle change writes the .cfg and leaves every other '
                   'file in BepInEx/config byte-identical',
                   'no schema declares a cfg enable gate other than the master '
                   'switch, so there is no slice toggle to flip. Phase 1 of '
                   'split-config-into-toggleable-slices is what adds them.')
        else:
            tgate = slice_gates[0]['enable']['cfg']
            okt, whyt = _cfg_without_keys(os.path.join(cdt, 'ckf.hardmode.cfg'),
                                          [tgate])
            t.check('the only-the-cfg fixture can remove the key it is about '
                    'to have appended', okt, whyt)
            t.check('the toggle being flipped is a key the .cfg does not '
                    'carry, so this covers the append, not the replace',
                    tgate not in CfgFile.load(
                        os.path.join(cdt, 'ckf.hardmode.cfg')).keys,
                    'key %s still in the fixture' % tgate)
            # Snapshot AFTER the fixture is built: what this asserts is that
            # the SAVE changed one file, not that the fixture builder did.
            before_t = dict((rel, read_bytes(os.path.join(cdt, rel)))
                            for rel in _walk_rel(cdt))
            t.check('the only-the-cfg fixture has more than one file to be '
                    'wrong about — a directory of one file cannot fail this',
                    len(before_t) > 1, sorted(before_t))
            appt = App({'gameDir': '', 'configDirOverride': cdt,
                        'stripReadme': False}, 'x')
            rt = appt.api_save({'cfg': {tgate: {'value': False}}})
            t.check('flipping one slice toggle saves', rt['ok'], rt.get('refused'))
            t.check('and the only file it reports writing is ckf.hardmode.cfg',
                    rt.get('written') == ['ckf.hardmode.cfg'], rt.get('written'))
            after_t = dict((rel, read_bytes(os.path.join(cdt, rel)))
                           for rel in _walk_rel(cdt))
            t.check('and no file was created or removed under BepInEx/config',
                    sorted(after_t) == sorted(before_t),
                    sorted(set(after_t) ^ set(before_t)))
            moved = sorted(rel for rel in before_t
                           if rel in after_t and after_t[rel] != before_t[rel])
            t.check('and every other file is byte-identical, line endings '
                    'included — bytes differ if endings do',
                    moved == ['ckf.hardmode.cfg'], moved)
            t.check('and the .cfg it did write really did change, so the '
                    'comparison above is not passing on a save that did nothing',
                    after_t['ckf.hardmode.cfg'] != before_t['ckf.hardmode.cfg'])
            t.check('and the change to it was an insertion: every line that '
                    'was there is still there, ending included',
                    _is_pure_insertion(before_t['ckf.hardmode.cfg'],
                                       after_t['ckf.hardmode.cfg']),
                    _first_line_diff(before_t['ckf.hardmode.cfg'],
                                     after_t['ckf.hardmode.cfg']))
            t.check('and the toggle reads back off',
                    App({'gameDir': '', 'configDirOverride': cdt,
                         'stripReadme': False}, 'x')
                    .api_model()['values']['cfg'][tgate]['value'] is False)
            t.check('and the transaction left no journal and no temporaries',
                    not os.path.exists(journal_path(cdt))
                    and not [f for f in os.listdir(cdt) if TMP_SUFFIX in f],
                    os.listdir(cdt))

        # (e) an emptied mission slot round-trips as a present empty string, and
        #     the unset-vs-absent contract is untouched everywhere else
        cde = _sandbox(src, os.path.join(td, 'slots'))
        appe = App({'gameDir': '', 'configDirOverride': cde, 'stripReadme': False}, 'x')
        me = appe.api_model()
        akey = [k for k, v in me['values']['tables'].items()
                if any(fmt == 'adjust' for fmt in v['formats'].values())][0]
        atab = me['values']['tables'][akey]
        acol = [c for c, fmt in atab['formats'].items() if fmt == 'adjust'][0]
        arows = json.loads(json.dumps(atab['rows']))
        filled = [r for r in arows if r['cells'].get(acol)][0]
        filled['cells'][acol] = ''
        ee = {'json': {atab['sidecar']: {'scalars': {},
                                         'tables': {atab['path']: {'shape': atab['shape'],
                                                                   'rows': arows}}}}}
        re_ = appe.api_save(ee)
        t.check('clearing a mission slot saves', re_['ok'], re_.get('refused'))
        after_rows = _read_section(cde, atab['sidecar'])
        after_row = dig(after_rows, atab['path'])[0][arows.index(filled)]
        t.check('an emptied slot is a present empty string, not a removed key — '
                'Adjust.Parse("") and Adjust.Parse(null) are both `none`',
                acol in after_row and after_row[acol] == '', after_row)

        # (f) unset is still not zero where it means something
        cdu = _sandbox(src, os.path.join(td, 'unset'))
        appu = App({'gameDir': '', 'configDirOverride': cdu, 'stripReadme': False}, 'x')
        mu = appu.api_model()
        ckey = [k for k, v in mu['values']['tables'].items()
                if (json_fields(appu.schemas).get((v['sidecar'], v['path'])) or
                    (None, {}))[1].get('ui') == 'curve'
                and v['shape'] == 'array'][0]
        ctab = mu['values']['tables'][ckey]
        ccol = [c['name'] for c in json_fields(appu.schemas)[(ctab['sidecar'],
                                                             ctab['path'])][1]['row']][1]
        crows = json.loads(json.dumps(ctab['rows']))
        crows[0]['cells'][ccol] = None
        ru = appu.api_save({'json': {ctab['sidecar']: {'scalars': {}, 'tables': {
            ctab['path']: {'shape': ctab['shape'], 'rows': crows}}}}})
        t.check('clearing a reward-curve cell saves', ru['ok'], ru.get('refused'))
        crow0 = dig(_read_section(cdu, ctab['sidecar']),
                    ctab['path'])[0][0]
        t.check('a cleared reward-curve cell round-trips as an ABSENT key, '
                'unchanged from before this work', ccol not in crow0, crow0)
        mrows = json.loads(json.dumps(mh2['values']['tables'][tkey]['rows']))
        dropped = mrows.pop(0)
        rm = apph.api_save({'json': {mh2['values']['tables'][tkey]['sidecar']:
                                     {'scalars': {}, 'tables': {
                                         mh2['values']['tables'][tkey]['path']:
                                         {'shape': 'array', 'rows': mrows}}}}})
        t.check('clearing a matrix cell saves', rm['ok'], rm.get('refused'))
        teampl_now = _read_section(cdh, U_TEAMPL)
        still = [r for r in teampl_now[mh2['values']['tables'][tkey]['path']]
                 if r[axes['row']] == dropped['cells'][axes['row']]
                 and r[axes['col']] == dropped['cells'][axes['col']]]
        t.check('a cleared matrix cell removes its override row and does not '
                'leave a zero behind', not still, still)

    print('\n[14] app.html pure functions, under node')
    rc = selftest_js()
    if rc == 0:
        t.passed += 1
        print('  PASS  node self-test of app.html')
    elif rc == 2:
        print('  SKIP  node is not available; app.html JS was NOT exercised')
        t.failed.append(('node self-test', 'node not available — not run'))
    else:
        t.failed.append(('node self-test', 'see output above'))

    print('\n[15] app.html, rendered — order, grouping and columns under a DOM stub')
    ok, detail = app_html_syntax()
    if ok is None:
        print('  SKIP  %s' % detail)
    else:
        t.check('both of app.html\'s script blocks parse (node --check)', ok, detail)
    with tempfile.TemporaryDirectory() as td:
        cdr = _sandbox(src, os.path.join(td, 'render'))
        # BOTH STATES OF A CFG GATE, IN ONE RENDER. The live ckf.hardmode.cfg
        # carries the master switch and nothing else until the game has been
        # launched with a build that binds the slice keys, so a render against
        # it would draw every slice toggle disabled and unreadable, the
        # linkedEnable group would resolve to nothing, and the writable branch
        # of the page would not be exercised at all. So the fixture writes the
        # slice keys BepInEx will write -- except one, deliberately held back
        # and named here, so the same render also covers a gate whose key is
        # not in the file. The key held back is the last one that no
        # linkedEnable group names, so holding it back cannot break a group.
        _gate_keys = sorted(set((sc.get('enable') or {}).get('cfg') for sc in schemas
                                if (sc.get('enable') or {}).get('cfg')) - {MASTER_KEY})
        _linked = set(k for sc in schemas for inv in sc.get('invariants', [])
                      if inv.get('kind') == 'linkedEnable' for k in inv['keys'])
        _held = [k for k in _gate_keys if k not in _linked][-1:]
        _write = [k for k in _gate_keys if k not in _held]
        if _write:
            okr, whyr = _cfg_with_keys(os.path.join(cdr, 'ckf.hardmode.cfg'), _write)
            t.check('the render fixture writes the slice keys it means to', okr, whyr)
        if _held:
            # The held-back key has to be ABSENT, and after the 2026-09-13
            # launch the source carries all 43 -- so it is removed here rather
            # than assumed missing. Without this the render covers only the
            # in-the-file branch and the other one goes untested in silence.
            okh, whyh = _cfg_without_keys(os.path.join(cdr, 'ckf.hardmode.cfg'), _held)
            t.check('the render fixture holds back the key it means to', okh, whyh)
        print('        render fixture cfg: %d slice key(s) written, held back: %s'
              % (len(_write), ', '.join(_held) or 'none'))
        t.check('the render fixture covers a gate that is in the file and one '
                'that is not — a render where every gate reads the same way '
                'proves only one of the two branches',
                bool(_write) and bool(_held), (_write, _held))
        appr = App({'gameDir': '', 'configDirOverride': cdr, 'stripReadme': False}, 'render')
        rc2 = selftest_dom(appr.api_model())
        if rc2 == 0:
            t.passed += 1
            print('  PASS  app.html renders the config it was given')
        elif rc2 == 2:
            print('  SKIP  node is not available; app.html was NOT rendered')
            t.failed.append(('node render', 'node not available — not run'))
        else:
            t.failed.append(('node render', 'see output above'))

        # The same page, over a config carrying an override in a column the
        # window hides. The row is data, so the column comes back -- and says
        # why it is there.
        cdo = _sandbox(src, os.path.join(td, 'render-outside'))
        appo = App({'gameDir': '', 'configDirOverride': cdo, 'stripReadme': False}, 'render')
        mo = appo.api_model()
        okey = [k for k, v in mo['values']['tables'].items()
                if (json_fields(appo.schemas).get((v['sidecar'], v['path'])) or
                    (None, {}))[1].get('ui') == 'matrix'][0]
        otab = mo['values']['tables'][okey]
        oax = json_fields(appo.schemas)[(otab['sidecar'], otab['path'])][1]['axes']
        owin = AXIS_WINDOWS[('Progression', oax['col'])]
        orows = json.loads(json.dumps(otab['rows']))
        orows.append({'id': None, 'cells': {oax['row']: 2, oax['col']: owin[0] - 1,
                                            oax['value']: 0.02}})
        ro_ = appo.api_save({'json': {otab['sidecar']: {'scalars': {}, 'tables': {
            otab['path']: {'shape': 'array', 'rows': orows}}}}})
        t.check('the fixture with an override outside the window saved',
                ro_['ok'], ro_.get('refused'))
        rc3 = selftest_dom(appo.api_model(), DOM_ASSERTS_OUTSIDE)
        if rc3 == 0:
            t.passed += 1
            print('  PASS  a hidden column that carries an override is drawn, and said so')
        elif rc3 == 2:
            print('  SKIP  node is not available')
            t.failed.append(('node render (outside)', 'node not available — not run'))
        else:
            t.failed.append(('node render (outside)', 'see output above'))


    # ---- 16. the frozen exe
    print('\n[16] the frozen exe — the check_schema re-entry')
    with tempfile.TemporaryDirectory() as td:
        cdz = _sandbox(src, os.path.join(td, 'frozen'))
        appz = App({'gameDir': '', 'configDirOverride': cdz, 'stripReadme': False}, 'z')
        mz = appz.api_model()
        tabz = mz['values']['tables'][tk]
        axz = json_fields(appz.schemas)[(tabz['sidecar'], tabz['path'])][1]['axes']
        VALCOL = axz['value']

        def _edit(value):
            rs = json.loads(json.dumps(tabz['rows']))
            rs[0]['cells'][VALCOL] = value
            return {'json': {tabz['sidecar']: {'scalars': {}, 'tables': {
                tabz['path']: {'shape': tabz['shape'], 'rows': rs}}}}}

        _cur_z = tabz['rows'][0]['cells'].get(VALCOL)
        LEGAL = 0.31 if not isinstance(_cur_z, (int, float)) or abs(_cur_z - 0.31) > 1e-12 else 0.32
        OUT_OF_RANGE = 99.0     # the column's declared range is [0, 5]

        # ---- the two argv shapes, both built on this machine
        un = check_schema_argv(cdz, frozen=False)
        fr = check_schema_argv(cdz, frozen=True)
        t.check('unfrozen, the child is an interpreter running check_schema.py',
                un[1] == CHECK_SCHEMA_PY and RUN_CHECK_SCHEMA not in un, un)
        t.check('frozen, the child is this executable re-entering itself',
                fr[0] == sys.executable and fr[1] == RUN_CHECK_SCHEMA, fr)
        t.check('frozen, no script path is handed to anything — sys.executable '
                'is the exe, and a path there would relaunch the GUI',
                not [x for x in fr if x.endswith('.py')], fr)
        t.check('both shapes validate the directory they were asked about',
                un[un.index('--config') + 1] == cdz == fr[fr.index('--config') + 1])
        t.check('the frozen shape names no --schema, so the child resolves its '
                'own bundle rather than the parent\'s temp directory',
                '--schema' not in fr, fr)

        # ---- the teardown instrument itself, on every machine
        #
        # _procs_settle is what decides whether the frozen HTTP case below
        # leaked a process, and the single immediate _procs_from it replaced
        # got that wrong on Windows: it FAILED while the delete beside it
        # PASSED, which cannot both be true of a process that was really still
        # holding the image. [David, 2026-09-04]
        #
        # These belong here rather than in the frozen block because here they
        # have a sampling moment on any machine: _procs_from is stubbed, so
        # the sequence of answers is the fixture and the OS is not involved.
        # The frozen block can only ever sample whatever its own teardown
        # happens to do on the machine running it.
        _real_procs_from = _procs_from
        seq = []
        try:
            globals()['_procs_from'] = lambda _p: (seq.pop(0) if seq else [])

            seq = [[]]
            t.check('nothing running reads as none',
                    _procs_settle('x', tries=3, delay=0) == [])

            seq = [['7'], ['7'], []]
            t.check('a pid still there while Windows finishes an asynchronous '
                    'teardown is not a leak — the poll is the fix for the '
                    'failure of 2026-09-04',
                    _procs_settle('x', tries=5, delay=0) == [])

            seq = [['7', '9'], ['9'], ['9']]
            t.check('a process of the same name that was already running '
                    'before the launch is not this copy\'s',
                    _procs_settle('x', exclude={'9'}, tries=3, delay=0) == [])

            seq = [['7'], ['7'], ['7']]
            t.check('a process that really does survive the whole budget is '
                    'still reported',
                    _procs_settle('x', tries=3, delay=0) == ['7'])

            seq = [None, None, None]
            t.check('an instrument that could never look returns None, which '
                    'the caller fails on, rather than none',
                    _procs_settle('x', tries=3, delay=0) is None)

            seq = [None, ['7'], []]
            t.check('one failed look does not end the poll',
                    _procs_settle('x', tries=3, delay=0) == [])
        finally:
            globals()['_procs_from'] = _real_procs_from

        # ---- the dispatch itself, as a real child process. Unfrozen it is the
        #      same code the exe runs, which is why it is not gated on FROZEN.
        SERVE_PY = os.path.abspath(__file__)
        rz = subprocess.run([sys.executable, SERVE_PY, RUN_CHECK_SCHEMA,
                             '--config', cdz],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, timeout=CHECK_SCHEMA_TIMEOUT)
        zout = rz.stdout.decode('utf-8', 'replace')
        zerr = rz.stderr.decode('utf-8', 'replace')
        t.check('%s exits 0 or 1, the way check_schema does' % RUN_CHECK_SCHEMA,
                rz.returncode in (0, 1), (rz.returncode, zerr[-400:]))
        t.check('%s prints check_schema\'s summary line' % RUN_CHECK_SCHEMA,
                _CHECK_SUMMARY_RE.search(zout) is not None, zout[-400:])
        t.check('%s starts no server and opens no browser' % RUN_CHECK_SCHEMA,
                'listening' not in zout and 'stop with Ctrl-C' not in zout, zout[:400])
        # NOT asserted here: that the re-entry resolves a schema directory
        # when none is named. check_schema.py's own --schema default is
        # dirname(its own __file__), which from a checkout is already the right
        # directory, so the check could not fail unfrozen whatever
        # run_check_schema_entry did. Frozen it can -- __file__ lands at the
        # unpack root, not at <root>/schema -- and it is asserted there, as
        # 'the exe finds its own bundled schemas'.

        # ---- and the result it produces has to be the script path's result
        direct = run_check_schema(cdz)
        t.check('the script-path child returns a complete result', direct['ran'], direct)
        with _child_cmd(lambda cd: [sys.executable, SERVE_PY, RUN_CHECK_SCHEMA,
                                    '--config', cd]):
            via = run_check_schema(cdz)
        t.check('the re-entry child returns a complete result too', via['ran'], via)
        t.check('and names exactly the same problems as the script path',
                set((p['kind'], p['message']) for p in via['problems'])
                == set((p['kind'], p['message']) for p in direct['problems']),
                sorted(set((p['kind'], p['message']) for p in via['problems'])
                       ^ set((p['kind'], p['message']) for p in direct['problems'])))

        # ---- the save-blocking rules, over a substituted child process.
        #      The control comes first: this edit IS accepted when the
        #      validator works, so a refusal below is the validator and not
        #      the edit.
        stub = os.path.join(td, 'child_stub.py')
        with open(stub, 'w', encoding='utf-8') as f:
            f.write(_CHILD_STUB)
        cdc = _sandbox(src, os.path.join(td, 'control'))
        appc2 = App({'gameDir': '', 'configDirOverride': cdc, 'stripReadme': False}, 'z')
        appc2.api_model()
        with _child_cmd(lambda cd: [sys.executable, stub, 'clean']):
            ctl = appc2.api_save(_edit(LEGAL))
        t.check('control: with a child that answers, the edit saves',
                ctl['ok'], ctl.get('refused'))

        before_z = read_bytes(os.path.join(cdz, F_TEAMPL))
        for mode, why in (('crash', 'exits 3 after printing a clean summary'),
                          ('nosummary', 'prints a problem line and no summary'),
                          ('miscount', 'says 3 problems and prints 1')):
            with _child_cmd(lambda cd, m=mode: [sys.executable, stub, m]):
                res = run_check_schema(cdz)
                t.check('a child that %s reads as could-not-run, not as clean' % why,
                        not res['ran'] and bool(res['error']) and not res['problems'], res)
                rr = appz.api_save(_edit(LEGAL))
                t.check('and the save is refused because validation could not '
                        'run (%s)' % mode,
                        not rr['ok'] and 'could not run'
                        in (rr.get('refused') or {}).get('summary', ''), rr)
            t.check('nothing was written by the refused save (%s)' % mode,
                    read_bytes(os.path.join(cdz, F_TEAMPL)) == before_z)

        # ---- the exe itself. Building it needs PyInstaller and produces a
        #      binary for the machine that built it, so these run only when one
        #      is handed over. Absent that they are NOT RUN and say so.
        WHY = ('no --frozen-exe given. Build it with '
               '`pyinstaller gui/ckf-config-editor.spec` and re-run as '
               '`serve.py --selftest --frozen-exe dist/CKF-Config-Editor.exe`')
        if not frozen_exe:
            t.skip('the exe answers %s with a complete check_schema result'
                   % RUN_CHECK_SCHEMA, WHY)
            t.skip('the save-blocking rules hold with the exe as the validator', WHY)
            t.skip('the frozen exe defaults to the directory it ran from', WHY)
        else:
            fx = os.path.abspath(frozen_exe)
            print('        frozen exe: %s' % fx)
            rx = subprocess.run([fx, RUN_CHECK_SCHEMA, '--config', cdz],
                                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, timeout=CHECK_SCHEMA_TIMEOUT)
            xout = rx.stdout.decode('utf-8', 'replace')
            t.check('the exe %s exits 0 or 1' % RUN_CHECK_SCHEMA,
                    rx.returncode in (0, 1),
                    (rx.returncode, rx.stderr.decode('utf-8', 'replace')[-400:]))
            t.check('the exe prints check_schema\'s summary line',
                    _CHECK_SUMMARY_RE.search(xout) is not None, xout[-400:])
            t.check('the exe starts no server in that mode',
                    'listening' not in xout, xout[:400])
            t.check('the exe finds its own bundled schemas',
                    'declared across' in xout and ' 0 schema file(s)' not in xout,
                    xout[-200:])
            with _child_cmd(lambda cd: [fx, RUN_CHECK_SCHEMA, '--config', cd]):
                vx = run_check_schema(cdz)
                t.check('the exe returns a complete result to run_check_schema',
                        vx['ran'], vx)
                t.check('and names exactly the same problems as the script path',
                        set((p['kind'], p['message']) for p in vx['problems'])
                        == set((p['kind'], p['message']) for p in direct['problems']),
                        vx['problems'])
                cdx = _sandbox(src, os.path.join(td, 'exe'))
                appx = App({'gameDir': '', 'configDirOverride': cdx,
                            'stripReadme': False}, 'z')
                appx.api_model()
                rbad = appx.api_save(_edit(OUT_OF_RANGE))
                t.check('with the exe as the validator an out-of-range save is '
                        'still refused, naming RANGE',
                        not rbad['ok']
                        and any(p['kind'] == 'RANGE' for p in (rbad.get('blocking') or [])),
                        rbad)
                rok = appx.api_save(_edit(LEGAL))
                t.check('and a legal save still goes through', rok['ok'],
                        rok.get('refused'))

            # The player's actual path, end to end: the exe binds a port,
            # serves the page out of its own bundle, and answers /api/model --
            # which means it ran check_schema through its own re-entry and
            # read docs/ and schema/ out of _MEIPASS. A free port is chosen
            # here and handed over rather than read back from the exe's
            # stdout, which a redirected pipe may hold in a buffer.
            import urllib.request
            sk = socket.socket()
            sk.bind(('127.0.0.1', 0))
            xport = sk.getsockname()[1]
            sk.close()
            cdw = _sandbox(src, os.path.join(td, 'exe-serve'))
            # A copy, in a directory of its own. settings.json is the one thing
            # the exe WRITES, and _MEIPASS is deleted on exit, so it has to
            # land beside the executable -- which in the zip is the game root.
            # Running the copy is what gives that somewhere to be seen.
            #
            # NOT under `td`. A one-file exe that is still running cannot be
            # unlinked on Windows, so a copy inside the block's own
            # TemporaryDirectory turns any failure to kill it into a
            # PermissionError out of the cleanup -- which is what happened on
            # 2026-09-04: every case in this section had passed and the run
            # died before printing the report. Its own directory, deleted with
            # retries and never raising, keeps a lock from costing the result.
            exedir = tempfile.mkdtemp(prefix='ckf-exe-home-')
            fxr = os.path.join(exedir, os.path.basename(fx))
            shutil.copy2(fx, fxr)
            # The install the release zip produces: the exe sits in the folder
            # holding the game. The marker file is what default_game_dir tests
            # for, so writing it here is what makes the directory a game
            # directory as far as the exe is concerned -- and without it the
            # case below could not tell the right answer from the hardcoded
            # Steam path, which exists on the machine this usually runs on.
            with open(os.path.join(exedir, GAME_MARKER), 'w') as fh:
                fh.write('')
            want_settings = os.path.join(
                exedir, os.path.splitext(os.path.basename(fx))[0] + '.settings.json')
            # The baseline, BEFORE anything is launched. `_procs_from` matches
            # by image name on Windows, so without this the teardown check
            # counts any other CKF-Config-Editor.exe on the machine -- the one
            # in dist/, or a player's -- and reports it as a leak from this
            # copy. None here means no baseline could be taken; the check says
            # so if it later fails.
            before = _procs_from(fxr)
            popen_kw = {}
            if os.name == 'posix':
                popen_kw['start_new_session'] = True     # a group _kill_tree can reach
            proc = subprocess.Popen([fxr, '--config', cdw, '--no-browser',
                                     '--port', str(xport)],
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, **popen_kw)
            try:
                xurl = 'http://127.0.0.1:%d/' % xport
                page = None
                for _ in range(120):
                    if proc.poll() is not None:
                        break
                    try:
                        page = urllib.request.urlopen(xurl, timeout=5).read().decode('utf-8')
                        break
                    except Exception:
                        time.sleep(0.5)
                t.check('the exe serves app.html out of its own bundle, with the '
                        'token substituted',
                        bool(page) and '__CKF_TOKEN__' not in page,
                        'exit %s' % proc.poll() if page is None else page[:200])
                mtok = re.search(r"TOKEN\s*=\s*'([^']+)'", page or '')
                t.check('the served page carries a session token', bool(mtok),
                        (page or '')[:200])
                if mtok:
                    xreq = urllib.request.Request(
                        xurl + 'api/model', headers={'X-CKF-Token': mtok.group(1)})
                    jm = json.loads(urllib.request.urlopen(
                        xreq, timeout=CHECK_SCHEMA_TIMEOUT + 180).read().decode('utf-8'))
                    t.check('/api/model from the exe carries every schema field',
                            jm['fieldCount'] == sum(len(sc['fields']) for sc in appz.schemas),
                            jm.get('fieldCount'))
                    t.check('the exe validated through its own re-entry and the '
                            'result is complete', jm['check']['ran'], jm['check'])
                    t.check('the exe read docs/mission-reference.json out of the bundle',
                            jm['missionReference']['state'] == 'loaded',
                            jm['missionReference'])
                    # config-surface spec, "The frozen exe defaults to the
                    # directory it runs from": the answer is where the exe
                    # sits, and it is not the hardcoded Steam path. Asserted
                    # end to end, through the running exe's own /api/model,
                    # rather than by calling default_game_dir() in this
                    # process -- section 18 does that, and it cannot see what a
                    # PyInstaller build actually resolves sys.executable to.
                    _norm = lambda p: os.path.normcase(os.path.abspath(p))
                    t.check('the frozen exe defaults to the directory it ran '
                            'from, not the hardcoded Steam path',
                            _norm(jm['defaultGameDir'] or '') == _norm(exedir)
                            and _norm(jm['defaultGameDir'] or '') != _norm(DEFAULT_GAME_DIR),
                            (jm.get('defaultGameDir'), exedir, DEFAULT_GAME_DIR))
                t.check('the exe writes its settings beside itself, not into a '
                        'bundle that is deleted on exit',
                        os.path.exists(want_settings),
                        sorted(os.listdir(exedir)))
            finally:
                died = _kill_tree(proc)
                alive = _procs_settle(fxr, exclude=before or ())
                gone = _rmtree_retry(exedir, tries=60)

            # The process question is asked of the OS, not of the Popen handle.
            # `died` only says this process reaped the child it owns; the
            # application the bootloader launched is a grandchild it cannot
            # see, and believing `died` is what let the second version of this
            # pass while the exe was still running. [David, 2026-09-04]
            t.check('no process is left running from the exe copy — a one-file '
                    'exe is two processes and terminate() reaches only the '
                    'bootloader',
                    alive == [],
                    'could not look for them' if alive is None
                    else 'still running 30s after the kill: %s (own handle '
                         'reaped: %s; %s)'
                         % (alive, died,
                            'baseline before launch: %s' % (before,)
                            if before is not None
                            else 'NO BASELINE — _procs_from could not look '
                                 'before the launch either, so an unrelated '
                                 'process of the same name would land here'))

            # The delete is a SEPARATE question, and on Windows it is the one
            # that can be answered by something other than this suite: a
            # just-executed exe is routinely held open for a moment by
            # antivirus or the search indexer. So it is a failure only when a
            # process really did survive; otherwise it is reported NOT RUN with
            # the path, because passing it would claim a sample this machine
            # did not take. On POSIX it cannot fail at all -- a running binary
            # unlinks fine there [measured 2026-09-04].
            if gone:
                t.check('and the directory it ran from could be deleted', True)
            elif alive == []:
                t.skip('the directory the exe ran from could be deleted',
                       'nothing is running from it any more, so the handle is '
                       'external to this suite — antivirus or the search '
                       'indexer on a just-executed exe. Left behind, delete it '
                       'when convenient: %s' % exedir)
            else:
                t.check('and the directory it ran from could be deleted', False,
                        exedir)


    # ---- 17. where --selftest gets its fixtures
    #
    # This is startup, before any case runs, and it is where `--selftest` with
    # no `--config` died on every machine that is not a cloud session's
    # assembled tree: `<repo>/live-config` was the unconditional default and
    # `shutil.copytree` raised FileNotFoundError out of section 2. Reported by
    # David, 2026-09-04, on the Phase 5 Windows run.
    print('\n[17] where --selftest gets its fixtures')
    with tempfile.TemporaryDirectory() as td:
        fake_repo = os.path.join(td, 'repo')
        staged = os.path.join(fake_repo, 'live-config')
        game = os.path.join(td, 'game')
        gcfg = os.path.join(game, 'BepInEx', 'config')
        os.makedirs(staged)
        os.makedirs(gcfg)
        settings = os.path.join(fake_repo, 'settings.json')
        with open(settings, 'w', encoding='utf-8') as f:
            json.dump({'gameDir': game, 'configDirOverride': None}, f)
        asked = os.path.join(td, 'asked')
        os.makedirs(asked)

        # Every call goes through _src. selftest_source raises SystemExit by
        # design when it finds nothing, and a case that calls it bare turns a
        # regression into a dead run: the first sweep of this section removed
        # the settings.json fallback, the suite exited mid-case, and no FAIL
        # line was printed at all. The sweep read that as "fault not caught",
        # and a person would have read it as a crash rather than as a named
        # failure. A check whose own setup can kill the suite is not a check.
        def _src(arg):
            try:
                got, how = selftest_source(arg)
                return got, how, None
            except SystemExit as e:
                return None, None, e

        with _paths(fake_repo, settings):
            got, _how, err = _src(asked)
            t.check('--config wins, even with both fallbacks available',
                    got == os.path.abspath(asked), err or got)
            got, how, err = _src(None)
            t.check('with no --config the staged copy beside the checkout is used',
                    got == staged and 'staged' in (how or ''), err or (got, how))
            shutil.rmtree(staged)
            got, how, err = _src(None)
            t.check('with no staged copy the game config from settings.json is '
                    'used — the case that was a FileNotFoundError until 2026-09-04',
                    got == os.path.abspath(gcfg) and 'settings.json' in (how or ''),
                    err or (got, how))
            shutil.rmtree(gcfg)
            got, _how, err = _src(None)
            t.check('with neither, it exits saying what it looked for, not with '
                    'a traceback out of copytree',
                    err is not None and 'no config to copy fixtures from' in str(err)
                    and staged in str(err), err or got)
            t.check('and the message names the game config it could not find too',
                    err is not None and game in str(err), err or got)

    # ---- 18. the game directory the editor starts from
    #
    # A fresh install opened with an empty game-folder box. The zip does not
    # carry the settings file, so the default should have applied -- but
    # setdefault only fills an ABSENT key, and a settings file left over beside
    # the exe carried "gameDir": "", which is what clearing the box writes.
    # Blank survived every restart and every re-extract. Reported by David,
    # 2026-09-07.
    print('\n[18] the game directory the editor starts from')
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, 'settings.json')

        def _load(payload):
            if payload is None:
                if os.path.exists(sp):
                    os.remove(sp)
            else:
                with open(sp, 'w', encoding='utf-8') as f:
                    json.dump(payload, f)
            with _paths(REPO, sp):
                return load_settings()

        kept = os.path.join(td, 'elsewhere')
        t.check('no settings file at all starts at the default',
                _load(None)['gameDir'] == default_game_dir(), _load(None)['gameDir'])
        t.check('a settings file with no gameDir key starts at the default',
                _load({'configDirOverride': None})['gameDir'] == default_game_dir())
        t.check('a blank gameDir is the same state as an absent one — the case '
                'that opened the editor with an empty box',
                _load({'gameDir': '', 'configDirOverride': None})['gameDir']
                == default_game_dir(),
                _load({'gameDir': ''})['gameDir'])
        t.check('whitespace counts as blank',
                _load({'gameDir': '   '})['gameDir'] == default_game_dir())
        t.check('a chosen directory is left exactly as it is',
                _load({'gameDir': kept})['gameDir'] == kept,
                _load({'gameDir': kept})['gameDir'])
        t.check('a blank gameDir with an override still gets a default, and the '
                'override still wins',
                config_dir_for(_load({'gameDir': '', 'configDirOverride': td})) == td)

        # The frozen half. EXE_DIR is None unfrozen, so these swap it.
        game = os.path.join(td, 'game')
        loose = os.path.join(td, 'downloads')
        os.makedirs(game)
        os.makedirs(loose)
        with _exe_at(loose):
            t.check('an exe with no %s beside it does not name its own folder' % GAME_MARKER,
                    default_game_dir() == DEFAULT_GAME_DIR, default_game_dir())
        with open(os.path.join(game, GAME_MARKER), 'w') as f:
            f.write('')
        with _exe_at(game):
            t.check('an exe extracted into the game folder starts there, not at '
                    'the hardcoded C: path',
                    default_game_dir() == game, default_game_dir())
            t.check('and a blank gameDir picks that up',
                    _load({'gameDir': ''})['gameDir'] == game,
                    _load({'gameDir': ''})['gameDir'])
        t.check('unfrozen there is no exe to reason from',
                default_game_dir() == DEFAULT_GAME_DIR, default_game_dir())


    # ---- 19. the 3.x -> 4.0 migrator
    #
    # THE SUBJECT IS A REAL SHIPPED 3.x INSTALL, NOT A RECONSTRUCTION:
    # tests/fixture-3.0.0/, extracted from dist/CKF-Hard-Mode-1.0.0.zip. Its
    # three files are the migrator's whole input and they are never written to
    # -- every case copies them into a temp directory first.
    #
    # THE COMPARISON IS AGAINST THE LIVE 4.0 LAYOUT, and its SIZE IS REPORTED.
    # A migrator selftest that compares two empty directories and prints no
    # differences is the failure this section exists to be incapable of: the
    # file count and the byte count are asserted to be the real ones before any
    # difference count is believed.
    print('\n[19] the 3.x -> 4.0 migrator')

    # RETIRED FROM THE DEFAULT SUITE, 2026-09-15. See migration_report_retired
    # and the banner above it for the ruling, what this block caught, and why
    # its premise lapsed. `--migration` runs every case below UNCHANGED -- not
    # one byte of section 19 moved for this retirement, which is what makes the
    # opt-in the same check and not a reconstruction of it. Section 19 is the
    # last thing selftest() does, so the guard is an early return rather than a
    # re-indent of 500 lines that would have to be re-read to be believed.
    if not migration:
        migration_report_retired(t)
        return t.report('gui/serve.py verification')

    FIXTURE = os.path.join(REPO, 'tests', 'fixture-3.0.0')

    def _mig_sandbox(td, name, cfg_bytes=None, carried=True, seed_4x=None,
                     backup=None):
        """A 3.x install under `td`. Copies; the fixture is never written to."""
        cd = os.path.join(td, name)
        os.makedirs(os.path.join(cd, MIGRATION_DIR))
        for n in MIGRATION_INPUTS:
            shutil.copy2(os.path.join(FIXTURE, n), os.path.join(cd, n))
        if cfg_bytes is not None:
            with open(os.path.join(cd, 'ckf.hardmode.cfg'), 'wb') as fh:
                fh.write(cfg_bytes)
        if carried:
            for n in MIGRATION_CARRIED:
                shutil.copy2(os.path.join(src, MIGRATION_DIR, n),
                             os.path.join(cd, MIGRATION_DIR, n))
        if seed_4x:
            with open(os.path.join(cd, MIGRATION_DIR, seed_4x), 'w') as fh:
                fh.write('{}')
        if backup:
            with open(os.path.join(cd, backup + MIGRATION_BACKUP_SUFFIX), 'wb') as fh:
                fh.write(b'an earlier backup nothing may overwrite')
        return cd

    class _mig_fault(object):
        """Set MIGRATION_FAULT for one block. Faults land in the CONVERSION,
        never in the fixture: a fault injected into the source would move both
        sides of the comparison equally and stay green."""

        def __init__(self, name):
            self.name = name

        def __enter__(self):
            global MIGRATION_FAULT
            MIGRATION_FAULT = self.name

        def __exit__(self, *_a):
            global MIGRATION_FAULT
            MIGRATION_FAULT = None

    def _mig_diff(files):
        """-> (identical, [ (rel, live_len, new_len) ]), against the live 4.0
        layout `src` was copied from."""
        same, diffs = 0, []
        for rel in sorted(files):
            p = os.path.join(src, rel)
            if not os.path.exists(p):
                diffs.append((rel, None, len(files[rel])))
                continue
            live = read_bytes(p)
            if live == files[rel]:
                same += 1
            else:
                diffs.append((rel, len(live), len(files[rel])))
        return same, diffs

    # -- 19a. the fixture is the artefact design.md section 13 describes.
    _fix_rules_raw = read_bytes(os.path.join(FIXTURE, 'ckf.hardmode.rules.json'))
    _fix_text = _fix_rules_raw.decode('utf-8-sig')
    _fix_rules = json.loads(migration_strip_jsonc(_fix_text))['rules']
    _shapes = {'exact': 0, 'range': 0, 'unscoped': 0}
    _by_model, _nonexact = {}, {}
    for _r in _fix_rules:
        _s = migration_selector(_r)
        _shapes[_s] += 1
        _by_model[_r['model']] = _by_model.get(_r['model'], 0) + 1
        if _s != 'exact':
            _nonexact[_r['model']] = _nonexact.get(_r['model'], 0) + 1
    t.check('the fixture is JSONC: json.loads throws on it unstripped',
            _raises(lambda: json.loads(_fix_text), ValueError))
    t.check('fixture: 82,478 bytes, 3,161 lines, 76 // comment lines',
            (len(_fix_rules_raw), _fix_text.count('\n') + 1,
             sum(1 for l in _fix_text.split('\n') if l.strip().startswith('//')))
            == (82478, 3161, 76),
            (len(_fix_rules_raw), _fix_text.count('\n') + 1))
    t.check('fixture: 287 rules = 263 exact + 24 range/unscoped',
            len(_fix_rules) == 287 and _shapes['exact'] == 263
            and _shapes['range'] + _shapes['unscoped'] == 24, _shapes)
    t.check('fixture non-exact by model: WeaponModel 17, TalentModel 5, '
            'ImplantModel 1, MonsterTypeModel 1',
            _nonexact == {'WeaponModel': 17, 'TalentModel': 5,
                          'ImplantModel': 1, 'MonsterTypeModel': 1}, _nonexact)
    t.check('the fixture ckf.hardmode.json is 40,865 bytes',
            os.path.getsize(os.path.join(FIXTURE, 'ckf.hardmode.json')) == 40865)
    t.check('the fixture .cfg is the 172-byte one-key file, before the 43-key layout',
            os.path.getsize(os.path.join(FIXTURE, 'ckf.hardmode.cfg')) == 172)

    # -- 19b. WHICH MonsterTypeModel. The trap design.md section 13 calls the
    # most load-bearing decision in the change, measured both ways here so the
    # two numbers are in the report rather than in a comment.
    def _ptr_census(path):
        with open(path, newline='', encoding='utf-8-sig') as fh:
            rows = list(csv.DictReader(fh))
        ids = set(int(r[MIGRATION_POINTER_COLUMN]) for r in rows
                  if (r[MIGRATION_POINTER_COLUMN] or '').strip())
        with open(os.path.join(migration_dump_dir(), 'WeaponModel.csv'),
                  newline='', encoding='utf-8-sig') as fh:
            weapons = list(csv.DictReader(fh))
        p = sum(1 for w in weapons if int(w['WeaponClass']) == 3
                and int(w['WeaponId']) not in ids)
        e = sum(1 for w in weapons if int(w['WeaponClass']) == 3
                and int(w['WeaponId']) in ids)
        return len(ids), p, e

    _post = _ptr_census(os.path.join(src, MIGRATION_DIR, MIGRATION_POINTER_FILE))
    _ship = _ptr_census(os.path.join(migration_dump_dir(), MIGRATION_POINTER_FILE))
    t.check('post-overlay ckf.hardmode.d/MonsterTypeModel.csv: 405 distinct '
            'WeaponTypeId, class 3 = 33 player / 43 enemy',
            _post == (405, 33, 43), _post)
    t.check('shipped sheets/raw/MonsterTypeModel.csv: 208 distinct WeaponTypeId, '
            'class 3 = 25 player / 51 enemy -- eight player ARs misclassified',
            _ship == (208, 25, 51), _ship)
    t.check('the two readings really do disagree, so the choice is not cosmetic',
            _post[1] - _ship[1] == 8, (_post, _ship))

    # THE STAMP THE CONVERSION WRITES, CHECKED AGAINST THE C# AND NOT AGAINST
    # ITSELF. MIGRATION_DOC_VERSION is a literal in this file; DocVersion is a
    # literal in mods/CKFHardMode/Defaults.cs. Nothing derives one from the
    # other, so this is a real comparison and not two readings of one source.
    # NOT RUN, never PASS, when Defaults.cs is absent -- that is the frozen exe,
    # whose _MEIPASS holds no mods/ tree.
    _defaults_cs = os.path.join(REPO, 'mods', 'CKFHardMode', 'Defaults.cs')
    if not os.path.exists(_defaults_cs):
        t.skip('the stamp the migration writes is Defaults.DocVersion',
               'no %s -- this is the frozen exe and it bundles no mods/ tree'
               % _defaults_cs)
    else:
        _dv = re.search(r'DocVersion\s*=\s*"([^"]+)"',
                        read_bytes(_defaults_cs).decode('utf-8'))
        t.check('the stamp the migration writes is Defaults.DocVersion, so a '
                'migrated install is not born reporting all ten slices behind',
                bool(_dv) and _dv.group(1) == MIGRATION_DOC_VERSION,
                ('MIGRATION_DOC_VERSION=%r' % MIGRATION_DOC_VERSION,
                 'Defaults.cs DocVersion=%r' % (_dv and _dv.group(1))))

    # THE STAMP THE CONVERSION PUTS IN THE .cfg HEADER, CHECKED THE SAME WAY.
    # MIGRATION_PLUGIN_VERSION is a literal in this file; PluginVersion is a
    # literal in mods/CKFHardMode/Plugin.cs, and BepInEx writes PluginVersion
    # into the header of every player's ckf.hardmode.cfg. Nothing derives one
    # from the other. NOT RUN, never PASS, when Plugin.cs is absent -- that is
    # the frozen exe, whose _MEIPASS holds no mods/ tree.
    _plugin_cs = os.path.join(REPO, 'mods', 'CKFHardMode', 'Plugin.cs')
    if not os.path.exists(_plugin_cs):
        t.skip('the version the migration stamps the .cfg header with is '
               'Plugin.PluginVersion',
               'no %s -- this is the frozen exe and it bundles no mods/ tree'
               % _plugin_cs)
    else:
        _pv = re.search(r'PluginVersion\s*=\s*"([^"]+)"',
                        read_bytes(_plugin_cs).decode('utf-8'))
        t.check('the version the migration stamps the .cfg header with is '
                'Plugin.PluginVersion, so a migrated .cfg does not announce '
                'the version it was converted FROM',
                bool(_pv) and _pv.group(1) == MIGRATION_PLUGIN_VERSION,
                ('MIGRATION_PLUGIN_VERSION=%r' % MIGRATION_PLUGIN_VERSION,
                 'Plugin.cs PluginVersion=%r' % (_pv and _pv.group(1))))

    with tempfile.TemporaryDirectory() as td:
        # -- 19c. the migration itself, run into a temp directory.
        cd = _mig_sandbox(td, 'convert')
        mig = run_migration(cd)
        _files, _bytes = len(mig.files), mig.bytes_total()
        _live_bytes = sum(os.path.getsize(os.path.join(src, r)) for r in mig.files)
        _same, _diffs = _mig_diff(mig.files)
        _carried_n = sum(1 for r in mig.source.values() if r == 'carried')
        _smallest = min(len(b) for b in mig.files.values())
        print('      compared %d file(s), %d byte(s) produced against %d byte(s) '
              'on the live 4.0 layout; %d identical, %d differ (%d of the %d are '
              'carried through unchanged and are identity by construction)'
              % (_files, _bytes, _live_bytes, _same, len(_diffs), _carried_n, _files))
        t.check('the migration produced %d files -- 67 under %s plus the .cfg'
                % (MIGRATION_EXPECTED_FILES, MIGRATION_DIR),
                _files == MIGRATION_EXPECTED_FILES
                and sum(1 for r in mig.files
                        if r.startswith(MIGRATION_DIR + '/')) == 67,
                _files)
        # THE CASE THAT PROVES THE COMPARISON HAS A SUBJECT. A floor and a
        # no-empty-file check, not a typed-in total: the total moved today
        # (586,634 -> 585,504) when scripts/implants.py stopped carrying a
        # column, and a literal here would fail for the wrong reason on every
        # future re-dump. What must survive is the proof that this is a real
        # layout and not an empty directory, and it does.
        t.check('every one of the %d files carries bytes and the layout is at '
                'least %d of them (measured: %d) -- so the comparison below '
                'cannot be over an empty directory'
                % (_files, MIGRATION_MIN_BYTES, _bytes),
                _smallest > 0 and _bytes >= MIGRATION_MIN_BYTES,
                (_smallest, _bytes))
        # Stronger than any literal, and impossible to type in wrong: the size
        # is measured on BOTH sides and has to agree.
        t.check('the produced layout and the live layout are the same size to '
                'the byte (%d == %d), measured on both sides' % (_bytes, _live_bytes),
                _bytes == _live_bytes, (_bytes, _live_bytes))
        t.check('the comparison actually read a live file for all %d' % _files,
                all(os.path.exists(os.path.join(src, r)) for r in mig.files))
        t.check('%d of the %d are byte-identical to the live 4.0 layout'
                % (MIGRATION_EXPECTED_FILES, MIGRATION_EXPECTED_FILES),
                _same == MIGRATION_EXPECTED_FILES, [d[0] for d in _diffs])
        t.check('nothing differs at all -- the declared divergence set is empty '
                'and the measured one equals it',
                not _diffs, [d[0] for d in _diffs])
        # THE THREE FILES THAT USED TO DIFFER. Restated, not deleted: they are
        # the record of a real defect this instrument found, and a case that
        # names what it used to measure is what stops the finding from being
        # re-discovered.
        for _rel, (_col, _model) in sorted(MIGRATION_CLOSED_DIVERGENCES.items()):
            t.check('%s is byte-identical -- it DIFFERED by exactly one column '
                    '(%s.%s) until scripts/implants.py gained '
                    'EFFECT_PRESENTATION on %s'
                    % (os.path.basename(_rel), _model, _col,
                       MIGRATION_DIVERGENCES_CLOSED_ON),
                    mig.files[_rel] == read_bytes(os.path.join(src, _rel)),
                    (len(mig.files[_rel]),
                     os.path.getsize(os.path.join(src, _rel))))
        # The retired bound, and its live successor.
        t.check('the one-column divergence check is retired and REFUSES rather '
                'than answering False over a subject that no longer exists',
                _raises(lambda: migration_divergence_is_one_column(b'', b'', 'x'),
                        RuntimeError))
        _decl, _indump, _scanned, _hits = migration_presentation_columns(mig.files)
        t.check('all %d names scripts/implants.py declares presentation-only are '
                'in the EffectModel dump header, so the exclusion has a subject'
                % len(_decl), len(_indump) == len(_decl) and _decl,
                [c for c in _decl if c not in _indump])
        t.check('and none of them reaches any of the %d generated overlay '
                'headers -- the tripwire that fires if the exclusion is dropped '
                'or the next re-dump adds a column that slips through' % _scanned,
                _scanned >= 56 and not _hits, _hits)

        # -- 19d. what the directory looks like afterwards.
        t.check('ckf.hardmode.json is gone from the top of the config',
                not os.path.exists(os.path.join(cd, 'ckf.hardmode.json')))
        t.check('ckf.hardmode.rules.json is gone from the top of the config',
                not os.path.exists(os.path.join(cd, 'ckf.hardmode.rules.json')))
        t.check('both originals are renamed to %s, byte for byte'
                % MIGRATION_BACKUP_SUFFIX,
                all(read_bytes(os.path.join(cd, n + MIGRATION_BACKUP_SUFFIX))
                    == read_bytes(os.path.join(FIXTURE, n))
                    for n in MIGRATION_INPUTS[:2]))
        t.check('%s holds 67 files' % MIGRATION_DIR,
                len(os.listdir(os.path.join(cd, MIGRATION_DIR))) == 67,
                len(os.listdir(os.path.join(cd, MIGRATION_DIR))))
        t.check('no journal is left behind',
                not os.path.exists(journal_path(cd)))
        t.check('the converted install is not in ConfigDoc.BothLayouts state',
                not any(os.path.exists(os.path.join(cd, n))
                        for n in MIGRATION_INPUTS[:2]))

        # -- 19e. D1. A positive measurement, never an inferred absence.
        t.check('D1: the fixture carries 1 MonsterTypeModel rule (PL 11+, '
                'ChasingSpeed and AggroSpeed x1.1)',
                mig.measured['D1']['rules_in'] == 1
                and mig.measured['D1']['operands'] == ['AggroSpeed', 'ChasingSpeed'],
                mig.measured['D1'])
        _d1_files = [r for r in mig.files
                     if os.path.basename(r).startswith(D1_MODEL + '.')
                     and mig.source[r] != 'carried']
        t.check('D1: it converts to NOTHING -- 0 files written for that model '
                '(the one MonsterTypeModel.csv on disk is the carried-through '
                'enemy-gear overlay, which this conversion does not author)',
                mig.measured['D1']['files_out'] == 0 and not _d1_files, _d1_files)
        t.check('D1: MonsterTypeModel.csv is the carried-through file, unchanged',
                mig.source['%s/MonsterTypeModel.csv' % MIGRATION_DIR] == 'carried'
                and mig.files['%s/MonsterTypeModel.csv' % MIGRATION_DIR]
                == read_bytes(os.path.join(src, MIGRATION_DIR, 'MonsterTypeModel.csv')))
        t.check('D1: no output file names ChasingSpeed or AggroSpeed at all',
                not [r for r, b in mig.files.items()
                     if b'ChasingSpeed' in b or b'AggroSpeed' in b],
                [r for r, b in mig.files.items()
                 if b'ChasingSpeed' in b or b'AggroSpeed' in b])

        # -- 19f. D2 + D4.
        _gc = mig.files['%s/gear-classes.csv' % MIGRATION_DIR]
        _gc_rows = list(csv.reader(io.StringIO(_gc.decode('utf-8'))))
        _starred = [r[0] for r in _gc_rows[1:]
                    if r[_gc_rows[0].index('RecoilRate2')] == '*1.8']
        t.check('D2+D4: the fixture carries 16 WeaponModel RecoilRate2 id ranges',
                mig.measured['D2D4']['ranges_in'] == 16, mig.measured['D2D4'])
        t.check('D2+D4: they become 10 gear-classes.csv rows, not 16 transcribed '
                'ranges', len(_gc_rows) - 1 == 10, len(_gc_rows) - 1)
        t.check('D2+D4: RecoilRate2 *1.8 lands on the four dual-mode player '
                'classes 3, 5, 10 and 12 -- derived from the partition, not listed',
                _starred == ['3', '5', '10', '12'], _starred)
        t.check('D2+D4: the partition was resolved from the post-overlay file, '
                '405 pointer ids over 2,427 rows',
                (mig.measured['pointer_ids'], mig.measured['pointer_rows'])
                == (405, 2427)
                and mig.measured['pointer_file'].startswith(cd),
                (mig.measured['pointer_ids'], mig.measured['pointer_file']))
        t.check('D2+D4: class 3 resolves to 33 player rows, all 33 with a live '
                'RecoilRate2', mig.measured['gear_partition'][3] == (33, 33),
                mig.measured['gear_partition'][3])
        t.check('D2+D4: gear-classes.csv is byte-identical to the shipping sheet',
                _gc == read_bytes(os.path.join(src, MIGRATION_DIR, 'gear-classes.csv')))

        # -- 19g. D3.
        _glob = json.loads(
            mig.files['%s/implants-global.json' % MIGRATION_DIR].decode('utf-8'))
        t.check('D3: the fixture\'s unscoped ImplantModel rule DOES carry '
                'clampMin ImplantStress 1', mig.measured['D3']['in_source'] is True,
                mig.measured['D3'])
        t.check('D3: implants-global.json is written with THREE numbers, not four',
                sorted(k for k in _glob if not k.startswith('_'))
                == ['costMultiply', 'implantStressMultiply', 'installTimeMultiply'],
                sorted(_glob))
        t.check('D3: the three carry the rule\'s own operands, 0.5 / 0.5 / 3',
                (_glob['costMultiply'], _glob['installTimeMultiply'],
                 _glob['implantStressMultiply']) == (0.5, 0.5, 3),
                (_glob['costMultiply'], _glob['installTimeMultiply'],
                 _glob['implantStressMultiply']))
        # Read as OPERANDS, not as text: implants-global.json's own _doc
        # explains at length why the floor is not carried, and a byte search
        # would score that explanation as the floor coming back.
        _clamped = []
        for _rel, _b in sorted(mig.files.items()):
            if _rel.endswith('.csv'):
                _h = next(csv.reader(io.StringIO(_b.decode('utf-8'))), [])
                _clamped += ['%s %s' % (_rel, c) for c in _h
                             if c.endswith('>') or c.endswith('<')]
            elif _rel.endswith('.json'):
                _o = json.loads(_b.decode('utf-8'))
                if isinstance(_o, dict):
                    _clamped += ['%s %s' % (_rel, k) for k in _o
                                 if not k.startswith('_') and 'lamp' in k]
        t.check('D3: no output file carries a clamp OPERAND anywhere -- no CSV '
                'header cell with a > or < operator suffix, no settings key '
                'naming a clamp', not _clamped, _clamped)

        # -- 19h. the .cfg.
        _cfg = mig.files['ckf.hardmode.cfg']
        _keys = re.findall(rb'^([A-Za-z]\w*) = (\S+)', _cfg, re.M)
        t.check('the .cfg goes from 1 key to 43',
                len(_keys) == 43 and len(re.findall(
                    rb'^([A-Za-z]\w*) = ', read_bytes(
                        os.path.join(FIXTURE, 'ckf.hardmode.cfg')), re.M)) == 1,
                len(_keys))
        t.check('the .cfg is byte-identical to the shipping one',
                _cfg == read_bytes(os.path.join(src, 'ckf.hardmode.cfg')))
        # RESTATED, 2026-09-15. This read `_cfg.startswith(<the fixture>)`,
        # which asserted the 3.x file survived byte for byte INCLUDING its
        # header line -- and that line is the one token the converter now
        # restamps. Weakening it to a prefix match below the header would have
        # lost the claim, so it is split into the two claims it was really
        # making: everything below the header line is untouched, and the header
        # line differs in the version token and in NOTHING else. The fixture's
        # own version is read back out of the fixture rather than typed here,
        # and the case requires the two to actually differ, so a fixture bumped
        # to 4.0.0 would make this case fail rather than pass vacuously.
        _fixcfg = read_bytes(os.path.join(FIXTURE, 'ckf.hardmode.cfg'))
        _fix_h, _, _fix_rest = _fixcfg.partition(b'\n')
        _cfg_h, _, _cfg_rest = _cfg.partition(b'\n')
        _fh = _MIGRATION_CFG_HEADER.match(_fix_h.rstrip(b'\r'))
        _want_h = (_fh and _fh.group(1)
                   + MIGRATION_PLUGIN_VERSION.encode('utf-8') + _fh.group(3))
        t.check('the 3.x file survives byte for byte below the header line, '
                'and the header line differs ONLY in the version token '
                '(fixture v%s -> v%s)'
                % (_fh and _fh.group(2).decode('ascii'),
                   MIGRATION_PLUGIN_VERSION),
                bool(_fh)
                and _fh.group(2) != MIGRATION_PLUGIN_VERSION.encode('utf-8')
                and _cfg_rest.startswith(_fix_rest)
                and _cfg_h.rstrip(b'\r') == _want_h
                and _cfg_h.endswith(b'\r') == _fix_h.endswith(b'\r'),
                (_cfg_h, _fix_h))
        t.check('Slices.SelfCheck carries its declared default of false, not a '
                'blanket true', (b'SelfCheck', b'false') in _keys,
                [k for k in _keys if k[0] == b'SelfCheck'])

    # -- 19i. the .cfg value a player actually set is carried across, not
    # rebuilt. Run on a fixture copy with the mod switched OFF.
    with tempfile.TemporaryDirectory() as td:
        _off = read_bytes(os.path.join(FIXTURE, 'ckf.hardmode.cfg')).replace(
            b'Enabled = true', b'Enabled = false')
        cd = _mig_sandbox(td, 'off', cfg_bytes=_off)
        m2 = build_migration(cd)
        t.check('a 3.x .cfg with Enabled = false converts to a 4.0 .cfg with '
                'Enabled = false', b'Enabled = false' in m2.files['ckf.hardmode.cfg']
                and b'Enabled = true' not in m2.files['ckf.hardmode.cfg'],
                m2.files['ckf.hardmode.cfg'][:200])
        # AND THE STAMP DID NOT COST THE CARRY. Same conversion, read for the
        # header: v1.0.0 in, MIGRATION_PLUGIN_VERSION out, Enabled = false
        # still false. The two claims are on one subject on purpose -- the
        # defect this guards against is a header rewrite that rebuilds the
        # block under it.
        t.check('and its header is restamped to v%s while Enabled = false is '
                'carried -- the stamp rewrites the version token, not the '
                'block below it' % MIGRATION_PLUGIN_VERSION,
                m2.files['ckf.hardmode.cfg'].split(b'\n')[0].rstrip(b'\r')
                == b'## Settings file was created by plugin CKF Hard Mode v'
                   + MIGRATION_PLUGIN_VERSION.encode('utf-8'),
                m2.files['ckf.hardmode.cfg'].split(b'\n')[0])

    # -- 19i-2. a header line this converter cannot read is a REFUSAL, not a
    # rewrite and not an append. A .cfg announcing a version other than the
    # running plugin's is the defect the stamp removes; guessing what a
    # stranger first line wants would put it straight back.
    with tempfile.TemporaryDirectory() as td:
        _bad = read_bytes(os.path.join(FIXTURE, 'ckf.hardmode.cfg')).replace(
            b'## Settings file was created by plugin CKF Hard Mode v1.0.0',
            b'## hand-edited, header line removed', 1)
        cd = _mig_sandbox(td, 'badhdr', cfg_bytes=_bad)
        t.check('a 3.x .cfg whose first line is not the BepInEx header is a '
                'refusal -- the version token has nothing to replace and '
                'nothing is written',
                _raises(lambda: build_migration(cd), MigrationRefused))
        # The shape IS the whole test: same file, header restored, converts.
        cd = _mig_sandbox(td, 'goodhdr')
        t.check('and the identical fixture WITH the header line converts, so '
                'the refusal above is the header and not the sandbox',
                b'[Slices]' in build_migration(cd).files['ckf.hardmode.cfg'])

    # -- 19j. the refusals. Each one is a refusal that WROTE NOTHING.
    with tempfile.TemporaryDirectory() as td:
        cd = _mig_sandbox(td, 'nojson')
        os.remove(os.path.join(cd, 'ckf.hardmode.json'))
        t.check('a missing 3.x input is a refusal, not a partial conversion',
                _raises(lambda: build_migration(cd), MigrationRefused))
        cd = _mig_sandbox(td, 'both', seed_4x='difficulty.json')
        t.check('a directory already carrying the 4.0 layout is refused '
                '(ConfigDoc.BothLayouts)',
                _raises(lambda: build_migration(cd), MigrationRefused))
        cd = _mig_sandbox(td, 'hasbak', backup='ckf.hardmode.json')
        _bak = os.path.join(cd, 'ckf.hardmode.json' + MIGRATION_BACKUP_SUFFIX)
        _before = read_bytes(_bak)
        t.check('an existing %s is refused rather than overwritten'
                % MIGRATION_BACKUP_SUFFIX,
                _raises(lambda: run_migration(cd), MigrationRefused))
        t.check('and the existing backup is still byte for byte what it was',
                read_bytes(_bak) == _before)
        t.check('and the refusal wrote no slice files',
                not os.listdir(os.path.join(cd, MIGRATION_DIR)) or
                sorted(os.listdir(os.path.join(cd, MIGRATION_DIR)))
                == sorted(MIGRATION_CARRIED),
                os.listdir(os.path.join(cd, MIGRATION_DIR)))
        cd = _mig_sandbox(td, 'noptr')
        os.remove(os.path.join(cd, MIGRATION_DIR, MIGRATION_POINTER_FILE))
        t.check('an unreadable ckf.hardmode.d/MonsterTypeModel.csv is a refusal, '
                'NOT a fallback to sheets/raw -- the same choice GearClasses.cs '
                'makes', _raises(lambda: build_migration(cd), MigrationRefused))
        cd = _mig_sandbox(td, 'blankptr')
        _p = os.path.join(cd, MIGRATION_DIR, MIGRATION_POINTER_FILE)
        _lines = read_bytes(_p).split(b'\n')
        _hdr = _lines[0].decode().split(',')
        _i = _hdr.index(MIGRATION_POINTER_COLUMN)
        _cells = _lines[1].decode().split(',')
        _cells[_i] = ''
        _lines[1] = ','.join(_cells).encode()
        with open(_p, 'wb') as fh:
            fh.write(b'\n'.join(_lines))
        t.check('a MonsterTypeModel row with a blank %s is a refusal -- an '
                'incomplete partition is not a smaller one'
                % MIGRATION_POINTER_COLUMN,
                _raises(lambda: build_migration(cd), MigrationRefused))

    # -- 19k. FAULT INJECTION. Every case must go RED. A control run first, so
    # that a fault "caught" by a harness that was already failing is not read
    # as the fault being caught.
    with tempfile.TemporaryDirectory() as td:
        cd = _mig_sandbox(td, 'control')
        _ctrl = build_migration(cd)
        _cs, _cd_ = _mig_diff(_ctrl.files)
        t.check('control: with no fault injected the run is the green one -- '
                '%d of %d identical, nothing differing at all'
                % (MIGRATION_EXPECTED_FILES, MIGRATION_EXPECTED_FILES),
                _cs == MIGRATION_EXPECTED_FILES and not _cd_, (_cs, _cd_))

        def _red(fault, why):
            """-> (went_red, detail). Red is a refusal OR a difference beyond
            the three declared ones."""
            c = _mig_sandbox(td, 'f-' + fault)
            try:
                with _mig_fault(fault):
                    m = build_migration(c)
            except MigrationRefused as e:
                return True, 'refused: %s' % str(e).split('\n')[0][:110]
            same, diffs = _mig_diff(m.files)
            # Every difference is red now: the declared divergence set is
            # empty since 2026-09-14, so nothing is filtered out here.
            extra = [d[0] for d in diffs]
            missing = sorted(set(_ctrl.files) - set(m.files))
            added = sorted(set(m.files) - set(_ctrl.files))
            if extra or missing or added:
                return True, ('differs: %s%s%s'
                              % (extra, ' missing=%s' % missing if missing else '',
                                 ' added=%s' % added if added else ''))
            return False, 'GREEN over %d file(s) -- the fault was not caught' % same

        for _f, _why in MIGRATION_FAULTS:
            if _f == 'backup-clobber':
                # This one cannot be seen in the output files: the guard it
                # disables is the one that keeps an EXISTING backup. So the red
                # condition is the backup's own bytes moving, on a directory
                # that has one -- the same directory 19j proved is refused.
                _c = _mig_sandbox(td, 'f-backup', backup='ckf.hardmode.json')
                _bp = os.path.join(_c, 'ckf.hardmode.json'
                                   + MIGRATION_BACKUP_SUFFIX)
                _was = read_bytes(_bp)
                try:
                    with _mig_fault(_f):
                        run_migration(_c)
                except MigrationRefused:
                    pass
                ok = read_bytes(_bp) != _was
                detail = ('the existing backup was overwritten (%d -> %d bytes), '
                          'which is what the guard prevents'
                          % (len(_was), os.path.getsize(_bp))) if ok else \
                         ('GREEN -- the backup survived even with the guard off, '
                          'so 19j proved nothing')
            else:
                ok, detail = _red(_f, _why)
            t.check('fault %r goes red -- %s' % (_f, _why), ok, detail)
            print('           %s' % detail)
        t.check('MIGRATION_FAULT is back to None after the injections',
                MIGRATION_FAULT is None, MIGRATION_FAULT)

    return t.report('gui/serve.py verification')


UI_VALUES = {'form', 'table', 'curve', 'matrix', 'readonly', 'hidden'}
GENERIC_WORDS = {'enabled', 'name', 'type', 'note', 'table', 'value', 'row', 'col', 'default'}


# An assignment at the start of a line to an ALL-CAPS name, and the
# declarations that would make one legal. ALL-CAPS is app.html's own convention
# for a module-level binding, which is what makes this exact: a local is
# lowercase, and a property assignment carries a dot that the pattern does not
# match.
ASSIGN_CAPS_RE = re.compile(r'^[ \t]*([A-Z][A-Z0-9_]*)\s*=(?!=)', re.M)
DECLARE_CAPS_RE = re.compile(r'\b(?:let|const|var)\s+([A-Z][A-Z0-9_]*)\b')


def undeclared_globals_in_app_html(path=None):
    """ALL-CAPS names app.html assigns to and never declares. Should be empty.

    'use strict' makes one of these a ReferenceError the first time the line
    runs, and nothing about the file's syntax says so: `node --check` passes,
    --selftest-js passes, and the failure only appears in a browser. RETRO_OK
    outlived the retroactive confirm gate 3.0 deleted -- a write with no
    declaration and no reader -- and threw out of load() on every start, so the
    page came up with "Could not load the config -- ReferenceError: RETRO_OK is
    not defined" and nothing else. Reported by David, 2026-09-07.
    """
    with open(path or APP_HTML, encoding='utf-8') as f:
        src = f.read()
    declared = set(DECLARE_CAPS_RE.findall(src))
    return sorted({n for n in ASSIGN_CAPS_RE.findall(src) if n not in declared})


def hardcoded_names_in_app_html(schemas, path=None):
    """Schema names that appear as string literals in app.html. Should be empty."""
    with open(path or APP_HTML, encoding='utf-8') as f:
        src = f.read()
    names = set()
    for sch in schemas:
        # A target may be a LIST since Phase 4: `targets.overlays` names the
        # overlay CSVs a slice owns, two or three for a talent pack. This read
        # `names.add(t)` over the raw value and raised
        # `TypeError: unhashable type: 'list'` the moment the first list-valued
        # target landed -- not a failed case, a dead run [measured 2026-09-13].
        # A target may also be null: the four sections Phase 3 created declare
        # "legacyJson": null to say they never had a 2.x sidecar.
        for t in (sch.get('targets') or {}).values():
            for one in (t if isinstance(t, list) else [t]):
                if one:
                    names.add(one)
        for k in (sch.get('enable') or {}).values():
            if k:
                names.add(k)
        for fl in sch['fields']:
            names.add(fl['path'])
            if fl['in'] == 'cfg':
                names.add(fl['path'].split('.', 1)[1])
            for c in fl.get('row', []):
                names.add(c['name'])
            for k in (fl.get('axes') or {}).values():
                names.add(k)
    out = []
    for n in sorted(names):
        if n in GENERIC_WORDS or n in UI_VALUES or len(n) < 4:
            continue
        if re.search(r'["\'`]' + re.escape(n) + r'["\'`.\s]', src):
            out.append(n)
    return out


def _strict_json(path):
    try:
        json.loads(read_bytes(path).decode('utf-8-sig'))
        return True
    except Exception:
        return False


def _raises(fn, exc):
    try:
        fn()
    except exc:
        return True
    except Exception:
        return False
    return False


def _hashes_of(root, rels):
    """One digest per relative path, or None where the file is not there.

    "Not there" and "could not look" are different facts, so an absent file
    comes back as None rather than being left out of the map.
    """
    out = {}
    for rel in rels:
        p = os.path.join(root, rel)
        out[rel] = (hashlib.sha256(read_bytes(p)).hexdigest()
                    if os.path.exists(p) else None)
    return out


def _same(a, b):
    return os.path.exists(a) and os.path.exists(b) and read_bytes(a) == read_bytes(b)


def _walk_rel(root):
    """Every file under root, relative and forward-slashed. Used by the cases
    that assert a save leaves the config directory holding the config and
    nothing else."""
    out = []
    for base, _dirs, names in os.walk(root):
        for n in names:
            out.append(os.path.relpath(os.path.join(base, n), root).replace(os.sep, '/'))
    return sorted(out)


def _edits_for(schemas, model):
    """The edit set the browser sends when nothing has been touched: every
    value it was handed, sent straight back. The server writes only what
    differs from disk, so this is the shape a no-op save arrives in.

    SINCE 2026-09-14 THAT INCLUDES EVERY LEVER CELL OF EVERY WRITABLE SHEET.
    Before the write path opened, a no-op edit set reached no sheet at all, so
    "a no-op save moves no overlay byte" was true because nothing offered one.
    It now goes through the real writer -- key lookup, span replacement, the
    whole path -- with every cell set to the value it already holds, which is
    the only shape in which that sentence is worth asserting.
    """
    edits = {'cfg': {}, 'json': {}, 'overlays': {}}
    for rel, ent in (model['values'].get('overlays') or {}).items():
        if not ent.get('writable'):
            continue
        cells = []
        for i, ed in enumerate(ent.get('editable') or []):
            if not ed:
                continue
            name = ent['columns'][i]['name']
            for r in ent['rows']:
                cells.append({'key': r['key'], 'column': name,
                              'value': r['cells'][i]})
        if cells:
            edits['overlays'][rel] = {'cells': cells}
    for path, v in model['values']['cfg'].items():
        if v['present'] and not v.get('error'):
            edits['cfg'][path] = {'value': v['value']}
    for (name, path), (_s, f) in json_fields(schemas).items():
        slot = model['values']['json'].get(name, {}).get(path)
        if not slot:
            continue
        blk = edits['json'].setdefault(name, {'scalars': {}, 'tables': {}})
        if f['type'] == 'table':
            tbl = model['values']['tables'].get(slot.get('table'))
            if not tbl or (not tbl['present'] and not tbl['rows']):
                continue
            blk['tables'][path] = {'shape': tbl['shape'], 'rows': tbl['rows']}
        elif slot.get('present'):
            blk['scalars'][path] = {'present': True, 'value': slot['value']}
    for name in list(edits['json']):
        b = edits['json'][name]
        if not b['scalars'] and not b['tables']:
            del edits['json'][name]
    return edits


def _status(url, data=None, headers=None):
    import urllib.request
    import urllib.error
    req = urllib.request.Request(url, data=data, headers=headers or {},
                                 method='POST' if data is not None else 'GET')
    try:
        return urllib.request.urlopen(req).status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return -1


def _teampl_first_fraction(cd, schemas=None):
    """The first override row's value, read off disk.

    THREE LAYOUTS HAVE HELD THAT ROW NOW: a section of the merged document, its
    own ckf.hardmode.teampl.json, and since Phase 3 a slice file under
    ckf.hardmode.d/. This used to carry the first two as a written-down list
    and raised FileNotFoundError the moment a third appeared -- which is how it
    ended a whole --selftest run with a traceback and no report line
    [measured 2026-09-13, against the split layout]. The file is resolved from
    the mirror declaration that already names it instead, so a fourth layout
    moves it without touching this.
    """
    for sch in (load_schemas() if schemas is None else schemas):
        for inv in sch.get('invariants', []):
            if inv.get('kind') != 'mirror':
                continue
            sfile, spath = inv['source'].split('#', 1)
            p = os.path.join(cd, sfile)
            if not os.path.exists(p):
                continue
            js = check_schema.load_jsonc(p)
            val, found = dig(js, spath[:-2] if spath.endswith('[]') else spath)
            if found and isinstance(val, list) and val:
                return val[0][inv['value']]
    raise FileNotFoundError('no mirror source carrying rows under %s' % cd)


def _journal_escape_refused(td):
    d = os.path.join(td, 'jesc')
    os.makedirs(d, exist_ok=True)
    outside = os.path.join(td, 'outside.txt')
    with open(outside, 'w') as f:
        f.write('original')
    tmp = os.path.join(d, 'x' + TMP_SUFFIX)
    with open(tmp, 'w') as f:
        f.write('attacker')
    with open(journal_path(d), 'w') as f:
        json.dump({'renames': [[tmp, outside]]}, f)
    recover_journal(d)
    with open(outside) as f:
        return f.read() == 'original'


def _cfg_key_line_count(raw, section, key):
    """How many `Key = ...` lines sit under [section]. Two means an append
    landed beside a line that was already there.

    Counted with str.splitlines rather than through CfgFile: an instrument
    built out of the thing under test cannot see the thing under test fail
    (AGENTS.md section 3). Splitting the file the way CfgFile used to would
    hide the merged line and report one key where the file has two."""
    n, here = 0, False
    for line in raw.decode('utf-8-sig').splitlines():
        s = line.strip()
        if s.startswith('[') and s.endswith(']'):
            here = s[1:-1] == section
            continue
        m = CfgFile.KEY_RE.match(line)
        if here and m and m.group(1) == key:
            n += 1
    return n


def _one_line_changed(before, after):
    """True when the two files have the same lines and the same endings except
    on one line, whose key is unchanged."""
    la, ea = split_lines_keepends(before.decode('utf-8-sig'))
    lb, eb = split_lines_keepends(after.decode('utf-8-sig'))
    if len(la) != len(lb) or ea != eb:
        return False
    changed = [(x, y) for x, y in zip(la, lb) if x != y]
    if len(changed) != 1:
        return False
    mx, my = CfgFile.KEY_RE.match(changed[0][0]), CfgFile.KEY_RE.match(changed[0][1])
    return bool(mx and my and mx.group(1) == my.group(1))


def _is_pure_insertion(before, after):
    """True when `after` is `before` with whole lines added and nothing else:
    every line `before` carried is still there, in order, with the same content
    AND the same ending. What the append path must not do is edit a line it was
    only supposed to insert beside.

    Built out of split_lines_keepends rather than out of CfgFile, for the same
    reason _cfg_key_line_count is: an instrument assembled from the thing under
    test cannot see the thing under test fail (AGENTS.md section 3). It does
    share split_lines_keepends, which is the one piece both need to agree on
    for "a line" to mean anything; that function has its own cases in [8].

    ONE ending is allowed to change, and only in one direction: the final
    entry's. split_lines_keepends guarantees the last entry's ending is always
    '' and no other entry's is, so this is exactly the file-with-no-trailing-
    newline case -- a line cannot be appended after an unterminated last line
    without terminating it. Holding that against the writer would make this
    instrument reject the only correct way to do the write.
    """
    lb, eb = split_lines_keepends(before.decode('utf-8-sig'))
    la, ea = split_lines_keepends(after.decode('utf-8-sig'))
    if len(la) < len(lb):
        return False
    j = 0
    for i, (line, end) in enumerate(zip(lb, eb)):
        last = (i == len(lb) - 1)
        while j < len(la):
            if la[j] == line and (ea[j] == end or (last and end == '')):
                break
            j += 1
        else:
            return False
        j += 1
    return True


_UNDER_O_CHILD = r'''
import importlib.util, sys
spec = importlib.util.spec_from_file_location("ckf_serve_under_O", %(path)r)
m = importlib.util.module_from_spec(spec)
sys.modules["ckf_serve_under_O"] = m
spec.loader.exec_module(m)

# If -O did not take, this raises and the run exits non-zero with a traceback:
# the harness must never read "guards held" off an interpreter whose asserts
# were still live, because then it proved nothing.
assert False, "asserts are still live: -O did not take"

raw = b"[General]\nEnabled = true\n"
want = [("General.Enabled", "#x"), ("General.Enabled", "a\nb"),
        ("Slices.New", "#x"),      ("Slices.New", "a\nb")]
n = 0
for key, val in want:
    try:
        m.CfgFile(raw).set_value(key, val)
    except m.SaveRefused:
        n += 1
    except Exception:
        pass
sys.exit(0 if n == len(want) else 1)
'''


def _refuses_under_O():
    """-> True | False | None. Do CfgFile's two round-trip guards still refuse
    with asserts stripped?

    REINSTATED for split-config-into-toggleable-slices, and REWRITTEN rather
    than restored: the 3.0 version went out with the guards it protected, and
    the commit that removed it is not in this repository (see the header
    comment above class CfgFile). Same stated property, new code.

    Why a child process. `python -O` strips asserts AT COMPILE TIME, so by the
    time this function runs, this module's own asserts are already whatever
    they were going to be. The only way to check the claim is to compile the
    module again under -O, which needs a second interpreter.

    None is not False. Frozen there is no interpreter to re-enter and no -O to
    pass, and a subprocess that cannot start is not evidence that the guards
    failed. The caller reports None as NOT RUN and says why (AGENTS.md
    section 3).

    Both guards are driven twice, against a key the fixture HAS and a key it
    does NOT, so a regression that moved the guards below the key lookup --
    where an appended key would skip them -- fails here rather than passing.
    """
    if getattr(sys, 'frozen', False):
        return None
    try:
        r = subprocess.run([sys.executable, '-O', '-c',
                            _UNDER_O_CHILD % {'path': os.path.abspath(__file__)}],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           timeout=CHECK_SCHEMA_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode == 0:
        return True
    # Anything else is a real answer only if the child got far enough to give
    # one. A traceback means -O did not take or the module would not import,
    # and neither is a verdict on the guards.
    if r.returncode == 1 and not r.stderr.strip():
        return False
    return None


def _first_line_diff(a, b):
    """The first line where two files differ, as a detail string.

    CORRECTION, 2026-09-13 afternoon. This split both sides on a literal b'\n'.
    The Phase 1a review found that and deliberately left it, on the grounds
    that "it is only ever a t.check detail string and can never decide a
    result" -- which is still true, and is why this is a readability fix and
    not a defect fix. But the file it most often describes is now CRLF (see the
    line-endings note above class CfgFile), and the literal split left a
    trailing \r on every line, so a report of a one-character value change read
    as `b'Enabled = true\r' vs b'Enabled = false\r'`. Worse, it could not
    describe a difference that was ONLY in the endings: both sides split the
    same way and it returned '', i.e. "no difference", for two files that
    differ. A diagnostic that says nothing about the thing currently under
    scrutiny is the wrong diagnostic to keep.

    It now splits through split_lines_keepends, the way _one_line_changed and
    _is_pure_insertion do, and names the ending when the ending is what moved.
    """
    la, ea = split_lines_keepends(a.decode('utf-8-sig', 'replace'))
    lb, eb = split_lines_keepends(b.decode('utf-8-sig', 'replace'))
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else '<eof>'
        y = lb[i] if i < len(lb) else '<eof>'
        if x != y:
            return 'line %d: %r vs %r' % (i + 1, x, y)
        ex = ea[i] if i < len(ea) else None
        ey = eb[i] if i < len(eb) else None
        if ex != ey:
            return ('line %d: same text %r, ending %r vs %r'
                    % (i + 1, x, ex, ey))
    return ''


def _cfg_line_shape(before_path, after_path):
    """Every line is either identical or a 'Key = Value' line whose key is
    unchanged, and every line keeps the ending it had. Nothing else moved.

    CORRECTION, 2026-09-13. This used to split both files on a literal CRLF --
    ``read_bytes(p).decode('utf-8-sig').split('\\r\\n')`` -- which is the same
    assumption that crashed selftest section 8 on David's machine the same day.
    The file measured 162 bytes, 8 LF, 0 CRLF on the morning of 2026-09-13.
    (This docstring said "BepInEx owns ckf.hardmode.cfg and writes it with LF".
    The byte count was measured; the attribution to BepInEx was not, and a
    launch the same afternoon rewrote the file as 179 CRLF and no LF -- see the
    line-endings note above class CfgFile. The defect described below is
    unaffected: it was about splitting on a literal separator, and a literal
    split breaks on whichever ending the file does not have.)
    On an LF file that split returns ONE
    element holding the whole text, so `len(a) != len(b)` passed, and the one
    comparison left ran KEY_RE over a multi-line blob -- KEY_RE is anchored
    without re.MULTILINE and `.` does not cross a newline, so it cannot match
    one. Every real save therefore read as False: a FAIL raised against the
    cfg writer for a file the writer had handled correctly, and the only thing
    that had moved was the line endings BepInEx uses.

    It now splits the way _one_line_changed does, through
    split_lines_keepends, so a line is a line whatever the file's endings are
    and however they are mixed.

    The `ea != eb` comparison is new with that correction. The literal split
    discarded the endings, so the docstring's "nothing else moved" did not
    cover them; it does now, and a save that rewrote an ending it was given is
    a shape change like any other.
    """
    la, ea = split_lines_keepends(read_bytes(before_path).decode('utf-8-sig'))
    lb, eb = split_lines_keepends(read_bytes(after_path).decode('utf-8-sig'))
    if len(la) != len(lb) or ea != eb:
        return False
    for x, y in zip(la, lb):
        if x == y:
            continue
        mx, my = CfgFile.KEY_RE.match(x), CfgFile.KEY_RE.match(y)
        if not mx or not my or mx.group(1) != my.group(1):
            return False
    return True


PURE_BEGIN = '/*==CKF-PURE-BEGIN==*/'
PURE_END = '/*==CKF-PURE-END==*/'

JS_DRIVER = r'''
let pass = 0, fail = [];
function ck(name, cond, detail) {
  if (cond) { pass++; console.log('  PASS  ' + name); }
  else { fail.push(name); console.log('  FAIL  ' + name + (detail === undefined ? '' : '  ' + JSON.stringify(detail))); }
}
const A = CKF.parseAdjust;
const ok = [['','none',null],['  ','none',null],['=40','set',40],['40','set',40],
  ['=-55','set',-55],['+25','add',25],['-25','add',-25],['x1.5','multiply',1.5],
  ['X1.5','multiply',1.5],['*1.5','multiply',1.5],['x.75','multiply',0.75],
  ['=0','set',0],['0','set',0],['+0','add',0],['x-2','multiply',-2],
  ['=1e3','set',1000],['  =40  ','set',40],['=+5','set',5],['.5','set',0.5],
  ['++5','add',5],['+-5','add',-5]];
for (const [s,k,v] of ok) { const r = A(s);
  ck('accepts ' + JSON.stringify(s), r.ok && r.kind===k && (v===null||Math.abs(r.value-v)<1e-12), r); }
for (const s of ['abc','x','=','+','-','1,000','4 2','=4a','xx2','=1.2.3','0x10','=,','- 25','1 000','%50'])
  ck('rejects ' + JSON.stringify(s), !A(s).ok, A(s));
for (const s of ['NaN','=NaN','Infinity','-Infinity','inf'])
  ck('refuses ' + JSON.stringify(s) + ' (stricter than C#, deliberately)', !A(s).ok, A(s));

ck('cfg bool renders lowercase', CKF.renderCfgValue('bool', true) === 'true');
ck('cfg int renders bare', CKF.renderCfgValue('int', 40) === '40');
ck('cfg float 3.0 renders as 3', CKF.renderCfgValue('float', 3) === '3');
ck('cfg float 1.5 renders as 1.5', CKF.renderCfgValue('float', 1.5) === '1.5');
ck('cfg floatOrNaN renders NaN', CKF.renderCfgValue('floatOrNaN', 'NaN') === 'NaN');
ck('cfg stringList stays on one line',
   CKF.renderCfgValue('stringList', ['A','B']) === 'A, B');

ck('empty input is unset, not zero', CKF.coerceCell('int', '').present === false);
ck('"0" is present and zero',
   CKF.coerceCell('int','0').present === true && CKF.coerceCell('int','0').value === 0);
ck('"0.0" float is present and zero',
   CKF.coerceCell('float','0.0').present === true && CKF.coerceCell('float','0.0').value === 0);
ck('a non-number is rejected, not silently zeroed', CKF.coerceCell('int','abc').ok === false);
ck('whitespace only is unset', CKF.coerceCell('int','   ').present === false);

ck('range check accepts the bounds', CKF.inRange(0,[0,100]) && CKF.inRange(100,[0,100]));
ck('range check rejects outside', !CKF.inRange(101,[0,100]) && !CKF.inRange(-1,[0,100]));
ck('range check ignores a null (unset) value', CKF.inRange(null,[0,100]));

ck('AND-chain: all on -> on', CKF.effective([true,true]) === 'on');
ck('AND-chain: one off -> off', CKF.effective([true,false]) === 'off');
ck('AND-chain: one unreadable -> unknown, not off', CKF.effective([true,null]) === 'unknown');
ck('AND-chain: off wins over unknown', CKF.effective([false,null]) === 'off');

const rows = [{id:0,cells:{x:1,y:null}},{id:1,cells:{x:2,y:0}}];
const pts = CKF.curvePoints(rows,'x','y');
ck('an unset point is not plotted', pts.length === 1 && pts[0].y === 0, pts);

const dom = CKF.matrixDomain(
  [{cells:{A:1,B:2,V:0.5}}], [{cells:{A:1,B:3,V:0.1}},{cells:{A:2,B:2,V:0.2}}],
  {row:'A',col:'B',value:'V'});
ck('matrix domain unions override and stock',
   JSON.stringify(dom.rows)==='[1,2]' && JSON.stringify(dom.cols)==='[2,3]', dom);

ck('rewardcurve keep-marker: absent counts as keep', CKF.isKeepValue(null) === true);
ck('rewardcurve keep-marker: -1 counts as keep', CKF.isKeepValue(-1) === true);
ck('rewardcurve keep-marker: 0 does NOT count as keep', CKF.isKeepValue(0) === false);

// A new matrix row or column starts unset. A 0 here is a real award of zero in
// a retroactive field, and neither the range check nor the mirror invariant
// can tell the two apart.
const AX = {row:'ActionClass', col:'MissionPowerLevel', value:'PowerLevelFraction'};
const SPEC = [{name:'ActionClass'},{name:'MissionPowerLevel'},{name:'PowerLevelFraction'}];
const newcol = CKF.newMatrixCells(SPEC, AX, AX.col, 21, 3, 7);
ck('a new matrix column leaves the value unset, not zero',
   newcol.PowerLevelFraction === null, newcol);
ck('a new matrix column takes its own coordinate and the first row',
   newcol.MissionPowerLevel === 21 && newcol.ActionClass === 3, newcol);
const newrow = CKF.newMatrixCells(SPEC, AX, AX.row, 4, 3, 7);
ck('a new matrix row leaves the value unset, not zero',
   newrow.PowerLevelFraction === null, newrow);
ck('a new matrix row takes its own coordinate and the first column',
   newrow.ActionClass === 4 && newrow.MissionPowerLevel === 7, newrow);
ck('no cell of a new row is zero',
   Object.keys(newrow).every(function (k) { return newrow[k] !== 0; }), newrow);
ck('a new row carries a key for every declared column and no others',
   JSON.stringify(Object.keys(newrow).sort())
     === JSON.stringify(['ActionClass','MissionPowerLevel','PowerLevelFraction']),
   Object.keys(newrow));
ck('the unset a new row starts in is the same unset clearing a cell leaves',
   newcol.PowerLevelFraction === CKF.coerceCell('float','').value
     && CKF.coerceCell('float','').present === false);

// REMOVED IN 3.0 with pairState: the five checks on the collapsed two-gate
// control. No subsystem is gated twice any more, so there is no pair to
// collapse and no 'mixed' state to report.

// Reference material sorts last, and nothing else moves.
const FS = [{path:'a',ui:'form'},{path:'b',ui:'readonly'},{path:'c',ui:'matrix'},{path:'d'}];
const SP = CKF.splitReference(FS);
ck('a readonly field is separated out',
   SP.reference.length === 1 && SP.reference[0].path === 'b', SP);
ck('every other field keeps its order',
   SP.main.map(function (f) { return f.path; }).join('') === 'acd', SP.main);
ck('splitting loses nothing', SP.main.length + SP.reference.length === FS.length);

// A windowed axis. Hiding is display only, and it never hides a coordinate
// that carries data.
const AXW = CKF.visibleAxis([-2,-1,0,1,2,3], [1,3], [1,2,3]);
ck('coordinates outside the window are not drawn',
   AXW.shown.join(',') === '1,2,3' && AXW.hidden.join(',') === '-2,-1,0', AXW);
ck('nothing outside the window is occupied, so nothing is forced back in',
   AXW.outside.length === 0, AXW);
const AXW2 = CKF.visibleAxis([-2,-1,0,1,2,3], [1,3], [-1,1,2,3]);
ck('an occupied coordinate outside the window is drawn anyway',
   AXW2.shown.join(',') === '-1,1,2,3', AXW2);
ck('and is named as the reason it is there',
   AXW2.outside.join(',') === '-1' && AXW2.hidden.join(',') === '-2,0', AXW2);
ck('no window means everything is drawn',
   CKF.visibleAxis([-2,5], null, []).shown.join(',') === '-2,5');

// REMOVED, 2026-09-07: the five hasUnsetControl cases. The control is gone and
// so is the function. What remains true, and is asserted here instead, is the
// coercion the boxes now carry on their own: a cleared numeric box drops the
// key, a cleared text box holds an empty string.
ck('the unset helper is gone from the pure block',
   CKF.hasUnsetControl === undefined);

// Column widths come from what a column holds, not from one constant for the
// whole page. These are the two shapes the old 11ch / 20ch pair got wrong.
const W_TYPE = CKF.colWidth({name:'type', type:'string'},
  ['PGen_CorpSecurity_Battle_Warehouse_Interior_M3', 'PGen_Hack'], '');
const W_ADJ = CKF.colWidth({name:'BonusPayment', type:'string'},
  ['x1.5', '+25', ''], 'adjust');
const W_EMPTY = CKF.colWidth({name:'Bonus', type:'int'}, [], '');
const W_LONGHEAD = CKF.colWidth({name:'PowerLevelFraction', type:'float'}, [0.25], '');
ck('a 46-character id gets a wide column', W_TYPE >= 36, W_TYPE);
ck('but never wider than the ceiling', W_TYPE === 44, W_TYPE);
ck('an adjustment slot stays narrow', W_ADJ <= 12 && W_ADJ >= 8, W_ADJ);
ck('the adjustment slot is narrower than the id column', W_ADJ < W_TYPE, [W_ADJ, W_TYPE]);
ck('an empty column is still wide enough to type in', W_EMPTY >= 4, W_EMPTY);
ck('a long heading widens its column as far as its longest segment',
   W_LONGHEAD === 12, W_LONGHEAD);
ck('nothing falls below the floor',
   CKF.colWidth({name:'x', type:'int'}, [null, null], '') >= 4);

// 120%: every column is at least a fifth wider than the widest thing it has to
// hold, heading included, plus the box's own padding. Asserted as a ratio so
// the rule survives a change to either constant.
const ROOM = function (w, content) { return (w - 2) / content; };
const W_VALUE = CKF.colWidth({name:'x', type:'string'}, ['abcdefghij'], '');
ck('a column is at least 120% of the widest value it holds',
   ROOM(W_VALUE, 11) >= 1.2, [W_VALUE, 11]);
ck('a column is at least 120% of its longest heading segment',
   ROOM(W_LONGHEAD, 8) >= 1.2, [W_LONGHEAD, 8]);
ck('the heading is no longer capped out of the width it needs',
   CKF.colWidth({name:'AveragePayoutMultiplier', type:'float'}, [1], '') > 12,
   CKF.colWidth({name:'AveragePayoutMultiplier', type:'float'}, [1], ''));
ck('a camelCase heading gains break points at the seams',
   CKF.headSegments('MissionPowerLevel').join('|') === 'Mission|Power|Level',
   CKF.headSegments('MissionPowerLevel'));
ck('a one-word heading gains none',
   CKF.headSegments('multiplier').length === 1);
ck('the zero-width joiner is the only thing added',
   CKF.softWrap('MissionPowerLevel').replace(/\u200b/g, '') === 'MissionPowerLevel');
ck('a cleared numeric box still drops the key',
   CKF.coerceCell('int', '').present === false);
ck('a cleared text box is an empty string, which is a value',
   CKF.coerceCell('string', '').present === true
   && CKF.coerceCell('string', '').value === '');
ck('null is still how an edit payload drops a text key',
   CKF.coerceCell('string', null).present === false);

// ---- overlayHidden: the DECLARED half of suppression, added 2026-09-14.
//
// The names live in the server's HIDDEN_COLUMNS and reach the page as a
// per-column reason string, so these cases are about the READING of that
// payload, not about which columns are in it. They are here rather than in the
// DOM render because the helper is pure and the two properties that matter --
// index 0 is never hidden, and the row count does not enter into it -- are
// cheaper to state on a fixture than to arrange on a rendered page.
const HFIX = function (n, reason, rows) {
  const cols = []; const hidden = [];
  for (let i = 0; i < n; i++) { cols.push({ name: 'c' + i, control: false });
                                hidden.push(i === 2 ? reason : null); }
  const rs = []; for (let i = 0; i < rows; i++) rs.push({ cells: [] });
  return { columns: cols, hidden: hidden, rows: rs }; };
ck('a column the server marked is hidden, and carries the reason it gave',
   CKF.overlayHidden(HFIX(4, 'item metadata, not a combat lever', 3))[2]
   === 'item metadata, not a combat lever');
ck('a column it did not mark is not hidden',
   CKF.overlayHidden(HFIX(4, 'r', 3))[1] === null
   && CKF.overlayHidden(HFIX(4, 'r', 3))[3] === null);
ck('index 0 is never hidden, whatever the server sends — the key column is '
   + 'the row\'s name and a grid without it is a grid of nothing',
   CKF.overlayHidden({ columns: [{ name: 'k' }, { name: 'a' }],
                       hidden: ['a reason', null], rows: [] })[0] === null);
ck('a one-row sheet hides exactly what a twenty-row sheet hides — a declared '
   + 'hide is not an observation about the cells, so the fewer-than-two-rows '
   + 'exemption the constancy rule needs does not apply to it',
   JSON.stringify(CKF.overlayHidden(HFIX(4, 'r', 1)))
   === JSON.stringify(CKF.overlayHidden(HFIX(4, 'r', 20))));
ck('and the constancy rule still HAS that exemption, so the two have not been '
   + 'quietly merged',
   CKF.overlaySuppressed({ columns: [{ name: 'k' }, { name: 'a' }],
                           constant: [null, { value: 'x', rows: 1 }],
                           editable: [false, false],
                           rows: [{ cells: [] }] })[1] === false);
ck('an entry with no hidden key at all is read as nothing hidden, not as a '
   + 'crash — the key is a server addition and may not have landed',
   JSON.stringify(CKF.overlayHidden({ columns: [{ name: 'k' }, { name: 'a' }] }))
   === JSON.stringify([null, null]));
ck('a non-string reason is not a reason', CKF.overlayHidden(
   { columns: [{ name: 'k' }, { name: 'a' }], hidden: [null, true] })[1] === null);
ck('and neither is an empty one', CKF.overlayHidden(
   { columns: [{ name: 'k' }, { name: 'a' }], hidden: [null, ''] })[1] === null);

console.log('\nnode self-test of app.html: ' + pass + ' passed, ' + fail.length + ' failed');
process.exit(fail.length ? 1 : 0);
'''


# ---------------------------------------------------------------------------
# app.html, rendered
#
# There is no browser in this environment, and ordering, grouping and spacing
# are exactly the kind of change that cannot be argued into being correct. So
# the page is rendered here instead: a DOM small enough to fit in this file,
# app.html's own two script blocks on top of it, a stubbed fetch handing back a
# real model built from a real config directory, and then assertions about the
# tree that came out. It proves structure -- order, grouping, which controls
# exist, which columns are drawn. It proves nothing about how any of it LOOKS.

DOM_STUB = r'''
function Node(tag, ns) {
  this.tagName = String(tag).toUpperCase(); this.ns = ns || null;
  this.children = []; this.attrs = {}; this.listeners = {};
  this.className = ''; this._text = ''; this.style = {};
  this.value = ''; this.checked = false; this.disabled = false;
  this.indeterminate = false; this.placeholder = ''; this.title = '';
  const self = this;
  this.classList = {
    add: function () { for (const c of arguments) if (!self._cls().includes(c)) self.className = (self.className + ' ' + c).trim(); },
    remove: function (c) { self.className = self._cls().filter(function (x) { return x !== c; }).join(' '); },
    contains: function (c) { return self._cls().includes(c); },
  };
}
Node.prototype._cls = function () { return this.className.split(/\s+/).filter(Boolean); };
Node.prototype.appendChild = function (n) { if (n) { n.parent = this; this.children.push(n); } return n; };
Node.prototype.insertBefore = function (n, ref) {
  const i = this.children.indexOf(ref);
  if (i < 0) this.children.push(n); else this.children.splice(i, 0, n);
  n.parent = this; return n;
};
Node.prototype.removeChild = function (n) {
  const i = this.children.indexOf(n); if (i >= 0) this.children.splice(i, 1); return n;
};
Node.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); if (k === 'type') this.type = String(v); };
Node.prototype.getAttribute = function (k) { return this.attrs[k]; };
Node.prototype.addEventListener = function (k, fn) { (this.listeners[k] = this.listeners[k] || []).push(fn); };
Node.prototype.removeEventListener = function () {};
Node.prototype.setPointerCapture = function () {};
Node.prototype.getBoundingClientRect = function () { return { top: 0, left: 0, width: 900, height: 260 }; };
Node.prototype.fire = function (k) { for (const fn of (this.listeners[k] || [])) fn({ preventDefault: function () {} }); };
Object.defineProperty(Node.prototype, 'firstChild', { get: function () { return this.children[0] || null; } });
Object.defineProperty(Node.prototype, 'textContent', {
  get: function () {
    if (this.tagName === '#TEXT') return this._text;
    return this._text + this.children.map(function (c) { return c.textContent; }).join('');
  },
  set: function (v) { this.children = []; this._text = String(v); },
});
Node.prototype.walk = function (fn) {
  fn(this);
  for (const c of this.children) c.walk(fn);
};
Node.prototype.find = function (pred) {
  const out = []; this.walk(function (n) { if (pred(n)) out.push(n); }); return out;
};
Node.prototype.querySelector = function (sel) {
  const hits = this.find(function (n) {
    if (sel[0] === '#') return n.attrs.id === sel.slice(1);
    if (sel[0] === '.') return n._cls().includes(sel.slice(1));
    return n.tagName === sel.toUpperCase();
  });
  return hits[0] || null;
};

const document = {
  _ids: {},
  createElement: function (t) { return new Node(t); },
  createElementNS: function (ns, t) { return new Node(t, ns); },
  createTextNode: function (s) { const n = new Node('#text'); n._text = String(s); return n; },
  querySelector: function (sel) {
    if (sel[0] === '#') return document._ids[sel.slice(1)] || null;
    return null;
  },
};
for (const id of ['banners', 'index', 'panel', 'dirty', 'save', 'gamedir', 'probe',
                  'applydir', 'revalidate']) {
  const n = new Node(id === 'gamedir' ? 'input' : 'div');
  n.setAttribute('id', id); document._ids[id] = n;
}
const window = {};
'''


def dom_driver(model_json, asserts=None):
    """The node program: DOM stub, both of app.html's script blocks, a fetch
    that answers with `model_json`, then the assertions."""
    with open(APP_HTML, encoding='utf-8') as f:
        src = f.read()
    blocks = re.findall(r'<script>(.*?)</script>', src, re.S)
    if len(blocks) != 2:
        raise RuntimeError('expected two <script> blocks in app.html, found %d' % len(blocks))
    body = blocks[1].replace('__CKF_TOKEN__', 'test-token')
    fetch = ('\nconst FIXTURE = %s;\n'
             'const fetch = async function (path) {\n'
             '  if (path !== "/api/model") throw new Error("unexpected " + path);\n'
             '  return { ok: true, status: 200, text: async function () '
             '{ return JSON.stringify(FIXTURE); } };\n'
             '};\n' % model_json)
    return DOM_STUB + fetch + blocks[0] + '\n' + body + '\n' + (asserts or DOM_ASSERTS)


DOM_ASSERTS = r'''
let pass = 0, fail = [];
function ck(name, cond, detail) {
  if (cond) { pass++; console.log('  PASS  ' + name); }
  else { fail.push(name); console.log('  FAIL  ' + name + (detail === undefined ? '' : '  ' + JSON.stringify(detail))); }
}
const nav = document.querySelector('#index');
const panel = document.querySelector('#panel');
// The page inserts a zero-width space into a long column name so the header
// can wrap; it is invisible and it is not part of the name. Stripping it here
// is what lets a case compare against the name a schema or a file declares.
const txt = function (n) {
  return n.textContent.replace(/\u200b/g, '').replace(/\s+/g, ' ').trim(); };
const navItems = function () { return nav.find(function (n) { return n._cls().includes('navitem'); }); };
const titleOf = function (item) { return txt(item.querySelector('b')); };
const select = function (i) { navItems()[i].fire('click'); };
// file#section, the same unit key the server builds. Derived from the schema's
// own targets, so nothing here names a file or a section.
const unitOf = function (s) {
  const tt = s.targets || {};
  return tt.json ? (tt.section ? tt.json + '#' + tt.section : tt.json) : null;
};

setTimeout(function () {
  const items = navItems();
  ck('every section has a nav item', items.length === FIXTURE.sections.length,
     [items.length, FIXTURE.sections.length]);

  // 1. the master switch is the first thing on the page
  const masterSub = FIXTURE.enableIndex.filter(function (e) {
    return (e.gates || []).some(function (g) { return g.name === FIXTURE.masterKey; });
  })[0];
  ck('the master switch is the first section',
     titleOf(items[0]) === masterSub.title, [titleOf(items[0]), masterSub.title]);

  // 2. the regression suite is the last
  const lastSec = FIXTURE.sections[FIXTURE.sections.length - 1];
  ck('the section pinned last really is last',
     titleOf(items[items.length - 1]) === lastSec.title,
     [titleOf(items[items.length - 1]), lastSec.title]);

  // 3. the merged section
  //
  // WAS: `findIndex(s => s.subsystems.length > 1)` -- "one section presents two
  // subsystems", which worked while exactly one section in the whole nav was a
  // merge. Since 2026-09-13 SECTION_GROUPS declares several, and that search
  // returned whichever came first rather than the one these cases are about.
  // The section under test is now found from the schema that owns the readonly
  // reference table, which is what the rest of this block reads.
  // TWO KINDS OF READONLY TABLE SINCE PHASE 4. This block is about the
  // UNDERLAY -- a readonly table some control declares as its `over`, drawn on
  // that control's axes. rulemodel's reference field is the other kind: its
  // rows are in the schema and it is drawn beside an overlay, with no owner and
  // no axes. `f.ui === 'readonly'` alone matched both and returned whichever
  // came first, so the cases below started measuring the wrong subsystem.
  const isUnderlay = function (s, f) {
    return f.ui === 'readonly' && s.fields.some(function (g) {
      return g.over === f.path && g.axes; }); };
  const roSchemas = FIXTURE.schemas.filter(function (s) {
    return s.fields.some(function (f) { return isUnderlay(s, f); }); });
  ck('exactly one schema declares a readonly underlay table',
     roSchemas.length === 1, roSchemas.map(function (s) { return s.subsystem; }));
  const gi = FIXTURE.sections.findIndex(function (s) {
    return s.subsystems.indexOf(roSchemas[0].subsystem) >= 0; });
  ck('it is drawn in a section that presents more than one subsystem',
     gi >= 0 && FIXTURE.sections[gi].subsystems.length > 1,
     gi < 0 ? 'no section holds it' : FIXTURE.sections[gi]);
  const group = FIXTURE.sections[gi];
  select(gi);
  const heads = panel.find(function (n) { return n.tagName === 'H3'; }).map(txt);
  for (const sub of group.subsystems) {
    const t = FIXTURE.schemas.find(function (s) { return s.subsystem === sub; }).title;
    ck('the grouped section shows ' + t, heads.some(function (h) { return h.indexOf(t) === 0; }), heads);
  }
  // the reference table is the last thing in the section
  const roField = FIXTURE.schemas.filter(function (s) { return group.subsystems.indexOf(s.subsystem) >= 0; })
    .reduce(function (a, s) { return a.concat(s.fields.filter(function (f) { return isUnderlay(s, f); })); }, []);
  ck('the group carries exactly one readonly underlay table', roField.length === 1, roField.length);
  const cards = panel.children.filter(function (c) { return c._cls().includes('card'); });
  const refCardIdx = cards.findIndex(function (c) { return txt(c).indexOf(roField[0].label) >= 0; });
  ck('the reference table is in the last card of the section',
     refCardIdx === cards.length - 1, [refCardIdx, cards.length]);

  // 4. both Team PL grids, same shape, no columns below the window
  const grids = panel.find(function (n) { return n.tagName === 'TABLE' && n._cls().includes('grid'); });
  const headersOf = function (g) {
    return g.querySelector('thead').find(function (n) { return n.tagName === 'TH'; }).map(txt);
  };
  const axisGrids = grids.filter(function (g) { return headersOf(g)[0].indexOf('\\') > 0; });
  ck('the section draws two grids on the same axes', axisGrids.length === 2, axisGrids.length);
  const h0 = headersOf(axisGrids[0]), h1 = headersOf(axisGrids[1]);
  ck('the reference grid has the same header row as the editable one',
     JSON.stringify(h0) === JSON.stringify(h1), [h0, h1]);
  ck('the columns start at 1 — nothing from -10 to 0 is drawn',
     h0.slice(1).join(',') === '1,2,3,4,5,6,7,8,9,10', h0);
  const bodyRows = function (g) { return g.querySelector('tbody').children; };
  ck('the two grids have the same number of rows',
     bodyRows(axisGrids[0]).length === bodyRows(axisGrids[1]).length,
     [bodyRows(axisGrids[0]).length, bodyRows(axisGrids[1]).length]);
  ck('and the same row axis labels',
     JSON.stringify(bodyRows(axisGrids[0]).map(function (r) { return txt(r.children[0]); }))
       === JSON.stringify(bodyRows(axisGrids[1]).map(function (r) { return txt(r.children[0]); })));
  ck('every cell of the reference grid is disabled',
     bodyRows(axisGrids[1]).every(function (r) {
       return r.children.slice(1).every(function (td) {
         const i = td.querySelector('input'); return i && i.disabled; }); }));
  ck('the editable grid is editable',
     bodyRows(axisGrids[0]).some(function (r) {
       return r.children.slice(1).some(function (td) {
         const i = td.querySelector('input'); return i && !i.disabled; }); }));
  ck('the page says what it is not drawing', txt(panel).indexOf('not shown') > 0);

  // 4b. the nav: one level of grouping, and a three-state toggle per page
  //
  // BEFORE section 5, deliberately: section 5 clicks gates, which edits the
  // working copy, and these cases read the working copy. Run after it they
  // would be measuring section 5's clicks.
  // The gate a schema declares, and the field behind it. Recomputed here
  // from the payload rather than borrowed from app.html, so the page is not
  // asserted against its own helper.
  const gateOf = function (s) {
    const en = s.enable || {};
    if (en.cfg) return { in: 'cfg', path: en.cfg };
    if (en.json) return { in: 'json', path: en.json };
    return null;
  };
  const schemaFor = function (sub) {
    return FIXTURE.schemas.find(function (s) { return s.subsystem === sub; }); };
  const slotOf = function (s, g) {
    return g.in === 'cfg' ? W.cfg[g.path] : (W.json[unitOf(s)] || {})[g.path]; };
  const groups = FIXTURE.navGroups.groups;
  const navKids = nav.children;
  const groupHeads = navKids.filter(function (n) { return n._cls().includes('navgroup'); });
  ck('every declared group has exactly one header in the nav',
     groupHeads.length === groups.length, [groupHeads.length, groups.length]);
  ck('the headers carry the titles the server sent, in the order it sent them',
     JSON.stringify(groupHeads.map(txt)) === JSON.stringify(groups.map(function (g) { return g.title; })),
     [groupHeads.map(txt), groups.map(function (g) { return g.title; })]);
  ck('no group is nested inside another — one level only',
     groupHeads.every(function (h) {
       return h.find(function (n) { return n !== h && n._cls().includes('navgroup'); }).length === 0; }));
  for (const g of groups) {
    if (g.sections.length) continue;
    const hi = navKids.findIndex(function (n) {
      return n._cls().includes('navgroup') && txt(n) === g.title; });
    const next = navKids[hi + 1];
    ck(g.id + ': a group that draws no page says why, right under its header',
       !!next && next._cls().includes('navnote') && txt(next).length > 0,
       next ? [next.className, txt(next)] : 'nothing follows the header');
    ck(g.id + ': and it draws no page rather than an empty row',
       !next || !next._cls().includes('navitem'), next && next.className);
  }
  let togTotal = 0, togIndeterminate = 0;
  for (let i = 0; i < FIXTURE.sections.length; i++) {
    const sec = FIXTURE.sections[i];
    const item = navItems()[i];
    const boxes = item.find(function (n) { return n.tagName === 'INPUT' && n.type === 'checkbox'; });
    const want = sec.subsystems.filter(function (sub) { return gateOf(schemaFor(sub)); });
    ck(sec.id + ': one nav toggle per page that declares a gate, and none for a '
       + 'page that does not', boxes.length === want.length, [boxes.length, want]);
    for (let k = 0; k < Math.min(boxes.length, want.length); k++) {
      const sch0 = schemaFor(want[k]);
      const g0 = gateOf(sch0);
      const slot = slotOf(sch0, g0);
      const unreadable = !slot || !slot.present || !!slot.error;
      togTotal++;
      if (boxes[k].indeterminate) togIndeterminate++;
      ck(want[k] + ': its nav toggle shows the gate it names — unknown is '
         + 'indeterminate, never unchecked',
         boxes[k].checked === (!unreadable && !!slot.value)
           && boxes[k].indeterminate === unreadable,
         [unreadable, slot && slot.value, boxes[k].checked, boxes[k].indeterminate]);
      // WAS, until 2026-09-14:
      //   ck(want[k] + ': and it is writable exactly when its key is in the
      //      file',
      //      boxes[k].disabled === (g0.in === 'cfg'
      //                             && !FIXTURE.values.cfg[g0.path].present));
      //
      // THE NAV AND THE PANEL WERE ASSERTING OPPOSITE RULES ABOUT THE SAME
      // GATE, and both passed. The panel's case (section 5, below) reads "its
      // key is not in the file, and the control is live rather than disabled —
      // saving appends the key", because split-config-into-toggleable-slices
      // reversed the old rule: CfgFile.set_value APPENDS a key the file does
      // not carry, and disabling an absent key greyed out every slice toggle
      // until somebody launched the game once. The nav kept the old rule and
      // its comment still claimed the two agreed.
      //
      // Item 3 merged the two controls into one gateBox, which forced the
      // question. The measured answer is that the key is writable, so the box
      // is live on BOTH screens and the absent case is carried by the
      // indeterminate state rather than by a disable. NOT loosened: the case
      // still asserts a value, the opposite one, and the absent branch is
      // still counted by togIndeterminate above so it cannot go quiet.
      ck(want[k] + ': and it is live rather than disabled even when its key is '
         + 'not in the file — saving appends the key, and "could not be read" '
         + 'is carried by the indeterminate state, not by a dead box',
         boxes[k].disabled === false,
         [boxes[k].disabled, g0, FIXTURE.values.cfg[g0.path]]);
      // The entry enable_index computed is what supplies the tooltip and the
      // pill beside the box; a page whose gate could not be read must not
      // report itself off.
      const ent = FIXTURE.enableIndex.find(function (x) { return x.subsystem === want[k]; });
      ck(want[k] + ': a gate that could not be read is not reported off',
         !(ent.gates.some(function (x) { return x.state === null; })
           && ent.effective === 'off'), ent);
    }
  }
  ck('the fixture exercised both toggle states: ' + togIndeterminate
     + ' unreadable of ' + togTotal + ' — a render where every gate reads the '
     + 'same way proves only one of the two',
     togTotal > 0 && togIndeterminate > 0 && togIndeterminate < togTotal,
     [togIndeterminate, togTotal]);
  // A TOGGLE THAT DOES NOT MOVE WHEN IT IS CLICKED. The first version of this
  // control read its checked state from the enableIndex the server sent rather
  // than from the working copy, so every click was undone by the re-render that
  // followed it and the box looked inert. Caught here, before it shipped.
  const liveTog = function () {
    return navItems().reduce(function (acc, it) {
      return acc.concat(it.find(function (n) {
        return n.tagName === 'INPUT' && n.type === 'checkbox' && !n.disabled; })); }, []);
  };
  const firstTog = liveTog()[0];
  ck('at least one nav toggle is writable, so the click below has something to '
     + 'land on', !!firstTog, liveTog().length);
  if (firstTog) {
    const before = firstTog.checked;
    firstTog.checked = !before;
    firstTog.fire('change');
    ck('clicking a nav toggle moves it, and the redraw keeps it moved',
       liveTog()[0].checked === !before,
       [before, liveTog()[0].checked]);
    // put it back, so section 5 starts from the state the fixture describes
    const again = liveTog()[0];
    again.checked = before;
    again.fire('change');
    ck('and moving it back returns it', liveTog()[0].checked === before,
       liveTog()[0].checked);
  }

  // 4b. ONE GATE CONTROL, THREE STATES, DRAWN ONCE.
  //
  // PLACED HERE, BETWEEN 4 AND 5, DELIBERATELY. Section 5 below ticks every
  // gate in turn to prove the click lands, and setBool marks a flipped key
  // PRESENT -- so after it has run, the key the fixture deliberately held
  // back is in the working copy and the indeterminate state can no longer be
  // rendered. Reading the box after that would assert the third state
  // against a page that no longer has one. The box is read off W, the
  // working copy, for the same reason the control itself is.
  //
  // The state pill, the enable-chain line and the "Enable <title>" checkbox
  // were three renderings of one fact across two cards. They are one control
  // now. What must survive is the third state: a gate whose key is not in the
  // file is INDETERMINATE, never unchecked, or a gate nobody could read is
  // indistinguishable from one that was read and is off.
  let gateUnknown = 0, gateKnown = 0;
  for (let i = 0; i < FIXTURE.sections.length; i++) {
    select(i);
    for (const sub of FIXTURE.sections[i].subsystems) {
      const sc = FIXTURE.schemas.find(function (x) { return x.subsystem === sub; });
      const gg = sc && (sc.enable || {}).cfg;
      if (!gg) continue;
      const slot = W.cfg[gg];
      const unreadable = !slot || !slot.present || !!slot.error;
      const boxes = panel.find(function (n) {
        return n.tagName === 'INPUT' && n.type === 'checkbox'; });
      const mineBox = boxes.filter(function (b) {
        return b.getAttribute && b.getAttribute('aria-label')
               === (sc.fields.find(function (f) {
                      return f.in === 'cfg' && f.path === gg; }) || {}).label; });
      ck(sub + ': its gate is ONE control on the page, not two',
         mineBox.length === 1, mineBox.length);
      if (mineBox.length !== 1) continue;
      const b = mineBox[0];
      if (unreadable) gateUnknown++; else gateKnown++;
      ck(sub + ': and it carries three states — unknown is indeterminate and '
         + 'is announced as mixed, never as unchecked',
         b.indeterminate === unreadable
         && b.checked === (!unreadable && !!slot.value)
         && b.getAttribute('aria-checked')
            === (unreadable ? 'mixed' : (b.checked ? 'true' : 'false')),
         [unreadable, b.checked, b.indeterminate, b.getAttribute('aria-checked')]);
      const pt = txt(panel);
      ck(sub + ': and the word beside it says which state, in the same '
         + 'vocabulary the chain and the nav use',
         pt.indexOf(unreadable ? 'could not be read'
                               : (b.checked ? 'on' : 'off')) >= 0);
      if (unreadable) {
        ck(sub + ': a gate whose key is not in the file says saving adds it, '
           + 'and the box is live rather than dead',
           pt.indexOf('not in the file yet') >= 0 && b.disabled === false,
           [b.disabled]);
      }
    }
  }
  ck('the fixture rendered both gate states: ' + gateUnknown + ' unknown, '
     + gateKnown + ' read — a page where every gate reads the same way proves '
     + 'only one of the two',
     gateUnknown > 0 && gateKnown > 0, [gateUnknown, gateKnown]);


  // 5. every subsystem gate is a control of its own, whatever it is spelled in
  //
  // WAS, until 2026-09-13, under the comment "This replaces 'one checkbox per
  // doubly gated subsystem'. Phase 3 deleted the outer cfg gate, so the
  // collapsed control and the fixture that drove it are gone":
  //
  //   ck('every gate is a field in the document except the master, which is
  //      the one cfg key left',
  //      cfgGated.length === 1 && ungated.length <= 1 && ...);
  //
  // "Phase 3 deleted the outer cfg gate" is a consolidate-config-and-ship
  // statement, and split-config-into-toggleable-slices reverses it: every slice
  // toggle is a cfg key again. Measured 2026-09-13 the three sets are 0 json,
  // 10 cfg, 33 with no gate declared, of 43 schemas. Counts move every phase,
  // so they are REPORTED in the case name and what is ASSERTED is the
  // partition plus the one property that outlives a phase: exactly one cfg
  // gate is the master key.
  const gated = FIXTURE.schemas.filter(function (s) {
    return (s.enable || {}).json && s.fields.some(function (f) {
      return f.in === 'json' && f.path === s.enable.json; }); });
  const cfgGated = FIXTURE.schemas.filter(function (s) { return (s.enable || {}).cfg; });
  const ungated = FIXTURE.schemas.filter(function (s) { return !s.enable; });
  ck('the gate spellings partition the schema set: ' + gated.length + ' json, '
     + cfgGated.length + ' cfg, ' + ungated.length + ' with no gate declared, of '
     + FIXTURE.schemas.length,
     gated.length + cfgGated.length + ungated.length === FIXTURE.schemas.length,
     [gated.length, cfgGated.length, ungated.length, FIXTURE.schemas.length]);
  ck('exactly one gate is the master key',
     cfgGated.filter(function (s) { return s.enable.cfg === FIXTURE.masterKey; }).length === 1,
     cfgGated.map(function (s) { return s.enable.cfg; }));

  // THIS LOOP USED TO RUN OVER `gated` ALONE AND WENT QUIET. `gated` is 0
  // today, so every per-subsystem assertion under it stopped executing --
  // no FAIL, no NOT RUN, nothing in the output naming what had stopped. It
  // runs over every gated schema whatever the spelling now, and the case
  // above it fails loudly if that set is ever empty.
  const gatedAll = FIXTURE.schemas.filter(function (s) {
    const g = gateOf(s);
    return g && s.fields.some(function (f) {
      return f.in === g.in && f.path === g.path; }); });
  ck('there are ' + gatedAll.length + ' gate(s) to check at all — a loop over an '
     + 'empty set is not a pass', gatedAll.length > 0,
     [gated.length, cfgGated.length, gatedAll.length]);
  let clickable = 0, notInFile = 0, linkedChecked = 0;
  for (const s of gatedAll) {
    const g = gateOf(s);
    const si = FIXTURE.sections.findIndex(function (sec) { return sec.subsystems.indexOf(s.subsystem) >= 0; });
    select(si);
    const unit = unitOf(s);
    const rows = panel.find(function (n) { return n._cls().includes('field'); });
    // A location is now one identifying part per line, so a row is matched on
    // the parts themselves rather than on the arrow-joined string they used to
    // be concatenated into. Matching the list also asserts the stacking: a
    // regression that put the parts back on one line finds no row here.
    const locParts = function (n) {
      return (n.children || []).map(function (k) { return txt(k).trim(); });
    };
    const named = function (r, parts) {
      const want = JSON.stringify(parts);
      return r.find(function (n) {
        return n.tagName === 'CODE' && n._cls().includes('loc')
               && JSON.stringify(locParts(n)) === want; }).length > 0;
    };
    // A cfg field's location is the key alone -- pathParts drops the sidecar
    // for `in: 'cfg'`, because a cfg key does not live in a document.
    const gparts = g.in === 'cfg' ? String(g.path).split('.')
                                  : unit.split('#').concat(String(g.path).split('.'));
    const gateRows = rows.filter(function (r) { return named(r, gparts); });
    ck(s.subsystem + ': exactly one control row carries its gate',
       gateRows.length === 1, [gateRows.length, gparts]);
    if (gateRows.length !== 1) continue;
    const boxes = gateRows[0].find(function (n) { return n.tagName === 'INPUT' && n.type === 'checkbox'; });
    ck(s.subsystem + ': and it is a checkbox', boxes.length === 1, boxes.length);
    if (boxes.length !== 1) continue;
    const slot = slotOf(s, g);
    // A cfg key the file does not carry USED TO BE drawn disabled here, and
    // this branch asserted the disable. split-config-into-toggleable-slices
    // reverses that: CfgFile.set_value appends such a key, so the control is
    // live and the row says that saving adds it. The branch is kept, and still
    // counted, so that "not in the file" never becomes a silent state -- what
    // changed is which behaviour it asserts, not whether it is asserted.
    if (g.in === 'cfg' && !slot.present) {
      notInFile++;
      ck(s.subsystem + ': its key is not in the file, and the control is live '
         + 'rather than disabled — saving appends the key',
         boxes[0].disabled === false, boxes[0].disabled);
      ck(s.subsystem + ': and the row says the key is not in the file yet',
         txt(gateRows[0]).indexOf('not in the file yet') >= 0,
         txt(gateRows[0]));
    } else {
      clickable++;
      ck(s.subsystem + ': a gate whose key IS in the file is writable',
         boxes[0].disabled === false, boxes[0].disabled);
    }
    const want = !boxes[0].checked;
    boxes[0].checked = want;
    boxes[0].fire('change');
    ck(s.subsystem + ': the click lands on its own gate',
       !!slotOf(s, gateOf(s)).value === want, slotOf(s, gateOf(s)));
    // The key an invariant names: the bare cfg key, or file#section.path.
    const gkey = g.in === 'cfg' ? g.path : unit + '.' + g.path;
    const grp = (FIXTURE.schemas.reduce(function (acc, sc) {
      return acc.concat(sc.invariants || []); }, []))
      .filter(function (inv) { return inv.kind === 'linkedEnable'
                                 && inv.keys.indexOf(gkey) >= 0; })[0];
    if (grp) {
      linkedChecked++;
      const states = grp.keys.map(function (k) {
        if (W.cfg[k] !== undefined) return !!W.cfg[k].value;
        for (const u in W.json) if (k.indexOf(u + '.') === 0) {
          const pth = k.slice(u.length + 1);
          if (W.json[u][pth]) return !!W.json[u][pth].value;
        }
        return null;
      });
      ck(s.subsystem + ': every key its linked group names moved with it',
         states.every(function (v) { return v === want; }), [grp.keys, states]);
    }
  }
  ck('every gate ended in one branch or the other: ' + clickable + ' already in '
     + 'the file, ' + notInFile + ' appended by a save',
     clickable + notInFile === gatedAll.length,
     [clickable, notInFile, gatedAll.length]);
  // The lookup that went quiet: it only ever built the file#path spelling, so
  // once the linked pair moved back into the .cfg `grp` was undefined for every
  // subsystem and the assertion under it never ran, with nothing saying so.
  const declaredGroups = FIXTURE.schemas.reduce(function (acc, sc) {
    return acc.concat((sc.invariants || []).filter(function (i) {
      return i.kind === 'linkedEnable'; })); }, []);
  ck(linkedChecked + ' gate(s) resolved into one of the ' + declaredGroups.length
     + ' declared linkedEnable group(s) — a lookup that matches nothing is not '
     + 'a pass',
     declaredGroups.length === 0 || linkedChecked > 0,
     [declaredGroups.map(function (g) { return g.keys; }), linkedChecked]);

  // 6. no cell carries a button, in any grid on any page, and the only button
  //    on a row is the one that deletes it.
  //
  // REPLACES, 2026-09-07: two cases that asserted the unset button appeared on
  // the free-text columns and not on the adjustment ones. The control is gone,
  // so the assertion is inverted and widened -- every grid, not just the one
  // with adjustment columns -- and the delete-row button is asserted by name
  // so that removing the unset control cannot quietly remove that one too.
  // WHICH GRIDS THIS IS ABOUT: the EDITABLE ones. The delete button is what
  // removes a row, so a grid with no editable cell has no row to remove and
  // must not be asked for one.
  //
  // WAS, until Phase 4: a grid counted if some schema declared a table field
  // whose row[] length equalled the header count minus one. That is not a test
  // for editability, it is a coincidence of widths -- readonly grids were
  // excluded only because their header has no trailing blank column, which is
  // the same arithmetic by accident. Phase 4's overlay grids are readonly and
  // have a header the arithmetic happened to match, so 341 rows were counted
  // and 185 delete buttons found [measured]. The marker is read off the grid
  // itself now: a grid is editable when its cells carry inputs.
  let cellButtons = 0, rowsSeen = 0, deleters = 0, editable = 0, readonly = 0, matrices = 0;
  for (let i = 0; i < FIXTURE.sections.length; i++) {
    select(i);
    for (const g of panel.find(function (n) {
           return n.tagName === 'TABLE' && n._cls().includes('grid'); })) {
      // Three kinds on the page, and only one of them deletes rows. A grid
      // with no input is readonly. A MATRIX has inputs and fixed axes -- there
      // is no row to remove, so it ends in a coordinate, not a blank column.
      // gridFor appends that blank header cell exactly when it is not
      // readonly, so it is the marker, read off the grid rather than inferred
      // from a schema's column count.
      const inputs = g.find(function (n) { return n.tagName === 'INPUT'; });
      const ths = g.querySelector('thead').children[0].children;
      if (!inputs.length) { readonly++; continue; }
      if (txt(ths[ths.length - 1]) !== '') { matrices++; continue; }
      editable++;
      for (const tr of g.querySelector('tbody').children) {
        rowsSeen++;
        const cells = tr.children;
        for (let c = 0; c < cells.length - 1; c++)
          cellButtons += cells[c].find(function (n) { return n.tagName === 'BUTTON'; }).length;
        const last = cells[cells.length - 1]
          .find(function (n) { return n.tagName === 'BUTTON'; });
        if (last.length === 1 && last[0]._text === '\u2715') deleters++;
      }
    }
  }
  ck('rows were drawn to look at', rowsSeen > 0, rowsSeen);
  ck('all three kinds of grid were drawn: ' + editable + ' editable, '
     + readonly + ' readonly, ' + matrices + ' matrix — a page with only one '
     + 'kind proves nothing about the others',
     editable > 0 && readonly > 0 && matrices > 0,
     [editable, readonly, matrices]);
  ck('no editable cell carries a button of any kind', cellButtons === 0, cellButtons);
  ck('every row still ends in its delete button, off to the side',
     deleters === rowsSeen, [deleters, rowsSeen]);

  // 7. prose: paragraphs, not one line per source line
  let paras = 0, wrapped = 0;
  for (let i = 0; i < FIXTURE.sections.length; i++) {
    select(i);
    for (const d of panel.find(function (n) { return n._cls().includes('doc'); })) {
      paras++;
      if (d.textContent.indexOf('\n') >= 0) wrapped++;
    }
  }
  ck('prose is rendered, ' + paras + ' paragraph(s) across the page', paras > 0);
  ck('no paragraph carries a hard line break from the source array', wrapped === 0, wrapped);

  // 7b. where a field lives: one identifying part per line.
  //
  // The file, the section inside it and each step of the key path are three
  // different kinds of thing and used to share one line joined by an arrow and
  // a "#". This fails against that version: it asserts the separators are gone
  // from the rendered text and that every part is its own element.
  let locs = 0, joined = 0, notStacked = 0, empties = 0;
  for (let i = 0; i < FIXTURE.sections.length; i++) {
    select(i);
    for (const c of panel.find(function (n) {
           return n.tagName === 'CODE' && n._cls().includes('loc'); })) {
      locs++;
      const t = c.textContent;
      if (t.indexOf('\u2192') >= 0 || t.indexOf('#') >= 0) joined++;
      const kids = c.children || [];
      if (!kids.length || kids.some(function (k) { return k.tagName !== 'SPAN'; })) notStacked++;
      if (kids.some(function (k) { return !(k._text || '').trim(); })) empties++;
    }
  }
  ck('every field says where it lives, ' + locs + ' of them', locs > 0, locs);
  ck('no location is still one arrow-joined line', joined === 0, joined);
  ck('every identifying part is its own line', notStacked === 0, notStacked);
  ck('no line is blank', empties === 0, empties);

  // 8. a curve's grid drives its own chart.
  //
  // The grid used to be built with no way to tell the chart anything, so an
  // edit moved the number in the box and left the line where it was until the
  // whole panel was rebuilt -- leaving the section and coming back was the only
  // way to see a point move. This fails against that version.
  const curveOwner = FIXTURE.schemas.find(function (s) {
    return s.fields.some(function (f) { return f.ui === 'curve'; }); });
  ck('a subsystem draws a curve', !!curveOwner, curveOwner && curveOwner.subsystem);
  if (curveOwner) {
    select(FIXTURE.sections.findIndex(function (sec) {
      return sec.subsystems.indexOf(curveOwner.subsystem) >= 0; }));
    const chart = panel.find(function (n) { return n._cls().includes('chart'); })[0];
    const svg = chart.querySelector('svg');
    const plotted = function () {
      return svg.find(function (n) { return n.tagName === 'CIRCLE'; })
                .map(function (n) { return n.attrs.cy; }).join(',');
    };
    const before = plotted();
    ck('the curve plots the rows below it', before.length > 0, txt(svg));
    const grid = chart.parent.querySelector('table');
    const cell = grid.querySelector('tbody').children[0].children[1];
    const inp = cell.querySelector('input');
    inp.value = String(Number(inp.value) + 7);
    inp.fire('input');
    ck('editing a cell moves the line without leaving the section',
       plotted() !== before, [before, plotted()]);
  }

  // 9. requires, in both directions, through both entry points
  //
  // The nav toggle and the panel control share setBool so they cannot drift,
  // and that is asserted rather than assumed: every case below is run once
  // through each, and the two outcomes are compared.
  //
  // Nothing here names a key or a slice. The group is read off the declarations
  // the server sent, so these cases follow the declarations wherever the next
  // phase moves them, and they report it when there is nothing to exercise.
  const banners = document.querySelector('#banners');
  const btxt = function () { return txt(banners); };
  const reqDecl = FIXTURE.schemas.reduce(function (acc, s) {
    return acc.concat((s.invariants || [])
      .filter(function (i) { return i.kind === 'requires'; })
      .map(function (i) { return { sub: s.subsystem, key: i.key, needs: i.needs || [] }; }));
  }, []);
  ck('at least one requires group is declared to exercise — a page with none '
     + 'proves nothing about either direction',
     reqDecl.length > 0, reqDecl.length);
  const cfgTarget = (FIXTURE.schemas.find(function (s) { return (s.targets || {}).cfg; })
                     || { targets: {} }).targets.cfg;
  ck('the cfg file name is discoverable from the schemas, which is how the '
     + 'page normalises the two spellings without writing either down',
     !!cfgTarget, cfgTarget);
  // THE LOOKUP THAT WENT QUIET IN PHASE 1. linkedSlot searched only the json
  // side, so the moment a group's keys moved into the .cfg every one of them
  // resolved to null and ticking a gate moved only itself, silently. requires
  // spells its keys with the .cfg's own name in front of them, which is the
  // exact spelling that was unreachable; both halves are asserted here.
  ck('the declarations use the file-prefixed spelling, so the case that was '
     + 'unreachable is the one under test',
     reqDecl.some(function (d) { return d.key.indexOf(cfgTarget + '#') === 0; }),
     reqDecl.map(function (d) { return d.key; }));
  ck('every requires key resolves to a slot in the working copy — a lookup '
     + 'that matches nothing enforces nothing in either direction',
     requiresKeysUnresolved().length === 0, requiresKeysUnresolved());

  if (reqDecl.length && reqDecl[0].needs.length) {
    const DEPK = reqKey(reqDecl[0].key);
    const NEEDK = reqKey(reqDecl[0].needs[0]);
    const subFor = function (k) {
      return FIXTURE.schemas.find(function (s) { return ((s.enable || {}).cfg) === k; }); };
    const depS = subFor(DEPK), needS = subFor(NEEDK);
    ck('both keys of the group under test are some subsystem\'s own gate, so '
       + 'both have a control and a toggle to click',
       !!depS && !!needS, [DEPK, NEEDK]);

    const secOf = function (sub) {
      return FIXTURE.sections.findIndex(function (sec) {
        return sec.subsystems.indexOf(sub) >= 0; }); };
    const locOf = function (n) {
      return (n.children || []).map(function (k) { return txt(k).trim(); }); };
    // entry point 1: the checkbox in the panel, found by the location line
    // that names the key.
    const panelBox = function (sub, key) {
      select(secOf(sub));
      const rs = panel.find(function (n) { return n._cls().includes('field'); })
        .filter(function (r) {
          return r.find(function (n) {
            return n.tagName === 'CODE' && n._cls().includes('loc')
                   && JSON.stringify(locOf(n)) === JSON.stringify(String(key).split('.'));
          }).length > 0; });
      if (rs.length !== 1) return null;
      const bs = rs[0].find(function (n) {
        return n.tagName === 'INPUT' && n.type === 'checkbox'; });
      return bs.length === 1 ? bs[0] : null;
    };
    // entry point 2: the toggle in the nav, at the position its page holds
    // among the gated pages of its section.
    const navBox = function (sub) {
      const si = secOf(sub);
      const want = FIXTURE.sections[si].subsystems.filter(function (x) {
        return gateOf(schemaFor(x)); });
      const boxes = navItems()[si].find(function (n) {
        return n.tagName === 'INPUT' && n.type === 'checkbox'; });
      return boxes[want.indexOf(sub)] || null;
    };
    const ENTRIES = [{ n: 'panel control', box: panelBox },
                     { n: 'nav toggle', box: function (sub, key) { return navBox(sub); } }];

    const setRaw = function (key, val, present) {
      W.cfg[key].value = val;
      W.cfg[key].present = present === undefined ? true : present;
    };
    const reset = function () { REQ_NOTES = []; REQ_REFUSAL = null; };

    // ---- up: turning the dependent on turns on what it needs
    const upOutcome = [];
    for (const E of ENTRIES) {
      setRaw(DEPK, false); setRaw(NEEDK, false); reset(); render();
      const b = E.box(depS.subsystem, DEPK);
      ck(E.n + ': the dependent has a control to click', !!b, DEPK);
      if (!b) continue;
      ck(E.n + ': and the thing it needs really is off before the click, or '
         + 'the case proves nothing', W.cfg[NEEDK].value === false);
      b.checked = true;
      b.fire('change');
      ck(E.n + ': turning the dependent on turned on the key it needs',
         W.cfg[NEEDK].value === true, W.cfg[NEEDK]);
      ck(E.n + ': and marked that key present, which is what puts it in the '
         + 'save — a value with present false is never sent',
         W.cfg[NEEDK].present === true, W.cfg[NEEDK]);
      ck(E.n + ': the click moved a key other than the one clicked — moving '
         + 'only itself is the Phase 1 defect this is guarding',
         NEEDK !== DEPK && W.cfg[NEEDK].value === true);
      ck(E.n + ': a banner names the key that changed',
         btxt().indexOf(NEEDK) >= 0, btxt().slice(0, 400));
      ck(E.n + ': and names the slice that caused it, so the change is not '
         + 'silent', btxt().indexOf(DEPK) >= 0, btxt().slice(0, 400));
      upOutcome.push(JSON.stringify([W.cfg[DEPK].value, W.cfg[NEEDK].value,
                                     W.cfg[NEEDK].present, REQ_NOTES.length,
                                     REQ_REFUSAL]));
    }
    ck('both entry points left the working copy in the same state after the '
       + 'auto-enable — they share setBool and must not drift',
       upOutcome.length === 2 && upOutcome[0] === upOutcome[1], upOutcome);

    // ---- down: turning off what an enabled slice needs is refused
    const downOutcome = [];
    for (const E of ENTRIES) {
      setRaw(DEPK, true); setRaw(NEEDK, true); reset(); render();
      const b = E.box(needS.subsystem, NEEDK);
      ck(E.n + ': the needed key has a control to click', !!b, NEEDK);
      if (!b) continue;
      b.checked = false;
      b.fire('change');
      ck(E.n + ': turning off a key an enabled slice needs did not move it',
         W.cfg[NEEDK].value === true, W.cfg[NEEDK]);
      ck(E.n + ': and the control is redrawn where it was, not left showing a '
         + 'change that did not happen',
         E.box(needS.subsystem, NEEDK).checked === true);
      ck(E.n + ': the message names the dependent by key',
         btxt().indexOf(DEPK) >= 0, btxt().slice(0, 400));
      ck(E.n + ': and by title, so it names a slice and not only a key',
         btxt().indexOf(depS.title) >= 0, btxt().slice(0, 400));
      ck(E.n + ': the dependent was not turned off for the player either — '
         + 'off is refused, never resolved by moving something else',
         W.cfg[DEPK].value === true, W.cfg[DEPK]);
      downOutcome.push(JSON.stringify([W.cfg[DEPK].value, W.cfg[NEEDK].value,
                                       REQ_NOTES.length, !!REQ_REFUSAL]));
    }
    ck('both entry points refused identically', downOutcome.length === 2
       && downOutcome[0] === downOutcome[1], downOutcome);

    // ---- turning the dependent and its need off together is legal
    setRaw(DEPK, true); setRaw(NEEDK, true); reset(); render();
    let bd = panelBox(depS.subsystem, DEPK);
    bd.checked = false; bd.fire('change');
    ck('the dependent itself turns off freely — off is refused only while '
       + 'something needs the key', W.cfg[DEPK].value === false, W.cfg[DEPK]);
    let bn = panelBox(needS.subsystem, NEEDK);
    bn.checked = false; bn.fire('change');
    ck('and with the dependent off, the key it needed turns off too',
       W.cfg[NEEDK].value === false, W.cfg[NEEDK]);

    // ---- the fresh-install case: the dependent's key is not in the file
    //
    // tasks.md Phase 1 records that a linkedEnable group is only enforceable
    // once both keys are on disk, and that "the editor cannot protect a linked
    // group on a fresh install". requires does not have that hole HERE,
    // because the page falls back to the schema's declared default for a key
    // the file does not carry. check_schema still cannot: it grades what is in
    // the file and reports the absent key SKIPPED.
    const depDefault = reqDefault(DEPK);
    ck('the dependent declares a bool default, which the fresh-install case '
       + 'reads', typeof depDefault === 'boolean', depDefault);
    if (depDefault === true) {
      setRaw(DEPK, null, false); setRaw(NEEDK, true, true); reset(); render();
      const b2 = panelBox(needS.subsystem, NEEDK);
      ck('fresh install: the control for the needed key is still live even '
         + 'though the dependent key is not in the file', !!b2);
      if (b2) {
        b2.checked = false;
        b2.fire('change');
        ck('fresh install: a dependent whose key is absent still counts as on, '
           + 'and the switch is refused', W.cfg[NEEDK].value === true, W.cfg[NEEDK]);
        ck('fresh install: and the message still names the dependent',
           btxt().indexOf(DEPK) >= 0, btxt().slice(0, 400));
      }
    } else {
      console.log('  NOT RUN  the fresh-install refusal: ' + DEPK
                  + ' declares default ' + JSON.stringify(depDefault)
                  + ', so an absent key is not on and there is nothing to refuse');
    }

    // ---- a violation nobody on this page made
    setRaw(DEPK, true); setRaw(NEEDK, false); reset(); render();
    ck('a dependent on with its need off is reported, even though no switch '
       + 'on this page made it — this is the state check_schema grades '
       + 'INVARIANT, and the one it SKIPs when the key is absent',
       btxt().indexOf(DEPK) >= 0 && btxt().indexOf(NEEDK) >= 0,
       btxt().slice(0, 400));
    ck('and nothing was turned on to paper over it — widening a config the '
       + 'player did not touch is the failure mode, not the fix',
       W.cfg[NEEDK].value === false, W.cfg[NEEDK]);
  }

  // ---- a chain, and a cycle, neither of which is declared on disk
  //
  // The two declarations that exist are one hop each, so transitivity would
  // otherwise be an untested claim. Three gate keys no declaration names are
  // wired into a chain in the loaded model -- not on disk, nothing under
  // schema/ is touched -- and the same three into a cycle. A one-hop
  // implementation fails the chain case; one without a termination bound
  // hangs on the cycle.
  const namedKeys = {};
  for (const d of reqDecl) { namedKeys[reqKey(d.key)] = 1;
    for (const n of d.needs) namedKeys[reqKey(n)] = 1; }
  for (const s of FIXTURE.schemas)
    for (const i of (s.invariants || []))
      if (i.kind === 'linkedEnable') for (const k of i.keys) namedKeys[reqKey(k)] = 1;
  const free = FIXTURE.schemas
    .filter(function (s) { return (s.enable || {}).cfg
             && !namedKeys[s.enable.cfg]
             && s.enable.cfg !== FIXTURE.masterKey
             && W.cfg[s.enable.cfg] !== undefined; })
    .map(function (s) { return s.enable.cfg; });
  ck('three unencumbered gate keys are available to wire into a chain',
     free.length >= 3, free.length);
  if (free.length >= 3) {
    const A = free[0], B = free[1], C = free[2];
    const host = MODEL.schemas[0];
    const keep = host.invariants || [];
    const chainInv = function (pairs) {
      return pairs.map(function (p) {
        return { kind: 'requires', key: p[0], needs: [p[1]],
                 reason: 'wired by the render test, not declared on disk' }; });
    };
    const aSub = FIXTURE.schemas.find(function (s) { return (s.enable || {}).cfg === A; });
    const aBox = function () {
      const si = FIXTURE.sections.findIndex(function (sec) {
        return sec.subsystems.indexOf(aSub.subsystem) >= 0; });
      const want = FIXTURE.sections[si].subsystems.filter(function (x) {
        return gateOf(schemaFor(x)); });
      const boxes = navItems()[si].find(function (n) {
        return n.tagName === 'INPUT' && n.type === 'checkbox'; });
      return boxes[want.indexOf(aSub.subsystem)] || null;
    };

    host.invariants = keep.concat(chainInv([[A, B], [B, C]]));
    for (const k of [A, B, C]) { W.cfg[k].value = false; W.cfg[k].present = true; }
    REQ_NOTES = []; REQ_REFUSAL = null; render();
    let ab = aBox();
    ck('the chain case has a toggle to click', !!ab, A);
    if (ab) {
      ab.checked = true; ab.fire('change');
      ck('a chain is followed past the first hop: A turned on B',
         W.cfg[B].value === true, W.cfg[B]);
      ck('and past the second: B turned on C. A one-hop closure fails here',
         W.cfg[C].value === true, W.cfg[C]);
      ck('and both are named, not just the first',
         btxt().indexOf(B) >= 0 && btxt().indexOf(C) >= 0, btxt().slice(0, 500));
    }

    host.invariants = keep.concat(chainInv([[A, B], [B, A]]));
    for (const k of [A, B, C]) { W.cfg[k].value = false; W.cfg[k].present = true; }
    REQ_NOTES = []; REQ_REFUSAL = null; render();
    ab = aBox();
    if (ab) {
      ab.checked = true; ab.fire('change');
      ck('a cycle settles instead of spinning: both keys ended on',
         W.cfg[A].value === true && W.cfg[B].value === true,
         [W.cfg[A], W.cfg[B]]);
      ck('and the page does not report an unsettled closure for a cycle that '
         + 'did settle',
         btxt().indexOf('did not settle') < 0, btxt().slice(0, 500));
    }
    host.invariants = keep;
    for (const k of [A, B, C]) {
      W.cfg[k].value = MODEL.values.cfg[k].value;
      W.cfg[k].present = MODEL.values.cfg[k].present;
    }
    REQ_NOTES = []; REQ_REFUSAL = null; render();
  }

  // 10. the two nav groups Phase 4 fills: the packs and the constants
  //
  // Nothing here names a class, a file or a column. The pack sections are the
  // ones whose schema declares overlays; the constants section is the one
  // whose schema also declares a reference field.
  const ovOf = function (s) {
    const o = (s.targets || {}).overlays;
    return o ? (Array.isArray(o) ? o : [o]) : []; };
  const packSubs = FIXTURE.schemas.filter(function (s) { return ovOf(s).length; });
  ck('more than one subsystem declares overlays, so the cases below are not '
     + 'one page pretending to be a group', packSubs.length > 1, packSubs.length);
  const secIndexOf = function (sub) {
    return FIXTURE.sections.findIndex(function (sec) {
      return sec.subsystems.indexOf(sub) >= 0; }); };
  let drawnFiles = 0, drawnRows = 0, refJoined = 0;
  for (const s of packSubs) {
    const si = secIndexOf(s.subsystem);
    ck(s.subsystem + ': has a section of its own to draw in', si >= 0, s.subsystem);
    if (si < 0) continue;
    select(si);
    const files = ovOf(s);
    // ONE SLICE, ONE TOGGLE, however many files.
    //
    // CORRECTION, Phase 5. This counted checkboxes across the whole PANEL and
    // asserted exactly one:
    //
    //     const boxes = panel.find(n => n.tagName === 'INPUT' && n.type === 'checkbox');
    //     ck(... + ': its N file(s) sit under exactly one toggle ...',
    //        boxes.length === 1, boxes.length);
    //
    // A panel is a SECTION, and a section may present several subsystems --
    // design.md section 12: "Weapons is one section holding three tables",
    // with the files and the toggles staying separate. So the correct panel
    // for that section carries three checkboxes, one per slice, and this
    // reported 3 against an expected 1 [measured on David's machine,
    // Logs/gates-phase5.txt, and reproduced here].
    //
    // IT WAS PASSING FOR A REASON THAT WAS NOT THE ONE IT CLAIMED. Until
    // Phase 5 every overlay-owning subsystem sat in a section of its own, so
    // "one toggle in the panel" and "one toggle per slice" were the same
    // number in every case it had ever seen, and it could not tell them
    // apart. GearClasses is the first overlay-owning subsystem to share a
    // section, and it separated them.
    //
    // What the case is FOR is that a slice's files sit under that slice's own
    // switch, so that is what it reads now: the card carrying the gate is
    // found, and the files have to be in THAT card -- not merely somewhere on
    // the page, which is what would let one escape.
    const locParts2 = function (n) {
      return (n.children || []).map(function (k) { return txt(k).trim(); }); };
    const gateKey = ((s.enable || {}).cfg || '').split('.');
    const cards2 = panel.children.filter(function (c) { return c._cls().includes('card'); });
    const owns = function (c) {
      return c.find(function (n) {
        return n.tagName === 'CODE' && n._cls().includes('loc')
               && JSON.stringify(locParts2(n)) === JSON.stringify(gateKey); }).length > 0; };
    const mine = cards2.filter(owns);
    ck(s.subsystem + ': exactly one card in its section carries its gate',
       mine.length === 1, [mine.length, gateKey]);
    const card = mine[0];
    // A SUBSYSTEM'S BLOCK IS TWO CARDS, and after 2026-09-14 the gate is in
    // the first of them.
    //
    // WAS: `const ct = txt(card)` and every file had to be inside THAT card.
    // That held while the gate was an ordinary field row in the body card, so
    // the card carrying the gate and the card carrying the files were the same
    // card. Item 3 moved the gate up into the header card -- it was being
    // drawn three times across the two, and David asked for one control -- so
    // "the card with the switch" and "the card with the files" are now the
    // header and the body of one subsystem, in that order.
    //
    // NOT LOOSENED TO FIT. The statement is still "a slice's files sit under
    // that slice's own switch and nobody else's"; what changed is that the
    // block is a header card plus the body card that follows it. The pairing
    // is checked rather than assumed: the following card counts only if it
    // carries no gate of its own, so a subsystem that draws no body (its
    // header is followed by the NEXT subsystem's header) cannot silently
    // borrow a neighbour's files.
    const anyGateIn = function (c) {
      return packSubs.some(function (o) {
        return (o.enable || {}).cfg && c.find(function (n) {
          return n.tagName === 'CODE' && n._cls().includes('loc')
                 && JSON.stringify(locParts2(n))
                    === JSON.stringify(String(o.enable.cfg).split('.')); }).length > 0; }); };
    const after = card ? cards2[cards2.indexOf(card) + 1] : null;
    const block = card ? [card].concat(after && !anyGateIn(after) ? [after] : []) : [];
    if (card) {
      const boxes = block.reduce(function (acc, c) {
        return acc.concat(c.find(function (n) {
          return n.tagName === 'INPUT' && n.type === 'checkbox'; })); }, []);
      ck(s.subsystem + ': its ' + files.length + ' file(s) sit in the block '
         + 'carrying its own gate, and that block holds exactly one toggle — '
         + 'flipping it skips all of them', boxes.length === 1, boxes.length);
      const ct = block.map(txt).join('\n');
      for (const rel of files)
        ck(s.subsystem + ': ' + rel.split('/').pop() + ' is inside that block, '
           + 'not merely somewhere on the page', ct.indexOf(rel) >= 0, rel);
      // and no OTHER slice's gate is in it, which is the other way a file
      // could end up under the wrong switch
      const strays = packSubs.filter(function (o) {
        return o !== s && ((o.enable || {}).cfg
               && block.some(function (c) {
                    return c.find(function (n) {
                      return n.tagName === 'CODE' && n._cls().includes('loc')
                             && JSON.stringify(locParts2(n))
                                === JSON.stringify(String(o.enable.cfg).split('.')); }).length > 0; })); });
      ck(s.subsystem + ': and no other slice\'s gate is drawn in it',
         strays.length === 0, strays.map(function (o) { return o.subsystem; }));
    }
    // The section-level count is still asserted, against the right
    // denominator: one toggle per gated subsystem the section presents. A
    // fourth switch appearing from nowhere is still a failure.
    const gated2 = FIXTURE.sections[si].subsystems.filter(function (sub) {
      const sc = FIXTURE.schemas.find(function (x) { return x.subsystem === sub; });
      return sc && (sc.enable || {}).cfg; });
    ck(s.subsystem + ': its section draws one toggle per gated page it '
       + 'presents, and no more — ' + gated2.length + ' here',
       panel.find(function (n) {
         return n.tagName === 'INPUT' && n.type === 'checkbox'; }).length
       === gated2.length,
       [panel.find(function (n) {
          return n.tagName === 'INPUT' && n.type === 'checkbox'; }).length, gated2]);
    const t2 = txt(panel);
    for (const rel of files) {
      ck(s.subsystem + ': the page names ' + rel.split('/').pop(),
         t2.indexOf(rel) >= 0, rel);
      drawnFiles++;
      const ent = FIXTURE.values.overlays[rel];
      ck(s.subsystem + ': and the server sent its rows', !!ent && !!ent.rows.length,
         ent && ent.rows.length);
      if (!ent) continue;
      drawnRows += ent.rows.length;
      // every id in the file is on the page
      const missing = ent.rows.filter(function (r) {
        return t2.indexOf(String(r.cells[0])) < 0; });
      ck(s.subsystem + '/' + rel.split('/').pop() + ': every id in the file is '
         + 'drawn, so no row is dropped by the grouping',
         missing.length === 0, missing.slice(0, 3).map(function (r) { return r.cells[0]; }));
    }
    // the columns are the FILE's, not a static row[]
    const declaredCols = (s.fields || []).reduce(function (a, f) {
      return a.concat((f.row || []).map(function (c) { return c.name; })); }, []);
    for (const rel of files) {
      const ent = FIXTURE.values.overlays[rel];
      if (!ent) continue;
      for (const c of ent.columns)
        if (!c.control && c.name)
          ck(s.subsystem + '/' + rel.split('/').pop() + ': its header column '
             + c.name + ' is on the page', t2.indexOf(c.name) >= 0, c.name);
      ck(s.subsystem + '/' + rel.split('/').pop() + ': and those columns come '
         + 'from the file, not from a row[] — its schema declares none for it',
         declaredCols.indexOf(ent.columns[1] ? ent.columns[1].name : '') < 0
         || (s.fields || []).every(function (f) { return f.in === 'reference'; }),
         declaredCols);
    }
    // a reference field, where one exists, is joined rather than drawn twice
    const ref = (s.fields || []).find(function (f) { return f.in === 'reference'; });
    if (ref) {
      refJoined++;
      const refTable = FIXTURE.values.tables[s.subsystem + '|' + ref.path];
      ck(s.subsystem + ': its reference table reached the page', !!refTable,
         Object.keys(FIXTURE.values.tables));
      if (refTable) {
        const gcol = ref.groupBy;
        ck(s.subsystem + ': the server named a grouping column for it', !!gcol, gcol);
        const groups = {};
        for (const r of refTable.rows) {
          const g = String(r.cells[gcol]);
          groups[g] = (groups[g] || 0) + 1;
        }
        ck(s.subsystem + ': every group name is drawn as a heading — '
           + Object.keys(groups).length + ' of them',
           Object.keys(groups).every(function (g) { return t2.indexOf(g) >= 0; }),
           Object.keys(groups).filter(function (g) { return t2.indexOf(g) < 0; }));
        const heads = panel.find(function (n) { return n._cls().includes('grouphead'); });
        ck(s.subsystem + ': one group heading per group, and the biggest group '
           + 'is first', heads.length === Object.keys(groups).length
           && txt(heads[0]).indexOf(Object.keys(groups).sort(function (a, b) {
                return groups[b] - groups[a] || (a < b ? -1 : 1); })[0]) === 0,
           [heads.length, Object.keys(groups).length, heads.length ? txt(heads[0]) : '']);
        // the shipped value sits beside the override, on the same row
        const labCol = (ref.row || []).find(function (c) {
          return c.type === 'string' && c.name !== gcol; });
        const valCol = (ref.row || []).find(function (c) {
          return c.type === 'int' && c.name !== ref.sortBy; });
        ck(s.subsystem + ': the reference declares a label and a shipped value '
           + 'to put beside the override', !!labCol && !!valCol,
           (ref.row || []).map(function (c) { return c.name; }));
        if (labCol && valCol) {
          const bad = refTable.rows.filter(function (r) {
            const row = panel.find(function (n) {
              return n.tagName === 'TR'
                     && txt(n).indexOf(String(r.cells[labCol.name])) >= 0; })[0];
            return !row || txt(row).indexOf(String(r.cells[valCol.name])) < 0;
          });
          ck(s.subsystem + ': every rule is drawn on one row carrying both its '
             + 'name and the value the game ships',
             bad.length === 0, bad.slice(0, 3).map(function (r) {
               return r.cells[labCol.name]; }));
        }
        // the variant pairs are adjacent, and badged with the remainder
        const nameOf = function (r) { return labCol ? String(r.cells[labCol.name]) : ''; };
        const cand = [];
        for (const r of refTable.rows) for (const b of refTable.rows) {
          const n = nameOf(r), bn = nameOf(b);
          if (r === b || !n || !bn || bn.length >= n.length) continue;
          if (n.indexOf(bn) === 0) cand.push({ r: r, b: b, suffix: n.slice(bn.length).trim() });
        }
        const tally = {};
        for (const c of cand) tally[c.suffix] = (tally[c.suffix] || 0) + 1;
        const best = Object.keys(tally).sort(function (a, b) {
          return tally[b] - tally[a] || (a < b ? -1 : 1); })[0];
        const fam = cand.filter(function (c) { return c.suffix === best; });
        ck(s.subsystem + ': a variant family was found to check adjacency on',
           fam.length > 1, fam.length);
        const trs = panel.find(function (n) { return n.tagName === 'TR'; });
        const idx = function (r) {
          return trs.findIndex(function (n) {
            return txt(n).indexOf(String(r.cells[labCol.name])) >= 0; }); };
        const notAdjacent = fam.filter(function (c) {
          const a = idx(c.b), z = idx(c.r);
          return a < 0 || z < 0 || z !== a + 1; });
        ck(s.subsystem + ': every variant is drawn immediately after the row it '
           + 'varies, so "faster early, unchanged later" reads as two rows',
           notAdjacent.length === 0,
           notAdjacent.slice(0, 3).map(function (c) { return nameOf(c.r); }));
        ck(s.subsystem + ': and each variant carries the remainder as its badge',
           fam.every(function (c) {
             const z = trs[idx(c.r)];
             return z && txt(z).indexOf(c.suffix) >= 0; }), best);
        // the other family is NOT paired
        const other = cand.filter(function (c) { return c.suffix !== best; });
        ck(s.subsystem + ': a smaller prefix family exists and is NOT indented '
           + 'under anything — a prefix is not a variant', other.length > 0,
           Object.keys(tally));
        // NOT "its text does not contain the remainder": these rows END in
        // it -- that is why they matched a prefix at all -- so a text search
        // would fail on a page that is correct. The badge is an element, and
        // that is what is looked for.
        ck(s.subsystem + ': and none of its rows carries a badge — a prefix is '
           + 'not a variant',
           other.every(function (c) {
             const z = trs[idx(c.r)];
             return !z || z.find(function (n) {
               return n._cls().includes('pill'); }).length === 0; }),
           other.map(function (c) { return nameOf(c.r); }));
        // and it is not drawn a second time in the reference card
        const cards = panel.children.filter(function (c) { return c._cls().includes('card'); });
        const refCards = cards.filter(function (c) { return txt(c).indexOf('For reference') === 0; });
        ck(s.subsystem + ': its 76 rows are not drawn twice — no separate '
           + 'reference card for a table already joined beside the overlay',
           refCards.length === 0, refCards.map(txt).map(function (x) { return x.slice(0, 40); }));
      }
    }
  }
  ck('overlay files were actually drawn: ' + drawnFiles + ' file(s), '
     + drawnRows + ' row(s) — a group of empty panels would pass every case '
     + 'above that looks for something in the text',
     drawnFiles > 10 && drawnRows > 100, [drawnFiles, drawnRows]);
  ck('exactly one overlay-owning subsystem also carries a reference field',
     refJoined === 1, refJoined);
  // AN OVERLAY GRID OFFERS AN EDIT ON ITS LEVER CELLS, AND NOWHERE ELSE.
  //
  // CORRECTION, 2026-09-14. This block asserted the opposite, once per
  // overlay-owning subsystem, and its name was:
  //
  //   'its overlay grids offer no editable cell - this editor never writes
  //    an overlay'      (condition: !!mycard && inputs.length === 0)
  //
  // David reversed that rule on 2026-09-14 -- lever and override columns
  // become editable, identity columns, control columns and the key column do
  // not. The reason the old rule carried, that scripts/rules_to_overlays.py
  // was the only thing that might write these files, had already lapsed when
  // Phase 9 retired that script together with its subject.
  //
  // WHAT IS ASSERTED NOW, AND WHY IT IS A RANGE AND NOT A COUNT. The server
  // publishes `editable` per column, so the number of cells a client MAY put
  // an input on is exactly computable and is the upper bound: an input beyond
  // it is an input on an identity, control or key cell. It also publishes
  // `constant` per column, which David asked for so that a column that never
  // changes within a table can be SUPPRESSED -- a suppressed column renders no
  // input, so an exact count would forbid the suppression he asked for. The
  // lower bound is therefore the editable cells of columns that VARY, which no
  // suppression rule may remove. A page that drew no input at all fails the
  // lower bound; a page that drew one on a key column fails the upper.
  for (const s of packSubs) {
    const si = secIndexOf(s.subsystem);
    if (si < 0) continue;
    select(si);
    // Scoped to the slice's own card for the same reason as above: a section
    // may present several subsystems, and another one's controls are not this
    // one's to account for.
    const lp = function (n) {
      return (n.children || []).map(function (k) { return txt(k).trim(); }); };
    const gk = ((s.enable || {}).cfg || '').split('.');
    // The gate card, and the body card after it. Since 2026-09-14 the gate
    // sits in the header card and the grids in the body card below it, so the
    // slice's block is the pair; before that it was one card and this took the
    // one. The scoping is the point either way -- a section may present
    // several subsystems, and another one's boxes are not this one's to count.
    const mycards = panel.children.filter(function (c) { return c._cls().includes('card'); });
    const gcard = mycards.filter(function (c) {
      return c.find(function (n) {
        return n.tagName === 'CODE' && n._cls().includes('loc')
               && JSON.stringify(lp(n)) === JSON.stringify(gk); }).length > 0; })[0];
    const mycard = gcard ? mycards[mycards.indexOf(gcard) + 1] || gcard : null;
    const inputs = (mycard || panel).find(function (n) {
      return n.tagName === 'INPUT' && n.type !== 'checkbox'; });
    let maxCells = 0, minCells = 0, ident = 0, ctrl = 0;
    for (const rel of ovOf(s)) {
      const ent = FIXTURE.values.overlays[rel];
      if (!ent || !ent.writable) continue;
      for (let i = 0; i < ent.columns.length; i++) {
        if (ent.editable[i]) {
          maxCells += ent.rows.length;
          if (ent.constant[i] === null) minCells += ent.rows.length;
        } else if (ent.roles[i] === 'identity' || i === 0) {
          ident += ent.rows.length;
        } else if (ent.roles[i] === 'control') {
          ctrl += ent.rows.length;
        }
      }
    }
    ck(s.subsystem + ': the server marks lever cells editable on its sheets, '
       + 'or the two cases below have nothing to be about — ' + maxCells
       + ' editable, ' + ident + ' identity/key, ' + ctrl + ' control',
       maxCells > 0 && ident > 0, [maxCells, ident, ctrl]);
    ck(s.subsystem + ': its overlay grids offer an input on every lever cell '
       + 'of every column that VARIES — at least ' + minCells + ', got '
       + inputs.length + '. The server sends `editable` and `constant`; '
       + 'app.html must render an input where editable is true and may '
       + 'suppress only a column whose `constant` is not null.',
       !!mycard && inputs.length >= minCells, [inputs.length, minCells, !!mycard]);
    ck(s.subsystem + ': and no input anywhere else — at most ' + maxCells
       + ' (one per editable cell), got ' + inputs.length + '. An input beyond '
       + 'that count is an input on an identity, control or key cell, which '
       + 'this editor never writes.',
       inputs.length <= maxCells, [inputs.length, maxCells]);
  }

  // ---- THE THREE THINGS 2026-09-14 CHANGED, ASSERTED ON THE RENDERED PAGE
  //
  // Each of these states a NEW truth. None of them replaces a case by relaxing
  // it: the counts above moved because the page changed, and these say what it
  // changed into. A page that quietly went back to the old behaviour would
  // pass every case above and fail these.
  //
  // One helper for all three: the sheet's own block, found by the path the
  // server sent for it, which is a value and not a name this file spells.
  const sheetBlock = function (rel) {
    return panel.find(function (n) {
      return n._cls().includes('field') && n.find(function (k) {
        return k.tagName === 'CODE' && k._cls().includes('loc')
               && txt(k).trim() === rel; }).length > 0; })[0] || null; };

  // 1. A ONE-ROW SHEET IS A GRID LIKE ANY OTHER.
  //
  // It used to be drawn as a stack of labelled values, on the reasoning that a
  // header row above a single line is a table of one. David overruled that on
  // 2026-09-14 after seeing the page. The consequence that matters is not the
  // shape: it is that the row's lever cells must take an edit on the same
  // terms as every other sheet's, which is the complaint this whole wave is
  // about.
  let oneRowSeen = 0;
  for (const s of packSubs) {
    const si = secIndexOf(s.subsystem);
    if (si < 0) continue;
    for (const rel of ovOf(s)) {
      const ent = FIXTURE.values.overlays[rel];
      if (!ent || !ent.present || ent.error || ent.rows.length !== 1) continue;
      select(si);
      const blk = sheetBlock(rel);
      ck(rel.split('/').pop() + ': its one row is drawn, and drawn as a grid',
         !!blk && blk.find(function (n) {
           return n.tagName === 'TABLE' && n._cls().includes('grid'); }).length === 1,
         !!blk);
      if (!blk) continue;
      oneRowSeen++;
      const hdr = blk.find(function (n) { return n.tagName === 'TH'; });
      ck(rel.split('/').pop() + ': with a header row, the key column named in '
         + 'it, one row of cells under it — the shape every other sheet has',
         hdr.length > 1 && hdr.some(function (h) {
           return txt(h).indexOf(ent.keyColumn) >= 0; }),
         [hdr.length, ent.keyColumn]);
      const ins = blk.find(function (n) {
        return n.tagName === 'INPUT' && n.type !== 'checkbox'; });
      // The upper bound is the editable columns still on screen; the lower
      // bound is that there is a box at all, which is the whole complaint.
      const drawn = ent.columns.filter(function (c, i) {
        return i > 0 && ent.editable[i] && !ent.hidden[i]; }).length;
      ck(rel.split('/').pop() + ': and its lever cells take an edit — ' + drawn
         + ' editable column(s) on screen, ' + ins.length + ' box(es). A form '
         + 'with no boxes is what this replaced',
         ins.length === drawn && ins.length > 0, [ins.length, drawn]);
    }
  }
  ck('the fixture carries a one-row sheet, so the three cases above are about '
     + 'a page that was rendered rather than a branch nobody took',
     oneRowSeen > 0, oneRowSeen);

  // 2. A COLUMN HIDDEN BY NAME IS OFF THE GRID, IN THE MODEL, AND SAYS WHY.
  //
  // HIDING IS NEVER DROPPING is the standing rule here, written after a hidden
  // matrix axis nearly lost an override. The declared hide is a second, newer
  // reason a column can be off the screen, and it has to meet the same
  // standard the constancy rule already meets.
  let hidSheets = 0, hidCols = 0;
  for (const s of packSubs) {
    const si = secIndexOf(s.subsystem);
    if (si < 0) continue;
    for (const rel of ovOf(s)) {
      const ent = FIXTURE.values.overlays[rel];
      if (!ent || !ent.present || ent.error) continue;
      const hid = ent.columns.filter(function (c, i) { return !!ent.hidden[i]; })
                             .map(function (c) { return c.name; });
      if (!hid.length) continue;
      select(si);
      const blk = sheetBlock(rel);
      if (!blk) continue;
      hidSheets++; hidCols += hid.length;
      const heads = blk.find(function (n) { return n.tagName === 'TH'; })
                       .map(function (h) { return txt(h).replace(/​/g, ''); });
      ck(rel.split('/').pop() + ': its ' + hid.length + ' declared-hidden '
         + 'column(s) are not in the grid header',
         hid.every(function (n) {
           return !heads.some(function (h) { return h.indexOf(n) >= 0; }); }),
         [hid, heads]);
      // IN THE MODEL, not merely absent from the screen.
      ck(rel.split('/').pop() + ': and every one of them is still in the model '
         + 'the save is built from, with its role and its editability',
         hid.every(function (n) {
           const i = ent.columns.findIndex(function (c) { return c.name === n; });
           return i > 0 && !!ent.roles[i] && typeof ent.editable[i] === 'boolean'; }),
         hid);
      // AND THE READER IS TOLD THE RIGHT REASON. A column hidden for being
      // metadata must not be described as one that never changes.
      const bt = txt(blk);
      ck(rel.split('/').pop() + ': the fold names each hidden column with the '
         + 'reason that applies to it, not with "never changes"',
         hid.every(function (n) {
           const j = bt.indexOf('Hidden: ' + n + ' ');
           return j >= 0 && bt.indexOf('Collapsed: ' + n + ' ') < 0; }),
         hid.map(function (n) { return [n, bt.indexOf('Hidden: ' + n + ' ')]; }));
      // AND IT COMES BACK. The button is the restore affordance the constancy
      // rule already ships; a declared hide shares it.
      const btn = blk.find(function (n) {
        return n.tagName === 'BUTTON' && n._cls().includes('colbtn'); })[0];
      ck(rel.split('/').pop() + ': and one click puts them back on the grid',
         !!btn, !!btn);
      if (btn) {
        btn.fire('click');
        const blk2 = sheetBlock(rel);
        const heads2 = (blk2 ? blk2.find(function (n) { return n.tagName === 'TH'; }) : [])
                         .map(function (h) { return txt(h).replace(/​/g, ''); });
        ck(rel.split('/').pop() + ': restored — every hidden column is in the '
           + 'header once the reader asks for it',
           hid.every(function (n) {
             return heads2.some(function (h) { return h.indexOf(n) >= 0; }); }),
           [hid, heads2]);
        const btn2 = blk2 && blk2.find(function (n) {
          return n.tagName === 'BUTTON' && n._cls().includes('colbtn'); })[0];
        if (btn2) btn2.fire('click');       // put the view back
      }
    }
  }
  ck('the declared hide reaches the rendered page at all: ' + hidCols
     + ' column(s) over ' + hidSheets + ' sheet(s). A table nobody matched '
     + 'would pass every case above by having nothing to check',
     hidSheets > 0 && hidCols > 0, [hidSheets, hidCols]);

  // every section renders without throwing
  for (let i = 0; i < FIXTURE.sections.length; i++) {
    select(i);
    ck('section ' + FIXTURE.sections[i].id + ' renders', panel.children.length > 0);
  }

  console.log('\nnode render of app.html: ' + pass + ' passed, ' + fail.length + ' failed');
  process.exit(fail.length ? 1 : 0);
}, 0);
'''


DOM_ASSERTS_OUTSIDE = r'''
let pass = 0, fail = [];
function ck(name, cond, detail) {
  if (cond) { pass++; console.log('  PASS  ' + name); }
  else { fail.push(name); console.log('  FAIL  ' + name + (detail === undefined ? '' : '  ' + JSON.stringify(detail))); }
}
const panel = document.querySelector('#panel');
const nav = document.querySelector('#index');
const txt = function (n) { return n.textContent.replace(/\s+/g, ' ').trim(); };
setTimeout(function () {
  // The section holding the windowed matrix, found from the schema that
  // declares it. `subsystems.length > 1` used to identify it because it was the
  // only merged section on the page; it is not since 2026-09-13.
  const owner = FIXTURE.schemas.filter(function (s) {
    return s.fields.some(function (f) { return f.ui === 'matrix'; }); })[0];
  const gi = FIXTURE.sections.findIndex(function (s) {
    return s.subsystems.indexOf(owner.subsystem) >= 0; });
  ck('the section holding the windowed matrix was found', gi >= 0, owner.subsystem);
  nav.find(function (n) { return n._cls().includes('navitem'); })[gi].fire('click');
  const grids = panel.find(function (n) { return n.tagName === 'TABLE' && n._cls().includes('grid'); });
  const headersOf = function (g) {
    return g.querySelector('thead').find(function (n) { return n.tagName === 'TH'; }).map(txt);
  };
  const axisGrids = grids.filter(function (g) { return headersOf(g)[0].indexOf('\\') > 0; });
  const h = headersOf(axisGrids[0]);
  ck('the column outside the window is drawn, because a value sits in it',
     h.slice(1).join(',') === '0,1,2,3,4,5,6,7,8,9,10', h);
  ck('and the reference grid follows it, so the two still line up',
     JSON.stringify(headersOf(axisGrids[1])) === JSON.stringify(h), headersOf(axisGrids[1]));
  ck('the page says why that column is there',
     txt(panel).indexOf('would normally be hidden') > 0, txt(panel).slice(-400));
  ck('the value itself is on screen',
     axisGrids[0].querySelector('tbody').find(function (n) {
       return n.tagName === 'INPUT' && n.value === '0.02'; }).length === 1);
  console.log('\nnode render (hidden column occupied): ' + pass + ' passed, ' + fail.length + ' failed');
  process.exit(fail.length ? 1 : 0);
}, 0);
'''


def selftest_dom(model, asserts=None):
    """-> 0 pass, 1 fail, 2 node unavailable."""
    node = shutil.which('node') or shutil.which('nodejs')
    if not node:
        print('node is not on PATH. app.html was NOT rendered.')
        return 2
    prog = dom_driver(json.dumps(model), asserts)
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'render.js')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(prog)
        r = subprocess.run([node, p], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.returncode


def app_html_syntax(path=None):
    """node --check over every <script> block. -> (ok, detail)."""
    node = shutil.which('node') or shutil.which('nodejs')
    if not node:
        return None, 'node is not on PATH'
    with open(path or APP_HTML, encoding='utf-8') as f:
        src = f.read()
    blocks = re.findall(r'<script>(.*?)</script>', src, re.S)
    if len(blocks) != 2:
        return False, 'expected two <script> blocks, found %d' % len(blocks)
    with tempfile.TemporaryDirectory() as td:
        for i, b in enumerate(blocks):
            p = os.path.join(td, 'block%d.js' % i)
            with open(p, 'w', encoding='utf-8') as f:
                f.write(b.replace('__CKF_TOKEN__', 'x'))
            r = subprocess.run([node, '--check', p], capture_output=True, text=True)
            if r.returncode != 0:
                return False, 'block %d: %s' % (i, r.stderr.strip()[:300])
    return True, 'both blocks parse'


def extract_pure_js(path=None):
    """The block of app.html between the two sentinels: functions with no DOM
    and no network, so they can be run outside a browser."""
    with open(path or APP_HTML, encoding='utf-8') as f:
        src = f.read()
    i = src.find(PURE_BEGIN)
    j = src.find(PURE_END)
    if i < 0 or j < 0:
        raise RuntimeError('app.html has no %s / %s region' % (PURE_BEGIN, PURE_END))
    return src[i + len(PURE_BEGIN):j]


def selftest_js():
    """-> 0 pass, 1 fail, 2 node not available (reported, never counted as a pass)."""
    import subprocess
    node = shutil.which('node') or shutil.which('nodejs')
    if not node:
        print('node is not on PATH. app.html\'s JavaScript was NOT exercised.')
        return 2
    try:
        body = extract_pure_js()
    except Exception as e:
        print('could not extract the pure region from app.html: %s' % e)
        return 1
    with tempfile.TemporaryDirectory() as td:
        p = os.path.join(td, 'pure.js')
        with open(p, 'w', encoding='utf-8') as f:
            f.write(body + '\n' + JS_DRIVER)
        r = subprocess.run([node, p], capture_output=True, text=True)
        sys.stdout.write(r.stdout)
        sys.stderr.write(r.stderr)
        return r.returncode


def main(argv=None):
    args = sys.argv[1:] if argv is None else list(argv)

    # BEFORE argparse. Frozen, this process is check_schema's child process as
    # well as the server, and the two are told apart by argv[1] and nothing
    # else -- argparse would have to be built, and a stray --config would be
    # parsed as the server's, before it could decide. See check_schema_argv.
    if args and args[0] == RUN_CHECK_SCHEMA:
        return run_check_schema_entry(args[1:])

    ap = argparse.ArgumentParser(
        epilog='%s --config DIR runs schema/check_schema.py in this process '
               'and exits with its code. It is how the frozen exe validates a '
               'save, and it is dispatched before these options are parsed.'
               % RUN_CHECK_SCHEMA)
    ap.add_argument('--config', help='a BepInEx/config directory, bypassing gameDir')
    ap.add_argument('--game', help='the game directory')
    ap.add_argument('--no-browser', action='store_true')
    ap.add_argument('--port', type=int, default=0,
                    help='bind this port instead of a free one')
    ap.add_argument('--selftest', action='store_true', help='run the verification suite')
    ap.add_argument('--migration', action='store_true',
                    help='with --selftest, also run section 19, the 3.x -> 4.0 '
                         'migrator block. Retired from the default suite by '
                         "David's ruling, %s -- it compares a conversion of "
                         'tests/fixture-3.0.0 against the LIVE config, so it '
                         'goes red on every tuning edit. Without this flag its '
                         'twelve subsections are reported NOT RUN by name, '
                         'never passing and never absent'
                         % MIGRATION_RETIRED_ON)
    ap.add_argument('--migrate', action='store_true',
                    help='convert the 3.x layout in --config to 4.0 and rename '
                         'the originals to %s. Refuses, writing nothing, if an '
                         'input is missing, if the 4.0 layout is already there, '
                         'if a backup exists, or if the post-overlay '
                         'MonsterTypeModel.csv cannot be read'
                         % MIGRATION_BACKUP_SUFFIX)
    ap.add_argument('--frozen-exe', metavar='PATH',
                    help='a built CKF-Config-Editor exe. --selftest runs its '
                         'frozen cases against it; without this they are '
                         'reported NOT RUN rather than passing')
    ap.add_argument('--selftest-js', action='store_true',
                    help='run app.html\'s pure functions under node')
    a = ap.parse_args(args)

    if a.selftest:
        return selftest(a.config, a.frozen_exe, a.migration)
    if a.selftest_js:
        return selftest_js()
    if a.migrate:
        cd = os.path.abspath(a.config) if a.config \
            else config_dir_for(load_settings())
        try:
            mig = run_migration(cd)
        except MigrationRefused as e:
            sys.stderr.write('REFUSED  the 3.x -> 4.0 migration wrote nothing.\n\n'
                             '%s\n' % e)
            return 2
        print('migrated %s' % cd)
        for n in mig.notes:
            print('  %s' % n)
        print('  %d file(s), %d byte(s) written' % (len(mig.files), mig.bytes_total()))
        for s_, d_ in mig.renames:
            print('  %s -> %s' % (s_, d_))
        return 0

    settings = load_settings()
    if a.game:
        settings['gameDir'] = a.game
    if a.config:
        settings['configDirOverride'] = os.path.abspath(a.config)
    if not os.path.exists(SETTINGS_PATH):
        save_settings(settings)

    app = App(settings, secrets.token_urlsafe(24))
    serve(app, open_browser=not a.no_browser, port=a.port)
    return 0


if __name__ == '__main__':
    sys.exit(main())
