# Difficulty and enemy Power Level

How hard the enemies are, and how high the mission power level can go.
`[PowerLevel]` is documented **only here**; `[Difficulty]`'s knob list belongs to
[`../mods/CKFHardMode/README.md`](../mods/CKFHardMode/README.md).

**What a mission awards is not here** — see [`progression.md`](progression.md)
for Team PL and [`mission-rewards.md`](mission-rewards.md) for money and XP.
Routes that do not work are in [`gotchas.md`](gotchas.md).

## There are two power levels, and they diverge

`ConfigureProcGenPowerLevels` produces four values from one `TeamPowerLevel`:
`UnscaledMissionPowerLevel` drives **rewards**, `ScaledMissionPowerLevel` drives
**enemies**, and `ScaledMatrixPowerLevel` drives Matrix hosts.
`GameMissionModel` stores the middle two as `PowerLevelUnscaled` and
`PowerLevel`, and they are routinely several levels apart.

**This is the single most important fact for a hard-mode build.** `[PowerLevel]`
raises the scaled level so enemies get harder; the reward side never sees it, so
a crew fighting a scaled PL 12 is paid at unscaled PL 7 rates. Raise the reward
curve instead — see [`mission-rewards.md`](mission-rewards.md) and
[`gotchas.md`](gotchas.md).

---

## `[Difficulty]` — widening the game's own sliders

The game ships a full custom-difficulty system (`WindowCustomizeDifficulty`).
Most settings on `GameDifficultyModel` are paired with writable `Min`/`Max`
clamp properties, and **this section's whole job is to widen those bounds** so
the in-game sliders reach further. You then set difficulty in the game's own
window, under the game's own names.

`SliderRangeMultiplier` (default `3.0`) is the section's only key. The 20
scalar knobs that used to live here were removed in 2.11.0: they were a second
place to set values the game already exposes, and two of them shipped non-`NaN`,
so a fresh install silently doubled enemy HP. Do not reintroduce them.

What the sliders reach, grouped:

| Group | Settings on `GameDifficultyModel` |
|---|---|
| **Combat** | `MonsterHitPointScalar`, `MonsterDamageScalar`, `PowerLevelScalar`, `BasePowerLevelOffset`, `MatrixPowerLevelOffset` |
| **Survivability** | `DeathSaveBase`, `WoundSaveBase`, `ArmorSaveBase`, `NegativeTraitSaveBase` |
| **Detection / heat** | `SecurityTallyPerHeat`, `SecurityTallyMaxPerTurn`, `MatrixTallyMaxPerTurn`, `LegworkDifficultyOffset` |
| **Economy / pacing** | `MissionEconomy`, `ExperienceMultiplier`, `GearCostMultiplier`, `ModuleCostMultiplier`, `MedicalCostMultiplier`, `ServiceCostMultiplier`, `CraftingCostMultiplier` |

`MonsterHitPointScalar` and `MonsterDamageScalar` are the bluntest way to make
every enemy tougher without editing a row. The bound properties are **static**,
so the widening is a one-shot on the type at load, not per row. Per-key
reference: [`../mods/CKFHardMode/README.md`](../mods/CKFHardMode/README.md).

The startup log names what moved. The line's shape is:

```
Difficulty: GameDifficultyModel — N properties, M Min/Max pair(s), widened M by xK.
  PowerLevelScalar [0.75, 1.5] -> [0.25, 4.5]
  BasePowerLevelOffset [-5, 5] -> [-15, 15]
```

`N` and `M` **vary with the game build** — captures in this repository disagree
and neither is dated, so read them off your own log rather than treating any
recorded pair as a target. Only `*PowerLevel*` stems are listed individually.

---

## `[PowerLevel]` — lifting the ceiling of 10

**[measured]** `GameDifficultyModel.CalculatePowerLevel(long powerLevel, bool
isMatrix)` saturates at 10 for every input. It is the clamp itself, not a
passthrough.

`PowerLevelCap.cs` recomputes the value instead of trying to detect saturation:

```
MissionPowerLevel = round( (teamPowerLevel + offset) * scalar )
clamped to [MinCap, MaxCap]
```

> ### ⚠️ Above PL 10 you get sponges, not lethality
>
> **[measured]** Across `MonsterTypeModel`'s 2,427 archetypes, median
> `HitPoints` goes 505 at PL 10 to 1070 at PL 20 — but the weapons do not follow.
> Median `BallisticDamage1` over distinct weapon rows is 255 at PL 10 **and at
> PL 20** (300 at both counted per archetype), and the maximum actually falls,
> 594 → 525: PL 11–20 archetypes reuse weapon rows already in service at PL 10.
> Median `ActionPoints` (40) and `MaxTalentCount` (3) are flat too.
>
> So raising `MaxCap` alone doubles enemy health and changes nothing else, while
> pay stays pinned at the PL 10 flatline. Fights get longer, not harder, and pay
> worse per minute. Pair it with the `MonsterDamageScalar` slider, or a rule like
> `{"model": "WeaponModel", "whereMin": {"WeaponId": 20000},
> "multiply": {"BallisticDamage1": 1.4, "BallisticDamage2": 1.4}}`.

**[measured] There is no per-mission roll.** 101 missions across 13 dump runs,
all at the same team power level, returned the identical
`ScaledMissionPowerLevel` and `ScaledMatrixPowerLevel` every time — mission power
level is a deterministic function of team power level, offset and scalar. A
`MaxCap` well above the result is never reached; the number you get is the
formula's own answer, not the ceiling.

`offset` and `scalar` are read straight off the `__instance` the postfix is
handed — the same `BasePowerLevelOffset` and `PowerLevelScalar` the in-game
sliders write. **There are no duplicate knobs here.** This section supplies only
the ceiling the sliders cannot express.

The whole live key surface is five entries
(`schema/powerlevel.schema.json`):

| Key | Default | Range | Meaning |
|---|---|---|---|
| `Enabled` | `true` | | Recompute mission Power Level so it can exceed the stock ceiling of 10 |
| `MinCap` | `1` | 1–25 | Lower clamp. Stock is 1 |
| `MaxCap` | `20` | 1–25 | Upper clamp. Stock is 10; enemy archetypes exist through 20. Must not be below `MinCap` — the subsystem refuses to install its hook if it is |
| `MatrixMaxCap` | `10` | 0–25 | Separate ceiling for Matrix calls, so hacking can stay at stock while ground missions climb. `0` = use `MaxCap`; the lower of the two wins |
| `LogFirst` | `40` | 0–500 | Calculations to log. The Team PL cross-check prints inside this gate, so `0` silences the only check that mod and game agree |

**Seven keys became consts in 2.12.0**, each because it was a measured fact
about the game rather than a preference. They are still facts, so they are still
documented below — just not adjustable:

| Was a key | Now fixed at | Why |
|---|---|---|
| `DerivedCallMode` | `PassThrough` | `arg0` is pinned to `max(1, Floor(teamPowerLevel))` across three saves — a reward calculation, not a difficulty request. `Recompute` is what turned a reward of 1 into 2 |
| `MatrixOffsetMode` | `Replace` | The Matrix path uses `MatrixPowerLevelOffset` **instead of** the base offset, not on top |
| `OffsetProperty` / `ScalarProperty` / `MatrixOffsetProperty` | `BasePowerLevelOffset` / `PowerLevelScalar` / `MatrixPowerLevelOffset` | `GameDifficultyModel`'s own column names |
| `InstanceTeamProperty` | `teamPowerLevel` | the one Team PL source |
| `TeamPowerLevelOverride` | deleted outright | at its default of 0 the branch reading it was unreachable |

### Where Team Power Level comes from

`GameDifficultyModel` carries its own **`teamPowerLevel`**, on the very instance
the postfix already holds. That is the source, and **there is no fallback.** The
database-discovery machinery (`TeamPowerLevelProperty`, `TeamPowerLevelSources`,
`TeamRowSources`, `TeamModelPriority`, `TeamRowFilter`) went in 2.11.0. If the
instance carries no readable `teamPowerLevel`, or carries one reading 0 — which
a freshly constructed model does before the game fills it in — the subsystem
logs an error and leaves the game's own result alone. It never proceeds on a
default: a default here is not a missing mission difficulty, it is a silently
wrong one.

Team PL is not in a database row either. `GameDataModel` has no `PowerLevel`
column at all; `CoreGameDataModel` has one and it **mirrors** the true Team
Power Level — it read 7.7075 in the same run `SumGameMissionScore()` returned
7.7075 — but it is profile-level, one row per playthrough, so reading it needs
the `ActiveGame = 1` filter. It is a mirror to check against, not a source to
compute from.

The log back-solves the game's own answer as a self-check. This is the one
worked example that carries its own parameters:

```
PowerLevel: team=7.44 (teamPowerLevel) base=1 mtx=0 used=1 scalar=1
            -> raw=8.44 round=8 clamp=8 (ceiling 20)
            (game said 8 for arg0=0, implied team ~7.44 at game scalar 1 offset 1)
```

A line ending in `TEAM PL MISMATCH` means the source is wrong — it fires when
the implied and read values differ by more than half a level. Answers of **10 or
more** report the implied value as `>=` rather than `~`, because the game
clamped them and the implied figure is only a lower bound.

### Two kinds of call

`CalculatePowerLevel` is called on two different paths, distinguished by `arg0`:

- **`arg0 = 0`** — the difficulty path. The level is worked out from
  `teamPowerLevel`. This is the one to rewrite.
- **`arg0 > 0`** — `arg0` is `max(1, Floor(teamPowerLevel))`. A method handed
  the team's own standing and asked for a number is the shape of a **reward**
  calculation, and a hard mode that pays more for being hard is not a hard mode.

The `arg0 > 0` path returns immediately, before reading, scaling or clamping
anything. That is now fixed behaviour rather than a setting.

### There is a second cap this does not lift

The reward curve goes flat at PL 10 and `[PowerLevel]` does not touch it. Lift
the enemy cap without raising rewards and the economy gets strictly worse — see
[`mission-rewards.md`](mission-rewards.md).

---

## `[Progression]` — Team Power Level gain per mission

Documented in full in [`progression.md`](progression.md). Team Power Level is a
sum over the save's mission log, not a number the difficulty path produces, so
nothing in this file reaches it. `[Difficulty]` and `[PowerLevel]` above are
about how hard the *enemies* are; they do not touch what a mission awards.
