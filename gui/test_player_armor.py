"""Player armor acquisition, intrinsic joins, export identity and controls."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import player_balance as pb
import static_data


class PlayerArmorTests(unittest.TestCase):
    def test_catalog_matches_typed_acquisition_and_class_order(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            model = pb.catalog(config, source.path)
            self.assertIsNone(model['error'])
            pages = [p for p in model['pages'] if p['group'] in ('Armor', 'Drone armors')]
            self.assertEqual([p['title'] for p in pages[:3]], ['Stealth', 'Light', 'Heavy'])
            options = {r['ServiceOptionId'] for r in pb.contact_services(source)
                       if r['attainable'] and r['ServiceFlow'] == '2' and int(r['ServiceOptionId']) > 0}
            expected = {r['ArmorId'] for r in source.read('ArmorModel')[1] if r['ServiceOptionId'] in options}
            expected.update(str(r[0]) for r in source.connection.execute('''
                SELECT LootKey FROM MissionLoot WHERE LootTypeId=12
                UNION SELECT OutputId FROM Blueprint b WHERE BlueprintClassId IN (2,10)
                  AND (Lootable=1 OR EXISTS (SELECT 1 FROM MissionLoot l
                       WHERE l.LootTypeId=1 AND l.LootKey=b.BlueprintId))
                UNION SELECT Armor FROM PetPrebuilt
                UNION SELECT ConditionValue3 FROM BlockCondition WHERE ConditionType='Equip'
            '''))
            expected &= {r['ArmorId'] for r in source.read('ArmorModel')[1]}
            actual = {r['id'] for p in pages for g in p['grids'] for r in g['rows']}
            self.assertEqual(actual, expected)
            for page in pages:
                grid = page['grids'][0]
                self.assertTrue(grid['dynamicColumns'])
                self.assertTrue(grid['scrollWithPage'])
                self.assertEqual(grid['defaultSort']['key'], 'column:Cost')
                self.assertIn('blueprintColumn', grid)
                for record in grid['rows']:
                    self.assertTrue(record['acquisition'])
                    self.assertEqual(pb.ARMOR_CLASSES[int(record['baseline']['ArmorClass'])], page['title'])
                    self.assertEqual(page['group'], 'Drone armors' if int(record['baseline']['ArmorClass'])
                                     in pb.DRONE_ARMOR_CLASSES else 'Armor')

    def test_intrinsics_follow_effective_pointers_and_preserve_shared_targets(self):
        with tempfile.TemporaryDirectory() as config:
            doc = pb.empty()
            doc['tables'] = {'Armor': {'7': {'ArmorEffectId': '56049'}}}
            model = pb.catalog(config, static_data.DEFAULT_DB, doc)
            self.assertIsNone(model['error'])
            rows = {r['id']:r for p in model['pages'] if p['group'] == 'Armor'
                    for g in p['grids'] for r in g['rows']}
            self.assertEqual(rows['7']['targets']['Intrinsic mods.WoundRes']['id'], '56049')
            self.assertEqual(rows['8']['targets']['Intrinsic mods.WoundRes']['id'], '56049')
            self.assertIn(rows['8']['name'], rows['7']['targets']['Intrinsic mods.WoundRes']['sharedWith'])
            self.assertNotIn('Intrinsic mods.WoundRes', rows['5']['targets'])
            doc['tables']['Armor']['7']['ArmorEffectId'] = '999999'
            self.assertIn('missing Effect 999999', pb.catalog(config, static_data.DEFAULT_DB, doc)['error'])

    def test_armor_and_intrinsic_edits_export_and_clear_by_original_identity(self):
        with static_data.StaticData() as source:
            doc = pb.apply_edits(pb.empty(), {'cells': [
                {'table':'Armor', 'id':'7', 'column':'BallisticArmor', 'value':'0'},
                {'table':'Effect', 'id':'56048', 'column':'WoundRes', 'value':'+2'}]}, source)
            statements, touched = pb.sql(doc, source)
            self.assertEqual(touched, {('Armor','7','BallisticArmor'), ('Effect','56048','WoundRes')})
            memory = sqlite3.connect(':memory:')
            try:
                source.connection.backup(memory)
                before = memory.execute('SELECT WoundRes FROM Effect WHERE EffectId=56048').fetchone()[0]
                memory.executescript('\n'.join(statements))
                self.assertEqual(memory.execute('SELECT BallisticArmor FROM Armor WHERE ArmorId=7').fetchone()[0], 0)
                self.assertEqual(memory.execute('SELECT WoundRes FROM Effect WHERE EffectId=56048').fetchone()[0], round(before)+2)
            finally:
                memory.close()
            self.assertEqual(pb.apply_edits(doc, {'cells':[]}, source), doc)
            cleared = pb.apply_edits(doc, {'cells': [
                {'table':'Armor', 'id':'7', 'column':'BallisticArmor', 'value':''},
                {'table':'Effect', 'id':'56048', 'column':'WoundRes', 'value':''}]}, source)
            self.assertEqual(cleared, pb.empty())

    def test_unavailable_armor_overrides_remain_editable_until_cleared(self):
        with tempfile.TemporaryDirectory() as config, static_data.StaticData() as source:
            acquired = pb.player_gear_references(source)['Armor']
            armor = next(r for r in source.read('ArmorModel')[1] if r['ArmorId'] not in acquired)
            doc = pb.empty()
            doc['tables'] = {'Armor': {armor['ArmorId']: {'Cost':'0'}}}
            model = pb.catalog(config, source.path, doc)
            page = next(p for p in model['pages'] if p['id'] == 'other-armor-overrides')
            self.assertIn(armor['ArmorId'], {r['id'] for g in page['grids'] for r in g['rows']})
            doc = pb.apply_edits(doc, {'cells':[{'table':'Armor','id':armor['ArmorId'],'column':'Cost','value':''}]}, source)
            self.assertNotIn('other-armor-overrides', {p['id'] for p in pb.catalog(config, source.path, doc)['pages']})


UI = r'''
setTimeout(function() {
 let passed=0;function ck(name,ok) {if(!ok) throw new Error(name);passed++;console.log('PASS '+name);}
 SEL='pb:armor-1';render();
 const panel=$('#panel'), find=fn=>panel.find(fn);
 ck('armor pages have their own navigation group', MODEL.playerBalance.pages.filter(p=>p.group==='Armor').slice(0,3).map(p=>p.title).join(',')==='Stealth,Light,Heavy');
 ck('armor has weapon-style service and blueprint columns', find(n=>n._cls().includes('pb-service')).length>0 && find(n=>n._cls().includes('pb-blueprint')).length>0);
 ck('armor has sort controls', find(n=>n.getAttribute('aria-label')==='Sort by Light · Light').length===1);
 const input=find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='Effect 56048.WoundRes')[0];
 ck('intrinsic bonuses are editable beside armor stats', !!input);
 const old=input.value;input.value='7';input.fire('input');
 ck('intrinsic edits keep their Effect identity', buildEdits().playerBalance.cells.some(c=>c.table==='Effect' && c.id==='56048' && c.column==='WoundRes'));
 input.value=old;input.fire('input');
 ck('restoring intrinsic values clears the pending edit', !playerChanges().cells.length);
 console.log('Player armor UI: '+passed+' passed');process.exit(0);
},0);
'''


if __name__ == '__main__':
    if '--ui' in sys.argv:
        import serve
        sys.exit(serve.selftest_dom(serve.App(serve.load_settings(), 'test').api_model(), UI))
    unittest.main()
