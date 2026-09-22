# Limit break traits

Use this page to identify the shipped temporary-trait pool
(`TraitModel.TraitClass 6`), resolve each trait to its effect, and distinguish
the general and Face classifications. The separate mission-fatigue grant path
is documented in [`character-fatigue.md`](character-fatigue.md).

The table values below are the game's own, [measured] from the dumped
`TraitModel`, `EffectModel`, `MatrixEffectModel` and `_id_constants.csv`. Live
behavior can differ when an overlay edits an effect row.

## Shape of the pool

- 19 rows, `TraitId` 2000–2018. Each row is `TraitLevel 1` and is its own `TraitGroup` (`TraitGroup = TraitId`), so any number can sit on one merc.
- `TraitScore` gives the tier and direction: magnitude 1 is mild, 2 is severe, and the sign marks a buff or a debuff. The four Face rows are the exception: all are `-2`, so the field carries no information for them.
- The duration is not in these rows. Every effect row has `Duration 0`.
  [measured] A captured Stress Limit Break granted a trait for 30 days; see
  [`mission-elapse-penalty.md`](mission-elapse-penalty.md#the-four-character-bars).
- These fields are identical on all 19 rows:
  - on the trait: `TraitLevel 1`, `HealTime 0`, `HealCost 0`, `TagMatch` empty;
  - on the effect: `EffectClearType`, `EffectPurgeType`, `EffectGroupId`, `EffectOwner`, `EffectHealType`, `Heals`, `Duration`, `Instant` and `SpecialMerge` are all 0, `VFX` is empty, and `IconAsset` is `talent_soldier_marker_sights`.

## Pool split by `EffectClassification`

| Value | Rows in all of `EffectModel` | Pool |
|---|---|---|
| 12 `MutationTempTrait` | 13 | General |
| 15 `MutationTempTraitFace` | 4 (effects 10508–10511, nowhere else) | Face only |

- `EffectClassification == 15` identifies the Face set with no false positives.
- The 13 class-12 rows cover the general pool except 2004 and 2005. Those two have no `EffectTypeId`; they point at `MatrixEffectModel` 50000 and 50001 through `MatrixEffectTypeId`, and those two matrix rows are also classification 12.

## General pool

### Debuffs, mild (`TraitScore -1`)

| Name | TraitId | EffectTypeId | Effect |
|---|---|---|---|
| Disgruntled | 2006 | 10504 | `WoundRes -25`, `StressRes -25`, `SpecialCode 28 StressRipples` 50 |
| Checked Out | 2007 | 10505 | `InitBonus -2`, `XpBonus -33` |

### Debuffs, severe (`TraitScore -2`)

| Name | TraitId | EffectTypeId | Effect |
|---|---|---|---|
| Malcontent | 2008 | 10506 | `WoundRes -50`, `StressRes -50`, `SpecialCode 28 StressRipples` 100 |
| Running Empty | 2009 | 10507 | `InitBonus -4`, `XpBonus -50`. The effect's locale name is "Bloodless" |
| Off-Duty | 2014 | 10512 | `SpecialCode 90 BlockMissions` 1, with no stat penalty |
| Cash Grab | 2015 | 10513 | `SpecialCode 92 PayRateIncrease` 6 |
| Seeing Red | 2016 | 10514 | `SpecialCode 91 LeftInSafehouseNoHype` 50 |
| Backseat | 2017 | 10515 | `SpecialCode 89 GoOnMission` 100 |
| Vulnerable | 2018 | 10516 | `MaxHitPoints -50`, `WoundRes -100`, `StressRes -100` |

Code 90 is covered in [`character-fatigue.md`](character-fatigue.md).

### Buffs (`TraitScore +1` / `+2`)

| Name | TraitId | EffectTypeId | Effect |
|---|---|---|---|
| Indomitable | 2000 | 10500 | `WoundRes +50`, `StressRes +50`, `PhysicalArmor +10`, `BallisticArmor +10`, `PureArmor +10` |
| Like Lightning | 2001 | 10501 | `InitBonus +2`, `ActionPoints +10` |
| Quick Study | 2002 | 10502 | `InitBonus +2`, `XpBonus +10` |
| Mastermind | 2003 | 10503 | `InitBonus +2`, `XpBonus +25` |
| Data-Inferno | 2004 | — (matrix 50000) | `ActionPoints +5`, `DamageBoost +25` |
| Data-Fusion | 2005 | — (matrix 50001) | `ActionPoints +20`, `DumpShockRes +25`, `DeckArmor +2` |

## Face pool

These four are Face-only. All four are `TraitScore -2`, so ignore the score. They form two mirrored pairs, with the buff at `n` and the debuff at `n+2`.

| Name | TraitId | EffectTypeId | Effect | Direction |
|---|---|---|---|---|
| High Baller | 2010 | 10508 | `SpecialCode 54 MissionPriceBonus` +25 | buff |
| Leadership Surge | 2011 | 10509 | `AttWill +12` | buff |
| Low Baller | 2012 | 10510 | `SpecialCode 54 MissionPriceBonus` −35 | debuff |
| Leadership Slump | 2013 | 10511 | `AttWill -12` | debuff |

These are the only `TraitClass 6` rows whose effect names do not resolve in the locale. The dump emits `Effect.Name.10508`–`10511` verbatim.

## Reading the sign of a payload

No trait or effect row carries a generic "is this a buff" flag. The sign of a payload tells direction only once the special code's meaning is known:

- `54 MissionPriceBonus` changes the player's payout, so +25 is good.
- `92 PayRateIncrease` raises the merc's own salary, so Cash Grab's +6 is the penalty.

## Limits of the dumped data

- Which traits a given limit break can draw, and the Face gate, are in code.
- Every column of every dumped `raw` and `raw-save` table was scanned for EffectIds 10504–10516 and TraitIds 2000–2018. Outside `TraitModel` and `EffectModel`, the only real reference is `GameCharacterTraitModel` in the save. The other hits are unrelated id spaces, such as `WeaponId 2010`.

So what a trait does can be changed with an `EffectModel` row edit. Which trait a limit break grants cannot be changed through an overlay; that needs a code patch.

## What the mod overlays

`ckf.hardmode.d/EffectModel.limitbreak.csv` is owned by `[Slices]
LimitBreakTraits`; it applies only while that slice and `ModelRules` are on. The
switch is separate from `Fatigue`: one controls effect-row edits, while the
other controls the mission-fatigue grant path. See
[`overlays.md`](overlays.md#files) for overlay ownership and inspect the live
file for its current cells.

The shipped values remain in the tables above. Clearing an overlay cell reverts
that column to the shipped value. The `MoveSpeed` versus `MoveSpeedDebuff`
trade-off is recorded in [`gotchas.md`](gotchas.md).

## Open questions

- [unverified] The runtime meanings of special codes 28, 89, 91 and 92 beyond
  their enum names.

## Related

- [`character-fatigue.md`](character-fatigue.md)
- [`overlays.md`](overlays.md#files)
- [`talent-value-specialcodes.md`](talent-value-specialcodes.md)
