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
    args = ap.parse_args()
    build(args.config, args.data, args.player_project, args.modkit, args.check)
