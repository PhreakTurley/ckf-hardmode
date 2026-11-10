"""Consumable tags, themed visuals, literal icon SQL and read-only view updates."""
from contextlib import closing
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import player_balance as pb
import static_data


def item_rows(model):
    return {r['id']: (p, g, r) for p in model['pages'] if p['group'] == 'Consumables'
            for g in p['grids'] for r in g['rows']}


class ConsumableEditorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as config:
            cls.model = pb.catalog(config, static_data.DEFAULT_DB)
        assert not cls.model['error'], cls.model['error']

    def test_tags_and_themed_visual_pools_keep_grenades_separate(self):
        rows = item_rows(self.model)
        medical = rows['1'][2]['consumable']['family']
        drugs = rows['9'][2]['consumable']['family']
        grenade = rows['3'][2]['consumable']['family']
        self.assertEqual(medical, drugs)
        self.assertNotEqual(medical, grenade)
        editor = rows['9'][1]['consumableEditor']
        self.assertEqual({c['id']: c['name'] for c in editor['tags']}['4'], 'Combat Drug')
        pools = editor['families']
        self.assertEqual({c['id'] for c in pools[medical]['models']}, {'1000', '1001', '1002'})
        self.assertEqual({c['id'] for c in pools[grenade]['models']}, {'25', '26'})
        self.assertFalse({c['id'] for c in pools[medical]['icons']} & {c['id'] for c in pools[grenade]['icons']})
        self.assertIn('combatdrug10', {c['id'] for c in pools[medical]['icons']})
        self.assertIn('talent_item_grenade', {c['id'] for c in pools[grenade]['icons']})
        self.assertIsNone(rows['1000'][2]['consumable']['talent'])
        for _, grid, _ in rows.values():
            self.assertFalse({'ItemClass', 'Asset3DTypeId', 'Action.ExtraAsset', 'Action.IconPng'} &
                             {c['name'] for c in grid['columns'] + grid['advanced']})

    def test_pending_tag_and_visuals_regroup_without_changing_saved_tuning(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            doc = pb.apply_edits(pb.empty(), {'cells': [
                {'table': 'Item', 'id': '9', 'column': 'ItemClass', 'value': '1'},
                {'table': 'Item', 'id': '9', 'column': 'Asset3DTypeId', 'value': '1001'},
                {'table': 'Item', 'id': '9', 'column': 'Cost', 'value': '17'},
                {'table': 'Talent', 'id': '75014', 'column': 'IconPng', 'value': 'talent_item_bandage'}]}, source)
            model = pb.catalog(config, static_data.DEFAULT_DB, document=doc)
            self.assertIsNone(model['error'])
            page, grid, row = item_rows(model)['9']
            self.assertEqual(page['id'], 'consumable-1')
            self.assertEqual(row['baseline']['ItemClass'], '4')
            self.assertEqual(row['consumable']['classCurrent'], '1')
            self.assertEqual(row['consumable']['modelCurrent'], '1001')
            self.assertEqual(row['consumable']['talent']['iconCurrent'], 'talent_item_bandage')
            self.assertEqual(row['targets']['Action.ApCost']['table'], 'Talent')
            self.assertEqual(row['targets']['Action.ApCost']['id'], '75014')
            self.assertEqual(pb.load(config), pb.empty())
            self.assertFalse((Path(config) / pb.FILE).exists())
            (Path(config) / pb.FILE).write_bytes(pb.encode(doc))
            self.assertEqual(item_rows(pb.catalog(config, static_data.DEFAULT_DB))['9'][0]['id'], 'consumable-1')
            reset = pb.apply_edits(doc, {'cells': [{'table': 'Item', 'id': '9', 'column': 'ItemClass', 'value': ''}]}, source)
            self.assertEqual(item_rows(pb.catalog(config, static_data.DEFAULT_DB, document=reset))['9'][0]['id'], 'consumable-4')

    def test_assignments_export_to_native_item_and_talent_rows(self):
        with static_data.StaticData() as source:
            edits = [{'table': 'Item', 'id': '9', 'column': 'ItemClass', 'value': '1'},
                     {'table': 'Item', 'id': '9', 'column': 'Asset3DTypeId', 'value': '1001'},
                     {'table': 'Talent', 'id': '75014', 'column': 'IconPng', 'value': 'talent_item_bandage'},
                     {'table': 'Talent', 'id': '75000', 'column': 'ExtraAsset', 'value': '25'}]
            doc = pb.apply_edits(pb.empty(), {'cells': edits}, source)
            statements, touched = pb.sql(doc, source)
            self.assertEqual(touched, {(e['table'], e['id'], e['column']) for e in edits})
            with closing(sqlite3.connect(':memory:')) as db:
                db.execute('CREATE TABLE Item (ItemTypeId INTEGER, ItemClass INTEGER, Asset3DTypeId INTEGER, Cost INTEGER)')
                db.executemany('INSERT INTO Item VALUES (?,?,?,?)', [(9, 4, 1002, 123), (-1, 2, 26, 456)])
                db.execute('CREATE TABLE Talent (TalentId INTEGER, IconPng TEXT, ExtraAsset INTEGER)')
                db.executemany('INSERT INTO Talent VALUES (?,?,?)', [(75014, 'combatdrug10', 0), (75000, 'talent_item_grenade', 26)])
                db.executescript('\n'.join(statements))
                self.assertEqual(db.execute('SELECT ItemClass,Asset3DTypeId,Cost FROM Item WHERE ItemTypeId=9').fetchone(), (1, 1001, 123))
                self.assertEqual(db.execute('SELECT ItemClass,Asset3DTypeId,Cost FROM Item WHERE ItemTypeId=-1').fetchone(), (2, 26, 456))
                self.assertEqual(db.execute('SELECT IconPng FROM Talent WHERE TalentId=75014').fetchone()[0], 'talent_item_bandage')
                self.assertEqual(db.execute('SELECT ExtraAsset FROM Talent WHERE TalentId=75000').fetchone()[0], 25)
            reset = pb.apply_edits(doc, {'cells': [dict(e, value='') for e in edits]}, source)
            self.assertEqual(reset, pb.empty())
            for column, value in [('ItemClass', '999999'), ('IconPng', 'not_a_real_icon')]:
                table, rid = ('Item', '9') if column == 'ItemClass' else ('Talent', '75014')
                with self.assertRaises(ValueError):
                    pb.apply_edits(pb.empty(), {'cells': [{'table': table, 'id': rid, 'column': column, 'value': value}]}, source)

    def test_shared_talent_visuals_keep_one_native_adjustment(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            doc = pb.apply_edits(pb.empty(), {'cells': [
                {'table': 'Item', 'id': '2', 'column': 'TalentId', 'value': '75014'},
                {'table': 'Talent', 'id': '75014', 'column': 'IconPng', 'value': 'talent_item_bandage'}]}, source)
            model = pb.catalog(config, static_data.DEFAULT_DB, document=doc)
            self.assertIsNone(model['error'])
            rows = item_rows(model)
            for rid in ('2', '9'):
                talent = rows[rid][2]['consumable']['talent']
                self.assertEqual(talent['id'], '75014')
                self.assertEqual(talent['iconCurrent'], 'talent_item_bandage')
                self.assertTrue(talent['sharedWith'])
            self.assertEqual(doc['tables']['Talent'], {'75014': {'IconPng': 'talent_item_bandage'}})

    def test_literal_icon_sql_quotes_an_existing_asset_key(self):
        with tempfile.TemporaryDirectory() as directory, static_data.StaticData() as source:
            database = Path(directory) / 'data.db'
            value = "medical's icon; still one value"
            with closing(sqlite3.connect(database)) as db:
                source.connection.backup(db)
                db.execute('UPDATE Talent SET IconPng=? WHERE TalentId=75014', (value,))
                db.commit()
            with static_data.StaticData(database) as modified:
                doc = pb.apply_edits(pb.empty(), {'cells': [{'table': 'Talent', 'id': '75014', 'column': 'IconPng', 'value': value}]}, modified)
                statements, _ = pb.sql(doc, modified)
            with closing(sqlite3.connect(':memory:')) as db:
                db.execute('CREATE TABLE Talent (TalentId INTEGER, IconPng TEXT)')
                db.execute("INSERT INTO Talent VALUES (75014,'old')")
                db.executescript('\n'.join(statements))
                self.assertEqual(db.execute('SELECT IconPng FROM Talent').fetchone()[0], value)

    def test_preview_is_read_only_and_save_moves_the_item(self):
        import serve
        with tempfile.TemporaryDirectory() as config:
            path = Path(config) / pb.FILE
            (Path(config) / 'ckf.hardmode.cfg').write_text('', encoding='utf-8')
            path.write_bytes(pb.encode(pb.empty()))
            app = serve.App({'configDirOverride': config}, 'test', static_source=static_data.DEFAULT_DB)
            model = app.api_model()
            change = {'databaseSha': model['playerBalance']['database']['sha256'], 'cells': [
                {'table': 'Item', 'id': '9', 'column': 'ItemClass', 'value': '1'},
                {'table': 'Talent', 'id': '75014', 'column': 'IconPng', 'value': 'talent_item_bandage'}]}
            before = {p: p.read_bytes() for p in Path(config).rglob('*') if p.is_file()}
            preview = app.api_player_preview(change, model['fingerprints'])
            self.assertTrue(preview['ok'], preview)
            self.assertEqual(item_rows({'pages': preview['pages']})['9'][0]['id'], 'consumable-1')
            self.assertEqual({p: p.read_bytes() for p in Path(config).rglob('*') if p.is_file()}, before)
            stale_data = app.api_player_preview(dict(change, databaseSha='changed'), model['fingerprints'])
            self.assertFalse(stale_data['ok'])
            saved = app.api_save({'playerBalance': change}, expect=model['fingerprints'])
            self.assertTrue(saved['ok'], saved)
            self.assertEqual(item_rows(app.api_model()['playerBalance'])['9'][0]['id'], 'consumable-1')
            self.assertEqual(pb.load(config)['tables']['Talent']['75014']['IconPng'], 'talent_item_bandage')
            stale = app.api_player_preview(change, model['fingerprints'])
            self.assertFalse(stale['ok'])
            self.assertIn(pb.FILE, stale['stale'])


if __name__ == '__main__':
    unittest.main()
