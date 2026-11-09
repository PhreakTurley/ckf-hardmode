"""Compact gear presentation retains native Workshop identities."""
from pathlib import Path
from contextlib import closing
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import player_balance as pb
import static_data


class PlayerDisplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as config:
            cls.model = pb.catalog(config, static_data.DEFAULT_DB)
        assert not cls.model['error'], cls.model['error']

    def test_equipment_defaults_to_cost_including_joined_and_hidden_cost_fields(self):
        tables = set()
        for page in self.model['pages']:
            for grid in page['grids']:
                if grid['table'] not in ('Weapon', 'WeaponMod', 'Item', 'Implant'):
                    continue
                tables.add(grid['table'])
                self.assertEqual(grid['defaultSort'], {'key': 'column:Cost', 'descending': False})
                self.assertIn('Cost', {c['name'] for c in grid['columns'] + grid['advanced']})
        self.assertEqual(tables, {'Weapon', 'WeaponMod', 'Item', 'Implant'})

    def test_single_graphic_mods_retain_asset_metadata_for_show_all_and_pending_edits(self):
        singles = [g for p in self.model['pages'] if p['id'] == 'weapon-mods'
                   for g in p['grids'] if not g.get('iconEditor')]
        self.assertTrue(singles)
        for grid in singles:
            source = grid['iconSource']
            self.assertEqual(source['column'], 'Asset3DTypeId')
            self.assertTrue(source['regroup'])
            for row in grid['rows']:
                asset = source['assets'].get(row['baseline']['Asset3DTypeId'], {})
                self.assertEqual(asset.get('thumbnail', ''), row['iconPath'])

    def test_cyberweapon_names_and_costs_use_linked_implants(self):
        pages = {p['id']: p for p in self.model['pages']}
        with static_data.StaticData() as source:
            weapons = {r['WeaponId']: r for r in source.read('WeaponModel')[1]}
            implants = {r['ImplantTypeId']: r for r in source.read('ImplantModel')[1]}
            for pid in ('weapon-16', 'weapon-17'):
                for row in pages[pid]['grids'][0]['rows']:
                    names = list(dict.fromkeys(r['name'] for r in row['cyberwareServices']))
                    if names:
                        self.assertEqual(row['name'], ' / '.join(names))
                        self.assertEqual(row['weaponName'], weapons[row['id']]['WeaponName'])
                    target = row['targets']['Cost']
                    self.assertEqual(target['table'], 'Implant')
                    self.assertEqual(target['id'], row['cyberwareServices'][0]['id'])
                    self.assertEqual(row['baseline']['Cost'], implants[target['id']]['Cost'])
            row = next(r for r in pages['weapon-17']['grids'][0]['rows'] if r['id'] == '25001')
            self.assertEqual(row['name'], 'Brightshot Optic 2')
            target = row['targets']['Cost']
            doc = pb.apply_edits(pb.empty(), {'cells': [{k: target[k] for k in ('table', 'id', 'column')} | {'value': '17'}]}, source)
            statements, touched = pb.sql(doc, source)
            self.assertEqual(touched, {('Implant', target['id'], 'Cost')})
            with closing(sqlite3.connect(':memory:')) as db:
                db.execute('CREATE TABLE Implant (ImplantTypeId INTEGER, Cost INTEGER)')
                db.execute('CREATE TABLE Weapon (WeaponId INTEGER, Cost INTEGER)')
                db.execute('INSERT INTO Implant VALUES (?, ?)', (int(target['id']), int(implants[target['id']]['Cost'])))
                db.execute('INSERT INTO Weapon VALUES (?, ?)', (int(row['id']), int(weapons[row['id']]['Cost'])))
                db.executescript('\n'.join(statements))
                self.assertEqual(db.execute('SELECT Cost FROM Implant').fetchone()[0], 17)
                self.assertEqual(db.execute('SELECT Cost FROM Weapon').fetchone()[0], int(weapons[row['id']]['Cost']))

    def test_cyberweapon_price_preserves_legacy_weapon_overrides_and_uses_saved_implant_adjustments(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            doc = pb.empty()
            doc['tables'] = {'Weapon': {'25001': {'Cost': '99'}}, 'Implant': {'3201': {'Cost': '+50'}}}
            doc['implantMultipliers']['Cost'] = 2
            path = Path(config) / pb.FILE
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(pb.encode(doc))
            model = pb.catalog(config, static_data.DEFAULT_DB)
            self.assertIsNone(model['error'])
            row = next(r for p in model['pages'] if p['id'] == 'weapon-17' for r in p['grids'][0]['rows'] if r['id'] == '25001')
            self.assertEqual(row['baseline']['Cost'], '250')
            self.assertEqual(row['targets']['Cost']['table'], 'Implant')
            self.assertEqual(pb.load(config), doc)
            statements, _ = pb.sql(doc, source)
            with closing(sqlite3.connect(':memory:')) as db:
                db.execute('CREATE TABLE Implant (ImplantTypeId INTEGER, Cost INTEGER)')
                db.execute('CREATE TABLE Weapon (WeaponId INTEGER, Cost INTEGER)')
                db.execute('INSERT INTO Implant VALUES (3201, 250)')
                db.execute('INSERT INTO Weapon VALUES (25001, 110)')
                db.executescript('\n'.join(statements))
                self.assertEqual(db.execute('SELECT Cost FROM Implant').fetchone()[0], 600)
                self.assertEqual(db.execute('SELECT Cost FROM Weapon').fetchone()[0], 99)

    def test_missing_or_ambiguous_cyberware_price_links_never_fall_back_to_weapon_cost(self):
        for count in (0, 2):
            with self.subTest(linked=count), tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
                database = Path(config) / 'data.db'
                with closing(sqlite3.connect(database)) as db:
                    source.connection.backup(db)
                    if count == 0:
                        db.execute('UPDATE Implant SET ImplantTalentId=0, ImplantTalentId2=0 WHERE ImplantTypeId=3201')
                    else:
                        db.execute('UPDATE Implant SET ImplantTalentId=(SELECT ImplantTalentId FROM Implant WHERE ImplantTypeId=3201) WHERE ImplantTypeId=3200')
                    db.commit()
                model = pb.catalog(config, database)
                self.assertIsNone(model['error'])
                grid = next(p for p in model['pages'] if p['id'] == 'weapon-17')['grids'][0]
                row = next(r for r in grid['rows'] if r['id'] == '25001')
                self.assertIsNone(row['baseline']['Cost'])
                self.assertNotIn('Cost', row['targets'])
                self.assertFalse(grid['joinsComplete'])
                self.assertIn('Weapon 25001: Cost requires one linked implant; found %s.' % count, grid['warning'])

    def test_cyberweapon_service_metadata_uses_implants_in_one_column(self):
        with static_data.StaticData() as source:
            services = pb.service_catalog(source)['Implant']
        for page in self.model['pages']:
            if page['id'] not in ('weapon-16', 'weapon-17'):
                continue
            grid = page['grids'][0]
            self.assertNotIn('cyberwareServiceColumn', grid)
            self.assertEqual(grid['serviceColumn']['source'], 'cyberware')
            self.assertTrue(grid['serviceColumn']['readOnly'])
            self.assertEqual(grid['serviceColumn']['options'], services)
            for row in grid['rows']:
                self.assertEqual(row['targets']['ServiceOptionId'],
                                 {'table': 'Weapon', 'id': row['id'], 'column': 'ServiceOptionId'})

    def test_item_fallbacks_keep_loot_and_blueprint_output_types_distinct(self):
        class Source:
            def read(self, model, required=()):
                if model == 'BlueprintModel':
                    specs = [('11', '3', '1', '1'), ('12', '1', '2', '1'), ('13', '3', '3', '0'),
                             ('14', '3', '4', '0')]
                    return [], [dict(zip(('BlueprintId', 'BlueprintClassId', 'OutputId', 'Lootable'), r)) for r in specs]
                specs = [('1', '2', '1'), ('2', '2', '2'), ('3', '1', '13'), ('4', '8', '4'), ('5', '10', '5')]
                return [], [dict(zip(('MissionLootId', 'LootTypeId', 'LootKey'), r)) for r in specs]
        actual = pb.item_service_fallbacks(Source())
        self.assertEqual({rid: r['label'] for rid, r in actual.items()},
                         {'1': 'Loot / Blueprint', '2': 'Loot', '3': 'Blueprint'})
        self.assertIn('MissionLoot 3', actual['3']['detail'])


if __name__ == '__main__':
    unittest.main()
