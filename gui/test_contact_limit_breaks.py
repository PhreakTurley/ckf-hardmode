"""Verify the contact mod targets only its declared rules and stays separate."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import contact_limit_breaks as contacts
import party_size
import modkit
from test_party_size import PartySizeTests


class ContactLimitBreakTests(unittest.TestCase):
    def setUp(self):
        PartySizeTests.setUp(self)
        self.party_project = self.project
        self.project = self.project.parent / 'FasterLimitBreaks'
        (self.project / 'upload_content').mkdir(parents=True)
        (self.project.parent / 'FasterLimitBreaks.workshop.json').write_text('{}')
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            for rid, value, name in [(84, 2, contacts.RULES[0][2]), (85, 15, contacts.RULES[1][2])]:
                db.execute('INSERT INTO Rule VALUES (?, ?, ?, ?)', (rid, value, name, 'Contact check turns'))
        self.contact_tuning = self.config / contacts.FILE
        self.contact_tuning.write_bytes(contacts.encode({'format': 1, 'minimum': 1, 'maximum': 1}))

    def send(self):
        return contacts.send(self.config, self.project, self.database)

    def test_two_scoped_updates_and_separate_destinations(self):
        party_size.send(self.config, self.party_project, self.database)
        old = (self.party_project / 'source_data/party-size.json').read_bytes()
        self.send()
        self.assertEqual(json.loads((self.project / 'source_data/contact-limit-breaks.json').read_bytes()),
                         {'Rule': [{'RuleId': 84, 'Value': 1, 'SQL': 'update'},
                                   {'RuleId': 85, 'Value': 1, 'SQL': 'update'}]})
        self.assertEqual((self.party_project / 'source_data/party-size.json').read_bytes(), old)
        with self.assertRaisesRegex(ValueError, 'another mod manifest'):
            contacts.send(self.config, self.party_project, self.database)

    def test_both_identities_are_required(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute('DELETE FROM Rule WHERE RuleId=85')
        with self.assertRaisesRegex(ValueError, 'missing or renamed'):
            self.send()
        self.assertFalse((self.project / 'source_data').exists())

    def test_invalid_and_reversed_turns_are_refused(self):
        for low, high in [(2, 1), (0, 1), (1, -1), (1.5, 2), (True, 2), (1, 2147483648)]:
            with self.subTest(low=low, high=high), self.assertRaises(ValueError):
                contacts.validate({'format': 1, 'minimum': low, 'maximum': high})

    def test_noop_save_preserves_both_documents_and_bytes(self):
        import serve
        app = serve.App({'configDirOverride': str(self.config)}, 'test', static_source=False)
        # Noncanonical whitespace must also survive a no-op.
        self.contact_tuning.write_bytes(b'{"maximum":1, "minimum":1, "format":1}\r\n')
        proposed = {}
        app.party_edits(str(self.config), {'partySize': party_size.load(self.config),
                                         'contactBreaks': contacts.load(self.config)}, proposed)
        self.assertEqual(set(proposed), {party_size.FILE, contacts.FILE})
        self.assertEqual(proposed[contacts.FILE], self.contact_tuning.read_bytes())
        self.assertEqual(proposed[party_size.FILE], self.tuning.read_bytes())

    def test_installed_parser_changes_only_the_two_rules(self):
        installed = Path(r'C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Mod Uploader')
        if not installed.is_dir():
            self.skipTest('Installed official Data Parser unavailable')
        self.send()
        output = self.root / 'prepared'
        runner = Path(__file__).resolve().parents[1] / 'scripts/prepare_enemy_difficulty.ps1'
        subprocess.run(['pwsh', '-NoProfile', '-File', str(runner), '-SourceContent', str(self.project / 'source_data'),
                        '-OutputDirectory', str(output), '-ModkitDirectory', str(installed)],
                       check=True, capture_output=True, text=True)
        sql = (output / 'data.sql').read_text(encoding='utf-8-sig')
        self.assertEqual(sql.splitlines(), ['UPDATE Rule SET Value=1 WHERE RuleId=84;',
                                           'UPDATE Rule SET Value=1 WHERE RuleId=85;'])
        self.assertEqual(json.loads((output / 'en-US.json').read_bytes()), {})
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            before = db.execute('SELECT * FROM Rule WHERE RuleId NOT IN (84,85)').fetchall()
            for _ in range(2):
                db.executescript(sql)
                self.assertEqual(db.execute('SELECT RuleId,Value FROM Rule WHERE RuleId IN (84,85) ORDER BY RuleId').fetchall(), [(84, 1), (85, 1)])
                self.assertEqual(db.execute('SELECT * FROM Rule WHERE RuleId NOT IN (84,85)').fetchall(), before)
                self.assertEqual(db.execute('SELECT * FROM Weapon').fetchall(), [(83, 99)])


if __name__ == '__main__':
    unittest.main(defaultTest='ContactLimitBreakTests')
