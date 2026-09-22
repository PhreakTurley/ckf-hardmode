# Mission elapse penalty

Use this page to trace an unplayed mission from the game's expiry log to the
Hard Mode elapse subsystem in `mods/CKFHardMode/Elapse.cs`. The subsystem has
two write channels: a credit charge and Stress for selected mercs. It does not
write contact state, heat, or replacement missions. Settings and defaults
belong to [`config-reference.md`](config-reference.md).

Evidence tags: [measured] means reproduced from a dump, a CKFDataDump probe (`ElapseProbe`, `WriteProbe`) or `Logs/Log18.txt`. [fitted] means the model fits but is unconfirmed. [unverified] means never observed.

## Shipped expiry behavior

### The expiry record

- `GameLogTypes.MissionExpire = 202` (`_id_constants.csv`).
- [measured] The reference save holds 20 such `GameLogModel` rows, turns 715–1367. The title reads `<TITLE> Window Closed` and the text reads "We missed the window of opportunity to …".
  - `ActorId` is blank.
  - `Experience`, `Credits` and `Favor` are all 0.
  - The row carries a turn and a title and nothing else usable.
- [measured] Gaps between consecutive expiries run from 1 to 76 turns, with a median of 33. Two expiries can land on adjacent turns.
- [measured] **The `GameMissionModel` row is deleted when the window closes.** A mission vanished from `ReadGameMissions()` between two turns. No flag was set on its way out: `IsActive`, `IsComplete` and `IsFailed` were all 0 and unchanged.
- [measured] Expiries with no contact exist. `M_PGen_HackingStation_Loot3_HackLoot` carries `ContactId = 0`, and its log text uses the "to finish the job known as" form.
- [measured] The expiry row is stamped with the turn that is ending. Every `202` row on record is stamped `EndTurn + 1`.
  - A postfix on `ProcessTimelineToNextTurn` reads `GameData.GameTurn` after it has advanced, so it sees the row at `turn − 1`, which is `EndTurn + 2`.
  - Other log types written on the same tick (trait expiry, limit break) show the same offset.
  - `Log18.txt`: PIANO RUN, `EndTurn 1385`, was resolved at turn 1387. EASTWIND RAPTOR 1409 → 1411, ALLEYWAY CALL 1421 → 1423, UNRAVELED LEASE 1429 → 1431, BULL RUSH HANDLER 1430 → 1432.
- The game moves mission deadlines on purpose; for example, a mission due while a merc is in surgery is pushed back. [unverified] Which turn the deadline shown to the player corresponds to.
- `GameMissionScoreModel.ActionClass` is written on completion only, so an expired mission has none.

### Credits

- [measured] `GameManagerBase.AddCredits(long, string)` and `SpendCredits(long, string) -> bool` move credits. `SpendCredits` returns `false` when the crew cannot afford the amount. `RPG.Core.SaveManager` inherits both.
- [measured] **Credits cannot be written through `UpdateGameData`.** The call returns `true` and a fresh read shows the new balance, but the next tick restores the old one.
  - `GameManagerBase` holds its own live `GameDataModel` (the `GameData` property) and writes it back over the row.
  - After `AddCredits`, the live object updated first and the row caught up on the next tick.
- [unverified] What the `reason` string does.

### The four character bars

The column names do not match the bars shown to the player.

| Bar shown to the player | Column on `GameCharacterModelBase` | Evidence |
|---|---|---|
| Stress | `NegativeTraitValue` | [measured] writing it moved the Stress bar |
| Edge (internally Hype) | `PositiveTraitValue`, shown via `GetAdjustedHype()` | [fitted] |
| Loyalty | `LoyaltyScore` | [fitted] |
| Discontent | `StressScore` | [measured] writing it moved the Discontent bar only |

- **Evidence for the mapping.**
  - `STEStress` has four label/slider pairs (`stress, edge, loyalty, disatisfaction`) matching `SetStress(float, float, float, float)`.
  - `STEContactInfluence` maps `InfluenceScore` / `InfluenceNegative` to loyalty / disatisfaction.
  - Stress is not a sum of `ImplantStress`. The Positive/NegativeTraitValue columns are not sums of `TraitScore`.
- **Column properties.** [measured] All four are writable `long` columns. They are written through the whole-row `UpdateGameCharacter(GameCharacterModel)`, and a write survives save and load.
- **The roster reads a cache.** [measured] The roster panel reads the engine's cached object, not the row.
  - `SaveManager.playerCache` is a `Dictionary<long, PlayerModel>`, and `PlayerModel.CharacterModel` is what `View_RosterPanel_Info.PopulateStressView` and `PlayerDataManager.RollStress` / `ReduceStress` use.
  - A row-only write stayed invisible until the engine rebuilt that merc's `PlayerModel`. [unverified] What triggers the rebuild.
  - [measured, `Log18.txt`] Writing through the cached object showed row and cache equal on every tick after the write.
- **Stress is consumed.** [measured] A merc's `NegativeTraitValue` was written to 8 and read 2 two ticks later. The log for that turn records a limit break: "Rhino suffers Trait Vulnerable for 30 days — Due to excessive Stress …". Discontent written to 8 held for ten turns.
- **What does not gate a limit break.** [measured] `IsStatusSafehouseAliveAndActive()` answers whether a merc is in the safehouse, alive and active. `IsStatusLimitBreakReady()` was false on every tick, including the tick a limit break fired. [measured] The limit-break threshold is not in `RuleModel`.
- [measured] `IsStatusSafehouseAliveAndActive()` returned false for statuses 4,
  5, and 7. [unverified] Their exact meanings; status 5 has been described as
  dead and status 7 as a non-selectable side character, but neither mapping has
  been established from a shipped declaration.

### Merc–contact relationships

- A merc's edge to a contact is a set of `GameCharacterTagModel` rows with `CharacterId = merc` and `ActorId = "NID_" + contactId`.
- [measured] Relationships are stored as a stack of rows (root, flavour, leaf) with the same `CreatedTurn`. Family edges write four rows. Every row in a stack carries the same polarity.
- [measured] Polarity is `TagModel.RelType`: `1` on 23 verbs, `-1` on 26, `0` on 12 (the six `DeathTag_*` and the six headhunting tags).
  - `TagScore` is intensity, not sign. `RelTag_Lover` and `RelTag_Hates` are both 3.
  - `RelTag_ExSpouse` has `RelType = 1` but `TagMatch = RelTag_SexyDislikes`.
  - A per-save row for one edge read `TagScore 0`.
- [measured] `RPG.Saving.DataLayer` declares `DataDBI` beside `GameDBI`, and `DataDb.ReadTags()` returns `TagModel`.
- [measured, reference save] 29 merc↔contact pairs: 13 positive, 11 negative, 4 neutral, 1 mixed. Only 13 of 60 contacts have a positively linked merc, reaching 9 of 16 mercs. This is a sample, not the full set.

## Hard Mode elapse subsystem

- Gate: `[Slices] Elapse` in `ckf.hardmode.cfg`.
- Settings: `ckf.hardmode.d/elapse.json` (`schema/elapse.schema.json`).
- This subsystem writes to the save. On load it logs `Elapse: ACTIVE, and this subsystem WRITES TO YOUR SAVE.`
- [measured] The penalty applies inside the same `ProcessTimelineToNextTurn` call that writes the LogTypeId 202 row.

### Hook and expiry detection

A postfix on `RPG.Core.SaveManager.ProcessTimelineToNextTurn` runs under Harmony id `ckf.hardmode.elapse`. It reaches `GameDb` through `.Dac.DataLayer.GameDBI`, never stores it, guards its own calls with a `[ThreadStatic]` re-entrancy flag, and swallows every exception. Each tick:

1. **Snapshot.** Read `ReadGameMissions()` into a new snapshot keyed by `MissionTitle`. If two live missions share a title, keep the one with the lower `EndTurn` and log a warning. The other is recorded after the first is released.
2. **Find new expiries.** Read `ReadGameLogs()`. Every `LogTypeId 202` row whose `Id` is above the session's high-water mark is a new expiry.
   - The first complete read of a session sets the mark.
   - The mark advances only on a complete read.
   - After a partial log read or a partial board read, the previous snapshot is kept.
   - The row's turn stamp is recorded, not filtered on.
3. **Resolve.** Strip ` Window Closed` from each new row's title and look it up in the previous tick's snapshot, the last one in which the mission still existed.
   - No match: a warning.
   - `ContactId == 0`: skipped, with the log line `has no contact (ContactId 0) — skipped, no penalty.`
   - A column that could not be read when the board was snapshotted (for example `ContactId` or `PowerLevelUnscaled`): the expiry is refused with a warning. It is never charged as contactless or as PL 0.
4. **Move on.** The new snapshot replaces the old.

On the first tick of a session it logs one instrument line: log rows, `202` rows, board size, missions with a contact, the `PowerLevelUnscaled` range and the highest log row id.

### Replay and reloads

- Nothing is written to the save to track progress. Reloading to before an expiry and advancing again applies the penalty again.
- A session guard keyed on `turn:title` blocks a second firing on the same tick.
- The guard and the snapshot are dropped on:
  - the load postfix (`ViewModel_GameManagement.LoadGame` / `.LoadGameSlot`);
  - a turn step other than 0 or +1;
  - a complete log read whose highest id is below the high-water mark.
- A reload onto the same or the next turn, with higher log ids and no load postfix firing, is not detected.
- After a detected reload, an expiry on the very next tick is logged as unmatched.

### Mission tiers

Classification is a substring match on `MissionTypeId`: `soloHack` first, then `story`, else `standard`. The patterns come from the file; the code has none built in.

Each tier (`soloHack`, `story`, `standard`) has its own `patterns` list and multiplier in `elapse.json`; `patterns` on `standard` is ignored with a warning. Values and schema defaults: [`config-reference.md`](config-reference.md).

`stress.applyTierMultiplier` also scales the stress `mercCount`, rounding half away from zero.

### Credits channel (`credits`)

```
fine   = round(row.amount × tierMultiplier) + round(balance × percentOfBalance)
charge = min(fine, balance)          when the live balance is readable
```

- **Which row.** `row` is the last `credits.byPowerLevel` row whose `minPowerLevel` ≤ the mission's `PowerLevelUnscaled`. The unscaled level is used because the base reward curve keys on it and it does not move with the difficulty sliders (see [`power-level.md`](power-level.md)).
- **How it is charged.** The balance comes from `SaveManager.GameData.Credits`, and the charge goes through `SpendCredits`. A `false` return after capping is logged as worth reporting.
- **Unreadable balance.** The full fine is requested and a warning is logged once.

### Stress channel (`stress`)

- **Which row.** The same row lookup gives `mercCount` and `stressAmount`.
- **Pool.** The pool is `ReadGameCharacters()`.
  - With `safehouseOnly`, it is filtered by each merc's own `IsStatusSafehouseAliveAndActive()`, read from the cached model when there is one.
  - Fatigue state is not consulted.
  - The Knight is not excluded.
- **Partition.** Mercs are split by their edges to the contact.
  - Any `RelType −1` edge makes a merc negative. Negative beats positive.
  - Otherwise any `+1` edge makes a merc positive.
  - Everyone else is neutral.
  - A tag with no `TagModel` row counts as neutral, with a warning.
- **Where `RelType` comes from.** `DataDb.ReadTags()`, with `GameCharacterTagModel.TagData` as fallback. If neither yields anything, the channel does nothing.
- **Picking.** Positive mercs are taken in seeded order until `mercCount` is reached.
  - With `fallbackToRandom`, a shortfall is filled from neutral mercs.
  - Negative mercs are never taken.
  - An unfilled quota is warned about.
- **Seed.** `splitmix64(turn, missionId or FNV-1a(title)) ^ seedSalt`. The salt keeps these rolls uncorrelated with the fatigue rolls. The same turn and expiry pick the same mercs on every reload.
- **The write.** `after = min(cap, before + stressAmount)`. A merc already at or above `cap` is left unchanged. `cap` must be 1–10. [unverified] Whether the engine ever holds `NegativeTraitValue` above 10.
- **The authority.** The cached `PlayerModel.CharacterModel` is the authority.
  - `before` is read from it, and a disagreement with the row is logged.
  - `NegativeTraitValue` is set on it and it is passed to `UpdateGameCharacter`. The row is the fallback when no cached object exists.
  - The row is re-read afterwards, and a mismatch is warned about.
  - Each write logs `Elapse: WROTE stress: merc … NegativeTraitValue a -> b via cached PlayerModel|row …`.

### Validation and logging

- **Rejected at load.** Any of these rejects the file and installs no hook:
  - an unknown key anywhere;
  - a negative tier multiplier;
  - `percentOfBalance` outside 0.0–1.0;
  - an empty or unsorted table;
  - a first `minPowerLevel` below 1;
  - negative amounts;
  - both channels off.
- **Head line.** Each expiry logs a head line before any write:

  ```
  Elapse: turn 1387 'PIANO RUN' (mission 114, M_PGenTreaty_HeistCPU, EndTurn 1385, <stamp>) contact 15 tier=standard x1 PL 7 (scaled 10)
  ```

- **Detail lines.** The first `logFirst` expiries get one line per channel; later ones get a single joined line.
- **Partial application.** An expiry where one channel applied and the other failed is logged as an error. It is not retried.

Offline checks: `tests/elapse/` (see its README).

## Open questions

- [unverified] Whether the mission-type patterns derived from `MissionModel.csv`
  and `_mission_generated.csv` match the same categories in play.
- [unverified] The Stress threshold at which a limit break becomes possible,
  and its ceiling.
- [unverified] Whether the whole-row `UpdateGameCharacter` write reverts a
  column the engine persists through another path.

## Related

- [`character-fatigue.md`](character-fatigue.md)
- [`power-level.md`](power-level.md)
- [`config-reference.md`](config-reference.md)
