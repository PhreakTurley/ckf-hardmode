"""Workshop ownership, SQL parity, and live catalog regression checks."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import os

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import player_balance as pb
import static_data


class PlayerBalanceTests(unittest.TestCase):
    def test_rounding_matches_integer_model_writes(self):
        db = sqlite3.connect(':memory:')
        for value in (-5.5, -4.5, -3.5, -2.5, -1.5, -.5, .5, 1.5, 2.5, 3.5, 4.5, 5.5, 2.49, 2.51):
            self.assertEqual(db.execute('SELECT ' + pb.rounded(str(value))).fetchone()[0], round(value), value)
        db.close()

    def test_legacy_transfer_matches_all_rows_and_future_sweep(self):
        config = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config')
        legacy = pb.load(config) if (config / pb.FILE).exists() else pb.import_legacy(config)
        with static_data.StaticData() as source:
            statements, touched = pb.sql(legacy, source)
            db = sqlite3.connect(':memory:')
            source.connection.backup(db)
            # Preserve an independent model view before executing generated SQL.
            before = {t: {r[pb.TABLE_KEYS[t]]: r for r in source.read(t + 'Model')[1]}
                      for t in legacy['tables']}
            all_implants = source.read('ImplantModel')[1]
            for statement in statements:
                db.execute(statement)
            for table, rid, col in touched:
                value = float(before[table][rid][col])
                op, number = pb.adjustment(legacy['tables'][table][rid][col])
                expected = round(number if op == 'set' else value + number if op == 'add' else value * number)
                if table == 'Implant' and col in pb.MULTIPLIERS:
                    expected = round(expected * legacy['implantMultipliers'][col])
                actual = db.execute('SELECT "%s" FROM "%s" WHERE "%s"=?' %
                                    (col, table, pb.TABLE_KEYS[table]), (rid,)).fetchone()[0]
                self.assertEqual(actual, expected, (table, rid, col))
            for row in all_implants:
                rid = row['ImplantTypeId']
                expected = round(float(row['Cost']) * legacy['implantMultipliers']['Cost'])
                self.assertEqual(db.execute('SELECT Cost FROM Implant WHERE ImplantTypeId=?', (rid,)).fetchone()[0], expected)
            self.assertNotIn(('Rule', '23', 'Value'), touched)
            self.assertFalse(any(t == 'Effect' and int(i) in pb.HARDMODE_EFFECTS for t, i, c in touched))
            # A row absent during export is still reached by the global UPDATE.
            db.execute('UPDATE Implant SET ImplantTypeId=999999, Cost=5.1 WHERE ImplantTypeId=(SELECT MIN(ImplantTypeId) FROM Implant)')
            db.execute(statements[-1])
            self.assertEqual(db.execute('SELECT Cost FROM Implant WHERE ImplantTypeId=999999').fetchone()[0], 2)
            db.close()

    def test_shared_effect_and_hardmode_ownership(self):
        with static_data.StaticData() as source:
            doc = pb.apply_edits(pb.empty(), {'cells': [{'table': 'Effect', 'id': '50007', 'column': 'CritMultiBase', 'value': '=0'}]}, source)
            self.assertEqual(doc['tables']['Effect'], {'50007': {'CritMultiBase': '=0'}})
            for effect in pb.HARDMODE_EFFECTS:
                with self.assertRaisesRegex(ValueError, 'Hard Mode'):
                    pb.apply_edits(doc, {'cells': [{'table': 'Effect', 'id': str(effect), 'column': 'XpBonus', 'value': '0'}]}, source)
            with self.assertRaisesRegex(ValueError, 'Only the surprised'):
                pb.apply_edits(doc, {'cells': [{'table': 'Rule', 'id': '23', 'column': 'Value', 'value': '4'}]}, source)

    def test_database_replacement_adds_rows_columns_and_preserves_overrides(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            database = root / 'data.db'
            with static_data.StaticData() as source:
                target = sqlite3.connect(database)
                source.connection.backup(target)
                target.close()
            (root / pb.FILE).write_bytes(pb.encode({'format': 1, 'implantMultipliers': dict.fromkeys(pb.MULTIPLIERS, 1),
                                                    'tables': {'Weapon': {'24000': {'CritMultiBase': '=0'}}}}))
            before = pb.catalog(root, database)
            self.assertIsNone(before['error'])
            db = sqlite3.connect(database)
            db.execute('ALTER TABLE Weapon ADD COLUMN NewCombatField INTEGER DEFAULT 0')
            db.execute('UPDATE Weapon SET NewCombatField=7 WHERE WeaponId=24000')
            db.execute('INSERT INTO Weapon (WeaponId, WeaponClass, Cost) VALUES (999999, 16, 17)')
            db.commit(); db.close()
            after = pb.catalog(root, database)
            self.assertIsNone(after['error'])
            self.assertNotEqual(before['database']['sha256'], after['database']['sha256'])
            claws = next(p for p in after['pages'] if p['id'] == 'weapon-16')['grids'][0]
            self.assertIn('999999', [r['id'] for r in claws['rows']])
            self.assertIn('NewCombatField', [c['name'] for c in claws['columns']])
            self.assertEqual(after['document']['tables']['Weapon']['24000']['CritMultiBase'], '=0')
            # An explicit zero override stays visible even when baselines agree.
            self.assertIn('CritMultiBase', [c['name'] for c in claws['columns']])
            db = sqlite3.connect(database)
            db.execute('DELETE FROM Weapon WHERE WeaponId=24000'); db.commit(); db.close()
            missing = pb.catalog(root, database)
            self.assertIn('no longer exists', missing['error'])
            self.assertEqual(missing['document'], after['document'])

    def test_invalid_adjustments_never_become_sql(self):
        with static_data.StaticData() as source:
            for value in ('nan', 'xInfinity', '1; DROP TABLE Weapon', '='):
                doc = pb.empty()
                doc['tables'] = {'Weapon': {'24000': {'Cost': value}}}
                with self.assertRaises(ValueError):
                    pb.sql(doc, source)

    def test_uniform_weapon_and_attack_fields_are_collapsed(self):
        with tempfile.TemporaryDirectory() as config:
            model = pb.catalog(config, static_data.DEFAULT_DB)
        self.assertIsNone(model['error'])
        for page in model['pages']:
            if not page['id'].startswith('weapon-'):
                continue
            for grid in page['grids']:
                for column in grid['columns']:
                    values = {row['baseline'][column['name']] for row in grid['rows']}
                    self.assertGreater(len(values), 1, (page['id'], grid['table'], column['name']))

    def test_gear_order_visibility_and_icon_sections(self):
        with tempfile.TemporaryDirectory() as config:
            model = pb.catalog(config, static_data.DEFAULT_DB)
        self.assertIsNone(model['error'])
        for page in model['pages']:
            for grid in page['grids']:
                if grid['table'] not in ('Weapon', 'WeaponMod', 'Implant'):
                    continue
                columns = [c['name'] for c in grid['columns']]
                expected = [c for c in pb.LEADING_COLUMNS if c in columns]
                self.assertEqual(columns[:len(expected)], expected)
                for col in pb.GEAR_ORDER if grid['table'] in ('Weapon', 'WeaponMod') else pb.LEADING_COLUMNS:
                    if col in grid['rows'][0]['baseline']:
                        values = {r['baseline'][col] for r in grid['rows']}
                        if len(values) > 1:
                            self.assertIn(col, columns, (page['id'], col))
                order = [c for c in pb.GEAR_ORDER if c in columns] if grid['table'] in ('Weapon', 'WeaponMod') else expected
                self.assertEqual([c for c in columns if c in order], order)
                keys = [(r.get('icon', ''), *(float(r['baseline'][c]) for c in pb.LEADING_COLUMNS), pb.natural(r['name']))
                        for r in grid['rows']]
                self.assertEqual(keys, sorted(keys, key=lambda k: (pb.natural(k[0]), *k[1:])), page['id'])
        for pid in ('weapon-1', 'weapon-10'):
            grid = next(p for p in model['pages'] if p['id'] == pid)['grids'][0]
            self.assertTrue(grid['iconColumn'])
            self.assertTrue(all(r['section'] == r['icon'] and r['iconPath'] for r in grid['rows']))
        implants = [p['id'] for p in model['pages'] if p['id'].startswith('implant-') and p['id'] != 'implant-global']
        self.assertEqual(implants[:10], ['implant-%d' % s for s in pb.SLOT_ORDER])

    def test_trait_and_leverage_links_are_complete_and_traceable(self):
        with tempfile.TemporaryDirectory() as config:
            model = pb.catalog(config, static_data.DEFAULT_DB)
        with static_data.StaticData() as source:
            traits = {r['TraitId']: r for r in source.read('TraitModel')[1]}
            grids = next(p for p in model['pages'] if p['id'] == 'traits')['grids']
            shown = [r for g in grids if g['table'] == 'Trait' for r in g['rows']]
            self.assertEqual(set(traits), {r['id'] for r in shown})
            self.assertEqual(len(shown), len(traits))
            for g in grids:
                if g['table'] == 'Trait':
                    self.assertEqual(len({r['baseline']['TraitScore'] for r in g['rows']}), 1)
                else:
                    pointer = 'EffectTypeId' if g['table'] == 'Effect' else 'MatrixEffectTypeId'
                    for r in g['rows']:
                        owners = [source.locale.get('Trait.Name.' + t['TraitId'] + '_Male',
                                                    source.locale.get('Trait.Name.' + t['TraitGroup'] + '_Male', t['TraitName']))
                                  for t in traits.values() if t[pointer] == r['id']]
                        self.assertTrue(owners)
                        self.assertTrue(any(name in r['section'] for name in owners))
                        self.assertFalse(r['name'].startswith(('Effect.Name.', 'MatrixEffect.Name.')))
            self.assertFalse(any(r['name'].startswith('Trait.Name.') for r in shown))
            leverage = next(p for p in model['pages'] if p['id'] == 'leverage')['grids'][0]
            talents = source.read('TalentModel')[1]
            for r in leverage['rows']:
                if r['section'].startswith('Face talent:'):
                    self.assertTrue(any(t['ActionId'] == r['id'] and t['TalentIsFace'] != '0'
                                        and t['TargetType'] == 'LEVERAGE' for t in talents))
                if r['section'].startswith('Room level '):
                    self.assertEqual(r['section'], 'Room level ' + r['baseline']['RoomLevel'])
            self.assertEqual(len(leverage['rows']), len(source.read('MissionAdvantageModel')[1]))

    def test_weapon_mod_edits_export_to_sql(self):
        with static_data.StaticData() as source:
            rid = source.read('WeaponModModel')[1][0]['WeaponModId']
            doc = pb.apply_edits(pb.empty(), {'cells': [{'table': 'WeaponMod', 'id': rid,
                                                       'column': 'AccuracyMod', 'value': '=17'}]}, source)
            statements, touched = pb.sql(doc, source)
            memory = sqlite3.connect(':memory:'); source.connection.backup(memory)
            memory.executescript('\n'.join(statements))
            self.assertEqual(memory.execute('SELECT AccuracyMod FROM WeaponMod WHERE WeaponModId=?', (rid,)).fetchone()[0], 17)
            self.assertEqual(touched, {('WeaponMod', rid, 'AccuracyMod')})
            memory.close()

    def test_api_save_clear_noop_and_stale_database(self):
        import serve
        live = r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config'
        with tempfile.TemporaryDirectory() as td:
            config = serve._sandbox(live, os.path.join(td, 'config'))
            original = (Path(config) / pb.FILE).read_bytes()
            app = serve.App({'gameDir': '', 'configDirOverride': config, 'stripReadme': False}, 'test',
                            static_source=str(static_data.DEFAULT_DB))
            model = app.api_model()
            edit = {'cells': [{'table': 'Trait', 'id': '3', 'column': 'TraitScore', 'value': '=-9'}],
                    'databaseSha': model['playerBalance']['database']['sha256']}
            saved = app.api_save({'playerBalance': edit}, expect=model['fingerprints'])
            self.assertTrue(saved['ok'], saved)
            self.assertEqual(pb.load(config)['tables']['Trait']['3']['TraitScore'], '=-9')
            self.assertEqual(saved['written'], [pb.FILE])
            model = app.api_model()
            trait = next(g for p in model['playerBalance']['pages'] if p['id'] == 'traits'
                         for g in p['grids'] if g['table'] == 'Trait' and any(r['id'] == '3' for r in g['rows']))
            self.assertEqual(trait['subsection'], 'Trait score -9')
            edit['cells'][0]['value'] = ''
            cleared = app.api_save({'playerBalance': edit}, expect=model['fingerprints'])
            self.assertTrue(cleared['ok'], cleared)
            self.assertEqual((Path(config) / pb.FILE).read_bytes(), original)
            model = app.api_model()
            noop = app.api_save({}, expect=model['fingerprints'])
            self.assertTrue(noop['ok'], noop)
            self.assertEqual(noop['written'], [])
            edit['cells'][0]['value'] = '=7'
            edit['databaseSha'] = '0' * 64
            stale = app.api_save({'playerBalance': edit}, expect=model['fingerprints'])
            self.assertFalse(stale['ok'])
            self.assertIn('Official data changed', stale['refused']['detail'])
            self.assertEqual((Path(config) / pb.FILE).read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
