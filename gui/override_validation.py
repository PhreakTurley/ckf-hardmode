"""Check content declarations and remove redundant assignments from proposed edits."""
import copy
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path

import enemy_armor
import player_balance as pb
import static_data


def numeric_type(declaration):
    return any(name in declaration.upper() for name in ('INT', 'REAL', 'FLOAT', 'DOUBLE', 'NUM', 'DEC'))


def number(text):
    try:
        value = Decimal(text)
        if not value.is_finite() or not math.isfinite(float(value)):
            raise ValueError('A numeric override must be finite and representable.')
        return value
    except (InvalidOperation, OverflowError) as exc:
        raise ValueError('Not a finite numeric override: ' + text) from exc


def matches(text, baseline, numeric):
    if not numeric:
        return text == baseline
    try:
        shipped = Decimal(baseline)
    except InvalidOperation:
        return False  # NULL or text under numeric affinity supplies no numeric default.
    return shipped.is_finite() and number(text) == shipped


def normalize(api, doc, edits, source):
    """Return proposed edits, explicit UI clears and validation notes; never write."""
    edits, cleared, checked = copy.deepcopy(edits), [], 0
    database_sha = pb.identity(source)['sha256']
    tables, declarations = {}, {}

    def content(model):
        if model not in tables:
            table = static_data.sql_name(model)
            aliases = static_data.COLUMN_NAMES.get(table, {})
            schema = source.schema.get(table, [])
            declarations[model] = {aliases.get(r[1], r[1]): r[2] for r in schema}
            keys = [aliases.get(r[1], r[1]) for r in schema if r[5]]
            if len(keys) != 1:
                raise ValueError(model + ': Official data must declare one primary key.')
            tables[model] = {r[keys[0]]: r for r in source.read(model, keys)[1]}
        return tables[model], declarations[model]

    def overlay_cells(rel, entry):
        nonlocal checked
        block = edits.get('overlays', {}).get(rel, {})
        pending = {}
        for cell in block.get('cells', []):
            ri = api.overlay_find_row(entry, cell.get('key'), rel)
            pending[ri, cell.get('column')] = cell
        mapping = api.overlay_column_targets(entry)
        class_wide = Path(rel).name == 'gear-classes.csv'
        for ri, row in enumerate(entry['rows']):
            raw = dict(zip((c['name'] for c in entry['columns']), row['cells']))
            for ci, column in enumerate(entry['columns']):
                if not entry['editable'][ci]:
                    continue
                name = column['name']
                cell = pending.get((ri, name))
                value = cell['value'] if cell is not None else raw.get(name, '')
                api.overlay_check_cell(entry, ci, value, rel, [])
                value = value.strip()
                if not value:
                    continue
                target = mapping.get(name)
                if target is None and class_wide:
                    target = ('WeaponModel', 'WeaponClass', name)
                if target is None:
                    raise ValueError('%s.%s: no declared content-field mapping.' % (rel, name))
                model, identity, field = target
                rows, declared = content(model)
                if field not in declared:
                    raise ValueError('%s.%s: %s.%s is not declared in Official data.' % (rel, name, model, field))
                numeric = numeric_type(declared[field])
                op, operand = column.get('op', 'set'), value
                if entry['kind'] == 'expanded':
                    parsed = api.parse_adjust(value)
                    op = parsed['kind']
                    operand = value[1:].strip() if value[0] in '=+xX*' else value
                if numeric or op != 'set':
                    n = number(operand)
                    if op == 'set' and 'INT' in declared[field].upper() and not -(2 ** 63) <= n < 2 ** 63:
                        raise ValueError('%s.%s: assignment is outside the declared INTEGER storage range.' % (rel, name))
                original = rows.get(raw.get(identity)) if not class_wide and not raw.get('_clone') else None
                checked += 1
                if op != 'set' or original is None or not matches(operand, original[field], numeric):
                    continue
                if cell is None:
                    cell = {'key': row['key'], 'column': name, 'value': ''}
                    edits.setdefault('overlays', {}).setdefault(rel, {'cells': []})['cells'].append(cell)
                cell['value'] = ''
                cleared.append({'kind': 'overlay', 'path': rel, 'key': row['key'], 'column': name})

    # Validate the complete pending surface, including already stored overrides.
    for rel, entry in doc.overlays.items():
        if entry.get('present') and entry.get('writable') and rel != enemy_armor.SHEET:
            overlay_cells(rel, entry)

    path = Path(doc.config_dir) / pb.FILE
    change = edits.get('playerBalance')
    if path.is_file() or change:
        if change and change.get('databaseSha') != database_sha:
            raise ValueError('Official data changed; reload before validating player tuning.')
        document = pb.apply_edits(pb.load(doc.config_dir), change or {}, source, doc.config_dir)
        for table, records in document['tables'].items():
            rows, declared = content(table + 'Model')
            for rid, fields in records.items():
                for field, value in fields.items():
                    numeric = field not in pb.TEXT_FIELDS.get(table, set())
                    parsed = pb.adjustment(value) if numeric else ('set', None)
                    checked += 1
                    if parsed is None or parsed[0] != 'set':
                        continue
                    operand = value[1:].strip() if numeric and value.startswith('=') else value
                    if matches(operand, rows[rid][field], numeric):
                        block = edits.setdefault('playerBalance', {'databaseSha': database_sha})
                        block.setdefault('cells', []).append({'table': table, 'id': rid, 'column': field, 'value': ''})
                        cleared.append({'kind': 'player', 'table': table, 'id': rid, 'column': field})

    choices = [Path(doc.config_dir) / rel for rel in (enemy_armor.SHEET, enemy_armor.SHEET + '.disabled')]
    if sum(p.is_file() for p in choices) == 1:
        path = next(p for p in choices if p.is_file())
        _raw, header, authored = enemy_armor.read_sheet(path)
        pending = {(str(c['id']), c['column']): c for c in edits.get('enemyArmor', {}).get('cells', [])}
        rows, declared = content('ArmorModel')
        for row in authored:
            original = rows.get(row['ArmorId']) if not row.get('_clone') else None
            for field in header:
                if field not in declared or field == 'ArmorId':
                    continue
                cell = pending.get((row['ArmorId'], field))
                value = str(cell['value'] if cell is not None else row[field]).strip()
                if not value:
                    continue
                numeric = numeric_type(declared[field])
                if numeric:
                    n = number(value)
                    if 'INT' in declared[field].upper() and (n != n.to_integral_value() or not -(2 ** 63) <= n < 2 ** 63):
                        raise ValueError('Armor %s.%s requires a representable whole number.' % (row['ArmorId'], field))
                checked += 1
                if original is not None and matches(value, original[field], numeric):
                    if cell is None:
                        cell = {'id': row['ArmorId'], 'column': field, 'value': ''}
                        edits.setdefault('enemyArmor', {'databaseSha': database_sha}).setdefault('cells', []).append(cell)
                    cell['value'] = ''
                    cleared.append({'kind': 'enemyArmor', 'id': row['ArmorId'], 'column': field})
    source.assert_unchanged()
    notes = ['Official data declarations: checked %d populated override cell(s) for column types and finite numeric values.' % checked]
    if cleared:
        notes.append('Cleared %d override(s) identical to the shipped cell; Save writes these removals.' % len(cleared))
    return edits, cleared, notes
