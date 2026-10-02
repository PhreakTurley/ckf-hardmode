# Mission fatigue

Use this page to trace a completed mission through the three-tier fatigue track
in `mods/CKFHardMode/Fatigue.cs`. It also records the shipped temporary traits,
mission score rows, and Wound Resist inputs on which the subsystem depends.
Settings and defaults belong to [`config-reference.md`](config-reference.md);
known traps belong to [`gotchas.md`](gotchas.md).

Evidence tags: [measured] means read back from a live save (CKFDataDump `TraitProbe`) or from the dumped tables. [unverified] means never observed.

## Shipped data and runtime behavior

### The three traits

All three are shipped limit-break temporary traits (`TraitClass 6`, see [`limit-break-traits.md`](limit-break-traits.md)). Each has its own `TraitGroup`, so a merc can hold all three at once and their penalties apply together.

| | Checked Out | Running Empty | Off-Duty |
|---|---|---|---|
| `TraitId` / `TraitGroup` | 2007 | 2009 | 2014 |
| `EffectTypeId` | 10505 | 10507 | 10512 |
| Effect name in locale | "Checked Out" | "Bloodless" | "Off-Duty" |
| `EffectClassification` | 12 `MutationTempTrait` | 12 `MutationTempTrait` | 12 `MutationTempTrait` |
| `TraitScore` | -1 mild | -2 severe | -2 severe |
| Shipped effect | `InitBonus -2`, `XpBonus -33` | `InitBonus -4`, `XpBonus -50` | `SpecialCode 90 BlockMissions`, value 1. No stat penalty |

The separate `LimitBreakTraits` slice can edit effect rows for these traits; see
[`limit-break-traits.md`](limit-break-traits.md#what-the-mod-overlays) and inspect
the live overlay for its current cells.

- `SpecialCode 90 BlockMissions` reads "Unwilling to go on any mission (unless required by mission)". `BlockMissions = 90` is confirmed against `_id_constants.csv`.
- [measured] A captured shipped Stress Limit Break granted one of these traits
  for 30 days; see
  [`mission-elapse-penalty.md`](mission-elapse-penalty.md#the-four-character-bars).
- 4 turns = 1 day. `RuleModel` 40 `Max Injury Time` is 100 turns, described in game as "25 days default".
- [measured] A `TraitClass 6` trait reaches the character's stat aggregate. A merc carrying 2007 read `XpBonus -33` in her `MissionStart` aggregate, and nothing else on her carried XP. `InitBonus` cannot be checked this way because gear, implants and jobs also feed that aggregate.
- Traits are processed in `TraitContext.MissionStart`. The other two contexts are `MissionVictory` and `CyberSurgery`.
- [measured] A merc holding 2014 still came back from `ReadGameCharactersAvailableForMission` with an aggregate reading `SpecialCode 0`. Where the game enforces `BlockMissions` is [unverified]; the mod does not depend on it.
- [unverified] Whether two `TraitClass 6` traits that carry the same stat column add in the aggregate or one of them wins. Nothing shipped stacks two of these traits, so the data holds no precedent.

### Trait rows and their life cycle

`GameCharacterTraitModel` columns: `Id, CharacterId, TraitTypeId, OptionId, IsWound, Description, CreatedTurn, ExpiresTurn, IsNew`. The model also carries the joined properties `TraitData`, `EffectData` and `MatrixEffectData`.

- [measured] The model has a public parameterless constructor. A row built with `Activator.CreateInstance` inserts through `GameDb.InsertGameCharacterTrait`, which returns the new id.
- [measured] The joins are filled by the reader, not by the insert. `ReadGameCharacterTrait(id)` returns the row with all three joins null. `ReadGameCharacterTraitsByCharacter(characterId)` returns the same row fully joined.
- `SaveManager.ProcessTraits` runs `SELECT * FROM GameCharacterTrait WHERE ExpiresTurn != 0 AND ExpiresTurn <= ?` every turn. It deletes expired rows and logs `Timeline.Log.TraitExpired` ("The temporary {0} Trait has lapsed and no longer affects {1}."). `ExpiresTurn = 0` therefore means permanent.
- [measured] An inserted row survived a save and reload, was absent from a different save slot, and was removed one turn after its `ExpiresTurn`.
- `GameDb` is a live working database and a save slot is a snapshot of it (`DataLayer.CreateSnapshot` and its variants). A row the mod writes persists exactly when the player's own progress does.
- [measured] Inserts and deletes made from inside a `GameDb.InsertGameScore` postfix completed without errors, while the game's own insert was still unwinding.
- There is no static `GameDb`. A hook that is not on `GameDb` reaches it through `__instance` (SaveManager) → `.Dac` (`RPG.Core.GameManagerBase`) → `RPG.Saving.DataLayer` → `.GameDBI`.

### Mission-completion score rows

- [measured] A completed mission writes, in order, one `GameScoreModel` row with `ScoreTypeId 19 MissionCompleteByCharacter` per deployed merc, then one `ScoreTypeId 16 MissionComplete` row with `CharacterId 0`.
- [measured] In the reference save, 92 turns carry a type-16 row and 92 carry type-19 rows, with no orphans. Two-room missions still produce one type-16 row.
- `ScoreTypeId 20 MissionCompleteByCharacterUnseen` is per character and conditional on not being spotted.
- Types 16 and 19 carry the real game turn in `GameTurn`. Types 15 and 18 carry the mission turn.
- Score rows carry no mission identity (`ScoreTargetId 0`, empty `ScoreKey`).
- [measured] A lost mission writes no score rows. The last row is `StartRoom`, followed by `ProcessGameOver gameOverWin=False`.
- `Status` is transient at mission end. [measured] Mercs read `Status 12 Extracted` on the victory screen and `Status 1` a few reads later. Whether type 19 means "deployed" or "survived" is [unverified].

### Wound Resist

- The Triage Clinic is `ModuleClassId 18`, module types 71–74. It grants `InjuryTime` -25/-30/-35/-40 and `WoundRes` 10/15/20/30 by upgrade level.
- `WoundRes` is an integer column on both `EffectModel` and `SafehouseModuleModel`.
- [fitted, game wiki] Every two effective Strength points add 1% Wound Resistance ([Character Attributes](https://cyberknightswiki.tresebrothers.com/Character_Attributes)). `Fatigue.ResistFor` combines `GameCharacterModel.AttStrength` with the deduplicated effects' `AttStrong` values before dividing by two. A live comparison with the game's character sheet would confirm the effective total.
- `EffectClassification` values are explicit enum values, not declaration order. They were read from the metadata `Constant` table and cross-checked against effect 10507 (classification 12):

| | | | | |
|---|---|---|---|---|
| 1 TalentBuff | 2 TalentBooster | 3 Backstory | 4 Wound | 5 JobFaceBonus |
| 6 JobBonus | 7 Cyberware | 8 TalentBoosterDebuff | 9 ArmorEffect | 10 TalentDebuff |
| 11 LoadedProgram | 12 MutationTempTrait | 13 MissionAdvantageBuff | 14 MissionAdvantageDebuff | 15 MutationTempTraitFace |

[measured, `EffectModel`] 144 effects carry a non-zero `WoundRes`:

| Class | Rows | Range |
|---|---|---|
| 1 TalentBuff | 9 | -50..+50 |
| 3 Backstory | 40 | -50..+25 |
| 4 Wound | 4 | -20..-10 |
| 7 Cyberware | 64 | -25..+25 |
| 9 ArmorEffect | 22 | +3..+30 |
| 10 TalentDebuff | 1 | -25 |
| 12 MutationTempTrait | 4 | -100..+50 |

- Cyberware mostly lowers the stat. 51 of the 83 implants that carry `WoundRes` are negative. [measured, reference save] Every merc on the roster sits between -10 and -39 from implants alone.
- 0 of the 1,525 shipped job nodes carry `WoundRes`.
- `GameArmorModel` [measured, interop property tables] carries `ArmorTypeId` and `GameEffectId`. It joins `ArmorData` (`ArmorModel`, with `ArmorEffectId`), `EffectData` and `EffectDataCrafted`.
- [measured, `CoreRPG_v1.dll` metadata] `GameDb` declares `ReadGameSafehouseModules()`; `GameSafehouseModuleModel` declares `GameSafehouseId`, `ModuleTypeId`, and `ModuleData`; `DataDb` declares `ReadSafehouseModule(long)`. [fitted] `Fatigue.SafehouseResist` uses that reader and lookup to sum built module values once per mission. A live log with a known built clinic will confirm the path returns its row and value.
- [measured, `Logs/run78.log:581`] The earlier safehouse-row paths all reported 0: `GetWoundRes 0`, `ModuleSummary 0`, `Modules 0`. They could not establish whether a clinic was built because the safehouse row's module cache was empty. The direct built-module reader is now used, and the log reports its row count and unresolved rows.

## Hard Mode fatigue subsystem

- Gate: `[Slices] Fatigue` in `ckf.hardmode.cfg`.
- Settings: `ckf.hardmode.d/fatigue.json`, described by `schema/fatigue.schema.json`.
- This subsystem writes to the save. It inserts `GameCharacterTrait` rows and adds no table, column or side file. It deletes nothing: `Fatigue.cs` has no delete path at all.
- The game handles expiry. Uninstalling the mod leaves at most a few live traits, which lapse on schedule.
- The mod never filters `ReadGameCharactersAvailableForMission`. Blocking the roster is left to the engine's `SpecialCode 90`, which keeps the game's story-mission override. [measured] A merc logged as already Off-Duty was deployed anyway on a story-required mission.

### Three-tier track

Each tier has a configurable trait id. A tier is a position in
`Fatigue.Options.Tiers` and `Options.TraitIds`, not a separate branch in the
code: the trait scan, grant, double-fire guard, and distinctness validation all
walk those arrays. Defaults belong to
[`config-reference.md`](config-reference.md).

- **Every eligible merc rolls once per completed mission.** A merc who fails moves up one tier from the highest they already carry — nothing to tier 1, tier 1 to tier 2, tier 2 to tier 3.
- **Moving up is not automatic.** The same `chancePercent` and the same Wound Resist subtraction decide a first grant and a move up a tier. There is no unconditional escalation.
- **The tiers stack.** A grant never removes the tier below. Each row carries its own `ExpiresTurn` counted from the mission that granted it, so the lower tiers lapse first.
- **A merc already on the top tier is not rolled**, because there is nowhere above it. They are counted as `already at the top of the track` in the summary.
- **One chance curve and one duration curve serve every tier.** The number that grants tier 1 is the number that moves a merc to tier 3, and the duration written on a tier-3 row is the one written on a tier-1 row. Beyond the trait id there are no per-tier tunables.
- **One pool, one clamp.** Everybody eligible to roll is in one pool whatever tier they are on, and `minAffected`/`maxAffected` bound the *total* number of grants the mission makes. A floor can therefore force a move up a tier, and a ceiling can spare one.
- The tier a merc is on is the **highest** matching `TraitTypeId` they carry, not a count, so a merc holding tier 3 but not tier 2 is read as being at the top of the track and is never walked back down.

### Hooks

- A postfix on `GameDb.InsertGameScore(GameScoreModel)` does the work:
  - **Phase A.** On a type-19 row it adds `CharacterId` to the pending roster, deduplicated. On the first such row it reads the mission's power level.
  - **Phase B.** On a type-16 row it resolves the mission.
- A type-19 row on a different turn while a roster is pending drops the session state.
- A postfix on `ViewModel_GameManagement.LoadGame` / `.LoadGameSlot` clears session state. Both fire on one load, so the clear line appears twice.

### Resolution (Phase B, once per mission)

1. **Solo exemption.** If the roster holds one distinct `CharacterId`, nothing happens: no roll, no row. The log line reads `Fatigue: mission complete at turn N with one merc deployed (character X). Solo missions are exempt: no roll, no escalation, nothing written.`
2. **Double-fire guard.** The key is the turn plus the sorted roster. On a repeat key, the mod asks the database for a row carrying *any* tier's trait with `CreatedTurn` equal to that turn on any roster merc.
   - Rows present: the mission is not resolved again.
   - Rows absent: the save was rolled back, so the mission resolves again. The deterministic rolls give the same result.
3. **Read** each merc's traits with `ReadGameCharacterTraitsByCharacter` and take the highest tier they hold. A trait list that could not be read all the way through, or a row with an unreadable `TraitTypeId`, skips that merc rather than granting on them.
4. **Skip** a merc already on the top tier, and a merc the curves name no `chancePercent` for.
5. **Pool.** One pool of everyone who reached this step with a tier above them, whatever tier they are on.
6. **Roll** each pool merc against their own threshold (below).
7. **Clamp** the total grant count to `[minAffected, maxAffected]`.
8. **Grant** tier `held + 1` to the final failure set, leaving the tier below in place.

Step 3 reads before step 8 writes, so "how far up the track were they when they deployed" needs no `CreatedTurn` arithmetic and no deploy-time hook. Rows are stamped `CreatedTurn = GameTurn` of the type-16 row and `ExpiresTurn = GameTurn + durationDays × 4`. The other columns are written as `IsWound 0`, `IsNew 1`, `OptionId 0` and `Description ""`. All nine `Set` calls are checked and a row with any miss is not inserted.

A merc carrying more than one row of one tier's trait is reported and left alone: the tiers stack, so a duplicate row is a trait held twice and it expires by itself.

### Power level and the curves

- **Which level.** The power level is `ReadGameMissionActive().PowerLevel`: the scaled level, including the lift from [`power-level.md`](power-level.md). It is not `PowerLevelUnscaled`. Phase A reads it and Phase B retries.
- **Unreadable level.** If both reads fail, each curve returns its lowest anchor, and the log says so once.
- **Anchors.** One required top-level `byPowerLevel` maps a power level to `chancePercent`, `durationDays`, `minAffected` and `maxAffected`, for all three tiers. An optional `knight.byPowerLevel` carries `chancePercent` and `durationDays` only.
- **Interpolation.** Each field interpolates linearly over only the anchors that name it, rounding away from zero. Below the lowest anchor and above the highest, the nearest anchor holds. One anchor gives a flat value.
- **The Knight.** The Knight is identified by `GameCharacterModel.IsKnight`. Where his curve names a field it beats the general curve for that field. He is inside the general floor and ceiling like anyone else, so a `minAffected` or `maxAffected` on a Knight anchor is warned about by name.
- **Missing values.** A field that no applicable anchor names has no value:
  - No `chancePercent`: the merc is not rolled for, at any tier.
  - No `durationDays`: nothing is granted to anyone, because a row with no expiry would be permanent.

  Both cases are logged once, and those mercs are counted separately in the mission summary as `not resolved for want of a configured value`.
  - No `minAffected` means no floor (a warning).
  - No `maxAffected` means no ceiling. `maxAffected: 0` is a ceiling of zero, and since every grant goes through the one clamp, it stops the whole mission's fatigue.
- **Validation at load.** The feature stays off if any of these fail, and the log names the key:
  - `byPowerLevel` must exist and name `chancePercent` and `durationDays`. A value on the Knight's curve does not satisfy either requirement: his curve is consulted for him and falls through to the general one for everybody else, so a chance named only there leaves every other merc without one.
  - Anchors are checked: chance 0–100, `durationDays` ≥ 1, counts ≥ 0, `max ≥ min`, and no two keys for one level (`"1"` and `"01"`).
  - A sweep over PL 1–20 rejects a curve whose ceiling crosses below its floor.
  - Each tier's trait id must be non-zero, positive, distinct from the other two, and below 900000 (the id range reserved for `RowClone`).
- **Unknown keys.** An unknown key anywhere in the file refuses the file, and matching is case-sensitive.
- **The retired 4.0 blocks.** `runningEmpty` and `offDuty` still parse, held as raw JSON, so a 4.0 file loads instead of being refused for keys that map to no member. Nothing reads them, `Fatigue.LegacyKeys` names whichever a file carries, and their curves do not stand behind the current one — a 4.0 file names no top-level `byPowerLevel`, so `Validate` refuses it and says what to do. `offDuty.clearsRunningEmpty` went with them, along with the `Revoke` method it drove.
- **Retired gate.** An `"enabled"` key is reported as retired (`Slices.ReportRetiredGate`).

### The roll

- **Threshold.** `chance − WoundResist`, floored at `min(woundResist.minChancePercent, chance)` and capped at 100. A configured chance of 0 means no roll, whatever the resist.
- **Roll.** `Fatigue.StableRoll` is `splitmix64(GameTurn, CharacterId) mod 100`, with no salt. The same turn and merc always give the same roll. `deterministicRolls: false` switches to an unseeded `Random`. [measured] Rolls predicted offline before a live run matched: turn 1388 gave 27, 61 and 97 for characters 1, 16 and 19. Changing the constants changes every save's future rolls.
- **Clamp.** Ranking is by distance from each merc's own threshold. Short of `minAffected`, the closest passes are made to fail. Past `maxAffected`, the closest fails are spared. Ties break on character id.
  - `minAffected` is capped at the pool size.
  - The Knight is inside the clamp.
  - Nothing is exempt from it. A merc the floor pulls in moves up a tier like any other failure, and a merc the ceiling spares moves nowhere.

### Wound Resist mitigation (`woundResist.enabled`)

A merc's total Wound Resist is subtracted from their chance point for point, at every tier. Sources:

| Source | Reader |
|---|---|
| Safehouse | `ReadGameSafehouseModules()` once per mission, with `DataDb.ReadSafehouseModule` for rows lacking `ModuleData`. The safehouse row's computed and summary values are fallbacks if the direct read is incomplete |
| Strength | `ReadGameCharacter.AttStrength` plus deduplicated `EffectData.AttStrong`; one resist point per two effective Strength points |
| Traits | `ReadGameCharacterTraitsByCharacter` |
| Character effects | `ReadGameCharacterEffects` |
| Implants | `ReadGameCharacterImplants` |
| Job nodes | `ReadGameCharacterJobNodes` |
| Armour | `ReadGameArmorByCharacter`. One row. Counts the armour's effect and the crafted effect |

- **Missing joins.** A row whose joined `EffectData` is null has its effect looked up in `DataDb` and cached per mission:
  - trait: `TraitData.EffectTypeId` or `ReadTrait`
  - effect: `EffectTypeId`
  - implant: `ImplantData.ImplantEffectId` or `ReadImplant`
  - job node: `NodeData.NodeEffect1Id` or `ReadJobNode`
  - armour's own effect: `EffectData`, else `ArmorData.ArmorEffectId`, else `ReadArmor(ArmorTypeId)`
  - armour's crafted effect: `EffectDataCrafted`, else `ReadEffect(GameEffectId)`
- **Duplicates.** All readers share one set of seen effect ids, so an effect mirrored into two tables counts once. The first repeat is logged.
- **Log split.**
  - Armour, and any classification-9 effect, is reported as `gear`.
  - Other effects are split into `timed` and `permanent`. An effect is `timed` if its classification is in `Fatigue.TimedClasses` (1, 2, 4, 8, 10, 12, 13, 14, 15), or if it comes from a trait row whose `ExpiresTurn` is non-zero.
  - The split is logged only. All parts count toward the total.

A merc's own fatigue traits reach the trait reader like any other trait row, and are classification 12, so they count as `timed`. None of the three shipped effect rows carries a non-zero `WoundRes`, so carrying a tier changes nothing about the next roll's resist.

Each roll line ends with the arithmetic and a per-reader summary, for example:

```
[57 base - -27 resist (permanent -27); read trait 6, effect 0, implant 3 (2 with WoundRes, 3 via DataDb), job 14]
```

| Tag | Meaning |
|---|---|
| `via DataDb` | The join was null and the effect was looked up |
| `name no effect` | The content row points at effect 0 |
| `UNRESOLVED` | The join was null and the lookup failed |
| `UNREADABLE` | The reader threw or returned null |
| `PARTIAL` | The reader stopped part way |

The first lookup per reader also logs `returned rows with no joined EffectData`.

### Logging

- `logGrants` switches the per-mission head line and the per-merc lines. The head line names the tier chain (`Tiers: 2007 -> 2009 -> 2014`). Each merc line names the tier they were on, their roll against their threshold, and the tier and trait they moved to.
- The summary counts grants per tier, then `clear` and `already at the top of the track`, plus `not resolved for want of a configured value` and `FAILED TO WRITE` where those occur.
- On a successful load the subsystem logs `Fatigue: ACTIVE, and this subsystem WRITES TO YOUR SAVE.` at Warning.
- A `ReadGameCharacter` failure (throw or null) is logged once. It costs the Knight check and merc names.

### Offline checks

`tests/fatigue/` checks the built DLL by reflecting over `Fatigue`'s private
members. It derives curve expectations from the config on disk, reads tier ids
from `Options.TraitIds`, and covers highest-tier-held scanning, stacking, the
shared clamp, pairwise trait-id validation, Strength deduplication, and the built-clinic fallback.
[measured, `Logs/release-4.1.1-fatigue.txt`] The harness passes against the
4.1.1 DLL and live fatigue configuration. Live coverage remains listed below.

## Measured runtime coverage

- [measured, `Logs/PlayedLogB.log` turn 1464] Non-trait readers did not fill
  joined `EffectData`: implants returned 6 of 7 unjoined, job nodes 7 of 41,
  and armour 1 of 1. The DataDb fallback carried them.
- [measured, `Logs/PlayedLogB.log` turn 1464] Wound Resist reached the roll and
  the arithmetic held: three chromed mercs subtracted -15, -16, and -6
  (`permanent`, from implants) from base chances of 24 and 60, producing
  thresholds of 39, 76, and 66. An unchromed merc used the base 60 with `no
  resist`; nothing logged `UNRESOLVED`.
- [measured, `Logs/PlayedLogB.log` turn 1464] Four tier-0 mercs resolved: three
  received tier 1 (trait 2007) and one remained clear. The tier chain logged as
  `2007 -> 2009 -> 2014`; the Knight's curve applied only to him (24% versus
  60%, 10 days versus 13).

## Open questions

- [unverified] What `ReadGameArmorByCharacter` returns for an unarmoured merc.
  Null or `ArmorTypeId 0` both show `armor 0`; a throw shows `armor UNREADABLE`.
  Also unknown: whether the row it returns is equipped; `IsEquipped` is not
  checked.
- [fitted] `GameArmorModel.GameEffectId` is the crafted upgrade's `EffectModel` id.
- [unverified] `ReadImplant(long)` and `ReadJobNode(long)` key on `ImplantTypeId` and `JobNodeId`.
- [unverified] Whether a grant also writes a `GameCharacterEffect` row. The
  first duplicate-effect log line would answer it.
- [unverified] Where the game enforces `BlockMissions`: the planning screen or
  a read of `GameCharacterEffect`.
- [unverified] The solo exemption in live play; it has only been checked
  offline.
- [unverified] The load hook's target was inferred from the interop type table. A `Fatigue: a save was loaded` line in a log confirms it.
- [unverified] Live move-up, stacking, top-tier skip, and clamp paths. The
  measured mission started every merc at tier 0 and its three natural failures
  already lay inside `min 1, max 5`.
- [unverified] Whether movement penalties from tier-1 and tier-2 effect
  overlays reach the in-mission character and stack. See
  [`limit-break-traits.md`](limit-break-traits.md#what-the-mod-overlays).

## Related

- [`limit-break-traits.md`](limit-break-traits.md)
- [`power-level.md`](power-level.md)
- [`mission-elapse-penalty.md`](mission-elapse-penalty.md)
- [`config-reference.md`](config-reference.md)
