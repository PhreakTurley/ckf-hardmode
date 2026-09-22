# Mission rewards

Use this page to trace mission credits and XP from the shipped base curve through
contact, mission-type, stage, and objective terms. Hard Mode has two separate
entry points: `RewardCurve` replaces curve-return values, while
`MissionRewards` adjusts generated requests and reward rows. Power levels are in
[`power-level.md`](power-level.md); item drops are in [`loot.md`](loot.md).
Settings and defaults belong to [`config-reference.md`](config-reference.md),
and known traps belong to [`gotchas.md`](gotchas.md).

Evidence tags: [measured] means reproduced from a dump or probe. [fitted] means the model fits but is unconfirmed.

## Shipped reward pipeline

### Generation and payout sequence

```
① MissionFactory.ConfigureProcGenPowerLevels(DataLayer)
     team PL + contact (BasePowerLevel, InfluenceScore via CalculateContactPowerLevel)
     → UnscaledMissionPowerLevel (rewards), ScaledMissionPowerLevel (enemies)
② RulesUtil.CalculateMissionPayment(UnscaledPL)     → base credits
   RulesUtil.CalculateMissionExperience(UnscaledPL) → base XP per merc
   RulesUtil.CalculateMissionBonus(UnscaledPL)      → secondary-objective unit
③ mission type: MissionFactory.BuildMissionRequest_<TYPE>(…) or
   BuildProcRequestFromDatabase(dac, key, req) sets BonusPayment / BonusExperience /
   PowerLevelBonus / NoPayment / loot tiers
④ structure: SegmentList → RoomList (a room is a "Stage" in the UI)
⑤ MissionFactory.ProcessMissionRequest(…) → GameMissionModel
     { Payment, Experience, PowerLevel, PowerLevelUnscaled, InfluenceBonus }
⑥ at payout: ContactEffectModel pay mods, Face talent special codes,
   GameDifficultyModel.MissionEconomy / ExperienceMultiplier
⑦ View_MissionRoomVictoryReward
```

### Base curve

[measured, CKFDataDump curve sweep] These are the stock return values, keyed on `PowerLevelUnscaled`:

| PL | Payment | XP/merc | Bonus |
|---|---|---|---|
| 0 | 150 | 100 | 10 |
| 1 | 150 | 100 | 25 |
| 2 | 225 | 120 | 30 |
| 3 | 350 | 145 | 35 |
| 4 | 500 | 190 | 40 |
| 5 | 650 | 235 | 45 |
| 6 | 800 | 280 | 50 |
| 7 | 1000 | 340 | 55 |
| 8 | 1500 | 390 | 60 |
| 9 | 2000 | 440 | 65 |
| 10–25 | 2800 | 500 | 70 |

- **Flat above 10.** The curve is a hardcoded step table and goes flat above PL 10. CKFDataDump's `[Mission] CurveSweepMaxPowerLevel` defaults to 25, so the sweep covers the flat range.
- **Payment vs XP.** Payment grows ×18.7 across the table; XP grows ×5.
- **XP is per merc.** A 1-merc mission also loses the SimStream share (`Mission.Completion.SimStream.TooFew`).
- **The Bonus column.** `CalculateMissionBonus` is the unit that secondary objectives are denominated in.
- **Loot tiers.** The same sweep records loot tiers per PL (Datawarehouse 1→4, Processor 0→2, Financial 1→4, Manufactorium 1→3 across PL 0–10).
- **Matrix loot values.** [measured] `CalcluateMatrixLootFileValue` and `CalculateMatrixLootAccountValue` are identity functions. Matrix file and account credit value does not scale with power level. Do not patch them (see [`gotchas.md`](gotchas.md)).

### Payout composition

A mission's total is a sum of independent terms. `GameMissionModel.Payment` is only the primary payment ("Earn {0} for completing primary objectives").

```
B               = CalculateMissionPayment(PowerLevelUnscaled) × contact
Primary payment = B × (1 + BonusPayment/100)              no stage term
Per objective   = RewardQuantity, in credits, each
Mission total   = primary + Σ per-objective
XP per merc     = CalculateMissionExperience(PL) × (1 + BonusExperience/100) × stage
```

- [measured] The XP formula fits exactly on 101 generated missions: 19 types from 19 paying contacts, all at `PowerLevelUnscaled` 7 and `PowerLevel` 12.
  - XP has no contact term.
  - Payment has no stage term.
  - Neither has a crew-size term: StealFiles and ExposedVIP both have `MaxCharacters = 4` and fit at 1.000.
- The terms routinely sum past 100% of B. Example, `M_PGenTreaty_StealFiles` with a full job payment of 1300:

  ```
  primary  = 130   (B × −90%)
  per file = 391   x3 = 1173
  security = 325
  total    = 1628
  ```

- **Objective rows.** They carry credits (`RewardQuantity` 391, 325), not percentages. The `PctOfFullPayment` column in `_mission_objectives.csv` is computed by the dumper.
- **Are objectives a share of the job?** [fitted] Objective payments land on round percentages of the full job payment: Kill3 pays 398 of 1325 (30.0%), StealFiles pays 391 of 1300 (30.1%) and 325 (25.0%), and HackFile pays 312 of 1562.5 (20.0%). Supporting evidence:
  - `RewardTypes` has both `Payment = 7` and `PaymentStatic = 13`.
  - `Trust5Pay20 = 15` is voiced as "+5% Trust and +20% Job Payment per lead researcher murdered".
  - The victory screen has separate `FullPayment`, `TeamPayment ({0}%)`, `BonusPayment for {0}` and `FailedBonusPayment for {0}` lines.
- **Where the rows live.** Objective rows are attached after `ProcessMissionRequest` returns, since `GameMissionModel.RewardList` is empty at that point. They land in the `GameDb` table `GameMissionRewardModel`, so the dumper's `rewards` probe sees none. Read them from a `GameDb` dump.
- **Check the dump's base.** When measuring from `_mission_*.csv`, divide by that run's `BaseCurve` column. The files append across sessions, and runs made with `RewardCurve` live carry a different base.

### Contact term

Every pay modifier in the game is an additive percentage. For example, `MissionPriceBonus` reads "+{0}% bonus on all Job Payments", and `GlobalPayBuff` / `GlobalPayDebuff` read "+{0}% / {0}% All Payments". So `contact = 1 + P/100`, where P is Trust plus contact trait pay mods plus Face talent pay mods.

- **P belongs to the contact.** [measured]
  - Contact 18 offered nine different types and every one paid ×2.071.
  - `M_PGenTreaty_BlackmailVIP` came from six contacts and paid five different multipliers (1.252, 1.302 twice, 1.327, 1.662, 2.071).
- **P is stable over time.** [measured] Contact 59's `HackCPU` paid ×1.364 in all 25 captures across 13 runs.
- **Bonus and contact multiply.** [measured] Contact 59 gives the same ratio at `BonusPayment +5` and `−20`.
- **P is fractional.** [measured] P ranges from 11.6 to 107.1. Every trait and talent modifier is an integer, so the fractional part comes from elsewhere.
- [fitted] Over 15 contacts, after subtracting each contact's trait `MissionPayMod`:

  ```
  P ≈ 23.52 + 1.296 × GameContactModel.ContactRep + trait MissionPayMod
  ```

  13 of the 15 fit within 1.4 points. The outliers are contact 1 (+5.99) and contact 18 (+2.67). The intercept should be the crew-side constant (Face talents, Persuasion).

### Stage term affects XP

[measured] `M_PGenTreaty_MultiSkyrise` is the only multi-stage type captured so far. It multiplies XP only, by exactly 1.5:

```
XP:      340 × (1 + 110/100) = 714 × 1.5 = 1071        observed 1071
Payment: 1000 × (1 + 50/100) = 1500 × 1.6493 (contact) observed 2474
```

Two contacts pay at the same rate for single-stage and multi-stage missions, which shows payment carries no stage term:

| Contact | Single-stage rate | MultiSkyrise rate |
|---|---|---|
| 17 | EscortVIP ×1.6500 | ×1.6493 |
| 50 | EscortVIP ×1.5625 | ×1.5627 |

Each room also has its own loot (`RoomLootTier1..4`, `MatrixLootRoom`, `MatrixFiles`, `MatrixAccounts`, `MatrixBlueprints`), so the stage count drives loot volume directly.

### Mission-type and source modifiers

Payment can be zeroed by the mission type or by the source, independently.

| Zero-pay case | Mechanism |
|---|---|
| Raid | Worth 0 at baseline; the reward is what is stolen on site |
| Self-generated solo hack (Counter-Intel Pod → Find Hack Mission) | `BonusPayment = −100`, and `ContactId = 0` so no contact term applies |
| Obligation repayment (some story missions) | `NoPayment` |
| `M_PGenTreaty_HackFile` from a contact | `BonusPayment = −100` |

- [measured] `M_PGenTreaty_HackCPU` from a contact pays 1432 at PL 7, so hacking missions are not zero-pay as a class.
- **Observed rows:**

| MissionTypeId | Payment | XP | BonusPayment | BonusExperience | ContactId | MaxChars |
|---|---|---|---|---|---|---|
| `M_PGen_HackingStation_Loot3_HackLoot` | 0 | 85 | −100 | −75 | 0 | 1 |
| `M_PGenTreaty_MultiSkyrise` | 2474 | 1071 | +50 | +110 | 17 | 4 |

- **Where type modifiers come from.** No table holds them.
  - `MissionModel` has 9 handwritten story rows (`PriceMod` / `ExpMod` are percentages, −60 to +100).
  - Proc-gen types come from 75 hardcoded `MissionFactory.BuildMissionRequest_*` overloads, or from `BuildProcRequestFromDatabase` keyed on the `MissionTypeId` string.
  - `BlockModel` holds dialogue plumbing and the mission keys (as `StoryNodeId`, for example `SN_PGenTreaty_StealFiles_Start`), not modifiers.
- **Only `BonusExperience` reaches XP.** [measured] `MissionProcGenRequest.ExperienceMod` and `MissionRequestModel.BonusExperience` are different fields. All 15 captured template keys have `ExperienceMod = −40`, but observed XP follows `BonusExperience` alone. Template `PriceMod` is 0 on all of them.
- **`BonusPayment` varies per instance.** [measured] Contact 59's `HackCPU` shipped `+5`, `−20`, `+30` and `−55` across runs.

### Context modifiers in DataDb

- **`ContactEffectModel`** has 161 rows, with these pay-related columns:
  - `MissionPayMod`: this contact's missions. Whole numbers from −35 to +40, for example Greedy 1–4 at −10/−15/−25/−35 and Generous 1–4 at +15/+20/+30/+40.
  - `GlobalPayMod`: all payments. Values are 3, 4 or 5.
  - `GlobalTrustMod`, `FavorRate`, `InfluenceMod`, `SecondaryInterest`.
  - 16 per-category cost mods.

  A mission with `ContactId = 0` gets none of these. No combination of these columns alone produces the measured contact multipliers.
- **Face talents** (`EffectModel.SpecialCode` / `SpecialValue` / `SpecialMerge`):

| Code | Name | Shipped |
|---|---|---|
| 54 | `MissionPriceBonus` | 10508 (+25), 10510 (−35), 17034 Dealmaker (+10, merge Add) |
| 59 / 60 | `MissionPriceBonusStreetSyndicate` / `…MilsecCorp` | 17037 / 17040 (+25) |
| 55 / 56 | `MissionInfluenceBonus…` | 17035 / 17038 (+1) |
| 57 / 58 | `MissionSecondaryBonus…` | 17036 / 17039 (+1) |
| 70 | `FaceHandlingTeamXP` | No shipped row uses it |
| 92 | `PayRateIncrease` | 10513 Cash Grab (+6) |

- **How sources combine.** `SpecialMerge` is `0 = Max, 1 = Min, 2 = Add`. Only Dealmaker is `Add`; everything else takes the single best source.
- **Trust as a gate.** Trust gates services (`ContactServiceModel.MinimumRep`). `MissionAdvantageModel.TrustMin` is 0 on all 116 rows, so leverages are priced, not gated by Trust.
- **Global sliders.** `GameDifficultyModel.MissionEconomy` and `ExperienceMultiplier` are custom-difficulty sliders (see [`power-level.md`](power-level.md)).

### Favour exchange

[measured] `CalculateFavorExchange(favorValue, creditsOffered)` is capped at 3. It was swept over favour values 1, 2, 5, 10, 25 and 50 against 0–50,000 credits:

- 0 credits buys 0.
- 100 credits buys 3, and every larger offer also buys 3.
- The exception is favour value 50, which returns 1 at 100 credits and 3 from 250 up.

### Secondary objectives

- **Table.** `GameMissionRewardModel` (GameDb) has the columns `MissionId`, `RewardTypeId`, `RewardItemId`, `RewardQuantity`, `RewardDescription`, `MaxAlarmLevel`, `MaxTurns`, `RewardGoalType`, `RewardGoalQuantity`, `IsHidden`, `RequiresGameStateId`, `VictoryEligible` and `GameStateMultiplier`.
- **`RewardTypes`:** `None=0, Blueprint=1, Weapon=2, Armor=3, Account=4, Descriptive=5, Experience=6, Payment=7, Advantage=8, SegmentRoomAdvantage=9, Favor=10, Trust=11, Influence=12, PaymentStatic=13, NBSCubes=14, Trust5Pay20=15, File=16`.
- **Conditions** come from `MissionProcSecondaryObjectivesRequest`: `AllowTurns` / `ExtraTurns`, `AllowKills` / `ExtraKills`, `AllowMaxKills`, `AllowSecurity` / `ExtraSecurity`, `AllowHiddenVIP`.

## Hard Mode entry points

### `RewardCurve` replaces base-curve returns

- **Settings.** Gate `[Slices] RewardCurve`. File `ckf.hardmode.d/rewardcurve.json`, with `logEffectiveCurve` and `curve`, a list of `{PowerLevel, Payment, Experience, Bonus}` rows.
- **The hooks.** `RewardCurve.cs` postfixes `RPG.Combat.RulesUtil.CalculateMissionPayment`, `CalculateMissionExperience` and `CalculateMissionBonus`.
- **Lookup.** The lookup is by exact `PowerLevel`, with no interpolation. A power level not in `curve`, or a cell that is negative or left out, keeps the game's number. This is the only lever that lifts the PL 10 flatline; rows above 10 must be listed.
- **Folding check.** Before patching, it compares the three methods' `NativeMethodInfoPtr_*` values.
  - If two coincide, nothing is patched.
  - A zero pointer cannot be compared. That is the normal case at load, and it is logged as a warning.
- **Checking the result.** `logEffectiveCurve` calls the three functions after patching and logs what they return. Cells that could not be read print `-` and are counted in a warning. Use it rather than `_reward_curve.csv`, whose relation to this patch depends on plugin load order ([`gotchas.md`](gotchas.md)).
- **No work to do.** A file with no overrides patches nothing and says so.

### `MissionRewards` adjusts mission types

- **Settings.** Gate `[Slices] MissionRewards`. File
  `ckf.hardmode.d/missions.json` (`schema/missionrewards.schema.json`), with a
  `missions` list keyed by `MissionTypeId`. Inspect the live file rather than
  relying on a documented entry count.
- **Matching.** The type is matched by exact name, ignoring case. There is no pattern layer.
- **Entry keys:**

| Key | What it adjusts |
|---|---|
| `type` | The `MissionTypeId` |
| `note` | Written by `scripts/refresh_mission_roster.py`; not read by the plugin |
| `BonusPayment`, `BonusExperience`, `PowerLevelBonus` | The request fields, in a prefix on `MissionFactory.ProcessMissionRequest`, so the game does its own arithmetic on the adjusted inputs |
| `ObjectivePayment` | `RewardQuantity` on the mission's own unconditional cash rows (`RewardTypeId` 7 or 13 with no goal, turn limit or alarm ceiling), via a postfix on `GameDb.GetRowGameMissionRewardModel` |
| `SecondaryPayment` | The same, on conditional cash rows: randomly generated secondary objectives |

- **Slot syntax** (`MissionRewards.Adjust.Parse`):

| Slot value | Effect |
|---|---|
| blank | Leave the value alone |
| `=40` or `40` | Set |
| `+25` / `-25` | Add |
| `x1.5` / `*1.5` | Multiply |

  An unparseable value is warned about and ignored. Results round only when the destination column is an integer.
- **Stock values vary.** `BonusPayment` varies per instance (see above), so `+N` and `xN` keep that variation and `=N` flattens it.
- **Reward rows are scaled once.** They are scaled from the first value seen per row id, so repeated reads do not compound. This postfix runs at `Priority.First`, ahead of `ModelRules`.
- **When the reward hook is installed.** The reward-row postfix is installed only when some entry sets `ObjectivePayment` or `SecondaryPayment`.
- **Session state.** The mission-id → type map and the per-row snapshots are cleared on the `LoadGame` / `LoadGameSlot` postfix. If that hook is missing, a warning says to restart the game between saves.
- **Log.** The first 40 generated missions are logged as `MissionRewards: mission <type> pay=… xp=… pl=…`, each stating whether an override applies. Every active override is listed at load.
- **Stock modifiers are only partly known.** A type's stock modifiers become
  observable only when the game generates a mission of that type. An `=N`
  override for an unobserved type is not backed by a shipped-value capture.
  - CKFDataDump's `_mission_generated.csv` and `_mission_builders.csv` append across sessions.
  - `scripts/refresh_mission_roster.py --dump <ckf-dump dir> --json <missions file> [--dry-run]` merges what has been observed. It keeps every edited override slot and writes the reference half (`shipped`, `roomFlags`, `objectivePayments`) to `--reference`.

Team PL is not adjusted here; see [`power-level.md`](power-level.md).

### Table edits

`ContactEffectModel` and `EffectModel` pay modifiers are plain row edits (see [`rule-engine.md`](rule-engine.md)). Changing a `SpecialMerge` mode changes balance more than raising any single value.

## Open questions

| Question | What would settle it |
|---|---|
| The contact multiplier's `ContactRep` coefficient | One contact's payments across a known Trust change with no trait change |
| The form of the stage multiplier (flat, per segment, per room) | Missions with different stage counts; only MultiSkyrise has been seen |
| Whether generated rewards move with power level as the curve predicts | Every captured mission is `PowerLevelUnscaled` 7; needs captures at another team PL |
| The hack-only pricing grid (`ProcGenerateHackOnlyPriceAndTurns`) | Cannot be recovered by sweep (see [`gotchas.md`](gotchas.md)); filter `_mission_generated.csv` to hack missions |

## Related

- [`power-level.md`](power-level.md)
- [`loot.md`](loot.md)
- [`mission-elapse-penalty.md`](mission-elapse-penalty.md)
- [`config-reference.md`](config-reference.md)
