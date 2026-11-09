"""Compact gear presentation retains native Workshop identities."""
from pathlib import Path
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

    def test_cyberweapon_names_come_from_linked_implants_without_changing_export_targets(self):
        pages = {p['id']: p for p in self.model['pages']}
        with static_data.StaticData() as source:
            weapons = {r['WeaponId']: r for r in source.read('WeaponModel')[1]}
            for pid in ('weapon-16', 'weapon-17'):
                for row in pages[pid]['grids'][0]['rows']:
                    names = list(dict.fromkeys(r['name'] for r in row['cyberwareServices']))
                    if names:
                        self.assertEqual(row['name'], ' / '.join(names))
                        self.assertEqual(row['weaponName'], weapons[row['id']]['WeaponName'])
                    self.assertEqual(row['targets']['Cost']['table'], 'Weapon')
                    self.assertEqual(row['targets']['Cost']['id'], row['id'])
            row = next(r for r in pages['weapon-17']['grids'][0]['rows'] if r['id'] == '25001')
            self.assertEqual(row['name'], 'Brightshot Optic 2')
            doc = pb.apply_edits(pb.empty(), {'cells': [{'table': 'Weapon', 'id': row['id'],
                                      'column': 'Cost', 'value': '17'}]}, source)
            _, touched = pb.sql(doc, source)
            self.assertEqual(touched, {('Weapon', '25001', 'Cost')})

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
