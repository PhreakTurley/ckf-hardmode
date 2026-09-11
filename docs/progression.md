# Progression — the four things a mission awards

The single map of what a completed mission gives you and which lever reaches
each part. **This file owns Team Power Level, contact Power Level and the
`[RewardCurve]` behaviour.** Money and XP are constructed in
[`mission-rewards.md`](mission-rewards.md); enemy difficulty is in
[`power-and-progression.md`](power-and-progression.md); closed routes are in
[`gotchas.md`](gotchas.md); dumping and testing are in
[`workflow.md`](workflow.md).

Every claim below is tagged:
**[measured]** reproduced from a dump or trace · **[fitted]** a model that fits
the data but has not been confirmed · **[closed]** tried, does not work.

## The four axes

| Axis | Where it is stored | The lever | Retroactive? |
|---|---|---|---|
| **Team Power Level** | Nowhere. `SUM(GameMissionScoreModel ⋈ MissionPowerLevelModel)` | `[Progression]` + `ckf.hardmode.teampl.json` | **Always** |
| **Contact Power Level** | Nowhere. Same shape: `SUM(GameContactScoreModel ⋈ ContactPowerLevelModel)` | None built yet — see below | — |
| **Money** | `GameMissionModel.Payment` + per-objective rows | `[RewardCurve]`, `[MissionRewards]`, table edits | No |
| **XP** | `GameMissionModel.Experience` | `[RewardCurve]`, `[MissionRewards]`, difficulty sliders | No |

Two of these are sums over history and two are numbers written once. That
distinction decides everything about how you change them.

---

## 1. Team Power Level

**[measured]** Team PL is not a counter. It is a sum evaluated on demand:

```
GameDb.SumGameMissionScore()
  = SUM over GameMissionScoreModel rows of
    MissionPowerLevelModel.PowerLevelFraction[ActionClass, MissionPowerLevel]
```

Reproduced exactly: 127 saved rows sum to 7.7075, the first 126 to 7.6925 — the
two numbers traced either side of the insert that finished a PL 7 solo hack.

Completing a mission **inserts one row**. That row has six columns and no
fraction among them:

```
Id, MissionTypeId, MissionPowerLevel, ActionClass, GameTurn, MissionSuccessful
```

So the award is decided entirely by which cell the row is filed under.

### `ActionClass` **[measured]**

From 127 completed missions, each classed by the game itself:

| Class | What lands there |
|---|---|
| `0` | `LEGWORK` only. Always PL 0, and there is no class-0 band, so it is worth nothing |
| `1` | Story missions **and** Power Play missions |
| `2` | Treaty contracts — the standard proc-gen board |
| `3` | Solo hacks — every `HackCPU` / `HackFile` / `HackLoot`, whatever generated it |

Class 3 wins over its source: `M_PGenPower_Icarus_M1_HackCPU` is class 3, not 1.

Two rows in the 127 do not fit the naming pattern: `M_SynDebts_StartRaid` is
class **2** though the rest of that story chain is class 1, and
`M_Era_Treaty31_UNABreakup` is class **3** without a `Hack*` name. So the class
is assigned per mission definition, not derived from the id — read it off the
row, do not predict it.

`MissionPowerLevelModel` is 63 rows: three `ActionClass` bands × 21 relative
power levels. The three bands are exactly **×2 apart on all 21 levels**, so
class 1 → 2 → 3 is a clean halving ladder.

### The lever

`override` in `BepInEx/config/ckf.hardmode.teampl.json`, switched on with
`[Progression] Enabled`. It postfixes `SumGameMissionScore`, enumerates the rows
through `GameDb`'s own bulk reader and re-sums from your values. Every past
mission re-prices at once and **any value is reachable**, because nothing has to
be stored in a row.

```jsonc
{ "ActionClass": 3, "MissionPowerLevel": 7, "PowerLevelFraction": 0.33 }
```

**It is always retroactive.** `RetroactiveTable` was removed in 2.12.0 because
retroactive was already this subsystem's only mode. `GainScalar`,
`GainOverride` and the `remap` list went in 2.11.0: all three worked by
rewriting a new row's `(ActionClass, MissionPowerLevel)` join keys as it was
inserted, so the award had to snap to one of the 63 shipped cells or zero — that
is all a row can express. `override` has no such limit, which is why it replaced
them. The Harmony prefix on `InsertGameMissionScore` went with them; nothing
hooks the insert path any more. *(`schema/teampl.schema.json`.)*

Confirmed in play: three override cells predicted 7.7075 → 7.7575, and the save
loaded showing 7.75 (reported from the game, not from a log in this dump).

Before substituting anything it re-sums with the *game's* values and compares
against what the game just returned. Mismatch means something is in that sum it
cannot see, and it shuts itself off rather than writing an unjustified number:

```
Progression: reconciled 7.7075 over 127 row(s).
```

> ⚠️ The retroactive total is what the save then persists —
> `CoreGameDataModel.PowerLevel` mirrors it, so turning the subsystem back off
> leaves that mirror holding a modded figure until something recomputes it. See
> [`gotchas.md`](gotchas.md).

`table` in that file is **reference, not a control**: it is what the mod checks
itself against. Editing it changes no award.

### `[Progression]` keys

`Enabled` (default `true`) is the whole cfg surface; everything else is shaped in
`ckf.hardmode.teampl.json`. `GainScalar`, `GainOverride`, `RetroactiveTable`,
`MinGain` and `LogFirst` have all been removed — older notes and logs still
mention them. [`config-reference.md`](config-reference.md) and
`schema/teampl.schema.json` are the authority on the live surface;
[`gotchas.md`](gotchas.md) lists what went.

### The rule on `MissionPowerLevelModel` **[closed]**

A `ckf.hardmode.rules.json` rule on `MissionPowerLevelModel` changes the
**victory-screen label only**, not the award: the rule engine patches the
`GetRow*Model` materialiser, and `SumGameMissionScore` is a SQL aggregate
evaluated inside SQLite, so no row is built and no postfix ever sees one.
Measured — set to `3.0`, the screen said *"Team gained 3 PL"* and the sum moved
`0.015`. That makes the table the right place to edit the *reported* number and
nothing else; keep it in step with what `ckf.hardmode.teampl.json` awards.
`../mods/CKFHardMode/README.md` still presents that rule as a rate control; this
file is the measured one. Other Team PL routes that do not work are in
[`gotchas.md`](gotchas.md).

---

## 2. Contact Power Level and Trust

### Contact PL looks like the same architecture **[fitted]**

```
Contact PL contribution
  = SUM over that contact's GameContactScoreModel rows of
    ContactPowerLevelModel.PowerLevelFraction[ActionPowerLevel]
```

`GameContactScoreModel` is `Id, ContactId, ActionPowerLevel, ActionClass,
GameTurn` — one row per completed mission, per contact, with `ActionClass` 1 on
every row. `ContactPowerLevelModel` is 21 rows and **carries no `ActionClass`
split** either, so contact awards look single-band: a PL 7 mission would give
its contact `0.06` regardless of type. A played PL 7 CPU spike did award 0.06,
which matches the table — but that is a table lookup agreeing with one report,
**not an observed sum**. Everything above the reported 0.06 is inference by
symmetry with Team PL.

`GameContactModel.BasePowerLevel` is a stored integer alongside this.
**[fitted]** Displayed contact PL looks like `BasePowerLevel + sum`, but one
snapshot cannot separate that from `BasePowerLevel` being recomputed.

**No lever is built for this yet**, and nothing blocks one: **[measured]**
`float SumGameContactScore(long)` is an instance method on
`RPG.Database.GameDb`, decoded from the interop assembly
([`gamedb-write-surface.md`](gamedb-write-surface.md)). Note the return type is
`float`, not the integer the Team PL mirror might lead you to expect. The
retroactive postfix in `Progression.cs` is the template.

### Trust and the payment multiplier

Every mission's payment carries a per-contact factor `1 + P/100`, where P is
dominated by Trust. It is per contact rather than per mission type, it is stable
over time, and it fits `GameContactModel.ContactRep`. The measurements, the fit
and its residuals are in
[`mission-rewards.md`](mission-rewards.md) — that file owns them. **XP carries
no contact term at all.**

### Levers

Plain table edits, no patching: `ContactEffectModel` (`MissionPayMod`,
`GlobalPayMod`, `GlobalTrustMod`, `FavorRate`, `InfluenceMod`) and `EffectModel`
special codes 54/59/60/92 for Face talents. Both are `DataDb`.

**[measured]** `CalculateFavorExchange(favorValue, creditsOffered)` is capped at
3. Swept over favor values 1, 2, 5, 10, 25 and 50 against 0–50,000 credits:
0 credits buys 0 favor, 100 buys 3, and every larger offer also buys 3. The one
exception is favor value 50, which returns 1 at 100 credits and 3 from 250 up.
**Offering more than 250 credits for favor is wasted.**

---

## 3. Money

```
B       = CalculateMissionPayment(PowerLevelUnscaled) × contact
Primary = B × (1 + BonusPayment/100)
Total   = primary + Σ per-objective
```

**[measured]** The base curve is a hardcoded step table that goes flat at PL 10,
it keys on `PowerLevelUnscaled` rather than the scaled level, and the terms sum
— routinely past 100% of B. Everything else about how a payout is built, and
every lever that reaches it, is in
[`mission-rewards.md`](mission-rewards.md).

### `[RewardCurve]` keys

This section replaces the base curve itself, so it is the lever that reaches the
PL 10 flatline. Config lives in `ckf.hardmode.rewardcurve.json`.

| Key | Default | Meaning |
|---|---|---|
| `Enabled` | `true` | |
| `LogEffectiveCurve` | `true` | After patching, call the three functions and log what they return. **This is the verification**; `_reward_curve.csv` can never show a patched curve — see [`gotchas.md`](gotchas.md) |

⚠️ **There is no `[RewardCurve] DryRun`.** Older notes describe one defaulting
to `true`; writing it into the `.cfg` gets you a live run, not a logging-only
one. `LogFirst` is gone from this section too. Set a cell to `-1`, or leave a
column out, to keep the game's own number for that power level.

⚠️ A run made with `[RewardCurve]` live writes its own `BaseCurve` into
`_mission_*.csv`. Divide measurements by the run's base, not the stock curve —
see [`mission-rewards.md`](mission-rewards.md).

---

## 4. XP

```
XP per merc = CalculateMissionExperience(PL) × (1 + BonusExperience/100) × stage
```

**[measured]** Fits exactly on every captured mission, with no contact term and
no crew-size term. XP is **per deployed merc**, and a 1-merc mission also loses
the SimStream share. The stage term, the `ExperienceMod` finding and the
per-type `BonusExperience` lever are in
[`mission-rewards.md`](mission-rewards.md); the global multiplier is the game's
own `ExperienceMultiplier` difficulty slider.

---

## What is still open

Whether contact `BasePowerLevel` is additive or recomputed — two dumps of the
same contact either side of a level gain would settle it. The open questions on
money and XP are tracked in [`mission-rewards.md`](mission-rewards.md).
