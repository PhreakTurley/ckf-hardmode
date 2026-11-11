"""Prepare and independently verify native rebalance payloads for Hard Mode.

Maintainer-only inputs are the live tuning, player/roster exporter checkouts,
Official data.db, and the installed Mod Uploader parser. No save is opened.
Generated packages live only in the game's BepInEx/config directory.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'gui'), str(ROOT / 'scripts')]
from export_enemy_difficulty import build as enemy_build, guarded_write, encode
from verify_enemy_difficulty import verify as verify_enemy
import player_balance
import modkit as guarded_handoff


def prepare_enemy(config, database, modkit, uploader):
    """Prepare one verified enemy payload for both native distribution paths."""
    config, database, modkit, uploader = map(Path, (config, database, modkit, uploader))
    if not (uploader.parent / (uploader.name + '.workshop.json')).is_file() or not (uploader / 'upload_content').is_dir():
        raise ValueError('Choose an initialized Enemy Difficulty Modkit folder.')
    manifest = uploader / 'source_data/stories.manifest'
    if manifest.exists():
        entries = [line.strip() for line in manifest.read_text(encoding='utf-8-sig').splitlines()
                   if line.strip() and not line.lstrip().startswith('#')]
        if entries != ['enemy-difficulty.json']:
            raise ValueError('The selected Modkit manifest belongs to another mod.')
    project = ROOT / 'ckf-enemy-difficulty'
    artifact_names = ('source_content/stories.manifest', 'source_content/enemy-difficulty.json',
        'prepared/_data/data.sql', 'prepared/_data/en-US.json', 'review/SOURCE.json', 'review/column-ledger.csv')
    paths = [project / name for name in artifact_names]
    paths += [project / 'parser_prepared/_data' / name for name in ('data.sql', 'en-US.json')]
    paths += [project / 'review/parser-verification.json']
    bundled = config / 'ckf.hardmode.rebalances/enemy'
    paths += [bundled / '_data' / name for name in ('data.sql', 'en-US.json')]
    paths += [bundled / 'receipt.json', manifest, uploader / 'source_data/enemy-difficulty.json']
    paths += [uploader / 'upload_content/_data' / name for name in ('data.sql', 'en-US.json')]
    expected = {p: guarded_handoff.state(p) for p in paths}
    before = fingerprints(config)
    tool_paths = [modkit / 'CyberKnightsModkit_Data/StreamingAssets/config.json',
                 modkit / 'CyberKnightsModkit_Data/Managed/DataParserNETStandard.dll',
                 ROOT / 'scripts/prepare_enemy_difficulty.ps1', Path(__file__),
                 ROOT / 'scripts/export_enemy_difficulty.py', ROOT / 'scripts/verify_enemy_difficulty.py']
    inputs = {p: guarded_handoff.state(p) for p in tool_paths}
    artifacts, summary = enemy_build(database, config / 'ckf.hardmode.d', tool_paths[0])
    for name, digest_value in summary['source_inputs'].items():
        path = Path(name)
        info = guarded_handoff.state(path)
        if info is None or info[2] != digest_value:
            raise ValueError('Enemy input changed during preparation: ' + name)
        inputs[path] = info
    with tempfile.TemporaryDirectory(prefix='ckf-enemy-prepare-') as temporary:
        temporary = Path(temporary)
        source, output = temporary / 'source', temporary / '_data'
        source.mkdir()
        for relative, data in artifacts.items():
            if relative.startswith('source_content/'):
                (source / Path(relative).name).write_bytes(data)
        run = subprocess.run(['pwsh', '-NoProfile', '-File', str(tool_paths[2]),
            '-SourceContent', str(source), '-OutputDirectory', str(output), '-ModkitDirectory', str(modkit)],
            capture_output=True, text=True, timeout=300, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if run.returncode:
            raise ValueError('Enemy Data Parser refused preparation: ' + (run.stderr or run.stdout)[-4000:])
        report = verify_enemy(output / 'data.sql', database, config / 'ckf.hardmode.d')
        files = {name: (output / name).read_bytes() for name in ('data.sql', 'en-US.json')}
    player_sql = config / 'ckf.hardmode.rebalances/player/_data/data.sql'
    if not player_sql.is_file():
        raise ValueError('Prepare the player bundle before checking combined package compatibility.')
    inputs[player_sql] = guarded_handoff.state(player_sql)
    check_combination(database, {'player': player_sql.read_bytes(), 'enemy': files['data.sql']})
    receipt = {'format': 1, 'package': 'enemy', 'verification': report,
               'files': {name: digest(data) for name, data in files.items()}}
    outputs = {project / rel: data for rel, data in artifacts.items()}
    outputs[project / 'review/parser-verification.json'] = encode(report)
    for name, data in files.items():
        outputs[project / 'parser_prepared/_data' / name] = data
        outputs[bundled / '_data' / name] = data
        outputs[uploader / 'upload_content/_data' / name] = data
    outputs[bundled / 'receipt.json'] = encode(receipt)
    outputs[manifest] = artifacts['source_content/stories.manifest']
    outputs[uploader / 'source_data/enemy-difficulty.json'] = artifacts['source_content/enemy-difficulty.json']
    if fingerprints(config) != before:
        raise ValueError('Live tuning changed during preparation; nothing committed.')
    written = guarded_handoff.commit_files(outputs, expected, inputs)
    return {'ok': True, 'written': written, 'files': receipt['files'],
            'message': 'Prepared Hard Mode Enemy Rebalance and Enemy Difficulty. Restart the game for Hard Mode; use Local Install Mod for Workshop.'}


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    sys.modules[name] = value
    spec.loader.exec_module(value)
    return value


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fingerprints(config):
    paths = [config / 'ckf.hardmode.cfg', config / 'ckf.player-balance.json',
             config / 'ckf.enemy-difficulty.json']
    paths += sorted(p for p in (config / 'ckf.hardmode.d').iterdir() if p.is_file())
    return {str(p): (p.stat().st_mtime_ns, digest(p.read_bytes())) for p in paths}


def check_combination(database, sql_by_pack):
    """The two native packages must commute; report conflicting cells by identity."""
    source = sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)
    outcomes = []
    try:
        for order in (('player', 'enemy'), ('enemy', 'player')):
            memory = sqlite3.connect(':memory:')
            source.backup(memory)
            for pack in order:
                memory.executescript(sql_by_pack[pack].decode('utf-8-sig'))
            state = {}
            for table, in memory.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"):
                quoted = '"' + table.replace('"', '""') + '"'
                state[table] = sorted(memory.execute('SELECT * FROM ' + quoted).fetchall(), key=repr)
            outcomes.append(state)
            memory.close()
        if outcomes[0] != outcomes[1]:
            tables = [t for t in outcomes[0] if outcomes[0][t] != outcomes[1].get(t)]
            raise ValueError('Player and enemy packages disagree by application order: ' + ', '.join(tables))
    finally:
        source.close()


def build(config, database, player_project, modkit, check=False):
    before = fingerprints(config)
    talent = module('bundled_talent_export', player_project / 'scripts/export_talent_balance.py')
    verifier = module('bundled_player_verify', player_project / 'scripts/verify_player_balance.py')
    parser_config = modkit / 'WorkshopContent/config.json'
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
    native, provenance, _ = talent.build_export(config / 'ckf.hardmode.d', commit, parser_config=parser_config)
    native, provenance, _ = player_balance.augment(native, provenance, config, database)
    talent.validate_parser_source(native, parser_config)
    enemy, _ = enemy_build(database, config / 'ckf.hardmode.d',
        modkit / 'CyberKnightsModkit_Data/StreamingAssets/config.json')
    contents = {}
    reports = {}
    with tempfile.TemporaryDirectory(prefix='ckf-bundled-') as temp:
        temp = Path(temp)
        for pack in ('player', 'enemy'):
            source = temp / pack / 'source'
            source.mkdir(parents=True)
            if pack == 'player':
                (source / 'stories.manifest').write_text('talent-balance.json\n', encoding='utf-8')
                (source / 'talent-balance.json').write_bytes(native)
            else:
                for relative, data in enemy.items():
                    if relative.startswith('source_content/'):
                        (source / Path(relative).name).write_bytes(data)
            output = temp / pack / '_data'
            subprocess.run(['pwsh', '-NoProfile', '-File', str(ROOT / 'scripts/prepare_enemy_difficulty.ps1'),
                '-SourceContent', str(source), '-OutputDirectory', str(output),
                '-ModkitDirectory', str(modkit)], check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            if pack == 'player':
                reports[pack] = verifier.verify(output / 'data.sql', config, ROOT, database, parser_config)
            else:
                reports[pack] = verify_enemy(output / 'data.sql', database, config / 'ckf.hardmode.d')
            files = {name: (output / name).read_bytes() for name in ('data.sql', 'en-US.json')}
            receipt = {'format': 1, 'package': pack,
                'files': {name: digest(data) for name, data in files.items()},
                'verification': reports[pack]}
            contents.update({f'{pack}/_data/{name}': data for name, data in files.items()})
            contents[f'{pack}/receipt.json'] = encode(receipt)
        check_combination(database, {p: contents[f'{p}/_data/data.sql'] for p in ('player', 'enemy')})
    if fingerprints(config) != before:
        raise ValueError('Live tuning changed during preparation; nothing committed.')
    destination = config / 'ckf.hardmode.rebalances'
    # Capture every destination before the first replacement, not halfway through a batch.
    expected = {rel: ((destination / rel).stat().st_mtime_ns, digest((destination / rel).read_bytes()))
                if (destination / rel).exists() else None for rel in contents}
    for relative, data in contents.items():
        path = destination / relative
        if check:
            if not path.is_file() or path.read_bytes() != data:
                raise ValueError('Stale bundled payload: ' + str(path))
        else:
            # guarded_write checks mtime and bytes, stages a unique neighbor and hashes readback.
            if expected[relative] is None and path.exists():
                raise ValueError('Concurrent package creation: ' + str(path))
            guarded_write(path, data, expected[relative])
    print(json.dumps({'status': 'PASS', 'packages': reports, 'application_order': 'PASS',
                      'files': {rel: digest(data) for rel, data in contents.items()}}, indent=2))


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--data', type=Path, default=ROOT / 'Official/data.db')
    ap.add_argument('--player-project', type=Path, default=ROOT / 'ckf-talent-balance')
    ap.add_argument('--modkit', type=Path, default=Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader'))
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--enemy-only', action='store_true')
    ap.add_argument('--uploader-project', type=Path)
    args = ap.parse_args()
    if args.enemy_only:
        if args.check or args.uploader_project is None:
            ap.error('--enemy-only requires --uploader-project and does not accept --check')
        result = prepare_enemy(args.config, args.data, args.modkit, args.uploader_project)
        print('CKF_ENEMY_PREPARED ' + json.dumps(result))
    else:
        build(args.config, args.data, args.player_project, args.modkit, args.check)
