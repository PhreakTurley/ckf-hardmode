"""Standalone authoring for contact limit-break Rules 84, 85 and 86."""
import json
from pathlib import Path

import party_size
import rule_mod
import static_data

FILE = 'ckf.contact-limit-breaks.json'
RULES = ((84, 'minimum', 'Shortest Wait for Contact Limit Breaks'),
         (85, 'maximum', 'Longest Wait for Contact Limit Breaks'),
         (86, 'readyThreshold', 'Contact Ready Threshold'))
LEGACY_RULE_NAMES = {84: 'Minx Turns Between Contact Limit Breaks',
                     85: 'Max Turns between Contact Limit Breaks'}
encode = party_size.encode


def validate(document):
    if (not isinstance(document, dict) or set(document) != {'format', 'minimum', 'maximum', 'readyThreshold'}
            or type(document['format']) is not int or document['format'] != 1
            or any(type(document[key]) is not int or not 1 <= document[key] <= 2147483647
                   for key in ('minimum', 'maximum', 'readyThreshold'))
            or document['minimum'] > document['maximum']):
        raise ValueError('Contact limit breaks need positive integer turns and a positive integer ready-contact threshold, with minimum <= maximum.')
    return document


def load(config_dir, database=None):
    path = Path(config_dir) / FILE
    if not path.exists():
        return None
    document = json.loads(path.read_text(encoding='utf-8-sig'))
    if isinstance(document, dict) and set(document) == {'format', 'minimum', 'maximum'}:
        # Extend the earlier document in memory using the selected official
        # baseline. Reading never rewrites its bytes or guesses a default.
        document['readyThreshold'] = next(r['baseline'] for r in rules(database) if r['id'] == 86)
    return validate(document)


def rules(database=None):
    with static_data.StaticData(database) as source:
        required = {'RuleId', 'Value', 'ConfigName', 'ConfigDesc'}
        if not required <= {c[1] for c in source.schema.get('Rule', [])}:
            raise ValueError('Official Rule table is missing required columns.')
        rows = source.connection.execute(
            'SELECT RuleId, Value, ConfigName, ConfigDesc FROM Rule WHERE RuleId IN (84,85,86) ORDER BY RuleId'
        ).fetchall()
        if ([r[0] for r in rows] != [rid for rid, _, _ in RULES]
                or any(row[2] not in (name, LEGACY_RULE_NAMES.get(rid, name))
                       for row, (rid, _, name) in zip(rows, RULES))):
            raise ValueError('Official contact rules 84/85/86 are missing or renamed; review before exporting.')
        return [{'table': 'Rule', 'id': rid, 'field': field, 'name': name, 'description': description,
                 'baseline': int(static_data.integer_text(value, 'Rule[%d].Value' % rid))}
                for (rid, value, name, description), (_, field, _) in zip(rows, RULES)]


def model(config_dir, database=None, project=''):
    result = {'document': None, 'rules': [], 'projectDir': project, 'error': None}
    try:
        result['document'] = load(config_dir, database)
        result['rules'] = rules(database)
    except (OSError, ValueError) as exc:
        result['error'] = str(exc)
    return result


def source_bytes(document):
    validate(document)
    return encode({'Rule': [{'RuleId': rid, 'Value': document[field], 'SQL': 'update'}
                            for rid, field, _ in RULES]})


def send(config_dir, project_dir, database=None, expect=None):
    return rule_mod.send(config_dir, project_dir, database, expect,
                         title='Faster Contact Limit Breaks', filename=FILE,
                         source_name='contact-limit-breaks.json',
                         load_document=lambda config: load(config, database), lookup=rules, render=source_bytes)
