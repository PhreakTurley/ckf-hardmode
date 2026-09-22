# Enemy faction roster map

Use this page to trace faction roster ownership and compare shipped enemy
archetypes. It is an observation reference, not a target ordering or tuning
plan. Current tuning belongs only in the live files under `BepInEx\config`; use
[`tuning-enemies.md`](tuning-enemies.md) to find those surfaces.

Unless stated otherwise, counts and values are [measured] from `sheets/raw/`,
including 2,427 `MonsterTypeModel` rows. They describe shipped data, not the
mutable live overlay.

## Roster resolution

`MonsterGroupMemberModel.MonsterType` holds a PowerGroup id. Its
`MonsterGroupId` resolves through `MonsterGroupModel` to a `FactionId` and
`FactionClass`. A group with `FactionId = 0` is a class-wide pool used by
untagged factions of that class.

`FactionClass` resolves as 1 Megacorp, 2 Corp, 3 Milsec, 4 Syndicate, and 5
Gang. Values 0 and 6 appear on `FactionModel` rows with no class text.

Nine factions own groups: Matsumoto 1, UltraTek 2, Jupiter 3, Warner-Braun 4,
McKellen 6, Brave Star 7, FSC 12, Demo Corp 13, and KEMCO 16. Other factions
draw from their class pool.

Arrowhead (FactionId 20) and Knight Horizon (19) own no groups. Their generic
Milsec groups are 2000, 2050, 2200, 2300, 2400, 2600, 2700, 2750, and 26250.
Those groups contain generic Guard, Guard Shotgun, FireCOM, Guard Sniper, Guard
Bladesman, Mecha Infantry, Guard Captain, and Sentinel Exec PowerGroups; VTOL
(PG 1140) and EG Turret (PG 1020) are the two entries not shared with generic
Megacorp. Rook Technologies (5) likewise owns no groups and draws generic
Megacorp.

## Archetype-difference surfaces

Faction rosters commonly share gear rows. For example, weapon tier 20009 at PL
10 is referenced by Guard, WB Guard, T-REX, KEM Guard, Advance NX, MK
Midweight, SWAT, Mecha Infantry, S-Class Brakka, FireCOM, J6 SIG, T-SIG Corp,
Lance VTOL, and MATS VTOL. Armour tier 22206 at PL 10 is referenced by 32
archetypes across the factions.

Compare factions on these separate surfaces:

- `HitPoints` and `InitBonus` curves.
- `MaxTalentCount` and `MonsterTalentGroup`.
- Weapon- and armour-block pointers.
- `EffectId` (present on 1,311 rows).
- `PatrolSpeed`, `ChasingSpeed`, and `AggroSpeed`.
- Roster membership and `WeightedRoll`.

### Shipped PL 10 gear ceiling

Every shipped gear ladder freezes at PL 10: `WeaponTypeId` and `ArmorTypeId`
repeat the PL 10 tier for PL 11–20. Guard, for example, references weapon 20009
and armour 22007 at both PL 10 and PL 20. Above PL 10, its `HitPoints` and
`InitBonus` continue to change. The live PL 1–20 retune is separate; inspect the
live overlay and [`../overlays/_reference/gear-blocks.md`](../overlays/_reference/gear-blocks.md).

### McKellen movement-speed variants

Six McKellen archetypes use `PatrolSpeed` 2.1, `ChasingSpeed` 3.1, and
`AggroSpeed` 3.75: MK Midweight, MK Crusher, MK FireCON, MK HeavyLift, MEK
Lead, and MEK Suit. MK Flashboom and MK Frontline instead use 2.25, 3.75, and
4.25. [unverified] Whether the difference is deliberate.

### Effects that contain only stun resistance

Four frequently referenced effect rows set only `Stunned`:

| Effect | References | `Stunned` |
|---|---:|---:|
| 64149 Hardened Target | 560 | -60 |
| 64158 Officer Grit | 140 | -50 |
| 64159 Lead from the Front | 40 | -40 |
| 64150 Precious VIP | 3 | -50 |

Together they account for 743 archetype rows. Treating every non-zero
`EffectId` as a general stat block would therefore misclassify many rows.

Other named effect rows do carry multiple stats:

- 64146 Nimble Suits: `Evasion 5`, `MoveSpeed 20`, `InitBonus 3`, `Stunned -50`
  on 180 rows.
- 64121 Instinct: `PureArmor 10`, `InitBonus 3`, `Stunned -75` on 100 rows.
- 64126 Hunter's Twitch: `PureArmor 10`, `Evasion 25`, `InitBonus 2` on 40
  rows.
- 64148 Military Precision: `CritRate 25`, `ArmorCrit 25`, `InitBonus 3` on 40
  rows.
- 64142 Cold Killer: `Melee/Ranged 10`, `CritRate 10`, `ArmorCrit 10`,
  `InitBonus 3` on 20 rows.
- 64160 Barrel Rush: `OverwatchBreak 50` on 40 rows.

## Project 1: Warner-Braun and UltraTek to generic Megacorp parity

Four Warner-Braun/UltraTek pairs are identical across the shipped stat columns
at all 20 power levels. They differ only in `MonsterName`, `MonsterTypeId`,
`OutfitId`, and `DetailGroup`:

| Warner-Braun | UltraTek |
|---|---|
| WB Guard (PG 40000) | T-REX (PG 40100) |
| WB Captain (PG 40001) | T-Capt (PG 40102) |
| WB Assault (PG 40002) | T-Assault (PG 40101) |
| WB FireCOM (PG 40003) | T-FireCOM (PG 40130) |

WB FireCOM also appears in KEMCO group 90000, so a PowerGroup-wide edit affects
that KEMCO roster entry as well.

The shipped `MonsterTypeId` runs are not all contiguous:

| Archetype | `MonsterTypeId`, PL 1–20 |
|---|---|
| WB Guard | `40000 40001 40002 40003 40004 40005 40026 40027 40028 40029 41000`–`41009` |
| WB Captain | `40006 40007 40008 40009 40010 40011 40022 40023 40024 40025 41010`–`41019` |
| WB Assault | `40012`–`40021 41020`–`41029` |
| WB FireCOM | `40030`–`40039 41030`–`41039` |
| T-REX | `40100 40103 40104 40105 40106 40107 40108 40109 40110 40111 40150`–`40159` |
| T-Assault | `40101 40121`–`40129 40170`–`40179` |
| T-Capt | `40102 40112`–`40120 40160`–`40169` |
| T-FireCOM | `40130`–`40139 40180`–`40189` |
| T-SIG Corp | `40200`–`40219` |

### What was written

Mutable implementation values are not duplicated here. `TASKS.md` owns the
current verification status; inspect the live `MonsterTypeModel.csv` overlay
for the cells that would run in game.

## Project 2: SWAT as a tier-2 Brave Star enemy

SWAT (PG 25000) is the `WeightedRoll = 2` entrant at PL 3 in Brave Star's
opening group 25100. It also fills slots 1 and 3 of ambush group 25000, slot 1
of group 26000, and slots 1 and 3 of group 26100.

At shipped PL 10, SWAT has 400 HP, weapon 20009, armour 22009, talent group
100, `MaxTalentCount 2`, `InitBonus 5`, and `CritRate 30`. The assault entries
in the generic Megacorp, Warner-Braun, UltraTek, McKellen, Jupiter, Matsumoto,
and KEMCO pools reference shotgun block 22009 instead. This is a pointer
difference, not evidence for why the roster was designed that way.

## Project 3: Arrowhead identity

Arrowhead Security is FactionId 20, `FactionClass = 3` Milsec, and
`ProcGenSelect = 1`, but it owns no `MonsterGroupModel` rows. Knight Horizon
(19) also owns none and has `ProcGenSelect = 0`.

A class-pool edit affects every faction drawing that class. Giving Arrowhead a
private roster instead requires Arrowhead-owned `MonsterGroupModel` rows and
therefore exercises a clone-serving path not yet established here. See
[`cloning-rows.md`](cloning-rows.md) before attempting it.

Appearance is a separate constraint. Of 321 shipped `CosmeticGroupModel`
groups, 219 are unreferenced; the only three unreferenced groups carrying a
faction livery are Matsumoto. Brave Star has two livery groups, both referenced.
No shipped Arrowhead livery was found [measured].

## Cross-faction shipped comparisons

These observations record table shape only; they are not tuning priorities.

- Street Warrior and Free Gunner (PG 3000 and 12050) have 280 HP at PL 7,
  370/330 at PL 10, and 690/560 at PL 20. Generic Guard has 270, 330, and 560.
- Mean `MaxTalentCount` at PL 10 is: Gang 2.7, generic Megacorp 2.7, Matsumoto
  2.6, Jupiter 2.6, Brave Star 2.3, McKellen 2.2, Warner-Braun 2.2, FSC 2.2,
  UltraTek 2.0, Syndicate 1.8, and KEMCO 1.3.
- Street King (PG 3410) has 922 HP at PL 10 and 2,880 at PL 20. Guard Captain
  has 500 and 1,070 while referencing the same armour and rifle blocks.
- At PL 10, Street Sniper's weapon 6014 has 594 ballistic damage and volume 65;
  Guard Sniper's 6016 has 525 and 50. The values converge at PL 15.
- Star FWD has 400 HP at PL 10; generic Guard has 330.
- Jupiter Field Exec has 1,538 HP at PL 10 and 4,800 at PL 20. Other captain
  rows on the same armour have 500 and 1,070.
- KEMCO's PL-10 mean `MaxTalentCount` is 1.3, and KEM Guard shares the generic
  Guard stat row shape.

## Shipped pointer gaps

Two shipped references point outside their target tables [measured]:

- Hover Tank (PG 1100) PL 1 references `ArmorTypeId 22510`; `ArmorModel` has no
  22510 or 22521 in the 22500 block.
- J4 FireCOM (PG 30120) and J3 Extinguisher (PG 30160) PL 11–20 reference
  `WeaponTypeId 23140`–`23149`; the shipped `WeaponModel` block stops at 23139.

The overlay set has repair rules documented in
[`../overlays/README.md`](../overlays/README.md). Inspect the live overlay to
confirm whether those rules are currently applied.

## Open questions

- [unverified] Whether the McKellen movement-speed split is deliberate.
- [unverified] Whether `PureDamage1` bypasses armour in the engine.
- [unverified] The runtime and validator coverage for cloned
  `MonsterGroupModel` rows.

## Related

- [`tuning-enemies.md`](tuning-enemies.md)
- [`armour-groups.md`](armour-groups.md)
- [`../overlays/README.md`](../overlays/README.md)
- [`cloning-rows.md`](cloning-rows.md)
- [`power-level.md`](power-level.md)
