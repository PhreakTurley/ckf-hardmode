# GameDb write surface

What `RPG.Database.GameDb` exposes for writing, and the reader names the elapse
layer uses. This is the reference for the write API; the callers are
`mods/CKFHardMode/Fatigue.cs` and `mods/CKFHardMode/Elapse.cs`.

## How this was obtained

**No game launch.** `BepInEx/interop/CoreRPG_v1.dll` is an ordinary managed
assembly; its method table and ECMA-335 signature blobs decode offline.
`scripts/dump_db_surface.py` is the decoder — rerun it after any game update.

```
pip install dnfile --break-system-packages
python3 scripts/dump_db_surface.py \
  "C:/Program Files (x86)/Steam/steamapps/common/Cyber Knights Flashpoint/BepInEx/interop/CoreRPG_v1.dll" \
  --out docs/_gamedb_surface.txt
```

The full 1320-method listing is checked in as
[`_gamedb_surface.txt`](_gamedb_surface.txt), alongside `DataDb` (333) and
`CoreDb` (78).

**What the tags mean here.** Everything tagged **[measured]** against the
assembly means the method exists with that exact name and signature. That is a
different claim from "calling it persists": Il2CppInterop emits a proxy whose
body is a native call, so the offline route cannot settle behaviour. Persistence
was settled separately, in game: **character-column writes survive a save and a
reload, and credits go through `AddCredits` / `SpendCredits` rather than the
row.** Both results are below.

---

## Both channels have an update method

**[measured]** Both are instance methods returning `bool`:

```
bool UpdateGameData(RPG.Database.Models.GameDataModel)             // Credits
bool UpdateGameCharacter(RPG.Database.Models.GameCharacterModel)   // StressScore
```

**[measured]** Both target columns are settable. Walking the inheritance chain:
`Credits` is `get/set` on `GameDataModelBase` (18 columns), and `StressScore`
and `LoyaltyScore` are `get/set` on `GameCharacterModelBase` (104 columns).
Neither is read-only and neither is a `const` — these are properties with
backing fields, not literals, so the IL2CPP const-inlining case does not arise.

**[measured]** Every method named in this file is an **instance** method on
`GameDb`. None is static. The live instance comes off the hook the way TraitProbe
proved in Runs 44–46: `__instance.Dac.GameDBI`.

### The shape of the surface

**[measured]** 505 of GameDb's 1320 methods are write-shaped:

| Prefix | Count | Shape |
|---|---|---|
| `Delete*` | 265 | `int Delete<Model>(long)` and a zero-arg truncate per model, plus by-column variants |
| `Update*` | 128 | `bool Update<Model>(<Model>)` — whole-row, one per model — plus 16 targeted setters |
| `Insert*` | 111 | `long Insert<Model>(<Model>)` returning the new id |
| `Save*` | 1 | `long SaveGameFileDownloads()` — unrelated |

`Update` is uniformly **whole-row**: it takes the model, not a column. A write is
read the row → set the column → pass the row back.

The 16 targeted `Update*` setters are the pattern the game itself uses for
single-column edits — for example `long UpdateGameBenchLockedForTurns(long)` and
`bool UpdateGameCharacterSetActiveOnMission(long)`. **There is no targeted setter
for `Credits` or for `StressScore`.** The whole-row route is the only route for
both.

---

## The bulk readers, by name

**[measured]** All zero-arg instance methods on `GameDb`:

```
RPG.Database.Models.GameDataModel            ReadGameData()
List<RPG.Database.Models.GameLogModel>       ReadGameLogs()
List<RPG.Database.Models.GameMissionModel>   ReadGameMissions()
List<RPG.Database.Models.GameCharacterModel> ReadGameCharacters()
```

Neighbours of the same shape:

```
List<GameLogModel>          ReadGameLogsByPage()
List<GameMissionModel>      ReadGameMissionsSorted()
GameMissionModel            ReadGameMissionActive()
List<GameCharacterModel>    ReadGameCharactersOnMission()
List<GameCharacterModel>    ReadGameCharactersOnMissionAndReserved()
List<GameContactModel>      ReadGameContacts()
List<GameCharacterTagModel> ReadGameCharacterTags()
List<GameContactTagModel>   ReadGameContactTags()
```

**[measured]** `ReadGameCharactersAvailableForMission` **takes one `long`**, not
zero arguments:

```
List<GameCharacterModel> ReadGameCharactersAvailableForMission(long)
```

The argument is the mission id, and an expired mission's row is gone by the time
the elapse penalty resolves, so there is no id left to pass. `Elapse.cs` uses the
zero-arg `ReadGameCharacters()` and filters with the engine's own
`GameCharacterModel.IsStatusSafehouseAliveAndActive()` predicate.

### Zero-arg readers are preferred

A by-id reader that misses **throws** rather than returning null, and a postfix
cannot see it — see [`gotchas.md`](gotchas.md), "Assemblies and reflection".
Bulk readers take no id and cannot miss. Every read in `ElapseProbe` is
a zero-arg reader for that reason.

### Read cost

The elapse hook bulk-reads the log every turn, against 561 rows at turn 1382 in
the reference save. `ElapseProbe` writes the elapsed milliseconds of each read
into `_elapse_ticks.csv`. **[measured]** `Member.Enumerate` caps at 256 items,
which silently drops the newest log rows — the ones the filter wants — so
`ElapseProbe` uses its own uncapped walk. See [`gotchas.md`](gotchas.md).

---

## `IsStatusLimitBreakReady()` is not the stress gate

**[measured]** `GameCharacterModel` declares a zero-arg predicate on the leaf
class:

```
bool IsStatusLimitBreakReady()
```

**[measured] It does not answer the stress question.** Run48 called it per merc
per tick and it returned `false` for all 17 mercs on all 8 ticks — including
Tractor on the tick a stress limit break fired on him, and Rhino sitting at the
save's highest `StressScore` of 5 throughout. Whatever this predicate gates, it
is not stress limit-break eligibility. Given `ContactMutationOffer` and
`WindowCharacterMutation` in the same assembly, a pending-mutation status flag is
the likelier reading, but that is **[unverified]**.

### Four bars, four columns, names that do not match

| Player-facing bar | Internal column on `GameCharacterModelBase` | Evidence |
|---|---|---|
| **Stress** | `NegativeTraitValue` | **[measured]**, Run50/51 |
| **Edge** (internally *Hype*) | `PositiveTraitValue`, shown via `GetAdjustedHype()` | [fitted] |
| **Loyalty** | `LoyaltyScore` | [fitted] |
| **Discontent** | `StressScore` | **[measured]**, Run49 |

**[measured]** Run49 wrote `8` into Rhino's `StressScore`. His **Discontent** bar
read 8; his **Stress** bar did not move. `StressScore` is Discontent.

**[measured]** `STEStress` has **four** label/slider pairs — `stress, edge,
loyalty, disatisfaction` — matching `SetStress(float, float, float, float)`.

**[measured]** `STEContactInfluence` fixes the convention: same method shape, two
sliders (`loyalty`, `disatisfaction`) over `GameContactModelBase.InfluenceScore`
/ `InfluenceNegative`. The loyalty slider takes the positive score and the
disatisfaction slider the negative — so on mercs that is `LoyaltyScore` /
`StressScore`, leaving `PositiveTraitValue` / `NegativeTraitValue` for edge and
stress.

**[measured]** `MutationType` has four independent levers (`StressFlush`,
`LoyaltyMore`/`Less`, `DisconentMore` (sic)/`DiscontentLess`, `HypeFlush`), and
`IPlayerDataProvider` exposes no such member at all — only
`get_CharacterModel()` — so `AddHype` / `ReduceStress` / `RollStress` write
columns on `GameCharacterModelBase`.
`FlowHypeStressToRelationships(IManager, IPlayerDataProvider, long, long)` names
the shape: two accumulators flowing into two relationship scores.

**[measured]** None of the four is a sum of anything else: Stress is not a total
of `ImplantStress` (Midnight, `NegativeTraitValue` 6, zero implants), and
`Positive`/`NegativeTraitValue` are not sums of `TraitModel.TraitScore` (Panther,
6/5 stored vs 3/1 computed).

---

## The write path

**[measured] Credits: the database row does not survive one turn.**
`UpdateGameData` returned `true`, a fresh `ReadGameData()` gave the new balance,
and the very next turn tick read the original balance again, **with no reload
involved**.

**[measured] The mechanism.** `RPG.Core.GameManagerBase` — `SaveManager`'s direct
base, so it is the object the turn hook receives — declares
`GameDataModel GameData { get; set; }`. The engine holds its own live model and
writes that back over the row.

### The credit API, on the object the hook already hands us

**[measured]** `GameManagerBase` (inherited by `SaveManager`):

```
void   AddCredits(long amount, string reason)
bool   SpendCredits(long amount, string reason)     // false = cannot afford
void   ProcessCreditsAchievements()
GameDataModel  GameData { get; set; }               // the engine's live model
DataLayer      Dac { get; set; }
void   SaveSlot(int, CoreGameSaveSlotModel, bool)
void   LoadSaveSlot(long)
bool   CanRunQuickSaveOrLoad()
```

and on `SaveManager` itself, `bool CheckCredits(long, bool)`. `RPG.Core.IManager`
declares the same `AddCredits` / `SpendCredits` pair.

`SpendCredits` returning `false` is the engine's own floor at zero, so the mod
does not clamp.

**[measured] `AddCredits` works.** Run52: `AddCredits(100, "CKF WriteProbe")` —
the live object read 3625 immediately while the database row still read 3525, and
by the next turn tick **both** read 3625. David confirmed the balance rose by 100
in game. The engine's object is the authority and it writes down to the row,
which is why the direct row write failed.

**[unverified]** what the `reason` string does. Whether it reaches the in-game
log has not been looked at.

**[measured] A `GameCharacterModel` write persists.** It held for 10 in-session
turns in Run49, and David then saved, loaded that save, and found the value still
there. Character columns survive save and reload; the stress channel of the
elapse layer rests on this.

> The `_write_probe.csv` for that load is empty because the probe only samples on
> a turn advance and the save was loaded without advancing time. The two backward
> turn jumps in the CSV are later loads of the pre-write save.
> `DataLayer.Connect()` (a save was loaded) and
> `DataLayer.CreateSnapshot(long, string)` (a save was written) are the hooks that
> make a probe self-evidencing. See [`gotchas.md`](gotchas.md).

Reading the save file to check directly is not available: the save databases are
encrypted with SQLite SEE, and the script that tried to defeat that
(`scripts/unlock_db.py`) is retired. Persistence is answered by playing.

### The save/load surface

**[measured]** On `RPG.Saving.DataLayer`, all instance methods:

```
bool                    Connect()                  // a save is being loaded
bool                    ConnectForNewGame()
void                    Disconnect()
void                    RefreshCoreGameData(float)
CoreGameSaveSlotModel   CreateSnapshot(long, string)        // save to a slot
CoreGameSaveSlotModel   CreateSnapshotTmp()
CoreGameSaveSlotModel   CreateSnapshotFromTmp(long, byte[])
CoreGameSaveSlotModel   CreateSnapshotSafehouse(long, byte[])
void                    PurgeSaveSlot(long)
void                    DeleteSnapshot(CoreGameSaveSlotModel)
```

`SaveManager.CanRunQuickSaveOrLoad()` sits alongside. `DataLayer` is the `Dac`
the turn hook hands us, and `GameDBI` hangs off it.

---

## Writing an in-game log row

**[measured]** The insert exists, and so do its siblings:

```
long InsertGameLog(RPG.Database.Models.GameLogModel)
bool UpdateGameLog(RPG.Database.Models.GameLogModel)
int  DeleteGameLog(long)
int  DeleteGameLog()
```

**[measured]** `GameLogModelBase` carries eleven columns:

```
Id, LogTypeId, GameTurn, Experience, Credits, Favor, ActorId,
Icon, PowerLevel, LogTitle, LogText
```

Nothing in the shipped mod writes a log row; it is a third untried write path and
is best attempted on its own ([`gotchas.md`](gotchas.md)).
