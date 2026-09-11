# Mission elapse penalty

How the shipped mission-elapse penalty works. `mods/CKFHardMode/Elapse.cs`,
CKFHardMode 2.10.2, `[Elapse] Enabled` default true, `[Elapse] LogFirst` 40.

Settings: `docs/config-reference.md` (Elapse section), generated from
`schema/*.schema.json`. Traps: `docs/gotchas.md`. Test procedure:
`docs/workflow.md`. Offline checks: `tests/elapse/`.

When a mission's window closes unplayed, the crew pays for it: credits off the
balance, Stress onto mercs who had a reason to care about that contact. Nothing
else — no contact damage, no heat, no change to how many missions are offered.

Tags: **[measured]** reproduced from a dump or trace · **[fitted]** a model that
fits but is unconfirmed · **[unverified]** never observed.

---

## 1. The trigger

**[measured]** The game records every expiry. `_id_constants.csv`:

```
GameLogTypes,MissionExpire,202,property
```

`GameLogModel.csv` in the reference save carries **20** such rows, turns 715 to
1367, in two text forms:

```
285,202,715,0,0,0,,UNDERBELLY SLICE Window Closed,"We missed the window of
    opportunity to pull off Dusty Diamond's job, the UNDERBELLY SLICE."
323,202,818,0,0,0,,QUANTUM RAID Window Closed,"We missed the window of
    opportunity to finish the job known as the QUANTUM RAID."
```

`ActorId` is blank on all 20 and `Experience`, `Credits` and `Favor` are all 0,
so the row carries a turn and a title and nothing else usable — every input the
formula needs comes from `GameMissionModel` (§2).

Gaps between consecutive expiries: `32, 32, 28, 11, 44, 54, 1, 31, 35, 22, 42,
33, 13, 76, 5, 51, 38, 65, 39`. Median 33, minimum 1 — two expiries can land on
adjacent turns and in principle on the same turn, so nothing assumes one per
tick.

**[measured] Contactless expiries are skipped entirely.** Three of the 20 use the
*"to finish the job known as"* form: QUANTUM RAID (818), QUANTUM STING (1080),
DRIVESPIKE EXIT (1328). The live board identifies the class: `GameMissionModel`
id 115 is `M_PGen_HackingStation_Loot3_HackLoot` with `ContactId = 0`, against id
114 `M_PGenTreaty_HeistCPU` with `ContactId = 15`. A mission with
`ContactId == 0` produces no penalty at all, and the test is the id, not a
substring on the title or type. Hack-typed missions that *do* carry a contact are
penalised at the solo-hack tier (§3).

## 2. The hook and the per-tick algorithm

A postfix on `RPG.Core.SaveManager.ProcessTimelineToNextTurn` (`Public_Void_0`)
reaches the database the way `TraitProbe` proved in Runs 44–46: `__instance`
(SaveManager) → `.Dac` (`RPG.Core.GameManagerBase`) → `DataLayer` → `.GameDBI`
(`RPG.Database.GameDb`). The `GameDb` is used inside the postfix and never
stored, a `[ThreadStatic] bool reentrant` guards the mod's own reads and writes,
and every exception is swallowed (`docs/gotchas.md`). It is installed under its
own Harmony id, `PluginGuid + ".elapse"`, with the `NativeMethodInfoPtr_*`
folding check used in `Fatigue.AlreadyClaimed`.

```
AfterProcessTimeline(__instance):
    if (!active || reentrant) return
    db   = Dac(__instance).DataLayer.GameDBI
    turn = ReadGameData(db).GameTurn

    # A. refresh the board snapshot BEFORE reading the log; on a duplicate
    #    MissionTitle keep the row with the lower EndTurn (§2.3)
    newSnapshot = { row.MissionTitle -> row for row in ReadGameMissions(db) }

    # B. new expiries are 202 rows above the high-water id (§2.1)
    expired = [ r for r in ReadGameLogs(db)
                if r.LogTypeId == 202 and r.Id > highWaterMark ]

    # C. resolve each against the PREVIOUS snapshot
    for r in expired:
        m = previousSnapshot.get(strip(r.LogTitle, " Window Closed"))
        if m is None:        log warning; continue
        if m.ContactId == 0: log skip;    continue
        ApplyCredits(db, m, turn); ApplyStress(db, m, turn)
        previousSnapshot.remove(m.MissionTitle)

    previousSnapshot = newSnapshot
```

The snapshot is the only state the subsystem holds; it lives in memory for the
session and losing it costs at most one missed expiry after a reload. It exists
because the `202` row carries none of `PowerLevelUnscaled`, `ContactId` or
`MissionTypeId`, and **[measured] the `GameMissionModel` row is deleted when the
window closes** — Run48, mission 114 PIANO RUN, gone from `ReadGameMissions()`
between turns 1386 and 1387 with **no flag set on its way out** (`IsActive 0,
IsComplete 0, IsFailed 0`, unchanged from the tick before). There is no retained
row to read and no flag to filter on. One tick of history is exactly enough: at
the tick that sees the `202` row, `previousSnapshot` holds the board as of the
last tick on which the mission was still present.

An unreadable column refuses the expiry rather than reading as 0: a null
`ContactId` or `PowerLevelUnscaled` is refused with a warning, never treated as
contactless or charged at PL 0, which is why `credits.byPowerLevel` and
`stress.byPowerLevel` start at `minPowerLevel >= 1`.

### 2.1 Detection is by log-row id

Detection is by `GameLogModel.Id` against a high-water mark: the first complete
read of a session is the baseline, and on later ticks every `202` row above the
previous tick's highest id is an expiry, whatever turn it carries. The mark
advances only on a complete log read, and the board snapshot is kept whenever the
log read was partial, so a row hidden by a bad read is resolved on the next
complete one. `ForgetSession` resets the mark. A `202` row already present on the
baseline tick and stamped `turn - 1` is warned about; the snapshot is empty on
that tick either way.

The stamp is logged in the head line (`log row 567 stamped 1386`) and any stamp
other than `turn - 1` warns, so the game's own deadline shifts get measured; a
turn filter would drop a shifted row silently and forever.

### 2.2 The turn offset

**[measured]** The game stamps the log row with the turn that is *ending* and the
postfix reads `GameData.GameTurn` after it has advanced, so every row is one
behind the hook. Three independent rows in Run48 carried `turnDelta -1` and none
carried `0` — the `202` expiry (row 567), a trait-expiry row (565) and a
limit-break row (566). This is a property of when the hook runs, not of the
expiry path.

**[measured]** Every `202` row on record is stamped `EndTurn + 1`, and the
penalty is applied inside the same `ProcessTimelineToNextTurn` call that wrote
the row, so the hook sees it at `EndTurn + 2` (Log18):

| Mission | row stamp (`EndTurn + 1`) | hook |
|---|---|---|
| PIANO RUN | 1385 | 1387 |
| EASTWIND RAPTOR | 1409 | 1411 |
| ALLEYWAY CALL | 1421 | 1423 |
| UNRAVELED LEASE | 1429 | 1431 |
| BULL RUSH HANDLER | 1430 | 1432 |

The mod adds no lag of its own. The game shifts mission deadlines by a turn or
more on purpose (a mission due when a merc finishes surgery is pushed back), but
nothing on record shows a row stamped other than `turn - 1`, so the only lag
measured is the game's own `EndTurn + 1`. **[unverified]** what the deadline the
player sees corresponds to.

### 2.3 Duplicate titles and replay

The snapshot is keyed by `MissionTitle`. If two live missions share a title, only
the one with the nearer `EndTurn` is recorded; once its penalty is applied the
title is released and the second becomes recordable on the next tick, and the
collision logs at warning level.

Nothing is written to the save to track progress, so reloading to a turn before
an expiry and advancing again re-applies the penalty. The session double-fire
guard is a `HashSet<string>` keyed on `turn + ":" + missionTitle` — the pair, not
the turn alone, because two missions can expire on one turn. Guard and snapshot
are both dropped on any turn discontinuity (a hook turn that is neither
`prevTurn` nor `prevTurn + 1`) and by the `ViewModel_GameManagement.LoadGame` /
`.LoadGameSlot` postfix, so a reload-and-replay is not blocked by a memory of
writes that no longer exist. A hook turn equal to `prevTurn` counts as the same
tick firing again and the guard holds.

## 3. Mission importance tiers

**[measured]** `GameMissionScoreModel.ActionClass` (1 story/power-play, 2 treaty,
3 solo hack) is written on *completion*, so an expired mission never has one.
Classification is by substring on `MissionTypeId`, the idiom `[MissionRewards]`
uses for `SoloHackTypes` and `PureCombatTypes`; first match wins, unmatched falls
to `standard`.

| Tier | Default patterns | Default multiplier |
|---|---|---|
| `soloHack` | `HackOnly, HackLoot, HackCPU, HackFile` | 0.5 |
| `story` | `M_Era, M_PGenPower, PowerPlay` | 1.5 |
| `standard` | *(everything else)* | 1.0 |

The `story` patterns are **[unverified]**, read off `MissionModel.csv` and
`_mission_generated.csv`. `applyTierMultiplier` extends the tier to the stress
channel by scaling `mercCount`, rounded half away from zero; it ships `false`, so
the tier affects credits only.

## 4. Channel 1 — credits

**[measured] in Runs 49-52, against a live save.** Credits move through
`saveManager.AddCredits(long, string)` and
`saveManager.SpendCredits(long, string) -> bool` (`false` = cannot afford), on
the `__instance` the turn-hook postfix already receives: `RPG.Core.SaveManager`
extends `RPG.Core.GameManagerBase`, which declares both. `gameDb` is
`saveManager.Dac.GameDBI`.

**[measured] Credits cannot be written through `UpdateGameData`.** Run49: the
call returned `true`, a fresh `ReadGameData()` confirmed the new balance, and the
next turn tick showed the original again, with no reload involved.
`GameManagerBase` holds its own live `GameDataModel` as the `GameData` property
and writes that down over the row. Run52 shows the direction of travel: after
`AddCredits(100, ...)` the live object read 3625 while the row still read 3525,
and by the next tick both read 3625. The object is the authority.
**[unverified]** what the `reason` string does.

**The amount** is `table[PowerLevelUnscaled] * tierMultiplier + round(balance *
percentOfBalance)`. The table is indexed by the mission's **`PowerLevelUnscaled`**
— **[measured]** the floored team power level at generation, and what the shipped
reward curve keys on — not `PowerLevel`, which carries the difficulty scalar and
would make the fine move when difficulty changes
([`power-and-progression.md`](power-and-progression.md)). `percentOfBalance`
defaults to `0.0`.

**The charge is capped to the live `GameData.Credits` before `SpendCredits` is
called**, so a 400 fine against a balance of 300 takes 300 and the balance never
goes below zero. A `false` return — the engine disagreeing with its own live
object — is a backstop, logged as worth reporting.

## 5. Channel 2 — stress

The stress channel writes `GameCharacterModel.NegativeTraitValue`, the Stress
bar. `stress.cap` (default 10) **bounds the increase, never the value**: a merc
already at or above the cap is left unchanged and logged as such.
**[unverified]** whether the engine ever holds `NegativeTraitValue` above 10. The
mod feeds the number and does not manage the consequence; what a limit break does
is the engine's, and **[measured]** the threshold is not in `RuleModel`.

### 5.1 Four bars, four columns, and the names do not match

| Player-facing bar | Internal column on `GameCharacterModelBase` | Evidence |
|---|---|---|
| **Stress** | `NegativeTraitValue` | **[measured]**, Run50/51 |
| **Edge** (internally *Hype*) | `PositiveTraitValue`, displayed via `GetAdjustedHype()` | **[fitted]** |
| **Loyalty** | `LoyaltyScore` | **[fitted]** |
| **Discontent** | `StressScore` | **[measured]**, Run49 |
| Credits | `GameDataModel.Credits` | **[measured]** — the row write is clobbered, §4 |

**[measured]** Run49 wrote `8` into Rhino's `StressScore`: his Discontent bar read
8 and his Stress bar did not move. Run50/51 confirmed it the other way — writing
`NegativeTraitValue = 8` moved his Stress bar to 8 with Discontent unchanged.

Corroborating **[measured]** facts: `STEStress` has four label/slider pairs
(`stress, edge, loyalty, disatisfaction`) matching `SetStress(float, float,
float, float)`; `STEContactInfluence` has the same shape with two sliders over
`GameContactModelBase.InfluenceScore` / `InfluenceNegative`, fixing positive →
loyalty and negative → disatisfaction; `MutationType` carries four independent
levers; and `IPlayerDataProvider` exposes only `get_CharacterModel()`, so
`AddHype` / `ReduceStress` / `RollStress` write columns on
`GameCharacterModelBase`. None of the four is a sum of anything else — Stress is
not a total of `ImplantStress` (Midnight, 6, zero implants), and
`Positive`/`NegativeTraitValue` are not sums of `TraitModel.TraitScore` (Panther,
6/5 stored vs 3/1 computed).

### 5.2 The write, and where it lands

**[measured]** All four are `long` columns, all `get/set`, none `const`, and a
write goes through the whole-row `bool UpdateGameCharacter(GameCharacterModel)`.
The write is durable — a `StressScore` change survived a save and a load (Run49)
— but the roster panel reads the engine's cached object, not the row:
`RPG.Core.SaveManager` declares `Dictionary<long, PlayerModel> playerCache`,
`PlayerModel.CharacterModel : GameCharacterModel`, and both
`View_RosterPanel_Info.PopulateStressView` and the engine's own
`PlayerDataManager.RollStress` / `ReduceStress` take a `PlayerModel` — the same
shape as credits in §4.

So the write reads `before` from `playerCache[id].CharacterModel` when the engine
holds one (a disagreement with the row is logged), sets `NegativeTraitValue` on
both objects, and passes the cached object to `UpdateGameCharacter`; the row is
the fallback, and a throw puts the cached object back. Every written merc gets a
`watch` line for six ticks showing row and cache side by side. **[unverified]**
whether the whole-row write reverts any column the engine persists by another
path.

**[measured] Stress is spent by the mechanic it feeds.** In Run50 Rhino's
`NegativeTraitValue` was written to 8 and read 2 two ticks later; the game log row
for that turn says why:

> *"Rhino suffers Trait Vulnerable for 30 days — Due to excessive Stress, Rhino's
> has suffered a constant negative Trait, -50 Hit Points, -100% Stress Res and
> -100% Wound Res, for 30 days."* — `_elapse_logrows.csv`, `ActorId` `PID_16`,
> `GameTurn` 1384

Discontent, by contrast, held at 8 for ten straight turns.
`IsStatusLimitBreakReady()` is **[measured]** not the gate — false for every merc
on every tick across Runs 48-49, including the tick a break fired.
**[unverified]**: the threshold at which a break becomes possible, and the
ceiling; neither is in `RuleModel`.

### 5.3 Selecting the mercs

The roster comes from the zero-arg `ReadGameCharacters()`;
`ReadGameCharactersAvailableForMission` takes a `long` mission id and
**[measured]** the expired mission's row is deleted by the time the penalty
resolves (§2). `stress.safehouseOnly` (default true) then limits the pool to
mercs whose own `GameCharacterModel.IsStatusSafehouseAliveAndActive()` returns
true, evaluated on the cached model when there is one — the engine's own
predicate, not a pool reconstructed from `Status` and `MedicalTurn`. Fatigue
state is not consulted; an Off-Duty merc is eligible.

The pool is partitioned by each merc's edge toward the expired mission's contact:

```
edges(merc, contact) = GameCharacterTagModel rows where
                       CharacterId == merc.Id
                   and ActorId    == "NID_" + contact.Id
sign = TagModel.RelType of the row's TagTypeId    # 1 | -1 | 0

positive = any edge RelType == 1 · negative = any edge RelType == -1 (wins over
positive) · neutral = the rest

take from positive, in seeded random order, until |pick| == n or exhausted
if short and fallbackToRandom: take from neutral the same way
never take from negative, even short of quota
```

**[measured]** `TagModel.RelType` is the polarity column: `1` on 23 verbs, `-1`
on 26, `0` on 12 (the six `DeathTag_*` and six headhunting tags). `TagScore` is
**intensity, not sign** — `RelTag_Lover` and `RelTag_Hates` are both 3 — so
polarity is read from `RelType`, never from `TagScore` or the `TagMatch` rollup.
**[measured]** `RelTag_ExSpouse` is the one row where rollup and polarity
disagree: `RelType = 1` with `TagMatch = RelTag_SexyDislikes`. `RelType` wins; it
does not appear in the reference save.

**[measured]** Relationships are stored as a **stack**, not one row — root
(`RelTag_Likes`), flavour (`RelTag_ProfLikes`), leaf (`RelTag_Trusts`), all
inserted with the same `CreatedTurn`; family edges write four. Every row in a
stack carries the same `RelType`, so any one answers the question. Direction is
**merc → contact only**; the `GameContactTagModel` rows pointing back
(`ActorId == "PID_n"`) are not consulted, and `TagScore` (1–3) on the leaf row is
recorded in the log line but unused.

`RelType` comes from `DataDb.ReadTags()` reached as `SaveManager.Dac.DataDBI` —
**[measured]** `RPG.Saving.DataLayer` declares `DataDBI` beside `GameDBI` — with
`GameCharacterTagModel.TagData` as the fallback (**[unverified]** whether the
bulk reader populates it). A `RelType` table read as all-zero is treated as
unreadable and the stress channel does nothing rather than treat everyone as
neutral.

**[measured] Coverage in the reference save**: 29 merc↔contact pairs — **13
positive, 11 negative, 4 neutral, 1 mixed** — with only **13 of 60 contacts**
carrying a positively-linked merc, reaching **9 of 16** mercs. With
`fallbackToRandom = false` the stress channel therefore fires on roughly a fifth
of expiries and the rest are a pure fine; it defaults to `true`. Log16 found a
positive Midnight → contact 15 edge outside that census, so it is a sample rather
than the full set.

Every roll is seeded, so the same turn and the same expiry pick the same victims
however many times the player reloads:
`seed = splitmix64(GameTurn, missionKey) ^ ElapseSalt`, where `missionKey` is the
snapshot row `Id` if present and `FNV-1a(MissionTitle)` otherwise. The salt is
distinct from `Fatigue`'s so the two subsystems' rolls do not correlate.

## 6. Logging

Every expiry emits one line:

```
Elapse: turn 1385 'PIANO RUN' contact 15 tier=standard PL 7
        credits 800 -> balance 3525 -> 2725
        stress +1 x1 -> [4 Bracket (RelTag_Trusts, score 2, +1)] 2 -> 3
```

Past `LogFirst` only the per-channel breakdown is dropped. The first tick of a
session logs an instrument line (log rows, 202 rows, board size, contacts, PLU
range). Warnings cover a `202` row with no snapshot match, a duplicate
`MissionTitle`, a stress write that reads back unchanged, and an unfilled quota.

## 7. Measurements

**Log16 / Run54, 2026-08-31**, the 1383 save advanced to 1387 with the write
calls stubbed out by hand. All **[measured]**, lines from `Logs/Log16.txt`: the
first tick (4252) read `turn 1383: 564 game-log row(s), 20 of them LogTypeId 202;
board 4 mission(s), 3 with a contact, PowerLevelUnscaled 7-9`, so the reader sees
the whole log and the whole board; PIANO RUN resolved at 4290-4292 as `turn 1387
'PIANO RUN' (mission 114, M_PGenTreaty_HeistCPU, EndTurn 1385) contact 15
tier=standard x1 PL 7 (scaled 10)`, `credits 400 -> would SpendCredits; balance
3525 -> 3125`, `stress +1 x1 -> [2 Midnight (RelTag_Likes, score 0, +1, Status 1)
6 -> would write 7]` — that row's `TagScore` read 0, so intensity is not on the
per-save row for that edge; and `Elapse: a save was loaded` fired twice on one
load (4240-4241), because `LoadGame` and `LoadGameSlot` both fire, so the seam is
real and Fatigue's identical hook rests on the same evidence.

**Log17 / Run55, 2026-08-31 — the first live run.** **[measured]** credits
(4263/4352/4368/4372): `SpendCredits` returned true four times, 400 → 800 → 200
(GRAVITY EXCAVATION, `M_PGenTreaty_HackCPU`, soloHack ×0.5) → 800, live balance
3525 → 1325 in step. **[measured]** stress (4265/4354/4370/4374): four writes,
every `UpdateGameCharacter` returned true and every same-hook read-back matched;
picks were Midnight 6→7, Bubbles 3→4 and Sentry 8→9 (Status 5), Ace 2→3, Tractor
1→2 and Diato Wethers 2→3 (Status 7). David clicked Midnight/Panther/Bubbles
right after 4265 and saw no change: the row write was real and durable but
invisible until the engine re-materialised that merc's `PlayerModel`, which
happened for Midnight before turn 1423 and for nobody else that session — the
finding §5.2's cached-object write answers. **[unverified]** what triggers the
re-materialisation. Sentry and Diato Wethers were picked as neutral fallbacks,
which is what `stress.safehouseOnly` prevents.

**Log18 (2.10.1), 2026-08-31 — the cached route holds.** All **[measured]**: five
expiries (PIANO RUN, EASTWIND RAPTOR — `M_PGenPower_AlphaStrike_BS_
KillBossBattle`, story ×1.5, 600 — ALLEYWAY CALL, UNRAVELED LEASE, BULL RUSH
HANDLER), seven stress writes, every one *via cached PlayerModel* with the row
reading back the same value, and 42 `watch` lines over the six ticks after each
write with row and cache equal throughout (4263-4378) — no `no cached
PlayerModel`, no disagreement, no drift. `Status`, from David: **5 is dead**
(Sparklight, Bracket, Sentry, Gyre), **7 is a side character not on the squad and
not currently selectable** (Diato Wethers), Balthasar's **4** means not
established; `IsStatusSafehouseAliveAndActive()` returned false for all six,
which is the right pool. The turn-offset table in §2.2 comes from this run.

## 8. Out of scope

Not done: temporary traits, contact damage (Trust, Exposure,
`InfluenceNegative`), heat, reducing the number of missions offered, escalation
on repeat expiries (the `escalation` block is a stub and repeats do not
compound), a contactless expiry, an idle clock on
`GameDataModel.LastMissionTurn`, and a stored escalation counter.

Still open: the credits table numbers, the `story`-tier patterns, and whether the
Knight should be eligible for stress — the code does not exclude him.
