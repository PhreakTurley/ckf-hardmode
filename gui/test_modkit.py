"""Player export prepares upload and local payloads as one guarded transaction."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import modkit
import steam_workshop


class PlayerExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config = self.root / 'config'
        self.live = self.config / 'ckf.hardmode.d'
        self.live.mkdir(parents=True)
        self.project = self.root / 'talents'
        self.mod = self.root / 'uploader/WorkshopContent/PlayerBalance'
        self.workshop = self.root / 'steamapps/workshop/content/1021210/3814427009'
        self.workshop.mkdir(parents=True)
        (self.mod / 'upload_content').mkdir(parents=True)
        self.metadata = self.mod.parent / 'PlayerBalance.workshop.json'
        self.meta = {'publishedfileid': '3814427009', 'steamModFolder': str(self.workshop)}
        self.metadata.write_text(json.dumps(self.meta))
        self.registration = self.workshop.parents[2] / 'appworkshop_1021210.acf'
        self.registration.write_text('"AppWorkshop" { "appid" "1021210" '
            '"WorkshopItemsInstalled" { "3814427009" { "size" "1" } } }')
        self.contract = self.mod.parent / 'config.json'
        self.contract.write_bytes(b'{}')
        for path, content in {
            self.project / 'scripts/export_talent_balance.py': b'# synthetic exporter',
            self.project / 'source_content/stories.manifest': b'talent-balance.json\n',
            self.live / 'native.csv': b'Id,Value\n1,5\n',
            self.config / 'ckf.hardmode.cfg': b'[General]\nEnabled = true\n',
            self.config / modkit.player_balance.FILE: b'{}',
            self.root / 'data.db': b'synthetic static identity',
        }.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        self.data = b'{"Rule":[{"RuleId":1,"Value":5,"SQL":"update"}]}'
        self.files = {'data.sql': b'\xef\xbb\xbfUPDATE Rule SET Value=5 WHERE RuleId=1;\r\n',
                      'en-US.json': b'{"test":"locale bytes"}\r\n'}
        self.exporter = SimpleNamespace(expected_files=lambda: [('native.csv', '', '')],
            validate_parser_source=lambda *_: None, build_export=self.build)
        self.addCleanup(patch.stopall)
        patch.object(modkit, 'load_exporter', return_value=self.exporter).start()
        patch.object(modkit.player_balance.static_data, 'database_path', return_value=self.root / 'data.db').start()
        patch.object(modkit.player_balance, 'augment', side_effect=lambda data, provenance, *_:
            (data, provenance, json.loads(provenance))).start()
        self.parser = patch.object(modkit, 'prepare_parser', return_value=(self.files, {})).start()

    def build(self, *_args, **_kwargs):
        metadata = {'parser_contract': {'sha256': modkit.state(self.contract)[2]},
                    'overlay_inputs': {'native.csv': {'sha256': modkit.state(self.live / 'native.csv')[2]}},
                    'switch_file': {'sha256': modkit.state(self.config / 'ckf.hardmode.cfg')[2]},
                    'parser_source': {'records': 1}, 'merged_update_records_by_table': {'Rule': 1}}
        return self.data, json.dumps(metadata).encode(), metadata

    def send(self):
        return modkit.send(self.config, self.project, self.mod, self.root / 'data.db')

    def snapshot(self):
        return {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def test_export_installs_exact_parser_bytes_and_preserves_other_files(self):
        extra = self.workshop / 'unrelated.txt'
        extra.write_bytes(b'keep')
        before = self.snapshot()
        result = self.send()
        self.assertTrue(result['ok'])
        self.assertEqual(result['installedDir'], str(self.workshop))
        for name, content in self.files.items():
            self.assertEqual((self.mod / 'upload_content/_data' / name).read_bytes(), content)
            self.assertEqual((self.workshop / '_data' / name).read_bytes(), content)
            self.assertEqual(result['files'][name], hashlib.sha256(content).hexdigest())
        self.assertEqual((self.mod / 'source_data/talent-balance.json').read_bytes(), self.data)
        for path, content in before.items():
            self.assertEqual(path.read_bytes(), content)
        first = self.snapshot()
        self.assertEqual(self.send()['written'], [])
        self.assertEqual(self.snapshot(), first)

    def test_unregistered_or_invalid_steam_manifest_refuses_every_write(self):
        for text in ('"AppWorkshop" { "WorkshopItemsInstalled" {} }',
                     '"AppWorkshop" { "WorkshopItemsInstalled" {',
                     'garbage "AppWorkshop" { "WorkshopItemsInstalled" { "3814427009" {} } }',
                     '"AppWorkshop" { "WorkshopItemsInstalled" { "3814427009" {} "3814427009" {} } }'):
            with self.subTest(text=text):
                self.registration.write_text(text)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.send()
                self.assertEqual(self.snapshot(), before)
                self.parser.assert_not_called()

    def test_mismatched_or_unconfigured_destination_is_refused(self):
        for changes in ({'publishedfileid': '0'}, {'steamModFolder': ''},
                        {'steamModFolder': 'relative/path'}, {'publishedfileid': '999'},
                        {'steamModFolder': str(self.root / 'workshop/content/999/3814427009')},
                        {'steamModFolder': str(self.root.anchor)}):
            with self.subTest(changes=changes):
                self.metadata.write_text(json.dumps(dict(self.meta, **changes)))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.send()
                self.assertEqual(self.snapshot(), before)

    def test_parser_failure_leaves_sources_upload_and_install_unchanged(self):
        before = self.snapshot()
        self.parser.side_effect = ValueError('parser rejected')
        with self.assertRaisesRegex(ValueError, 'parser rejected'):
            self.send()
        self.assertEqual(self.snapshot(), before)

    def test_changed_metadata_registration_or_tuning_refuses_transaction(self):
        for path in (self.metadata, self.registration, self.live / 'native.csv'):
            with self.subTest(path=path):
                original = path.read_bytes()
                def changed(*_):
                    path.write_bytes(original + b'\n')
                    return self.files, {}
                self.parser.side_effect = changed
                with self.assertRaisesRegex(ValueError, 'changed during export'):
                    self.send()
                self.assertFalse((self.mod / 'source_data/talent-balance.json').exists())
                self.assertFalse((self.workshop / '_data/data.sql').exists())
                path.write_bytes(original)

    def test_newer_installed_payload_is_preserved_and_no_sources_are_sent(self):
        dest = self.workshop / '_data/data.sql'
        dest.parent.mkdir()
        dest.write_bytes(b'old')
        def changed(*_):
            dest.write_bytes(b'newer independent install')
            return self.files, {}
        self.parser.side_effect = changed
        with self.assertRaisesRegex(ValueError, 'changed; send again'):
            self.send()
        self.assertEqual(dest.read_bytes(), b'newer independent install')
        self.assertFalse((self.mod / 'source_data/talent-balance.json').exists())

    def test_local_install_failure_rolls_back_all_completed_destinations(self):
        targets = [self.project / 'source_content/talent-balance.json',
                   self.mod / 'upload_content/_data/data.sql', self.workshop / '_data/data.sql']
        for dest in targets:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(b'previous ' + dest.name.encode())
        before = self.snapshot()
        replace = modkit.os.replace
        def fail_local_locale(source, dest):
            if Path(dest) == self.workshop / '_data/en-US.json':
                raise PermissionError('local install denied')
            return replace(source, dest)
        with patch.object(modkit.os, 'replace', side_effect=fail_local_locale):
            with self.assertRaisesRegex(PermissionError, 'local install denied'):
                self.send()
        self.assertEqual(self.snapshot(), before)


class InstalledParserTests(unittest.TestCase):
    def test_prepared_bytes_survive_temporary_directory_cleanup(self):
        engine = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader')
        if not (engine / 'CyberKnightsModkit_Data/Managed/DataParserNETStandard.dll').is_file() or not shutil.which('pwsh'):
            self.skipTest('Installed Modkit parser and PowerShell 7 unavailable')
        files, inputs = modkit.prepare_parser(
            b'{"Rule":[{"RuleId":83,"Value":6,"SQL":"update"}]}',
            engine / 'WorkshopContent/Unused', engine / 'WorkshopContent/config.json')
        self.assertEqual(files['data.sql'].decode('utf-8-sig').strip(), 'UPDATE Rule SET Value=6 WHERE RuleId=83;')
        self.assertEqual(json.loads(files['en-US.json']), {})
        self.assertTrue(all(modkit.state(path) == expected for path, expected in inputs.items()))

    def test_success_exit_without_complete_output_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('scripts/prepare_enemy_difficulty.ps1',
                         'CyberKnightsModkit_Data/Managed/DataParserNETStandard.dll', 'WorkshopContent/config.json'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b'fixture')
            with patch.object(sys, '_MEIPASS', str(root), create=True), \
                    patch.object(modkit.shutil, 'which', return_value='pwsh'), \
                    patch.object(modkit.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')):
                with self.assertRaisesRegex(ValueError, 'incomplete result'):
                    modkit.prepare_parser(b'{}', root / 'WorkshopContent/Unused', root / 'WorkshopContent/config.json')


if __name__ == '__main__':
    unittest.main()
