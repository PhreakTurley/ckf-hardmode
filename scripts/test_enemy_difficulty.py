"""Exercise the independent Workshop verifier against corrupted real payloads."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from export_enemy_difficulty import PROJECT
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

    def test_rejects_corrupted_payloads(self):
        cases = (
            ("wrong enemy ceiling", 'UPDATE Rule SET Value=12 WHERE RuleId=82;', 'Row mismatch: Rule 82'),
            ("mission ceiling changed", 'UPDATE Rule SET Value=20 WHERE RuleId=81;', 'Row mismatch: Rule 81'),
            ("high-level HP backslide", 'UPDATE MonsterType SET HitPoints=1 WHERE MonsterTypeId=24;', 'Row mismatch: MonsterType 24'),
            ("authored weapon changed", 'UPDATE Weapon SET BallisticDamage1=1 WHERE WeaponId=20019;', 'Row mismatch: Weapon 20019'),
            ("new enemy misses authored gear", 'UPDATE MonsterType SET WeaponTypeId=6016 WHERE PowerGroupId=127620 AND PowerLevel=20;', 'Row mismatch: MonsterType'),
            ("official upgrade missed", 'UPDATE MonsterTalent SET TargetEffect=64140 WHERE MonsterTalentId=836;', 'Row mismatch: MonsterTalent 836'),
            ("talent band gap", 'UPDATE MonsterTalent SET MaxPowerLevel=0 WHERE MonsterTalentId=857;', 'Row mismatch: MonsterTalent 857'),
            ("roster taper changed", 'UPDATE MonsterGroupMember SET WeightedRoll=9999 WHERE MonsterGroupMemberId=30;', 'Row mismatch: MonsterGroupMember 30'),
            ("player talent changed", 'UPDATE Talent SET Range=999 WHERE TalentId=5001;', 'Unowned table changed: Talent'),
            ("shared effect changed", 'UPDATE Effect SET Heals=999 WHERE EffectId=64192;', 'Row mismatch: Effect 64192'),
            ("effect variant ownership lost", 'UPDATE Effect SET EffectOwner=0 WHERE EffectId=960002;', 'Row mismatch: Effect 960002'),
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
