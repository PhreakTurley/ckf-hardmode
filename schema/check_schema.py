#!/usr/bin/env python3
"""
Verify the live config against the schema files.

    python check_schema.py --game "C:\\...\\Cyber Knights Flashpoint" [--schema DIR]

Reports four classes of drift. Exit code 1 if any STALE, MISSING, RANGE or
INVARIANT problem is found.

  STALE      a key on disk that no schema field declares. This is the check
             that would have caught the 12 dead cfg keys without a manual grep.
  MISSING    a schema field with no key on disk, unless that field declares
             "optional": true, which says omission from the file is legal.
             "optional" is NOT implied by "absent" and does not imply it:
             "absent" documents what an omitted value MEANS, "optional" says
             the omission is allowed at all. A field may carry either, both or
             neither, and a field carrying only "absent" still reports MISSING.
  RANGE      a value outside its declared range
  INVARIANT  a mirror whose sides disagree, a half-on linkedEnable group, or an
             'ordered' group whose keys are out of order
"""

import argparse, json, os, re, sys

# --------------------------------------------------------------------------
# JSONC: the sidecars carry // comments and trailing commas by design.

def strip_jsonc(s):
    out, instr, esc, i = [], False, False, 0
    while i < len(s):
        c = s[i]
        if instr:
            out.append(c)
            if esc:            esc = False
            elif c == '\\':    esc = True
            elif c == '"':     instr = False
            i += 1; continue
        if c == '"':
            instr = True; out.append(c); i += 1; continue
        if c == '/' and i + 1 < len(s) and s[i+1] == '/':
            while i < len(s) and s[i] != '\n': i += 1
            continue
        if c == '/' and i + 1 < len(s) and s[i+1] == '*':
            j = s.find('*/', i + 2); i = (j + 2) if j >= 0 else len(s); continue
        out.append(c); i += 1
    return re.sub(r',(\s*[}\]])', r'\1', ''.join(out))

def load_jsonc(path):
    with open(path, encoding='utf-8-sig') as f:
        return json.loads(strip_jsonc(f.read()))

def load_cfg(path):
    """-> {'Section.Key': 'raw value string'}"""
    keys, sec = {}, None
    with open(path, encoding='utf-8-sig') as f:
        for line in f:
            line = line.rstrip('\r\n')
            if line.startswith('['):
                sec = line.strip('[]'); continue
            m = re.match(r'^([A-Za-z]\w*) = ?(.*)$', line)
            if m and sec:
                keys[f'{sec}.{m.group(1)}'] = m.group(2)
    return keys

def dig(obj, dotted):
    for part in dotted.split('.'):
        if not isinstance(obj, dict) or part not in obj:
            return None, False
        obj = obj[part]
    return obj, True

# --------------------------------------------------------------------------

def coerce(raw, typ):
    """cfg values arrive as strings. -> (value, ok)"""
    try:
        if typ == 'bool':        return raw.strip().lower() == 'true', True
        if typ == 'int':         return int(raw.strip()), True
        if typ == 'float':       return float(raw.strip()), True
        if typ == 'floatOrNaN':
            t = raw.strip()
            return (float('nan'), True) if t == 'NaN' else (float(t), True)
        return raw, True
    except ValueError:
        return None, False

def table_rows(val, keyed_by, cols):
    """The rows of a table field, whichever of the two shapes it is in on disk.

    For an object-shaped table the KEY is a column like any other, so it is
    folded back into its row before the range check, coerced to the type the
    column declares.

    This used to be `list(val.values())`, which threw the keys away: a keyedBy
    column was the one column in the file no layer range-checked. Measured
    2026-09-01 -- powerLevel 9999 against a declared range of [1, 20] was
    accepted into ckf.hardmode.fatigue.json and reported clean, while the same
    value in an array-shaped table was correctly blocked.
    """
    if not isinstance(val, dict):
        return val
    if not keyed_by:
        return list(val.values())
    out = []
    typ = (cols.get(keyed_by) or {}).get('type', 'string')
    for k, row in val.items():
        row = dict(row) if isinstance(row, dict) else {}
        kv, ok = coerce(k, typ)
        row[keyed_by] = kv if ok else k
        out.append(row)
    return out

def inv_value(key, cfg, files, cfgdir):
    """The live value of a key named by an invariant. -> (value, found)

    Two spellings, because 3.0 moved 21 of the 22 cfg keys into the merged
    document and two invariants named keys that moved:

      "PowerLevel.MinCap"                    a cfg key; comes back as its raw
                                             string, the way load_cfg holds it
      "ckf.hardmode.json#powerlevel.minCap"  a path inside a config document;
                                             comes back parsed

    The second is the spelling `mirror` has always used for its source and
    target, so this is one notation across all three invariant kinds rather
    than a new one.
    """
    if '#' in key:
        fname, dotted = key.split('#', 1)
        doc = files.get(fname)
        if doc is None:
            path = os.path.join(cfgdir, fname)
            if not os.path.exists(path):
                return None, False
            doc = load_jsonc(path)
            files[fname] = doc
        return dig(doc, dotted)
    if key in cfg:
        return cfg[key], True
    return None, False


def inv_bool(value):
    """An invariant key's value as a flag. A cfg key arrives as a string."""
    if isinstance(value, str):
        return value.strip().lower() == 'true'
    return bool(value)


def inv_float(value):
    """An invariant key's value as a number. Raises for anything that is not
    one, which the caller treats as 'skip this group' -- MISSING and RANGE own
    an absent or mistyped key."""
    if isinstance(value, bool):
        raise ValueError('a bool is not a number here')
    if isinstance(value, str):
        return float(value.strip())
    if isinstance(value, (int, float)):
        return float(value)
    raise ValueError('%r is not a number' % (value,))


def check_range(name, val, rng, problems):
    if rng is None or val is None:               return
    if isinstance(val, float) and val != val:    return   # NaN = "leave alone"
    if isinstance(val, bool) or not isinstance(val, (int, float)): return
    lo, hi = rng
    if val < lo or val > hi:
        problems.append(('RANGE', f'{name} = {val}, declared range [{lo}, {hi}]'))

# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game')
    ap.add_argument('--config')
    ap.add_argument('--schema', default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument('--no-cfg', action='store_true',
                    help='the directory has no ckf.hardmode.cfg and is not meant to: '
                         'check the JSON document and the mirror only. This is for '
                         'mods/CKFHardMode/defaults/, part of the set the release zip ships. '
                         'BepInEx owns the .cfg and writes it itself, so a default set '
                         'cannot carry one, and without this flag its one declared key '
                         'reads as MISSING and the run can never be clean.')
    a = ap.parse_args()

    cfgdir = a.config or (os.path.join(a.game, 'BepInEx', 'config') if a.game else None)
    if not cfgdir or not os.path.isdir(cfgdir):
        sys.exit('need --game or --config pointing at BepInEx/config')

    schemas = []
    for fn in sorted(os.listdir(a.schema)):
        if fn.endswith('.schema.json'):
            schemas.append(load_jsonc(os.path.join(a.schema, fn)))
    if not schemas:
        sys.exit(f'no *.schema.json in {a.schema}')

    cfg_path = os.path.join(cfgdir, 'ckf.hardmode.cfg')
    cfg = {} if a.no_cfg else load_cfg(cfg_path)
    problems, declared_cfg = [], set()

    # One physical file can now hold several subsystems, each under its own
    # top-level "section". Read each file once; dig the section out per schema.
    files, claimed = {}, {}
    for sch in schemas:
        f = (sch.get('targets') or {}).get('json')
        if not f or f in files:
            continue
        p = os.path.join(cfgdir, f)
        files[f] = load_jsonc(p) if os.path.exists(p) else None

    for sch in schemas:
        name = sch['subsystem']
        tgt = sch.get('targets') or {}
        sidecar = tgt.get('json')
        section = tgt.get('section')
        js = None
        if sidecar:
            doc = files.get(sidecar)
            if doc is None:
                problems.append(('MISSING', f'{name}: sidecar {sidecar} not on disk'))
            elif section:
                claimed.setdefault(sidecar, set()).add(section)
                if section in doc:
                    js = doc[section]
                else:
                    problems.append(('MISSING',
                        f'{name}: {sidecar} has no "{section}" section'))
            else:
                js = doc
            # A label that names the file AND the section, so a problem line
            # still says where to look now that five subsystems share a file.
            sidecar = f'{sidecar}#{section}' if section else sidecar

        for en in ('cfg',):
            if sch.get('enable', {}).get(en):
                declared_cfg.add(sch['enable'][en])

        for f in sch['fields']:
            path, where, typ = f['path'], f['in'], f['type']
            optional = f.get('optional') is True
            if where == 'cfg':
                declared_cfg.add(path)
                if a.no_cfg:
                    # Declared, deliberately not looked for. Counted so the
                    # trailing line still reports what the schemas declare.
                    continue
                if path not in cfg:
                    if not optional:
                        problems.append(('MISSING', f'{name}: cfg key {path} declared but absent'))
                    continue
                val, ok = coerce(cfg[path], typ)
                if not ok:
                    problems.append(('RANGE', f'{path} = {cfg[path]!r} is not a {typ}'))
                    continue
                check_range(path, val, f.get('range'), problems)
            else:
                if js is None:
                    continue
                val, found = dig(js, path)
                if not found:
                    # "optional": true means omission is legal. Deliberately a
                    # key of its own rather than a second meaning for "absent":
                    # overloading "absent" would also silence MISSING for every
                    # field that documents an omitted value's meaning and is
                    # nevertheless on disk today.
                    if not optional:
                        problems.append(('MISSING', f'{name}: {sidecar} path "{path}" declared but absent'))
                    continue
                if typ == 'table':
                    cols = {c['name']: c for c in f.get('row', [])}
                    rows = table_rows(val, f.get('keyedBy'), cols)
                    for i, row in enumerate(rows or []):
                        if not isinstance(row, dict): continue
                        for k, v in row.items():
                            c = cols.get(k)
                            if c: check_range(f'{path}[{i}].{k}', v, c.get('range'), problems)
                else:
                    check_range(f'{sidecar}:{path}', val, f.get('range'), problems)

    for key in sorted(cfg):
        if key not in declared_cfg:
            problems.append(('STALE', f'cfg key {key} = {cfg[key]!r} is on disk but no schema declares it'))

    # A top-level key in a shared file that no schema claims as a section.
    #
    # This replaces a guard the split gave for free. When each subsystem owned
    # a whole file, a stray key at its root landed in the C# POCO's
    # [JsonExtensionData] bag and the loader refused the file. In a shared
    # document a MISSPELLED SECTION ("elapes") belongs to no POCO at all, so
    # nothing sees it and the subsystem quietly runs on its defaults. Reported
    # here, and by ConfigDoc at runtime, so the mistake is loud in both places.
    for fname, doc in files.items():
        if doc is None or not claimed.get(fname):
            continue
        for key in sorted(doc):
            if key == '_version' or key in claimed[fname]:
                continue
            problems.append(('STALE',
                f'{fname}: top-level key "{key}" is not a section any schema '
                f'declares. Nothing reads it. A misspelled section name looks '
                f'exactly like this and silently disables its subsystem.'))

    # ---- invariants
    for sch in schemas:
        for inv in sch.get('invariants', []):
            if inv['kind'] == 'linkedEnable':
                states = {}
                for k in inv['keys']:
                    v, found = inv_value(k, cfg, files, cfgdir)
                    if found:
                        states[k] = inv_bool(v)
                if states and len(set(states.values())) > 1:
                    on  = [k for k, v in states.items() if v]
                    off = [k for k, v in states.items() if not v]
                    problems.append(('INVARIANT',
                        f'linked group half on: {", ".join(on)} true, {", ".join(off)} false. {inv["reason"]}'))
            elif inv['kind'] == 'ordered':
                # Keys that must be non-decreasing left to right.
                vals = []
                for k in inv['keys']:
                    v, found = inv_value(k, cfg, files, cfgdir)
                    if not found: break
                    try: vals.append((k, inv_float(v)))
                    except ValueError: break
                else:
                    for (ka, va), (kb, vb) in zip(vals, vals[1:]):
                        if va > vb:
                            problems.append(('INVARIANT',
                                f'{ka} = {va:g} is above {kb} = {vb:g}. {inv["reason"]}'))
            elif inv['kind'] == 'mirror':
                sfile, spath = inv['source'].split('#')
                tgt = os.path.join(cfgdir, inv['target'])
                sp  = os.path.join(cfgdir, sfile)
                if not os.path.exists(sp):  continue
                src_rows = dig(load_jsonc(sp), spath.rstrip('[]'))[0] or []
                stock = {}
                if inv.get('mergeWith'):
                    mfile, mpath = inv['mergeWith'].split('#')
                    for r in dig(load_jsonc(os.path.join(cfgdir, mfile)), mpath.rstrip('[]'))[0] or []:
                        stock[tuple(r[k] for k in inv['match'])] = r[inv['value']]
                merged = dict(stock)
                for r in src_rows:
                    merged[tuple(r[k] for k in inv['match'])] = r[inv['value']]
                # Only cells that differ from stock need a label rule; a rule
                # setting a column to what it already holds changes nothing.
                want = {k: v for k, v in merged.items()
                        if k not in stock or abs(float(stock[k]) - float(v)) > 1e-12}
                if not os.path.exists(tgt):
                    problems.append(('INVARIANT',
                        f'mirror target {inv["target"]} does not exist; '
                        f'{len(want)} cell(s) have no generated label'))
                    continue
                have = {}
                for rule in (load_jsonc(tgt).get('rules') or []):
                    w = rule.get('where', {})
                    try:    have[tuple(w[k] for k in inv['match'])] = rule['set'][inv['value']]
                    except KeyError: continue
                for k in sorted(set(want) | set(have)):
                    if k not in have:
                        problems.append(('INVARIANT', f'mirror: {inv["match"]}={k} award {want[k]} has no label rule'))
                    elif k not in want:
                        problems.append(('INVARIANT', f'mirror: {inv["match"]}={k} has a label rule but the award is stock'))
                    elif abs(float(have[k]) - float(want[k])) > 1e-9:
                        problems.append(('INVARIANT', f'mirror: {inv["match"]}={k} award {want[k]} vs label {have[k]}'))

    order = {'STALE': 0, 'MISSING': 1, 'RANGE': 2, 'INVARIANT': 3}
    for kind, msg in sorted(problems, key=lambda p: (order[p[0]], p[1])):
        print(f'{kind:10s} {msg}')
    where_cfg = ('no ckf.hardmode.cfg read (--no-cfg)' if a.no_cfg
                 else f'{len(cfg)} cfg key(s) on disk')
    print(f'\n{len(problems)} problem(s). {where_cfg}, '
          f'{len(declared_cfg)} declared across {len(schemas)} schema file(s).')
    return 1 if problems else 0

if __name__ == '__main__':
    sys.exit(main())
