# Power level

Use this page to distinguish Team PL, contact PL, unscaled mission PL, and scaled
mission PL, then locate the three Hard Mode entry points that affect them:
`Difficulty`, `PowerLevel`, and `Progression`. Rewards are covered in
[`mission-rewards.md`](mission-rewards.md); settings and defaults belong to
[`config-reference.md`](config-reference.md); closed routes belong to
[`gotchas.md`](gotchas.md).

Evidence tags: [measured] means reproduced from a dump or trace. [fitted] means the model fits but is unconfirmed. [closed] means the route was tried and does not work.

## Shipped power-level paths

### Team PL is a score-row sum

[measured] Team PL is evaluated on demand:

```
GameDb.SumGameMissionScore() -> Single
  = SUM over GameMissionScoreModel rows of
    MissionPowerLevelModel.PowerLevelFraction[ActionClass, MissionPowerLevel]
```

- **Reconciled against a save.** 127 saved rows sum to 7.7075 and the first 126 sum to 7.6925. These are the two values traced on either side of the insert that finished a PL 7 solo hack.
- **One row per mission.** A completed mission inserts one `GameMissionScoreModel` row with the columns `Id, MissionTypeId, MissionPowerLevel, ActionClass, GameTurn, MissionSuccessful`. The row stores no fraction; the award is decided by which cell the row joins to.
- **The table.** `MissionPowerLevelModel` has 63 rows: three `ActionClass` bands × 21 relative power levels (−10..10). On every level each band is exactly half the one before (class 1 → 2 → 3). A row whose `(ActionClass, MissionPowerLevel)` has no cell contributes nothing.
- **No stored copy.** `GameDataModel` has no `PowerLevel` column. `CoreGameDataModel.PowerLevel` mirrors the sum; it read 7.7075 in the same run. That table is profile-level with one row per playthrough, so reading it needs `ActiveGame = 1`.

[measured] `ActionClass`, as the game assigned it across 127 completed missions:

| Class | What lands there |
|---|---|
| 0 | `LEGWORK` only. Always PL 0 and there is no class-0 band, so it is worth nothing |
| 1 | Story missions and Power Play missions |
| 2 | Treaty contracts (the standard proc-gen board) |
| 3 | Solo hacks: every `HackCPU` / `HackFile` / `HackLoot`, whatever generated it (`M_PGenPower_Icarus_M1_HackCPU` is class 3) |

The class belongs to each mission definition and cannot be derived from its id. `M_SynDebts_StartRaid` is class 2 although the rest of its chain is class 1, and `M_Era_Treaty31_UNABreakup` is class 3 without a `Hack*` name.

### Contact PL is fitted, not confirmed

[fitted] Contact PL appears to be built the same way as Team PL:

```
SUM over that contact's GameContactScoreModel rows of
    ContactPowerLevelModel.PowerLevelFraction[ActionPowerLevel]
```

- **The score rows.** `GameContactScoreModel` has the columns `Id, ContactId, ActionPowerLevel, ActionClass, GameTurn`, with `ActionClass` 1 on every row.
- **The table.** `ContactPowerLevelModel` has 21 rows and no `ActionClass` split.
- **One check so far.** A played PL 7 CPU spike awarded its contact 0.06, which matches the table. That is one table lookup agreeing with one report, not an observed sum.
- **Base level.** `GameContactModel.BasePowerLevel` is a stored integer. Whether the displayed contact PL is `BasePowerLevel + sum`, or `BasePowerLevel` is recomputed, is open.
- **Where a hook would go.** [measured] `float SumGameContactScore(long)` is an instance method on `RPG.Database.GameDb` (see [`gamedb-write-surface.md`](gamedb-write-surface.md)). No mod hook exists for it.

### A mission's two power levels

`MissionFactory.ConfigureProcGenPowerLevels` produces a `MissionRequestPowerLevelSet` from the team's standing:

| Value | Drives | Stored on `GameMissionModel` as |
|---|---|---|
| `TeamPowerLevel` | input | — |
| `UnscaledMissionPowerLevel` | rewards (the base curve in [`mission-rewards.md`](mission-rewards.md)) | `PowerLevelUnscaled` |
| `ScaledMissionPowerLevel` | enemies | `PowerLevel` |
| `ScaledMatrixPowerLevel` | Matrix hosts | — |

- **Shifts per mission type.** `AdjustScaledMissionPowerLevel(long)` and `AdjustScaledMatrixPowerLevel(long)` apply them.
- **The two levels diverge.** [measured] Across 101 generated missions, every one was `PowerLevelUnscaled` 7 and `PowerLevel` 12. Raising the scaled level makes enemies harder while pay stays at the unscaled rate.
- **No per-mission roll.** [measured] 101 missions across 13 dump runs at one team PL returned identical `ScaledMissionPowerLevel` and `ScaledMatrixPowerLevel`. Mission PL is a deterministic function of team PL, offset and scalar.
- **Unscaled is the floored team PL.** [measured] `PowerLevelUnscaled` is the floored team PL at generation time, so it does not move when the difficulty sliders change.

### `GameDifficultyModel.CalculatePowerLevel`

- [measured] `CalculatePowerLevel(long powerLevel, bool isMatrix)` saturates at 10 for every input. It is the clamp itself.
- The team's standing is `GameDifficultyModel.teamPowerLevel`, a `Single` property on the same instance. A freshly constructed model reads 0 until the game fills it in.
- The game's own arithmetic is `round((teamPowerLevel + offset) × PowerLevelScalar)`, clamped to 1..10.
  - `offset` is `BasePowerLevelOffset`.
  - On the Matrix path, `MatrixPowerLevelOffset` replaces the base offset rather than adding to it.
- There are two kinds of call, told apart by `arg0`:
  - `arg0 = 0`: the difficulty path. The level is worked out from `teamPowerLevel`.
  - `arg0 > 0`: [measured] `arg0 == max(1, Floor(teamPowerLevel))` in 7 of 7 calls across three saves. The team 6.62 case gave `arg0` 6, which rules out rounding. A method handed the team's own standing looks like a reward calculation. That is inferred from the input, not from the caller.

### Enemies above PL 10

[measured] Across `MonsterTypeModel`'s 2,427 archetypes:

- Median `HitPoints` goes from 505 at PL 10 to 1070 at PL 20.
- Median `BallisticDamage1` over distinct weapon rows is 255 at both PL 10 and PL 20, and the maximum falls from 594 to 525. PL 11–20 archetypes reuse weapon rows already in service at PL 10.
- Median `ActionPoints` (40) and `MaxTalentCount` (3) are flat.

In this shipped-table aggregate, PL 11–20 primarily extends hit points; weapon
damage, Action Points, and talent-count medians do not rise with it. See
[`tuning-enemies.md`](tuning-enemies.md) for the separate enemy-stat surfaces.

### Custom difficulty

`WindowCustomizeDifficulty` edits `GameDifficultyModel`. Most settings are paired with writable static `<Name>Min` / `<Name>Max` bound properties:

| Group | Settings |
|---|---|
| Combat | `MonsterHitPointScalar`, `MonsterDamageScalar`, `PowerLevelScalar`, `BasePowerLevelOffset`, `MatrixPowerLevelOffset` |
| Survivability | `DeathSaveBase`, `WoundSaveBase`, `ArmorSaveBase`, `NegativeTraitSaveBase` |
| Detection / heat | `SecurityTallyPerHeat`, `SecurityTallyMaxPerTurn`, `MatrixTallyMaxPerTurn`, `LegworkDifficultyOffset` |
| Economy / pacing | `MissionEconomy`, `ExperienceMultiplier`, `GearCostMultiplier`, `ModuleCostMultiplier`, `MedicalCostMultiplier`, `ServiceCostMultiplier`, `CraftingCostMultiplier` |

## Hard Mode entry points

### `Difficulty`: wider sliders

- **Settings.** Gate `[Slices] Difficulty`. File `ckf.hardmode.d/difficulty.json`, whose only key is `sliderRangeMultiplier`.
- **What it does.** `Patches.WidenSliders` (`Plugin.cs`) finds every numeric `<Stem>Min` / `<Stem>Max` pair by name and scales each bound by the multiplier `m`, starting from the stock bounds captured once:
  - a positive max is multiplied by `m`;
  - a negative min is multiplied by `m`;
  - a positive min is divided by `m`;
  - a zero bound is left alone.
- **Off switch.** `m ≤ 1` does nothing.
- **When it runs.** Once on the type at load. The reconfigure and materialiser hooks re-run it, and the result is the same each time.
- **Using it.** Difficulty is then set in the game's own window. The mod has no duplicate value knobs.
- **Log.** One summary line, then one line per `*PowerLevel*` stem:

```
Difficulty: GameDifficultyModel — N properties, M Min/Max pair(s), widened M by x3.
  PowerLevelScalar [0.75, 1.5] -> [0.25, 4.5]
```

`N` and `M` depend on the game build; read them from your own log.

### `PowerLevel`: lifting the ceiling of 10

- **Settings.** Gate `[Slices] PowerLevel`. File `ckf.hardmode.d/powerlevel.json`, with keys `minCap`, `maxCap`, `matrixMaxCap` and `logFirst`.
- **The hook.** `PowerLevelCap.After` postfixes every `CalculatePowerLevel` overload. On the difficulty path (`arg0 = 0`) it replaces the result with:

```
round((teamPowerLevel + offset) × scalar), away from zero
clamped to [minCap, ceiling]
ceiling = matrixMaxCap > 0 ? min(maxCap, matrixMaxCap) : maxCap   (Matrix calls)
          maxCap                                                  (everything else)
```

- **Inputs.** `offset` and `scalar` are read from `__instance`, the same values the sliders write. A scalar of 0 is treated as 1. The Matrix offset replaces the base offset (`MatrixOffsetReplaces`).
- **Fixed behaviour.**
  - `arg0 > 0` calls return untouched before anything is read.
  - `teamPowerLevel` has no fallback source. If it cannot be read, the game's result stands and a warning is logged once. If it reads 0, the game's result stands and an error is logged once.
- **Refused configs.**
  - `maxCap < minCap`: nothing is patched.
  - `matrixMaxCap` below `minCap`: only the separate Matrix ceiling is refused; Matrix uses `maxCap`.
- **Log.** The first call logs how `__args[1]` was read as `isMatrix`. The first `logFirst` calculations each log a back-solve of the game's own answer:

```
PowerLevel: team=7.44 (teamPowerLevel) base=1 mtx=0 used=1 scalar=1 -> raw=8.44 round=8 clamp=8 (ceiling 20)  (game said 8 for arg0=0, implied team ~7.44 at game scalar 1 offset 1)
```

  - `TEAM PL MISMATCH` at the end means the implied and read team PL differ by more than 0.5.
  - A game answer of 10 or more prints `>=` because the game clamped it.
  - `logFirst: 0` silences this cross-check.

This does not lift the reward curve, which goes flat at PL 10. See `RewardCurve` in [`mission-rewards.md`](mission-rewards.md).

### `Progression`: Team PL award per mission

- **Settings.** Gate `[Slices] Progression`. File `ckf.hardmode.d/teampl.json` (`schema/teampl.schema.json`), with two grids of `{ActionClass, MissionPowerLevel, PowerLevelFraction}` rows:
  - `table` is the game's own `MissionPowerLevelModel`. It is a reference that the mod reconciles against, and editing it changes no award.
  - `override` holds the replacement cells. A cell not listed keeps its stock value.
- **The hook.** `Progression.AfterSum` postfixes `GameDb.SumGameMissionScore`, enumerates `GameMissionScoreModel` through `GameDb`'s own bulk reader, and returns the sum using `override` over `table`. Every past mission is re-priced at once and any value is reachable.
- **Reconcile first.** Before substituting, it sums with the `table` values and compares against the game's answer.
  - On a match it logs `Progression: reconciled <sum> over <n> row(s). Substituting the override table.`
  - Two consecutive mismatches switch the substitution off for the session (`RETROACTIVE MODE OFF`), leaving the game's own sum.
  - Three consecutive read failures do the same.
  - At the main menu it logs `nothing to reconcile yet`.
- **Cache.** The row histogram is rebuilt when the row count changes or the game's answer stops matching. It is dropped on the `LoadGame` / `LoadGameSlot` postfix.
- **No work to do.** An empty `override` or an empty `table` leaves the sum alone and says so.
- **The substituted total persists.** `CoreGameDataModel.PowerLevel` stores it, so turning the slice off leaves the modded figure there until something recomputes it.
- **Victory-screen label.** [closed] A rule on `MissionPowerLevelModel` changes only the label. The victory screen re-reads the table through the row materialiser, but the award is a SQL aggregate that builds no row. Measured: a rule set to 3.0 showed "Team gained 3 PL" while the sum moved 0.015. The label is therefore generated from the award:
  - `scripts/gen_teampl_labels.py` writes `ckf.hardmode.d/MissionPowerLevelModel.generated.json`, one rule per cell whose merged value differs from stock.
  - That file is gated by `[Slices] Progression` and applied by `ModelRules`, so both slices must be on for award and label to agree (the `linkedEnable` invariant in the schema).
  - Regenerate it after editing `override`; never edit it by hand.
- **Checked in play.** [measured] Three override cells predicted 7.7075 →
  7.7575, and the loaded save showed 7.75.
- **Verifying.** Use CKFDataDump `[Diagnostics] TraceMethods = RPG.Database.GameDb.SumGameMissionScore`. The difference across the insert is the award.

## Open questions

- [unverified] Whether contact `BasePowerLevel` is additive or recomputed. Two
  dumps of one contact on either side of a level gain would settle it.
- [unverified] Whether the `arg0 > 0` path of `CalculatePowerLevel` is a reward
  calculation. Instrumenting a reward site directly would settle it.

## Related

- [`mission-rewards.md`](mission-rewards.md)
- [`tuning-enemies.md`](tuning-enemies.md)
- [`gotchas.md`](gotchas.md)
- [`config-reference.md`](config-reference.md)
