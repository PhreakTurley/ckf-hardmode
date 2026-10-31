"""Exercise the independent Workshop verifier against corrupted real payloads."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import csv

from export_enemy_difficulty import PROJECT, build, guarded_write
from static_data import StaticData
from verify_enemy_difficulty import verify
from install_enemy_difficulty import require_steam_install


class EnemyDifficultyChecks(unittest.TestCase):
    def test_requires_a_registered_steam_install(self):
        with TemporaryDirectory(prefix='registration-test-', dir=PROJECT) as temporary:
            root = Path(temporary).resolve()
            self.assertTrue(root.is_relative_to(PROJECT.resolve()))
            workshop = root / 'workshop/content/1021210/3829942905'
            workshop.mkdir(parents=True)
            manifest = root / 'workshop/appworkshop_1021210.acf'
            with self.assertRaisesRegex(ValueError, 'Could not establish Steam installation'):
                require_steam_install(workshop)
            manifest.write_text('"AppWorkshop" { "WorkshopItemsInstalled" { "3814427009" { "size" "1" } } }')
            with self.assertRaisesRegex(ValueError, 'Steam has not registered Workshop item 3829942905'):
                require_steam_install(workshop)
            manifest.write_text('"AppWorkshop" { "WorkshopItemsInstalled" { "3829942905" { "size" "1" } } }')
            self.assertEqual(require_steam_install(workshop)['itemid'], '3829942905')
            manifest.write_text('"AppWorkshop" { "WorkshopItemsInstalled" {')
            with self.assertRaisesRegex(ValueError, 'Could not establish Steam installation'):
                require_steam_install(workshop)

    def test_export_ignores_legacy_nonarmor_fields_and_sheets(self):
        # Synthetic identity-only fixture, not a copy of live tuning. There is
        # deliberately no weapon or roster sheet for the exporter to read.
        with TemporaryDirectory(prefix='verifier-test-', dir=PROJECT) as temporary:
            directory = Path(temporary)
            with StaticData() as db:
                ids = [r['MonsterTypeId'] for r in db.read('MonsterTypeModel')[1]]
            guarded_write(directory / 'ArmorModel.csv', b'ArmorId,BallisticArmor\n')
            monster = 'MonsterTypeId,ArmorTypeId,HitPoints,WeaponTypeId,MonsterTalentGroup\n'
            monster += ''.join(f'{identity},,1,999999,999999\n' for identity in ids)
            guarded_write(directory / 'MonsterTypeModel.csv', monster.encode())
            artifacts, _ = build(config_dir=directory)
            import json
            payload = json.loads(artifacts['source_content/enemy-difficulty.json'])
            self.assertEqual(len(payload['RawSQL']), 1)
            self.assertIn('WHERE "RuleId"=82', payload['RawSQL'][0])
            self.assertEqual(payload['RawText']['Generic'], {})

    def test_native_integrity_gate_remains_runnable(self):
        with self.assertRaisesRegex(AssertionError, 'Unresolved high-PL WeaponTypeId: 30130'):
            verify(PROJECT / 'parser_prepared/_data/data.sql', native_integrity=True)

    def test_rejects_corrupted_payloads(self):
        with (PROJECT / "review/column-ledger.csv").open(encoding="utf-8-sig", newline="") as handle:
            armor = next(int(row["Id"]) for row in csv.DictReader(handle)
                         if row["Table"] == "Armor" and row["Column"] == "BallisticArmor")
        cases = (
            ("authored armor changed", f'UPDATE Armor SET BallisticArmor=BallisticArmor+1 WHERE ArmorId={armor};', f'Row mismatch: Armor {armor}'),
            ("wrong enemy ceiling", 'UPDATE Rule SET Value=12 WHERE RuleId=82;', 'Row mismatch: Rule 82'),
            ("mission ceiling changed", 'UPDATE Rule SET Value=20 WHERE RuleId=81;', 'Row mismatch: Rule 81'),
            ("high-level HP backslide", 'UPDATE MonsterType SET HitPoints=1 WHERE MonsterTypeId=24;', 'Forbidden SQL write: MonsterType.HitPoints'),
            ("authored weapon changed", 'UPDATE Weapon SET BallisticDamage1=1 WHERE WeaponId=20010;', 'Forbidden SQL write: Weapon.BallisticDamage1'),
            ("native weapon overwritten", 'UPDATE Weapon SET BallisticDamage1=1 WHERE WeaponId=20012;', 'Forbidden SQL write: Weapon.BallisticDamage1'),
            ("native effect overwritten", 'UPDATE Effect SET InitBonus=999 WHERE EffectId=64206;', 'Forbidden SQL write: Effect.InitBonus'),
            ("new enemy misses authored gear", 'UPDATE MonsterType SET ArmorTypeId=1 WHERE PowerGroupId=127620 AND PowerLevel=20;', 'Row mismatch: MonsterType'),
            ("weapon pointer overwritten", 'UPDATE MonsterType SET WeaponTypeId=22010 WHERE MonsterTypeId=189;', 'Forbidden SQL write: MonsterType.WeaponTypeId'),
            ("official upgrade missed", 'UPDATE MonsterTalent SET TargetEffect=64140 WHERE MonsterTalentId=836;', 'Forbidden SQL write: MonsterTalent.TargetEffect'),
            ("talent band gap", 'UPDATE MonsterTalent SET MaxPowerLevel=0 WHERE MonsterTalentId=857;', 'Forbidden SQL write: MonsterTalent.MaxPowerLevel'),
            ("roster taper changed", 'UPDATE MonsterGroupMember SET WeightedRoll=9999 WHERE MonsterGroupMemberId=30;', 'Forbidden SQL write: MonsterGroupMember.WeightedRoll'),
            ("player talent changed", 'UPDATE Talent SET Range=999 WHERE TalentId=5001;', 'Forbidden SQL write: Talent.Range'),
            ("shared effect changed", 'UPDATE Effect SET Heals=999 WHERE EffectId=64192;', 'Forbidden SQL write: Effect.Heals'),
            ("effect variant ownership lost", 'UPDATE Effect SET EffectOwner=0 WHERE EffectId=960002;', 'Forbidden SQL write: Effect.EffectOwner'),
            ("no-op weapon write", 'UPDATE Weapon SET Accuracy1=Accuracy1 WHERE WeaponId=20010;', 'Forbidden SQL write: Weapon.Accuracy1'),
            ("weapon insert", 'INSERT INTO Weapon SELECT * FROM Weapon WHERE 0;', 'Forbidden SQL write: Weapon'),
            ("armor removal", f'DELETE FROM Armor WHERE ArmorId={armor};', 'Forbidden SQL write: Armor'),
        )
        source = (PROJECT / 'parser_prepared/_data/data.sql').read_bytes()
        locale = (PROJECT / 'parser_prepared/_data/en-US.json').read_bytes()
        with TemporaryDirectory(prefix='verifier-test-', dir=PROJECT) as temporary:
            directory = Path(temporary)
            self.assertTrue(directory.resolve().is_relative_to(PROJECT.resolve()))
            sql = directory / 'data.sql'
            (directory / 'en-US.json').write_bytes(locale)
            for name, mutation, failure in cases:
                with self.subTest(name=name):
                    sql.write_bytes(source + b'\n' + mutation.encode())
                    with self.assertRaisesRegex(AssertionError, failure):
                        verify(sql)


if __name__ == '__main__':
    unittest.main()
