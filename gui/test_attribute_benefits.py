"""Attribute benefit discovery, table identities, sparse export and UI controls."""
from pathlib import Path
import json
import shutil
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import navigation
import player_balance as pb
import static_data


class AttributeBenefitsTests(unittest.TestCase):
    def test_catalog_covers_official_attribute_groups_with_current_baselines(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            model = pb.catalog(config, source.path)
            self.assertIsNone(model['error'])
            page = next(p for p in navigation.catalog_pages(model['pages']) if p['id'] == 'attribute-benefits')
            self.assertEqual((page['owner'], page['group']), ('player-balance', 'Character'))
            expected = {(table, str(row[0])) for table, key in [('Effect', 'EffectId'), ('MatrixEffect', 'MatrixEffectId')]
                        for row in source.connection.execute(
                            'SELECT %s FROM %s WHERE EffectGroupId BETWEEN 301 AND 307' % (key, table))}
            actual = {(g['table'], r['id']) for g in page['grids'] for r in g['rows']}
            self.assertEqual(actual, expected)
            self.assertEqual(len(actual), 13)
            for g in page['grids']:
                self.assertTrue(g['dynamicColumns'])
                self.assertTrue(g['advanced'])
                self.assertTrue(g['scrollWithPage'])
                key = pb.TABLE_KEYS[g['table']]
                official = {r[key]:r for r in source.read(g['table'] + 'Model')[1]}
                for r in g['rows']:
                    self.assertFalse(r['readOnly'])
                    self.assertEqual(r['description'], source.locale[g['table'] + '.' + r['id'] + '.AttributeDesc'])
                    for col, value in r['baseline'].items():
                        self.assertEqual(value, official[r['id']][col])

    def test_edit_export_and_clear_preserve_table_identity_and_other_rows(self):
        with static_data.StaticData() as source:
            cells = [
                {'table':'Effect', 'id':'310', 'column':'RecoilRate', 'value':'-350'},
                {'table':'Effect', 'id':'313', 'column':'SpecialValue', 'value':'150'},
                {'table':'MatrixEffect', 'id':'330', 'column':'ActionPoints', 'value':'200'},
                {'table':'Effect', 'id':'310', 'column':'MaxHitPoints', 'value':'7'},
            ]
            doc = pb.apply_edits(pb.empty(), {'cells':cells}, source)
            statements, touched = pb.sql(doc, source)
            self.assertEqual(touched, {(c['table'], c['id'], c['column']) for c in cells})
            mem = sqlite3.connect(':memory:')
            try:
                source.connection.backup(mem)
                before = mem.execute('SELECT * FROM Effect WHERE EffectId<>310 AND EffectId<>313 ORDER BY EffectId').fetchall()
                mem.executescript('\n'.join(statements))
                self.assertEqual(mem.execute('SELECT RecoilRate,MaxHitPoints FROM Effect WHERE EffectId=310').fetchone(), (-350,7))
                self.assertEqual(mem.execute('SELECT SpecialValue FROM Effect WHERE EffectId=313').fetchone()[0], 150)
                self.assertEqual(mem.execute('SELECT ActionPoints FROM MatrixEffect WHERE MatrixEffectId=330').fetchone()[0], 200)
                self.assertEqual(before, mem.execute('SELECT * FROM Effect WHERE EffectId<>310 AND EffectId<>313 ORDER BY EffectId').fetchall())
            finally:
                mem.close()
            cleared = pb.apply_edits(doc, {'cells':[dict(c, value='') for c in cells]}, source)
            self.assertEqual(cleared, pb.empty())
            self.assertEqual(pb.sql(cleared, source)[0], [])

    def test_older_database_names_missing_records_without_hiding_other_catalogs(self):
        with tempfile.TemporaryDirectory() as config:
            model = pb.catalog(config, Path(static_data.DEFAULT_DB).parent / '.119/data.db')
            self.assertIsNone(model['error'])
            page = next(p for p in model['pages'] if p['id'] == 'attribute-benefits')
            self.assertEqual(len(page['grids']), 8)
            self.assertTrue(all(g['warning'] and not g['rows'] for g in page['grids']))
            self.assertTrue(any(p['id'] == 'traits' for p in model['pages']))

    def test_saved_edits_regenerate_complete_tooltips_and_clear_to_official(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            doc = pb.empty()
            doc['tables'] = {'Effect': {
                '310': {'PureDamageMelee': '0', 'PhysicalDamage': '100', 'WoundRes': '100'},
                '311': {'MoveSpeed': '50'}, '313': {'SpecialValue': '200'}}}
            path = Path(config) / pb.FILE
            path.write_bytes(pb.encode(doc))
            # No new cells: previously saved adjustments are the complete input.
            restored = pb.apply_edits(pb.load(config), {'cells': []}, source)
            text = pb.attribute_descriptions(restored, source)
            self.assertEqual(set(text), {'Effect.310.AttributeDesc', 'Effect.311.AttributeDesc',
                                         'Effect.313.AttributeDesc'})
            self.assertEqual(set(text['Effect.310.AttributeDesc'].splitlines()), {
                '-2% Recoil Rate per 1 Strength', '+1% Kinetic Dmg per 1 Strength',
                '+1% Wound Res per 1 Strength'})
            self.assertEqual(set(text['Effect.311.AttributeDesc'].splitlines()), {
                '+1% Move Speed per 2 Reaction', '+1 Initiative per 5 Reaction'})
            self.assertEqual(text['Effect.313.AttributeDesc'], '+2% Cybernetic Weapon Dmg per 1 Will')
            model = pb.catalog(config, source.path)
            page = next(p for p in navigation.catalog_pages(model['pages']) if p['id'] == 'attribute-benefits')
            for grid in page['grids']:
                for row in grid['rows']:
                    key = '%s.%s.AttributeDesc' % (grid['table'], row['id'])
                    self.assertEqual(row['description'], text.get(key, source.locale[key]))
            payload = {'RawText': {'Generic': {'unrelated': 'keep'}, 'Other': {'x': 'keep'}}}
            provenance = {'parser_source': {}}
            data, _, _ = pb.augment(pb.encode(payload), pb.encode(provenance), config, source.path)
            exported = json.loads(data)
            self.assertEqual(exported['RawText']['Generic'], {'unrelated': 'keep', **text})
            self.assertEqual(exported['RawText']['Other'], {'x': 'keep'})
            self.assertEqual(path.read_bytes(), pb.encode(doc))
            cleared = pb.apply_edits(restored, {'cells': [
                {'table': table, 'id': rid, 'column': col, 'value': ''}
                for table, records in doc['tables'].items() for rid, fields in records.items()
                for col in fields]}, source)
            path.write_bytes(pb.encode(cleared))
            data, _, _ = pb.augment(pb.encode(payload), pb.encode(provenance), config, source.path)
            self.assertEqual(json.loads(data)['RawText'], payload['RawText'])

    def test_ratios_specials_matrix_and_zero_rows(self):
        with static_data.StaticData() as source:
            doc = pb.empty()
            doc['tables'] = {'Effect': {'310': {'RecoilRate': '-350'},
                                      '311': {'InitBonus': '25', 'Evasion': '50'},
                                      '322': {'SpecialValue': '50'},
                                      '324': {'SpecialValue': '0'}},
                             'MatrixEffect': {'330': {'ActionPoints': 'x2', 'DeckArmor': '+5',
                                                     'IoPercent': '50'}}}
            pb.validate(doc, source)
            text = pb.attribute_descriptions(doc, source)
            self.assertIn('-7% Recoil Rate per 2 Strength', text['Effect.310.AttributeDesc'])
            self.assertIn('+1 Initiative per 4 Reaction', text['Effect.311.AttributeDesc'])
            self.assertIn('+1% Evasion per 2 Reaction', text['Effect.311.AttributeDesc'])
            self.assertEqual(text['Effect.322.AttributeDesc'], '+6 hr mission delay with Handbrake Talent per 2 Cunning')
            self.assertEqual(text['Effect.324.AttributeDesc'], '')
            self.assertEqual(set(text['MatrixEffect.330.AttributeDesc'].splitlines()), {
                '+2 Matrix AP per 1 Tech', '+1 Cyberdeck Armor per 4 Tech', '+1% IO Speed per 2 Tech'})

    def test_missing_display_rules_and_conflicting_locale_refuse(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            for fields, message in [({'AttFast': '100'}, r'Effect 311.AttFast'),
                                    ({'SpecialCode': '999', 'SpecialValue': '100'}, 'SpecialCode 999')]:
                doc = pb.empty()
                doc['tables'] = {'Effect': {'311': fields}}
                with self.assertRaisesRegex(ValueError, message):
                    pb.validate(doc, source)
            doc = pb.empty()
            doc['tables'] = {'Effect': {'311': {'MoveSpeed': '50'}}}
            (Path(config) / pb.FILE).write_bytes(pb.encode(doc))
            with self.assertRaisesRegex(ValueError, 'both own hover text Effect.311.AttributeDesc'):
                pb.augment(pb.encode({'RawText': {'Generic': {'Effect.311.AttributeDesc': 'conflict'}}}),
                           pb.encode({'parser_source': {}}), config, source.path)

    def test_validate_and_save_check_previously_saved_rows_without_new_cells(self):
        import serve
        with tempfile.TemporaryDirectory() as config:
            root = Path(config)
            (root / 'ckf.hardmode.cfg').write_text('[General]\nEnabled = true\n')
            doc = pb.empty()
            doc['tables'] = {'Effect': {'311': {'MoveSpeed': '50'}}}
            path = root / pb.FILE
            path.write_bytes(pb.encode(doc))
            app = serve.App({'configDirOverride': config, 'gameDir': '', 'stripReadme': False},
                            'test', static_source=str(static_data.DEFAULT_DB))
            app.schemas = []
            # Isolate the player validation path; the full editor suite covers
            # the unchanged Hard Mode schema checker and its required files.
            with patch.object(serve, 'stage_and_validate', return_value={'ran': True, 'problems': []}), \
                 patch.object(serve, 'run_check_schema', return_value={'ran': True, 'problems': []}), \
                 patch.object(pb, 'attribute_descriptions', wraps=pb.attribute_descriptions) as generate:
                self.assertTrue(app.api_validate({})['ok'])
                self.assertEqual(generate.call_args.args[0], doc)
                self.assertTrue(app.api_save({})['ok'])
                self.assertEqual(generate.call_args.args[0], doc)
                self.assertEqual(path.read_bytes(), pb.encode(doc))
                doc['tables']['Effect']['311']['AttFast'] = '100'
                path.write_bytes(pb.encode(doc))
                for operation in (app.api_validate, app.api_save):
                    response = operation({})
                    self.assertFalse(response['ok'])
                    self.assertIn('Effect 311.AttFast', response['refused']['detail'])
                    self.assertEqual(path.read_bytes(), pb.encode(doc))

    def test_installed_parser_emits_generated_locale_and_matching_values(self):
        import modkit
        engine = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader')
        if not (engine / 'CyberKnightsModkit_Data/Managed/DataParserNETStandard.dll').is_file() or not shutil.which('pwsh'):
            self.skipTest('Installed Modkit parser and PowerShell 7 unavailable')
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            doc = pb.empty()
            doc['tables'] = {'Effect': {'311': {'MoveSpeed': '50', 'InitBonus': '25', 'Evasion': '50'},
                                      '324': {'SpecialValue': '0'}},
                             'MatrixEffect': {'330': {'DeckArmor': '25'}}}
            (Path(config) / pb.FILE).write_bytes(pb.encode(doc))
            data, _, _ = pb.augment(b'{}', pb.encode({'parser_source': {}}), config, source.path)
            files, _ = modkit.prepare_parser(data, engine / 'WorkshopContent/Unused',
                                             engine / 'WorkshopContent/config.json')
            self.assertEqual(json.loads(files['en-US.json']), {
                'Effect.311.AttributeDesc': '+1% Evasion per 2 Reaction\n+1% Move Speed per 2 Reaction\n+1 Initiative per 4 Reaction',
                'Effect.324.AttributeDesc': '',
                'MatrixEffect.330.AttributeDesc': '+1 Matrix AP per 1 Tech\n+1 Cyberdeck Armor per 4 Tech'})
            db = sqlite3.connect(':memory:')
            try:
                source.connection.backup(db)
                db.executescript(files['data.sql'].decode('utf-8-sig'))
                self.assertEqual(db.execute('SELECT MoveSpeed,InitBonus,Evasion FROM Effect WHERE EffectId=311').fetchone(), (50,25,50))
                self.assertEqual(db.execute('SELECT SpecialValue FROM Effect WHERE EffectId=324').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT DeckArmor FROM MatrixEffect WHERE MatrixEffectId=330').fetchone()[0], 25)
            finally:
                db.close()


UI = r'''
setTimeout(function() {
 let passed=0;function ck(name,ok) {if(!ok) throw new Error(name);passed++;console.log('PASS '+name);}
 SEL='pb:attribute-benefits';render();
 const panel=$('#panel'), find=fn=>panel.find(fn);
 const page=MODEL.playerBalance.pages.find(p=>p.id==='attribute-benefits');
 ck('attribute benefits belongs to Player Balance', page.owner==='player-balance');
 ck('all seven attributes are visible', ['Strength','Reaction','Will','Tech','Persuasion','Cunning','Handling'].every(s=>panel.textContent.includes(s)));
 let target=s=>find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')===s)[0];
 ck('nonzero physical and matrix bonuses are editable', !!target('Effect 310.RecoilRate') && !!target('MatrixEffect 330.ActionPoints'));
 ck('unused columns start hidden', !target('Effect 310.MaxHitPoints'));
 const show=find(n=>n.tagName==='INPUT' && n.type==='checkbox')[0];
 ck('show all columns checkbox is present', !!show && panel.textContent.includes('Show all columns'));
 show.checked=true;show.fire('change');
 ck('show all exposes unused and metadata columns', !!target('Effect 310.MaxHitPoints') && !!target('Effect 310.EffectGroupId'));
 let input=target('Effect 310.MaxHitPoints');input.value='7';input.fire('input');
 input=target('MatrixEffect 330.ActionPoints');input.value='200';input.fire('input');
 ck('save payload keeps physical and matrix identities', buildEdits().playerBalance.cells.some(c=>c.table==='Effect' && c.id==='310' && c.column==='MaxHitPoints' && c.value==='7') && buildEdits().playerBalance.cells.some(c=>c.table==='MatrixEffect' && c.id==='330' && c.column==='ActionPoints' && c.value==='200'));
 show.checked=false;show.fire('change');
 ck('an overridden zero column stays visible', !!target('Effect 310.MaxHitPoints'));
 for (const s of ['Effect 310.MaxHitPoints','MatrixEffect 330.ActionPoints']) {input=target(s);input.value='';input.fire('input');}
 ck('clearing removes both pending edits', !playerChanges().cells.length);
 console.log('Attribute benefits UI: '+passed+' passed');process.exit(0);
},0);
'''


if __name__ == '__main__':
    if '--ui' in sys.argv:
        import serve
        sys.exit(serve.selftest_dom(serve.App(serve.load_settings(), 'test').api_model(), UI))
    unittest.main()
