# Armour families and enemy assignments

An armor tier and an enemy power level are separate values. `MonsterType.ArmorTypeId`
selects a row by `Armor.ArmorId`; the armor's `PowerLevel` does not select it.
Authoring and validation are described in the [Enemy Armors editor guide](../gui/README.md#enemy-armors).

To construct a twenty-tier family, reuse its shipped ladder rows and clone only
additional tiers above that ladder. A blank stat cell on a shipped row restores
Official data; a blank clone cell inherits its donor after authored edits.
Keep the source row's identity, and author the tier's `PowerLevel` explicitly
when the native metadata or name does not match its position in the ladder.

The shipped lower tiers need not map one to one to enemy PL. Preserve those
native assignments when restoring the native opening progression. Higher-level
assignments are explicit authoring choices: unused intermediate armor tiers are
valid, while an enemy pointing to an absent armor row is not. Changing shared
shipped armor also changes any singleton enemies referencing it.

## Shipped pointer runs

These captured native `MonsterTypeModel` pointer runs are historical evidence
[measured, `sheets/raw/MonsterTypeModel.csv`]. For current shipped pointers and
armor values, read `Official/data.db` through `scripts/static_data.py`; never
use the authored overlay as a native baseline.

### `guard-standard`: 3 patterns, 24 PowerGroups

| n | PL 1–10 rows | PL 11–20 rows | PowerGroups |
|---|---|---|---|
| 12 | 22001 22001 22002 22003 22003 22004 22005 22005 22006 22007 | 22007 x10 | 1, 25000, 25002, 27000, 27060, 30000, 30040, 40000, 40100, 40150, 42000, 90000 |
| 10 | 22002 22002 22003 22004 22004 22005 22006 22007 22008 22009 | 22009 x10 | 3100, 3101, 3500, 3520, 3540, 3600, 4000, 4150, 12000, 12001 |
| 2 | 22000 22000 22001 22002 22003 22003 22004 22004 22005 22005 | 22005 x10 | 3000 Street Warrior, 12050 Free Gunner |

The 10-PowerGroup pattern is the strongest, not the most common:
`BallisticArmorDegraded` at PL 10 was 50 for it and 40 for the other two.

### `adaptive`: 4 patterns, 43 PowerGroups

| n | PL 1–10 rows | PL 11–20 rows | PowerGroups |
|---|---|---|---|
| 31 | 22202 22202 22203 22203 22204 22204 22205 22205 22206 22206 | 22206 x10 | 100, 160, 25001, 25003, 27030, 27040, 30020, 30060, 30120, 30140, 40002, 40003, 40101, 40130, 42040, 42060, 90001, 90002, 126001–126003, 127001, 127003, 127340, 127350, 127360, 127382–127384, 127392, 127393 |
| 9 | 22200 22201 22201 22202 22202 22203 22204 22204 22204 22205 | 22205 x10 | 3200, 3201, 3400, 3650, 3700, 3720, 3740, 4100, 12060 |
| 2 | 22200 22200 22201 22201 22202 22202 22203 22203 22204 22205 | 22205 x10 | 125001 Macha Stalker, 125002 Macha Blue |
| 1 | 22200 22200 22201 22201 22202 22202 22203 22203 22204 22206 | 22205/22206 alternating | 300 Guard Bladesman |

PowerGroup 300's PL 11–20 run alternates 22205 and 22206.

## Validation and naming

The editor resolves authored armor replacements before validating every effective
enemy assignment. It also accounts for the exporter's matched higher-level
extensions to newly shipped ladders. Warnings identify the enemy and missing
armor ID; replaced native references are not reported as unresolved. The exporter
and independent verifier check every effective enemy armor reference as well.

Authored shipped rows and clones receive names using their effective armor PL.
The source name's trailing PL/Lvl suffix is replaced, so a clone does not carry
two different levels in its name. See [Workshop preparation](enemy-difficulty-workshop.md)
for the SQL and locale handoff.

## Open questions

- [unverified] Whether PowerGroup 300's alternating native PL11–20 pointers are
  deliberate or incidental.

## Related

- [Enemy tuning surfaces](tuning-enemies.md#armour)
- [Cloning rows](cloning-rows.md)
