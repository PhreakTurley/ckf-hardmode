"""Workshop ownership, SQL parity, and live catalog regression checks."""
import copy
from contextlib import closing
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
    def test_assignment_prefix_normalization_preserves_operations(self):
        for original, expected in [('=90','90'), ('=-10','-10'), ('=+10','10'),
                                   (' = -1e1 ','-1e1'), ('+10','+10'),
                                   ('x1.5','x1.5'), ('+-10','+-10'), ('','')]:
            with self.subTest(original=original):
                self.assertEqual(pb.normalize_adjustment(original), expected)
                self.assertEqual(pb.adjustment(original), pb.adjustment(expected))
        with static_data.StaticData() as source:
            doc = pb.apply_edits(pb.empty(), {'cells':[
                {'table':'Weapon','id':'24000','column':'Cost','value':'=+90'}]}, source)
            self.assertEqual(doc['tables']['Weapon']['24000']['Cost'], '90')

    def test_negative_assignments_and_explicit_commands_match_preview_and_sql(self):
        with static_data.StaticData() as source, closing(sqlite3.connect(':memory:')) as db:
            db.execute('CREATE TABLE Weapon (WeaponId INTEGER PRIMARY KEY, RecoilRate1 INTEGER)')
            db.execute('INSERT INTO Weapon VALUES (24000, 50)')
            for spec, expected in [('-10', -10), (' -10 ', -10), ('-1e1', -10),
                                   ('+10', 60), ('x1.5', 75), ('x-1.5', -75),
                                   ('+-10', 40), ('=-10', -10)]:
                with self.subTest(spec=spec):
                    doc = pb.empty()
                    doc['tables'] = {'Weapon': {'24000': {'RecoilRate1': spec}}}
                    statements, touched = pb.sql(doc, source)
                    self.assertEqual(touched, {('Weapon', '24000', 'RecoilRate1')})
                    db.execute('UPDATE Weapon SET RecoilRate1=50')
                    for statement in statements:
                        db.execute(statement)
                    self.assertEqual(db.execute('SELECT RecoilRate1 FROM Weapon').fetchone()[0], expected)
                    self.assertEqual(pb.effective(doc, 'Weapon', {'WeaponId':'24000','RecoilRate1':'50'},
                                                  'RecoilRate1'), expected)

    def test_legacy_negative_adjustment_keeps_subtracting_after_import(self):
        with tempfile.TemporaryDirectory() as temp:
            legacy = Path(temp) / 'ckf.hardmode.d'
            legacy.mkdir()
            (legacy / 'implants-global.json').write_text(json.dumps(
                {'costMultiply':1,'installTimeMultiply':1,'implantStressMultiply':1}))
            (legacy / 'implants-slot1.csv').write_text('ImplantTypeId,Cost\n100,-10\n')
            for name in ('cyberweapons-claws.csv', 'cyberweapons-lasers.csv'):
                (legacy / name).write_text('WeaponId\n')
            doc = pb.import_legacy(temp)
            self.assertEqual(doc['tables']['Implant']['100']['Cost'], '+-10')
            self.assertEqual(pb.adjustment(doc['tables']['Implant']['100']['Cost']), ('add', -10))

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
            self.assertEqual(doc['tables']['Effect'], {'50007': {'CritMultiBase': '0'}})
            for effect in pb.HARDMODE_EFFECTS:
                with self.assertRaisesRegex(ValueError, 'Hard Mode'):
                    pb.apply_edits(doc, {'cells': [{'table': 'Effect', 'id': str(effect), 'column': 'XpBonus', 'value': '0'}]}, source)
            changed = pb.apply_edits(doc, {'cells': [{'table': 'Rule', 'id': '23', 'column': 'Value', 'value': '4'}]}, source)
            self.assertEqual(changed['tables']['Rule'], {'23': {'Value': '4'}})
            statements, touched = pb.sql(changed, source)
            self.assertIn(('Rule', '23', 'Value'), touched)
            memory = sqlite3.connect(':memory:')
            try:
                source.connection.backup(memory)
                memory.executescript('\n'.join(statements))
                self.assertEqual(memory.execute('SELECT Value FROM Rule WHERE RuleId=23').fetchone()[0], 4)
            finally:
                memory.close()
            for rid, owner in [('82', 'Enemy Balance'), ('83', 'Party Size Mod'),
                               ('84', 'Faster Contact Limit Breaks'), ('85', 'Faster Contact Limit Breaks')]:
                with self.subTest(rule=rid), self.assertRaisesRegex(ValueError, owner):
                    pb.apply_edits(doc, {'cells': [{'table': 'Rule', 'id': rid, 'column': 'Value', 'value': '4'}]}, source)

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
                    targets = [r.get('targets', {}).get(column['name']) for r in grid['rows']]
                    table = next((t['table'] for t in targets if t), grid['table'])
                    if table in ('Effect', 'MatrixEffect'):
                        # Linked bonuses have the documented nonzero policy,
                        # even when every weapon shares the same bonus.
                        self.assertTrue(any(v not in (None, '', '0', '0.0') for v in values),
                                        (page['id'], table, column['name']))
                    else:
                        self.assertGreater(len(values), 1, (page['id'], table, column['name']))

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
                keys = [(r.get('icon', ''), r.get('sectionKey', ''), *(float(r['baseline'][c]) for c in pb.LEADING_COLUMNS), pb.natural(r['name']))
                        for r in grid['rows']]
                self.assertEqual(keys, sorted(keys, key=lambda k: (pb.natural(k[0]), pb.natural(k[1]), *k[2:])), page['id'])
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
            # Independently join the official SQL tables rather than calling
            # the catalog's classification helper to grade its own output.
            tag_fields = ['BackstoryTrait'] + [c[1] for c in source.schema['Backstory']
                                             if c[1].startswith(('Trait1', 'Trait2'))]
            tags_sql = ' UNION ALL '.join('SELECT JobTypeId, NewGame, %s AS Tag FROM Backstory'
                                         % static_data.quote(c) for c in tag_fields)
            knight_ids = {str(row[0]) for row in source.connection.execute('''
                WITH BackstoryTags AS (%s)
                SELECT DISTINCT family.TraitId FROM Trait tagged
                JOIN Trait family ON family.TraitGroup = tagged.TraitGroup
                WHERE tagged.TagMatch <> ''
                  AND EXISTS (SELECT 1 FROM BackstoryTags b WHERE b.Tag = tagged.TagMatch
                              AND b.JobTypeId = 1 AND b.NewGame <> 0)
                  AND NOT EXISTS (SELECT 1 FROM BackstoryTags b WHERE b.Tag = tagged.TagMatch
                                  AND b.JobTypeId <> 1)
                ''' % tags_sql)}
            knight_grid = next(g for g in grids if g['table'] == 'Trait' and g['subsection'] == 'Cyber Knight Traits')
            self.assertTrue(knight_ids)
            self.assertEqual({r['id'] for r in knight_grid['rows']}, knight_ids)
            for g in grids:
                if g['table'] == 'Trait':
                    if g['subsection'] == 'Cyber Knight Traits':
                        self.assertEqual({r['id'] for r in g['rows']}, knight_ids)
                    else:
                        scores = {r['baseline']['TraitScore'] for r in g['rows']}
                        self.assertEqual(len(scores), 1)
                        score = float(next(iter(scores)))
                        self.assertEqual(g['subsection'], 'Trait score ' + (format(score, '+g') if score else '0'))
                        self.assertFalse(knight_ids & {r['id'] for r in g['rows']})
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
            leverage_grids = next(p for p in model['pages'] if p['id'] == 'leverage')['grids']
            talents = source.read('TalentModel')[1]
            face_ids = {t['ActionId'] for t in talents if t['TalentIsFace'] != '0' and t['TargetType'] == 'LEVERAGE'}
            official = {r['AdvantageTypeId']: r for r in source.read('MissionAdvantageModel')[1]}
            shown_leverage = [r for g in leverage_grids for r in g['rows']]
            self.assertEqual(len(shown_leverage), len(official))
            self.assertEqual({r['id'] for r in shown_leverage}, set(official))
            for g in leverage_grids:
                for r in g['rows']:
                    native = official[r['id']]
                    expected = ('Face leverage' if r['id'] in face_ids else
                                '0-token leverage' if float(native['TokenCost']) == 0 else
                                'Matrix-only leverage' if float(native['AdvantageIsMatrixOnly']) != 0 else
                                'Favor-cost leverage' if float(native['FavorCost']) != 0 else 'Other leverage')
                    self.assertEqual(g['subsection'], expected)
                    self.assertEqual(r['baseline']['RoomLevel'], native['RoomLevel'])
                    if r['id'] in face_ids:
                        self.assertTrue(any(t['TalentName'] in r['description'] for t in talents
                                            if t['ActionId'] == r['id'] and t['TalentIsFace'] != '0'
                                            and t['TargetType'] == 'LEVERAGE'))

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

    def test_claws_omit_attack_range_and_preserve_stored_adjustments(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            model = pb.catalog(config, static_data.DEFAULT_DB)
            claws = next(p for p in model['pages'] if p['id'] == 'weapon-16')['grids'][0]
            columns = {c['name'] for c in claws['columns'] + claws['advanced']}
            self.assertFalse(any(c.startswith('Attack') and c.endswith('.Range') for c in columns))
            self.assertIn('Attack.ApCost', {c['name'] for c in claws['advanced']})
            laser = next(p for p in model['pages'] if p['id'] == 'weapon-17')['grids'][0]
            self.assertIn('Attack.Range', {c['name'] for c in laser['columns'] + laser['advanced']})
            # The removed control must not erase an existing saved adjustment.
            tid = claws['rows'][0]['links']['Attack']
            document = pb.empty()
            document['tables'] = {'Talent': {tid: {'Range': '9', 'ApCost': '0'}}}
            path = Path(config) / pb.FILE
            path.write_bytes(pb.encode(document))
            before = path.read_bytes()
            adjusted = pb.catalog(config, static_data.DEFAULT_DB)
            claws = next(p for p in adjusted['pages'] if p['id'] == 'weapon-16')['grids'][0]
            self.assertFalse(any(c['name'].startswith('Attack') and c['name'].endswith('.Range')
                                 for c in claws['columns'] + claws['advanced']))
            self.assertIn('Attack.ApCost', {c['name'] for c in claws['columns']})
            self.assertEqual(path.read_bytes(), before)
            statements, touched = pb.sql(adjusted['document'], source)
            self.assertEqual(touched, {('Talent', tid, 'Range'), ('Talent', tid, 'ApCost')})
            with closing(sqlite3.connect(':memory:')) as memory:
                source.connection.backup(memory)
                memory.executescript('\n'.join(statements))
                self.assertEqual(memory.execute('SELECT Range, ApCost FROM Talent WHERE TalentId=?',
                                                (tid,)).fetchone(), (9, 0))

    def test_weapon_mod_groups_use_visible_labels_and_distinct_thumbnail_paths(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            database = Path(config) / 'data.db'
            with closing(sqlite3.connect(database)) as memory:
                source.connection.backup(memory)
                initial = pb.catalog(config, database)
                grids = next(p for p in initial['pages'] if p['id'] == 'weapon-mods')['grids']
                selected = max(grids, key=lambda g: len(g['rows']))['rows'][:4]
                self.assertEqual(len(selected), 4)
                ids = [r['id'] for r in selected]
                # Labels and path order disagree. Different assets can share
                # a path; identical labels can also name different paths.
                paths = ['ZFolder/WeaponMod_A', 'ZFolder/WeaponMod_A',
                         'YFolder/WeaponMod_A', 'AFolder/WeaponMod_Z']
                next_asset = memory.execute('SELECT MAX(WeaponModelId) FROM Weapon3DAsset').fetchone()[0] + 1
                for index, (rid, thumbnail) in enumerate(zip(ids, paths)):
                    asset = next_asset + index
                    memory.execute('INSERT INTO Weapon3DAsset (WeaponModelId, Thumbnail) VALUES (?,?)', (asset, thumbnail))
                    memory.execute('UPDATE WeaponMod SET Asset3DTypeId=? WHERE WeaponModId=?', (asset, rid))
                memory.commit()
            updated = pb.catalog(config, database)
            self.assertIsNone(updated['error'])
            grid = next(g for p in updated['pages'] if p['id'] == 'weapon-mods' for g in p['grids']
                        if {r['id'] for r in g['rows']} >= set(ids))
            records = {r['id']: r for r in grid['rows']}
            self.assertEqual(records[ids[0]]['sectionKey'], records[ids[1]]['sectionKey'])
            self.assertEqual(records[ids[0]]['icon'], records[ids[2]]['icon'])
            self.assertNotEqual(records[ids[0]]['sectionKey'], records[ids[2]]['sectionKey'])
            order = [r['id'] for r in grid['rows'] if r['id'] in ids]
            self.assertEqual(order[0], ids[2])
            self.assertEqual(set(order[1:3]), set(ids[:2]))
            self.assertEqual(order[-1], ids[3])
            closed, previous = set(), None
            for row in grid['rows']:
                if row['sectionKey'] != previous:
                    self.assertNotIn(row['sectionKey'], closed)
                    closed.add(row['sectionKey'])
                    previous = row['sectionKey']

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
            self.assertEqual(pb.load(config)['tables']['Trait']['3']['TraitScore'], '-9')
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
