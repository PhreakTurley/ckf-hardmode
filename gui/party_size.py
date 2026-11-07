"""Standalone Workshop authoring for Rule 83 only; never opens a save."""
import json
from pathlib import Path

import rule_mod
import static_data

FILE = 'ckf.party-size.json'
RULE_ID = 83
RULE_NAME = 'Mission Max MercDefault'


def encode(document):
    return (json.dumps(document, indent=2) + '\n').encode('utf-8')


def validate(document):
    if (not isinstance(document, dict) or set(document) != {'format', 'maximum'}
            or type(document['format']) is not int or document['format'] != 1
            or type(document['maximum']) is not int or not 1 <= document['maximum'] <= 2147483647):
        raise ValueError('Party Size Mod needs format 1 and a positive integer maximum.')
    return document


def load(config_dir):
    path = Path(config_dir) / FILE
    if not path.exists():
        return None
    return validate(json.loads(path.read_text(encoding='utf-8-sig')))


def rule(database=None):
    # Deliberately select the one declared identity, never a catalog of rules.
    with static_data.StaticData(database) as source:
        required = {'RuleId', 'Value', 'ConfigName', 'ConfigDesc'}
        if not required <= {c[1] for c in source.schema.get('Rule', [])}:
            raise ValueError('Official Rule table is missing required columns.')
        rows = source.connection.execute(
            'SELECT RuleId, Value, ConfigName, ConfigDesc FROM Rule WHERE RuleId = ?',
            (RULE_ID,)).fetchall()
        if len(rows) != 1 or rows[0][2] != RULE_NAME:
            raise ValueError('Official Rule 83 is missing or renamed; review before exporting.')
        rid, value, name, description = rows[0]
        return {'table': 'Rule', 'id': rid, 'name': name, 'description': description,
                'baseline': int(static_data.integer_text(value, 'Rule[83].Value'))}


def model(config_dir, database=None, project=''):
    result = {'document': None, 'rule': None, 'projectDir': project, 'error': None}
    try:
        result['document'] = load(config_dir)
        result['rule'] = rule(database)
    except (OSError, ValueError) as exc:
        result['error'] = str(exc)
    return result


def source_bytes(document):
    validate(document)
    return encode({'Rule': [{'RuleId': RULE_ID, 'Value': document['maximum'], 'SQL': 'update'}]})


def send(config_dir, project_dir, database=None, expect=None):
    return rule_mod.send(config_dir, project_dir, database, expect,
                         title='Party Size Mod', filename=FILE, source_name='party-size.json',
                         load_document=load, lookup=rule, render=source_bytes)
