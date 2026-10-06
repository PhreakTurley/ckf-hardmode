"""Send saved talent tuning through the standalone exporter to Modkit.

The standalone talent repository owns all field mappings. This module only
loads its exporter, checks the inputs, and commits verified source files.
It never prepares SQL, installs a mod, or submits a Workshop item.
"""

import hashlib
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile


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
            if state(path) != fingerprint:
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


def send(config_dir, project_dir, mod_dir):
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
    inputs[script] = script_state
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
    data, provenance, metadata = exporter.build_export(live, source_commit(project))
    # Check the exact bytes the exporter consumed, as well as their mtimes.
    for filename, info in metadata['overlay_inputs'].items():
        if inputs[live / filename][2] != info['sha256']:
            raise ValueError('%s moved before it could be exported' % filename)
    if inputs[cfg][2] != metadata['switch_file']['sha256']:
        raise ValueError('The talent switches changed during export.')
    outputs = dict(zip(paths, [data, provenance, manifest_bytes, data]))
    written = commit_files(outputs, expected, inputs)
    return {'ok': True, 'records': metadata['parser_source']['records'],
            'counts': metadata['merged_update_records_by_table'],
            'sourceDir': str(mod / 'source_data'), 'written': written,
            'sha256': hashlib.sha256(data).hexdigest(),
            'next': 'In Modkit Uploader, click Prepare Mod Data, then Local Install Mod.'}
