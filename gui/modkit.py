"""Send saved player tuning through the guarded Workshop exporter to Modkit.

The standalone repository owns native talent mappings; player_balance owns
the additional SQL. This module checks inputs and commits verified sources.
It preflights SQL in a temporary directory, never installs a mod or submits a Workshop item.
"""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import player_balance


def preflight_parser(data, mod, parser_config):
    """Run the installed parser before a handoff; nothing is installed."""
    root = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
    script = root / 'scripts/prepare_enemy_difficulty.ps1'
    engine = Path(mod).parent.parent
    dll_name = 'CyberKnightsModkit_Data/Managed/DataParserNETStandard.dll'
    if not (engine / dll_name).is_file():
        engine = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader')
    if not (engine / dll_name).is_file() or not script.is_file() or not shutil.which('pwsh'):
        raise ValueError('Player export requires the installed Modkit parser and PowerShell 7 for validation.')
    inputs = {path: state(path) for path in (script, engine / dll_name, Path(parser_config))}
    with tempfile.TemporaryDirectory(prefix='ckf-player-parser-') as directory:
        directory = Path(directory)
        source = directory / 'source'
        source.mkdir()
        (source / 'stories.manifest').write_text('talent-balance.json\n', encoding='utf-8')
        (source / 'talent-balance.json').write_bytes(data)
        result = subprocess.run(['pwsh', '-NoProfile', '-File', str(script), '-SourceContent', str(source),
            '-OutputDirectory', str(directory / '_data'), '-ModkitDirectory', str(engine),
            '-SchemaPath', str(parser_config)], capture_output=True, text=True, timeout=180,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode:
            raise ValueError('Modkit parser rejected player balance; nothing was sent. ' +
                             (result.stderr or result.stdout)[-4000:].strip())
        if not (directory / '_data/data.sql').is_file() or not (directory / '_data/en-US.json').is_file():
            raise ValueError('Modkit parser produced an incomplete result; nothing was sent.')
    for path, expected in inputs.items():
        if state(path) != expected:
            raise ValueError('Parser input changed during validation: ' + str(path))
    return inputs


def state(path):
    path = Path(path)
    if not path.exists():
        return None
    before = path.stat()
    data = path.read_bytes()
    after = path.stat()
    if (before.st_mtime_ns, before.st_size) != (after.st_mtime_ns, after.st_size):
        raise ValueError('%s changed while being read' % path)
    return after.st_mtime_ns, len(data), hashlib.sha256(data).hexdigest()


def load_exporter(project):
    script = Path(project) / 'scripts' / 'export_talent_balance.py'
    spec = importlib.util.spec_from_file_location('ckf_talent_export', script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not callable(getattr(module, 'build_export', None)):
        raise ValueError('Update the talent repository: its exporter needs build_export().')
    if getattr(module, 'PARSER_CONTRACT_VERSION', 0) < 1:
        raise ValueError('Update the talent repository: its exporter needs official Modkit value-mapping validation.')
    return module


def source_commit(project):
    parent = Path(project).resolve().parent
    if not (parent / '.git').exists():
        return None  # Unavailable is not a guessed commit.
    try:
        result = subprocess.run(['git', '-C', str(parent), 'rev-parse', 'HEAD'],
                                capture_output=True, text=True, timeout=10,
                                creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def commit_files(outputs, expected, inputs):
    """Guard every replacement and verify its bytes; roll back a failed write.

    `expected` is captured before rendering. A destination or source modified
    during export refuses the handoff instead of silently overwriting it.
    """
    staged, written = [], []
    old = {}
    try:
        for path, data in outputs.items():
            if state(path) != expected[path]:
                raise ValueError('%s changed; send again after reviewing it' % path)
            old[path] = path.read_bytes() if expected[path] is not None else None
            if old[path] == data:
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, name = tempfile.mkstemp(prefix='.talent-export-', dir=path.parent)
            with os.fdopen(fd, 'wb') as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            staged.append((Path(name), path))
        for path, fingerprint in inputs.items():
            if state(path) != fingerprint:
                raise ValueError('%s changed during export; nothing was sent' % path)
        for path, fingerprint in expected.items():
            if state(path) != fingerprint:
                raise ValueError('%s changed during export; nothing was sent' % path)
        for stage, path in staged:
            if state(path) != expected[path]:
                raise ValueError('%s changed before replacement' % path)
            os.replace(stage, path)
            written.append(path)
            if path.read_bytes() != outputs[path]:
                raise OSError('%s failed read-back verification' % path)
        for path, data in outputs.items():
            if path.read_bytes() != data:
                raise OSError('%s changed before verification completed' % path)
        for path, fingerprint in inputs.items():
            if path not in outputs and state(path) != fingerprint:
                raise ValueError('%s changed before export completed' % path)
    except Exception as exc:
        rollback_errors = []
        for path in reversed(written):
            try:
                if path.read_bytes() != outputs[path]:
                    raise OSError('file changed; refusing to overwrite newer bytes')
                if old[path] is None:
                    path.unlink()
                else:
                    fd, name = tempfile.mkstemp(prefix='.talent-rollback-', dir=path.parent)
                    with os.fdopen(fd, 'wb') as f:
                        f.write(old[path])
                        f.flush()
                        os.fsync(f.fileno())
                    try:
                        os.replace(name, path)
                    finally:
                        if os.path.exists(name):
                            os.unlink(name)
                    if path.read_bytes() != old[path]:
                        raise OSError('rollback read-back failed')
            except Exception as rollback:
                rollback_errors.append('%s: %s' % (path, rollback))
        if rollback_errors:
            raise OSError('%s; incomplete rollback: %s' %
                          (exc, '; '.join(rollback_errors))) from exc
        raise
    finally:
        for stage, _path in staged:
            if stage.exists():
                stage.unlink()
    return [str(p) for p in written]


def send(config_dir, project_dir, mod_dir, database=None):
    project, mod = Path(project_dir).resolve(), Path(mod_dir).resolve()
    if not (mod.parent / (mod.name + '.workshop.json')).is_file():
        raise ValueError('Choose the mod folder beside its .workshop.json file.')
    if not (mod / 'upload_content').is_dir():
        raise ValueError('The selected folder is not an initialized Modkit project.')
    script = project / 'scripts' / 'export_talent_balance.py'
    script_state = state(script)
    exporter = load_exporter(project)
    if state(script) != script_state:
        raise ValueError('The exporter changed while being loaded; send again.')
    live = Path(config_dir).resolve() / 'ckf.hardmode.d'
    inputs = {live / filename: state(live / filename)
              for filename, _prefix, _key in exporter.expected_files()}
    cfg = live.parent / 'ckf.hardmode.cfg'
    inputs[cfg] = state(cfg)
    player_path = Path(config_dir) / player_balance.FILE
    inputs[player_path] = state(player_path)
    for name in ('fatigue.json', 'EffectModel.limitbreak.csv'):
        path = live / name
        inputs[path] = state(path)
    database_path = player_balance.static_data.database_path(database)
    inputs[database_path] = state(database_path)
    inputs[script] = script_state
    parser_config = mod.parent / 'config.json'
    inputs[parser_config] = state(parser_config)
    manifest = project / 'source_content' / 'stories.manifest'
    inputs[manifest] = state(manifest)
    manifest_bytes = manifest.read_bytes()
    entries = [line.strip() for line in manifest_bytes.decode('utf-8-sig').splitlines()
               if line.strip() and not line.lstrip().startswith('#')]
    if entries != ['talent-balance.json']:
        raise ValueError('The talent manifest must list only talent-balance.json.')
    destination_manifest = mod / 'source_data' / 'stories.manifest'
    if destination_manifest.exists() and destination_manifest.read_bytes() != manifest_bytes:
        raise ValueError('The Modkit manifest differs; review it before replacing it.')
    paths = [project / 'source_content' / 'talent-balance.json',
             project / 'provenance' / 'SOURCE.json', destination_manifest,
             mod / 'source_data' / 'talent-balance.json']
    expected = {p: state(p) for p in paths}
    if any(Path(config_dir).resolve() in p.resolve().parents for p in paths):
        raise ValueError('Export destinations must be outside the live config directory.')
    # Native-sheet-only exports need the same tree gate as Workshop tuning.
    if inputs[player_path] is None:
        import talent_tree
        with player_balance.static_data.StaticData(database) as source:
            talent_tree.validate(player_balance.empty(), source, config_dir)
    data, provenance, metadata = exporter.build_export(live, source_commit(project), parser_config=parser_config)
    if inputs[player_path] is not None:
        data, provenance, receipt = player_balance.augment(data, provenance, config_dir, database)
        metadata = receipt
    exporter.validate_parser_source(data, parser_config)
    player_balance.validate_native_updates(json.loads(data))
    if (inputs[parser_config] is None or state(parser_config) != inputs[parser_config]
            or inputs[parser_config][2] != metadata['parser_contract']['sha256']):
        raise ValueError('The official Modkit parser contract changed during export; nothing was sent.')
    # Check the exact bytes the exporter consumed, as well as their mtimes.
    for filename, info in metadata['overlay_inputs'].items():
        if inputs[live / filename][2] != info['sha256']:
            raise ValueError('%s moved before it could be exported' % filename)
    if inputs[cfg][2] != metadata['switch_file']['sha256']:
        raise ValueError('The talent switches changed during export.')
    for path, checked in preflight_parser(data, mod, parser_config).items():
        if path in inputs and inputs[path] != checked:
            raise ValueError('The parser contract changed during validation; nothing was sent.')
        inputs[path] = checked
    outputs = dict(zip(paths, [data, provenance, manifest_bytes, data]))
    written = commit_files(outputs, expected, inputs)
    return {'ok': True, 'records': metadata['parser_source']['records'],
            'counts': metadata['merged_update_records_by_table'],
            'sourceDir': str(mod / 'source_data'), 'written': written,
            'sha256': hashlib.sha256(data).hexdigest(),
            'next': 'In Modkit Uploader, click Prepare Mod Data, then Local Install Mod.'}
