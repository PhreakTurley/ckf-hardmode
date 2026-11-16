"""Enemy rule ownership, Validate/Save transactions and UI routing."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import sys
import unittest

import serve
import enemy_rules
import player_balance as pb
import static_data
import test_override_validation


class EnemyRuleTests(unittest.TestCase):
    setUp = test_override_validation.OverrideValidationTests.setUp
    snapshot = test_override_validation.OverrideValidationTests.snapshot

    def prepare(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript('CREATE TABLE Rule (RuleId INTEGER PRIMARY KEY, ConfigName TEXT, Value INTEGER);'
                             "INSERT INTO Rule VALUES (82,'Max Enemy Power Level',14);")
        self.path = self.config / enemy_rules.FILE
        self.original = {'format': 1, 'basis': {'fixture': 'preserve'}, 'clones': [],
                         'updates': [{'table': 'Weapon', 'id': 1, 'set': {'Accuracy1': 76}}],
                         'rules': {'82': {'Value': 20}}}
        self.path.write_text(json.dumps(self.original))

    def change(self, value):
        with static_data.StaticData(self.database) as source:
            digest = pb.identity(source)['sha256']
        return {'enemyRules': {'databaseSha': digest, 'cells': [{'id': '82', 'column': 'Value', 'value': value}]}}

    def test_authoritative_save_preserves_other_enemy_authoring(self):
        self.prepare()
        before = self.path.read_bytes()
        change = self.change('19')
        validated = self.app.api_validate(change)
        self.assertTrue(validated['ok'], validated)
        self.assertIn(enemy_rules.FILE, validated['wouldWrite'])
        self.assertEqual(self.path.read_bytes(), before)
        saved = self.app.api_save(change)
        self.assertTrue(saved['ok'], saved)
        expected = {**self.original, 'rules': {'82': {'Value': 19}}}
        self.assertEqual(json.loads(self.path.read_bytes()), expected)
        self.assertFalse((self.config / pb.FILE).exists())

    def test_shipped_assignment_is_cleared_in_editor_then_saved(self):
        self.prepare()
        before = self.path.read_bytes()
        result = self.app.api_validate(self.change('14'))
        self.assertTrue(result['ok'], result)
        self.assertIn({'kind': 'enemyRule', 'id': '82', 'column': 'Value'}, result['cleared'])
        self.assertEqual(self.path.read_bytes(), before)
        saved = self.app.api_save(self.change('14'))
        self.assertTrue(saved['ok'], saved)
        self.assertEqual(json.loads(self.path.read_bytes()), {k: v for k, v in self.original.items() if k != 'rules'})
        self.assertEqual(enemy_rules.model(self.config, self.database)['values']['82']['Value'], '')

    def test_invalid_values_and_stale_data_never_write(self):
        self.prepare()
        before = self.path.read_bytes()
        for value in ('1.5', '+10', 'x2', 'NaN', '9223372036854775808'):
            for method in (self.app.api_validate, self.app.api_save):
                result = method(self.change(value))
                self.assertFalse(result['ok'], result)
                self.assertEqual(self.path.read_bytes(), before)
        change = self.change('19')
        change['enemyRules']['databaseSha'] = 'stale'
        self.assertFalse(self.app.api_save(change)['ok'])
        self.assertEqual(self.path.read_bytes(), before)

    def test_external_enemy_edits_are_guarded(self):
        self.prepare()
        fingerprints = self.app.current_fingerprints(str(self.config))
        self.assertIn(enemy_rules.FILE, fingerprints)
        external = self.path.read_bytes() + b'\n'
        self.path.write_bytes(external)
        refused = self.app.api_save(self.change('19'), expect=fingerprints)
        self.assertFalse(refused['ok'])
        self.assertIn(enemy_rules.FILE, refused['stale'])
        self.assertEqual(self.path.read_bytes(), external)


UI = r'''
setTimeout(function() {
 let passed=0;function ck(name,ok) {if(!ok) throw new Error(name);passed++;console.log('PASS '+name);}
 SEL='pb:enemy-balance-rules';render();
 const page=MODEL.playerBalance.pages.find(p=>p.id==='enemy-balance-rules');
 ck('enemy rules retain their own heading', page.title==='Rules' && page.owner==='enemy-balance');
 const input=$('#panel').find(n=>n.attrs['data-player-target']==='Rule 82.Value')[0];
 ck('authoritative rule has an editable integer control', input && input.attrs.type==='number' && input.attrs.step==='1');
 ck('control reads the Enemy Balance authoring value', input.value===MODEL.enemyRules.values['82'].Value);
 ck('baseline remains the shipped value', input.attrs.placeholder===page.grids[0].rows[0].baseline.Value);
 input.value='19';input.fire('input');
 let edits=buildEdits();
 ck('rule input routes to Enemy Balance', edits.enemyRules.cells.some(c=>c.id==='82' && c.column==='Value' && c.value==='19'));
 ck('rule input never writes Player Balance', !edits.playerBalance);
 ck('enemy rules participate in unsaved-change detection', dirtyPaths().some(p=>p==='Enemy rule 82.Value'));
 applyOverrideClears([{kind:'enemyRule',id:'82',column:'Value'}]);
 ck('Validate clears the working rule override', W.enemyRules['82'].Value==='');
 ck('cleared rule is included in Save', buildEdits().enemyRules.cells.some(c=>c.value===''));
 ck('read-only ownership message is gone', !$('#panel').textContent.includes('Their read-only fields'));
 console.log('Enemy rule UI: '+passed+' passed');process.exit(0);
},0);
'''

if __name__ == '__main__':
    if '--ui' in sys.argv:
        sys.exit(serve.selftest_dom(serve.App(serve.load_settings(), 'test').api_model(), UI))
    unittest.main()
