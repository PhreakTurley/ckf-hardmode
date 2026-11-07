"""Standalone Workshop authoring for Rule 83 only; never opens a save."""
import json
from pathlib import Path

import modkit
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
    """Copy only this mod's manifest/JSON, guarding inputs and destinations."""
    if not str(project_dir).strip():
        raise ValueError('Choose the initialized Party Size Mod folder.')
    project = Path(project_dir).resolve()
    config = Path(config_dir).resolve()
    if project == config or config in project.parents:
        raise ValueError('The Modkit project must be outside the live config directory.')
    metadata = project.parent / (project.name + '.workshop.json')
    if not metadata.is_file() or not (project / 'upload_content').is_dir():
        raise ValueError('Choose the initialized mod folder beside its .workshop.json.')
    tuning = config / FILE
    database_path = static_data.database_path(database)
    contract_path = project.parent / 'config.json'
    inputs = {p: modkit.state(p) for p in (tuning, database_path, contract_path, metadata)}
    if expect is not None:
        if expect.get(FILE) != (inputs[tuning][2] if inputs[tuning] else None):
            raise ValueError('Party Size Mod changed on disk; reload before sending.')
        if expect.get('@official-data.db') != (inputs[database_path][2] if inputs[database_path] else None):
            raise ValueError('Official data changed; reload before sending.')
    document = load(config)
    if document is None:
        raise ValueError('Save a Party Size Mod maximum before sending.')
    rule(database)
    contract = json.loads(contract_path.read_text(encoding='utf-8-sig'))
    fields = {f['name']: f for f in contract.get('Rule', {}).get('sql', {}).get('fields', [])}
    if (contract.get('Rule', {}).get('sql', {}).get('table') != 'Rule'
            or fields.get('RuleId', {}).get('type') != 'INTEGER'
            or not fields.get('RuleId', {}).get('primaryKey')
            or fields.get('Value', {}).get('type') != 'INTEGER'):
        raise ValueError('The installed parser no longer declares Rule.RuleId / Value as expected.')
    manifest = project / 'source_data' / 'stories.manifest'
    manifest_bytes = b'party-size.json\n'
    outputs = {manifest: manifest_bytes,
               project / 'source_data' / 'party-size.json': source_bytes(document)}
    expected = {p: modkit.state(p) for p in outputs}
    if expected[manifest] is not None:
        entries = [s.strip() for s in manifest.read_text(encoding='utf-8-sig').splitlines()
                   if s.strip() and not s.lstrip().startswith('#')]
        if entries != ['party-size.json']:
            raise ValueError('The selected project contains another mod manifest; choose a dedicated project.')
    written = modkit.commit_files(outputs, expected, inputs)
    return {'ok': True, 'written': written, 'sourceDir': str(manifest.parent),
            'next': 'In Modkit Uploader, select this mod and click Prepare Mod Data.'}
