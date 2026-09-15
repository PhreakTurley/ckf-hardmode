#!/usr/bin/env python3
"""
Verify the live config against the schema files.

    python check_schema.py --game "C:\\...\\Cyber Knights Flashpoint" [--schema DIR]

Reports four classes of drift. Exit code 1 if any STALE, MISSING, RANGE or
INVARIANT problem is found.

  STALE      a key on disk that no schema field declares, or an overlay CSV in
             ckf.hardmode.d that no schema's targets.overlays names. This is the check
             that would have caught the 12 dead cfg keys without a manual grep.
  MISSING    a schema field with no key on disk, unless that field declares
             "optional": true, which says omission from the file is legal.
             "optional" is NOT implied by "absent" and does not imply it:
             "absent" documents what an omitted value MEANS, "optional" says
             the omission is allowed at all. A field may carry either, both or
             neither, and a field carrying only "absent" still reports MISSING.
  RANGE      a value outside its declared range
  INVARIANT  a mirror whose sides disagree, a half-on linkedEnable group, an
             'ordered' group whose keys are out of order, or a 'requires'
             whose dependent key is true while a key it needs is false

A 'requires' whose own key, or one of its 'needs' keys, no schema declares is
not an INVARIANT: an undeclared 'key' is MISSING and an undeclared 'needs' entry
is STALE, because the fault is in the declaration rather than in the config.

A 'requires' it could not evaluate -- a declared key that is not on disk, or
--no-cfg, under which the cfg dict is empty by construction -- is NOT silence.
Every such group prints a SKIPPED line and is counted on the 'requires:' census
line, which is printed on every run whether or not anything was skipped.
'ordered' and 'linkedEnable' carry the same census, for the same reason and
since 2026-09-13: without it a group whose keys no longer resolve is skipped in
silence and the run still prints '0 problem(s).' An
instrument that can decline to look has to say when it declined.
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

CFG_FILE = 'ckf.hardmode.cfg'


def inv_key(key):
    """One key, whichever of the three spellings an invariant used.

    'Slices.X' and 'ckf.hardmode.cfg#Slices.X' are the same cfg key and both
    normalise to the bare form, which is what load_cfg's dict and declared_cfg
    hold. A '<json file>#<dotted path>' key is returned unchanged.

    CORRECTION, 2026-09-13. tasks.md's Phase 2 checkbox 2 says "inv_value
    already reads a key in either space via mirror's <file>#<path> notation, so
    no new key resolution is needed", and design.md section 4's `requires`
    example spells its key 'ckf.hardmode.cfg#Slices.CyberweaponsLasers'. Both
    cannot be true, and it is the checkbox that is wrong. The two spellings
    inv_value read were 'Section.Key' and '<json file>#<path>'; a key prefixed
    with the .cfg's own name took the '#' branch, handed an INI file to
    load_jsonc and raised

        json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)

    -- an uncaught traceback, not a miss and not a problem line. Measured
    2026-09-13 against the unmodified check_schema.py, with that spelling on a
    linkedEnable over the live 43-key ckf.hardmode.cfg. This function is the
    new key resolution the checkbox says is not needed, and it is two lines.
    """
    return key[len(CFG_FILE) + 1:] if key.startswith(CFG_FILE + '#') else key


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
    key = inv_key(key)
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


def inv_declared(key, declared_cfg, declared_json):
    """Does any schema field declare the key an invariant names?

    The same two spellings inv_value resolves. This is a question about the
    SCHEMAS, not about the disk: a key every schema has forgotten is a broken
    declaration, and a declared key merely absent from disk is MISSING's and
    the skip census's business, not this function's.
    """
    key = inv_key(key)
    return key in (declared_json if '#' in key else declared_cfg)


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
                         'any config directory without a .cfg, such as a copy of the '
                         'JSON files taken out of BepInEx/config. Without this flag '
                         'the .cfg\'s one declared key reads as MISSING and the run '
                         'can never be clean.')
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
    # Every field path an invariant may legally name, in the two spellings
    # inv_value resolves: "Section.Key" for a cfg key, "<file>#<dotted path>"
    # for a path inside a config document. 'requires' checks its key and its
    # needs against these before it looks on disk, so a declaration naming a
    # key nothing declares is reported as a bad declaration rather than as a
    # violated invariant.
    declared_json = set()

    # One physical file can now hold several subsystems, each under its own
    # top-level "section". Read each file once; dig the section out per schema.
    files, claimed = {}, {}
    for sch in schemas:
        f = (sch.get('targets') or {}).get('json')
        if not f or f in files:
            continue
        p = os.path.join(cfgdir, f)
        files[f] = load_jsonc(p) if os.path.exists(p) else None

    # Every overlay path any schema claims, and who claimed it. A direct
    # overlay is NOT a JSON document -- it is a CSV whose header names game
    # columns -- so it is checked for EXISTENCE and never parsed. Pointing
    # targets.json at one instead raises an uncaught JSONDecodeError out of
    # load_jsonc and the run dies with a traceback rather than a graded
    # problem. [measured 2026-09-13]
    claimed_overlays = {}
    for sch in schemas:
        for rel in (sch.get('targets') or {}).get('overlays') or []:
            claimed_overlays.setdefault(rel, []).append(sch['subsystem'])

    for sch in schemas:
        name = sch['subsystem']
        tgt = sch.get('targets') or {}
        sidecar = tgt.get('json')
        section = tgt.get('section')
        # AN ABSENT OVERLAY IS A PROBLEM, NOT A SKIP. A pack that lists three
        # files and finds two would otherwise read as "that class has no rules
        # for this model", which is the instrument-silence failure AGENTS.md
        # section 3 names and Phase 4's own checkbox calls out by name.
        for rel in tgt.get('overlays') or []:
            if not os.path.exists(os.path.join(cfgdir, rel)):
                problems.append(('MISSING',
                    f'{name}: overlay {rel} is declared but not on disk. A slice '
                    f'that lists a file and does not find it applies fewer rules '
                    f'than it declares, and nothing else would say so.'))
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
            if where == 'reference':
                # Data that lives in the SCHEMA, not in a config file: a
                # snapshot the editor renders beside the control it annotates.
                # There is nothing on disk to compare it against -- that is the
                # point of it -- so the only thing checkable here is that the
                # snapshot obeys its own declared column ranges.
                cols = {c['name']: c for c in f.get('row', [])}
                for i, row in enumerate(f.get('rows') or []):
                    if not isinstance(row, dict):
                        continue
                    for k, v in row.items():
                        c = cols.get(k)
                        if c:
                            check_range(f'{name}: {path}[{i}].{k}', v,
                                        c.get('range'), problems)
                continue
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
                declared_json.add(f'{sidecar}.{path}' if section
                                  else (f'{sidecar}#{path}' if sidecar else path))
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
    #
    # THREE CENSUSES, NOT ONE. 'requires' got a skip census when it was added
    # and 'ordered' and 'linkedEnable' did not, so those two could decline to
    # look and still let the run print "0 problem(s)." That is what happened
    # when Phase 3 split the merged document: powerlevel's ordered pair named
    # ckf.hardmode.json, inv_value returned not-found, the for/else below took
    # the break, and nothing said so. minCap 20 above maxCap 1 reported 0
    # problems at rc 0. [measured 2026-09-13] Every kind now counts what it
    # declared, what it actually compared, and what it skipped and why.
    req_total = req_checked = req_vacuous = 0
    req_skipped = []
    ord_total = ord_checked = 0
    ord_skipped = []
    link_total = link_checked = 0
    link_skipped = []
    for sch in schemas:
        # `name` was NOT rebound here before 2026-09-13. It held whatever the
        # field loop above left in it -- the last schema in sorted order,
        # Progression -- so any invariant message naming `name` named the wrong
        # subsystem. No existing kind's message used it, so nothing showed it;
        # the first `requires` message did, reporting a CyberweaponsClaws
        # declaration as "Progression:". [measured 2026-09-13]
        name = sch['subsystem']
        for inv in sch.get('invariants', []):
            if inv['kind'] == 'linkedEnable':
                link_total += 1
                # A PARTIALLY READ GROUP IS NOT A CLEAN ONE. This used to keep
                # whichever keys resolved and compare those: one key of a pair
                # readable and the other not gave a single state, which can
                # never disagree with itself, so the group passed without
                # anything being compared. A group is compared only when every
                # key in it was read.
                states, unread = {}, []
                for k in inv['keys']:
                    v, found = inv_value(k, cfg, files, cfgdir)
                    if found:
                        states[k] = inv_bool(v)
                    else:
                        unread.append(k)
                if unread:
                    why = ('was not read (--no-cfg)' if a.no_cfg
                           else 'did not resolve against the config directory')
                    link_skipped.append(
                        f'{name}: linkedEnable -- {", ".join(unread)} {why}, so '
                        f'the group was not compared')
                    continue
                link_checked += 1
                if states and len(set(states.values())) > 1:
                    on  = [k for k, v in states.items() if v]
                    off = [k for k, v in states.items() if not v]
                    problems.append(('INVARIANT',
                        f'linked group half on: {", ".join(on)} true, {", ".join(off)} false. {inv["reason"]}'))
            elif inv['kind'] == 'requires':
                # Directed, which linkedEnable is not. "key is true" is the
                # antecedent; every key in "needs" must then also be true.
                # Turning the dependent OFF is always legal here -- the
                # asymmetry is the point, and the downward refusal lives in
                # the editor, which knows which key the player just moved.
                req_total += 1
                dep, reason = inv['key'], inv.get('reason', '')
                needs = inv.get('needs') or []
                if not inv_declared(dep, declared_cfg, declared_json):
                    problems.append(('MISSING',
                        f'{name}: requires names key {dep}, which no schema '
                        f'declares. Nothing can enforce it. {reason}'))
                    req_skipped.append(f'{name}: requires on {dep} -- key is '
                                       f'not declared by any schema')
                    continue
                # A requires with no needs is a check with no subject. It would
                # pass every run and mean nothing, which is the exact shape of
                # the four instruments in this repo that reported success over
                # an empty input.
                if not needs:
                    problems.append(('MISSING',
                        f'{name}: requires on {dep} declares no "needs" keys. '
                        f'Nothing is compared. {reason}'))
                    req_skipped.append(f'{name}: requires on {dep} -- empty needs')
                    continue
                undeclared = [k for k in needs
                              if not inv_declared(k, declared_cfg, declared_json)]
                for k in undeclared:
                    problems.append(('STALE',
                        f'{name}: requires {dep} needs {k}, which no schema '
                        f'declares. The declaration is stale. {reason}'))
                live = [k for k in needs if k not in undeclared]
                # Two different reasons a key does not resolve, and they are
                # not the same fact: --no-cfg never opened the file, while a
                # normal run opened it and did not find the key. Naming the
                # wrong one would misreport why the check declined to look.
                why = ('was not read (--no-cfg)' if a.no_cfg
                       else 'is declared but not on disk')
                dv, dfound = inv_value(dep, cfg, files, cfgdir)
                if not dfound:
                    req_skipped.append(
                        f'{name}: requires on {dep} -- {dep} {why}, so the '
                        f'group was not compared')
                    continue
                if not inv_bool(dv):
                    req_vacuous += 1
                    continue
                checked_any = False
                for k in live:
                    nv, nfound = inv_value(k, cfg, files, cfgdir)
                    if not nfound:
                        req_skipped.append(
                            f'{name}: requires {dep} needs {k} -- {k} {why}, '
                            f'so it was not compared')
                        continue
                    checked_any = True
                    if not inv_bool(nv):
                        problems.append(('INVARIANT',
                            f'requires: {dep} is true but {k}, which it needs, '
                            f'is false. {reason}'))
                if checked_any:
                    req_checked += 1

            elif inv['kind'] == 'ordered':
                # Keys that must be non-decreasing left to right.
                #
                # The two ways this declines to look are DIFFERENT FACTS and are
                # reported apart: a key that did not resolve at all, and a key
                # that resolved to something that is not a number. The MISSING
                # and RANGE checks own both conditions for a declared FIELD, but
                # an invariant can name a key no field declares, so neither of
                # those would necessarily have said anything.
                ord_total += 1
                vals, why = [], None
                for k in inv['keys']:
                    v, found = inv_value(k, cfg, files, cfgdir)
                    if not found:
                        why = (f'{k} was not read (--no-cfg)' if a.no_cfg
                               else f'{k} did not resolve against the config '
                                    f'directory')
                        break
                    try:
                        vals.append((k, inv_float(v)))
                    except ValueError:
                        why = f'{k} is {v!r}, which is not a number'
                        break
                if why is not None:
                    ord_skipped.append(
                        f'{name}: ordered -- {why}, so the group was not '
                        f'compared')
                else:
                    ord_checked += 1
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

    # ---- overlay census
    #
    # 33 overlay files and 312 rows landed in ckf.hardmode.d on 2026-09-13 and
    # this run's output did not move by one character, because nothing declared
    # them. [measured] A file nothing claims is applied by the plugin and
    # validated by no one. The four below are claimed by no schema ON PURPOSE
    # and are named rather than counted as findings: the three enemy-gear
    # overlays are out of scope per the proposal's non-goals, and the teampl
    # mirror is a schema OUTPUT, generated by scripts/gen_teampl_labels.py and
    # checked by the `mirror` invariant rather than by a target.
    LEGITIMATELY_UNCLAIMED = ('ArmorModel.csv', 'WeaponModel.csv',
                              'MonsterTypeModel.csv')
    ov_dir = os.path.join(cfgdir, 'ckf.hardmode.d')
    on_disk = sorted(n for n in (os.listdir(ov_dir) if os.path.isdir(ov_dir) else [])
                     if n.lower().endswith(('.csv', '.tsv')))
    unclaimed = [n for n in on_disk
                 if 'ckf.hardmode.d/' + n not in claimed_overlays
                 and n not in LEGITIMATELY_UNCLAIMED]
    expected_absent = [n for n in LEGITIMATELY_UNCLAIMED if n not in on_disk]
    for n in unclaimed:
        problems.append(('STALE',
            f'ckf.hardmode.d/{n} is on disk and no schema\'s targets.overlays '
            f'names it. The plugin applies it and nothing validates it.'))
    twice = {rel: subs for rel, subs in claimed_overlays.items() if len(subs) > 1}
    for rel, subs in sorted(twice.items()):
        problems.append(('STALE',
            f'{rel} is claimed by more than one schema ({", ".join(sorted(subs))}). '
            f'One file, one slice.'))

    order = {'STALE': 0, 'MISSING': 1, 'RANGE': 2, 'INVARIANT': 3}
    for kind, msg in sorted(problems, key=lambda p: (order[p[0]], p[1])):
        print(f'{kind:10s} {msg}')
    for msg in sorted(req_skipped + ord_skipped + link_skipped):
        print(f'{"SKIPPED":10s} {msg}')
    where_cfg = ('no ckf.hardmode.cfg read (--no-cfg)' if a.no_cfg
                 else f'{len(cfg)} cfg key(s) on disk')
    print(f'\n{len(problems)} problem(s). {where_cfg}, '
          f'{len(declared_cfg)} declared across {len(schemas)} schema file(s).')
    # Printed on every run, including a run with no requires declared at all.
    # "0 declared" and "2 declared, 0 compared" are different facts and a
    # census that only appeared when something went wrong could not tell them
    # apart.
    print(f'requires: {req_total} declared, {req_checked} compared, '
          f'{req_vacuous} vacuous (dependent off), '
          f'{len(req_skipped)} skipped.')
    print(f'ordered: {ord_total} declared, {ord_checked} compared, '
          f'{len(ord_skipped)} skipped.')
    print(f'linkedEnable: {link_total} declared, {link_checked} compared, '
          f'{len(link_skipped)} skipped.')
    print(f'overlays: {len(claimed_overlays)} declared across '
          f'{len([s2 for s2 in schemas if (s2.get("targets") or {}).get("overlays")])} '
          f'schema file(s), {len(on_disk)} csv/tsv on disk, '
          f'{len(unclaimed)} unclaimed, '
          f'{len(LEGITIMATELY_UNCLAIMED) - len(expected_absent)} unclaimed by design '
          f'({", ".join(n for n in LEGITIMATELY_UNCLAIMED if n in on_disk) or "none"}).')
    return 1 if problems else 0

if __name__ == '__main__':
    sys.exit(main())
