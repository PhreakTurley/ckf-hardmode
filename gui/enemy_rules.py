"""Authoritative Enemy Balance rule assignments, separate from Player Balance."""
import copy
import json
from pathlib import Path
import re

import player_balance as pb
import static_data

FILE = 'ckf.enemy-difficulty.json'


def assignment(value):
    text = str(value).strip()
    if not re.fullmatch(r'-?\d+', text) or not -(2 ** 63) <= int(text) < 2 ** 63:
        raise ValueError('Rule 82.Value requires a representable whole number.')
    return int(text)


def load(config):
    document = json.loads((Path(config) / FILE).read_bytes())
    if document.get('format') != 1 or set(document) - {'format', 'basis', 'updates', 'clones', 'rules'}:
        raise ValueError('Unsupported enemy authoring document.')
    rules = document.get('rules', {})
    if not isinstance(rules, dict) or set(rules) - {'82'}:
        raise ValueError('Enemy Balance owns only Rule 82.Value.')
    for fields in rules.values():
        if not isinstance(fields, dict) or set(fields) != {'Value'} or type(fields['Value']) is not int:
            raise ValueError('Enemy Balance rules require integer Value assignments.')
        assignment(fields['Value'])
    return document


def baseline(source):
    declared = {r[1]: r[2] for r in source.schema['Rule']}
    if 'INT' not in declared.get('Value', '').upper():
        raise ValueError('Official Rule.Value no longer declares INTEGER storage.')
    row = next(r for r in source.read('RuleModel')[1] if r['RuleId'] == '82')
    if row['ConfigName'] != 'Max Enemy Power Level':
        raise ValueError('Rule 82 declaration changed.')
    return assignment(row['Value'])


def pending(config, source, change):
    document = copy.deepcopy(load(config))
    stock = baseline(source)
    if change and change.get('databaseSha') != pb.identity(source)['sha256']:
        raise ValueError('Official data changed; reload before editing enemy rules.')
    rules = document.setdefault('rules', {})
    seen = set()
    for cell in (change or {}).get('cells', []):
        key = (str(cell.get('id')), cell.get('column'))
        if key != ('82', 'Value') or key in seen:
            raise ValueError('Enemy Balance owns only one Rule 82.Value assignment.')
        seen.add(key)
        text = str(cell['value']).strip()
        if text:
            rules['82'] = {'Value': assignment(text)}
        else:
            rules.pop('82', None)
    redundant = '82' in rules and rules['82']['Value'] == stock
    if redundant:
        rules.pop('82')
    if not rules:
        document.pop('rules', None)
    source.assert_unchanged()
    return document, redundant


def model(config, database):
    result = {'error': None, 'values': {'82': {'Value': ''}}}
    if database is False:
        return result
    try:
        with static_data.StaticData(database) as source:
            baseline(source)
            document = load(config)
            result['database'] = pb.identity(source)
            if '82' in document.get('rules', {}):
                result['values']['82']['Value'] = str(document['rules']['82']['Value'])
    except (ValueError, OSError, static_data.DataError, KeyError, StopIteration) as exc:
        result['error'] = str(exc)
    return result


def decorate(pages):
    for page in pages:
        if page['id'] != 'enemy-balance-rules':
            continue
        page.update(enemyRules=True, ownershipReference=False)
        for grid in page['grids']:
            for row in grid['rows']:
                row['targets'] = {c['name']: {'table': 'Rule', 'id': row['id'], 'column': c['name'],
                    **({'enemyRule': True} if c['name'] == 'Value' else {'readOnly': True})}
                    for c in grid['columns'] + grid.get('advanced', [])}
