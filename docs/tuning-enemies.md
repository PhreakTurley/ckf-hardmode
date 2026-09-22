# Tuning enemies

Use this page to locate enemy-stat, gear, appearance, and roster-pool surfaces.
It explains what has been measured about each path; it does not record current
tuning values. The CSV format is in [`overlays.md`](overlays.md), row insertion
is in [`cloning-rows.md`](cloning-rows.md), and validation steps are in
[`workflow.md`](workflow.md).

The live files are under `BepInEx\config\ckf.hardmode.d\`; inspect them directly
for current values. Tier ids per block are in
`overlays/_reference/gear-blocks.md`;
which ids are enemy-facing is in
`overlays/_reference/player-vs-enemy-gear.md`.

| To change | Where |
|---|---|
| Enemy stats: HP, crit, AP, talents | `MonsterTypeModel.csv`, one line per archetype row |
| What a gear tier is worth | `ArmorModel.csv`, `WeaponModel.csv` |
| Which tier an enemy carries | the `WeaponTypeId` / `ArmorTypeId` cells in `MonsterTypeModel.csv` |
| Stats no archetype column holds: damage %, armour, evasion | `EffectModel` rows, via a new overlay or JSON rules file in `ckf.hardmode.d/` |
| Who fills a roster slot, and how often | `MonsterGroupMemberModel`, likewise |

Column names come from the current dump's `<Table>.csv`. `Aug21Sheets/` is stale.

## Archetype stats in `MonsterTypeModel.csv`

One line per archetype row, `_comment` naming the PowerGroup, power level and
shipped `EffectId`. `MonsterTypeModel` ships rows at every level 1–20, so nothing
here needs a clone.

Columns that mislead:

- **`Evasion` is dead** on this table: 0 on 2,424 of 2,427 rows [measured].
  Enemy evasion comes from the `EffectId` stat block.
- **`ShotLimit` is gated by `ActionPoints`.** A shot costs AP, so `ShotLimit`
  above what the AP pays for buys nothing: 817 archetypes carry `ShotLimit` 3 at
  `ActionPoints` 40 against a weapon costing 20 [measured]. Move the two
  together. Only Hover Tank and H-Support scale AP in the shipped data, reaching
  60 at PL 11 [measured].
- **Leave `EffectId` blank where the dump value is 0** ("no stat block").
  `make_enemy_overlays.py` writes the dump value into `_comment` as `eff:N`.
  A literal 0 would be read by the
  validator as a pointer at a missing row.
- [unverified] `MovePoints` has been described as distance per action point,
  rather than a separate movement budget. No cited runtime capture establishes
  that conversion here.
- `SpecialMovementRule` and `SpecialRule` use the static `MonsterSpecialRule`
  names resolved in `_id_constants.csv`: `ClearMoveRule` -2, `ClearVIP` -1,
  `Standard` 0, `VIP` 1, `Bodyguard` 2, `Stationary` 3,
  `AssassinationTargetStationary` 5, `Flying` 6, `EnemyRefuseToMove` 7,
  `AlwaysGoesFirst` 8, and `VIPFightsBack` 9. There is no 4. The shipped table
  uses these values [measured, `sheets/raw/MonsterTypeModel.csv`, 2,427 rows]:

  | Column | Value | Rows | Meaning | Who |
  |---|---|---|---|---|
  | `SpecialRule` | 1 | 63 | `VIP` | VIP, Defector, Lucretia, Brauk Executioner |
  | `SpecialRule` | 5 | 21 | `AssassinationTargetStationary` | Wireghost, Head Researcher |
  | `SpecialMovementRule` | 3 | 40 | `Stationary` | every MG Turret (`EntityType` 8 Turret) |
  | `SpecialMovementRule` | 6 | 104 | `Flying` | every Hover Tank (`EntityType` 7 DroneFlying) |
  | `SpecialMovementRule` | 7 | 20 | `EnemyRefuseToMove` | Rhino / Sniper Survivor |

  Everything else is 0. `Bodyguard`, `AlwaysGoesFirst` and `VIPFightsBack` appear on no shipped row. The 20 `EnemyRefuseToMove` rows are exactly the 20 rows carrying `StartInit` 42 [measured]. `EntityType` resolves the same way: Human 1, Drone 3, Dog 4, Cat 5, DroneFlying 7, Turret 8 - there is no 2 or 6. Neither column is in the `MonsterTypeModel.csv` overlay header; adding one means adding it to `make_enemy_overlays.py`'s declared column set.
- **0 means the stat is absent, not small.** Leave zeros alone.

### `EffectId`

`EffectId` is the widest lever for stats this table has no column for: damage,
armour, `DmgReduction`, `Evasion`, `OverwatchBreak`, `CoverBonus`. An effect row
is a shared reference, so pointing a PL 15+ archetype at a row another archetype
uses costs nothing and does not change the other owner. 1,116 of 2,427
archetypes carry `EffectId` 0 [measured].

No monster-referenced `EffectModel` row sets a damage column: all 25 leave
`BallisticDamage`, `PhysicalDamage`, `PureDamage*` and `FullAutoDamage` at 0.
Whether those apply to a monster's attack has never been tested. Values
elsewhere in the table cluster at 3/5/10/15/20/25 against weapon damage of
144–500, which reads as percent [unverified].

## Weapon tiers in `WeaponModel.csv`

Twenty blocks of twenty tiers; each row's `_comment` names its block. The shipped
PL 1–10 shape each tier continues is in the dump's `WeaponModel.csv`.

Columns that carry a weapon: `BallisticDamage1`, `PhysicalDamage1`,
`PureDamage1`, `Accuracy1`, `ActionPoints1`, `ArmorCritRate1`, `RecoilRate1`,
`ShotVolume`, `FAShots`, `MaxRange`, and the mode-2 twins. Always write the
suffixed columns; the unsuffixed ones (`BallisticDamage`, `Accuracy`, …) are
aliases that discard writes ([`gotchas.md`](gotchas.md)).

Shipped slope: PL 1–10 ladders rise about 1.6x in damage, from 1.36x on the
Guard Rifle to 2.23x on the WB Revolver [fitted].

`WeaponModel.PowerLevel` is cosmetic. A tier's position is its id and the
pointer in `MonsterTypeModel.csv`.

## Armour

`ArmorModel.csv`: nine blocks, same shape.

Armour is the percentage of damage prevented, and the engine caps damage
reduction at 95%. A plain multiply is wrong: 50 → 75 halves damage taken, and so
does 80 → 90, so multiplying improves a high-armour family far faster than a low
one and pushes the top of a ladder toward immunity. Work in the gap:

```
new = 100 - (100 - old) * factor
```

A factor of 0.65 turns 50 into 67.5: that tier lets 32.5% through instead of
50%. Returns diminish on their own: 80 → 87, 85 → 90. Above the 95% cap, extra
armour buys resistance to degradation, which has no ceiling. The JSON form is
`gapFrom` ([`rule-engine.md`](rule-engine.md#gapfrom)).

- **0 means the stat is absent.** Guard Standard carries `BallisticArmor` 0; only
  its `*Degraded` values matter.
- **`ArmorPoints` 0 is not evidence of absent armour.** All 319 shipped
  `ArmorModel` rows read `ArmorPoints 0` while `MaxArmorPoints` runs 1–5
  [measured]. Compare the four armour-value columns and `MaxArmorPoints`; do not
  use `ArmorPoints` alone to compare archetypes.
- **`MaxArmorPoints` runs 1 to 4 across a whole shipped family** [measured].
  There is no room for a per-level slope; set each tier by hand.
- `ArmorModel.PowerLevel` is cosmetic: the developers cloned the last three rows
  to make Lvl8–10 without updating it.

## Appearance: `MonsterTypeModel.OutfitId`

`OutfitId` is a pointer into `CosmeticGroupModel.GroupId`, not an asset id. All
102 values the shipped archetypes use resolve to a row set there [measured], and
the column is constant across a PowerGroup's whole PL 1–20 ladder, so changing a
look means editing all twenty of that group's rows.

An appearance group is a recipe: one `CosmeticGroupModel` row per
`(CosmeticFieldType, CosmeticValue)` pair. Twenty-six field types are pointers
into `CosmeticModel`, whose `Resource` column holds the asset path
(`Players/Outfits/Male_Outfit_3`, `Players/Heads/head_m_ks1002`); roughly thirty
more carry a colour packed as decimal RRRGGGBBB (`155186255` is 155, 186, 255).

**321 groups exist and archetypes use 102**, so 219 are already built and unused;
the free ones in the 200–499 band draw on the same outfit pool the monster groups
do. A number with no `GroupId` behind it is not a new look, so repointing at a
free group is the cheap move and inventing an id is not a move at all.

Repointing is proven [measured, Run68]: PG 40003 WB FireCOM 351 → 232 and PG 530
Suppressant 363 → 210, twenty rows each, both visibly different in the mission.

**Editing an existing group does nothing** [closed]. Run70 loaded one rule
against row `Id` 1055 (`CosmeticGroupModel: 1 rule(s), no index`), spawned eight
enemies wearing that group, and logged **zero** trace lines for the table while
nine other tables logged thousands. No "no materializer" warning, so the hook was
installed and simply never saw a row: `GetRowCosmeticGroupModel` is not on the
path that dresses a spawned enemy.

**A CLONED group does not work, and pointing at one is fatal** [closed, Run72].
Three arms ran at `WeightedRoll 3000`, PL 11-20, against Warner-Braun: ARM A
repointed PG 40003 WB FireCOM at cloned GroupId `2200`, ARM B repointed PG 40000
WB Guard at cloned GroupId `900351`, and the CONTROL repointed PG 40002 WB
Assault at existing free group `211`. All sixty `OutfitId` edits fired
(`OutfitId 351 -> 2200`, `225 -> 900351`, `227 -> 211`, twenty traces each).
Mission load reached `TurnCommandSpawnMonsterStarting` ten times, threw **seven**
`NullReferenceException`s, and died two lines after `TurnCommandLoadLevelFinalize`
at the intro block event — the black screen. Run70, the same mission with only
existing-group repoints, had **zero** NREs and ran eighty-two lines past that
same point.

Not one `RowClone: built CosmeticGroupModel` line appeared, and neither did the
once-per-table "checking each new id is unused" advisory that `MonsterGroupMemberModel`,
`WeaponModel` and `ArmorModel` each printed. `RowClone` never attempted a build,
because nothing on the game's path ever asked for those ids.

The zero-hit reader trace from Run72 does **not** establish that the table was
never read. [measured, Run76] `CosmeticGroupModel` is also materialized by raw
SQL plus the static `GetRow*Model`, bypassing the three named readers. That
materializer fired for the player's character on the safehouse screen and did
not fire while ten enemies were dressed. The instrument can therefore separate
"the reader was bypassed" from "the enemy path requested no mutable row."
[measured, Run69 `FindMethods`] The named cosmetic reader surface is on
`RPG.Database.DataDb`; that method inventory does not expose raw-SQL callers.

**Repointing to an EXISTING group is the only lever, and the palette is closed**
at the 321 shipped groups (102 in use, 219 free). Do not point `OutfitId` at an
id that is not in `sheets/raw/CosmeticGroupModel.csv`.

**Named leaf-table readers do not serve enemy appearance** [closed, Run73]. All
seven cosmetic readers were traced across boot, safehouse and a full mission
load: `ReadCosmeticGroups`, `ReadCosmeticGroup(Int64)`, `ReadCosmeticGroupIds`,
`ReadCosmetics`, `ReadCosmetic(Int64)`, `ReadCosmeticColors`,
`ReadCosmeticColor(Int64)`. Sixteen hits, **all of them
`ReadCosmetic(4500)` / `ReadCosmetic(4501)`** — `Avatars/Male_avatar` and
`Avatars/Female_avatar`, `CosmeticType` 25, the two fallback portrait avatars —
and every one fired in the safehouse or at `GameManager:Awake`, none during the
ten `TurnCommandSpawnMonsterStarting` calls. This is silence from those named
readers only, not evidence that no SQL/materializer path ran. The run was clean:
0 NREs and the intro cutscene played.

**Conclusion.** [closed, Runs 68, 70, 72, 73, 76] Repointing `OutfitId` to an
existing shipped group works. Editing a shipped group's rows does not affect an
enemy, and pointing at a cloned group is fatal. The supported palette is
therefore the 321 shipped GroupIds; do not point at an id absent from
`sheets/raw/CosmeticGroupModel.csv`.

### Faction-livery groups

`CosmeticFieldType` 23 is the faction livery material, and the developers build
per-faction looks as sibling groups off one base. Group 246 is group 300 with a
single cell changed: `Male_Outfit_4_Matsumoto_MAT` where 300 has
`Male_Outfit_4_BraveStar_MAT`. Everything else — outfit, hat, haircut, beard,
all three colour rows — is identical.

Only three free groups carry a livery at all, and all three are Matsumoto
[measured]: 246, and 248 twice. Brave Star owns exactly two groups, 300 and 301,
and both are in use by the twin pairs. So a twin can be split while keeping its
faction livery only where a free sibling of the same livery exists, which today
means Matsumoto alone.

The four Cosmetic tables are skipped by the dumper's `SkipIrrelevantTables`
policy. `[Dump] Include` overrides it; its own documentation names
`CosmeticModel` as the example. Point `[Dump] OutputDirectory` somewhere
disposable first — filling `BepInEx/ckf-dump/` makes `validate_rules.py --game`
stop refusing and start reporting noise (gate 03).

Two archetypes sharing an `OutfitId` render identically only if they also share
`DetailGroup`; the pair splits the look otherwise.

## Roster pools: `MonsterGroupMemberModel`

Each slot is filled from a weighted pool. `MonsterGroupMemberId` is the key;
`MonsterType` holds a PowerGroupId, not a MonsterTypeId. Spawning keys off the
scaled mission power level, so every gate is live above PL 10.

```json
{ "model": "MonsterGroupMemberModel", "where": { "MonsterGroupMemberId": 31 },
  "set": { "WeightedRoll": 1 } }
```

Six member rows in the Gang pool (group 1000) carry a non-zero `Faction`:
Patchmax/F-Duster/Bulwark at PL 4 and Slagga/Detonator/Brutewain at PL 5,
tagged 9/10/11 [measured]. They are one trio member per gang, so a gang's pool
holds six types and not ten, and any share computed by summing all ten rows is
wrong by a third. No other pool carries a tag. What a faction with no matching
tag sees is [unverified]; the faction argument is known not to be a plain
equality filter on that column
([`cloning-rows.md`](cloning-rows.md#spawn-pools)).

One lever needs no clone, and one only looks like it does:

- **`WeightedRoll`** biases the pool, and an edit to a shipped row lands
  [measured]. The roll runs in managed code over the list the reader returned,
  after the row has been through `GetRow*`. Shipped values are 1, 2, 4, 5 and
  10. In Run67 two rows raised from 2 to 100 took 8 of the mission's 9 slots
  while the baseline grunt at its shipped 4 took none.
- **`MinPowerLevel` / `MaxPowerLevel` cannot be edited on a shipped row**
  [measured]. `ReadMonsterGroupMembersByGroup` takes `powerLevel` as an
  argument, so the band filter runs in the encrypted SQL before anything is
  materialized and a rule rewriting those columns changes nothing. Run67:
  member 299 at `MinPowerLevel` 25 still spawned at a far lower mission PL. The
  gates are real only on a clone, where `RowClone.GatesPass` applies them
  itself. No shipped entry gates above PL 8 [measured], so every pool's mix is
  frozen from PL 8 up and re-spacing it takes clones, not edits.

Adding members is a clone into the reserved range, with gates set explicitly
([`cloning-rows.md`](cloning-rows.md#spawn-pools)).

### Spawn-overlay generator scope

`scripts/gen_spawn_weights.py` writes twelve `MonsterGroupMemberModel.spawn-*`
overlays, one per faction pool, and each covers **slot 1 of one group**: the
opening roster (`MonsterGroupModel.Starting = 1`, `MonsterGroupTypeId` 1). The
writer asserts the group has exactly one slot and refuses otherwise.

**A pool no generated mission builds gets no file.** A faction with
`FactionModel.ProcGenSelect` 0 is never picked for a generated mission, so a
shared pool whose every user is such a faction is never rolled. Group 500 (the
Corp pool, used only by Demo Corp) is the one case and is excluded; its
clone-id block stays reserved so no other file's ids move. `check_reachable`
refuses the whole run if a later dump makes another pool unreachable. Five
other factions carry `ProcGenSelect` 0 — Indie, Electric Jackals, Seven
Dragons, Ricksham and Knight Horizon — but each shares a pool with a faction
that is picked, and the rows are shared, so their weights cannot be reverted
separately from that pool's.

A faction owns more groups than that. Brave Star (FactionId 7) owns eight
[measured]: 25100 the opening roster, plus 25200, 25300, 26050 and 26200 also
at `Starting = 1`, and 25000, 26000 and 26100 at `Starting = 0`. Several carry
slots 2, 3 and 4. Two archetypes never reach the opening roster at all — Star
Phalanx (PG 26110) is only in 26050, and Lance VTOL (PG 26000) is in no member
row anywhere [measured]. Changing a weight here therefore changes what walks
the map at mission start and nothing else.

The generator owns taper construction; do not copy its current anchors or
weights into documentation. Run
`python scripts/gen_spawn_weights.py --check` to re-derive the expected totals
from the dump and compare them with the live files.

## Checking a change

`traceRules` in `modelrules.json` prints what each rule moved, and the
`RowClone: built` / `served` lines show which tiers a mission used
([`rule-engine.md`](rule-engine.md#tracing),
[`cloning-rows.md`](cloning-rows.md#serving-paths)). To assert exact values, add
rows to `ckf.hardmode.selfcheck.csv` and set `[Slices] SelfCheck = true` for that
launch.

## Open questions

- [unverified] **Reinforcements**: alarm-deck cards drawing `Starting = 0` groups, read from
  the data and never observed firing ([`reinforcements.md`](reinforcements.md)).
- [unverified] **Talent bands** stop at "PL 9+". `MonsterTalentModel` clone serving has never
  been exercised.
- [unverified] **`EffectModel` damage columns on monsters**, as above.

## Related

- [`armour-groups.md`](armour-groups.md)
- [`power-level.md`](power-level.md)
