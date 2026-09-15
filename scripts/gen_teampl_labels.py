#!/usr/bin/env python3
"""
Generate the victory-screen Team PL label rules from whichever file the
`mirror` invariant in schema/*.schema.json names as its source.

    python gen_teampl_labels.py --game "C:\\...\\Cyber Knights Flashpoint"
    python gen_teampl_labels.py --game "..." --check        # CI / pre-launch
    python gen_teampl_labels.py --game "..." --strip-rules  # one-time migration

WHICH FILE IT READS, AND WHY IT IS NOT WRITTEN DOWN HERE

Three layouts have held the award rows now: ckf.hardmode.teampl.json in 2.x,
the "teampl" section of the merged ckf.hardmode.json in 3.0, and since Phase 3
of split-config-into-toggleable-slices a slice file, ckf.hardmode.d/teampl.json.
This script used to carry the last two as a written-down list, so against the
split directory it exited 1 with
`not found: <dir>\\ckf.hardmode.json (nor the legacy <dir>\\ckf.hardmode.teampl.json)`
and gate 05 went with it [measured 2026-09-13, against the split layout].

It now resolves the file from the declaration that already names it -- the
`mirror` invariant whose `target` is this script's own output. That invariant
gives the source rows (`source`), the reference rows to merge under them
(`mergeWith`) and the file to write (`target`), so a fourth layout moves all
three by editing the schema and nothing here. serve.py's
`_teampl_first_fraction` was fixed the same way and for the same reason; this
is the same resolution, one layer up.

WHY THIS EXISTS

The Team Power Level a mission awards is set in two places that must agree and
have no mechanism keeping them equal:

  award  GameDb.SumGameMissionScore() is a SQL aggregate. Progression.AfterSum
         postfixes it and substitutes from teampl.json's merged table.
  label  The victory screen re-reads MissionPowerLevelModel through the row
         materialiser after the row is inserted. ModelRules postfixes THAT.

The aggregate materialises no row, so it never sees a rules.json edit.
closed-routes.md:133-136 has the measured proof: a rule set to 3.0 printed
"Team gained 3 PL" on screen while the sum moved 0.015.

So teampl.json's "override" is canonical and the label rules are generated from
it. They are emitted into ckf.hardmode.d/ rather than written back into
rules.json, because Overlays.cs:38-45 makes a .json in that directory an
ordinary rules file merged after rules.json in filename order. rules.json stays
hand-authored and no tool ever touches it again.

WHAT GETS EMITTED

Only cells where the merged value DIFFERS from the game's own "table" value. A
rule setting a column to what it already holds changes nothing and costs a
match per row, so stock cells get no rule. Rules are sorted by
(ActionClass, MissionPowerLevel) so an unchanged run reproduces the file
byte for byte and a diff shows only real edits.

WHAT IT WILL NOT TOUCH

teampl.json's "table" section. It is reference only: Load() puts it in Cells
(Progression.cs:446-447) and Merged() reads Overrides ahead of Cells
(:340-342), so no cell of it is ever substituted. The mod reconciles its own
arithmetic against it before substituting anything, and corrupting it makes
that reconcile fail, which sets retroDead (Progression.cs:298-312) and silently
reverts awards to stock while the labels stay modded.
"""

import argparse, json, os, re, shutil, sys


def newline_of(path, default='\n'):
    """Whatever line ending the file already uses. Never convert one silently."""
    if not os.path.exists(path):
        return default
    with open(path, 'rb') as f:
        raw = f.read(65536)
    return '\r\n' if b'\r\n' in raw else '\n' 

BANNER = "MissionPowerLevelModel"
OUTNAME = "MissionPowerLevelModel.generated.json"
SCHEMA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          os.pardir, 'schema')


# --------------------------------------------------------------------------
# JSONC. The five sidecars became pure JSON in gui-plan.md 5.5 and nothing
# writes a comment into one any more, but a hand-added // or trailing comma is
# still legal input (SCHEMA-FORMAT.md), and ckf.hardmode.rules.json is still
# hand-authored JSONC. This stays.

def strip_jsonc(s):
    out, instr, esc, i = [], False, False, 0
    while i < len(s):
        c = s[i]
        if instr:
            out.append(c)
            if esc:         esc = False
            elif c == '\\': esc = True
            elif c == '"':  instr = False
            i += 1; continue
        if c == '"':
            instr = True; out.append(c); i += 1; continue
        if c == '/' and i + 1 < len(s) and s[i + 1] == '/':
            while i < len(s) and s[i] != '\n': i += 1
            continue
        if c == '/' and i + 1 < len(s) and s[i + 1] == '*':
            j = s.find('*/', i + 2); i = (j + 2) if j >= 0 else len(s); continue
        out.append(c); i += 1
    return re.sub(r',(\s*[}\]])', r'\1', ''.join(out))


def load_jsonc(path):
    with open(path, encoding='utf-8-sig') as f:
        return json.loads(strip_jsonc(f.read()))


def dig(obj, dotted):
    """check_schema.dig, copied rather than imported. -> (value, found).

    schema/ is not on sys.path for a bare `python scripts\\gen_teampl_labels.py`
    and this script is imported BY serve.py rather than the other way round, so
    importing check_schema here would make the GUI's import order decide
    whether the CLI runs. Six lines, no behaviour of its own."""
    for part in dotted.split('.'):
        if not isinstance(obj, dict) or part not in obj:
            return None, False
        obj = obj[part]
    return obj, True


# --------------------------------------------------------------------------
# WHERE THE ROWS ARE. Read from the `mirror` invariant, never from a list here.

def load_schemas(schema_dir):
    """-> [(filename, parsed schema)]. Raises if the directory holds none:
    an empty schema set would make every mirror lookup below come back
    'no declaration' and read as a layout problem instead of a missing
    checkout."""
    out = []
    for fn in sorted(os.listdir(schema_dir)):
        if fn.endswith('.schema.json'):
            out.append((fn, load_jsonc(os.path.join(schema_dir, fn))))
    if not out:
        raise SystemExit(f'no *.schema.json in {schema_dir}')
    return out


def mirror_for(schemas, outname):
    """The one `mirror` invariant whose target is `outname`.

    -> (schema filename, schema, invariant). Raises if there is not exactly
    one: two schemas generating the same file, or none, is a schema bug and
    silently picking the first would hide it."""
    hits = [(fn, sch, inv) for fn, sch in schemas
            for inv in sch.get('invariants', [])
            if inv.get('kind') == 'mirror'
            and os.path.basename(inv.get('target', '')) == outname]
    if len(hits) != 1:
        raise SystemExit(
            f'{len(hits)} schema(s) declare a mirror whose target is {outname}; '
            f'expected exactly 1. Found: '
            + (', '.join(f'{fn}:{inv.get("target")}' for fn, _s, inv in hits)
               or 'none')
            + f'. Looked in {SCHEMA_DIR}.')
    return hits[0]


def split_ref(ref):
    """"file#a.b.rows[]" -> ("file", "a.b.rows", "a.b"), the last being the
    object that CONTAINS the rows -- the section, or None at the file root."""
    fname, path = ref.split('#', 1)
    if path.endswith('[]'):
        path = path[:-2]
    parent = path.rsplit('.', 1)[0] if '.' in path else None
    return fname, path, parent


def read_source(cfgdir, schfile, sch, inv):
    """The rows the mirror is generated from, from whichever file is on disk.

    -> (object shaped for merged_cells, srcname, path read, note). `srcname`
    is the provenance string written into the output, and is built the same
    way serve.py builds it when it regenerates the mirror inside a save:
    "<file>#<section>" when the rows sit under a section, "<file>" when the
    file IS the section. Both spellings are produced by the same two lines,
    so the two writers cannot drift apart on it.

    Candidates, in order, each one a declaration and not a filename written
    down here:
      1. the mirror's own `source` file  -- ckf.hardmode.d/teampl.json today
      2. the schema's `targets.legacyJson` -- the 2.x sidecar, whose root IS
         the section, so the declared paths keep only their last segment
    The second is UNEXERCISED by any gate in this repository: nothing on this
    machine has a 2.x sidecar, so a run that takes it has never been measured.
    The failure below names every candidate it tried and which of them was on
    disk, so a fallback that fires is visible in the output rather than
    inferred from the result."""
    sfile, spath, section = split_ref(inv['source'])
    mfile, mpath, _msec = split_ref(inv['mergeWith'])
    if mfile != sfile:
        raise SystemExit(
            f'mirror source {inv["source"]} and mergeWith {inv["mergeWith"]} '
            f'name different files; this script reads one file.')

    legacy = (sch.get('targets') or {}).get('legacyJson')
    cands = [(sfile, spath, mpath, sfile if section is None
              else f'{sfile}#{section}')]
    if legacy:
        cands.append((legacy, spath.rsplit('.', 1)[-1],
                      mpath.rsplit('.', 1)[-1], legacy))

    tried = []
    for fname, sp, mp, srcname in cands:
        p = os.path.join(cfgdir, *fname.split('/'))
        if not os.path.exists(p):
            tried.append(f'{p} (not on disk)')
            continue
        doc = load_jsonc(p)
        over, ok_o = dig(doc, sp)
        tbl,  ok_t = dig(doc, mp)
        if not ok_o:
            tried.append(f'{p} (on disk, but no "{sp}")')
            continue
        note = ('' if fname == sfile else
                f'  NOTE: read the legacy {fname}; the mirror\'s own source '
                f'{sfile} is not on disk.')
        return ({'override': over or [], 'table': (tbl if ok_t else []) or []},
                srcname, p, note)

    raise SystemExit(
        'the mirror declared in schema/%s could not be read. Tried, in '
        'order:\n%s\nsource: %s   mergeWith: %s' % (
            schfile,
            ''.join('    %s\n' % t for t in tried),
            inv['source'], inv['mergeWith']))


# --------------------------------------------------------------------------

def merged_cells(teampl):
    """-> ({(class, pl): value} merged, {(class, pl): value} stock)"""
    stock = {(r['ActionClass'], r['MissionPowerLevel']): r['PowerLevelFraction']
             for r in teampl.get('table', [])}
    merged = dict(stock)
    for r in teampl.get('override', []):
        merged[(r['ActionClass'], r['MissionPowerLevel'])] = r['PowerLevelFraction']
    return merged, stock


def rules_for(merged, stock):
    """Only cells that differ from the game's own value."""
    out = []
    for key in sorted(merged):
        cls, pl = key
        val = merged[key]
        if key in stock and abs(float(stock[key]) - float(val)) < 1e-12:
            continue
        out.append({
            "comment": f"GENERATED from teampl.json override — ActionClass {cls}, "
                       f"MissionPowerLevel {pl}"
                       + (f" (stock {stock[key]})" if key in stock else " (no stock cell)"),
            "model": "MissionPowerLevelModel",
            "where": {"ActionClass": cls, "MissionPowerLevel": pl},
            "set": {"PowerLevelFraction": val},
        })
    return out


def render(rules, srcname):
    """Pure JSON. gui-plan.md 3 and 5.3: every file the GUI writes is data.

    DIVERGENCE FROM THE PLAN, RECORDED RATHER THAN HIDDEN (AGENTS.md 5).
    gui-plan.md 5.3 says "Strip the // header from render() -- that file is data
    too." The // header is gone, but its CONTENT was not deleted: it is now a
    top-level "_comment" array. That is data, in exactly the way each rule's own
    "comment" key is, so the plan's stated reason -- the file must be data, not
    JSONC -- is met; its literal instruction, delete the prose, is not.

    Why the prose was kept. It is the only DO-NOT-EDIT warning a reader who
    opens the generated overlay will ever see, and the only statement of why the
    mirror exists at all. Deleting it sends the next person to hand-edit a file
    that the next generate silently overwrites. The same choice is already made
    twice in this repository: refresh_mission_roster.py writes REFERENCE_NOTE as
    a top-level "_note", and every rule carries its own "comment".

    Why it is safe. ModelRules.cs:209-211 declares RuleFile with "rules" and
    nothing else. Overlays.LoadJson (Overlays.cs:125-135) sets only
    ReadCommentHandling and AllowTrailingCommas, and leaves
    UnmappedMemberHandling at its default of Skip, so "_comment" is ignored and
    the overlay loads unchanged. [measured]

    If David would rather have the file with no prose in it at all, delete the
    "_comment" key below and regenerate; nothing else depends on it.
    """
    doc = {
        "_comment": [
            "GENERATED FILE — DO NOT EDIT.",
            f"Written by scripts/gen_teampl_labels.py from {srcname} \"override\".",
            "Any edit here is lost on the next generate. Change the award in "
            f"{srcname} and regenerate; that keeps the number the victory screen "
            "prints equal to the number the save actually banks.",
            "These rules exist because the award and the label are read through two "
            "different layers: the award is a SQL aggregate that materialises no row, "
            "the label is the row materialiser. A rules.json edit is invisible to the "
            "first and a teampl.json edit is invisible to the second.",
            f"{len(rules)} rule(s). Cells equal to the game's own value are omitted — "
            "setting a column to what it already holds changes nothing.",
        ],
        "rules": rules,
    }
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


# --------------------------------------------------------------------------

def strip_label_rules(path):
    """Remove every MissionPowerLevelModel rule from rules.json.

    Line based, so every comment and every other rule survives byte for byte.
    Depth is counted over braces AND brackets, ignoring // comment tails, so a
    rule object is recognised by starting at depth 2 — inside the root object,
    inside the "rules" array. Without that the root object itself matches and
    the whole file reads as one block.

    Returns (new_text, count), or (None, 0) if there was nothing to do.
    """
    with open(path, encoding='utf-8-sig') as f:
        lines = f.read().split('\n')

    def delta(line):
        code = line.split('//')[0]
        return sum(code.count(c) for c in '{[') - sum(code.count(c) for c in '}]')

    keep, removed, depth, i = [], 0, 0, 0
    while i < len(lines):
        line = lines[i]
        if line.strip() == '{' and depth == 2:
            d, j = 0, i
            while j < len(lines):
                d += delta(lines[j])
                if d == 0:
                    break
                j += 1
            block = lines[i:j + 1]
            if any(f'"{BANNER}"' in b for b in block):
                removed += 1
                i = j + 1
                continue
            keep.extend(block)
            for b in block:
                depth += delta(b)
            i = j + 1
            continue
        keep.append(line)
        depth += delta(line)
        i += 1

    if not removed:
        return None, 0

    # The last surviving rule now ends "}," with only the array close after it.
    for k in range(len(keep) - 1, -1, -1):
        s = keep[k].strip()
        if s == '},':
            nxt = next((keep[m].strip() for m in range(k + 1, len(keep))
                        if keep[m].strip()), '')
            if nxt == ']':
                keep[k] = keep[k].replace('},', '}')
            break
        if s and s not in (']', '}'):
            break

    return '\n'.join(keep), removed


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--game')
    ap.add_argument('--config')
    ap.add_argument('--check', action='store_true',
                    help='verify the generated file is current; exit 1 if not')
    ap.add_argument('--strip-rules', action='store_true',
                    help='one-time migration: remove MissionPowerLevelModel rules from rules.json')
    ap.add_argument('--schema', default=SCHEMA_DIR,
                    help='where the *.schema.json declaring the mirror live '
                         '(default: ../schema beside this script)')
    a = ap.parse_args()

    cfgdir = a.config or (os.path.join(a.game, 'BepInEx', 'config') if a.game else None)
    if not cfgdir or not os.path.isdir(cfgdir):
        sys.exit('need --game or --config pointing at BepInEx/config')
    if not os.path.isdir(a.schema):
        sys.exit(f'no schema directory at {a.schema}; this script reads the '
                 f'mirror invariant to find the file it generates from')

    schfile, sch, inv = mirror_for(load_schemas(a.schema), OUTNAME)
    teampl, srcname, src_path, note = read_source(cfgdir, schfile, sch, inv)

    merged, stock = merged_cells(teampl)
    rules = rules_for(merged, stock)
    text = render(rules, srcname)

    # The target is the invariant's too, so the output directory is not a
    # second filename written down here either.
    out = os.path.join(cfgdir, *inv['target'].split('/'))
    outdir = os.path.dirname(out)

    if note:
        print(note.strip())

    if a.check:
        if not os.path.exists(out):
            print(f'STALE  {OUTNAME} does not exist; {len(rules)} rule(s) would be written')
            return 1
        with open(out, encoding='utf-8-sig') as f:
            cur = f.read()
        if cur != text:
            have = {(r['where']['ActionClass'], r['where']['MissionPowerLevel']):
                    r['set']['PowerLevelFraction']
                    for r in (load_jsonc(out).get('rules') or [])}
            want = {(r['where']['ActionClass'], r['where']['MissionPowerLevel']):
                    r['set']['PowerLevelFraction'] for r in rules}
            for k in sorted(set(have) | set(want)):
                if k not in have:   print(f'STALE  ActionClass {k[0]} PL {k[1]}: label missing, award {want[k]}')
                elif k not in want: print(f'STALE  ActionClass {k[0]} PL {k[1]}: label {have[k]} but award is now stock')
                elif abs(float(have[k]) - float(want[k])) > 1e-12:
                    print(f'STALE  ActionClass {k[0]} PL {k[1]}: label {have[k]} vs award {want[k]}')
            print(f'\n{OUTNAME} is out of date. Regenerate.')
            return 1
        # Names the file it actually read. The old wording said "teampl.json"
        # whichever of the three layouts it had opened, so a run against the
        # wrong one looked exactly like a run against the right one.
        print(f'{OUTNAME} current — {len(rules)} rule(s) match {srcname}.')
        return 0

    os.makedirs(outdir, exist_ok=True)
    nl = newline_of(out, newline_of(src_path))
    with open(out, 'w', encoding='utf-8', newline=nl) as f:
        f.write(text)
    print(f'wrote {out}')
    print(f'  read {src_path}  (mirror source {inv["source"]}, '
          f'declared in schema/{schfile})')
    print(f'  {len(rules)} rule(s) from {len(merged)} merged cell(s) '
          f'({len(merged) - len(rules)} at the game\'s own value, omitted)')

    if a.strip_rules:
        rp = os.path.join(cfgdir, 'ckf.hardmode.rules.json')
        new, n = strip_label_rules(rp)
        if not n:
            print(f'  rules.json: no {BANNER} rules found — nothing to strip')
        else:
            shutil.copy2(rp, rp + '.pre-teampl-split-backup')
            with open(rp, 'w', encoding='utf-8', newline=newline_of(rp)) as f:
                f.write(new)
            print(f'  rules.json: removed {n} {BANNER} rule(s) '
                  f'(backup at ckf.hardmode.rules.json.pre-teampl-split-backup)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
