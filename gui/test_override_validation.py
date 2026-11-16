"""Official type checks and redundant overrides across Validate and Save."""
from contextlib import closing
import csv
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import serve
import static_data
import player_balance as pb


class OverrideValidationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.config = self.root / 'config'
        self.sheet = self.config / 'ckf.hardmode.d/EffectModel.fixture.csv'
        self.sheet.parent.mkdir(parents=True)
        self.sheet.write_bytes(b'# keep this comment\r\nEffectId,Heals,MoveSpeed,_clone,_comment,_shipped\r\n'
            b'1,10,1.5,,keep,"{""Heals"":99}"\r\n2,777,,,keep,"{""Heals"":777}"\r\n900001,10,,1,clone,\r\n')
        (self.config / 'ckf.hardmode.cfg').write_bytes(b'[General]\r\nEnabled = true\r\n')
        self.database = self.root / 'data.db'
        with closing(sqlite3.connect(self.database)) as db:
            db.executescript('CREATE TABLE Effect (EffectId INTEGER PRIMARY KEY, Heals INTEGER, MoveSpeed REAL);'
                             'INSERT INTO Effect VALUES (1,10,1.5),(2,20,2);'
                             'CREATE TABLE Weapon (WeaponId INTEGER PRIMARY KEY, Cost INTEGER, WeaponClass INTEGER);'
                             'INSERT INTO Weapon VALUES (1,99,3),(2,-5,3);'
                             'CREATE TABLE JobNode (JobNodeId INTEGER PRIMARY KEY, IconPng TEXT);'
                             "INSERT INTO JobNode VALUES (1,'original'),(2,'other');"
                             'CREATE TABLE Armor (ArmorId INTEGER PRIMARY KEY, BallisticArmor INTEGER);'
                             'INSERT INTO Armor VALUES (1,45);')
        self.app = serve.App({'gameDir': '', 'configDirOverride': str(self.config), 'stripReadme': False},
                             'test', static_source=str(self.database))
        self.app.schemas = []
        self.addCleanup(patch.stopall)
        patch.object(self.app, 'snapshot', side_effect=self.snapshot).start()
        patch.object(self.app, 'validate_talent_tree').start()
        patch.object(self.app, 'validate_enemy_armor').start()
        # These tests isolate content validation and transaction behavior. The
        # unchanged configuration-schema checker has its own editor suite.
        patch.object(serve, 'stage_and_validate', return_value={'ran': True, 'problems': []}).start()
        patch.object(serve, 'run_check_schema', return_value={'ran': True, 'problems': []}).start()

    def snapshot(self):
        doc = serve.Document(str(self.config), [])
        doc.cfg = serve.CfgFile((self.config / 'ckf.hardmode.cfg').read_bytes())
        with static_data.StaticData(self.database) as source:
            for path in self.sheet.parent.glob('*.csv'):
                rel = str(path.relative_to(self.config)).replace('\\', '/')
                doc.overlays[rel] = serve.read_overlay(path, rel, source)
                doc.overlay_raw[rel] = path.read_bytes()
        model, extras = serve.build_model(doc)
        return doc, model, extras, str(self.config), {}

    def edit(self, value, column='Heals'):
        return {'overlays': {'ckf.hardmode.d/EffectModel.fixture.csv': {'cells': [
            {'key': ['1'], 'column': column, 'value': value}]}}}

    def test_validate_reports_clears_without_writing_and_save_persists_them(self):
        before = self.sheet.read_bytes()
        result = self.app.api_validate({})
        self.assertTrue(result['ok'], result)
        self.assertEqual(self.sheet.read_bytes(), before)
        self.assertEqual({(c['key'][0], c['column']) for c in result['cleared']},
                         {('1', 'Heals'), ('1', 'MoveSpeed')})
        self.assertFalse(any('NOT VALIDATED AGAINST A SCHEMA' in n for n in result['notes']))
        saved = self.app.api_save({})
        self.assertTrue(saved['ok'], saved)
        self.assertEqual(self.sheet.read_bytes(), before.replace(b'1,10,1.5,,keep,', b'1,,,,keep,'))
        again = self.app.api_save({})
        self.assertTrue(again['ok'], again)
        self.assertEqual(again['written'], [])

    def test_pending_defaults_use_official_rows_and_ignore_stale_sheet_metadata(self):
        for value in ('10.0', '1e1'):
            result = self.app.api_validate(self.edit(value))
            self.assertTrue(result['ok'], result)
            self.assertTrue(any(c['column'] == 'Heals' for c in result['cleared']))
        result = self.app.api_validate(self.edit('11'))
        self.assertTrue(result['ok'], result)
        self.assertFalse(any(c['column'] == 'Heals' for c in result['cleared']))
        self.assertFalse(any(c['key'][0] == '900001' for c in result['cleared']))

    def test_numeric_types_and_nonfinite_values_are_blocked_before_any_write(self):
        before = self.sheet.read_bytes()
        for value in ('nonsense', 'NaN', 'Infinity', '1e400', '9223372036854775808'):
            for method in (self.app.api_validate, self.app.api_save):
                with self.subTest(value=value, method=method.__name__):
                    result = method(self.edit(value))
                    self.assertFalse(result['ok'], result)
                    self.assertIn('Content override validation failed', result['refused']['summary'])
                    self.assertEqual(self.sheet.read_bytes(), before)

    def test_arithmetic_terms_are_not_compared_as_literal_assignments(self):
        path = self.sheet.with_name('EffectModel.ops.csv')
        path.write_bytes(b'EffectId,Heals+,MoveSpeed*\n1,10,1.5\n')
        result = self.app.api_validate({})
        self.assertTrue(result['ok'], result)
        self.assertFalse(any(c['path'].endswith('.ops.csv') for c in result['cleared']))

    def test_integer_baseline_uses_the_documented_model_conversion(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('UPDATE Effect SET Heals=10.4 WHERE EffectId=1')
            db.commit()
        result = self.app.api_validate(self.edit('10'))
        self.assertTrue(result['ok'], result)
        self.assertTrue(any(c['key']==['1'] and c['column']=='Heals' for c in result['cleared']))

    def test_a_null_shipped_value_does_not_prevent_a_valid_assignment(self):
        with closing(sqlite3.connect(self.database)) as db:
            db.execute('UPDATE Effect SET MoveSpeed=NULL WHERE EffectId=1')
            db.commit()
        result = self.app.api_validate(self.edit('1.5', 'MoveSpeed'))
        self.assertTrue(result['ok'], result)
        self.assertFalse(any(c['column']=='MoveSpeed' for c in result['cleared']))

    def test_clone_armor_is_type_checked_without_clearing_its_assignments(self):
        path = self.sheet.with_name('ArmorModel.csv')
        path.write_bytes(b'ArmorId,_clone,BallisticArmor\n900001,1,45\n')
        result = self.app.api_validate({})
        self.assertTrue(result['ok'], result)
        self.assertFalse(any(c['kind']=='enemyArmor' for c in result['cleared']))
        for value in ('nonsense', '1.5', '1e400'):
            path.write_text('ArmorId,_clone,BallisticArmor\n900001,1,'+value+'\n')
            result = self.app.api_validate({})
            self.assertFalse(result['ok'], result)

    def test_player_cleanup_keys_on_table_id_and_handles_negative_assignments(self):
        doc = pb.empty()
        doc['tables'] = {'Weapon': {'1': {'Cost': '10'}, '2': {'Cost': '-5'}},
                         'Effect': {'1': {'Heals': '=10'}}}
        path = self.config / pb.FILE
        path.write_bytes(pb.encode(doc))
        result = self.app.api_validate({})
        self.assertTrue(result['ok'], result)
        self.assertEqual({(c['table'], c['id'], c['column']) for c in result['cleared'] if c['kind'] == 'player'},
                         {('Weapon', '2', 'Cost'), ('Effect', '1', 'Heals')})
        self.assertEqual(pb.load(self.config), doc)
        saved = self.app.api_save({})
        self.assertTrue(saved['ok'], saved)
        self.assertEqual(pb.load(self.config)['tables'], {'Weapon': {'1': {'Cost': '10'}}})

    def test_text_columns_preserve_real_overrides_and_clear_exact_defaults(self):
        path = self.sheet.with_name('JobNodeModel.icons.csv')
        path.write_bytes(b'JobNodeId,IconPng\n1,original\n2,different\n')
        result = self.app.api_validate({})
        self.assertTrue(result['ok'], result)
        icons = [c for c in result['cleared'] if c['path'].endswith('.icons.csv')]
        self.assertEqual([c['key'] for c in icons], [['1']])


if __name__ == '__main__':
    unittest.main()
