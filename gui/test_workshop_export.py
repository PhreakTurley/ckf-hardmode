"""The main Workshop action updates every configured mod and reports partial failures."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import serve


class WorkshopExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config = self.root / 'config'
        self.config.mkdir()
        self.settings = {'configDirOverride': str(self.config), 'talentProjectDir': str(self.root / 'talents'),
                         'enemySourceDir': str(self.root), 'officialDataPath': str(self.root / 'data.db')}
        self.keys = ('modkitProjectDir', 'enemyModkitProjectDir', 'partySizeProjectDir', 'contactBreaksProjectDir',
                     'hireEveryoneProjectDir')
        ids = []
        for index, key in enumerate(self.keys, 1):
            project = self.root / 'uploader/WorkshopContent' / key
            (project / 'upload_content').mkdir(parents=True)
            installed = self.root / 'steamapps/workshop/content/1021210' / str(index)
            installed.mkdir(parents=True)
            (project.parent / (project.name + '.workshop.json')).write_text(json.dumps(
                {'publishedfileid': str(index), 'steamModFolder': str(installed)}))
            self.settings[key] = str(project)
            ids.append('"%d" { "size" "1" }' % index)
        self.registration = self.root / 'steamapps/workshop/appworkshop_1021210.acf'
        self.registration.write_text('"AppWorkshop" { "appid" "1021210" "WorkshopItemsInstalled" { '
                                     + ' '.join(ids) + ' } }')
        self.app = serve.App(self.settings, 'test', static_source=False)
        self.baseline = self.app.current_fingerprints(str(self.config))
        self.addCleanup(patch.stopall)
        self.check = patch.object(serve, 'run_check_schema', return_value={'ran': True, 'problems': []}).start()
        self.senders = [patch.object(module, name, return_value={
            'ok': True, 'written': [key], 'installedDir': 'installed-' + key}).start()
            for module, name, key in ((serve.modkit, 'send', 'player'), (serve.enemy_armor, 'prepare', 'enemy'),
                                      (serve.party_size, 'send', 'party'), (serve.contact_limit_breaks, 'send', 'contacts'),
                                      (serve.build_hire_everyone, 'send', 'hire'))]

    def test_main_export_updates_all_configured_mods_with_their_own_destinations(self):
        result = self.app.api_workshop_export(self.baseline)
        self.assertTrue(result['ok'], result)
        self.assertEqual([r['id'] for r in result['mods']], ['player', 'enemy', 'party', 'contacts', 'hire'])
        self.assertEqual(result['written'], ['player', 'enemy', 'party', 'contacts', 'hire'])
        for sender, key in zip(self.senders, self.keys):
            sender.assert_called_once()
            self.assertIn(self.settings[key], tuple(str(arg) for arg in sender.call_args.args))
        self.assertEqual(self.senders[2].call_args.args[-1], self.baseline)
        self.assertEqual(self.senders[3].call_args.args[-1], self.baseline)
        self.assertEqual(self.senders[4].call_args.args[-1], self.baseline)

    def test_existing_projects_can_export_without_a_hire_everyone_project(self):
        self.settings.pop('hireEveryoneProjectDir')
        result = self.app.api_workshop_export(self.baseline)
        self.assertTrue(result['ok'], result)
        self.assertEqual(result['written'], ['player', 'enemy', 'party', 'contacts'])
        self.senders[4].assert_not_called()

    def test_failure_reports_successful_mods_and_still_attempts_independent_mods(self):
        self.senders[1].side_effect = ValueError('enemy parser refused')
        result = self.app.api_workshop_export(self.baseline)
        self.assertFalse(result['ok'])
        self.assertEqual([r['ok'] for r in result['mods']], [True, False, True, True, True])
        self.assertIn('enemy parser refused', result['mods'][1]['error'])
        self.assertEqual(result['written'], ['player', 'party', 'contacts', 'hire'])
        self.assertTrue(all(sender.call_count == 1 for sender in self.senders))

    def test_stale_config_and_invalid_schema_refuse_all_exports(self):
        for expected, check in (({}, {'ran': True, 'problems': []}),
                                (self.baseline, {'ran': False, 'problems': []})):
            self.check.return_value = check
            result = self.app.api_workshop_export(expected)
            self.assertFalse(result['ok'], result)
            self.assertFalse(result['mods'])
        self.assertTrue(all(not sender.called for sender in self.senders))

    def test_missing_or_duplicate_destinations_refuse_every_write(self):
        for value in ('', self.settings[self.keys[0]]):
            self.settings[self.keys[1]] = value
            result = self.app.api_workshop_export(self.baseline)
            self.assertFalse(result['ok'], result)
            self.assertFalse(result['mods'])
            self.assertTrue(all(not sender.called for sender in self.senders))

    def test_destination_change_after_an_export_blocks_remaining_writes(self):
        def changed(*_):
            self.registration.write_text(self.registration.read_text() + '\n')
            return {'ok': True, 'written': ['player']}
        self.senders[0].side_effect = changed
        result = self.app.api_workshop_export(self.baseline)
        self.assertEqual([r['ok'] for r in result['mods']], [True, False, False, False, False])
        self.assertTrue(all(not sender.called for sender in self.senders[1:]))

    def test_tuning_change_after_an_export_blocks_remaining_writes(self):
        def changed(*_):
            (self.config / serve.enemy_rules.FILE).write_bytes(b'{}')
            return {'ok': True, 'written': ['player']}
        self.senders[0].side_effect = changed
        result = self.app.api_workshop_export(self.baseline)
        self.assertEqual([r['ok'] for r in result['mods']], [True, False, False, False, False])
        self.assertTrue(all(not sender.called for sender in self.senders[1:]))


class EnemyPointerContractTests(unittest.TestCase):
    def data_with_extra_column(self, table):
        import export_enemy_difficulty as enemy
        reader = enemy.StaticData

        class ExtendedData:
            def __init__(self, *args, **kwargs):
                self.original = reader(*args, **kwargs)

            def __enter__(self):
                self.original.__enter__()
                self.schema = dict(self.original.schema)
                self.schema[table] = self.schema[table] + [(999, 'FixtureNewOfficialColumn', 'INTEGER', 0, '0', 0)]
                return self

            def __exit__(self, *args):
                return self.original.__exit__(*args)

            def __getattr__(self, name):
                return getattr(self.original, name)

        return ExtendedData

    def test_new_read_only_effect_columns_do_not_change_the_enemy_payload(self):
        import export_enemy_difficulty as enemy
        baseline, _ = enemy.build()
        with patch.object(enemy, 'StaticData', self.data_with_extra_column('Effect')):
            extended, _ = enemy.build()
        for path in ('source_content/enemy-difficulty.json', 'prepared/_data/data.sql',
                     'prepared/_data/en-US.json', 'review/column-ledger.csv'):
            self.assertEqual(extended[path], baseline[path], path)

    def test_written_table_column_disagreement_still_refuses_export(self):
        import export_enemy_difficulty as enemy
        with patch.object(enemy, 'StaticData', self.data_with_extra_column('Armor')):
            with self.assertRaisesRegex(ValueError, 'Parser/official SQL column disagreement: Armor'):
                enemy.build()


UI = r'''
setTimeout(async function() {
  let passed=0;function ck(name,ok) {if(!ok) throw new Error(name);passed++;console.log('PASS '+name);}
  const calls=[];let failEnemy=false;
  api=async function(path,body) {
    calls.push({path:path,body:body});
    return {ok:!failEnemy,mods:['Player Balance','Enemy Difficulty','Party Size Mod','Faster Contact Limit Breaks','Hire Everyone Mod'].map((title,index)=>
      ({title:title,ok:!(failEnemy && index===1),error:'enemy fixture refused'})),next:'Restart the game to test.'};
  };
  const button=$('#send-talents');
  await button.listeners.click[0]();
  ck('main button calls the combined export with current fingerprints', calls.length===1 && calls[0].path==='/api/workshop-export'
    && CKF.deepEqual(calls[0].body.fingerprints,MODEL.fingerprints));
  const status=$('#modkit-status');
  ck('success lists all installed mods', ['Player Balance','Enemy Difficulty','Party Size Mod','Faster Contact Limit Breaks','Hire Everyone Mod'].every(title=>
    status.textContent.includes(title+': prepared and installed locally.')));
  failEnemy=true;await button.listeners.click[0]();
  ck('partial failure names the failed mod and preserves success receipts', status.textContent.includes('Enemy Difficulty: failed: enemy fixture refused')
    && status.textContent.includes('Player Balance: prepared and installed locally.') && status.textContent.includes('finished with failures'));
  ck('button is re-enabled after the export', !button.disabled);
  console.log('Workshop export UI: '+passed+' passed');process.exit(0);
},0);
'''


if __name__ == '__main__':
    if '--ui' in sys.argv:
        sys.exit(serve.selftest_dom(serve.App(serve.load_settings(), 'test').api_model(), UI))
    unittest.main()
