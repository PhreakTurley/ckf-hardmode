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
            db.execute('INSERT INTO Weapon (WeaponId, WeaponClass, Cost, ServiceOptionId) VALUES (999999, 16, 17, 1)')
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

    def test_inclusive_acquisition_keeps_explicit_story_gear_and_nonlootable_mission_blueprints(self):
        with tempfile.TemporaryDirectory() as config:
            model = pb.catalog(config, static_data.DEFAULT_DB)
        self.assertIsNone(model['error'])
        drawn = {(g['table'], r['id']): r for p in model['pages'] for g in p['grids'] for r in g['rows']}
        for wid in ('1028', '4025'):
            self.assertTrue(any('BlockCondition 2526 Equip' in e for e in drawn['Weapon', wid]['acquisition']))
        self.assertIn('Blueprint 200132 via MissionLoot 9130', drawn['WeaponMod', '132']['acquisition'])
        for key in (('Weapon', '21001'), ('Weapon', '21006'), ('Weapon', '23001'), ('WeaponMod', '5075')):
            self.assertNotIn(key, set(drawn))

    def test_blueprint_column_matches_typed_drop_references_and_never_enters_sql(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            expected = {('Weapon' if int(r[0]) in (1, 7) else 'WeaponMod', str(r[1]))
                        for r in source.connection.execute("""
                            SELECT DISTINCT b.BlueprintClassId,b.OutputId FROM Blueprint b
                            WHERE b.BlueprintClassId IN (1,5,7) AND
                              (b.Lootable=1 OR EXISTS (SELECT 1 FROM MissionLoot l
                                 WHERE l.LootTypeId=1 AND l.LootKey=b.BlueprintId))
                        """)}
            actual = pb.blueprint_drop_references(source)
            self.assertEqual({(table, rid) for table, records in actual.items() for rid in records}, expected)
            self.assertIn('Blueprint 200132 via MissionLoot 9130', actual['WeaponMod']['132'])
            self.assertNotIn('21001', actual['Weapon'])
            self.assertNotIn('1028', actual['Weapon'])
            doc = pb.empty()
            doc['tables'] = {'Weapon': {'21001': {'Cost': '0'}}, 'WeaponMod': {'5075': {'Cost': '0'}}}
            path = Path(config) / pb.FILE
            before = pb.encode(doc); path.write_bytes(before)
            model = pb.catalog(config, static_data.DEFAULT_DB)
            self.assertIsNone(model['error'])
            for page in model['pages']:
                for grid in page['grids']:
                    if grid['table'] not in ('Weapon', 'WeaponMod'):
                        self.assertNotIn('blueprintColumn', grid)
                        continue
                    self.assertEqual(grid['blueprintColumn']['label'], 'Blueprint')
                    for row in grid['rows']:
                        self.assertEqual(bool(row['blueprintDrops']), (grid['table'], row['id']) in expected)
                    self.assertNotIn('Blueprint', [c['name'] for c in grid['columns'] + grid['advanced']])
            self.assertEqual(path.read_bytes(), before)
            statements, touched = pb.sql(model['document'], source)
            self.assertEqual(touched, {('Weapon','21001','Cost'), ('WeaponMod','5075','Cost')})
            self.assertTrue(all('Blueprint' not in stmt for stmt in statements))

    def test_service_fallbacks_distinguish_generic_pools_from_mission_only_sources(self):
        class Source:
            def read(self, model, *args):
                if model == 'BlueprintModel':
                    specs = [('103','1','3','1'), ('104','1','4','1'), ('105','1','5','0'),
                             ('106','1','6','0'), ('108','1','8','1'), ('109','1','9','0'),
                             ('114','2','14','1'), ('115','1','15','0'),
                             ('502','5','2','1'), ('503','5','3','0'), ('506','5','6','0')]
                    return [], [dict(zip(('BlueprintId','BlueprintClassId','OutputId','Lootable'), r)) for r in specs]
                specs = [('8','1','9000'), ('8','2','9000'), ('8','2','100000'),
                         ('8','4','100000'), ('1','105','9000'), ('1','106','50000'),
                         ('8','8','9000'), ('8','9','100000'), ('1','109','9000'),
                         ('8','13','9000'), ('1','115','9000'), ('8','16','7000'),
                         ('10','1','8000'), ('10','2','8000'), ('1','503','9000'), ('1','506','60001')]
                return [], [dict(zip(('LootTypeId','LootKey','LootGroupId'), r)) for r in specs]
        expected = {'Weapon': {'1':'Mission','2':'Loot','3':'Blueprint','4':'Loot / Blueprint',
                              '5':'Mission','6':'Blueprint','8':'Loot / Blueprint','9':'Loot / Blueprint',
                              '10':'Cyberware','11':'Pet','12':'Mission','13':'Loot','14':'',
                              '15':'Blueprint','16':'Loot'},
                    'WeaponMod': {'1':'Loot','2':'Loot / Blueprint','3':'Mission','4':'Crafting','5':'', '6':'Blueprint'}}
        kinds = {'Weapon': {'10': {'cyberware'}, '11': {'pet'}, '12': {'mission'},
                            '13': {'pet'}, '14': {'service'}, '15': {'pet'}},
                 'WeaponMod': {'4': {'crafting'}, '5': {'service'}}}
        refs = {t: {rid: [t + ' evidence ' + rid] for rid in ids} for t, ids in expected.items()}
        actual = pb.gear_service_fallbacks(Source(), refs, kinds)
        self.assertEqual({t: {rid: r['label'] for rid, r in records.items()} for t, records in actual.items()}, expected)
        self.assertTrue(all('evidence' in r['detail'] for records in actual.values() for r in records.values()))

    def test_blueprint_resale_categories_do_not_admit_wb_revolvers(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            rows = source.read('WeaponModel')[1]
            wb_ids = {r['WeaponId'] for r in rows if r['WeaponName'] == 'WB Revolver'}
            self.assertTrue(wb_ids)
            blueprint_ids = {r['BlueprintId'] for r in source.read('BlueprintModel')[1]
                             if r['BlueprintClassId'] == '1' and r['OutputId'] in wb_ids}
            self.assertTrue(blueprint_ids)
            refs = pb.player_gear_references(source)
            self.assertFalse(wb_ids & refs['Weapon'].keys())
            doc = pb.empty()
            doc['tables'] = {'Weapon': {'21001': {'Cost': '0'}}}
            (Path(config) / pb.FILE).write_bytes(pb.encode(doc))
            model = pb.catalog(config, static_data.DEFAULT_DB)
            self.assertIsNone(model['error'])
            matches = [(p['id'], r) for p in model['pages'] for g in p['grids']
                       if g['table'] == 'Weapon' for r in g['rows'] if r['id'] in wb_ids]
            self.assertEqual([(pid, r['id']) for pid, r in matches], [('other-weapon-overrides', '21001')])

    def test_crafted_intrinsic_remains_an_explicit_player_catalog_category(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            expected = {r['WeaponModId'] for r in source.read('WeaponModModel')[1]
                        if int(r['ModClassId']) >= 200}
            self.assertTrue(expected)
            model = pb.catalog(config, static_data.DEFAULT_DB)
            self.assertIsNone(model['error'])
            page = next(p for p in model['pages'] if p['id'] == 'weapon-mods')
            crafted = {r['id']: r for g in page['grids'] if g['category'] == 'Crafted Intrinsic' for r in g['rows']}
            self.assertEqual(set(crafted), expected)
            self.assertTrue(all('Player crafting option (Crafted Intrinsic)' in r['acquisition'] for r in crafted.values()))

    def test_other_weapon_overrides_disappear_only_after_the_last_saved_reset(self):
        import serve
        with tempfile.TemporaryDirectory() as config:
            root = Path(config)
            (root / 'ckf.hardmode.d').mkdir()
            (root / 'ckf.hardmode.cfg').write_text('', encoding='utf-8')
            doc = pb.empty()
            doc['tables'] = {'Weapon': {'23001': {'Cost': '0', 'Accuracy1': '80'}},
                             'WeaponMod': {'5075': {'Cost': '0'}}}
            (root / pb.FILE).write_bytes(pb.encode(doc))
            app = serve.App({'configDirOverride': config}, 'test', static_source=static_data.DEFAULT_DB)
            model = app.api_model()
            other = next(p for p in model['playerBalance']['pages'] if p['id'] == 'other-weapon-overrides')
            self.assertEqual({(g['table'], r['id']) for g in other['grids'] for r in g['rows']},
                             {('Weapon', '23001'), ('WeaponMod', '5075')})
            self.assertTrue(all(not r['readOnly'] for g in other['grids'] for r in g['rows']))
            for table, rid, col, remaining in [
                    ('Weapon', '23001', 'Cost', {'Weapon', 'WeaponMod'}),
                    ('Weapon', '23001', 'Accuracy1', {'WeaponMod'}),
                    ('WeaponMod', '5075', 'Cost', set())]:
                result = app.api_save({'playerBalance': {
                    'databaseSha': model['playerBalance']['database']['sha256'],
                    'cells': [{'table': table, 'id': rid, 'column': col, 'value': ''}]}},
                    expect=model['fingerprints'])
                self.assertTrue(result['ok'], result)
                model = app.api_model()
                other = next((p for p in model['playerBalance']['pages'] if p['id'] == 'other-weapon-overrides'), None)
                self.assertEqual({g['table'] for g in other['grids']} if other else set(), remaining)
                self.assertEqual(set(pb.load(config)['tables']), remaining)
            self.assertEqual(pb.load(config), pb.empty())

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
                keys = [(r.get('iconOrder', 0), r.get('icon', ''), r.get('sectionKey', ''), *(float(r['baseline'][c]) for c in pb.LEADING_COLUMNS), pb.natural(r['name']))
                        for r in grid['rows']]
                self.assertEqual(keys, sorted(keys, key=lambda k: (k[0], pb.natural(k[1]), pb.natural(k[2]), *k[3:])), page['id'])
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

    def test_weapon_mod_intrinsic_categories_preserve_fitment_and_export_identity(self):
        from types import SimpleNamespace
        cases = [('1', '1', 'Pistol/SMG Barrel', 'Weapon Mods'),
                 ('201', '10', 'Pistol/SMG Barrel', 'Crafted Intrinsic'),
                 ('100', '4', 'Intrinsic Melee Damage', 'Intrinsic'),
                 ('201', '10', 'Intrinsic Barrel', 'Intrinsic')]
        for modclass, slot, label, category in cases:
            with self.subTest(modclass=modclass, label=label):
                source = SimpleNamespace(locale={'Table.Column.ModType.' + modclass: label})
                fit = pb.mod_fitment(source, {'ModClassId': modclass, 'ModSlot': slot, 'Exclusions': '0'}, [])
                self.assertEqual(fit['category'], category)
                self.assertEqual(fit['slot'], slot)
                self.assertIn(label, fit['title'])
                if category != 'Weapon Mods':
                    self.assertIn('slot ' + slot, fit['title'])
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            model = pb.catalog(config, static_data.DEFAULT_DB)
            self.assertIsNone(model['error'])
            grids = next(p for p in model['pages'] if p['id'] == 'weapon-mods')['grids']
            self.assertEqual(list(dict.fromkeys(g['category'] for g in grids)),
                             ['Weapon Mods', 'Crafted Intrinsic', 'Intrinsic'])
            native = {r['WeaponModId']: r for r in source.read('WeaponModModel')[1]}
            # Independent SQL join checks the Python catalog against all
            # current mod services, direct loot and lootable or loot-listed blueprints.
            eligible = {str(r[0]) for r in source.connection.execute("""
                SELECT m.WeaponModId FROM WeaponMod m WHERE
                  m.ModClassId>=200
                  OR
                  EXISTS (SELECT 1 FROM ContactService s
                          WHERE s.ServiceFlow=3 AND s.ServiceOptionId>0
                            AND s.ServiceOptionId=m.ServiceOptionId)
                  OR EXISTS (SELECT 1 FROM MissionLoot l
                             WHERE l.LootTypeId=10 AND l.LootKey=m.WeaponModId)
                  OR EXISTS (SELECT 1 FROM Blueprint b
                             WHERE b.BlueprintClassId=5 AND b.OutputId=m.WeaponModId
                               AND (b.Lootable=1
                                 OR EXISTS (SELECT 1 FROM MissionLoot l
                                            WHERE l.LootTypeId=1 AND l.LootKey=b.BlueprintId)))
            """)}
            displayed = [r['id'] for g in grids for r in g['rows']]
            self.assertEqual(len(displayed), len(set(displayed)))
            self.assertEqual(set(displayed), eligible)
            for g in grids:
                for r in g['rows']:
                    row = native[r['id']]
                    label = source.locale.get('Table.Column.ModType.' + row['ModClassId'], '')
                    expected = ('Intrinsic' if 'intrinsic' in label.casefold() else
                                'Crafted Intrinsic' if int(row['ModClassId']) >= 200 else 'Weapon Mods')
                    self.assertEqual(g['category'], expected)
                    self.assertEqual(r['fitment'], g['subsection'])
            # A mod in each category still saves and exports to its own native row.
            ids = [next(r['id'] for g in grids if g['category'] == category for r in g['rows'])
                   for category in ('Weapon Mods', 'Crafted Intrinsic', 'Intrinsic')]
            document = pb.apply_edits(pb.empty(), {'cells': [
                {'table': 'WeaponMod', 'id': rid, 'column': 'AccuracyMod', 'value': '17'} for rid in ids]}, source)
            path = Path(config) / pb.FILE
            path.write_bytes(pb.encode(document))
            before = path.read_bytes()
            regrouped = pb.catalog(config, static_data.DEFAULT_DB)
            self.assertEqual(path.read_bytes(), before)
            statements, touched = pb.sql(regrouped['document'], source)
            self.assertEqual(touched, {('WeaponMod', rid, 'AccuracyMod') for rid in ids})
            with closing(sqlite3.connect(':memory:')) as memory:
                source.connection.backup(memory)
                memory.executescript('\n'.join(statements))
                for rid in ids:
                    self.assertEqual(memory.execute('SELECT AccuracyMod FROM WeaponMod WHERE WeaponModId=?',
                                                    (rid,)).fetchone()[0], 17)

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
