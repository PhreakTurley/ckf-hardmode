"""Exercise the independent Workshop verifier against corrupted real payloads."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import csv

from export_enemy_difficulty import PROJECT, build, guarded_write, FIXES_FILE, SPAWN_TAGS
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

    def test_export_ignores_legacy_weapon_stat_and_spawn_fields(self):
        # Synthetic identity-only fixture, not a copy of live tuning. There is
        # deliberately no weapon sheet; invalid legacy spawn columns prove those
        # obsolete files are not read or stacked with the new roster policy.
        with TemporaryDirectory(prefix='verifier-test-', dir=PROJECT) as temporary:
            directory = Path(temporary) / "ckf.hardmode.d"
            directory.mkdir()
            guarded_write(directory.parent / FIXES_FILE, b'{"format":1,"clones":[],"updates":[]}')
            with StaticData() as db:
                ids = [r['MonsterTypeId'] for r in db.read('MonsterTypeModel')[1]]
            guarded_write(directory / 'ArmorModel.csv', b'ArmorId,BallisticArmor\n')
            for tag in SPAWN_TAGS:
                guarded_write(directory / f'MonsterGroupMemberModel.spawn-{tag}.csv',
                              b'MonsterGroupMemberId,InvalidLegacyColumn\n30,999999\n')
            monster = 'MonsterTypeId,ArmorTypeId,HitPoints,WeaponTypeId,MonsterTalentGroup\n'
            monster += ''.join(f'{identity},,1,999999,999999\n' for identity in ids)
            guarded_write(directory / 'MonsterTypeModel.csv', monster.encode())
            artifacts, _ = build(config_dir=directory)
            import json
            payload = json.loads(artifacts['source_content/enemy-difficulty.json'])
            non_roster = [statement for statement in payload['RawSQL'] if 'MonsterGroupMember' not in statement]
            self.assertEqual(len(non_roster), 1)
            self.assertIn('WHERE "RuleId"=82', non_roster[0])
            self.assertTrue(any(statement.startswith('DELETE FROM "MonsterGroupMember"') for statement in payload['RawSQL']))
            self.assertFalse(any('spawn-' in path for path in artifacts['review/SOURCE.json'].decode().splitlines()))
            self.assertEqual(payload['RawText']['Generic'], {})
            # An upstream correction or retune must refuse the old patch,
            # rather than silently applying a stale override.
            stale = {"format": 1, "clones": [], "updates": [{"table": "Weapon", "id": 20007,
                     "expect": {"Accuracy1": 999}, "set": {"Accuracy1": 76}, "reason": ["test"]}]}
            guarded_write(directory.parent / FIXES_FILE, json.dumps(stale).encode())
            with self.assertRaisesRegex(ValueError, 'Native surgical target changed: Weapon 20007.Accuracy1'):
                build(config_dir=directory)
            guarded_write(directory.parent / FIXES_FILE,
                          b'{"format":1,"updates":[],"clones":[{"table":"Weapon","id":980010}]}')
            with self.assertRaisesRegex(ValueError, 'clones are disabled'):
                build(config_dir=directory)


    def test_native_integrity_gate_remains_runnable(self):
        with self.assertRaisesRegex(AssertionError, 'Unresolved high-PL WeaponTypeId: 30130'):
            verify(PROJECT / 'parser_prepared/_data/data.sql', native_integrity=True)

    def test_rejects_corrupted_payloads(self):
        with (PROJECT / "review/column-ledger.csv").open(encoding="utf-8-sig", newline="") as handle:
            ledger = list(csv.DictReader(handle))
            armor = next(int(row["Id"]) for row in ledger
                         if row["Table"] == "Armor" and row["Column"] == "BallisticArmor")
        members = {}
        for row in ledger:
            if row["Table"] == "MonsterGroupMember":
                members.setdefault(int(row["Id"]), {})[row["Column"]] = row["Value"]
        roster = next(identity for identity, row in members.items() if "WeightedRoll" in row)
        gate = lambda group, maximum: next(identity for identity, row in members.items()
                      if row.get("MonsterGroupId") == str(group) and row.get("MaxPowerLevel") == str(maximum))
        vip, armored, reinforcement = gate(12550, 14), gate(12600, 14), gate(12150, 19)
        with StaticData() as db:
            unowned = next(int(r["MonsterGroupMemberId"]) for r in db.read("MonsterGroupMemberModel")[1]
                           if int(r["MonsterGroupMemberId"]) not in members)
        # An unreviewed column is rejected before the exact-row comparison.
        accuracy_reviewed = any(row["Table"] == "Weapon" and row["Column"] == "Accuracy1"
                                for row in ledger)
        cases = (
            ("authored armor changed", f'UPDATE Armor SET BallisticArmor=BallisticArmor+1 WHERE ArmorId={armor};', f'Row mismatch: Armor {armor}'),
            ("wrong enemy ceiling", 'UPDATE Rule SET Value=12 WHERE RuleId=82;', 'Row mismatch: Rule 82'),
            ("mission ceiling changed", 'UPDATE Rule SET Value=20 WHERE RuleId=81;', 'Row mismatch: Rule 81'),
            ("high-level HP backslide", 'UPDATE MonsterType SET HitPoints=1 WHERE MonsterTypeId=24;', 'Row mismatch: MonsterType 24'),
            ("authored weapon changed", 'UPDATE Weapon SET BallisticDamage1=1 WHERE WeaponId=20010;', 'Forbidden SQL write: Weapon.BallisticDamage1'),
            ("native weapon overwritten", 'UPDATE Weapon SET BallisticDamage1=1 WHERE WeaponId=20012;', 'Forbidden SQL write: Weapon.BallisticDamage1'),
            ("native effect overwritten", 'UPDATE Effect SET InitBonus=999 WHERE EffectId=64206;', 'Forbidden SQL write: Effect.InitBonus'),
            ("new enemy misses authored gear", 'UPDATE MonsterType SET ArmorTypeId=1 WHERE PowerGroupId=127620 AND PowerLevel=20;', 'Row mismatch: MonsterType'),
            ("weapon pointer overwritten", 'UPDATE MonsterType SET WeaponTypeId=22010 WHERE MonsterTypeId=189;', 'Row mismatch: MonsterType 189'),
            ("unreviewed native talent changed", 'UPDATE MonsterTalent SET TargetEffect=TargetEffect+1 WHERE MonsterTalentId=836;', 'Row mismatch: MonsterTalent 836'),
            ("talent band gap", 'UPDATE MonsterTalent SET MaxPowerLevel=0 WHERE MonsterTalentId=857;', 'Forbidden SQL write: MonsterTalent.MaxPowerLevel'),
            ("roster taper changed", f'UPDATE MonsterGroupMember SET WeightedRoll=9999 WHERE MonsterGroupMemberId={roster};', f'Row mismatch: MonsterGroupMember {roster}'),
            ("VIP removal gate lost", f'UPDATE MonsterGroupMember SET MaxPowerLevel=20 WHERE MonsterGroupMemberId={vip};', f'Row mismatch: MonsterGroupMember {vip}'),
            ("Armored VIP removal gate lost", f'UPDATE MonsterGroupMember SET MaxPowerLevel=20 WHERE MonsterGroupMemberId={armored};', f'Row mismatch: MonsterGroupMember {armored}'),
            ("reinforcement removal gate lost", f'UPDATE MonsterGroupMember SET MaxPowerLevel=20 WHERE MonsterGroupMemberId={reinforcement};', f'Row mismatch: MonsterGroupMember {reinforcement}'),
            ("unowned roster deleted", f'DELETE FROM MonsterGroupMember WHERE MonsterGroupMemberId={unowned};', 'Row identities differ: MonsterGroupMember'),
            ("legacy roster restored", 'INSERT INTO MonsterGroupMember (MonsterGroupMemberId,MonsterGroupId,MonsterType,Slot,Faction,MinPowerLevel,MaxPowerLevel,MinSecLevel,MaxSecLevel,Exclusive,WeightedRoll) VALUES (30,100,1,1,0,0,0,0,0,0,5);', 'Row identities differ: MonsterGroupMember'),
            ("player talent changed", 'UPDATE Talent SET Range=999 WHERE TalentId=5001;', 'Forbidden SQL write: Talent.Range'),
            ("shared effect changed", 'UPDATE Effect SET Heals=999 WHERE EffectId=64192;', 'Forbidden SQL write: Effect.Heals'),
            ("effect variant ownership lost", 'UPDATE Effect SET EffectOwner=0 WHERE EffectId=960002;', 'Forbidden SQL write: Effect.EffectOwner'),
            ("no-op weapon write", 'UPDATE Weapon SET BallisticDamage1=BallisticDamage1 WHERE WeaponId=20010;', 'Forbidden SQL write: Weapon.BallisticDamage1'),
            ("weapon insert forbidden", 'INSERT INTO Weapon SELECT * FROM Weapon WHERE 0;', 'Forbidden SQL write: Weapon'),
            ("unauthorized accuracy change", 'UPDATE Weapon SET Accuracy1=1 WHERE WeaponId=20012;',
             'Row mismatch: Weapon 20012' if accuracy_reviewed else 'Forbidden SQL write: Weapon.Accuracy1'),
            ("native sniper source changed", 'UPDATE Weapon SET Accuracy1=1 WHERE WeaponId=6014;',
             'Row mismatch: Weapon 6014' if accuracy_reviewed else 'Forbidden SQL write: Weapon.Accuracy1'),
            ("VTOL native source changed", 'UPDATE Effect SET Stunned=0 WHERE EffectId=64175;', 'Forbidden SQL write: Effect.Stunned'),
            ("VTOL pointer repair lost", 'UPDATE MonsterType SET EffectId=64173 WHERE MonsterTypeId=1150;', 'Row mismatch: MonsterType 1150'),
            ("sniper pointer repair lost", 'UPDATE MonsterType SET WeaponTypeId=6015 WHERE MonsterTypeId=3310;', 'Row mismatch: MonsterType 3310'),
            ("Vita-Tech group repair lost", 'UPDATE MonsterTalent SET MonsterTalentGroup=603 WHERE MonsterTalentId=603;', 'Row mismatch: MonsterTalent 603'),
            ("Rallying Cry repair lost", 'UPDATE MonsterTalent SET TargetEffect=64006 WHERE MonsterTalentId=303;', 'Row mismatch: MonsterTalent 303'),
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
