# Gotchas

Everything that has been tried and does not work, plus every setting or edit
that fails silently. Read this before adding a lever; most of the ideas that
look obvious are already on this page with a reason attached.

Ordering is by area, not by severity. Sources are the mod sources, the live
config under `BepInEx/config/`, and the run records this file replaces.

---

## The save and content databases

- **The content database is encrypted with SQLite SEE and cannot be edited on
  disk.** Entropy 8.000, only bytes 16–23 readable, 12 reserved bytes per page.
  This project does not pursue the key.
- **Repairing the header does not open it.** Writing `SQLite format 3\0` over
  the scrambled header gets `unsupported file format` back, because offset 44 is
  garbage like the rest of the pages. Any extract → edit → repack workflow is
  wrong at step one.
- `scripts/unlock_db.py` was deliberately retired. Do not revisit it and do not
  look for another way round. Save contents are answered by playing and
  observing.
- **All edits happen in memory**, after the game has decrypted its own rows.
  That is what the rule engine and the overlays are.
- A save slot is a snapshot of the live `GameDb`. An inserted row persists
  exactly when the player's progress does.

## The asset bundles

- **They hold no data tables.** 622 bundles and 1,826 MonoBehaviours scanned,
  all negative. Do not re-scan them.
- Equipment prefabs are pure art. One `Monster.prefab` serves all 144 enemies
  with placeholder values overwritten at runtime, and weapon `AssetId` is `0` in
  every instance.
- `StreamingAssets/Locales/en-US.json` is *not* encrypted — 44,662 keys, keyed
  by the same numeric ids as the tables. That is the name lookup.

## Assemblies and reflection

- **`RPG.Database.*` lives in `BepInEx/interop/CoreRPG_v1.dll`**, not
  `Assembly-CSharp.dll`.
- **The interop assembly contains marshalling stubs, not game logic.** There is
  no method body to read and no caller graph to walk. A method name is not
  evidence of a mechanism — this is the single most-broken rule in the repo.
- `CoreRPG_v1.dll` is an ordinary managed assembly, so its method table and
  signature blobs decode offline with `dnfile`; no launch needed.
- **Never patch a method that only does arithmetic.** IL2CPP release linking
  folds identical small function bodies onto one native address, so patching one
  patches all of them and the game stack-overflows on load — with a trace
  pointing at unrelated code in a different plugin. All 91 patches report
  success and nothing is refused. See `patching-rules.md`.
- **Never cache a database instance.** A captured instance that outlived its
  moment caused the Log7 mission hang. The live `__instance` wins.
- **A by-id reader that misses throws**, and a postfix cannot see the throw.
  Prefer the zero-arg bulk readers.
- `AccessTools.TypeByName` costs a `ReflectionTypeLoadException` from
  `UnityEngine.CoreModule` per call — 90 calls once made most of a 4,900-line log.
- `const` fields cannot be patched at all. `__result` on a `void` method is
  refused with an IL compile error; the workaround is a `ref` prefix whose
  parameter name must match.

## BepInEx config mechanics

- **BepInEx preserves a key it did not bind.** Removing a `Config.Bind` orphans
  the key in the `.cfg`; it does not delete it. A stale orphan reads exactly like
  a real setting. This is why Phase 3 deleted the 21 moved keys from the live
  `ckf.hardmode.cfg` by hand: unbinding them would have left all 21 sitting in
  the file, each reading like a setting that does something.
- **Deleting a key while its bind still exists brings it back at the code
  default.** For the old `[Difficulty] MonsterHitPointScalar` that silently
  restored a 2.0 enemy-HP multiplier on a live save.
- **Close the game before editing `ckf.hardmode.cfg`.** BepInEx rewrites the file
  on exit and will undo an edit made while it is running.
- **Every `.cfg` value must sit on one line.** A comma-separated list split
  across lines silently keeps only the first entry.
  **Correction, 3.0.** No key this can bite is in the `.cfg` any more. The only
  `stringList` there was, `[ModelRules] ProbeTables`, is `probeTables` in the
  `modelrules` section of `ckf.hardmode.json` and is a JSON array. The rule is
  kept here because it is a property of the file format, and the file still
  exists.
- `[Diagnostics]` belongs to CKF Data Dump. Nothing in CKF Hard Mode declares it.

## Sidecar JSON

- **Misspelled keys are accepted silently.** `"chancepercent"` (lowercase p)
  leaves `chancePercent` at its default of 25 and the mod writes traits at five
  times the intended rate, with no distinguishing log line. `"enabeld": false`
  leaves credits being spent.
- **`"x0.4"` on a `MissionRewards` field holding `1` gives `0`** — the bonus is
  deleted. Every adjustment is forced through `long`, with banker's rounding.
- **`byPowerLevel` keys `"1"` and `"01"` are distinct keys** that collapse to one
  anchor, and the sort is unstable — the curve becomes non-deterministic across
  runs.
- **`"traitId": 20009` instead of `2009` passes validation** and persists a
  dangling trait reference into the save.
- ~~**`chancePercent: 0` does not switch fatigue off.**~~ Fixed in code before
  2026-09-10: `ThresholdFor` returns 0 for any chance ≤ 0, whatever the resist.
  This entry described the older floor arithmetic and was not updated when that
  changed.
- **A key the refresh script does not generate is no longer preserved.** Anything
  hand-added to a row in the `missions` section is dropped on the next
  `refresh_mission_roster.py` run and on the next GUI save.
- Never hand-write the `teampl` section's `table` block. Corrupting it
  makes the reconcile fail, sets `retroDead`, and silently reverts awards to
  stock while the labels stay modded.
- Never hand-edit `ckf.hardmode.d/MissionPowerLevelModel.generated.json`;
  regenerate it with `scripts/gen_teampl_labels.py`.
- **`Utf8JsonWriter` cannot reproduce `json.dumps` without help.** The config
  document's on-disk shape is
  `json.dumps(doc, indent=2, ensure_ascii=False) + "\n"`, and
  `gui/serve.py --selftest` asserts a no-op save writes zero bytes — so anything
  in C# that rewrites the file has to match it byte for byte. Two defaults get
  in the way: the writer's indented output uses `Environment.NewLine`, which is
  CRLF on Windows against Python's LF, and the default `JavaScriptEncoder`
  escapes non-ASCII and `+`, of which the document has 126 bytes and 16
  respectively. `Defaults.Render` set `UnsafeRelaxedJsonEscaping` and folded
  CRLF to LF for exactly those two reasons.
  **The CR half cannot be tested on Linux**, where `Environment.NewLine` is
  already `\n`: `tests/defaults` asserts it, and only a Windows run gives that
  assertion a sampling moment (AGENTS.md §3).
  **Superseded, 2026-09-07.** `Defaults.Render` is gone with the rest of what
  `Defaults.cs` wrote, so no C# in this mod rewrites the document and the two
  defaults above cost nothing here today. The entry stays because the trap is a
  property of `Utf8JsonWriter`, not of that one caller: the next thing in C#
  that writes this file walks into both defaults again, and the zero-byte no-op
  save assertion in `gui/serve.py --selftest` is still what would catch it.

## The rule engine

- **Match on the domain id, not `Id`.** Almost every model inherits an `Id` from
  a UI row class that reads `-1`. The real key is `WeaponId`, `ArmorId`,
  `MonsterTypeId`, `ImplantTypeId`, and so on.
- **`multiply` compounds on `Game*` models.** `DataDb` rows are re-materialised
  fresh on every read so `multiply` is safe there; `GameDb` rows come from the
  save, so use `set` or `clampMin`.
- **A SQL aggregate has no materialiser.** The engine hooks `GetRow*Model`.
  Anything computed inside SQLite — `SumGameMissionScore` above all — never
  builds a row, so a rule aimed at it does nothing.
- **`"set": {"WeaponTypeId": "20020"}` — a JSON string — loads clean, matches
  rows, changes nothing and reports nothing.** `null` and array values are
  dropped the same way.
- A `set` curve on a `string` column writes the literal; on a `bool` column any
  non-zero writes `true`. The numeric check `Arith` performs is skipped.
- Arithmetic overflow on an `int` column is silently dropped and the trace prints
  `matched, nothing changed`.
- `"model": "weaponmodel"` becomes `"weaponmodelModel"` and is reported as an
  orphan — the lookup is an ordinal `EndsWith` against a case-insensitive
  dictionary.
- A rule whose every operation list is null (a misspelled `"mulitply"`) is
  registered and matched per row for nothing. Nothing checks that a rule carries
  at least one operation.
- String `where` comparison uses the current culture. On a de-DE machine
  `"where": {"SomeFloat": "1.5"}` never matches, with no diagnostic.
- **Some columns are computed and silently ignore writes.** Unsuffixed weapon
  stats are aliases for the selected firing mode and talent `Adjusted*` columns
  are derived; neither is read-only, so nothing warns. Always write the suffixed
  ones — `BallisticDamage1`, not `BallisticDamage`.
- `CharacterTypeModel` is not an enemy table. It is five rows, the player
  classes. `{"model":"CharacterTypeModel","multiply":{"HitPoints":2.0}}` —
  including the one in the plugin's own starter rules file — does nothing. Enemy
  archetypes are `MonsterTypeModel`.

## Cloning and overlays

- **`Overlays.Load` takes `.json` as well as `.csv`.** `ckf.hardmode.d/` is not
  a CSV directory: `Overlays.cs:88-90` globs `.csv`, `.tsv` AND `.json`, and a
  `.json` there is loaded as an ordinary rules file. That is what
  `MissionPowerLevelModel.generated.json` is, and it is why a good launch says
  `Overlays: 4 file(s), 3022 row(s) merged` — three CSVs for 2992 rows and the
  mirror for 30. Counting the directory as "the three overlay CSVs" undercounts
  it by one file and 30 rules; Phase 4's embedded-defaults list was written that
  way and had to be corrected. [measured, Run59 + `Overlays.cs`, 2026-09-03]
  The list that made the mistake no longer exists — the embedded resources were
  removed on 2026-09-07 — but the same undercount is available in its two
  successors, `CONFIG_FILES` in `scripts/make_release.py` and `Expected` in
  `Defaults.cs`, which each name all four files of `ckf.hardmode.d/` by hand.
- **The live `ckf.hardmode.rules.json` contains zero clone rules.** Every clone
  in this project comes from the `_clone` column of a CSV in
  `BepInEx/config/ckf.hardmode.d/`. An audit that reads only `rules.json` will
  conclude cloning is dead. It is not.
- **Enemy gear numbers live in `overlays/*.csv`, not in `rules.json`.** A gear
  rule added back to `rules.json` still runs, but the overlays load after it and
  a `set` there wins, so the rule silently does nothing. Player gear is the
  opposite: it stays a rule, marked with a `PLAYER` comment prefix.
- **Copy `overlays/ckf.hardmode.rules.json` *and* the CSVs, or neither.** The
  rewritten rules file no longer inserts the tiers its pointers aim at, so
  installing it alone is a black screen.
- **A pointer aimed at a row that does not exist stops the mission loading** — a
  black screen, not a degraded stat, and the game's own exception never reaches
  `LogOutput.log`. Watch for `RowClone: <reader>(<id>) found nothing`.
  `scripts/validate_rules.py` catches this before you launch. Run it.
- **`CloneServeOnBulkReads` must stay off.** An append landing after the game has
  already built from the list cost a mission load in Run 42.
- **Do not run the dumper's sweep while cloning is on.** The sweep calls
  `ReadArmors()`, the clones get appended to the returned list, and from then on
  the game resolves armour from something built out of that list rather than by
  id, and dies on a null. Set CKF Data Dump `[General] Enabled = false` before
  testing gear.
- **`DataDb.ReadWeapon` returns a defaulted row for an unknown id**, so a
  SelfCheck expectation on a row that does not exist reports PASS.
- **A cloned row has no locale name** until one is added to
  `StreamingAssets/Locales/en-US.json`.
- **Do not repurpose anything on the 74-row "unreferenced `EffectModel`" list.**
  Rows 65001–65005 are referenced by `SecurityDeckCardModel.CardEffectId`, a
  table the scan did not check. The whole list is unproven. Clone into the
  reserved `900000+` range instead.
- `WeaponId` 20010/20011 ship unreferenced as "Guard Rifle Lvl11/12" and are safe
  to point at. `WeaponId` 23097–23099 are developer work in progress, not free
  space.
- Nothing establishes what the game derives from an id it has never seen.
  `MonsterSpawnModel` and `MonsterGroupModel` clone rules will run, but what a
  synthetic row means there is unknown. Work that out before relying on one.
- **A ladder file's line count is not its block's size.** A 20-tier block can be
  14 lines because 6 of its tiers are rows the game already ships.

## Team Power Level

- **Rules on `MissionPowerLevelModel` change the victory-screen label, not the
  award.** Set to 3.0, the screen printed "Team gained 3 PL" while the sum moved
  0.015. The award and the label are separate edits to separate things, and
  neither follows the other.
- The 33 `MissionPowerLevelModel` rules are deliberate. An earlier note saying to
  delete them was wrong.
- `SetMissionPowerLevel` never fires. The award is an INSERT into
  `GameMissionScoreModel`.
- **Team PL is not in a database row.** `GameDb.GameDataModel` has no
  `PowerLevel` column; `CoreGameDataModel.PowerLevel` is a mirror of the sum.
  Team PL is `SUM(GameMissionScoreModel ⋈ MissionPowerLevelModel)`.
- `teampl.enabled` without `modelrules.enabled` gives a correct award
  with a stock label; the reverse gives a stock award with a lying label.
  **Neither direction logs anything.**
- `override[]` is retroactive and `CoreGameDataModel.PowerLevel` persists the
  substituted total, so turning it back off leaves a modded figure in the save.
- An override on `(ActionClass 0, MissionPowerLevel 0)` never takes effect for
  the session — the game's own sum does not move, so the cache-invalidation guard
  never fires. All 34 LEGWORK rows are `(0, 0)` and worth zero in the stock
  table, so an override there re-prices every LEGWORK row from a base of zero.
- `Progression.retroDead` is process-lifetime. One transient throw disables
  retroactive Team PL until the game restarts, including across save loads.

## Power Level and difficulty

- `GameDifficultyModel.CalculatePowerLevel` **saturates at 10 for every input** —
  it is the clamp itself, not a passthrough.
- `MinCap = 12, MaxCap = 20, MatrixMaxCap = 10` inverts the clamp and produces a
  level above both the Matrix ceiling and the game's own stock clamp, unlogged.
- `MatrixOffsetMode = Replace` is confirmed: the Matrix path uses
  `MatrixPowerLevelOffset` *instead of* `BasePowerLevelOffset`, not on top.
- `DerivedCallMode = Recompute` is what turned a reward of 1 into 2. PassThrough
  is pinned.
- **Lifting the Power Level cap does not lift the reward cap.** The base curve
  flatlines above PL 10 at 2800 credits / 500 XP; the `rewardcurve` section is the only
  thing that changes it.
- Above PL 10 the shipped weapon damage flatlines too — median
  `BallisticDamage1` is 255 at PL 10 and at PL 20, and the maximum *falls*
  594→525. Raising the cap alone gives you sponges, not lethality.

## Elapse and Fatigue (the save-writing subsystems)

- **THE TRAP.** In `Elapse.Resolve` the save writes are arguments to log-string
  builders — `summary.Add(SpendCredits(...))`, `parts.Add(WriteStress(...))`.
  Deleting the list plumbing deletes both save-write channels and leaves
  `[Elapse] Enabled = true` doing nothing (the key that read is `elapse.enabled`
  since 3.0). Refactor as extract-the-call,
  discard-the-return. Never "delete the list".
- **A reflection miss on `ExpiresTurn` leaves it 0, which this mod treats as
  permanent.** Every merc that rolls a hit takes a permanent, save-resident
  Running Empty or Off-Duty trait the mod cannot remove.
- Credits are committed before Stress is attempted, with the replay guard already
  set. A half-applied penalty is never retried and nothing signals it.
- **Reloading onto the same or the next turn defeats Elapse's turn-discontinuity
  fallback** — every mission expiry in the loaded save is then ignored for the
  rest of the process. The load hook is not optional.
- Elapse's log high-water mark advances before the row is classified, so a
  transiently unreadable row is skipped forever and never logged as unmatched.
- **`MissionRewards` static caches are keyed by save-local row ids and never
  cleared.** Load save B in the same process and its rewards are scaled off save
  A's base.
- Two subsystems postfix `GameDb.GetRowGameMissionRewardModel` with no
  `HarmonyPriority`. The result is stable-but-wrong (3× or 2×), not obviously
  flapping.
- `Fatigue`'s session state has no fallback reset; quitting to menu mid-mission
  can escalate the wrong mercs on the wrong power-level curve.
- `Writability`'s restore guarantee is not one — a setter that throws on the
  second write leaves the probe value on the row for the session, unlogged.
- **Credits cannot be written through `UpdateGameData`.** The call returns true
  and the next turn tick restores the original, because
  `GameManagerBase.GameData` is the live authority and writes down over the row.
  Use `AddCredits(long, string)` / `SpendCredits(long, string) -> bool`, and take
  `SpendCredits` returning `false` as the engine's own floor at zero.
- **A `GameCharacterModel` column write persists, but the roster panel does not
  read the row** — it reads `SaveManager.playerCache[id].CharacterModel`. Write
  both or the change is invisible.
- **Written Stress is consumed by the limit break it feeds.** `NegativeTraitValue`
  written to 8 read 2 two ticks later, with a Vulnerable trait logged.
- `IsStatusLimitBreakReady()` is **not** the stress gate — false for all 17 mercs
  on all 8 ticks, including the tick a break fired.
- **A joined content property can be null, and a null is not an empty.**
  `GameCharacterTraitModel.EffectData` is filled by the by-character reader and
  not by the by-id one (RUN44). The same property on implant, effect and
  job-node rows was assumed filled and never checked, and Fatigue skipped a null
  silently, so Run63 logged "no resist" for four mercs with nothing to say why.
  Fatigue now looks the effect up in `DataDb` and prints per-reader counts on the
  roll line. Any new reader of a joined property should do the same: check it,
  count the nulls, and log them.
- **Elapse keys its curves on `PowerLevelUnscaled`; Fatigue keys its on the
  effective `PowerLevel`.** Same table name, same shape, different numbers.
- `stress.applyTierMultiplier` scales **`mercCount`**, not the Stress amount.
- **No dry runs.** Do not build a `DryRun` default of `true`, do not ask for a
  logging-only session first, and do not gate a live test on one. `[Elapse]
  DryRun`, `[MissionRewards] DryRun` and `[RewardCurve] DryRun` do not exist —
  writing one into the `.cfg` gets you live credit spends and live
  `NegativeTraitValue` writes.
- `Status` decode: **5 = dead**, **7 = a side character, not selectable**, 4 not
  established. `IsStatusSafehouseAliveAndActive()` is false for all three.

## The injury route (shelved)

Kept so it is not re-derived. `MedicalTurn > GameTurn` is the game's own
out-of-action state, written with `MedicalTurn = GameTurn + days*4` then
`GameDb.UpdateGameCharacter(model)`; `SaveManager.ProcessCharacterMedicalTurns`
runs every turn and self-clears it.

- A future `MedicalTurn` also blocks cyber surgery, legwork, the Detox bench and
  stress treatment. It does not block the medical bench.
- A raw write bypasses `RuleModel` 40 Max Injury Time (100 turns / 25 days),
  `GameSafehouseModel.GetInjuryTime`, `EffectSpecialCode 16 InjuryReduction` and
  `GameDifficultyModel.GameSpeedScalar`.
- `Status` 13 = `MedicalBench`, 14 = `CyberBench`; both bench-owned via
  `LockedForTurns`.

This route was rejected in favour of trait insertion. It was never built and
never observed in game.

## Dumping and diagnostics

- **CKF Data Dump is not read-only.** `[TraitProbe]` inserts `GameCharacterTrait`
  rows and `[WriteProbe]` calls `AddCredits`/`SpendCredits` and writes
  `NegativeTraitValue`. Both ship disabled. `[General] Enabled` is the table-sweep
  switch, not a master switch — `[Diagnostics]`, `[TraitProbe]`, `[WriteProbe]`
  and `[ElapseProbe]` all initialise before it is checked.
- **The dumper under-reports failures.** Four `GameDb` readers throw
  `NullReferenceException` when swept at the main menu and `_readers.csv` records
  all four as `ok` — the exception surfaces through the il2cpp trampoline, past
  the sweep's `try`/`catch`. Use `[Dump] Databases = DataDb` unless you are in a
  mission.
- There is no dedupe on the domain id; Run 32's `WeaponModel.csv` carried
  `WeaponId` 13000 twice.
- **`_reward_curve.csv` can never show a patched curve.** CKF Data Dump loads
  first and sweeps before CKF Hard Mode patches (sweep at log line 4081, patch at
  4548). Use `rewardcurve.logEffectiveCurve` instead.
- `PreloadTables` / `DumpAllRows` were why every early dump was partial —
  `GetRow<X>Model` fires only for rows the game reads. Twelve tables out of 192
  passed for a complete capture across a dozen runs, and loot was never among
  them.
- Parsing `LogOutput.log` into sheets is obsolete; the dumper writes CSV.
- **Unity exceptions never reach `LogOutput.log`.** A hung mission otherwise
  leaves an empty log; the `RowClone` dangling-pointer warning is the only
  pre-black-screen signal.
- **An instrument's silence is not evidence.** Four documented incidents: a by-id
  reader that throws where a postfix cannot see it; `[Diagnostics] FindMethods`
  logging nothing because its call site sat below `if (!enabled) return;`;
  `WriteProbe` sampling only on a turn advance, so a save loaded without
  advancing time produced no row; `ElapseProbe`'s board diff deciding a mission
  was deleted by not finding it.
- Never delete or reformat a log line matched by one of `check_run.py`'s ten
  regexes — it breaks the verifier silently.
- Keep a copy of the **live** log. It carries Unity messages (`Restoring
  Monster`, the spawn commands) that the saved copy does not.

## SelfCheck

- `selfcheck.enabled` ships **off** and should stay off outside a verification
  launch. Against a stale baseline it reports a retune as a regression. The order
  is: retune → turn on → regenerate → read → turn off.
- Regenerating the baseline after a retune is the point. Regenerating to make a
  failure go away is not.
- SelfCheck is gated behind `modelrules.enabled` and reached through
  `RowClone`. With `modelrules.enabled` false it is handed no database types,
  says so at Error and checks nothing.
  **Correction, 3.0.** This entry used to end "the whole `[SelfCheck]` section is
  dropped from the `.cfg` as an orphan", which was the reason `SelfCheck.Init` is
  called from `Plugin.Load` rather than from inside `ModelRules.Init`. That
  failure mode is gone: the three keys are the `selfcheck` section of
  `ckf.hardmode.json`, and a JSON key needs nothing done to it to stay on disk.
  The call site did not move — a launch with ModelRules off is exactly the one
  where this subsystem has something to say — but the reason it is there has
  changed.
- **Not judged is not passed.** A `row not read` result is not a pass.
- A database is per *type*, not per table — a `GameDb` selfcheck run read only
  `WeaponModel` and 96 checks came back "row not read".
- Do not put a test fixture on a row that a clone rule copies.

## Settings that were removed or renamed

**3.0 moved 21 of the 22 cfg keys, and it is a move rather than a removal.**
`[General] Enabled` is the only key left in `ckf.hardmode.cfg`. Everything else
lives in `ckf.hardmode.json` under its subsystem's section: `[PowerLevel] MaxCap`
is `powerlevel.maxCap`, `[SelfCheck] Enabled` is `selfcheck.enabled`, and each
subsystem's `Enabled` folded into its section's own `"enabled"` rather than
becoming a second one. The rows below are keys that no longer exist anywhere;
`docs/config-reference.md` is the current address of every key that does.

Older logs and notes reference settings that no longer exist. The current surface
is 22 `.cfg` keys in ten sections plus five sidecar JSONs, all declared in
`schema/*.schema.json` and documented in `config-reference.md`.

| Gone | Use instead |
|---|---|
| `[PowerLevel] ScalarOverride`, `UseOffsetOverride`, `OffsetOverride` | `[Difficulty] PowerLevelScalar`, `BasePowerLevelOffset`, `MatrixPowerLevelOffset` (the game's own sliders, widened) |
| `[PowerLevel] ScaleDerivedCalls`, `TeamPowerLevelSource`, `ApplyMatrixOffset` | renamed; now hardcoded constants |
| `[PowerLevel] TeamPowerLevelOverride` and the five DB-fallback keys | gone for good |
| `[Progression] MinGain` | shape awards in the `teampl` section — its guard was `before > 0`, which skipped the floor in exactly the case it existed for |
| `[Progression] GainScalar`, `GainOverride`, `RetroactiveTable` | retroactive is the subsystem's only mode; shape in the `teampl` section |
| `[MissionRewards] SoloHackTeamPowerLevelScalar` and the six other bucket keys | per-type rows in the `missions` section; there is **no pattern layer**, one `MissionTypeId` per row, matched exactly |
| The 20 `[Difficulty]` scalar knobs | the game's own custom-difficulty sliders, widened by `SliderRangeMultiplier` |
| `[ModelRules] CompiledAccessors`, `EnableRowCloning`, `CloneServeById`, `CloneFreshInstances`, `CloneServeOnBulkReads` | hardcoded |
| `[Elapse]/[MissionRewards]/[RewardCurve] DryRun`, the three `LogFirst` extras | gone |

## Working practice

- Search the local dumps and logs before explaining a mechanic. If the search
  comes up empty, report the observation and stop — a list of plausible
  mechanisms is a guess wearing a lab coat.
- Tag claims: `[measured]`, `[fitted]`, `[closed]`, `[unverified]`. An untagged
  claim reads as established fact to the next reader.
- Corrections stay visible. Do not quietly edit a wrong claim out.
- **Run numbers and the files in `Logs/` are two independent schemes, and a
  mismatch between them is not a finding.** Agents number their own runs; some
  of those were direct reads of the live `BepInEx/LogOutput.log`, which is
  overwritten on every launch and was not always saved into `Logs/`. So a
  document citing "Run58" may mean a log that no file of that name contains.
  This is settled — do not investigate it. Cite a log by its filename and a UTC
  timestamp; if a run number is needed, say which of the two you mean.
  [David, 2026-09-03] `[closed]`
- Anything that writes to a save gets a review **before** it runs.
- Hand over `cmd.exe` command lines with literal paths, never PowerShell `$VAR`
  syntax, and make the config change on disk rather than listing keys to flip.
- The sandbox can compile-check but cannot build the shipping artifact: only the
  net8.0 targeting pack is available, and a `nuget.config` with
  `<packageSources><clear /></packageSources>` is required or restore fails.
  **The SDK is not in the image and has to be installed**, which is two
  commands — `apt-get update` then `apt-get install -y dotnet-sdk-8.0` — and the
  `apt-get update` is not optional: without it the dotnet packages 404. A Cowork
  session's proxy denies `api.nuget.org`, which is why the cleared package
  source matters and why `net6.0` cannot be restored at all.
  **Correction, 2026-09-03:** the Phase 3 handoff said there was no C# compiler
  in the container and that C# changes could only be reviewed by diff. That was
  wrong — this bullet was already here and was not read. Phase 4's C# was
  compiled, and `tests/defaults` ran 94 checks against the built DLL.
- **An MSBuild comment cannot contain `--`.** It is an XML comment, so a
  `.csproj` comment quoting a command line with a long flag is a parse error and
  the build fails before it starts. Name the flag in prose or put the command
  line in a Markdown file next to it.
- **`-p:TargetFramework=net8.0` does not override the csproj's `net6.0` for the
  sandbox verification build.** Restore still resolves `Microsoft.NETCore.App.Ref
  6.0.36`, which the cleared package source cannot supply, and the build fails
  before compiling anything. Copy the project to a scratch directory and edit
  the `TargetFramework` element instead — that is what "a net8.0 verification
  build, not the shipping artifact" means in practice. [measured 2026-09-04]
- **`tests/defaults` needs the BepInEx core DLLs listed in `deps.json`, not just
  present in the output directory.** `BepInEx.Paths`' static initializer pulls
  in `SemanticVersioning.dll`, and a framework-dependent app resolves by
  `deps.json` rather than by probing its own folder, so copying the core DLLs
  next to `DefaultsTests.dll` is not enough: every scenario fails with
  `TypeInitializationException`. `tests/defaults/README.md` has the fix.
  [measured 2026-09-04, container]
- **PyInstaller: two independent things make the frozen editor find its schemas,
  and removing either one alone changes nothing.** `check_schema.py` shipped as
  a data file at `schema/check_schema.py` puts the frozen module's `__file__` in
  `<_MEIPASS>/schema`, so `check_schema`'s own `--schema` default resolves;
  `run_check_schema_entry` passes `--schema` explicitly, so it resolves wherever
  `__file__` lands. Drop both and the exe prints `no *.schema.json in <_MEIPASS>`
  and every save is refused. A fault sweep that removes one at a time catches
  neither — the sweep has to remove both. [measured 2026-09-04]
- **A .NET version string in an assembly is length-prefixed, and the length byte
  can itself be an ASCII digit.** `AssemblyInformationalVersion` is stored as a
  SerString: one compressed-length byte, then UTF-8. BepInEx's is
  `6.0.0-be.785+<40 hex commit>`, 53 bytes, and 53 is ASCII `5` — so a regex
  reading `\d+` leftward swallows the length and reports the build as
  `56.0.0-be.785`. Anchor on the length byte instead: trim leading digits until
  the byte before the match equals the bytes remaining AND what is left still
  matches the whole pattern. Walking the start forward one byte at a time
  without that second condition reads `6.0.0-be.999+<40 a>` preceded by an `x`
  as the build `-be.999`, because the fifth byte is an ASCII `0` and 48 bytes
  follow it. `scripts/make_release.py:be_version` got this wrong twice.
  [measured 2026-09-04, against `BepInEx/core/BepInEx.Core.dll`]
- **`EmbeddedResource` is stored uncompressed, which makes "is this DLL stale"
  a substring search.** Each embedded file's exact bytes appear verbatim in the
  assembly that embedded it, so `open(src,'rb').read() in dll_bytes` is a
  content comparison and needs no metadata parser. That was what
  `make_release.py`'s `check_embedded` gate used instead of comparing mtimes,
  because a timestamp is a fact about the filesystem and not about the artifact.
  [measured 2026-09-04, all seven defaults found in the 814,592-byte Release
  DLL]
  **Superseded, 2026-09-07.** The seven `<EmbeddedResource>` entries were
  removed from `CKFHardMode.csproj` and the config files now ship loose in the
  zip, so there is nothing embedded left to go stale. `check_embedded` and the
  `embedded_sources` table it walked are deleted from `make_release.py`. The
  technique above is still correct about the CLI format and is kept here because
  it is the cheap way to answer "does this assembly contain these exact bytes"
  for any DLL that *does* embed something — it is no longer a check this repo
  runs. What replaced it is `check_doc_version()`, which compares the `_version`
  in `mods/CKFHardMode/defaults/ckf.hardmode.json` with the `DocVersion` literal
  in `Defaults.cs`; the shipped file's own bytes need no proving because the same
  file is what goes into the zip.
- **`3.0.0` appears inside the 2.13.0 `CKFHardMode.dll` and it is not the
  version.** It is the config document's LAYOUT version — it moves when the
  layout does, not when the mod ships. Anything looking for the assembly's
  version has to look for the length-prefixed form. [measured 2026-09-04]
  **Correction, 2026-09-07.** This entry located the string as
  "`Defaults.DocVersion`, inside the embedded `ckf.hardmode.json`", which is two
  places at once. They were both in the DLL when it was measured, and only one
  of them still is: `Defaults.DocVersion` is an `internal const string` in
  `Defaults.cs` and still exists, while the embedded document that carried the
  same number in its `"_version"` went with the rest of the embedded resources.
  What form the const takes in a 3.0 assembly has not been measured — no build
  was run for this correction — so treat the length-prefixed advice above as
  covering the `AssemblyInformationalVersion` case it was measured against and
  nothing more.
- **Windows tears a process down asynchronously, so "is it still running?" has
  to be polled, not sampled.** `taskkill /F /T` returns when it has issued the
  terminations, not when they are complete, and `Popen.wait` covers only the
  process this one owns. Asking `tasklist` once, immediately after the kill,
  reports the application the bootloader launched as still running when it is
  mid-teardown. `gui/serve.py`'s frozen-exe case did exactly that on the first
  Windows run: **the "no process is left running" check FAILED while the "the
  directory could be deleted" check beside it PASSED**, and a running exe
  cannot be unlinked on Windows, so whatever it saw was gone within the
  delete's own 30 seconds. `_procs_settle` polls on the same budget
  `_rmtree_retry` already used. [measured, David's Windows run, 2026-09-04]
- **`tasklist /FI "IMAGENAME eq X.exe"` matches by NAME, not by path.** Any
  other copy of the same executable anywhere on the machine counts. A check
  asking "did MY copy leak a process" has to take a baseline before it launches
  anything and subtract it, or the answer is about the machine rather than
  about the copy.
- **BepInEx 6 for IL2CPP ships its own .NET runtime, and it is most of the
  download.** `dotnet\` is 187 of the 232 files in `CKF-Hard-Mode-3.0.0.zip`
  and 35 of its 43 MB. `doorstop_config.ini` names it — `coreclr_path =
  dotnet\coreclr.dll`, `corlib_dir = dotnet` — so a BepInEx tree unpacked
  without it extracts, installs, and does not launch: doorstop finds no
  runtime. It belongs to BepInEx, not to the game: every file in the live
  install's `dotnet\` carries the BepInEx extraction mtime (1785199898–99),
  while `CyberKnights.exe` and `UnityPlayer.dll` are at 1775867726, ten million
  seconds earlier. [measured 2026-09-04]
- **A config file that reads back at its shipped default is not proof the
  editor's save did nothing.** `serve.py`'s `commit` skips any file whose
  proposed bytes equal what is on disk and returns `written: []` when that
  leaves nothing, so a no-op save writes nothing and moves no mtime; and the
  `.pre-gui-backup` is written only when one does not already exist, so a
  second save keeps the first save's backup. A document sitting at its default
  with a moved mtime and a default-valued backup beside it therefore means two
  saves — one that put a value in and one that took it back — not a save that
  failed. Read the mtimes and the backup together before concluding anything.
  [measured 2026-09-07, from Run61/Run62's install]
- **BepInEx's first launch downloads Unity base libraries over the network.**
  `InteropManager] Downloading unity base libraries from
  https://unity.bepinex.dev/libraries/<unity version>.zip`. It is the only
  network access anything in the player zip makes, it happens once per Unity
  version, and an offline or firewalled machine will not get past it.
  `release/README.txt.in` says so. [measured, Run61 line 8]
