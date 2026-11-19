"""Exercise the independent Workshop verifier against corrupted real payloads."""
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
import csv
import sqlite3
from contextlib import closing

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
            guarded_write(directory.parent / FIXES_FILE, b'{"format":1,"clones":[],"updates":[],"rules":{"82":{"Value":19}}}')
            with StaticData() as db:
                ids = [r['MonsterTypeId'] for r in db.read('MonsterTypeModel')[1]]
            armor = directory / 'ArmorModel.csv'
            guarded_write(armor, b'ArmorId,BallisticArmor,_comment\n18,,\n21999,,reference\n')
            for tag in SPAWN_TAGS:
                guarded_write(directory / f'MonsterGroupMemberModel.spawn-{tag}.csv',
                              b'MonsterGroupMemberId,InvalidLegacyColumn\n30,999999\n')
            monster = 'MonsterTypeId,ArmorTypeId,HitPoints,WeaponTypeId,MonsterTalentGroup\n'
            patched_armor = {"1100", "1160"}  # Hover Tank and Helios Gunboat PL1
            monster += ''.join(f'{identity},{"22511" if identity in patched_armor else ""},1,999999,999999\n'
                               for identity in ids)
            guarded_write(directory / 'MonsterTypeModel.csv', monster.encode())
            artifacts, _ = build(config_dir=directory)
            import json
            payload = json.loads(artifacts['source_content/enemy-difficulty.json'])
            self.assertEqual(payload['Metadata'], {'Name':'EnemyVariety', 'StoryKey':'EnemyVariety', 'StartingId':560000})
            non_roster = [statement for statement in payload['RawSQL'] if 'MonsterGroupMember' not in statement]
            self.assertEqual(non_roster, [
                'UPDATE "Rule" SET "Value"=19 WHERE "RuleId"=82;',
                'UPDATE "MonsterType" SET "ArmorTypeId"=22511 WHERE "MonsterTypeId"=1100;',
                'UPDATE "MonsterType" SET "ArmorTypeId"=22511 WHERE "MonsterTypeId"=1160;',
            ])
            sql = directory.parent / 'data.sql'
            sql.write_bytes(artifacts['prepared/_data/data.sql'])
            sql.with_name('en-US.json').write_bytes(artifacts['prepared/_data/en-US.json'])
            self.assertEqual(verify(sql, config_dir=directory)['status'], 'PASS')
            sql.write_bytes(sql.read_bytes() + b'\nUPDATE Rule SET Value=20 WHERE RuleId=82;')
            with self.assertRaisesRegex(AssertionError, 'Row mismatch: Rule 82'):
                verify(sql, config_dir=directory)
            # With no authored rule, the shipped cell remains authoritative.
            guarded_write(directory.parent / FIXES_FILE, b'{"format":1,"clones":[],"updates":[]}')
            stock_artifacts, _ = build(config_dir=directory)
            stock_payload = json.loads(stock_artifacts['source_content/enemy-difficulty.json'])
            self.assertFalse(any('WHERE "RuleId"=82' in s for s in stock_payload['RawSQL']))
            sql.write_bytes(stock_artifacts['prepared/_data/data.sql'])
            self.assertEqual(verify(sql, config_dir=directory)['status'], 'PASS')
            self.assertTrue(any(statement.startswith('DELETE FROM "MonsterGroupMember"') for statement in payload['RawSQL']))
            self.assertFalse(any('spawn-' in path for path in artifacts['review/SOURCE.json'].decode().splitlines()))
            self.assertEqual(payload['RawText']['Generic'], {})
            guarded_write(armor, b'ArmorId,BallisticArmor\n18,0\n')
            with self.assertRaisesRegex(ValueError, 'Armor 18 has shipped-row overrides'):
                build(config_dir=directory)
            with self.assertRaisesRegex(AssertionError, 'Unexpected shipped armor overrides: 18'):
                verify(sql, config_dir=directory)
            guarded_write(armor, b'ArmorId,BallisticArmor\n')
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
        result = verify(PROJECT / 'parser_prepared/_data/data.sql', native_integrity=True)
        self.assertTrue(result['native_integrity_checks'])
        self.assertTrue(all(status == 'PASS' for status in result['native_integrity_checks'].values()))

    def test_authored_ids_do_not_replace_another_mods_rows(self):
        sql = (PROJECT / "parser_prepared/_data/data.sql").read_text(encoding="utf-8-sig")
        with StaticData() as db:
            for table, key, identity, field in (
                ("Armor", "ArmorId", 560000, "BallisticArmor"),
                ("MonsterGroupMember", "MonsterGroupMemberId", 561000, "WeightedRoll"),
            ):
                with self.subTest(table=table), closing(sqlite3.connect(":memory:")) as connection:
                    db.connection.backup(connection)
                    connection.execute(f"INSERT INTO {table} ({key}, {field}) VALUES (?, -987)", (identity,))
                    with self.assertRaisesRegex(sqlite3.IntegrityError, f"UNIQUE constraint failed: {table}.{key}"):
                        connection.executescript(sql)
                    self.assertEqual(connection.execute(f"SELECT {field} FROM {table} WHERE {key}=?",
                                                        (identity,)).fetchone(), (-987,))

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
        vip, armored, reinforcement = gate(12550, 15), gate(12600, 15), gate(12150, 20)
        with StaticData() as db:
            unowned = next(int(r["MonsterGroupMemberId"]) for r in db.read("MonsterGroupMemberModel")[1]
                           if int(r["MonsterGroupMemberId"]) not in members)
        # An unreviewed column is rejected before the exact-row comparison.
        accuracy_reviewed = any(row["Table"] == "Weapon" and row["Column"] == "Accuracy1"
                                for row in ledger)
        cases = (
            ("authored armor changed", f'UPDATE Armor SET BallisticArmor=BallisticArmor+1 WHERE ArmorId={armor};', 'Forbidden SQL write: Armor.BallisticArmor'),
            ("wrong enemy ceiling", 'UPDATE Rule SET Value=12 WHERE RuleId=82;', 'Row mismatch: Rule 82'),
            ("mission ceiling changed", 'UPDATE Rule SET Value=20 WHERE RuleId=81;', 'Row mismatch: Rule 81'),
            ("high-level HP backslide", 'UPDATE MonsterType SET HitPoints=1 WHERE MonsterTypeId=24;', 'Forbidden SQL write: MonsterType.HitPoints'),
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
            ("reinforcement removal gate lost", f'UPDATE MonsterGroupMember SET MaxPowerLevel=21 WHERE MonsterGroupMemberId={reinforcement};', f'Row mismatch: MonsterGroupMember {reinforcement}'),
            ("unowned roster deleted", f'DELETE FROM MonsterGroupMember WHERE MonsterGroupMemberId={unowned};', 'Row identities differ: MonsterGroupMember'),
            ("legacy roster restored", 'UPDATE MonsterGroupMember SET MaxPowerLevel=0 WHERE MonsterGroupMemberId=30;', 'Row mismatch: MonsterGroupMember 30'),
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
            ("VTOL pointer repair lost", 'UPDATE MonsterType SET EffectId=64173 WHERE MonsterTypeId=1150;', 'Forbidden SQL write: MonsterType.EffectId'),
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
