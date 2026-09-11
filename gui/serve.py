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
import errno
import hashlib
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
# app.html names nothing. These three tables are the declared exceptions --
# presentation decisions that no schema key expresses, written down once, here,
# with the reason, rather than scattered through the page. None of them changes
# what is read or written: every one is display only, and the save path is
# computed from the data in every case.
#
# Nothing else in this file names a subsystem, a field or a column.

# Two subsystems, presented as one section. They go on writing two files and
# two cfg keys and their schemas are untouched; only the page groups them,
# because they are the two halves of one question -- what a mission pays.
# David, 2026-09-01.
SECTION_GROUPS = [
    {'id': 'mission-pay',
     'title': 'What a Mission Pays',
     'subsystems': ['Progression', 'RewardCurve']},
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
# ckf.hardmode.cfg — one value line replaced in place, never rewritten,
# never commented, never added to.

class CfgFile:
    """Line-preserving reader for a BepInEx .cfg, plus one write.

    Every line the caller does not change comes back byte for byte. A value is
    only rewritten when its rendered form differs from what is on disk, so a
    save with no edits is a no-op even for keys whose value would format
    differently (3 vs 3.0).

    3.0 CUT THIS DOWN. 21 of the 22 keys moved into ckf.hardmode.json, and the
    one left -- [General] Enabled -- is a bool on a key BepInEx binds on every
    launch and therefore always writes. So `set_value` replaces a value line
    and does nothing else: the append-under-a-section-header path is gone, and
    with it the two round-trip refusals it needed (a value starting with `#`
    reads back as a comment; a value carrying a line break leaves a stray line).
    Neither can be reached by a bool, and a key that is not in the file is
    refused rather than created, because BepInEx owns this file's contents.

    Line endings are per line, not per file. `self.lines` holds line contents
    with no ending and `self.ends` holds each line's own ending, so a file that
    mixes CRLF and LF -- one LF-only line in a CRLF file is enough -- still
    indexes one line per physical line. Splitting on a single sniffed separator
    merged such lines into one string, which lost a key or swallowed a
    `[Section]` header and filed every key beneath it under the section before
    it; the write then landed in the wrong block. An edited line keeps the
    ending it had.
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

    def set_value(self, dotted, rendered):
        """Replace one key's value line. -> 'unchanged' | 'replaced'.

        A key that is not already in the file is REFUSED rather than created.
        BepInEx writes this file from the keys the plugin binds, and since 3.0
        it binds exactly one; a key missing from it is a broken install or a
        hand-edit, not something this tool can fix by appending a line the
        plugin will not read.
        """
        i = self.keys.get(dotted)
        if i is None:
            raise SaveRefused({
                'summary': '%s is not in ckf.hardmode.cfg' % dotted,
                'detail': 'BepInEx writes that file from the keys the plugin binds, and '
                          'this tool only replaces a value line it can already see. '
                          'Launch the game once to have the key written, or add it by '
                          'hand. Nothing was written.'})
        if self.KEY_RE.match(self.lines[i]).group(2) == rendered:
            return 'unchanged'
        key = dotted.split('.', 1)[1]
        self.lines[i] = '%s = %s' % (key, rendered)
        return 'replaced'

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


def sections_for(schemas):
    """-> [{'id', 'title', 'subsystems': [...]}] in the order the page shows.

    Schema file order is the default. The master switch is first because it is
    the first thing anyone checks when the mod appears to do nothing; the
    groups in SECTION_GROUPS present as one section; SECTION_LAST goes last.
    Every subsystem appears exactly once -- the selftest asserts it.
    """
    by_sub = dict((s['subsystem'], s) for s in schemas)
    group_of = {}
    for g in SECTION_GROUPS:
        members = [m for m in g['subsystems'] if m in by_sub]
        if len(members) < 2:
            continue                      # a group of one is not a group
        for m in members:
            group_of[m] = (g, members)

    out, seen = [], set()
    for s in schemas:
        sub = s['subsystem']
        if sub in seen:
            continue
        if sub in group_of:
            g, members = group_of[sub]
            seen.update(members)
            out.append({'id': g['id'], 'title': g['title'], 'subsystems': members})
        else:
            seen.add(sub)
            out.append({'id': sub, 'title': s.get('title', sub), 'subsystems': [sub]})

    def is_master(sec):
        return any((by_sub[m].get('enable') or {}).get('cfg') == MASTER_KEY
                   for m in sec['subsystems'])

    def is_last(sec):
        return any(m in SECTION_LAST for m in sec['subsystems'])

    first = [s for s in out if is_master(s)]
    last = [s for s in out if not is_master(s) and is_last(s)]
    mid = [s for s in out if not is_master(s) and not is_last(s)]
    return first + mid + last


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

    return {'cfg': values_cfg, 'json': values_json, 'tables': tables,
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
    """Every path check_schema will open under the config dir, derived from the
    schemas rather than guessed, so a staging copy is complete."""
    rel = {'ckf.hardmode.cfg'}
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
            'sections': sections_for(self.schemas),
            'values': model,
            'enableIndex': enable_index(doc, model),
            'masterKey': MASTER_KEY,
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
                proposed, notes = apply_edits(doc, extras, edits, strip_readme)
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
                proposed, notes = apply_edits(doc, extras, edits, strip_readme)
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


def selftest(config_arg, frozen_exe=None):
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
        raise KeyError('no unit for section %r' % section)

    def _sec(payload, unit):
        """The section object out of one proposed physical file's bytes."""
        d = json.loads(payload[unit_file(unit)].decode('utf-8-sig'))
        sec = unit_section(unit)
        return d[sec] if sec else d

    U_ELAPSE, U_FATIGUE = _unit('elapse'), _unit('fatigue')
    U_MISSION, U_CURVE = _unit('missions'), _unit('rewardcurve')
    U_TEAMPL = _unit('teampl')
    U_MODELRULES = _unit('modelrules')
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
        for name in sidecar_physical:
            after = check_schema.load_jsonc(os.path.join(cd, name))
            dd = _semantic_diff(parsed_before[name], after)
            t.check('forced write: %s on disk is semantically identical' % name, not dd, dd[:8])
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
        idx = dict((e['subsystem'], e) for e in m['enableIndex'])
        # One gate each since 3.0, and it is a path in the merged document.
        # Elapse had two -- a cfg key and the section's own "enabled" -- and the
        # cfg half is gone.
        t.check('the enable index reports effective state per subsystem',
                idx['Elapse']['effective'] == 'on' and len(idx['Elapse']['gates']) == 1
                and idx['Elapse']['gates'][0]['kind'] == 'json',
                idx['Elapse'])
        t.check('SelfCheck reads as deliberately off, from its own section',
                idx['SelfCheck']['effective'] == 'off', idx['SelfCheck'])
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
        # 3.0 moved both halves of the linkedEnable group out of the cfg and
        # into the merged document, so this is a json edit now. The check is
        # the same one: half the group cannot move on its own.
        badinv = app.api_save({'json': {U_TEAMPL: {
            'scalars': {'enabled': {'present': True, 'value': False}}, 'tables': {}}}})
        t.check('a half-on linkedEnable group is refused', not badinv['ok'], badinv)
        t.check('the refusal names INVARIANT',
                any(p['kind'] == 'INVARIANT' for p in (badinv.get('blocking') or [])),
                badinv.get('blocking'))
        t.check('the teampl gate was not written',
                dig(_read_section(cd, U_TEAMPL), 'enabled')[0] is True,
                dig(_read_section(cd, U_TEAMPL), 'enabled'))

        # the linked pair moving together is accepted
        okinv = app.api_save({'json': {
            U_TEAMPL: {'scalars': {'enabled': {'present': True, 'value': False}},
                       'tables': {}},
            U_MODELRULES: {'scalars': {'enabled': {'present': True, 'value': False}},
                           'tables': {}}}})
        t.check('the linked pair moving together is accepted', okinv['ok'], okinv.get('refused'))
        t.check('and both gates are false on disk',
                dig(_read_section(cd, U_TEAMPL), 'enabled')[0] is False
                and dig(_read_section(cd, U_MODELRULES), 'enabled')[0] is False,
                (dig(_read_section(cd, U_TEAMPL), 'enabled'),
                 dig(_read_section(cd, U_MODELRULES), 'enabled')))
        t.check('the cfg was not written by a save that touched neither cfg key',
                'ckf.hardmode.cfg' not in (okinv.get('written') or []),
                okinv.get('written'))

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
        print('\n[8] a .cfg with mixed line endings')
        clean_raw = read_bytes(os.path.join(src, 'ckf.hardmode.cfg'))
        clean = CfgFile(clean_raw)
        t.check('the fixture source really is CRLF',
                b'\r\n' in clean_raw and clean_raw.replace(b'\r\n', b'').count(b'\n') == 0)

        # one line above [General]'s Enabled rewritten with an LF ending
        gj = clean_raw.index(b'Enabled', clean_raw.index(b'[General]'))
        gk = clean_raw.rindex(b'\r\n', 0, gj)
        mixed = clean_raw[:gk] + b'\n' + clean_raw[gk + 2:]
        t.check('the mixed fixture differs from the source by exactly one ending',
                len(mixed) == len(clean_raw) - 1 and b'\r\n' in mixed)
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
        t.check('the master switch is replaced in place, not appended a second time',
                cm2.set_value(MASTER_KEY, 'false') == 'replaced')
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
        cs.set_value('Beta.Enabled', 'true')
        t.check('the write lands in its own section, not in the one above it',
                cs.to_bytes()
                == b'[Alpha]\r\nEnabled = true\r\n## a note\n[Beta]\r\nEnabled = true\r\n',
                cs.to_bytes())
        t.check('and no duplicate section header was appended',
                cs.to_bytes().count(b'[Beta]') == 1)

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
    grouped = [sec for sec in secs if len(sec['subsystems']) > 1]
    t.check('the two halves of what a mission pays are one section',
            len(grouped) == 1 and grouped[0]['subsystems'] == SECTION_GROUPS[0]['subsystems'],
            grouped)
    gsch = [by_sub[m] for m in grouped[0]['subsystems']]
    t.check('and they still write two separate units and carry two separate '
            'enable gates — nothing merged but the presentation',
            len(set(sidecar_unit(s) for s in gsch)) == 2
            and len(set((sidecar_unit(s), (s.get('enable') or {}).get('json'))
                        for s in gsch)) == 2,
            [(sidecar_unit(s), s['enable']) for s in gsch])
    ro = [(s['subsystem'], f['path']) for s in schemas for f in s['fields']
          if f.get('ui') == 'readonly']
    t.check('the section carrying the reference table is the grouped one',
            all(sub in grouped[0]['subsystems'] for sub, _p in ro) and ro, ro)
    # the reference is drawn on the axes of the field that declares it as its
    # underlay -- which is what app.html derives, so the schema has to carry it
    for sub, path in ro:
        owners = [g for g in by_sub[sub]['fields'] if g.get('over') == path and g.get('axes')]
        t.check('%s.%s has an owner field whose axes it can be drawn on'
                % (sub, path), len(owners) == 1, owners)

    # 3.0: no subsystem is gated twice any more, so nothing collapses. The
    # check is not deleted, it is inverted -- a schema that grows a second gate
    # would go back to needing a collapsed control, and this is what says so.
    twice_gated = sorted(s['subsystem'] for s in schemas
                         if (s.get('enable') or {}).get('cfg')
                         and (s.get('enable') or {}).get('json'))
    t.check('no subsystem declares two enable gates: the outer cfg gate is gone',
            twice_gated == [], twice_gated)
    gated_by_cfg = sorted(s['subsystem'] for s in schemas
                          if (s.get('enable') or {}).get('cfg'))
    t.check('exactly one subsystem is gated by a cfg key, and it is the master',
            len(gated_by_cfg) == 1
            and (by_sub[gated_by_cfg[0]].get('enable') or {}).get('cfg') == MASTER_KEY,
            gated_by_cfg)

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
    grp = [g['title'] for g in SECTION_GROUPS
           for i, w in enumerate(g['title'].split())
           if w[:1].islower() and (i == 0 or w.lower() not in small)]
    t.check('so is every grouped section title', not grp, sorted(set(grp)))

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
    t.check('there are %d field docs to check' % len(all_docs), len(all_docs) == 48, len(all_docs))
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
        # (a) a no-op save writes nothing at all
        cdn = _sandbox(src, os.path.join(td, 'noop'))
        appn = App({'gameDir': '', 'configDirOverride': cdn, 'stripReadme': False}, 'x')
        mn = appn.api_model()
        noop = _edits_for(appn.schemas, mn)
        rn = appn.api_save(noop)
        t.check('a no-op save of an untouched config writes zero bytes',
                rn['ok'] and rn['written'] == [], rn.get('written') or rn.get('refused'))

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

        # (c) every subsystem gate is a path in the merged document now, and
        #     writing one off is what turns the subsystem off
        #
        # This replaces the two blocks that used to sit here: "one checkbox,
        # two gates" and "a file whose two gates disagree". Phase 3 deleted the
        # outer cfg gate, so there is no pair to collapse and no pair to
        # disagree. What is left is one gate per subsystem, and the thing worth
        # asserting is that it is honoured.
        json_gated = [sc for sc in apph.schemas
                      if (sc.get('enable') or {}).get('json') and sidecar_unit(sc)]
        cfg_gated = [sc for sc in apph.schemas if (sc.get('enable') or {}).get('cfg')]
        ungated = [sc for sc in apph.schemas if not (sc.get('enable') or {})]
        # The partition, stated rather than counted: one subsystem is gated by a
        # cfg key and it is the master switch; at most one declares no switch of
        # its own; every other gate is a path in the merged document.
        t.check('every gate is a path in the merged document except the master, '
                'which is the one cfg key left',
                len(cfg_gated) == 1
                and (cfg_gated[0].get('enable') or {}).get('cfg') == MASTER_KEY
                and len(ungated) <= 1
                and len(json_gated) + len(cfg_gated) + len(ungated) == len(apph.schemas),
                ([sc['subsystem'] for sc in json_gated],
                 [sc['subsystem'] for sc in cfg_gated],
                 [sc['subsystem'] for sc in ungated]))
        for sch in json_gated:
            gate = sch['enable']['json']
            unit = sidecar_unit(sch)
            cdp = _sandbox(src, os.path.join(td, 'gate-' + sch['subsystem']))
            appp = App({'gameDir': '', 'configDirOverride': cdp, 'stripReadme': False}, 'x')
            rp = appp.api_save({'json': {unit: {'scalars': {
                gate: {'present': True, 'value': False}}, 'tables': {}}}})
            # A gate the linkedEnable invariant covers cannot move on its own,
            # and that refusal is section 7's subject rather than this one's.
            if not rp['ok']:
                t.check('%s: a gate that will not move alone is refused for a '
                        'stated INVARIANT, not silently' % sch['subsystem'],
                        any(q['kind'] == 'INVARIANT' for q in (rp.get('blocking') or [])),
                        rp.get('blocking') or rp.get('refused'))
                continue
            side, _found = dig(_read_section(cdp, unit), gate)
            t.check('%s: the gate is false in its own section on disk'
                    % sch['subsystem'], side is False, side)
            t.check('%s: only its own physical file was written' % sch['subsystem'],
                    'ckf.hardmode.cfg' not in rp['written'], rp['written'])
            appp2 = App({'gameDir': '', 'configDirOverride': cdp, 'stripReadme': False}, 'x')
            ent = [e for e in appp2.api_model()['enableIndex']
                   if e['subsystem'] == sch['subsystem']][0]
            t.check('%s: and the enable index reads it back as off'
                    % sch['subsystem'], ent['effective'] == 'off', ent)

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

        # A key the file does not carry is refused rather than appended: this
        # tool replaces a value line and does not create one, because BepInEx
        # writes ckf.hardmode.cfg from the keys the plugin binds.
        cdx = _sandbox(src, os.path.join(td, 'nokey'))
        cx = CfgFile.load(os.path.join(cdx, 'ckf.hardmode.cfg'))
        gone = [ln for i, ln in enumerate(cx.lines) if i != cx.keys[MASTER_KEY]]
        gone_ends = [e for i, e in enumerate(cx.ends) if i != cx.keys[MASTER_KEY]]
        if gone_ends:
            gone_ends[-1] = ''
        with open(os.path.join(cdx, 'ckf.hardmode.cfg'), 'wb') as fh:
            fh.write(''.join(l + e for l, e in zip(gone, gone_ends)).encode('utf-8'))
        appx = App({'gameDir': '', 'configDirOverride': cdx, 'stripReadme': False}, 'x')
        rx = appx.api_save({'cfg': {MASTER_KEY: {'value': False}}})
        t.check('a cfg key the file does not carry is refused, not appended',
                not rx['ok'] and 'not in ckf.hardmode.cfg'
                in (rx.get('refused') or {}).get('summary', ''), rx)
        t.check('and nothing was written by that refusal',
                MASTER_KEY not in CfgFile.load(
                    os.path.join(cdx, 'ckf.hardmode.cfg')).keys)

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
        # A target may be null: the four sections Phase 3 created declare
        # "legacyJson": null to say they never had a 2.x sidecar.
        for t in (sch.get('targets') or {}).values():
            if t:
                names.add(t)
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
    differs from disk, so this is the shape a no-op save arrives in."""
    edits = {'cfg': {}, 'json': {}}
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


def _teampl_first_fraction(cd):
    for fname, section in ((MERGED_CONFIG, 'teampl'), ('ckf.hardmode.teampl.json', None)):
        p = os.path.join(cd, fname)
        if not os.path.exists(p):
            continue
        js = check_schema.load_jsonc(p)
        if section:
            js = js.get(section, {})
        return js['override'][0]['PowerLevelFraction']
    raise FileNotFoundError('no teampl section under %s' % cd)


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


# REMOVED IN 3.0: _refuses_under_O.
#
# It ran CfgFile's two round-trip guards in a child interpreter started with -O,
# so the claim "these are refusals, not assertions" was checked against an
# interpreter that had actually stripped its asserts. Both guards are gone with
# the append path they protected -- the one cfg key left is a bool -- so there
# is nothing for it to run. If a string-valued key ever comes back to the cfg,
# the guards and this come back together.


def _first_line_diff(a, b):
    la, lb = a.split(b'\n'), b.split(b'\n')
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else b'<eof>'
        y = lb[i] if i < len(lb) else b'<eof>'
        if x != y:
            return 'line %d: %r vs %r' % (i + 1, x, y)
    return ''


def _cfg_line_shape(before_path, after_path):
    """Every line is either identical or a 'Key = Value' line whose key is
    unchanged. Nothing else moved."""
    a = read_bytes(before_path).decode('utf-8-sig').split('\r\n')
    b = read_bytes(after_path).decode('utf-8-sig').split('\r\n')
    if len(a) != len(b):
        return False
    for x, y in zip(a, b):
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
const txt = function (n) { return n.textContent.replace(/\s+/g, ' ').trim(); };
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

  // 3. the grouped section
  const gi = FIXTURE.sections.findIndex(function (s) { return s.subsystems.length > 1; });
  ck('one section presents two subsystems', gi >= 0, FIXTURE.sections.map(function (s) { return s.subsystems; }));
  const group = FIXTURE.sections[gi];
  select(gi);
  const heads = panel.find(function (n) { return n.tagName === 'H3'; }).map(txt);
  for (const sub of group.subsystems) {
    const t = FIXTURE.schemas.find(function (s) { return s.subsystem === sub; }).title;
    ck('the grouped section shows ' + t, heads.some(function (h) { return h.indexOf(t) === 0; }), heads);
  }
  // the reference table is the last thing in the section
  const roField = FIXTURE.schemas.filter(function (s) { return group.subsystems.indexOf(s.subsystem) >= 0; })
    .reduce(function (a, s) { return a.concat(s.fields.filter(function (f) { return f.ui === 'readonly'; })); }, []);
  ck('the group carries exactly one readonly reference table', roField.length === 1, roField.length);
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

  // 5. every subsystem gate is an ordinary control now
  //
  // This replaces "one checkbox per doubly gated subsystem". Phase 3 deleted
  // the outer cfg gate, so the collapsed control and the fixture that drove it
  // are gone; what is asserted instead is that the remaining gate is rendered
  // as a control of its own, and that ticking it moves every key its
  // linkedEnable group names.
  const gated = FIXTURE.schemas.filter(function (s) {
    return (s.enable || {}).json && s.fields.some(function (f) {
      return f.in === 'json' && f.path === s.enable.json; }); });
  const cfgGated = FIXTURE.schemas.filter(function (s) { return (s.enable || {}).cfg; });
  const ungated = FIXTURE.schemas.filter(function (s) { return !s.enable; });
  ck('every gate is a field in the document except the master, which is the one cfg key left',
     cfgGated.length === 1 && ungated.length <= 1
       && gated.length + cfgGated.length + ungated.length === FIXTURE.schemas.length,
     [gated.length, cfgGated.length, ungated.length, FIXTURE.schemas.length]);
  for (const s of gated) {
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
    const gparts = unit.split('#').concat(String(s.enable.json).split('.'));
    const gateRows = rows.filter(function (r) { return named(r, gparts); });
    ck(s.subsystem + ': exactly one control row carries its gate',
       gateRows.length === 1, gateRows.length);
    const boxes = gateRows[0].find(function (n) { return n.tagName === 'INPUT' && n.type === 'checkbox'; });
    ck(s.subsystem + ': and it is a checkbox', boxes.length === 1, boxes.length);
    const want = !boxes[0].checked;
    boxes[0].checked = want;
    boxes[0].fire('change');
    ck(s.subsystem + ': the click lands on its own gate',
       !!W.json[unit][s.enable.json].value === want, W.json[unit][s.enable.json]);
    const grp = (FIXTURE.schemas.reduce(function (acc, sc) {
      return acc.concat(sc.invariants || []); }, []))
      .filter(function (inv) { return inv.kind === 'linkedEnable'
                                 && inv.keys.indexOf(unit + '.' + s.enable.json) >= 0; })[0];
    if (grp) {
      const states = grp.keys.map(function (k) {
        for (const u in W.json) if (k.indexOf(u + '.') === 0) {
          const pth = k.slice(u.length + 1);
          if (W.json[u][pth]) return !!W.json[u][pth].value;
        }
        return null;
      });
      ck(s.subsystem + ': every key its linked group names moved with it',
         states.every(function (v) { return v === want; }), states);
    }
  }

  // 6. no cell carries a button, in any grid on any page, and the only button
  //    on a row is the one that deletes it.
  //
  // REPLACES, 2026-09-07: two cases that asserted the unset button appeared on
  // the free-text columns and not on the adjustment ones. The control is gone,
  // so the assertion is inverted and widened -- every grid, not just the one
  // with adjustment columns -- and the delete-row button is asserted by name
  // so that removing the unset control cannot quietly remove that one too.
  let cellButtons = 0, rowsSeen = 0, deleters = 0;
  for (let i = 0; i < FIXTURE.sections.length; i++) {
    select(i);
    for (const g of panel.find(function (n) {
           return n.tagName === 'TABLE' && n._cls().includes('grid'); })) {
      const owner = FIXTURE.schemas.find(function (s) {
        return s.fields.some(function (f) {
          return (f.type === 'table' || f.type === 'matrix')
                 && (f.row || []).length === g.querySelector('thead')
                      .children[0].children.length - 1; }); });
      if (!owner) continue;
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
  const gi = FIXTURE.sections.findIndex(function (s) { return s.subsystems.length > 1; });
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
    ap.add_argument('--frozen-exe', metavar='PATH',
                    help='a built CKF-Config-Editor exe. --selftest runs its '
                         'frozen cases against it; without this they are '
                         'reported NOT RUN rather than passing')
    ap.add_argument('--selftest-js', action='store_true',
                    help='run app.html\'s pure functions under node')
    a = ap.parse_args(args)

    if a.selftest:
        return selftest(a.config, a.frozen_exe)
    if a.selftest_js:
        return selftest_js()

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
