"""Maintainer pass: complete talent sheets from a stock Data Dump.

Leaves every existing override unchanged. Missing rows receive blank levers;
comments and _group carry the catalog so the installed editor needs no dump.
Run explicitly; the editor and game never regenerate tuning from stock data.
"""
import argparse
import csv
import io
import json
from pathlib import Path
import re
import tempfile

import modkit

JOBS = {'ck': 1, 'wm': 2, 'cs': 3, 'aex': 5, 'sol': 7, 'sn': 11,
        'vg': 12, 'hkr': 13, 'gs': 14, 'sc': 15, 'wg': 19}
KEYS = {'JobModel': 'JobId', 'JobNodeModel': 'JobNodeId', 'TalentModel': 'TalentId',
        'EffectModel': 'EffectId', 'MatrixEffectModel': 'MatrixEffectId'}
TALENT_LINKS = ('NodeTalent1Id', 'NodeTalentAdjustmentId', 'NodeTalentTriggerId')
NODE_TUNING = ('BuyCost', 'MaxCharges', 'RechargeTurns', 'TurnMaxUses',
               'TalentRange', 'TalentRangeAoE', 'TalentDuration', 'TalentHealing',
               'TalentDamage', 'TalentCount', 'TalentAp', 'TalentLimit')
ATTRIBUTES = ('AttStrong', 'AttFast', 'AttWill', 'AttTech')
# Authored editing columns, checked against the installed parser declaration;
# never derived from whichever nonzero fields happen to occur in the dump.
CATALOG_COLUMNS = {'JobNodeModel': NODE_TUNING,
                   'EffectModel': ATTRIBUTES + ('MaxHitPoints',)}
REGULAR, ATTRIBUTE = 'Talents and upgrades', 'Attribute nodes'


def positive(row, column):
    value = int(row.get(column) or 0)
    return str(value) if value > 0 else None


def is_attribute(node, tables):
    effect = tables['EffectModel'].get(positive(node, 'NodeEffect1Id'), {})
    return any(effect.get(c, '0') != '0' for c in ATTRIBUTES)


def load_stock(dump):
    inputs = {}
    coverage_path = dump / '_coverage.csv'
    inputs[coverage_path] = modkit.state(coverage_path)
    coverage = {r['Table']: r for r in csv.DictReader(io.StringIO(
        coverage_path.read_text(encoding='utf-8-sig')))}
    tables = {}
    for name, key in KEYS.items():
        report = coverage.get(name, {})
        if report.get('Captured') != 'yes' or report.get('Capped') != 'no':
            raise ValueError('Stock dump is incomplete for ' + name)
        path = dump / (name + '.csv')
        inputs[path] = modkit.state(path)
        rows = list(csv.DictReader(io.StringIO(path.read_text(encoding='utf-8-sig'))))
        if len(rows) != int(report['Rows']):
            raise ValueError('Coverage row count disagrees for ' + name)
        by_id = {}
        for row in rows:
            identity = row[key]
            if identity in by_id and by_id[identity] != row:
                raise ValueError('Ambiguous stock (%s, %s)' % (name, identity))
            by_id[identity] = row
        tables[name] = by_id
    return tables, inputs


def catalog(tables, job):
    nodes = {k: r for k, r in tables['JobNodeModel'].items() if int(r['JobId']) == job}
    parent_ids = {}
    for identity, row in nodes.items():
        ids = [positive(row, c) for c in TALENT_LINKS]
        subtree = tables['JobNodeModel'].get(positive(row, 'SubTree'), {})
        ids += [positive(subtree, c) for c in TALENT_LINKS]
        parent_ids[identity] = list(dict.fromkeys(t for t in ids if t))
        for t in parent_ids[identity]:
            if t not in tables['TalentModel']:
                raise ValueError('Missing TalentModel %s for node %s' % (t, identity))
    talent_ids = {t for ids in parent_ids.values() for t in ids}
    owners = {'JobNodeModel': {k: [k] for k in nodes},
              'TalentModel': {t: [] for t in talent_ids},
              'EffectModel': {}, 'MatrixEffectModel': {}}

    def link(table, identity, node_id):
        if not identity:
            return
        if identity not in tables[table]:
            raise ValueError('Missing (%s, %s), referenced by node %s' %
                             (table, identity, node_id))
        users = owners[table].setdefault(identity, [])
        if node_id not in users:
            users.append(node_id)

    for identity, row in nodes.items():
        for t in parent_ids[identity]:
            link('TalentModel', t, identity)
            talent = tables['TalentModel'][t]
            for c in ('TargetEffect', 'SelfEffect'):
                link('EffectModel', positive(talent, c), identity)
            link('MatrixEffectModel', positive(talent, 'MatrixEffect'), identity)
        link('EffectModel', positive(row, 'NodeEffect1Id'), identity)
        link('MatrixEffectModel', positive(row, 'MatrixEffect1Id'), identity)
        trigger = tables['TalentModel'].get(positive(row, 'NodeTalentTriggerId'), {})
        target = ('MatrixEffectModel' if trigger.get('TalentIsMatrixOnly') == '1'
                  else 'EffectModel')
        link(target, positive(row, 'NodeTalentTriggerEffect'), identity)
    return nodes, parent_ids, owners


def render_sheet(raw, table, tag, tables, nodes, parent_ids, owners):
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
    header = list(reader.fieldnames or [])
    key = KEYS[table]
    if not header or header[0] != key:
        raise ValueError('Unexpected key in %s.%s' % (table, tag))
    if any(c.endswith(('+', '*', '^')) for c in header if not c.startswith('_')):
        raise ValueError('Catalog only supports declared set columns')
    original = {}
    for row in reader:
        if not any((v or '').strip() for v in row.values()):
            continue
        if row[key] in original:
            raise ValueError('Duplicate live row in %s.%s' % (table, tag))
        original[row[key]] = row
    identities = set(original) | set(owners[table])
    controls = [c for c in header if c.startswith('_')]
    levers = list(dict.fromkeys(CATALOG_COLUMNS.get(table, ()) + tuple(
        c for c in header[1:] if not c.startswith('_'))))
    header = [key] + levers + controls
    for control in ('_comment', '_group', '_shipped'):
        if control not in header:
            header.append(control)
    rows = []

    def node_label(identity):
        r = tables['JobNodeModel'][identity]
        return r['JobNodeName']

    for identity in sorted(identities, key=int):
        stock = tables[table].get(identity)
        if stock is None:
            raise ValueError('No stock row for (%s, %s)' % (table, identity))
        users = sorted(owners[table].get(identity, []), key=int)
        attr = bool(users) and all(is_attribute(nodes[n], tables) for n in users)
        row = dict(original.get(identity, {}))
        row[key] = identity
        parent = list(dict.fromkeys(t for n in users for t in parent_ids[n]))
        names = list(dict.fromkeys(tables['TalentModel'][t]['TalentName'] for t in parent))
        if table == 'TalentModel':
            label = stock['TalentName']
            names = [label]
        elif table == 'JobNodeModel':
            label = node_label(identity)
        else:
            label = ', '.join(dict.fromkeys(node_label(n) for n in users)) if attr else ', '.join(names)
            if not label:
                label = ', '.join(dict.fromkeys(node_label(n) for n in users)) or 'Effect'
        parts = [label]
        if names and label != ', '.join(names):
            parts.append('Parent: ' + ', '.join(names))
        if not names and not attr and users:
            bases = list(dict.fromkeys(positive(nodes[n], 'SubTree') or n for n in users))
            bases = [n for n in bases if positive(tables['JobNodeModel'][n], 'NodeEffect1Id')]
            if bases:
                parent_label = ', '.join(dict.fromkeys(node_label(n) for n in bases))
                if parent_label != label:
                    parts.append('Parent: ' + parent_label)
        row['_shipped'] = json.dumps({c: stock[c] for c in levers}, separators=(',', ':'))
        if table == 'EffectModel' and attr:
            connected = []
            for owner in users:
                connected += [node_label(n) for c in ('NodeReq1', 'NodeReq2', 'NodeReq3')
                              if (n := positive(nodes[owner], c))]
                dependents = [n for n, r in nodes.items() if owner in
                              [positive(r, c) for c in ('NodeReq1', 'NodeReq2', 'NodeReq3')]]
                connected += [node_label(n) for n in sorted(dependents, key=int)]
            if connected:
                parts.append('Connections: ' + ', '.join(dict.fromkeys(connected)))
        # The overlay reader addresses physical CSV lines; keep each record
        # on one line and let the GUI lay out the compact clauses.
        row['_comment'] = ' | '.join(parts)
        row['_group'] = ATTRIBUTE if attr else REGULAR
        rows.append(row)
    def row_order(row):
        identity = row[key]
        if table == 'JobNodeModel':
            # SubTree names the attached base node in the dump. Keep each
            # base with its upgrades even when a later upgrade has a lower id.
            base = positive(tables[table][identity], 'SubTree') or identity
            name = tables[table][identity]['JobNodeName']
            natural = tuple(int(s) if s.isdigit() else s.casefold()
                            for s in re.split(r'(\d+)', name))
            return (row['_group'] == ATTRIBUTE, int(base), identity != base,
                    natural, int(identity))
        return (row['_group'] == ATTRIBUTE, int(identity))

    rows.sort(key=row_order)
    output = io.StringIO(newline='')
    writer = csv.DictWriter(output, header, lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    # Every pre-existing non-control cell must survive byte-for-cell.
    rebuilt = {r[key]: r for r in csv.DictReader(io.StringIO(output.getvalue()))}
    for identity, old in original.items():
        for c in reader.fieldnames:
            if not c.startswith('_') and (old[c] or '') != (rebuilt[identity][c] or ''):
                raise ValueError('Override changed: (%s,%s,%s)' % (table, identity, c))
    return output.getvalue().encode('utf-8'), len(rows)


def semantics(data):
    parsed = json.loads(data)
    return {(t, r[KEYS[t + 'Model']]): {k: v for k, v in r.items() if k != '#'}
            for t in ('Talent', 'JobNode', 'Effect', 'MatrixEffect') for r in parsed[t]}


def complete(config, dump, project):
    script = project / 'scripts/export_talent_balance.py'
    script_state = modkit.state(script)
    exporter = modkit.load_exporter(project)
    tables, inputs = load_stock(dump)
    inputs[script] = script_state
    cfg = config / 'ckf.hardmode.cfg'
    inputs[cfg] = modkit.state(cfg)
    files = [config / 'ckf.hardmode.d' / name for name, _, _ in exporter.expected_files()]
    expected = {p: modkit.state(p) for p in files}
    originals = {}
    for p in files:
        if p.exists():
            originals[p] = p.read_bytes()
        elif p.name == 'EffectModel.hkr.csv':
            originals[p] = b'EffectId,_comment\n'
        else:
            raise ValueError('Missing live sheet: ' + str(p))
    outputs, counts = {}, {}
    for tag, job in JOBS.items():
        nodes, parents, owners = catalog(tables, job)
        for p in files:
            if p.name.split('.')[1] != tag:
                continue
            outputs[p], counts[p.name] = render_sheet(originals[p], p.name.split('.')[0],
                tag, tables, nodes, parents, owners)
    with tempfile.TemporaryDirectory(prefix='ckf-catalog-check-') as td:
        staged = Path(td) / 'ckf.hardmode.d'
        staged.mkdir()
        (staged.parent / cfg.name).write_bytes(cfg.read_bytes())
        for p, data in originals.items():
            (staged / p.name).write_bytes(data)
        original_export = exporter.build_export(staged, None)[0]
        for p, data in outputs.items():
            (staged / p.name).write_bytes(data)
        proposed = exporter.build_export(staged, None)[0]
        if semantics(original_export) != semantics(proposed):
            raise ValueError('Catalog would change the exported overrides')
    written = modkit.commit_files(outputs, expected, inputs)
    return {'rows': counts, 'written': written, 'overrides_unchanged': True}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--dump', type=Path, required=True)
    ap.add_argument('--project', type=Path, required=True)
    args = ap.parse_args()
    print(json.dumps(complete(args.config, args.dump, args.project), indent=2))
