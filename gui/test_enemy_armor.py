"""Enemy armor ownership, clone inheritance, guarded edits and rendered controls."""
import csv
import io
from pathlib import Path
import sys
import tempfile
import unittest

import serve
import enemy_armor as armor


class ArmorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = Path(self.temp.name)
        (self.config / 'ckf.hardmode.d').mkdir()
        self.path = self.config / armor.SHEET
        self.raw = (b'ArmorId,_clone,_serveOn,BallisticArmor,_comment\r\n'
                    b'22000,,,45,source adjustment\r\n'
                    b'990001,22000,never,,fixture clone\r\n')
        self.path.write_bytes(self.raw)
        (self.config / armor.MONSTERS).write_bytes(b'MonsterTypeId,ArmorTypeId\n1,990001\n1100,22511\n')

    def test_validation_uses_replaced_assignments_and_reports_unmodified_native_defects(self):
        view = armor.validate(self.config, serve.static_data.DEFAULT_DB)
        self.assertEqual(view['unresolvedAssignments'], [])
        (self.config / armor.MONSTERS).write_bytes(b'MonsterTypeId,ArmorTypeId\n1,990001\n')
        view = armor.model(self.config, serve.static_data.DEFAULT_DB, {})
        self.assertIn({'monsterId':'1100', 'name':'Hover Tank', 'powerLevel':'1', 'armorId':'22510'},
                      view['unresolvedAssignments'])
        with self.assertRaisesRegex(ValueError, 'MonsterType 1100 -> Armor 22510'):
            armor.validate(self.config, serve.static_data.DEFAULT_DB)

    def test_proposed_missing_pointer_is_refused_before_save(self):
        proposed = {armor.MONSTERS:b'MonsterTypeId,ArmorTypeId\n1100,999999\n'}
        with self.assertRaisesRegex(ValueError, 'MonsterType 1100 -> Armor 999999'):
            armor.validate(self.config, serve.static_data.DEFAULT_DB, proposed)

    def test_authored_names_use_the_effective_level_and_natural_sort(self):
        self.path.write_bytes(b'ArmorId,_clone,PowerLevel\n990001,135,9\n990002,135,10\n22104,,5\n')
        view = armor.validate(self.config, serve.static_data.DEFAULT_DB)
        rows = {r['id']:r for r in view['page']['grids'][0]['rows']}
        self.assertEqual(rows['990001']['name'], 'Drone Infantry (PL 9)')
        self.assertEqual(rows['990002']['name'], 'Drone Infantry (PL 10)')
        self.assertEqual(rows['22104']['name'], 'Sniper Guard (PL 5)')
        order = [r['id'] for r in view['page']['grids'][0]['rows']]
        self.assertLess(order.index('990001'), order.index('990002'))

    def test_clones_inherit_the_authored_source_and_keep_distinct_identity(self):
        view = armor.model(self.config, serve.static_data.DEFAULT_DB, {})
        self.assertIsNone(view['error'])
        rows = {r['id']: r for r in view['page']['grids'][0]['rows']}
        self.assertEqual(rows['990001']['cloneOf'], '22000')
        self.assertEqual(rows['990001']['baseline']['BallisticArmor'], '45')
        self.assertEqual(rows['990001']['targets']['BallisticArmor']['id'], '990001')
        self.assertIsNone(rows['22000']['cloneOf'])

    def test_noop_preserves_original_bytes(self):
        self.assertEqual(armor.apply_edits(self.config, serve.static_data.DEFAULT_DB, []), {})
        self.assertEqual(armor.apply_edits(self.config, serve.static_data.DEFAULT_DB,
            [{'id':'22000','column':'BallisticArmor','value':'45'}]), {})
        self.assertEqual(self.path.read_bytes(), self.raw)

    def test_clear_and_zero_are_distinct_and_clone_controls_survive(self):
        for value in ('', '0'):
            result = armor.apply_edits(self.config, serve.static_data.DEFAULT_DB,
                [{'id':'22000','column':'BallisticArmor','value':value}])
            rows = list(csv.DictReader(io.StringIO(result[armor.SHEET].decode())))
            self.assertEqual(rows[0]['BallisticArmor'], value)
            self.assertEqual(rows[1]['_clone'], '22000')
            self.assertEqual(rows[1]['_serveOn'], 'never')
            self.assertEqual(rows[1]['_comment'], 'fixture clone')
            self.assertEqual(self.path.read_bytes(), self.raw)

    def test_unlisted_shipped_enemy_row_and_extra_column_can_be_authored(self):
        result = armor.apply_edits(self.config, serve.static_data.DEFAULT_DB,
            [{'id':'22001','column':'PhysicalArmor','value':'37'}])
        rows = {r['ArmorId']:r for r in csv.DictReader(io.StringIO(result[armor.SHEET].decode()))}
        self.assertEqual(rows['22001']['PhysicalArmor'], '37')
        self.assertEqual(rows['990001']['_clone'], '22000')

    def test_controls_nonintegers_and_unknown_targets_are_refused(self):
        for rid, column, value in [('990001','_clone','22001'), ('990001','PhysicalArmor','NaN'),
                                    ('990001','PhysicalArmor','3.5'), ('999999','PhysicalArmor','1')]:
            with self.subTest(column=column, value=value), self.assertRaises(ValueError):
                armor.apply_edits(self.config, serve.static_data.DEFAULT_DB,
                    [{'id':rid,'column':column,'value':value}])

    def test_ambiguous_parked_source_is_refused(self):
        self.path.with_suffix('.csv.disabled').write_bytes(self.raw)
        self.assertIn('Expected one active or parked', armor.model(self.config, serve.static_data.DEFAULT_DB, {})['error'])

    def test_shared_player_marker_uses_positive_table_scoped_references(self):
        with serve.static_data.StaticData() as source:
            stock = {r['ArmorId']:r for r in source.read('ArmorModel')[1]}
            refs = armor.player_references(source, stock)
            pets = source.read('DronePrebuiltModel')[1]
            pet = next(r for r in pets if r['Armor'] in stock)
            self.assertTrue(any('PetPrebuilt '+pet['DroneType'] in x for x in refs[pet['Armor']]))

    def test_save_uses_the_shared_overlay_and_refuses_stale_armor_bytes(self):
        settings = serve.load_settings()
        config = Path(serve._sandbox(serve.config_dir_for(settings), str(self.config / 'full-config')))
        app = serve.App({'gameDir':'', 'configDirOverride':str(config), 'stripReadme':False,
                         'officialDataPath':str(serve.static_data.DEFAULT_DB)}, 'test')
        model = app.api_model()
        view = model['enemyArmor']
        clone = next(r for r in view['page']['grids'][0]['rows'] if r['cloneOf'])
        previous = view['values'][clone['id']]['BallisticArmor']
        change = {'enemyArmor': {'databaseSha':view['database']['sha256'], 'cells':[
            {'id':clone['id'], 'column':'BallisticArmor', 'value':'47' if previous!='47' else '48'}]}}
        result = app.api_save(change, expect=model['fingerprints'])
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['written'], [view['path']])
        refreshed = app.api_model()
        path = config / view['path']
        external = path.read_bytes() + b'# another editor changed this file\n'
        path.write_bytes(external)
        refused = app.api_save(change, expect=refreshed['fingerprints'])
        self.assertFalse(refused['ok'])
        self.assertIn(view['path'], refused['stale'])
        self.assertEqual(path.read_bytes(), external)


UI = r'''
setTimeout(function() {
 let passed=0;function ck(name,ok) {if(!ok) throw new Error(name);passed++;console.log('PASS '+name);}
 SEL=MODEL.enemyArmor.sectionId;render();
 const panel=$('#panel'), find=fn=>panel.find(fn), page=MODEL.enemyArmor.page;
 ck('enemy armor has a dedicated navigation section', MODEL.sections.some(s=>s.id===SEL && s.title==='Enemy Armors'));
 ck('clones have an explicit visible identity', find(n=>n._cls().includes('pb-clone') && /Clone \d+ \(from \d+\)/.test(n.textContent)).length>0);
 ck('shipped armors are labelled separately', find(n=>n._cls().includes('pill') && n.textContent.startsWith('Shipped ')).length>0);
 ck('tables scroll with the page', find(n=>n._cls().includes('grid-wrap')).every(n=>n._cls().includes('page-grid-wrap')));
 const before=JSON.stringify(W.player), clone=page.grids[0].rows.find(r=>r.cloneOf);
 const input=find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='Armor '+clone.id+'.BallisticArmor')[0];
 const previous=input.value;input.value=previous==='47'?'48':'47';input.fire('input');
 ck('armor edits enter their own save block', buildEdits().enemyArmor.cells.some(c=>c.id===clone.id && c.column==='BallisticArmor'));
 ck('armor editing does not change player tuning', JSON.stringify(W.player)===before);
 ck('unsaved edits block package preparation', find(n=>n.getAttribute('id')==='prepare-enemy')[0].disabled);
 input.value=previous;input.fire('input');
 ck('restoring an armor value clears its pending edit', !enemyArmorChanges().cells.length);
 const row=page.grids[0].rows[0];row.playerUse=true;row.acquisition=['Fixture positive player reference'];render();
 ck('shared armor declares its player use', find(n=>n._cls().includes('pb-enemy') && n.textContent==='Also used by players').length>0);
 const all=find(n=>n.tagName==='INPUT' && n.type==='checkbox')[0];all.checked=true;all.fire('change');
 ck('advanced armor columns remain available', find(n=>n.tagName==='INPUT' && /\.ServiceOptionId$/.test(n.getAttribute('data-player-target') || '')).length>0);
 console.log('Enemy armor UI: '+passed+' passed');process.exit(0);
},0);
'''

if __name__ == '__main__':
    if '--ui' in sys.argv:
        sys.exit(serve.selftest_dom(serve.App(serve.load_settings(),'test').api_model(), UI))
    unittest.main()
