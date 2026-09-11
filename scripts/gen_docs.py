#!/usr/bin/env python3
"""
Generate docs/config-reference.md from schema/*.schema.json.

    python3 scripts/gen_docs.py [--schema DIR] [--out FILE]

Defaults are relative to the repository root (the parent of this script's
directory): --schema <root>/schema, --out <root>/docs/config-reference.md.

ORDERING. Subsystems are emitted in ascending order of schema FILENAME:

    difficulty, elapse, fatigue, general, missionrewards, modelrules,
    powerlevel, rewardcurve, selfcheck, teampl

which is the order schema/check_schema.py walks (`sorted(os.listdir(...))`),
so the two tools always agree on which file they are talking about. Note that
teampl.schema.json declares the subsystem `Progression`; the filename, not the
subsystem name, decides position. Within a subsystem, fields are emitted in
schema order, which is authored order and carries meaning.

DETERMINISM. The output contains no timestamp, no path from the running
machine and no dictionary-iteration order: the same schema directory produces
a byte-identical file on every run. Every string in the document comes from a
schema file; this script adds structure and headings, not content.

This is the destination for the prose that was stripped
out of the sidecars. A fact that lives only in a stripped comment is a gap in
the schema, not a fact this document can print.
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Schema keys this renderer knows about. Anything else in a schema or a field
# is surfaced in an "unrendered keys" line rather than silently dropped, so a
# key added to the format cannot go missing from the document unnoticed.
KNOWN_TOP = {
    'subsystem', 'title', 'doc', 'uiDoc', 'targets', 'enable', 'fields',
    'invariants',
}
KNOWN_FIELD = {
    'path', 'in', 'type', 'default', 'range', 'label', 'doc', 'uiDoc', 'ui',
    'enabledBy', 'absent', 'optional', 'retroactive', 'oneLine',
    'row', 'keyedBy', 'sortBy', 'axes', 'over', 'values',
}
KNOWN_COL = {'name', 'type', 'range', 'values', 'format'}

UI_NOTE = {
    'form':     'labelled control',
    'table':    'editable grid',
    'curve':    'grid plus editable line chart, x = the first row column',
    'matrix':   '2-D grid over the declared axes',
    'readonly': 'shown, not editable',
    'hidden':   'never rendered',
}

TYPE_NOTE = {
    'floatOrNaN': '`NaN` means "leave the game\'s own value alone". cfg only.',
    'stringList': 'Comma-separated in the cfg, a JSON array in a sidecar. '
                  'In the cfg it must stay on ONE line: a list split across '
                  'lines silently keeps only the first entry.',
}

# A row column may declare the grammar its cell text must parse under. This is
# a property of the column, not of the field, and it is unrelated to `absent`
# and `optional`, which are about a value being left out entirely.
FORMAT_NOTE = {
    'adjust': 'The mission adjustment grammar `MissionRewards.Adjust.Parse` '
              'reads (`MissionRewards.cs:392-415`): `""` leaves the value '
              'alone, `=N` sets it, `+N` adds, `-N` adds a negative, `xN` / '
              '`XN` / `*N` multiplies, and a bare number sets. A column with '
              'no `format` declares no grammar.',
}


# ---------------------------------------------------------------- loading

def load_schema(path):
    with open(path, encoding='utf-8-sig') as f:
        text = f.read()
    try:
        return json.loads(text)
    except ValueError:
        # The schema files are plain JSON today, but the repo's own reader
        # tolerates JSONC. Reuse check_schema.strip_jsonc rather than keeping
        # a second copy of that state machine.
        return json.loads(_strip_jsonc(text))


def _strip_jsonc(text):
    import importlib.util
    for cand in (os.path.join(ROOT, 'schema', 'check_schema.py'),):
        if os.path.exists(cand):
            spec = importlib.util.spec_from_file_location('_ckf_check', cand)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            return mod.strip_jsonc(text)
    raise SystemExit('schema is not plain JSON and check_schema.py was not found')


def load_all(schema_dir):
    out = []
    for fn in sorted(os.listdir(schema_dir)):
        if fn.endswith('.schema.json'):
            out.append((fn, load_schema(os.path.join(schema_dir, fn))))
    if not out:
        raise SystemExit('no *.schema.json in %s' % schema_dir)
    return out


# ---------------------------------------------------------------- helpers

def cell(s):
    """Make a string safe inside a markdown table cell."""
    if s is None:
        return ''
    s = str(s)
    s = s.replace('\\', '\\\\').replace('|', '\\|')
    s = s.replace('\r\n', ' ').replace('\n', '<br>')
    return s


def code(s):
    return '`%s`' % s


def scalar(v):
    """Render a JSON scalar the way it is written in the schema."""
    if v is None:
        return 'null'
    if v is True:
        return 'true'
    if v is False:
        return 'false'
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, int):
        return str(v)
    return '"%s"' % v


def fmt_default(f):
    if 'default' not in f:
        return '_none declared_'
    v = f['default']
    if v is None:
        return '`null` — unset'
    if isinstance(v, str) and v == '':
        return '`""` — empty'
    return code(scalar(v))


def fmt_range(rng):
    if not rng:
        return ''
    lo, hi = rng
    return '`%s` to `%s`' % (scalar(lo), scalar(hi))


def paragraphs(lines):
    """Render a schema `doc` array.

    A line that starts with whitespace is preformatted and goes into a fenced
    block with its alignment intact; the aligned key/value listings in
    powerlevel and missionrewards depend on that. Everything else is prose,
    with blank array entries ending a paragraph.
    """
    out, para, pre = [], [], []

    def flush_para():
        if para:
            out.append(' '.join(para))
            out.append('')
            del para[:]

    def flush_pre():
        if pre:
            while pre and not pre[-1].strip():
                pre.pop()
            out.append('```text')
            out.extend(pre)
            out.append('```')
            out.append('')
            del pre[:]

    i = 0
    while i < len(lines):
        line = lines[i]
        indented = line[:1].isspace() and line.strip() != ''
        if indented:
            flush_para()
            pre.append(line.rstrip())
        elif line.strip() == '':
            if pre:
                # A blank line inside a preformatted run stays in it only if
                # more preformatted lines follow.
                j = i + 1
                while j < len(lines) and lines[j].strip() == '':
                    j += 1
                if j < len(lines) and lines[j][:1].isspace():
                    pre.append('')
                else:
                    flush_pre()
            else:
                flush_para()
        else:
            flush_pre()
            para.append(line.rstrip())
        i += 1
    flush_para()
    flush_pre()
    while out and out[-1] == '':
        out.pop()
    return out


def unrendered(obj, known, what):
    extra = sorted(k for k in obj if k not in known)
    if not extra:
        return []
    return ['> This document does not render these %s keys: %s.'
            % (what, ', '.join(code(k) for k in extra)), '']


def anchor(subsystem):
    return '#' + subsystem.lower()


# ---------------------------------------------------------------- sections

def sidecar_unit(sch):
    """file#section, or the bare filename when a schema owns a whole file.

    Five subsystems share ckf.hardmode.json now, so the filename alone no
    longer says where a key lives. The section is the useful half.
    """
    t = sch.get('targets') or {}
    if not t.get('json'):
        return None
    return '%s#%s' % (t['json'], t['section']) if t.get('section') else t['json']


def render_enable_chain(sch, out):
    name = sch['subsystem']
    tgt = sch.get('targets', {})
    en = sch.get('enable', {})
    fields = sch['fields']

    gates = {}
    for f in fields:
        g = f.get('enabledBy')
        if g:
            gates.setdefault(g, []).append(f['path'])

    out.append('### Enable chain')
    out.append('')
    out.append('Every link is AND-ed with the ones before it. The first link '
               'that reads false stops everything to its right, and nothing '
               'further down the chain is consulted.')
    out.append('')

    links = []
    if en.get('cfg'):
        section, key = en['cfg'].split('.', 1)
        links.append((
            'cfg',
            '[%s] %s = true' % (section, key),
            '%s — a BepInEx bind, read before anything else on disk'
            % tgt.get('cfg', 'ckf.hardmode.cfg'),
        ))
    if en.get('json'):
        unit = sidecar_unit(sch) or tgt.get('json')
        links.append((
            'document',
            '"%s": true' % en['json'],
            '%s — checked after the document loads' % unit,
        ))

    out.append('```text')
    if not links:
        out.append('(no enable block declared in this schema)')
    for i, (level, expr, where) in enumerate(links):
        if i:
            out.append('        AND')
        out.append('  %-8s %-34s %s' % (level, expr, where))
    if gates:
        if links:
            out.append('        AND  (per field, not per subsystem)')
        for g in sorted(gates):
            out.append('  %-8s %-34s gates %s'
                       % ('field', '"%s": true' % g, ', '.join(sorted(gates[g]))))
    out.append('```')
    out.append('')

    # The point of the chain, said in words.
    if len(links) >= 2:
        out.append('**Reading `%s = true` in `%s` is not enough.** '
                   'A subsystem whose cfg key is on and whose `%s` is '
                   'false loads its settings, installs nothing and writes '
                   'nothing. The cfg key alone does not tell you whether %s is '
                   'doing anything.'
                   % (en['cfg'], tgt.get('cfg', 'ckf.hardmode.cfg'),
                      en['json'], name))
        out.append('')
    elif en.get('json'):
        out.append('**One gate.** 3.0 collapsed the chain: the `.cfg` key that '
                   'used to gate this subsystem before its settings were read '
                   'is gone, and `"%s"` in its own section is the whole of it. '
                   'One consequence worth holding: a `%s` that cannot be read '
                   'costs this subsystem its switch as well as its values, and '
                   'the log says which of the two it is rather than implying '
                   'someone set a toggle.'
                   % (en['json'], tgt.get('json', 'ckf.hardmode.json')))
        out.append('')
    elif links:
        out.append('**One gate only.** This subsystem reads nothing but the '
                   'master switch, so there is no second gate.')
        out.append('')
    else:
        out.append('**No gate of its own.** `%s` declares no `enable` block, '
                   'so this document can cite no per-subsystem switch for it.'
                   % sch['_filename'])
        out.append('')

    if name != 'General':
        out.append('Outside every chain in this document sits `[General] '
                   'Enabled`, which since 3.0 is the only key in '
                   '`ckf.hardmode.cfg`. `general.schema.json` records that its '
                   'bail-out sits above every subsystem init in '
                   '`Plugin.Load()`, and that it used to sit underneath — which '
                   'meant `Enabled = false` still let ModelRules rewrite every '
                   'row and PowerLevelCap overwrite every calculation.')
        out.append('')


def render_fields(sch, out):
    fields = sch['fields']
    out.append('### Fields')
    out.append('')
    out.append('%d field(s). `Absent` is deliberately a column of its own: it '
               'says what an omitted value means when that differs from the '
               'default, and the two are not interchangeable. The `optional` '
               'flag is a third, separate thing again: it says the omission is '
               'allowed at all. A field may carry both, either or neither.'
               % len(fields))
    out.append('')
    out.append('| Path | In | Type | UI | Default | Absent | Range | Gated by | Flags | Label | Documentation |')
    out.append('|---|---|---|---|---|---|---|---|---|---|---|')
    for f in fields:
        flags = []
        if f.get('retroactive'):
            flags.append('**RETROACTIVE**')
        if f.get('optional'):
            flags.append('optional')
        if f.get('oneLine'):
            flags.append('one line')
        if f.get('keyedBy'):
            flags.append('keyed by `%s`' % f['keyedBy'])
        if f.get('sortBy'):
            flags.append('sorted by `%s`' % f['sortBy'])
        if f.get('axes'):
            flags.append('matrix axes')
        if f.get('over'):
            flags.append('over `%s`' % f['over'])
        path = code(f['path'])
        if f.get('retroactive'):
            path = '**%s**' % path
        out.append('| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |' % (
            path,
            f.get('in', ''),
            code(f['type']) if f.get('type') else '',
            code(f['ui']) if f.get('ui') else '',
            cell(fmt_default(f)),
            cell(f.get('absent', '')),
            cell(fmt_range(f.get('range'))),
            code(f['enabledBy']) if f.get('enabledBy') else '',
            cell(', '.join(flags)),
            cell(f.get('label', '')),
            cell(f.get('doc', '')),
        ))
    out.append('')

    for f in fields:
        out.extend(unrendered(f, KNOWN_FIELD, 'field `%s`' % f['path']))

    # A field's own uiDoc, where it has one. Same split as the subsystem's,
    # one level down: `doc` above is the record, this is what the GUI shows a
    # player instead of it. Rendered here so the maintainer document says what
    # the player is being told.
    ui_fields = [f for f in fields if f.get('uiDoc')]
    if ui_fields:
        out.append('**What the config GUI shows for these fields.**')
        out.append('')
        out.append('| Field | GUI help |')
        out.append('|---|---|')
        for f in ui_fields:
            out.append('| %s | %s |' % (code(f['path']), cell(f['uiDoc'])))
        out.append('')
        out.append('%d of %d fields carry a `uiDoc`; the rest show their `doc` '
                   'with the citations and evidence tags stripped.'
                   % (len(ui_fields), len(fields)))
        out.append('')

    # Types that carry semantics beyond their name, on a field or on a column.
    seen = []
    for f in fields:
        for t in [f.get('type')] + [c.get('type') for c in f.get('row', [])]:
            if t in TYPE_NOTE and t not in seen:
                seen.append(t)
    if seen:
        out.append('**Type notes.**')
        out.append('')
        for t in seen:
            out.append('- `%s` — %s' % (t, TYPE_NOTE[t]))
        out.append('')

    # Column definitions for every table / matrix / curve field.
    tables = [f for f in fields if f.get('row')]
    for f in tables:
        out.append('#### Columns of `%s`' % f['path'])
        out.append('')
        shape = []
        if f.get('keyedBy'):
            shape.append('On disk this is a JSON **object**, keyed by `%s`; '
                         'that key is the column named below, not a member of '
                         'each row object.' % f['keyedBy'])
        else:
            shape.append('On disk this is a JSON **array** of row objects.')
        if f.get('sortBy'):
            shape.append('Sorted by `%s`.' % f['sortBy'])
        if f.get('ui') == 'curve':
            shape.append('Rendered as a curve; the x axis is the first column.')
        if f.get('axes'):
            ax = f['axes']
            shape.append('Matrix axes: rows are `%s`, columns are `%s`, the '
                         'cell value is `%s`.'
                         % (ax.get('row'), ax.get('col'), ax.get('value')))
        if f.get('over'):
            shape.append('Overlays `%s`: a cell absent here keeps its `%s` '
                         'value.' % (f['over'], f['over']))
        out.append(' '.join(shape))
        out.append('')
        # The Format column appears only where a column of this field declares
        # one, so a table with no declared grammar carries no empty column.
        has_format = any(c.get('format') for c in f['row'])
        out.append('| Column | Type | Range |' + (' Format |' if has_format else ''))
        out.append('|---|---|---|' + ('---|' if has_format else ''))
        for c in f['row']:
            row = '| %s | %s | %s |' % (
                code(c['name']), code(c.get('type', '')),
                fmt_range(c.get('range')))
            if has_format:
                row += ' %s |' % (code(c['format']) if c.get('format') else '')
            out.append(row)
        out.append('')
        if has_format:
            seen_fmt = []
            for c in f['row']:
                fm = c.get('format')
                if fm and fm not in seen_fmt:
                    seen_fmt.append(fm)
            out.append('**Format notes.** A `Format` entry names the grammar '
                       'that column\'s text must parse under. It constrains '
                       'the value that is present; it says nothing about the '
                       'value being omitted, which is what `Absent` and '
                       '`optional` are for.')
            out.append('')
            for fm in seen_fmt:
                out.append('- `%s` — %s'
                           % (fm, FORMAT_NOTE.get(fm, '_no note for this '
                                                      'format in `gen_docs.py`_')))
            out.append('')
        for c in f['row']:
            out.extend(unrendered(c, KNOWN_COL,
                                  'column `%s.%s`' % (f['path'], c['name'])))


def render_invariants(sch, out):
    invs = sch.get('invariants', [])
    out.append('### Invariants')
    out.append('')
    if not invs:
        out.append('None declared.')
        out.append('')
        return
    for inv in invs:
        out.append('#### `%s`' % inv['kind'])
        out.append('')
        rows = []
        if inv.get('keys'):
            rows.append(('Keys', ', '.join(code(k) for k in inv['keys'])))
        if inv.get('source'):
            rows.append(('Source', code(inv['source'])))
        if inv.get('target'):
            rows.append(('Target', code(inv['target'])))
        if inv.get('match'):
            rows.append(('Matched on', ', '.join(code(k) for k in inv['match'])))
        if inv.get('value'):
            rows.append(('Value column', code(inv['value'])))
        if inv.get('mergeWith'):
            rows.append(('Merged with', code(inv['mergeWith'])))
        if 'generated' in inv:
            rows.append(('Target is machine-owned',
                         'yes — rewritten wholesale, never hand-edited'
                         if inv['generated'] else 'no'))
        if rows:
            out.append('| | |')
            out.append('|---|---|')
            for k, v in rows:
                out.append('| %s | %s |' % (k, cell(v)))
            out.append('')
        out.append('**Reason.** %s' % inv.get('reason', '_none stated_'))
        out.append('')


def render_subsystem(fn, sch, out):
    sch['_filename'] = fn
    name = sch['subsystem']
    tgt = sch.get('targets', {})

    out.append('## %s' % name)
    out.append('')
    where = ('`.cfg` section `[%s]`' % name) if tgt.get('cfg') else \
            ('`%s`' % sidecar_unit(sch) if sidecar_unit(sch) else 'no file of its own')
    out.append('**%s** &nbsp;·&nbsp; %s &nbsp;·&nbsp; '
               'declared in `schema/%s`' % (sch['title'], where, fn))
    out.append('')

    out.extend(unrendered(sch, KNOWN_TOP | {'_filename'}, 'top-level'))

    retro = [f for f in sch['fields'] if f.get('retroactive')]
    if retro:
        names = ['`%s`' % f['path'] for f in retro]
        joined = names[0] if len(names) == 1 else \
            '%s and %s' % (', '.join(names[:-1]), names[-1])
        out.append('> **RETROACTIVE CONTROL%s IN THIS SUBSYSTEM.** %s '
                   're-price%s existing save data. Changing one does not only '
                   'affect what happens next; it rewrites what already '
                   'happened, and the substituted figure persists into the '
                   'save.'
                   % ('S' if len(retro) > 1 else '', joined,
                      '' if len(retro) > 1 else 's'))
        out.append('')

    if sch.get('doc'):
        out.extend(paragraphs(sch['doc']))
        out.append('')

    if sch.get('uiDoc'):
        out.append('### What the config GUI shows for this section')
        out.append('')
        out.append('The `uiDoc` array: the same subsystem written for someone '
                   'playing the game rather than maintaining the mod. It '
                   'carries no citations, run numbers or evidence tags by '
                   'design — the prose above is the record, and this is the '
                   'reader-facing summary of it. The GUI renders `uiDoc` where '
                   'a subsystem has one and falls back to `doc` where it does '
                   'not.')
        out.append('')
        out.extend(paragraphs(sch['uiDoc']))
        out.append('')

    out.append('### Files this subsystem writes')
    out.append('')
    out.append('| Role | File |')
    out.append('|---|---|')
    for role in ('cfg', 'json'):
        if tgt.get(role):
            out.append('| `%s` | `%s` |' % (role, tgt[role]))
    for role in sorted(k for k in tgt if k not in ('cfg', 'json')):
        if tgt[role] is None:
            # An explicit null, not an omission: "this section is new in 3.0
            # and has no 2.x file behind it". Rendered rather than skipped, so
            # the reader can tell it apart from a schema that forgot to say.
            out.append('| `%s` | _none — this section is new in 3.0_ |' % role)
        else:
            out.append('| `%s` | `%s` |' % (role, tgt[role]))
    out.append('')

    render_enable_chain(sch, out)
    render_fields(sch, out)
    render_invariants(sch, out)


# ---------------------------------------------------------------- document

def render(schemas):
    out = []
    out.append('# CKF Hard Mode — configuration reference')
    out.append('')
    out.append('Generated by `scripts/gen_docs.py` from `schema/*.schema.json`. '
               '**Do not edit this file.** Every sentence below is a `doc`, '
               '`label`, `absent` or `reason` string from a schema file; to '
               'change one, change the schema and regenerate.')
    out.append('')
    out.append('Subsystems appear in ascending order of schema filename — the '
               'order `schema/check_schema.py` walks. `teampl.schema.json` '
               'declares the subsystem `Progression`, so it sorts last under '
               'its filename, not under its name.')
    out.append('')
    out.append('This document is the single destination for the prose that '
               'used to live as `//` comments and `_readme` arrays inside the '
               'five sidecars. A fact that is '
               'not here is not in the schema either.')
    out.append('')

    total_fields = sum(len(s['fields']) for _, s in schemas)
    total_cfg = sum(1 for _, s in schemas for f in s['fields'] if f['in'] == 'cfg')

    out.append('## Subsystems at a glance')
    out.append('')
    out.append('| Subsystem | Title | Sidecar | cfg keys | Fields | Enable chain depth |')
    out.append('|---|---|---|---|---|---|')
    for fn, s in schemas:
        en = s.get('enable', {})
        depth = (1 if en.get('cfg') else 0) + (1 if en.get('json') else 0)
        gate_paths = sorted({f['enabledBy'] for f in s['fields'] if f.get('enabledBy')})
        depth_txt = str(depth)
        if gate_paths:
            depth_txt += ' + %d per-field gate(s)' % len(gate_paths)
        out.append('| [%s](%s) | %s | %s | %d | %d | %s |' % (
            s['subsystem'], anchor(s['subsystem']), cell(s['title']),
            '`%s`' % sidecar_unit(s) if sidecar_unit(s) else '—',
            sum(1 for f in s['fields'] if f['in'] == 'cfg'),
            len(s['fields']),
            depth_txt))
    out.append('')
    out.append('%d subsystems, %d cfg keys, %d fields in total.'
               % (len(schemas), total_cfg, total_fields))
    out.append('')

    # --- retroactive controls, collected, before anything else
    retro = [(s['subsystem'], f) for _, s in schemas for f in s['fields']
             if f.get('retroactive')]
    out.append('## Retroactive controls — read before changing these')
    out.append('')
    out.append('A retroactive control re-prices existing save data. It is not '
               'a setting that takes effect from now on; it rewrites what has '
               'already happened, and the result persists into the save, so '
               'putting the control back does not put the save back.')
    out.append('')
    if retro:
        out.append('| Subsystem | Field | What it re-prices |')
        out.append('|---|---|---|')
        for sub, f in retro:
            out.append('| %s | **`%s`** | %s |'
                       % (sub, f['path'], cell(f.get('doc', ''))))
        out.append('')
        out.append('%d retroactive control(s). Every other control in this '
                   'document takes effect from the next relevant event '
                   'onwards.' % len(retro))
    else:
        out.append('None declared.')
    out.append('')

    # --- cfg key index
    out.append('## Every `.cfg` key')
    out.append('')
    out.append('One row per `Section.Key` in `ckf.hardmode.cfg`. '
               '`schema/check_schema.py` reports any key on disk that is not '
               'in this list as STALE, and any key here that is not on disk as '
               'MISSING.')
    out.append('')
    out.append('| Key | Type | Default | Subsystem | Label |')
    out.append('|---|---|---|---|---|')
    cfg_rows = []
    for _, s in schemas:
        for f in s['fields']:
            if f['in'] == 'cfg':
                cfg_rows.append((f['path'], f, s['subsystem']))
    for path, f, sub in sorted(cfg_rows, key=lambda r: r[0]):
        out.append('| `%s` | `%s` | %s | [%s](%s) | %s |'
                   % (path, f['type'], cell(fmt_default(f)), sub,
                      anchor(sub), cell(f.get('label', ''))))
    out.append('')
    out.append('%d key(s).' % len(cfg_rows))
    out.append('')

    # --- sidecar field index
    out.append('## Every sidecar field')
    out.append('')
    out.append('| Sidecar | Path | Type | UI | Subsystem |')
    out.append('|---|---|---|---|---|')
    n_json = 0
    for _, s in schemas:
        side = sidecar_unit(s) or ''
        for f in s['fields']:
            if f['in'] == 'json':
                n_json += 1
                out.append('| `%s` | `%s` | `%s` | `%s` | [%s](%s) |'
                           % (side, f['path'], f['type'], f.get('ui', ''),
                              s['subsystem'], anchor(s['subsystem'])))
    out.append('')
    out.append('%d sidecar field(s) across %d section(s) in %d file(s).'
               % (n_json,
                  len({sidecar_unit(s) for _, s in schemas if sidecar_unit(s)}),
                  len({s['targets']['json'] for _, s in schemas
                       if s.get('targets', {}).get('json')})))
    out.append('')

    # --- how to read the columns
    out.append('## How to read the field tables')
    out.append('')
    out.append('| Column | Meaning |')
    out.append('|---|---|')
    out.append('| `Path` | For `in: cfg`, `Section.Key`. For `in: json`, a '
               'dotted path from the sidecar root. Both are the literal '
               'address a generator writes to; neither is derived from the '
               'other. |')
    out.append('| `Default` | The value the schema declares. |')
    out.append('| `Absent` | What leaving the key out means, stated only where '
               'that differs from the default. Where this column has an '
               'entry, omitting the key and writing the default are two '
               'different things. |')
    out.append('| `Range` | Inclusive `[min, max]`. `check_schema.py` reports '
               'a value outside it as RANGE. |')
    out.append('| `Gated by` | A third enable level: a boolean elsewhere in '
               'the same file that must be true for this field to mean '
               'anything. |')
    out.append('| `Flags` | `RETROACTIVE` re-prices existing save data. '
               '`optional` means leaving the key out of the file is legal, so '
               '`check_schema.py` skips its `MISSING` check — it does **not** '
               'say what the omission means, which is the `Absent` column\'s '
               'job, and a field may carry one, both or neither. '
               '`one line` means a cfg list split across lines silently keeps '
               'only its first entry. `keyed by` means the block is a JSON '
               'object whose keys are that column, not an array. |')
    out.append('')
    out.append('Table and matrix fields get a `Columns of ...` section of '
               'their own below. A column there may carry a `Format`, naming '
               'the grammar its cell text must parse under; that is a property '
               'of a value that is present, and is unrelated to `Absent` and '
               '`optional`.')
    out.append('')
    out.append('**`ui` values.**')
    out.append('')
    out.append('| Value | Renders as |')
    out.append('|---|---|')
    for k in ('form', 'table', 'curve', 'matrix', 'readonly', 'hidden'):
        out.append('| `%s` | %s |' % (k, UI_NOTE[k]))
    out.append('')

    out.append('---')
    out.append('')

    for fn, s in schemas:
        render_subsystem(fn, s, out)
        out.append('---')
        out.append('')

    while out and out[-1] == '':
        out.pop()
    return '\n'.join(out) + '\n'


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[1])
    ap.add_argument('--schema', default=os.path.join(ROOT, 'schema'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'docs', 'config-reference.md'))
    a = ap.parse_args()

    schemas = load_all(a.schema)
    text = render(schemas)

    outdir = os.path.dirname(os.path.abspath(a.out))
    if outdir and not os.path.isdir(outdir):
        os.makedirs(outdir)
    with open(a.out, 'w', encoding='utf-8', newline='\n') as f:
        f.write(text)

    n_cfg = sum(1 for _, s in schemas for f in s['fields'] if f['in'] == 'cfg')
    n_fields = sum(len(s['fields']) for _, s in schemas)
    print('%s: %d subsystem(s), %d cfg key(s), %d field(s), %d line(s)'
          % (a.out, len(schemas), n_cfg, n_fields, text.count('\n')))
    return 0


if __name__ == '__main__':
    sys.exit(main())
