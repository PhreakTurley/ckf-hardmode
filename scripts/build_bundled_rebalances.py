"""Prepare and independently verify native rebalance payloads for Hard Mode.

Maintainer-only inputs are the live tuning, player/roster exporter checkouts,
Official data.db, and the installed Mod Uploader parser. No save is opened.
Generated packages live only in the game's BepInEx/config directory.
Installed packages can also be verified and staged without regenerating them.
"""
import argparse
from contextlib import closing
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
import make_release as release
from static_data import quote


def prepare_enemy(config, database, modkit, uploader):
    """Prepare one verified enemy payload for both native distribution paths."""
    config, database, modkit, uploader = map(Path, (config, database, modkit, uploader))
    if not (uploader.parent / (uploader.name + '.workshop.json')).is_file() or not (uploader / 'upload_content').is_dir():
        raise ValueError('Choose an initialized Enemy Difficulty Modkit folder.')
    workshop, install_inputs = guarded_handoff.steam_workshop.local_install_target(uploader, guarded_handoff.state)
    payloads = guarded_handoff.payload_paths(uploader, workshop)
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
    paths += payloads
    expected = {p: guarded_handoff.state(p) for p in paths}
    before = fingerprints(config)
    tool_paths = [modkit / 'CyberKnightsModkit_Data/StreamingAssets/config.json',
                 modkit / 'CyberKnightsModkit_Data/Managed/DataParserNETStandard.dll',
                 ROOT / 'scripts/prepare_enemy_difficulty.ps1', Path(__file__),
                 ROOT / 'scripts/export_enemy_difficulty.py', ROOT / 'scripts/verify_enemy_difficulty.py']
    inputs = {p: guarded_handoff.state(p) for p in tool_paths}
    inputs.update(install_inputs)
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
        outputs[workshop / '_data' / name] = data
    outputs[bundled / 'receipt.json'] = encode(receipt)
    outputs[manifest] = artifacts['source_content/stories.manifest']
    outputs[uploader / 'source_data/enemy-difficulty.json'] = artifacts['source_content/enemy-difficulty.json']
    if fingerprints(config) != before:
        raise ValueError('Live tuning changed during preparation; nothing committed.')
    written = guarded_handoff.commit_files(outputs, expected, inputs)
    return {'ok': True, 'written': written, 'files': receipt['files'],
            'uploadDir': str(uploader / 'upload_content'), 'installedDir': str(workshop),
            'message': 'Prepared and locally installed Enemy Difficulty. Start or restart Cyber Knights to test; the Modkit payload is ready for Workshop submission.'}


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


PACKS = (('player', '3814427009'), ('hire', '3841540859'), ('enemy', '3829942905'))
FILES = ('data.sql', 'en-US.json')
BUNDLE_DIR = 'ckf.hardmode.rebalances'


def input_paths(config, workshop):
    tuning = [rel for rel in release.CONFIG_FILES if not rel.startswith(BUNDLE_DIR + '/')]
    tuning.append(release.CFG_NAME)
    tuning.extend(
        p.relative_to(config).as_posix()
        for p in (config / release.OVERLAY_DIR).iterdir()
        if p.is_file() and p.name.lower().endswith(release.OVERLAY_EXTS)
    )
    paths = {rel: config / rel for rel in tuning}
    for pack, item in PACKS:
        for name in FILES:
            paths[f'{BUNDLE_DIR}/{pack}/_data/{name}'] = workshop / item / '_data' / name
    return paths


def verify_combined(database, payloads):
    locales = {}
    for pack, _item in PACKS:
        for key, value in json.loads(payloads[pack]['en-US.json']).items():
            if key in locales and locales[key] != value:
                raise ValueError(f'Conflicting native locale entry: {key}')
            locales[key] = value
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(':memory:')) as memory:
            source.backup(memory)
            tables = [row[0] for row in memory.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
            ordered_sql = [payloads[pack]['data.sql'].decode('utf-8-sig') for pack, _item in PACKS]
            for sql in ordered_sql:
                memory.executescript(sql)
            before = {table: memory.execute('SELECT * FROM ' + quote(table)).fetchall()
                      for table in tables}
            for sql in ordered_sql:
                memory.executescript(sql)
            for table, rows in before.items():
                if memory.execute('SELECT * FROM ' + quote(table)).fetchall() != rows:
                    raise ValueError(f'Combined payload changes {table} on repeat application')


def stage_installed(config, workshop, output, database, player_project, modkit):
    import build_hire_everyone as hire

    if output.exists():
        raise ValueError(f'Choose a new release staging directory: {output}')
    output.parent.mkdir(parents=True, exist_ok=True)
    journal = config / release._serve().JOURNAL_NAME
    hire_config = config / hire.FILE
    if journal.exists():
        raise ValueError(f'Finish the editor save before staging: {journal}')
    inputs = input_paths(config, workshop)
    before = {path: guarded_handoff.state(path)
              for path in (*inputs.values(), hire_config, database)}
    with tempfile.TemporaryDirectory(prefix='installed-release-', dir=output.parent) as temporary:
        snapshot = Path(temporary) / 'config'
        for relative, path in inputs.items():
            target = snapshot / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            data = path.read_bytes()
            if digest(data) != before[path][2]:
                raise ValueError(f'Input changed while copying: {path}')
            target.write_bytes(data)

        native = snapshot / BUNDLE_DIR
        payloads = {pack: {name: (native / pack / '_data' / name).read_bytes() for name in FILES}
                    for pack, _item in PACKS}
        verify_player = module('installed_player_verify',
            player_project / 'scripts/verify_player_balance.py').verify
        parser_config = modkit / 'WorkshopContent/config.json'
        document = hire.load(config)
        source, expected, _summary = hire.build(database, document)
        reports = {
            'player': verify_player(native / 'player/_data/data.sql', snapshot, ROOT, database, parser_config),
            'hire': hire.verify(database, payloads['hire']['data.sql'], payloads['hire']['en-US.json'],
                                expected, source['RawText']['Generic'], document),
            'enemy': verify_enemy(native / 'enemy/_data/data.sql', database,
                                  snapshot / release.OVERLAY_DIR),
        }
        check_combination(database, {pack: payloads[pack]['data.sql'] for pack in ('player', 'enemy')})
        verify_combined(database, payloads)
        if journal.exists() or inputs != input_paths(config, workshop) or any(
                guarded_handoff.state(path) != state for path, state in before.items()):
            raise ValueError('Release inputs changed during verification')
        for pack, item in PACKS:
            receipt = {'format': 1, 'package': pack, 'workshopItem': item,
                       'files': {name: digest(data) for name, data in payloads[pack].items()},
                       'verification': reports[pack]}
            (native / pack / 'receipt.json').write_bytes(encode(receipt))
            print(f'{pack}: {receipt["files"]}')
        release.check_bundled_payloads(snapshot)
        snapshot.rename(output)
    print(f'Installed payloads verified in player, hire, enemy order and staged at {output}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--config', type=Path, required=True)
    ap.add_argument('--data', type=Path, default=ROOT / 'Official/data.db')
    ap.add_argument('--player-project', type=Path, default=ROOT / 'ckf-talent-balance')
    ap.add_argument('--modkit', type=Path, default=Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader'))
    ap.add_argument('--check', action='store_true')
    ap.add_argument('--enemy-only', action='store_true')
    ap.add_argument('--uploader-project', type=Path)
    ap.add_argument('--capture-installed', type=Path, metavar='WORKSHOP_DIR',
                    help='stage the exact installed Workshop payloads instead of rebuilding them')
    ap.add_argument('--out', type=Path, help='new config staging directory for --capture-installed')
    args = ap.parse_args()
    if args.capture_installed is not None:
        if args.out is None or args.enemy_only or args.check or args.uploader_project is not None:
            ap.error('--capture-installed requires --out and cannot use --enemy-only, --check or --uploader-project')
        stage_installed(args.config.resolve(), args.capture_installed.resolve(),
                        args.out.resolve(), args.data.resolve(), args.player_project, args.modkit)
    elif args.out is not None:
        ap.error('--out requires --capture-installed')
    elif args.enemy_only:
        if args.check or args.uploader_project is None:
            ap.error('--enemy-only requires --uploader-project and does not accept --check')
        result = prepare_enemy(args.config, args.data, args.modkit, args.uploader_project)
        print('CKF_ENEMY_PREPARED ' + json.dumps(result))
    else:
        build(args.config, args.data, args.player_project, args.modkit, args.check)
