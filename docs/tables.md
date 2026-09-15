# Table reference

This file says which table controls what, which column is the key, and what is
worth knowing before you edit it. Column names themselves come from
`D:\ckf-data-modding\sheets\raw\<Table>.csv` — see [`workflow.md`](workflow.md).

192 tables across three databases. 191 carry a zero-arg bulk reader
(`ReadWeapons()`), which is how the dumper captures everything in one launch;
the exception is `CoreGameSaveSlotModel`.

| Prefix | Database | Meaning |
|---|---|---|
| *(none)* | `DataDb` | Shipped content. Shared by every save. |
| `Game*` | `GameDb` | This save's state. Writes land in your save file. |
| `Core*` | `CoreDb` | Profile level, spans playthroughs. |
| `*AltPathData` | — | Alternate-route variant of the base table. |
| `*Bench` | — | Safehouse workbench state. |

Which verbs are safe on which database — and why `multiply` compounds on
`Game*` — is in [`gotchas.md`](gotchas.md).

---

## What controls what

| To change… | Edit |
|---|---|
| Enemy stats | `MonsterTypeModel` |
| Enemy abilities and AI weighting | `MonsterTalentModel` |
| Squad composition | `MonsterGroupModel`, `MonsterGroupMemberModel`, `MonsterSpawnModel` |
| Weapon damage / accuracy / AP | `WeaponModel` (ids 20000+ are enemy weapons) |
| Armor values | `ArmorModel` |
| Player talent cost, range, cooldown | `TalentModel` |
| Talent upgrade tiers | `JobNodeModel` and the `EffectModel` rows it points at |
| Any stat modifier in the game | `EffectModel` |
| Character XP curve and points per level | `CharacterLevelModel` |
| Implants and their humanity cost | `ImplantModel` |
| Consumable behaviour | the `TalentId` an `ItemModel` row points at |
| Matrix deck performance | `CyberdeckModel`, `CyberdeckProgramModel` |
| Global constants not exposed in the UI | `RuleModel` — see [`game-constants.md`](game-constants.md) |
| Team Power Level per mission | `MissionPowerLevelModel` — see [`progression.md`](progression.md) |
| Drops | `MissionLootModel` — see [`loot.md`](loot.md) |
| Alarm escalation | `SecurityDeckCardModel`, `SecurityDataModel` |
| Contact pay modifiers | `ContactEffectModel` for the flat trait percentages — but the dominant term is **Trust**, on `GameContactModel`. See [`mission-rewards.md`](mission-rewards.md) |

---

## Enemies

### `MonsterTypeModel` — the enemy archetype table

The main enemy lever. `DataDb`, so no save risk and no compounding. Changes
apply to every enemy of that type in every mission. **2,427 rows**, ~120 at
every power level from 1 to 20.

PL 11–20 archetypes exist, but only `HitPoints` scales into that range —
`ActionPoints`, `MaxTalentCount` and enemy weapon damage are flat above PL 10.
Read [`power-and-progression.md`](power-and-progression.md) before lifting the
Power Level cap.

Key: `MonsterTypeId`, which is what `GameMonsterModel.MonsterTypeId` points at.

| Column | Sample | Notes |
|---|---|---|
| `PowerGroupId` | 30140 | used by `ReadMonsterTypeByPowerGroupId` |
| `PowerLevel` | 1 | tier — good for `whereMin` targeting |
| `HitPoints` | 324 | |
| `ActionPoints` | 40 | |
| `MovePoints` | 20 | |
| `CritRate` | 20 | |
| `Evasion` | 0 | |
| `ShotLimit` | 1 | shots per turn |
| `SightDistance` / `DetectDistance` | 18 / 10 | |
| `FieldOfView` / `FlankAllowance` | 90 / 120 | degrees |
| `InitBonus` / `StartInit` | 2 / 0 | |
| `MonsterTalentGroup` | 100 | → `MonsterTalentModel.MonsterTalentGroup` |
| `MaxTalentCount` | 2 | how many talents this enemy gets — high leverage, low risk |
| `WeaponTypeId` | 21001 | → `WeaponModel` |
| `ArmorTypeId` | 22202 | → `ArmorModel` |
| `EffectId` | 64158 | → `EffectModel` |
| `PatrolSpeed` / `ChasingSpeed` / `AggroSpeed` | 2.75 / 3.75 / 4.25 | `Single` |

Read-only: `MonsterName`, `MonsterDisplayName`. Presentation and AI wiring
(`ClassId`, `OutfitId`, `EntityType`, `AgentTypeId`, `AnimationLayer`,
`DetailGroup`, `EyeKit`) are writable but not balance.

Note `MonsterTypeId` does **not** share an id space with the locale's
`Monster.Name.<id>`.

### `MonsterTalentModel` — enemy abilities

Key: **`MonsterTalentId`**. `TalentId` and `TalentName` exist here but are
read-only — match on the domain id, not on `Id` or a borrowed one; see
[`gotchas.md`](gotchas.md).

Writable: `MonsterTalentGroup`, `MonsterTalentTypeId`, `MinPowerLevel`,
`MaxPowerLevel`, `FactionId`, `Weight`, `AiUseMode`, `AiUsePriority`,
`AiUseValidation`, `MinAlertLevel`, `ApUse`, `MaxCharges`, `RechargeTurns`,
`Range`, `RangeAoE`, `PureDamage`, `PhysicalDamage`, `BallisticDamage`,
`Volume`, `FilterTypeId`, `Counter`, `Token`, `TokenCount`, `TokenDuration`,
`TokenCancel`, `Summon`, `TargetEffect`, `TargetEffectDuration`.

`Weight` and `AiUsePriority` control how often the AI reaches for a talent — a
subtler difficulty lever than raw numbers. `MinPowerLevel` / `MaxPowerLevel`
gate when enemies gain access to it.

### Squad composition

`MonsterGroupModel`: `MonsterGroupId`, `MonsterGroupTypeId`, `FactionId`,
`FactionClass`, `Starting`, `Randomize`.

`MonsterGroupMemberModel`: `MonsterGroupMemberId`, `MonsterGroupId`,
`MonsterType` (→ `MonsterTypeModel`), `Slot`, `WeightedRoll`, `MinPowerLevel` /
`MaxPowerLevel`, `MinSecLevel` / `MaxSecLevel`, `Exclusive`, `Faction`.

`WeightedRoll` biases which archetype fills a slot; the Min/Max pairs gate
eligibility. *[unverified] — these semantics are read from the column names.*

### `GameMonsterModel` — live enemies (save state)

Prefer `MonsterTypeModel` unless you need to touch enemies already spawned in
the current save.

Writable: `HitPoints`, `HitPointsMax`, `Level`, `ActionPoints` (a `Single`),
`InitiativeScore`, `ArmorDamage`, `AmmoUsed`, `Status`, `MonsterTypeId`,
`DisplayName`, `FactionId`, `IsFriendly`, `SpecialRule`, `WakeGroup`,
`AiAlarmLevel`, `HuntTurns`, patrol fields, and position/rotation floats.

`DisplayName` is carried on the row, which makes it the practical way to target
one specific enemy.

---

## Gear

### `WeaponModel`

Key: `WeaponId`. **No column says whether a row is player or enemy gear — the
only thing that makes a row enemy gear is that `MonsterTypeModel` points at
it.** Id ranges do not separate the two groups cleanly; the canonical split, and
the `whereMin` / `whereMax` pairs that express it, is in
[`../overlays/_reference/player-vs-enemy-gear.md`](../overlays/_reference/player-vs-enemy-gear.md).

Every weapon has two firing modes with a full stat block each. **Write the
suffixed columns** — see [`gotchas.md`](gotchas.md).

| Per-mode (writable) | Sample (mode 1 / 2) |
|---|---|
| `ModeType1` / `2` | 3 (Burst Fire) / 4 (Full Auto) |
| `BallisticDamage1` / `2` | 260 / 168 |
| `PureDamage1` / `2` | 73 / 46 |
| `Accuracy1` / `2` | 69 / 74 |
| `ActionPoints1` / `2` | 20 / 30 |
| `AmmoUsed1` / `2` | 1 / 2 |
| `RecoilRate1` / `2` | 28 / 48 |
| `ArmorCritRate1` / `2` | 25 / 27 |
| `AngleFire1` / `2` | 62 / 60 |
| `OptimalRangeA1` / `A2` | 5 / 5 |
| `OptimalRangeB1` / `B2` | 24 / 24 |

Weapon-wide, writable: `Rarity`, `PowerLevel`, `Cost`, `MaxRange`, `FAShots`,
`ReloadActionPoints`, `ReloadSize`, `ReloadClipMax`, `CritMultiBase`,
`CritMultiStealth`, `ShotVolume`, `WeaponClass`, `FactionId`, `PrecisionRule`,
`SpecialRule`, `WeaponEffect`, `Locked`, `ServiceOptionId`.

Read-only: `Id`, all `*Name` columns, `IsHeavyWeapon`, `AmmoReady`,
`RarityType`, and every unsuffixed combat stat.

### `ArmorModel`

Key: `ArmorId`, which matches the locale directly (`ArmorId` 5 = `ArmorName.5`).

Writable: `BallisticArmor`, `PhysicalArmor`, `BallisticArmorDegraded`,
`PhysicalArmorDegraded`, `MaxArmorPoints`, `ArmorPoints`, `CarryCapacity`,
`MovementRate`, `InitPenalty`, `Cost`, `PowerLevel`, `ArmorClass`, `Rarity`,
`ArmorEffectId`, `FactionId`, `ServiceOptionId`.

### `ImplantModel`

Key: **`ImplantTypeId`** — there is no `ImplantId`.

Writable: `ImplantClass`, `ImplantLevel`, `ImplantSlot`, `ImplantConflictId`,
`ImplantStress`, `ImplantDVMult`, `ImplantDVScore`, `Deactivated`,
`ImplantEffectId`, `MatrixEffectId`, `ArmorRestriction`, `InstallTime`,
`ImplantTalentId`, `BackstoryGroup`, `InstallJobId`, `ServiceOptionId`,
`Rarity`, `PowerLevel`, `Cost`.

`ImplantTraitGroup`, `EffectTriggerType`, `TriggerEffectId` and `WoundTraitId`
are 0 on all 198 rows, so they are not levers on shipped content.

`ImplantStress`, `ImplantDVMult` and `ImplantDVScore` are the humanity-cost
levers; `InstallTime` is downtime in days. Pair with `RuleModel` ids 13 and 58
(`Max Implants`, `Knight Max Implants`).

### `ItemModel`

Key: `ItemTypeId`. Writable: `ItemClass`, `LeverageClass`, `Rarity`,
`PowerLevel`, `Cost`, `TalentId`.

**A consumable's behaviour lives in a talent row.** Retuning what a medkit does
means editing the `TalentModel` row its `TalentId` names, not the item.

### `CyberdeckModel`

Key: `CyberdeckId`. The Matrix performance knobs are `DeckRating`, `IOSpeed`,
`ActiveMem` and `MaxProgram`; also `ApBonus`, `Armor`, `Rarity`, `PowerLevel`,
`Cost`. Cap on programs per deck is `RuleModel` id 48.

---

## Player talents

### `TalentModel`

Player talents only — enemy talents are `MonsterTalentModel`. Key: `TalentId`.

| Group | Columns |
|---|---|
| Cost & cadence | `ApCost`, `RechargeTurns`, `MaxCharges`, `TurnMaxUses`, `TeamTurnMaxUses`, `LevelCost`, `StressChance`, `Volume` |
| Reach | `Range`, `RangeAoE` |
| Damage | `PureDamage`, `PhysicalDamage`, `BallisticDamage`, `DroneDamage` |
| Effects & duration | `TargetEffect`, `TargetEffectDuration`, `SelfEffect`, `SelfDuration`, `MatrixEffect`, `MatrixDuration`, `Token`, `TokenCount`, `TokenDuration` |
| Flags & wiring | `TalentTypeId`, `TalentLevel`, `TalentIsActive`, `TalentIsCyber`, `TalentReqCyber`, `TalentIsFace`, `TalentIsMatrixOnly`, `ActionId`, `TeamGlobal`, `Weapon`, `WeaponMode`, `PreReq`, `FilterTypeId`, `GameEventTrigger`, `TargetType`, `Counter` |

Read-only: `TalentName`, every `Adjusted*` column, `TokenCancel`.

`TalentStringKey` (e.g. `Job.Talents.Active.SecurityDeviceAny`) is the bridge
into the locale JSON, so a talent's displayed name and description can be
rewritten to match a mechanical change.

### `JobNodeModel` — talent upgrade tiers

1,525 rows. Key: `JobNodeId`. `NodeReq1` is the prerequisite node, so the chain
of `NodeReq1` values reconstructs the tree. `SubTree` groups tiers under their
base node; `SubQuad` is the branch within it, taking values 1, 2 or 3 (0 on base
nodes).

There are **three kinds of node**, and each is retuned in a different place.
Worked example, Strike Zone (nodes 11320–11325):

```
11320  Strike Zone     JobId=11  NodeReq1=11402  NodeTalent1Id=11013   BuyCost=1
11321  Strike Zone 1   NodeReq1=11320  NodeTalentAdjustmentId=11013  RechargeTurns=-1
11322  Strike Zone 2   NodeReq1=11321  NodeTalentAdjustmentId=11013  TalentRangeAoE=4
11323  Strike Zone 3   NodeReq1=11322  NodeTalentAdjustmentId=11013  MaxCharges=1
11324  Strike Zone 4   NodeReq1=11320  NodeTalentTriggerId=11013  NodeTalentTriggerEffect=11119
11325  Strike Zone 5   NodeReq1=11324  NodeTalentTriggerId=11013  NodeTalentTriggerEffect=11120
```

| Kind | Identified by | Retune by editing |
|---|---|---|
| **Base** | `NodeTalent1Id` — grants the talent | the `TalentModel` row |
| **Adjustment tier** | `NodeTalentAdjustmentId` + a stat column on the node itself | the `JobNodeModel` row |
| **Trigger tier** | `NodeTalentTriggerEffect` — carries no stats | the `EffectModel` row it points at |
| **Travel** | `NodeEffect1Id`, no `SubTree` — a permanent effect | the `EffectModel` row it points at |

Travel nodes are the filler between talents, mostly named `Left n` /
`Right n` / `Center n`: 334 on the twelve player jobs, all `BuyCost` 1, every
one granting +1 of an attribute, usually plus one small stat. Each job's
`Unlock: Extra Item Carry` capstone is the same kind of node (`ActionPoints` 1,
i.e. 0.1 AP, on most jobs plus a job-specific stat) and roots the `Carry Generic` /
`Carry Tech` chain. *[measured]*

`NodeTalentTriggerType` is 1 (`OnChargeUsed`) on all 275 trigger tiers.
Five base nodes have `NodeTalent1Id = -1` (Claw Master, Laser Master, Pulse Gen
Master, Blast Radius, Metabolize); their tiers adjust a talent-group row
instead — `TalentId` 1 Any Grenade, 3 Any Combat Drug, 20–22 the cyber weapons.
*[measured]*

```json
{ "model": "JobNodeModel", "where": { "JobNodeId": 11321 },
  "set": { "RechargeTurns": -2 } }
```

**To find any talent's nodes:** get the id from `JobNode.Name.<id>` in the
locale file (see [`workflow.md`](workflow.md)), read the next few ids as its
tiers, and follow any `NodeTalentTriggerEffect` into `EffectModel.csv`.

### `CharacterLevelModel` — the XP curve

129 rows: three `LevelType` values — **1, 2 and 6** — with 43 rows each covering
levels 1–43. Columns: `Id`, `Level`, `Xp`, `Job`, `Talent`, `LevelType`.

⚠️ **Off by one against the cap.** `RuleModel` id 1 (`Max Character Level`) is
**42**, so a 43-row band is one row longer than the cap allows. Most likely one
row is a level-0 or seed row and the reachable levels are 1–42, but that has not
been checked against a dump — *[unverified]*. If you retune the curve, confirm
which row is the spare before assuming row 43 is live. See
[`game-constants.md`](game-constants.md).

```
Id  Level   Xp    Job  Talent  LevelType
 1     1      -     7     5        1
 2     2    100     9     5        1
 5     5    400    14     6        1
10    10   1500    22     7        1
14    14   3500    26     8        1
```

`Xp` is the threshold to reach that level. `Job` and `Talent` are the point
allocations granted, and grow independently of the XP curve. Filter on `LevelType`
to touch one progression only. Match `Id` for one row, `Level` to hit that level
across all three.

The level cap itself is `RuleModel` id 1.

### `CharacterTypeModel` — nothing to tune

Five rows, and they are the **player classes**: Knight, Runner, Drone, Hund,
Cybercat. Columns are `CharacterTypeId`, `CharacterClass`, `TypeName`,
`TypeDesc` — no numbers, so there is nothing here to tune. It is read only
during character creation, which is why it stays silent in a normal session, and
it is **not** an enemy table — enemy archetypes are `MonsterTypeModel`. A
`multiply` aimed at it is a known dead end; see [`gotchas.md`](gotchas.md).

### `TraitModel`

Key: `TraitId`. Writable: `TraitGroup`, `TraitClass`, `EffectTypeId` (→
`EffectModel`), `MatrixEffectTypeId`, `TraitLevel`, `HealTime`, `HealCost`,
`TraitScore`, `TagMatch`. Read-only: `TraitNameWithLevel`, `TraitDesc`.

`HealTime` and `HealCost` are 0 on most rows, so gate with
`"whereMin": { "HealCost": 1 }`.

---

## `EffectModel` — the master modifier table

1,678 rows, 74 columns after trimming. How essentially every buff, debuff,
talent, implant and armor effect modifies a character. Key: `EffectId`.

Seven of the columns below ship as 0 on every row and so are trimmed out of the
CSV: `DeathSave`, `ActionPointsPet`, `AttackDetectRangeReduction`, `CommsOut`,
`Immobilized`, `LevePoints`, `TalentLimit`. They are writable, but nothing in
the shipped game uses them.

| Group | Columns |
|---|---|
| Attributes | `AttStrong`, `AttFast`, `AttWill`, `AttTech`, `MaxHitPoints` |
| Accuracy | `AccuracyRifle`, `AccuracyPistol`, `AccuracyAssault`, `AccuracyCloseCombat`, `AccuracyDrone`, `StealthAccuracy`, `MeleeAttack`, `RangedAttack`, `OptimalRange`, `FiringArc` |
| Crit | `CritRate`, `CritRateStealth`, `CritRateStreak`, `CritMultiBase`, `CritMultiStealth`, `CritVulnerable` |
| Damage | `PhysicalDamage`, `BallisticDamage`, `PureDamageBallistic`, `PureDamageMelee`, `FullAutoDamage`, `DroneDamage` |
| Defence | `PhysicalArmor`, `BallisticArmor`, `PureArmor`, `ArmorCrit`, `DmgReduction`, `Evasion`, `CoverBonus`, `SafeArmor` |
| Saves | `DeathSave`, `WoundRes`, `StressRes`, `DumpShockRes` |
| Detection | `SightRange`, `DetectRangeReduction`, `AttackDetectRangeReduction` |
| Movement | `MoveSpeed`, `MoveSpeedDebuff`, `MoveSpeedMitigate`, `RecoilRate`, `RecoilBonus` |
| Economy of action | `ActionPoints`, `ActionPointsPet`, `MovePoints`, `InitBonus` |
| Status flags | `Stunned`, `Immobilized`, `Invisible`, `Invulnerable`, `Silent`, `OverwatchBreak`, `CommsOut`, `DroneJammed`, `PathRevealed`, `HitStreak` |
| Meta | `Heals`, `EffectHealType`, `Duration`, `Instant`, `XpBonus`, `LevePoints`, `TalentLimit`, `Legwork`, `MinLoyalty`, `SpecialCode`, `SpecialValue`, `SpecialMerge`, `EffectClassification`, `EffectClearType`, `EffectPurgeType`, `EffectGroupId`, `EffectOwner` |

Read-only: `EffectName`, `NeedsTraitPostProcessing`.

**Almost every column on any given row is 0**, so a broad `multiply` across this
table silently does nothing. Use `set` or `add` against a specific `EffectId`.

`EffectGroupId` ties a tier effect back to its parent — Strike Zone's tier
effects 11119 and 11120 both carry `EffectGroupId = 11013`.

`SpecialCode` / `SpecialValue` / `SpecialMerge` are how Face talents modify
mission pay. The shipped codes, the merge modes and what flipping one costs you
are in [`mission-rewards.md`](mission-rewards.md).

### Enum-coded columns

Il2CppInterop keeps enum constants, so every enum's values can be read offline
from the constant table of `BepInEx/interop/CoreRPG_v1.dll`. These were read
that way *[measured]*; which column uses which enum is matched by name and by
fitting every talent checked *[fitted]*.

| Column | Enum | Values |
|---|---|---|
| `EffectModel.EffectHealType` | `EffectHealType` — what `Heals` means | 1 Health, 2 Armor, 3 Stress, 4 Recoil, 5 AlarmSub, 6 Alarm, 7 Reload, 8 OverwatchToken, 9 HealthOverTime, 10 DamageOverTime, 11 BladeAmmo, 12 PureDamage, 13 CharacterAlarmLevel, 14 DroneDamageOverTime, 15 ReduceHealth |
| `EffectModel.EffectClearType` | `EffectClearType` | -1 DoNotClearMove, 1 Invisibility, 2 Invulnerable, 3 Move, 4 AttackOrMove, 5 EndMove, 6 EndOverwatch, 7 Healing, 8 Matrix, 9 Attack, 10 MoveOrMiss, 11 EndDualSMGStreak, 12 StunBreak, 13 AttackedByEnemy, 14 HitByEnemyOrMiss, 15 SecurityDispatch, 16 PurgeDebuff, 17 TakeDamage, 18 TakeDamageOrAttack, 19 MatrixChangeNode, 20 TakeDamageDebuffOrAttack, 21 CriticalHit |
| `EffectModel.SpecialCode` | `EffectSpecialCode` (93 values) | names match the `Job.Effects.SpecialCodes.*` locale keys, e.g. 1 Disorient, 3 EnemyShootsOwn, 10 LifeStealing, 18 SkipOverwatch, 22 IgnoreAllRecoil, 27 InvisibleWhileNotMoving |
| `TalentModel.GameEventTrigger` | `GameActionType` | 2 OnDying, 3 OnTakeDamage, 5 OnTakeMeleeAttack, 6 OnDealDamage, 7 OnDealCritical, 11 OnAlarmRise, 12 OnKill, 13 OnKillStealth, 14 OnKillDrone, 16 OnMoveAfterAttack, 21 OnMissed, 23 OnMatrixKill, 26 OnKillDroneTeam, 27 OnDroneAttack, 28 OnMatrixDumpShock, 29 OnTakeDamageInstant, 30 OnSpottedInstant, 31 OnDebuffDOT, 32 OnAttackUnderOverwatch, 33 OnKillCyberWeapon, 34 OnUsePulseGen, 35 OnMatrixLowConnection |
| `TalentModel.FilterTypeId` | `TalentFilterType` | 1 DroneOnly, 2 AnyDevice, 5 EnemyNonCombat, 6 NeedHealing, 7 ZeroArmor, 8 NotSelf, 9 NotVisibleToEnemy, 10 TargetIsVisible, 11 EnemyNonCombatVisible, 12 BodyHasTimer, 13 BodyIsUnknown, 15 NotDrone, 16 NotDroneOrHeadHunter, 17 NeedHealArmor, 20 FloorVisible, 21 CorpseVisible, 22 DeviceVisible, 23 DeviceCausesDmg |
| `TalentModel.Token` | `TalentTokenType` | players only 4, 7, 19; enemies only 5, 8, 10, 14, 15; both 6, 9, 12, 13; 1 Overwatch, 2 SmokeGrenade, 3 DeflectionShield, 11 RefractWall, 16 LineCrawler |
| `TalentModel.PreReq` | `TalentPreReq` | 1 NeedHealing, 2 NeedReloadPrimary, 3 NeedAlarmSub, 4 NeedArmorHealing, 5 AllowedOnDowned, 6 NeedsReloadSpecial, 7 OnStreak, 8 NotOnStreak, 9 SpottedByEnemy, 10 HasCover, 11 HealthAdvantage, 12 OnDualSMGStreak |
| `JobNodeModel.NodeTalentTriggerType` | `TalentTriggerType` | 1 OnChargeUsed, 2 OnChargeGain, 3 OnChargeFull, 4 OnChargeZero |

Consequences worth knowing: `Heals = 50` on Tox-Cloud is 50 damage per turn
(type 10), and Burn Surge's `Heals = 20` costs 20 HP (type 15). `FilterTypeId =
1` is on EMP, Leech, Quantum Assault, Disentangle, Downed Shields, N-Coat
Bullet, Counter Static, Flash Hack and Upchain. Morass (12) and Tox-Cloud (13)
use both-sides tokens.

**Attributes** (`AttFast` … `AttTech` above) convert as the locale's
`Att.*.BonusesDesc` strings state *[measured, game text]*: Reaction +1% Move
Speed and +1 Initiative per 5; Strength +1% Kinetic Dmg as extra Pure, −2%
Recoil Rate, +1% Wound Res per 2; Will +1% Cybernetic Weapon Dmg, +2% Stress
Res, +1% Built-in Armor per 2; Tech +1% Crit, +2% Dmg vs Drones, +1 Matrix AP.

---

## Full inventory — 192 tables

<details>
<summary>Loot and rewards (5)</summary>

`GameMissionLootModel`, `GameMissionRewardModel`, `LootBoxAltPathDataModel`,
`LootBoxDataModel`, `MissionLootModel`
</details>

<details>
<summary>Enemies and spawns (15)</summary>

`GameMonsterBodyBoneModel`, `GameMonsterBodyModel`, `GameMonsterEffectModel`,
`GameMonsterEventModel`, `GameMonsterModel`, `GameMonsterOrderModel`,
`GameMonsterTalentModel`, `GameMonsterTalentTokenModel`,
`MonsterGroupMemberModel`, `MonsterGroupModel`, `MonsterSpawnAltPathDataModel`,
`MonsterSpawnModel`, `MonsterTalentModel`, `MonsterTypeModel`,
`PlayerSpawnModel`
</details>

<details>
<summary>Player characters (27)</summary>

`CharacterLevelModel`, `CharacterTypeModel`, `ContactTraitModel`,
`GameBenchCharacterMedicalModel`, `GameBenchCharacterModel`,
`GameBenchCharacterPetModel`, `GameCharacterCosmeticFieldModel`,
`GameCharacterEffectModel`, `GameCharacterImageModel`,
`GameCharacterImplantModel`, `GameCharacterJobModel`,
`GameCharacterJobNodeModel`, `GameCharacterLoadoutModel`,
`GameCharacterLogModel`, `GameCharacterModel`, `GameCharacterTagModel`,
`GameCharacterTalentAdjustmentModel`, `GameCharacterTalentModel`,
`GameCharacterTalentTokenModel`, `GameCharacterTalentTriggerModel`,
`GameCharacterTraitModel`, `GameContactTraitModel`, `ImplantModel`,
`JobNodeModel`, `SharedCharacterConfigModel`, `TalentModel`, `TraitModel`
</details>

<details>
<summary>Gear (21)</summary>

`ArmorModel`, `GameArmorModel`, `GameBenchArmorModel`, `GameBenchGearModel`,
`GameBenchWeaponModModel`, `GameBenchWeaponModel`, `GameGearModel`,
`GameItemModel`, `GameWeaponCosmeticFieldModel`, `GameWeaponModModel`,
`GameWeaponModel`, `GearModel`, `ItemModel`, `LoadoutGameArmorModel`,
`LoadoutGameGearModel`, `LoadoutGameWeaponModModel`, `LoadoutGameWeaponModel`,
`Weapon3DAssetModel`, `WeaponClassModModel`, `WeaponModModel`, `WeaponModel`
</details>

<details>
<summary>Effects (5)</summary>

`ContactEffectModel`, `EffectModel`, `GameMatrixEffectModel`,
`GameMatrixIcEffectModel`, `MatrixEffectModel`
</details>

<details>
<summary>Matrix (22)</summary>

`CyberdeckModel`, `CyberdeckProgramModel`, `GameCyberdeckModel`,
`GameCyberdeckProgramModel`, `GameMatrixConnectionModel`,
`GameMatrixHackLogModel`, `GameMatrixHackStateModel`,
`GameMatrixHostAccountModel`, `GameMatrixHostBlueprintModel`,
`GameMatrixHostFileModel`, `GameMatrixHostModel`, `GameMatrixICModel`,
`GameMatrixLinkModel`, `GameMatrixNodeModel`, `GameMatrixRemoteDeviceModel`,
`MatrixDeckCardModel`, `MatrixFileModel`, `MatrixFileSetModel`,
`MatrixHostDataModel`, `MatrixICModel`, `MatrixNodeTypeModel`,
`SecurityDeckCardModel`
</details>

<details>
<summary>Missions (30)</summary>

`BlockConditionModel`, `BlockModel`, `DoorAltPathDataModel`, `DoorDataModel`,
`GameBlockStateModel`, `GameDoorModel`, `GameMissionAdvantageModel`,
`GameMissionAdvantageSegmentRoomModel`, `GameMissionBlockModel`,
`GameMissionLogModel`, `GameMissionModel`, `GameMissionRequirementModel`,
`GameMissionRoomFlagModel`, `GameMissionRoomModel`, `GameMissionScoreModel`,
`GameMissionSegmentModel`, `GameMissionStateModel`, `GameRoomStateModel`,
`GameSafehouseBlockModel`, `MissionAdvantageMatchModel`,
`MissionAdvantageModel`, `MissionBlockModel`, `MissionModel`,
`MissionPowerLevelModel`, `MissionRoomModel`, `ObjectiveDataModel`,
`RoomTypeModel`, `TerminalAltPathDataModel`, `TerminalDataModel`,
`TriggerDataModel`
</details>

<details>
<summary>Contacts and factions (12)</summary>

`BackstoryModel`, `ContactBackstoryModel`, `ContactPowerLevelModel`,
`ContactServiceModel`, `ContactTypeModel`, `FactionModel`,
`GameContactLogModel`, `GameContactModel`, `GameContactScoreModel`,
`GameContactServiceModel`, `GameContactTagModel`, `GameFactionRankModel`
</details>

<details>
<summary>Economy and crafting (14)</summary>

`BankAccountModel`, `BlueprintModel`, `CraftingSupplyModel`,
`GameBankAccountModel`, `GameBenchCraftingSupplyRecordModel`,
`GameBlueprintModel`, `GameCraftingSupplyModel`, `GameSafehouseDecoModel`,
`GameSafehouseModel`, `GameSafehouseModuleModel`,
`GameSafehouseSubModuleModel`, `GameSafehouseTaskLogModel`,
`GameSafehouseTaskModel`, `SafehouseModuleModel`
</details>

<details>
<summary>Story and journal (9)</summary>

`DialogModel`, `DialogQuipModel`, `GameStoryNodeModel`,
`GameStoryReminderModel`, `JobModel`, `JournalModel`, `LegworkModel`,
`StoryMatchModel`, `StoryNodeModel`
</details>

<details>
<summary>Security (4)</summary>

`GameSecurityDeviceModel`, `GameSecurityEventModel`,
`SecurityAltPathDataModel`, `SecurityDataModel`
</details>

<details>
<summary>Cosmetic (5)</summary>

`CosmeticAdjustmentModel`, `CosmeticColorModel`, `CosmeticGroupModel`,
`CosmeticModel`, `UnityMapModel`
</details>

<details>
<summary>Meta and save state (19)</summary>

`AchievementModel`, `CoreGameDataModel`, `CoreGameSaveSlotModel` — **no bulk
reader**, `CoreGameSaveSlotRefModel`, `CoreGameSyncConfigModel`,
`GameCombatLogModel`, `GameDataModel`, `GameDifficultyCoreModel`,
`GameDifficultyModel`, `GameFileDownloadModel`, `GameLogModel`, `GamePetModel`,
`GameScoreAchievementModel`, `GameScoreModel`, `GameScorePositionModel`,
`GameStateLinkModel`, `GameStateModel`, `RuleModel`, `TagModel`
</details>

<details>
<summary>Other (4)</summary>

`GameBenchItemModel`, `GamePlayerBodyBoneModel`, `GamePlayerBodyModel`,
`LoadoutGameItemModel`
</details>

## Tables that stay empty, and why

**43 `Game*` tables are empty at the main menu.** They are genuinely empty until
a save is open, and several until a mission is *running*. How to dump them is in
[`workflow.md`](workflow.md).
