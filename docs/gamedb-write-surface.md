# GameDb write surface

What `RPG.Database.GameDb` exposes for writing, the readers the turn-tick code
uses, and which write routes persist. The callers are
`mods/CKFHardMode/Elapse.cs`, `mods/CKFHardMode/Fatigue.cs` and Data Dump's
`WriteProbe`. How to run the probes is in
`mods/CKFDataDump/README.md`.

Use this page to choose an already-tested write route. It does not authorize a
new save write: any code that writes a save is reviewed before it runs.

| Target | Route | Evidence |
|---|---|---|
| Credits | the live manager's `AddCredits` / `SpendCredits` | [measured] Row-only `UpdateGameData` is overwritten on the next turn. |
| Character bars | update the cached `PlayerModel.CharacterModel`, then call `UpdateGameCharacter` | [measured] Cache and row agreed on sampled writes. |
| Game log | `InsertGameLog` exists | [measured] Signature only; no code in this repository calls it. |

## Rebuild the method inventory

Method names and signatures come from `BepInEx/interop/CoreRPG_v1.dll`, a
managed assembly whose method table decodes offline. `scripts/dump_db_surface.py`
is the decoder; rerun it after a game update:

```
pip install dnfile
python3 scripts/dump_db_surface.py "<game>/BepInEx/interop/CoreRPG_v1.dll" --out docs/_gamedb_surface.txt
```

`--types` picks the types (default `RPG.Database.GameDb`, `DataDb`, `CoreDb`)
and `--filter` narrows by method name. The generated listing,
`docs/_gamedb_surface.txt`, is local research output and is not committed.

In this file, [measured] on a signature means the method exists with that name
and signature in the interop assembly. The assembly cannot show whether a call
persists, because an Il2CppInterop proxy's body is a native call. Persistence
claims are tagged separately and come from in-game sessions with
`WriteProbe`/`ElapseProbe` and Hard Mode's `Elapse`.

## Know the whole-row update methods

[measured] Both are instance methods returning `bool`:

```
bool UpdateGameData(RPG.Database.Models.GameDataModel)             // Credits
bool UpdateGameCharacter(RPG.Database.Models.GameCharacterModel)   // character bars
```

[measured] `Credits` is `get/set` on `GameDataModelBase`; `StressScore`,
`LoyaltyScore`, `PositiveTraitValue` and `NegativeTraitValue` are `get/set` on
`GameCharacterModelBase`. They are properties with backing fields, not
constants.

[measured] Every `GameDb` method named here is an instance method. The live
instance is reached from the turn hook as `__instance.Dac.GameDBI`.

### Shape of the surface

[measured] Write-shaped `GameDb` methods by prefix:

| Prefix | Shape |
|---|---|
| `Delete*` | `int Delete<Model>(long)`, a zero-arg truncate per model, and by-column variants |
| `Update*` | `bool Update<Model>(<Model>)`, whole-row, one per model, plus a few targeted setters |
| `Insert*` | `long Insert<Model>(<Model>)`, returning the new id |
| `Save*` | only `long SaveGameFileDownloads()`, unrelated |

A whole-row update is: read the row, set the column, pass the row back. The
targeted setters (for example `long UpdateGameBenchLockedForTurns(long)`,
`bool UpdateGameCharacterSetActiveOnMission(long)`) do not include one for
`Credits` or for any character bar.

## Prefer bulk readers

[measured] Zero-arg instance methods on `GameDb`:

```
GameDataModel               ReadGameData()
List<GameLogModel>          ReadGameLogs()
List<GameMissionModel>      ReadGameMissions()
List<GameCharacterModel>    ReadGameCharacters()
List<GameLogModel>          ReadGameLogsByPage()
List<GameMissionModel>      ReadGameMissionsSorted()
GameMissionModel            ReadGameMissionActive()
List<GameCharacterModel>    ReadGameCharactersOnMission()
List<GameCharacterModel>    ReadGameCharactersOnMissionAndReserved()
List<GameContactModel>      ReadGameContacts()
List<GameCharacterTagModel> ReadGameCharacterTags()
List<GameContactTagModel>   ReadGameContactTags()
```

[measured] `ReadGameCharactersAvailableForMission(long)` takes a mission id.
An expired mission's row is already deleted when the elapse penalty resolves,
so `Elapse.cs` calls `ReadGameCharacters()` and filters with
`GameCharacterModel.IsStatusSafehouseAliveAndActive()`.
[unverified] `Status` 5 is dead and 7 is a side character; the method is false
for both.

Prefer zero-arg readers: a by-id reader that misses throws where a postfix
cannot see it ([`gotchas.md`](gotchas.md)). `Member.Enumerate` stops at 256
items, which drops the newest log rows, so `ElapseProbe` uses its own uncapped
walk. `_elapse_ticks.csv` records the milliseconds of each read.

## Map character bars to columns

Four bars on the roster panel, four columns on `GameCharacterModelBase`. The
column names do not match the bar names.

| Bar | Column | Evidence |
|---|---|---|
| Stress | `NegativeTraitValue` | [measured] a write moved the Stress bar |
| Edge (internally Hype) | `PositiveTraitValue`, displayed via `GetAdjustedHype()` | [fitted] |
| Loyalty | `LoyaltyScore` | [fitted] |
| Discontent | `StressScore` | [measured] writing 8 moved the Discontent bar to 8 and left Stress alone |

Supporting evidence from the interop assembly [measured]:

- `STEStress` has four label/slider pairs (`stress`, `edge`, `loyalty`,
  `disatisfaction`), matching `SetStress(float, float, float, float)`.
- `STEContactInfluence` has two sliders (`loyalty`, `disatisfaction`) over
  `GameContactModelBase.InfluenceScore` / `InfluenceNegative`: the loyalty
  slider takes the positive score, the disatisfaction slider the negative. On
  mercs that is `LoyaltyScore` / `StressScore`, leaving `PositiveTraitValue` /
  `NegativeTraitValue` for Edge and Stress.
- `MutationType` has four independent levers: `StressFlush`,
  `LoyaltyMore`/`LoyaltyLess`, `DisconentMore` (sic)/`DiscontentLess`,
  `HypeFlush`. `IPlayerDataProvider` exposes only `get_CharacterModel()`, so
  `AddHype`, `ReduceStress` and `RollStress` write columns on
  `GameCharacterModelBase`.
  `FlowHypeStressToRelationships(IManager, IPlayerDataProvider, long, long)`
  has the shape of two accumulators flowing into two relationship scores.

[measured] None of the four bars is a sum: Stress is not a total of
`ImplantStress` (a merc with `NegativeTraitValue` 6 and no implants), and
`PositiveTraitValue`/`NegativeTraitValue` are not sums of
`TraitModel.TraitScore` (a merc storing 6/5 against a computed 3/1).

### `IsStatusLimitBreakReady()` is not the stress gate

[measured] `GameCharacterModel` declares `bool IsStatusLimitBreakReady()`. In an
`ElapseProbe` session it returned `false` for every merc on every tick,
including a merc on the tick a stress limit break fired on him. It does not
answer stress limit-break eligibility. A pending-mutation flag is a possible
reading, given `ContactMutationOffer` and `WindowCharacterMutation` in the same
assembly. [unverified]

## Use the route that owns the live value

### Credits

[measured] Writing the row does not survive one turn. `UpdateGameData` returned
`true` and a fresh `ReadGameData()` showed the new balance, but the next turn
tick read the original balance, with no reload.

[measured] The cause: `RPG.Core.GameManagerBase`, the direct base of
`SaveManager` and so the object the turn hook receives, declares
`GameDataModel GameData { get; set; }`. The engine holds its own live model and
writes it back over the row.

[measured] `GameManagerBase` members, inherited by `SaveManager`:

```
void          AddCredits(long amount, string reason)
bool          SpendCredits(long amount, string reason)   // false = cannot afford
void          ProcessCreditsAchievements()
GameDataModel GameData { get; set; }                     // the engine's live model
DataLayer     Dac { get; set; }
void          SaveSlot(int, CoreGameSaveSlotModel, bool)
void          LoadSaveSlot(long)
bool          CanRunQuickSaveOrLoad()
```

`SaveManager` also has `bool CheckCredits(long, bool)`, and `RPG.Core.IManager`
declares the same `AddCredits`/`SpendCredits` pair.

[measured] `AddCredits(100, "CKF WriteProbe")` works: the live object showed the
new balance at once, the row caught up by the next tick, and the in-game
balance rose by 100. The live object is the authority and writes down to the
row. `SpendCredits` returning `false` is the engine's own floor at zero.
`Elapse.cs` caps its charge to the live balance and spends through
`SpendCredits`.

[unverified] What the `reason` string does, including whether it reaches the
in-game log.

### Character columns

[measured] A `GameCharacterModel` write through `UpdateGameCharacter` held for
10 in-session turns, and the value was still there after saving and loading
that save.

[measured, per the `Elapse.cs` header] The row is not what the UI reads.
`SaveManager.playerCache` (`Dictionary<long, PlayerModel>`) holds a live
`PlayerModel` per merc, and its `CharacterModel` is what the roster panel shows
and what the engine writes back. A row-only write read back correctly while the
panel kept the old number. `Elapse.cs` therefore reads `before` from the cached
object, adds to it, passes that object to `UpdateGameCharacter`, and writes the
row as a copy; it falls back to the row only when no cached object exists.
After the switch, cache and row agreed on every sampled write
(`Logs/Log18.txt`, `row N, cache N` lines).

`WriteProbe` samples only when a turn advances, so a save loaded without
advancing time leaves no row in `_write_probe.csv`.
`DataLayer.Connect()` (a save was loaded) and
`DataLayer.CreateSnapshot(long, string)` (a save was written) are the hooks
that would make a probe record those moments.

The save databases are encrypted with SQLite SEE, and this project does not
decrypt them (`scripts/unlock_db.py` is retired). Persistence is checked by
playing.

### Save and load

[measured] Instance methods on `RPG.Saving.DataLayer`, the `Dac` the turn hook
exposes; `GameDBI` hangs off it:

```
bool                  Connect()                  // a save is being loaded
bool                  ConnectForNewGame()
void                  Disconnect()
void                  RefreshCoreGameData(float)
CoreGameSaveSlotModel CreateSnapshot(long, string)        // save to a slot
CoreGameSaveSlotModel CreateSnapshotTmp()
CoreGameSaveSlotModel CreateSnapshotFromTmp(long, byte[])
CoreGameSaveSlotModel CreateSnapshotSafehouse(long, byte[])
void                  PurgeSaveSlot(long)
void                  DeleteSnapshot(CoreGameSaveSlotModel)
```

## Treat game-log insertion as untested

[measured] The log table has the full set:

```
long InsertGameLog(RPG.Database.Models.GameLogModel)
bool UpdateGameLog(RPG.Database.Models.GameLogModel)
int  DeleteGameLog(long)
int  DeleteGameLog()
```

[measured] `GameLogModelBase` columns: `Id`, `LogTypeId`, `GameTurn`,
`Experience`, `Credits`, `Favor`, `ActorId`, `Icon`, `PowerLevel`, `LogTitle`,
`LogText`.

No code in this repo calls `InsertGameLog`. It is an untried write path.

## Verify persistence in game

Do not infer persistence from a `true` return value or an immediate readback.
Use the Data Dump probe named for the route, advance through every sampling
moment it documents, then save and reload when persistence is part of the claim.
`WriteProbe` samples only on turn advance; a reload with no turn advance
produces no row. The probe configuration and output columns are owned by
[`../mods/CKFDataDump/README.md`](../mods/CKFDataDump/README.md).

## Related

- [`mission-elapse-penalty.md`](mission-elapse-penalty.md)
- [`character-fatigue.md`](character-fatigue.md)
- [`gotchas.md`](gotchas.md)
