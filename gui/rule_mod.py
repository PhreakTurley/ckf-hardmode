"""Guarded handoff for explicitly scoped standalone native Rule mods."""
import json
from pathlib import Path

import modkit
import static_data


def send(config_dir, project_dir, database=None, expect=None, *, title, filename, source_name, load_document, lookup, render):
    """Prepare and locally install this mod, guarding every destination together."""
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
    workshop, install_inputs = modkit.steam_workshop.local_install_target(project, modkit.state)
    inputs.update(install_inputs)
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
    payloads = modkit.payload_paths(project, workshop)
    expected = {p: modkit.state(p) for p in list(outputs) + payloads}
    if expected[manifest] is not None:
        entries = [s.strip() for s in manifest.read_text(encoding='utf-8-sig').splitlines()
                   if s.strip() and not s.lstrip().startswith('#')]
        if entries != [source_name]:
            raise ValueError('The selected project contains another mod manifest; choose a dedicated project.')
    files, parser_inputs = modkit.prepare_parser(outputs[project / 'source_data' / source_name],
                                                project, contract_path, source_name)
    for path, checked in parser_inputs.items():
        if path in inputs and inputs[path] != checked:
            raise ValueError('Parser input changed during preparation: ' + str(path))
        inputs[path] = checked
    outputs.update({path: files[path.name] for path in payloads})
    written = modkit.commit_files(outputs, expected, inputs)
    return {'ok': True, 'written': written, 'sourceDir': str(manifest.parent),
            'uploadDir': str(project / 'upload_content'), 'installedDir': str(workshop),
            'files': {name: modkit.hashlib.sha256(data).hexdigest() for name, data in files.items()},
            'next': 'Start or restart Cyber Knights to test. The Modkit payload is ready for Workshop submission.'}
