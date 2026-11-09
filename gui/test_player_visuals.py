"""Official visual choices, grouping, and Workshop persistence."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import player_balance as pb
import static_data


class PlayerVisualTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as config:
            cls.model = pb.catalog(config, static_data.DEFAULT_DB)
        assert not cls.model['error'], cls.model['error']
        cls.pages = {p['id']: p for p in cls.model['pages']}
        with static_data.StaticData() as source:
            cls.assets = {r['WeaponModelId']: r for r in source.read('Weapon3DAssetModel')[1]}
            cls.weapons = source.read('WeaponModel')[1]
            cls.mods = source.read('WeaponModModel')[1]
            mappings = source.read('WeaponClassModModel')[1]
            cls.fits = {r['WeaponModId']: pb.mod_fitment(source, r, mappings) for r in cls.mods}

    def test_weapon_names_and_all_three_class_pickers(self):
        self.assertEqual(self.pages['weapon-3']['title'], 'Assault Rifle')
        self.assertEqual(self.pages['weapon-12']['title'], 'Urban Assault')
        for weapon_class in ('3', '4', '12'):
            grid = self.pages['weapon-' + weapon_class]['grids'][0]
            expected = {r['Asset3DTypeId'] for r in self.weapons if r['WeaponClass'] == weapon_class
                        and self.assets[r['Asset3DTypeId']]['Thumbnail']
                        and self.assets[r['Asset3DTypeId']]['Resource']}
            self.assertEqual({c['id'] for c in grid['iconEditor']['choices']}, expected)
            self.assertNotIn('Asset3DTypeId', [c['name'] for c in grid['columns'] + grid['advanced']])
            self.assertTrue(grid['dynamicColumns'])

    def test_mod_pickers_follow_fitment_and_allow_icon_only_assets(self):
        icon_only, multiple = set(), 0
        for grid in self.pages['weapon-mods']['grids']:
            pool = [r for r in self.mods if (self.fits[r['WeaponModId']]['category'],
                    self.fits[r['WeaponModId']]['title']) == (grid['category'], grid['subsection'])]
            ids = {r['Asset3DTypeId'] for r in pool if self.assets[r['Asset3DTypeId']]['Thumbnail']}
            paths = {self.assets[rid]['Thumbnail'] for rid in ids}
            self.assertEqual('iconEditor' in grid, len(paths) > 1)
            self.assertTrue(grid['dynamicColumns'])
            if len(paths) < 2:
                continue
            multiple += 1
            editor = grid['iconEditor']
            self.assertTrue(editor['regroup'])
            self.assertEqual({c['id'] for c in editor['choices']}, ids)
            self.assertNotIn('Asset3DTypeId', [c['name'] for c in grid['columns'] + grid['advanced']])
            icon_only.update(c['id'] for c in editor['choices'] if not c['resource'])
        self.assertGreater(multiple, 1)
        self.assertGreaterEqual(icon_only, {'3000', '3001'})

    def test_scope_swap_is_limited_to_combined_rifle_optics(self):
        for mod_class, expected in [('6', ['Scope Reflex', 'Scope Sowo', 'Scope Rifle']),
                                    ('9', ['Scope Long Range', 'Scope Rifle', 'Scope Sowo'])]:
            grids = [g for g in self.pages['weapon-mods']['grids']
                     if any(self.fits[r['id']]['modClass'] == mod_class for r in g['rows'])]
            self.assertTrue(grids)
            for grid in grids:
                order = list(dict.fromkeys(c['name'] for c in grid['iconEditor']['choices']))
                self.assertEqual(order, expected)
                row_order = list(dict.fromkeys(r['icon'] for r in grid['rows']))
                self.assertEqual(row_order, [name for name in expected if name in row_order])

    def test_mod_and_urban_visuals_round_trip_sql_regroup_and_reset(self):
        grids = [self.pages['weapon-12']['grids'][0]] + [
            g for g in self.pages['weapon-mods']['grids'] if g.get('iconEditor')]
        edits = []
        for grid in grids:
            row = grid['rows'][0]
            base = self.assets[row['baseline']['Asset3DTypeId']]['Thumbnail']
            chosen = next(c for c in grid['iconEditor']['choices'] if c['thumbnail'] != base)
            edits.append({'table': grid['table'], 'id': row['id'], 'column': 'Asset3DTypeId', 'value': chosen['id']})
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            doc = pb.apply_edits(pb.empty(), {'cells': edits}, source)
            (Path(config) / pb.FILE).parent.mkdir(parents=True, exist_ok=True)
            (Path(config) / pb.FILE).write_bytes(pb.encode(doc))
            self.assertEqual(pb.load(config), doc)
            statements, touched = pb.sql(doc, source)
            self.assertEqual(touched, {(e['table'], e['id'], e['column']) for e in edits})
            with closing(sqlite3.connect(':memory:')) as db:
                for table, key in [('Weapon', 'WeaponId'), ('WeaponMod', 'WeaponModId')]:
                    db.execute(f'CREATE TABLE {table} ({key} INTEGER PRIMARY KEY, Asset3DTypeId INTEGER, Cost INTEGER)')
                    db.executemany(f'INSERT INTO {table} VALUES (?, 0, 123)',
                                   [(int(e['id']),) for e in edits if e['table'] == table] + [(-1,)])
                db.executescript('\n'.join(statements))
                for e in edits:
                    key = pb.TABLE_KEYS[e['table']]
                    self.assertEqual(db.execute(f"SELECT Asset3DTypeId, Cost FROM {e['table']} WHERE {key}=?",
                                                (int(e['id']),)).fetchone(), (int(e['value']), 123))
                self.assertEqual(db.execute('SELECT Asset3DTypeId, Cost FROM WeaponMod WHERE WeaponModId=-1').fetchone(), (0, 123))
            reloaded = pb.catalog(config, static_data.DEFAULT_DB)
            self.assertIsNone(reloaded['error'])
            mod_rows = {r['id']: r for p in reloaded['pages'] if p['id'] == 'weapon-mods' for g in p['grids'] for r in g['rows']}
            for e in edits:
                if e['table'] == 'WeaponMod':
                    self.assertEqual(mod_rows[e['id']]['sectionKey'], self.assets[e['value']]['Thumbnail'])
            cleared = pb.apply_edits(doc, {'cells': [dict(e, value='') for e in edits]}, source)
            self.assertEqual(cleared, pb.empty())


if __name__ == '__main__':
    unittest.main()
