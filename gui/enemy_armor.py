"""Enemy armor views and edits over the shared native armor authoring sheet."""
import csv
import io
import json
import math
from pathlib import Path
import shutil
import subprocess

import player_balance as pb
import static_data

SHEET = 'ckf.hardmode.d/ArmorModel.csv'
MONSTERS = 'ckf.hardmode.d/MonsterTypeModel.csv'
CORE_COLUMNS = ('PowerLevel', 'BallisticArmor', 'PhysicalArmor', 'BallisticArmorDegraded',
                'PhysicalArmorDegraded', 'MaxArmorPoints', 'InitPenalty', 'MovementRate', 'CarryCapacity')


def sheet_path(config, relative):
    choices = [p for p in (Path(config) / relative, Path(config) / (relative + '.disabled')) if p.is_file()]
    if len(choices) != 1:
        raise ValueError('Expected one active or parked armor authoring source: ' + relative)
    return choices[0]


def read_sheet(path):
    raw = path.read_bytes()
    reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig'), newline=''))
    header = list(reader.fieldnames or [])
    rows = []
    for line, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise ValueError('Armor row %d does not match the header width' % line)
        if any(value.strip() for value in row.values()):
            rows.append(row)
    if not header or header[0] != 'ArmorId':
        raise ValueError('Armor sheet must start with ArmorId')
    if len(header) != len(set(header)) or len({r['ArmorId'] for r in rows}) != len(rows):
        raise ValueError('Armor sheet contains duplicate columns or ids')
    return raw, header, rows


def fingerprints(config):
    return [str(p.relative_to(config)).replace('\\', '/')
            for relative in (SHEET, MONSTERS) for p in (Path(config) / relative, Path(config) / (relative + '.disabled'))]


def player_references(source, armors):
    """Positive service, loot and player-pet references; never an id-only join.

    ContactService flow 2 is the armor catalog. LootTypes.Armor=12 is declared
    by the captured Constants metadata in _id_constants.csv. This is an
    inclusive catalog policy, not a campaign availability calculation.
    """
    refs = {}
    def add(rid, why):
        if rid in armors:
            refs.setdefault(rid, []).append(why)
    services = [r for r in pb.contact_services(source) if r['ServiceFlow'] == '2'
                and r['attainable'] and int(r['ServiceOptionId']) > 0]
    for rid, armor in armors.items():
        for service in services:
            if armor['ServiceOptionId'] == service['ServiceOptionId']:
                add(rid, 'ContactService ' + service['ServiceTypeId'] + ' (armor service)')
    for row in source.read('MissionLootModel')[1]:
        if row['LootTypeId'] == '12':
            add(row['LootKey'], 'MissionLoot ' + row['MissionLootId'])
    for row in source.read('DronePrebuiltModel')[1]:
        add(row['Armor'], 'PetPrebuilt ' + row['DroneType'] + '.Armor')
    return refs


def model(config, database, settings):
    result = {'error': None, 'page': None, 'values': {},
              'sourceDir': settings.get('enemySourceDir', ''),
              'modkitDir': settings.get('enemyModkitProjectDir', '')}
    if database is False:
        return result
    try:
        with static_data.StaticData(database) as source:
            result['database'] = pb.identity(source)
            path = sheet_path(config, SHEET)
            _, header, authored = read_sheet(path)
            declared = pb.declarations(source, 'Armor')
            unknown = set(c for c in header if not c.startswith('_')) - set(declared) - {'ArmorId'}
            if unknown:
                raise ValueError('Undeclared armor fields: ' + ', '.join(sorted(unknown)))
            stock = {r['ArmorId']: r for r in source.read('ArmorModel')[1]}
            effective = {rid: dict(r) for rid, r in stock.items()}
            for row in authored:
                if not row.get('_clone', '').strip():
                    if row['ArmorId'] not in stock:
                        raise ValueError('Armor update has no shipped row: ' + row['ArmorId'])
                    effective[row['ArmorId']].update({k: v for k, v in row.items() if k in declared and v.strip()})
            clones = {}
            for row in authored:
                donor = row.get('_clone', '').strip()
                if donor:
                    if donor not in stock or row['ArmorId'] in effective:
                        raise ValueError('Invalid armor clone: ' + row['ArmorId'] + ' from ' + donor)
                    clones[row['ArmorId']] = donor
                    effective[row['ArmorId']] = {**effective[donor], 'ArmorId': row['ArmorId'],
                        **{k: v for k, v in row.items() if k in declared and v.strip()}}
            monsters = {r['MonsterTypeId']: r for r in source.read('MonsterTypeModel')[1]}
            enemy_ids = {r['ArmorTypeId'] for r in monsters.values()}
            monster_path = sheet_path(config, MONSTERS)
            for row in csv.DictReader(io.StringIO(monster_path.read_text(encoding='utf-8-sig'))):
                if row.get('ArmorTypeId', '').strip():
                    enemy_ids.add(row['ArmorTypeId'].strip())
            enemy_ids.update(r['ArmorId'] for r in authored)
            refs = player_references(source, stock)
            by_id = {r['ArmorId']: r for r in authored}
            columns = []
            for name in dict.fromkeys(CORE_COLUMNS + tuple(declared)):
                columns.append({'name': name, 'label': pb.label(name), 'order': len(columns),
                    'metadata': name not in CORE_COLUMNS, 'integer': 'INT' in declared[name].upper(),
                    'visibilityPolicy': 'nonzero'})
            records = []
            for rid in sorted(enemy_ids & effective.keys(), key=int):
                donor = clones.get(rid)
                baseline = effective[donor] if donor else stock[rid]
                fields = {k: by_id.get(rid, {}).get(k, '').strip() for k in declared}
                result['values'][rid] = fields
                records.append({'id': rid, 'name': stock[donor or rid]['ArmorName'], 'baseline': baseline,
                    'cloneOf': donor, 'origin': 'Clone' if donor else 'Shipped',
                    'playerUse': bool(refs.get(rid)), 'acquisition': refs.get(rid, []),
                    'targets': {name: {'table': 'Armor', 'id': rid, 'column': name, 'enemyArmor': True}
                                for name in declared}})
            records.sort(key=lambda r: (r['name'].casefold(), int(r['baseline']['PowerLevel']), bool(r['cloneOf']), int(r['id'])))
            result['page'] = {'id': 'enemy-armors', 'title': 'Enemy Armors', 'group': 'Enemy Gear', 'enemyArmor': True,
                'grids': [{'key': 'enemy-armors', 'table': 'Armor', 'title': 'Enemy Armors',
                           'columns': columns, 'advanced': [], 'rows': records, 'dynamicColumns': True,
                           'scrollWithPage': True, 'unpaginated': True}]}
            result['path'] = str(path.relative_to(config)).replace('\\', '/')
            result['unresolvedShipped'] = sorted(enemy_ids - effective.keys() - {'0', '-1', ''}, key=int)
    except (ValueError, OSError, static_data.DataError) as exc:
        result['error'] = str(exc)
    return result


def apply_edits(config, database, cells):
    if not cells:
        return {}
    view = model(config, database, {})
    if view['error']:
        raise ValueError(view['error'])
    path = sheet_path(config, SHEET)
    raw, header, rows = read_sheet(path)
    by_id = {r['ArmorId']: r for r in rows}
    changed = False
    for cell in cells:
        rid, column, value = str(cell['id']), cell['column'], str(cell.get('value', '')).strip()
        if rid not in view['values'] or column not in view['values'][rid]:
            raise ValueError('Not an editable enemy armor cell: %s.%s' % (rid, column))
        if value:
            try:
                number = float(value)
            except ValueError:
                raise ValueError('Armor values must be numbers; clear a cell to inherit: ' + value)
            if not math.isfinite(number) or number != int(number):
                raise ValueError('Armor values must be finite integers: ' + value)
        row = by_id.get(rid)
        if row is None:
            row = {'ArmorId': rid}
            by_id[rid] = row
            rows.append(row)
        if row.get(column, '') == value:
            continue
        if column not in header:
            header.append(column)
        row[column] = value
        changed = True
    if not changed:
        return {}
    out = io.StringIO(newline='')
    writer = csv.DictWriter(out, header, lineterminator='\r\n' if b'\r\n' in raw else '\n')
    writer.writeheader()
    writer.writerows(rows)
    data = (b'\xef\xbb\xbf' if raw.startswith(b'\xef\xbb\xbf') else b'') + out.getvalue().encode('utf-8')
    return {str(path.relative_to(config)).replace('\\', '/'): data}


def prepare(config, database, source_dir, uploader):
    root, destination = Path(source_dir).resolve(), Path(uploader).resolve()
    script = root / 'scripts/build_bundled_rebalances.py'
    if not script.is_file():
        raise ValueError('Choose the Hard Mode source checkout containing the rebalance builder.')
    python = shutil.which('python')
    if not python:
        raise ValueError('Python is required to prepare native packages on the maintainer machine.')
    run = subprocess.run([python, str(script), '--enemy-only', '--config', str(config),
        '--data', str(database), '--uploader-project', str(destination)], cwd=root,
        capture_output=True, text=True, timeout=600, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if run.returncode:
        raise ValueError((run.stderr or run.stdout)[-4000:].strip())
    lines = [line for line in run.stdout.splitlines() if line.startswith('CKF_ENEMY_PREPARED ')]
    if len(lines) != 1:
        raise ValueError('Preparation did not return a complete result.')
    return json.loads(lines[0].split(' ', 1)[1])
