"""Node removal repairs, shipped graph exemptions, and joined save identities."""
import copy
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

import serve
import talent_tree as tree


class Source:
    def __init__(self):
        self.jobs = [{'JobId': '1', 'Enabled': '1', 'JobName': 'Fixture',
                      'DefaultNode1': '100', 'DefaultNode2': '110',
                      'DefaultNode3': '0', 'DefaultNode4': '0'}]
        self.nodes = []
        for rid, req, subtree in [('100', '0', '0'), ('110', '100', '0'),
                                  ('111', '110', '110'), ('112', '111', '110'),
                                  ('113', '112', '110')]:
            self.nodes.append({'JobNodeId': rid, 'JobId': '1', 'SubTree': subtree,
                               'NodeReq1': req, 'NodeReq2': '0', 'NodeReq3': '0'})

    def read(self, table):
        return [], copy.deepcopy(self.jobs if table == 'JobModel' else self.nodes)


class TreeTests(unittest.TestCase):
    def setUp(self):
        self.source = Source()
        self.doc = serve.player_balance.empty()

    def test_reconnects_through_multiple_removed_upgrades(self):
        self.doc['removedJobNodes'] = ['111', '112']
        result = tree.validate(self.doc, self.source)
        self.assertEqual(result['repairs'], {'113': {'NodeReq1': '110'}})
        con = sqlite3.connect(':memory:')
        self.addCleanup(con.close)
        con.executescript('CREATE TABLE JobNode(JobNodeId INTEGER PRIMARY KEY, NodeReq1 INTEGER);'
                          'INSERT INTO JobNode VALUES(111,110),(112,111),(113,112);')
        con.executescript('\n'.join(tree.sql(self.doc, self.source)))
        self.assertEqual(con.execute('SELECT * FROM JobNode').fetchall(), [(113, 110)])

    def test_base_talents_are_protected(self):
        self.doc['removedJobNodes'] = ['110']
        with self.assertRaisesRegex(ValueError, 'Only upgrade nodes'):
            tree.validate(self.doc, self.source)

    def test_new_disconnection_is_rejected(self):
        self.doc['tables']['JobNode'] = {'111': {'NodeReq1': '113'}}
        with self.assertRaisesRegex(ValueError, 'unreachable JobNodes 111, 112, 113'):
            tree.validate(self.doc, self.source)

    def test_new_dangling_pointer_is_rejected(self):
        self.doc['tables']['JobNode'] = {'111': {'NodeReq1': '999'}}
        with self.assertRaisesRegex(ValueError, 'points outside'):
            tree.validate(self.doc, self.source)

    def test_shipped_disconnections_are_exempt_but_new_ones_are_not(self):
        self.source.nodes += [dict(self.source.nodes[-1], JobNodeId='150', NodeReq1='151'),
                              dict(self.source.nodes[-1], JobNodeId='151', NodeReq1='150')]
        tree.validate(self.doc, self.source)
        self.doc['tables']['JobNode'] = {'111': {'NodeReq1': '150'}}
        with self.assertRaisesRegex(ValueError, 'unreachable JobNodes 111, 112, 113'):
            tree.validate(self.doc, self.source)

    def test_repairs_do_not_drop_alternative_requirements(self):
        self.source.nodes[2]['NodeReq2'] = '100'
        self.doc['removedJobNodes'] = ['111']
        result = tree.validate(self.doc, self.source)
        self.assertEqual(result['repairs']['112'], {'NodeReq1': '110', 'NodeReq2': '100'})

    def test_cannot_silently_truncate_more_than_three_requirements(self):
        self.source.nodes[2].update(NodeReq2='100', NodeReq3='112')
        self.source.nodes[-1].update(NodeReq1='111', NodeReq2='113')
        self.doc['removedJobNodes'] = ['111']
        with self.assertRaisesRegex(ValueError, 'more than three prerequisites'):
            tree.plan(self.doc, self.source)


class FieldTests(unittest.TestCase):
    def test_missing_maintainer_database_keeps_unrelated_hardmode_editing_available(self):
        with tempfile.TemporaryDirectory() as folder:
            app = serve.App({'officialDataPath': str(Path(folder) / 'missing.db')}, 'test')
            app.validate_talent_tree(folder, {'ckf.hardmode.cfg': b'fixture'})
            with self.assertRaises(serve.SaveRefused):
                app.validate_talent_tree(folder, {'ckf.hardmode.d/JobNodeModel.sol.csv': b'fixture'})

    def test_icon_fields_and_effect_pointers_export_with_their_native_ids(self):
        pb = serve.player_balance
        with serve.static_data.StaticData() as source:
            doc = pb.apply_edits(pb.empty(), {'cells': [
                {'table': 'JobNode', 'id': '7021', 'column': 'IconPng', 'value': 'Strength'},
                {'table': 'JobNode', 'id': '7021', 'column': 'NodeEffect1Id', 'value': '800'},
            ]}, source)
            statements, touched = pb.sql(doc, source)
            self.assertIn(('JobNode', '7021', 'IconPng'), touched)
            self.assertTrue(any('"IconPng"=\'Strength\'' in s and '"JobNodeId"=7021' in s for s in statements))
            with self.assertRaisesRegex(ValueError, 'missing Effect'):
                pb.apply_edits(doc, {'cells': [
                    {'table': 'JobNode', 'id': '7021', 'column': 'NodeEffect1Id', 'value': '999999999'}]}, source)
            for table in ('Effect', 'MatrixEffect'):
                rows = source.read(table + 'Model')[1]
                icon = next(r['IconAsset'] for r in rows if r['IconAsset'])
                doc = pb.apply_edits(doc, {'cells': [
                    {'table': table, 'id': rows[0][pb.TABLE_KEYS[table]], 'column': 'IconAsset', 'value': icon}]}, source)
            pb.sql(doc, source)

    def test_explicit_node_icon_overrides_only_derived_attribute_icon(self):
        pb = serve.player_balance
        with tempfile.TemporaryDirectory() as folder:
            doc = pb.empty()
            doc['tables']['JobNode'] = {'7400': {'IconPng': 'Strength'}}
            (Path(folder) / pb.FILE).write_bytes(pb.encode(doc))
            payload = {'JobNode': [{'JobNodeId': 7400, 'Icon': 'Tech', 'SQL': 'update'}]}
            receipt = {'parser_source': {}, 'automatic_attribute_icons': [
                {'node_id': 7400, 'icon': 'Tech', 'previous_icon_override': None}]}
            data, _, result = pb.augment(pb.encode(payload), pb.encode(receipt), folder, serve.static_data.DEFAULT_DB)
            self.assertNotIn('Icon', json.loads(data)['JobNode'][0])
            self.assertEqual(result['manual_attribute_icon_nodes'], ['7400'])
            receipt['automatic_attribute_icons'][0]['previous_icon_override'] = 'Will'
            with self.assertRaisesRegex(ValueError, 'both own'):
                pb.augment(pb.encode(payload), pb.encode(receipt), folder, serve.static_data.DEFAULT_DB)


UI = r'''
setTimeout(function() {
 let passed=0;
 function ck(name, ok) {if(!ok) throw new Error(name);passed++;console.log('PASS '+name);}
 const schema=MODEL.schemas.find(s=>s.subsystem==='TalentsSoldier');
 SEL=MODEL.sections.find(s=>s.subsystems.includes(schema.subsystem)).id;render();
 const panel=$('#panel'), find=fn=>panel.find(fn);
 const before=JSON.stringify(buildEdits());
 const rows=()=>find(n=>n.tagName==='TR' && n.getAttribute('data-player-row')==='JobNode 7021');
 ck('talent and node fields share one row', rows()[0].find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='JobNode 7021.BuyCost').length===1
   && rows()[0].find(n=>n.tagName==='INPUT' && /^Talent /.test(n.getAttribute('data-player-target')||'')).length>0);
 ck('talent grids scroll with the page', find(n=>n._cls().includes('grid-wrap')).every(n=>n._cls().includes('page-grid-wrap')));
 ck('base talents cannot be removed', !find(n=>n.tagName==='BUTTON' && n.getAttribute('aria-label')==='Remove Job Node 7020').length);
 ck('upgrade removal is available', find(n=>n.tagName==='BUTTON' && n.getAttribute('aria-label')==='Remove Job Node 7021').length===1);
 ck('icons and effect pointers have choices', ['JobNode 7021.IconPng','JobNode 7021.NodeEffect1Id'].every(target=>
   find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')===target && n.getAttribute('list')).length>0));
 const all=find(n=>n.tagName==='INPUT' && n.type==='checkbox' && !n.getAttribute('aria-label'))[0];
 const count=find(n=>n.tagName==='TH').length;all.checked=true;all.fire('change');
 ck('show all exposes advanced fields', find(n=>n.tagName==='TH').length>count);
 ck('view options never create edits', JSON.stringify(buildEdits())===before);
 const node=find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='JobNode 7021.BuyCost')[0];
 const was=node.value;node.value=was==='17'?'18':'17';node.fire('input');
 ck('joined node edit keeps its native sheet identity', Object.values(buildEdits().overlays).some(b=>b.cells.some(c=>c.key[0]==='7021' && c.column==='BuyCost')));
 node.value=was;node.fire('input');
 const icon=find(n=>n.tagName==='INPUT' && n.getAttribute('data-player-target')==='JobNode 7021.IconPng')[0];
 const oldIcon=icon.value;icon.value='Strength';icon.fire('input');
 ck('new icon edit keeps its table and id', buildEdits().playerBalance.cells.some(c=>c.table==='JobNode' && c.id==='7021' && c.column==='IconPng'));
 icon.value=oldIcon;icon.fire('input');
 find(n=>n.tagName==='BUTTON' && n.getAttribute('aria-label')==='Remove Job Node 7021')[0].fire('click');
 ck('removal preserves the surviving upgrade rows', !rows().length && find(n=>n.getAttribute('data-player-row')==='JobNode 7022').length>0);
 ck('removal reaches the save payload', buildEdits().playerBalance.removedJobNodes.includes('7021'));
 find(n=>n.tagName==='BUTTON' && n.getAttribute('data-restore-node')==='7021')[0].fire('click');
 ck('restore returns the untouched save payload', JSON.stringify(buildEdits())===before);
 const attr=MODEL.talentBalance.pages.sol.grids.find(g=>g.title==='Attributes');
 ck('extra item carry is at the bottom of attributes', attr.rows.slice(-3).map(r=>r.id).join(',')==='7500,7501,7502');
 ck('editing help follows every grid', panel.children[panel.children.length-1]._cls().includes('page-instructions'));
 console.log('Talent UI: '+passed+' passed');process.exit(0);
},0);
'''


if __name__ == '__main__':
    if '--ui' in sys.argv:
        model = serve.App(serve.load_settings(), 'test-token').api_model()
        sys.exit(serve.selftest_dom(model, UI))
    unittest.main()
