"""Scope and stale-write checks for the standalone Party Size Mod."""
import json
from contextlib import closing
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import party_size
import modkit


def registered_project(root, project, itemid):
    workshop = root / 'workshop/content/1021210' / itemid
    workshop.mkdir(parents=True)
    (workshop.parents[2] / 'appworkshop_1021210.acf').write_text(
        '"AppWorkshop" { "WorkshopItemsInstalled" { ' +
        ' '.join('"%s" {}' % p.name for p in workshop.parent.iterdir()) + ' } }')
    metadata = project.parent / (project.name + '.workshop.json')
    metadata.write_text(json.dumps({'publishedfileid': itemid, 'steamModFolder': str(workshop)}))
    return workshop


class PartySizeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / 'config'
        self.config.mkdir()
        self.database = self.root / 'data.db'
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.executescript('CREATE TABLE Rule (RuleId INTEGER PRIMARY KEY, Value INTEGER, '
                             'ConfigName TEXT, ConfigDesc TEXT);'
                             "INSERT INTO Rule VALUES (83, 4, 'Mission Max MercDefault', 'Default mercs');"
                             "INSERT INTO Rule VALUES (82, 12, 'Other rule', 'Unrelated');"
                             'CREATE TABLE Weapon (RuleId INTEGER PRIMARY KEY, Value INTEGER);'
                             'INSERT INTO Weapon VALUES (83, 99);')
        self.project = self.root / 'WorkshopContent' / 'IncreasedPartySize'
        (self.project / 'upload_content').mkdir(parents=True)
        self.metadata = self.project.parent / 'IncreasedPartySize.workshop.json'
        self.workshop = registered_project(self.root, self.project, '1001')
        self.metadata_bytes = self.metadata.read_bytes()
        (self.project.parent / 'config.json').write_text(json.dumps({'Rule': {'sql': {
            'table': 'Rule', 'fields': [
                {'name': 'RuleId', 'type': 'INTEGER', 'primaryKey': True},
                {'name': 'Value', 'type': 'INTEGER'}]}}}))
        self.tuning = self.config / party_size.FILE
        self.tuning.write_bytes(party_size.encode({'format': 1, 'maximum': 6}))

    def send(self, **kwargs):
        return party_size.send(self.config, self.project, self.database, **kwargs)

    def test_export_contains_one_update_only(self):
        self.send()
        source = json.loads((self.project / 'source_data/party-size.json').read_bytes())
        self.assertEqual(source, {'Rule': [{'RuleId': 83, 'Value': 6, 'SQL': 'update'}]})
        self.assertEqual((self.project / 'source_data/stories.manifest').read_bytes(), b'party-size.json\n')
        self.assertEqual(self.metadata.read_bytes(), self.metadata_bytes)
        for name in ('data.sql', 'en-US.json'):
            self.assertEqual((self.project / 'upload_content/_data' / name).read_bytes(),
                             (self.workshop / '_data' / name).read_bytes())

    def test_only_the_declared_identity_is_accepted(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute('DELETE FROM Rule WHERE RuleId=83')
        with self.assertRaisesRegex(ValueError, 'missing or renamed'):
            self.send()
        self.assertFalse((self.project / 'source_data').exists())

    def test_unregistered_local_target_refuses_sources_and_upload_together(self):
        manifest = self.workshop.parents[2] / 'appworkshop_1021210.acf'
        manifest.write_text('"AppWorkshop" { "WorkshopItemsInstalled" {} }')
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        with self.assertRaisesRegex(ValueError, 'Steam has not registered'):
            self.send()
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    def test_local_install_failure_rolls_back_sources_and_prepared_upload(self):
        from unittest.mock import patch
        self.send()
        self.tuning.write_bytes(party_size.encode({'format': 1, 'maximum': 7}))
        before = {p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        replace = modkit.os.replace
        def fail_local(source, destination):
            if Path(destination) == self.workshop / '_data/data.sql':
                raise PermissionError('local destination denied')
            return replace(source, destination)
        with patch.object(modkit.os, 'replace', side_effect=fail_local):
            with self.assertRaisesRegex(PermissionError, 'local destination denied'):
                self.send()
        self.assertEqual({p: p.read_bytes() for p in self.root.rglob('*') if p.is_file()}, before)

    def test_no_implicit_maximum_or_database_fallback(self):
        self.tuning.unlink()
        self.assertIsNone(party_size.load(self.config))
        with self.assertRaisesRegex(ValueError, 'Save Party Size Mod'):
            self.send()
        self.assertIsNotNone(party_size.model(self.config, self.root / 'missing.db')['error'])

    def test_invalid_and_overbroad_documents_are_refused(self):
        for maximum in (0, -1, 1.5, True, '6', None, 2147483648):
            with self.subTest(maximum=maximum), self.assertRaises(ValueError):
                party_size.validate({'format': 1, 'maximum': maximum})
        with self.assertRaises(ValueError):
            party_size.validate({'format': 1, 'maximum': 6, 'RuleId': 82})

    def test_other_mod_manifest_is_preserved(self):
        source = self.project / 'source_data'
        source.mkdir()
        (source / 'stories.manifest').write_bytes(b'other-mod.json\n')
        with self.assertRaisesRegex(ValueError, 'another mod manifest'):
            self.send()
        self.assertEqual((source / 'stories.manifest').read_bytes(), b'other-mod.json\n')

    def test_stale_browser_snapshot_is_refused(self):
        expected = {party_size.FILE: modkit.state(self.tuning)[2],
                    '@official-data.db': modkit.state(self.database)[2]}
        self.tuning.write_bytes(party_size.encode({'format': 1, 'maximum': 7}))
        with self.assertRaisesRegex(ValueError, 'changed on disk'):
            self.send(expect=expected)
        self.assertFalse((self.project / 'source_data').exists())

    def test_player_balance_cannot_export_the_party_rule(self):
        from unittest.mock import patch
        import player_balance
        import static_data
        document = player_balance.empty()
        document['tables'] = {'Rule': {'83': {'Value': '7'}}}
        with static_data.StaticData(self.database) as source:
            with patch.object(player_balance, 'protected_rows', return_value={}):
                with self.assertRaisesRegex(ValueError, 'belongs to Party Size Mod'):
                    player_balance.validate(document, source)

    def test_input_change_during_export_is_refused(self):
        from unittest.mock import patch
        original = party_size.source_bytes

        def moved(document):
            result = original(document)
            self.tuning.write_bytes(party_size.encode({'format': 1, 'maximum': 9}))
            return result

        with patch.object(party_size, 'source_bytes', moved):
            with self.assertRaisesRegex(ValueError, 'changed during export'):
                self.send()
        self.assertFalse((self.project / 'source_data/party-size.json').exists())

    def test_installed_parser_changes_exactly_one_field(self):
        installed = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader')
        if not installed.is_dir():
            self.skipTest('Installed official Data Parser unavailable')
        self.send()
        output = self.root / 'prepared'
        runner = Path(__file__).resolve().parents[1] / 'scripts/prepare_enemy_difficulty.ps1'
        subprocess.run(['pwsh', '-NoProfile', '-File', str(runner),
                        '-SourceContent', str(self.project / 'source_data'),
                        '-OutputDirectory', str(output), '-ModkitDirectory', str(installed)],
                       check=True, capture_output=True, text=True)
        sql = (output / 'data.sql').read_text(encoding='utf-8-sig')
        self.assertEqual(sql.strip(), 'UPDATE Rule SET Value=6 WHERE RuleId=83;')
        self.assertEqual(json.loads((output / 'en-US.json').read_bytes()), {})
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            for _ in range(2):
                db.executescript(sql)
                self.assertEqual(db.execute('SELECT * FROM Rule ORDER BY RuleId').fetchall(),
                                 [(82, 12, 'Other rule', 'Unrelated'),
                                  (83, 6, 'Mission Max MercDefault', 'Default mercs')])
                self.assertEqual(db.execute('SELECT * FROM Weapon').fetchall(), [(83, 99)])


if __name__ == '__main__':
    unittest.main()
