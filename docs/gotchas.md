# Avoid known failure modes

Use this troubleshooting reference after you identify the subsystem you are changing. Each entry records a failure that is silent, destructive, misleading, or expensive to reproduce. Setting meanings belong in the [generated configuration reference](config-reference.md); procedures belong in the [workflow](workflow.md).

## Game data & databases

- **Never try to open the save or content databases.** They are SQLite SEE-encrypted, and `scripts/unlock_db.py` was retired on purpose (David's rule). `source: AGENTS.md`
- **All edits happen in memory, after the game decrypts its rows.** A save slot snapshots the live `GameDb`, so an inserted row persists when progress does.
- **The asset bundles hold no data tables.** Prefabs are art only; don't re-scan them. `source: scripts/inspect_bundles.py`
- **Names live in `StreamingAssets/Locales/en-US.json`** (unencrypted, keyed by table ids). A cloned row has no name until you add one.
- **Weapon class names come from `WeaponModel.WeaponClassName`.** `_id_constants.csv` has no `WeaponClass` constants, and `WeaponClassModModel` spells three differently; players see `WeaponModel`'s. [measured]
- **Key on `(table, id)`, never on an id alone.** 130 ids are both an `EffectId` and a `MatrixEffectId`, 221 both a `TalentId` and an `EffectId`, 137 both a `MonsterTypeId` and a `WeaponId`. [measured]
- **A `JobNodeId`'s digit prefix is not its `JobId`.** Every `sc` node starts `16`, but JobId 16 is "Attack Hund"; the owner is JobId 15 (Scourge). [measured]
- **A movement penalty on a `TraitClass 6` trait can go in `MoveSpeed` or `MoveSpeedDebuff`. Both apply; they differ in two ways.** `MoveSpeedDebuff` is reduced by the merc's own `MoveSpeedMitigate` and shows on the character sheet. `MoveSpeed` is not mitigated by anything, and a negative one does not show on the sheet at all — the penalty still applies, the player just cannot see it; it may not display in either direction. So the choice is mitigatable and visible, or unmitigatable and silent. No shipped `TraitClass 6` row uses either column, so there is no in-data example to copy. [measured, in play] The mod writes `MoveSpeedDebuff`, which is David's ruling; see [limit-break-traits.md](limit-break-traits.md#what-the-mod-overlays). `source: sheets/raw/EffectModel.csv` for the columns themselves
- **`RuleModel` RuleId 12 `AI Skip Turn Distance` (ships 30) is a presentation feature, not an AI decision.** It is how far an enemy has to be from the player or from a dead body before the game stops animating its travel and teleports it to its destination, on the grounds that the travel is not worth watching. The unit still takes its turn and still acts. `RPG.Control.AIController.CanSkipByDistanceToPlayerOrDeadBody(Vector3 rootPosition, Boolean allowSkip) -> Boolean` carries it, and `allowSkip` belongs to the same mechanic [measured, `FindMethods` at `LogOutput.log`]; the row lands in `RuleConfig.AISkipTurnDistance`. Do not reach for it when an enemy ends its turn without acting. `source: David`
- **`RuleModel` RuleId 6 `AI Sleepy Distance` (ships 40) is a relevance pass, not a behaviour lever.** Guards beyond it do not render and do not take turns until something wakes them. It decides whether a unit is simulated at all, never what an awake unit chooses to do. The row lands in `RuleConfig.AIAsleepDistance`. `source: David`
- **`RuleConfig`'s field order is `RuleModel`'s `RuleId` order, 1-76.** That is how a row reaches the constant the code reads; nothing else links them. [measured, `BepInEx/interop/CoreRPG_v1.dll` metadata, `RuleConfig`]
- **Four `ImplantModel` oddities ship as they are. Don't "fix" them** (David's rule). Row 904 `Deactivated = 904` (itself); row 3801 `Deactivated = -2`; row 100 `MatrixEffectId 50014` resolves only in `EffectModel`; in slots 3 and 7 `ImplantLevel` is not a tier index, so those sheets use dump file order. [unverified]

- **The game prints a full, named AI turn log and it does not reach `LogOutput.log` by default.** Every enemy turn is written to the Unity log as `TURN LOG <n> for <Name> (<Archetype>) on INIT <n>` followed by its state lines and `-) Starting turn as <AiAlarmLevel>` / `-) Ending turn as <AiAlarmLevel>`. BepInEx forwards it to the console (`[Logging] UnityLogListening = true`) but `[Logging.Disk] WriteUnityLog` ships `false`, so the file keeps none of it and a capture taken from the file looks as if the game logs nothing. Turn it on before tracing anything AI-related; most of what a `TraceMethods` postfix can tell you is already in there, with the unit's name attached. `source: BepInEx/config/BepInEx.cfg`, [enemy-ai.md](enemy-ai.md)

## Asset bundles & assemblies (IL2CPP, Harmony, reflection)

- **A method name is not evidence of a mechanism.** The interop assembly is marshalling stubs: no bodies, no caller graph. `RPG.Database.*` is in `BepInEx/interop/CoreRPG_v1.dll` (decodable offline with `dnfile`). `source: AGENTS.md`
- **Never patch a method that only does arithmetic.** IL2CPP folds identical small bodies onto one address, so patching one patches all; the game stack-overflows on load with a trace pointing elsewhere, while every patch reports success. `source: patching-rules.md`, `mods/CKFDataDump/MissionProbe.cs`
- **Never cache a database instance.** Always use the live `__instance`; a stale captured instance once hung a mission load.
- **By-id readers behave differently when the id is missing.** `GameDb` ones throw (invisible to a postfix); `DataDb` ones return an all-default row, so non-null proves nothing. Check the row's id column; prefer zero-arg bulk readers. `source: SelfCheck.cs:ReadRow`, `RowClone.cs:ReadById`
- **A joined property can be null, and null is not the same as empty.** `GameCharacterTraitModel.EffectData` is filled by the by-character reader only. Check, count and log nulls. `source: Fatigue.cs:ResistFor`
- **Each `AccessTools.TypeByName` call logs a `ReflectionTypeLoadException`.** Resolve once and cache.
- **Harmony limits:** `const` fields can't be patched. `__result` on a `void` method fails with an IL compile error; use a `ref` prefix instead, and its parameter name must match the original's.
- **Two postfixes on `GameDb.GetRowGameMissionRewardModel` depend on their priorities.** `MissionRewards` is `Priority.First` (snapshots stock), `ModelRules` is `Priority.Last`; without both the result is stably wrong. `source: MissionRewards.cs:AfterGetRowMissionReward`, `ModelRules.cs:AfterGetRow`

## BepInEx config

- **BepInEx keeps keys it no longer binds.** An unbound key stays in the `.cfg` looking real; `check_schema.py` calls it `STALE`. `source: schema/check_schema.py`
- **Deleting a key while its bind still exists brings it back at the code default.** For example, `[Slices]` keys default to `true` and `SelfCheck` defaults to `false`. `source: Slices.cs`
- **Close the game before editing `ckf.hardmode.cfg`.** BepInEx rewrites it on exit, and the plugin reads it once per launch: an edit made while the game runs is neither seen nor reported. `source: Slices.cs` (header)
- **An unreadable `[Slices]` key counts as on, not off** (logged at Error). `source: Slices.cs:Init`

## Hard Mode config (slices, sidecars, overlays, rule engine, cloning)

Layout: `ckf.hardmode.cfg` holds `[General] Enabled` plus one `[Slices]` key per slice, and `ckf.hardmode.d/` holds the settings JSONs and the sheets. See [overlays.md](overlays.md) and [rule-engine.md](rule-engine.md).

- **If both config layouts are present, Hard Mode applies nothing.** When the pre-4.0 `ckf.hardmode.json` sits next to any slice file, `ConfigDoc` logs `BOTH CONFIG LAYOUTS ARE ON DISK` and the game runs unmodified. Extracting a 4.0 zip over a 3.x install produces exactly this. Delete or rename `BepInEx\config\ckf.hardmode.json` (for example to `.pre-4.0-backup`). `source: ConfigDoc.cs:Ensure`, `Plugin.cs:Load`
- **A leftover `ckf.hardmode.rules.json` is still read, and it is read first.** Any non-`set` rule in it applies on top of the sheet that replaced it (logged at Error). `source: Plugin.cs:Load (rulesPath)`
- **A top-level `"enabled"` inside a slice JSON is dead.** Only the `[Slices]` key switches a slice. It is only logged (Error when `false` and the slice is on). The nested `credits.enabled`, `stress.enabled` (elapse) and `woundResist.enabled` (fatigue) are live settings. `source: Slices.cs:ReportRetiredGate`
- **`[Slices] ModelRules = false` switches off every sheet-based slice** (talents, implants, consumables, cyberweapons, gear classes, `RuleModel`, enemy gear) and the Team PL label mirror `MissionPowerLevelModel.generated.json`, whatever their own keys say. `Progression`'s award itself still applies. An unreadable or invalid `modelrules.json` does the same for the launch. `source: ModelRules.cs:Init` (returns before `Overlays.Load`)
- **A settings file older than `Defaults.DocVersion` is not filled in.** A missing key takes the built-in default. `source: ConfigDoc.cs:ReportStamps`
- **A deleted slice file is not recreated.** `Defaults.Install` only reports it. `source: Defaults.cs:Install`
- **Five keys' code defaults disagree with the schema in the shipped 4.0.0 DLL.** An absent key there gets the code value, not the schema value shown in config-reference.md: `fatigue.json` `logGrants` (schema false, DLL true), `elapse.json` `logFirst` (0 vs 40), `elapse.json` `stress.fallbackToRandom` (false vs true), `powerlevel.json` `logFirst` (0 vs 40), `rewardcurve.json` `logEffectiveCurve` (false vs true). Write these keys explicitly against that build. All five `Options` properties in the source now carry no initialiser, so they match their schema defaults from the next Release build on (tracked in `TASKS.md`). Nothing compares an initialiser with its schema default. `source:` each subsystem's `Options`
- **A misspelled or duplicate top-level key is logged at Error and not applied** (duplicates: last wins). `elapse.json` and `fatigue.json` refuse the whole file, turning that feature off. Misspellings nested inside the other slices' objects are not checked. `source: ConfigDoc.cs:ReadOne`, `Elapse.cs:UnknownKeys`
- **A new top-level key has to be added to two hand-kept lists, and each one fails differently.** `ConfigDoc.Declared[<slice>]` is transcribed from the schema's `fields`; a real key missing from it is reported at Error as a key "NOTHING READS IT" even though the subsystem does read it. The subsystem's own `[JsonExtensionData]` bag is the one that refuses the whole file and switches the feature off for the launch. Adding a key to `fatigue.schema.json` means adding it to `Fatigue.Options`, to `ConfigDoc.Declared[Fatigue]` and to `Fatigue.UnknownKeys`' walk. Nothing compares the lists. `source: ConfigDoc.cs:Declared`, `Fatigue.cs:Load`, `UnknownKeys`
- **`ckf.hardmode.d/` loads `.json` files as well as `.csv` and `.tsv`.** A `.json` that `ConfigDoc` doesn't own is a rules file (e.g. `MissionPowerLevelModel.generated.json`). A file no slice claims (`ArmorModel.csv`, `WeaponModel.csv`, `MonsterTypeModel.csv`) has no switch and loads on every launch while `ModelRules` is on. Subfolders are ignored. `source: Overlays.cs:Load`, `Slices.cs:VerdictForOverlay`
- **An overlay whose first column is not the id column is ignored** (one Error). `source: Overlays.cs:LoadTable`
- **A non-numeric cell under an operator header (`Col*`) is warned and skipped; under a plain header it is written as a literal.** `source: Overlays.cs:BuildRule`
- **Empty lever sheets are the editing surface, not dead files.** Many have no override filled in; don't delete them. A sheet with every lever blank emits zero rules, so a per-rule "unknown column" warning never fires for it. `source: scripts/validate_rules.py:load_consumable_sheet`
- **A lever sheet has to be recognised before its filename is parsed.** `TableOf` takes the name up to the first dot, so an unrecognised `foo-bar.csv` becomes `foo-barModel` with only an orphan warning. `source: Overlays.cs:Load (GearClasses.Owns / Cyberweapons.Owns)`
- **A blank overlay cell leaves the column alone. A filled cell is a write, and it beats anything merged after it.** A generator that emits every column it reads turns no-ops into writes; filter art and constant columns. `source: make_enemy_overlays.py:informative`, `consumables.py`
- **Never derive a sheet's column set from the dump.** Its columns vary with settings and game state. Declare them (`SHEET_COLUMNS` + `EXCLUDED_COLUMNS`) and use the dump as a check. Key the exclusions on `(model, column)`: `EffectPurgeType` and `InitBonus` are excluded on `MatrixEffectModel` but are levers on `EffectModel`. `source: scripts/consumables.py`
- **Build the gear-class partition from the post-overlay `ckf.hardmode.d/MonsterTypeModel.csv`, not from the shipped dump.** The shipped table misclassifies eight class-3 player ARs as enemy gear; both `GearClasses.cs` and `gear_classes.py` refuse rather than fall back. `source: GearClasses.cs` (header)
- **Match rules on the domain id, not `Id`.** The inherited `Id` reads `-1`. Use `WeaponId`, `ArmorId`, `MonsterTypeId`, `ImplantTypeId` and so on.
- **`multiply` compounds on `Game*` models.** `DataDb` rows are rebuilt fresh on every read, but `GameDb` rows come from the save. Use `set` or `clampMin` there.
- **A SQL aggregate never builds a row, so a rule can't touch it.** The engine hooks `GetRow*Model`; `SumGameMissionScore` is computed in SQLite.
- **Some columns are computed, and writes to them are silently ignored.** Unsuffixed weapon stats are aliases for the selected firing mode, and talent `Adjusted*` columns are derived. Write the suffixed columns, such as `BallisticDamage1`. See [tables.md](tables.md).
- **`CharacterTypeModel` is the five player classes;** enemies are `MonsterTypeModel`.
- **A clone pointer to a row that doesn't exist gives a black screen when the mission loads,** and Unity's exception never reaches `LogOutput.log`. Watch for `RowClone: <reader>(<id>) found nothing`; run `validate_rules.py` first. `source: RowClone.cs`
- **Don't re-add bulk-read serving for clones.** Clones appended to `ReadArmors()` during a Data Dump sweep killed a mission load; zero-arg readers are skipped. `source: RowClone.cs` (reader selection)
- **A Data Dump never shows clone rows.** It captures rows in a `GetRow*` postfix and a clone is appended after that returns. Confirm clones from the `RowClone: built` / `RowClone: served` log lines. `RowClone list:` call-shape lines appear only for tables that have a clone rule. `source: RowClone.cs` (header)
- **Clone into the reserved `900000+` range.** The "unreferenced `EffectModel`" list is unproven: `SecurityDeckCardModel.CardEffectId` references 65001–65005. `WeaponId` 20010 and 20011 are safe to point at; 23097–23099 are developer work in progress. What the game derives from a new `MonsterSpawnModel` or `MonsterGroupModel` id is unknown. `source: RowClone.cs:ReservedFrom`, [cloning-rows.md](cloning-rows.md)
- **A spawn pool's `MinPowerLevel` / `MaxPowerLevel` cannot be edited on a shipped row.** `ReadMonsterGroupMembersByGroup` takes `powerLevel` as an argument, so the band filter runs in the encrypted SQL before any row is materialized; a `GetRow*` rule rewriting those columns is too late and changes nothing. Measured in Run67: member 299 with `MinPowerLevel` 8 -> 25 still spawned twice at a mission PL far below 25. `WeightedRoll` on the same row did land, because the roll runs in managed code over the returned list. Band gates only work on a clone, where `RowClone.GatesPass` decides injection from the clone's own columns. `source: RowClone.cs:GatesPass`, [tuning-enemies.md](tuning-enemies.md#roster-pools-monstergroupmembermodel)
- **A test that depends on a spawn roll is not a test. Force the unit.** Run75 spent a launch on whether editing a monster's cosmetic group works and measured nothing, because the target unit — WB FireCOM, `WeightedRoll` 2 against a slot total near 17 — never appeared. With the unit absent, "the row was never read" and "no unit needed it" are indistinguishable. `scripts/gen_force_spawn.py` emits a `MonsterGroupMemberModel` overlay that clones one member row per power level pointed at the target PowerGroup at a weight orders of magnitude above the rest of the slot, which is the same clone shape the production spawn-* sheets use and that Run72 proved serves. Note it must be a clone per PL: `MinPowerLevel`/`MaxPowerLevel` are filtered SQL-side and cannot be edited on a shipped row. `source: Run72/Run75`
- **Editing a `CosmeticGroupModel` row never reaches a monster, and the reader trace will lie to you about why.** The three named readers log zero hits ever, but the table IS materialized — by raw SQL plus the static `GetRow*Model`, bypassing them — so trace the materializer, not the reader. It fires for the player's character on the safehouse screen and never for an enemy: Run76 forced ten WB FireCOMs, all wearing group 351, and the three unindexed edit rules on that group's rows produced zero trace lines across the entire mission. Every data column of both cosmetic tables is writable and none silently discards, so writability is not the obstacle — the rows are simply never read for enemies. Cloning a new GroupId is worse: nothing builds it and pointing `OutfitId` at one throws `NullReferenceException` at spawn and hangs the mission (Run72). **`MonsterTypeModel.OutfitId` repointed to one of the 321 shipped groups is the only lever**, and it is proven (Run68, Run70, Run73). `source: Run69-Run76`, [tuning-enemies.md](tuning-enemies.md#appearance-monstertypemodeloutfitid)
- **`missions.json` has a fixed key set.** Other keys are dropped by `refresh_mission_roster.py` and by the next GUI save. `source: scripts/refresh_mission_roster.py:ENTRY_KEYS`
- **In `missions.json`, `"-25"` adds −25; `"=-25"` sets it.** A bare `"40"` sets. `source: MissionRewards.cs:Adjust.Parse`
- **A multiplier on a small integer can round to 0.** `"x0.4"` on a `MissionRewards` field holding `1` gives `0`. `source: MissionRewards.cs:Adjust.Apply`

## Power Level & progression

See [power-level.md](power-level.md).

- **Rules on `MissionPowerLevelModel` change the victory-screen label, not the award.** The award is an INSERT into `GameMissionScoreModel`; Team PL is a SQL sum (mirrored in `CoreGameDataModel.PowerLevel`). `SetMissionPowerLevel` never fires. [measured] `source: Progression.cs` (header)
- **The label and the award must be switched together.** `[Slices] Progression` without `ModelRules` gives a stock label; the reverse gives a stock award with a wrong label. Neither logs; `check_schema.py` flags it `INVARIANT`. `source: schema/teampl.schema.json (linkedEnable)`
- **Never edit `MissionPowerLevelModel.generated.json` by hand.** Use `scripts/gen_teampl_labels.py` or the editor. Don't hand-write `teampl.json`'s `table` either: two failed reconciles turn retroactive mode off until a save load, so awards revert while labels stay modded. `source: Progression.cs:AfterSum`
- **Overrides are retroactive, and `CoreGameDataModel.PowerLevel` saves the substituted total.** Turning it off leaves the modded figure in the save. `source: Progression.cs` (header)
- **`GameDifficultyModel.CalculatePowerLevel` is the clamp itself.** It saturates at 10. `MatrixPowerLevelOffset` replaces `BasePowerLevelOffset`. Derived calls (`arg0 > 0`) must pass through; recomputing them turned a reward of 1 into 2. `source: PowerLevelCap.cs` (header)
- **Raising the Power Level cap doesn't raise the reward cap.** The base curve flattens above PL 10 at 2800 credits and 500 XP, and only `rewardcurve.json` changes that. `source: RewardCurve.cs` (header)
- **`rewardcurve.json` rows are looked up by exact PL.** No interpolation or carry-forward: each PL above 10 must be listed or the game's value stands. `source: RewardCurve.cs:Apply`
- **`powerlevel.json` `logFirst: 0` also silences the only Team PL cross-check** (`TEAM PL MISMATCH`). `source: PowerLevelCap.cs:After`
- **Above PL 10, shipped weapon damage flattens too.** Raising the cap alone gives sponges, not lethality. [measured]

## Save-writing subsystems (Elapse, Fatigue)

See [mission-elapse-penalty.md](mission-elapse-penalty.md), [character-fatigue.md](character-fatigue.md) and [gamedb-write-surface.md](gamedb-write-surface.md).

- **In `Elapse.Resolve`, the save writes happen inside the arguments to the log builder:** `summary.Add(SpendCredits(...))` and `summary.Add(ApplyStress(...))`. Deleting the list plumbing deletes both writes. Extract the call and discard the return; never delete the list. `source: Elapse.cs:Resolve`
- **A trait with `ExpiresTurn = 0` is permanent.** Any grant path that can't set a duration must write nothing. `source: Fatigue.cs` (grant paths)
- **Credits can't be written through `UpdateGameData`.** It returns true and the next tick restores the old value. Use `AddCredits`/`SpendCredits(long, string)`; `SpendCredits` returning `false` is the zero floor. `source: Elapse.cs` (header)
- **A `GameCharacterModel` write persists, but the roster panel reads `SaveManager.playerCache[id].CharacterModel`.** Write both. `source: Elapse.cs`
- **Written Stress is consumed by the limit break it triggers,** and `IsStatusLimitBreakReady()` is not the stress gate. [measured] See [gamedb-write-surface.md](gamedb-write-surface.md).
- **Elapse's reload detection needs the save-load hook.** Without it, a reload onto the same or next turn looks continuous and stale state survives. `source: Elapse.cs` (header, REPLAY)
- **Elapse keys its curves on `PowerLevelUnscaled`; Fatigue keys its curves on the effective `PowerLevel`.** `source: Elapse.cs:Resolve`, `Fatigue.cs`
- **`stress.applyTierMultiplier` scales `mercCount`, not the Stress amount.** `source: Elapse.cs:Resolve`
- **Fatigue has three `traitId`s and a typo in one is caught only if it lands in `900000+`.** `tier1`, `tier2` and `tier3`; any other wrong id writes a dangling trait into the save. They must also be distinct — two tiers sharing an id is refused, because the scan reads the merc on the lower one as already holding the higher and nobody would move past it. `source: Fatigue.cs:Validate`
- **Fatigue does nothing on solo missions** (David's rule): no roll and no row, so a merc who goes out alone cannot move up a tier. `source: Fatigue.cs:Resolve`
- **Fatigue's tiers stack and nothing deletes a trait row.** Don't look for a revoke path; `offDuty.clearsRunningEmpty` and the `Revoke` method are gone. Each row expires on its own `ExpiresTurn`, counted from the mission that granted it. `source: Fatigue.cs:Apply`
- **Fatigue's `minAffected`/`maxAffected` bound the mission's TOTAL grants, across all three tiers.** There is one pool and one clamp, so a floor can force a merc up a tier and `maxAffected: 0` stops every grant on the mission — there is no second path past the clamp. `source: Fatigue.cs:Clamp`
- **One save load fires both `LoadGame` and `LoadGameSlot`,** so every "a save was loaded" line from Elapse, Fatigue, MissionRewards and Progression appears twice. `source: MissionRewards.cs` (load hook comment)
- **No dry runs** (David's rule). No `DryRun` defaults or logging-only sessions; review before the run instead. `source: AGENTS.md`

## Data Dump & diagnostics

- **CKF Data Dump is not read-only, and `[General] Enabled` is not its master switch.** `[TraitProbe]` inserts and deletes traits and `[WriteProbe]` moves credits and writes `NegativeTraitValue` (both ship off). These, ElapseProbe and Trace start before the `Enabled` check, which gates only the table sweep and mission probes. `source: mods/CKFDataDump/Plugin.cs:Load`
- **WriteProbe and ElapseProbe sample only on `SaveManager.ProcessTimelineToNextTurn`.** Loading a save without advancing time records nothing. `source: mods/CKFDataDump/WriteProbe.cs`
- **Table CSVs are overwritten; probe CSVs append across sessions.** A probe CSV whose header changed is renamed `*.pre-<stamp>.csv`. `source: mods/CKFDataDump/MissionProbe.cs:CsvFile`
- **The dumper under-reports failures.** `GameDb` readers swept at the menu can throw past the `catch` and still be `ok` in `_readers.csv`. Keep `Databases = DataDb` outside a mission. `source: mods/CKFDataDump/README.md`
- **The dump doesn't dedupe on the domain id.**
- **Dump columns come out untrimmed by default.** `ModelColumnsOnly`, `DropPresentationColumns` and `DropConstantColumns` all default to `false`. `ModelColumnsOnly` has never removed a column. `source: mods/CKFDataDump/Plugin.cs`
- **`[Dump] Tables`, `Skip` and `Include` match names exactly.** `Weapon` doesn't match `WeaponModel`. `make_overlay.py` needs `--key` for tables outside its `KEYS` map. `source: mods/CKFDataDump/Plugin.cs`, `scripts/make_overlay.py`
- **`--game` derives the dump as `BepInEx/ckf-dump`** in `make_overlay.py` and `validate_rules.py`. If `[Dump] OutputDirectory` points elsewhere, pass `--dump`; `validate_rules.py` exits 2 when the dump directory is missing. `source: scripts/validate_rules.py:main`, `scripts/make_overlay.py:main`
- **`_reward_curve.csv` is not the effective curve.** Whether the sweep sees Hard Mode's `RewardCurve` postfix depends on plugin load order, which is not established [unverified]. Sweep with Hard Mode off for the stock curve; read the effective one from `rewardcurve.json`'s `logEffectiveCurve`. `source: mods/CKFDataDump/CurveSweep.cs`, `RewardCurve.cs`
- **Silence from an instrument is not evidence.** Confirm it could have produced a row. `source: AGENTS.md`
- **Don't reword a log line that `check_run.py` matches with a regex.** It breaks silently. Its `OVERLAY` regex still expects `Overlays: N file(s), M row(s) merged`, but `Overlays.Load` now prints `Overlays: N file(s) in the directory, …`. `source: scripts/check_run.py`, `Overlays.cs:Load`
- **Leave SelfCheck (`[Slices] SelfCheck`) off except during a verification launch.** A stale baseline reports a retune as a regression: retune, turn on, regenerate, read, turn off. Never regenerate to clear a failure. "row not read" is not a pass. No fixtures on rows a clone copies. `source: SelfCheck.cs`

## GUI editor

- **Only `RANGE` and `INVARIANT` problems block a save.** `MISSING`/`STALE` never refuse, so a false problem can show on every save. A check with the same count every run may be looking at the wrong files. `source: gui/serve.py:BLOCKING`, `files_check_schema_reads`
- **A no-op save writes nothing.** `commit` skips any file whose bytes are unchanged, so the file's mtime doesn't move. Any `.pre-gui-backup` is from an older build. `source: gui/serve.py:commit`
- **An unfinished save leaves `.ckf-gui-save-journal.json` behind.** `make_release.py` refuses to build until the editor has been started once to finish the save. `source: gui/serve.py:JOURNAL_NAME`, `scripts/make_release.py:config_sources`
- **`serve.py --selftest --config` takes the config directory, not a file.** `validate_rules.py --game` wants the game root. `source: gui/serve.py:_sandbox`, `scripts/validate_rules.py`
- **`--run-check-schema` must be `argv[1]`** (dispatched before argparse). `source: gui/serve.py:RUN_CHECK_SCHEMA`
- **Frozen, the default game directory is the exe's folder only if `CyberKnights.exe` is beside it;** otherwise it is the hardcoded Steam path. `source: gui/serve.py:default_game_dir`
- **Don't disable a slice checkbox because its key is absent from the `.cfg`.** Saving appends the key; disabling on absence greys out every slice toggle on a fresh install. `source: gui/app.html` (`cb.disabled`), `gui/serve.py:set_value`
- **Keep `HIDDEN_COLUMNS` separate from the constancy rule.** Constancy exempts sheets with fewer than two rows; a declared hide applies everywhere. `source: gui/serve.py:overlay_hidden`, `overlay_constant`
- **An absent cfg key counts as its schema default in the editor, while `check_schema.py` reports it `SKIPPED`.** The two can disagree on a fresh install. `source: gui/serve.py:requires_pass`
- **Anything in C# that rewrites a config document must match `json.dumps(doc, indent=2, ensure_ascii=False) + "\n"` byte for byte.** `Utf8JsonWriter` defaults to CRLF on Windows and escapes non-ASCII and `+`. No C# writes it today; the selftest's zero-byte no-op save would catch it.
- **The frozen exe finds its schemas two independent ways.** (`check_schema.py` shipped at `schema/`, and `--schema` passed explicitly). Remove both and every save is refused; removing one at a time shows nothing. `source: gui/serve.py:run_check_schema_entry`
- **On Windows, poll to see whether a process has exited; don't check once.** `taskkill /F /T` returns before teardown ends; `tasklist /FI IMAGENAME` matches by name, so baseline first. `source: gui/serve.py:_procs_settle`

## Schema checks

See [SCHEMA-FORMAT.md](../schema/SCHEMA-FORMAT.md).

- **Schema files must be strict JSON.** `gen_binds.py` uses `json.load`; `check_schema.py` and the editor accept comments and trailing commas. A comment passes the editor and breaks the bind generator. `source: scripts/gen_binds.py:collect`
- **A numeric field with no `range` is not checked at all.** `source: schema/check_schema.py:check_range`
- **`absent` does not imply `optional`.** Only `"optional": true` silences `MISSING`.
- **`--no-cfg` skips every invariant that names a cfg key** (`SKIPPED`, exit 0).
- **A `mirror` invariant whose `source` file is absent is skipped without a line;** an absent `mergeWith` file raises a traceback. `source: schema/check_schema.py:main` (mirror branch)
- **`targets.json` must name a JSON file.** Pointed at a CSV, `check_schema.py` dies with `JSONDecodeError`; use `targets.overlays`.
- **The stray top-level-key check is inactive.** It runs only for schemas declaring `targets.section`, and none do. Only the runtime (`ConfigDoc.ReadSection`) and the editor's ungraded "undeclared keys" banner see stray keys.
- **The implant-slot schema docs are hand-copied from `Implants.SlotHelp`,** and nothing checks the copy. `source: scripts/implants.py:probe_help`

## Build & release

See [workflow.md](workflow.md).

- **Nothing compares built bytes with disk bytes any more.** `serve.py --selftest --migration` was the only check that did, and it was deleted with the migration block: it converted the frozen 3.0 fixture and compared the result against the live config, which only held while that config was the shipped defaults. So a generator whose output drifts from the file on disk is caught by nothing. `source: gui/serve.py`, above `MIGRATION_DOC_VERSION`
- **Keep the release's required-file list and the directory sweep separate.** `CONFIG_FILES` refuses when a file is absent. The sweep ships any other `.csv`, `.tsv` or `.json` but can't notice an absence. `Defaults.Expected` must still be edited by hand for the mod to report a missing file. `source: scripts/make_release.py:CONFIG_FILES`, `config_sources`; `Defaults.cs:Expected`
- **Two version checks guard a release, and they are independent.** `Defaults.DocVersion` and every slice's `_version` must agree (`check_doc_version`); `Plugin.PluginVersion`, the csproj `<Version>` and the DLL metadata must agree (`check_versions`). Nothing compares the two groups, and since 4.1.0 they no longer hold the same string: `DocVersion` is the settings-layout stamp and bumps on a shape change alone, while the plugin version bumps on a public release. A layout bump restamps all ten slices together. The full bump list is in [workflow.md](workflow.md). `source: scripts/make_release.py`, `Defaults.cs:DocVersion`
- **Expected non-zero gates; don't "fix" them.** `merge_overlays.py --check` exits 1 (`overlays/` has no top-level CSV and the script doesn't recurse); `merge_sidecars.py` and `rules_to_overlays.py` are retired and exit 1; `validate_rules.py --game` without a dump exits 2. `source: scripts/run_gates.cmd`
- **`implants.py --selftest` and `consumables.py --selftest` need `--game`/`--dump`** like their `--check` runs, or they exit 2.
- **A .NET version string's length-prefix byte can be an ASCII digit.** BepInEx's is 53 bytes, read as `5`. Anchor on the length byte. `source: scripts/make_release.py:be_version`
- **BepInEx 6 IL2CPP ships its own .NET runtime in `dotnet\`.** Without it doorstop can't launch. First launch downloads Unity base libraries from `unity.bepinex.dev`, so offline machines stall. `source: scripts/make_release.py:doorstop_wants`, `release/README.txt.in`
- **The sandbox can compile-check but not build the shipping net6.0 artifact.** `apt-get update && apt-get install -y dotnet-sdk-8.0` (the update is required), a `nuget.config` with `<clear />` sources, and a project copy with `TargetFramework` edited to net8.0 (`-p:TargetFramework` still restores net6.0 refs).
- **An MSBuild comment can't contain `--`.** It is an XML comment, so the build fails before it starts.
- **`tests/defaults` needs the BepInEx core DLLs listed in `deps.json`.** Copying them next to the test DLL is not enough. `source: tests/defaults/README.md`

## Working practice

- **Search the dumps and logs before explaining a mechanic.** If it finds nothing, report and stop. Tag claims `[measured]`, `[fitted]`, `[closed]` or `[unverified]`. `source: AGENTS.md`
- **Run numbers and `Logs/` filenames are separate schemes.** A mismatch is not a finding; cite logs by filename and UTC time. [closed]
- **Review anything that writes to a save before it runs.** Make config edits on disk yourself; hand over `cmd.exe` lines with literal paths. `source: AGENTS.md`
- **Verify device file writes.** A same-path `device_commit_files` re-commit has reported `written` and left old bytes. Stage under a distinct name, commit with `expectedMtimeMs`, re-stage and hash. `/mnt/user-data/uploads/` accretes stale files: re-stage before reading; `device_list_dir` is the authority.
- **Copy the whole repo to a quiet local mirror before running gates.** `serve.py --selftest`'s `copytree` races the staging layer's `.stage-tmp.*` files. Partial copies give false reds (a missing `docs/mission-reference.json`, `overlays/`, `release/*.in`), and false greens when both sides of a comparison come from the same partial source.
- **There is no repo-wide line-ending convention.** `ConfigDoc.cs`, `Defaults.cs`, `Plugin.cs` and the csproj use CRLF; the other `.cs` files use LF. Don't normalise a file you are only editing.
- **A marker scrape must require exactly one match.** `Implants.cs` has one `BEGIN LEVER MAP` and three `END LEVER MAP`, so a `find()`-based scrape passes while checking nothing. Copy `consumables.py`'s check. A converter's `--check` must list the directory. `source: scripts/implants.py:probe_map`
- **`Cyberweapons.cs` contains a literal NUL byte (inside the string in `KeyOf`),** so `grep` treats the file as binary. Use `--binary-files=text`.
- **Retiring a check doesn't mean deleting it.** A retired check stays runnable behind a flag and reports `NOT RUN` by name. Divergence from the 3.0 ruleset is not a defect. `source: AGENTS.md`
