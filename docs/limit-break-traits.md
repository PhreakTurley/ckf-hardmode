# Limit break traits — the temporary trait pool

`TraitClass 6` in `TraitModel` is the limit-break temporary trait pool: 19 rows,
`TraitId` 2000–2018, each `TraitLevel 1` and each in its **own `TraitGroup`**
(`TraitGroup` = `TraitId`), so any number of them can sit on one merc at once
with no group collision.

`TraitScore` is the tier and the direction: magnitude 1 = mild, 2 = severe;
sign = buff or debuff. That holds for every row **except** the four Face rows in
§3, where all four are `-2` and the field carries no information.

Grant duration is not in the data. Every effect row has `Duration 0`; the
shipped Stress Limit Break grants for 30 days (120 turns at 4 turns/day). See
[`character-fatigue.md`](character-fatigue.md).

## 1. The split — `EffectClassification`

`EffectClassification` on the joined `EffectModel` row separates the two pools
cleanly, and is the only field that does:

| Value | Rows in all of `EffectModel` | Meaning |
|---|---|---|
| `12 MutationTempTrait` | 13 | the general pool (§2) |
| `15` | **exactly 4** | the Face-exclusive pool (§3) |

`15` appears on effect ids 10508–10511 and **nowhere else in the shipped
`EffectModel`** (1,680 rows scanned). Testing `EffectClassification == 15` is a
zero-false-positive filter for the Face set.

The 13 class-12 rows are the general pool minus 2004/2005, which carry no
`EffectTypeId` at all — they point at `MatrixEffectModel` 50000/50001 through
`MatrixEffectTypeId`, and those two rows are also classification 12.

## 2. General pool — `EffectClassification 12`

### Debuffs, mild (`TraitScore -1`)

| Name | TraitId | EffectTypeId | Effect |
|---|---|---|---|
| Disgruntled | 2006 | 10504 | `WoundRes -25`, `StressRes -25`, `SpecialCode 28 StressRipples` 50 |
| Checked Out | 2007 | 10505 | `InitBonus -2`, `XpBonus -33` |

### Debuffs, severe (`TraitScore -2`)

| Name | TraitId | EffectTypeId | Effect |
|---|---|---|---|
| Malcontent | 2008 | 10506 | `WoundRes -50`, `StressRes -50`, `SpecialCode 28 StressRipples` 100 |
| Running Empty | 2009 | 10507 | `InitBonus -4`, `XpBonus -50` |
| Off-Duty | 2014 | 10512 | `SpecialCode 90 BlockMissions` 1 — no stat penalty at all |
| Cash Grab | 2015 | 10513 | `SpecialCode 92 PayRateIncrease` 6 |
| Seeing Red | 2016 | 10514 | `SpecialCode 91 LeftInSafehouseNoHype` 50 |
| Backseat | 2017 | 10515 | `SpecialCode 89 GoOnMission` 100 |
| Vulnerable | 2018 | 10516 | `MaxHitPoints -50`, `WoundRes -100`, `StressRes -100` |

2009's effect name in locale is **"Bloodless"**, not "Running Empty".

Beyond the enum names above, the behaviour of codes 28, 89, 91 and 92 is
**[unverified]**. Only `90 BlockMissions` has been observed — it is the whole of
Off-Duty's content.

### Buffs (`TraitScore +1` / `+2`)

| Name | TraitId | EffectTypeId | Effect |
|---|---|---|---|
| Indomitable | 2000 | 10500 | `WoundRes +50`, `StressRes +50`, `PhysicalArmor +10`, `BallisticArmor +10`, `PureArmor +10` |
| Like Lightning | 2001 | 10501 | `InitBonus +2`, `ActionPoints +10` |
| Quick Study | 2002 | 10502 | `InitBonus +2`, `XpBonus +10` |
| Mastermind | 2003 | 10503 | `InitBonus +2`, `XpBonus +25` |
| Data-Inferno | 2004 | — (matrix 50000) | `ActionPoints +5`, `DamageBoost +25` |
| Data-Fusion | 2005 | — (matrix 50001) | `ActionPoints +20`, `DumpShockRes +25`, `DeckArmor +2` |

## 3. Face pool — `EffectClassification 15`

Face-exclusive. All four are `TraitScore -2`; **ignore the score here.** The set
is two mirrored pairs on the same field, buff at `n`, debuff at `n+2`:

| Name | TraitId | EffectTypeId | Effect | Direction |
|---|---|---|---|---|
| High Baller | 2010 | 10508 | `SpecialCode 54 MissionPriceBonus` **+25** | buff |
| Leadership Surge | 2011 | 10509 | `AttWill +12` | buff |
| Low Baller | 2012 | 10510 | `SpecialCode 54 MissionPriceBonus` **−35** | debuff |
| Leadership Slump | 2013 | 10511 | `AttWill -12` | debuff |

These four are also the only `TraitClass 6` rows whose effect names do not
resolve in locale — the dump emits `Effect.Name.10508`–`10511` verbatim.

## 4. Reading payload sign

Sign of the payload tells you buff or debuff **only once you know what the
`SpecialCode` does**, and only reliably within a mirrored pair:

- `54 MissionPriceBonus` modifies the mission's payout to the player, so
  High Baller's **+25 is good** and Low Baller's **−35 is bad**.
- `92 PayRateIncrease` raises the merc's own salary, so Cash Grab's **+6 is the
  penalty** — a debuff carrying a positive number.

There is no generic "is this a buff" flag anywhere in the trait or effect rows.

## 5. What is *not* in the data

Which traits a given limit break can draw, and the Face gate on §3, live in code.
Every column of all 62 `raw` and 64 `raw-save` tables was scanned for exact-value
references to EffectIds 10504–10516 and TraitIds 2000–2018 used as trait or
effect references. Outside `TraitModel` and `EffectModel` there are none — every
apparent hit is an unrelated id namespace (`WeaponId 2010`, `MatrixFileId 2010`,
`BlockModel.Id 2010`, …). The single genuine reference is
`GameCharacterTraitModel` in the save, holding granted rows (2006 and 2007 in the
reference save).

Consequence for modding: a trait pool cannot be re-pointed through an overlay.
Changing *what a trait does* is a row edit on `EffectModel`; changing *which
trait a break grants* needs a patch.

## Uniform fields

Across all 19 rows, these carry no information — every row is identical:
`TraitLevel 1`, `HealTime 0`, `HealCost 0`, `TagMatch` empty, and on the effect
row `EffectClearType`, `EffectPurgeType`, `EffectGroupId`, `EffectOwner`,
`EffectHealType`, `Heals`, `Duration`, `Instant`, `SpecialMerge` all `0`, `VFX`
empty, `IconAsset` always `talent_soldier_marker_sights`.

Source: `sheets/raw/TraitModel.csv`, `sheets/raw/EffectModel.csv`,
`sheets/raw/MatrixEffectModel.csv`, `sheets/raw/_id_constants.csv`
(dump 26-9-12).
