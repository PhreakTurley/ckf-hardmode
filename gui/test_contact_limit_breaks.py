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
            for rid, value, name in [(84, 2, contacts.RULES[0][2]), (85, 12, contacts.RULES[1][2]),
                                     (86, 15, contacts.RULES[2][2])]:
                db.execute('INSERT INTO Rule VALUES (?, ?, ?, ?)', (rid, value, name, 'Contact check turns'))
        self.contact_tuning = self.config / contacts.FILE
        self.contact_tuning.write_bytes(contacts.encode({'format': 1, 'minimum': 1, 'maximum': 1, 'readyThreshold': 15}))

    def send(self):
        return contacts.send(self.config, self.project, self.database)

    def test_three_scoped_updates_and_separate_destinations(self):
        party_size.send(self.config, self.party_project, self.database)
        old = (self.party_project / 'source_data/party-size.json').read_bytes()
        self.send()
        self.assertEqual(json.loads((self.project / 'source_data/contact-limit-breaks.json').read_bytes()),
                         {'Rule': [{'RuleId': 84, 'Value': 1, 'SQL': 'update'},
                                   {'RuleId': 85, 'Value': 1, 'SQL': 'update'},
                                   {'RuleId': 86, 'Value': 15, 'SQL': 'update'}]})
        self.assertEqual((self.party_project / 'source_data/party-size.json').read_bytes(), old)
        with self.assertRaisesRegex(ValueError, 'another mod manifest'):
            contacts.send(self.config, self.party_project, self.database)

    def test_all_identities_are_required(self):
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute('DELETE FROM Rule WHERE RuleId=86')
        with self.assertRaisesRegex(ValueError, 'missing or renamed'):
            self.send()
        self.assertFalse((self.project / 'source_data').exists())

    def test_reviewed_rule_names_accept_current_and_legacy_but_refuse_unknown(self):
        for names in ({rid: name for rid, _, name in contacts.RULES}, contacts.LEGACY_RULE_NAMES):
            with self.subTest(names=names), closing(sqlite3.connect(self.database, isolation_level=None)) as db:
                for rid, name in names.items():
                    db.execute('UPDATE Rule SET ConfigName=? WHERE RuleId=?', (name, rid))
                self.assertEqual([r['name'] for r in contacts.rules(self.database)],
                                 [names[84], names[85], contacts.RULES[2][2]])
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute("UPDATE Rule SET ConfigName='Unreviewed contact rule' WHERE RuleId=85")
        with self.assertRaisesRegex(ValueError, 'missing or renamed'):
            contacts.rules(self.database)

    def test_invalid_and_reversed_turns_are_refused(self):
        for low, high in [(2, 1), (0, 1), (1, -1), (1.5, 2), (True, 2), (1, 2147483648)]:
            with self.subTest(low=low, high=high), self.assertRaises(ValueError):
                contacts.validate({'format': 1, 'minimum': low, 'maximum': high, 'readyThreshold': 15})
        for threshold in (0, -1, 1.5, True, '15', None, 2147483648):
            with self.subTest(threshold=threshold), self.assertRaises(ValueError):
                contacts.validate({'format': 1, 'minimum': 1, 'maximum': 1, 'readyThreshold': threshold})

    def test_legacy_document_uses_selected_official_threshold_without_rewriting(self):
        import serve
        raw = b'{"maximum":1, "minimum":1, "format":1}\r\n'
        self.contact_tuning.write_bytes(raw)
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            db.execute('UPDATE Rule SET Value=23 WHERE RuleId=86')
        document = contacts.load(self.config, self.database)
        self.assertEqual(document['readyThreshold'], 23)
        self.assertEqual(self.contact_tuning.read_bytes(), raw)
        app = serve.App({'configDirOverride': str(self.config)}, 'test', static_source=str(self.database))
        proposed = {}
        app.party_edits(str(self.config), {'contactBreaks': document}, proposed)
        self.assertEqual(proposed[contacts.FILE], raw)
        self.send()
        self.assertEqual(json.loads((self.project / 'source_data/contact-limit-breaks.json').read_bytes())['Rule'][2],
                         {'RuleId': 86, 'Value': 23, 'SQL': 'update'})

    def test_threshold_cannot_enter_player_balance(self):
        from unittest.mock import patch
        import player_balance
        import static_data
        document = player_balance.empty()
        document['tables'] = {'Rule': {'86': {'Value': '7'}}}
        with static_data.StaticData(self.database) as source, patch.object(player_balance, 'protected_rows', return_value={}):
            with self.assertRaisesRegex(ValueError, 'belongs to Faster Contact Limit Breaks'):
                player_balance.validate(document, source)

    def test_noop_save_preserves_both_documents_and_bytes(self):
        import serve
        app = serve.App({'configDirOverride': str(self.config)}, 'test', static_source=False)
        # Noncanonical whitespace must also survive a no-op.
        self.contact_tuning.write_bytes(b'{"maximum":1, "minimum":1, "readyThreshold":15, "format":1}\r\n')
        proposed = {}
        app.party_edits(str(self.config), {'partySize': party_size.load(self.config),
                                         'contactBreaks': contacts.load(self.config)}, proposed)
        self.assertEqual(set(proposed), {party_size.FILE, contacts.FILE})
        self.assertEqual(proposed[contacts.FILE], self.contact_tuning.read_bytes())
        self.assertEqual(proposed[party_size.FILE], self.tuning.read_bytes())

    def test_installed_parser_changes_only_the_three_rules(self):
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
                                           'UPDATE Rule SET Value=1 WHERE RuleId=85;',
                                           'UPDATE Rule SET Value=15 WHERE RuleId=86;'])
        self.assertEqual(json.loads((output / 'en-US.json').read_bytes()), {})
        with closing(sqlite3.connect(self.database, isolation_level=None)) as db:
            before = db.execute('SELECT * FROM Rule WHERE RuleId NOT IN (84,85,86)').fetchall()
            for _ in range(2):
                db.executescript(sql)
                self.assertEqual(db.execute('SELECT RuleId,Value FROM Rule WHERE RuleId IN (84,85,86) ORDER BY RuleId').fetchall(), [(84, 1), (85, 1), (86, 15)])
                self.assertEqual(db.execute('SELECT * FROM Rule WHERE RuleId NOT IN (84,85,86)').fetchall(), before)
                self.assertEqual(db.execute('SELECT * FROM Weapon').fetchall(), [(83, 99)])


if __name__ == '__main__':
    unittest.main(defaultTest='ContactLimitBreakTests')
