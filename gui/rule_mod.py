"""Guarded handoff for explicitly scoped standalone native Rule mods."""
import json
from pathlib import Path

import modkit
import static_data


def send(config_dir, project_dir, database=None, expect=None, *, title, filename, source_name, load_document, lookup, render):
    """Copy only this mod's manifest/JSON, guarding inputs and destinations."""
    if not str(project_dir).strip():
        raise ValueError('Choose the initialized %s folder.' % title)
    project = Path(project_dir).resolve()
    config = Path(config_dir).resolve()
    if project == config or config in project.parents:
        raise ValueError('The Modkit project must be outside the live config directory.')
    metadata = project.parent / (project.name + '.workshop.json')
    if not metadata.is_file() or not (project / 'upload_content').is_dir():
        raise ValueError('Choose the initialized mod folder beside its .workshop.json.')
    tuning = config / filename
    database_path = static_data.database_path(database)
    contract_path = project.parent / 'config.json'
    inputs = {p: modkit.state(p) for p in (tuning, database_path, contract_path, metadata)}
    if expect is not None:
        if expect.get(filename) != (inputs[tuning][2] if inputs[tuning] else None):
            raise ValueError('%s changed on disk; reload before sending.' % title)
        if expect.get('@official-data.db') != (inputs[database_path][2] if inputs[database_path] else None):
            raise ValueError('Official data changed; reload before sending.')
    document = load_document(config)
    if document is None:
        raise ValueError('Save %s settings before sending.' % title)
    lookup(database)
    contract = json.loads(contract_path.read_text(encoding='utf-8-sig'))
    fields = {f['name']: f for f in contract.get('Rule', {}).get('sql', {}).get('fields', [])}
    if (contract.get('Rule', {}).get('sql', {}).get('table') != 'Rule'
            or fields.get('RuleId', {}).get('type') != 'INTEGER'
            or not fields.get('RuleId', {}).get('primaryKey')
            or fields.get('Value', {}).get('type') != 'INTEGER'):
        raise ValueError('The installed parser no longer declares Rule.RuleId / Value as expected.')
    manifest = project / 'source_data' / 'stories.manifest'
    manifest_bytes = (source_name + '\n').encode('utf-8')
    outputs = {manifest: manifest_bytes,
               project / 'source_data' / source_name: render(document)}
    expected = {p: modkit.state(p) for p in outputs}
    if expected[manifest] is not None:
        entries = [s.strip() for s in manifest.read_text(encoding='utf-8-sig').splitlines()
                   if s.strip() and not s.lstrip().startswith('#')]
        if entries != [source_name]:
            raise ValueError('The selected project contains another mod manifest; choose a dedicated project.')
    written = modkit.commit_files(outputs, expected, inputs)
    return {'ok': True, 'written': written, 'sourceDir': str(manifest.parent),
            'next': 'In Modkit Uploader, select this mod and click Prepare Mod Data.'}
