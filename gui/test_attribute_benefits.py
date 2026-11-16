"""Attribute benefit discovery, table identities, sparse export and UI controls."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

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
