# Mission rewards

How a payout is built, and where to change it. **This file is the canonical
reference for money and XP** — the formulas, the base curve, the contact term
and the stage term all live here. For the map of all four reward axes — Team PL,
contact PL, money and XP — start at [`progression.md`](progression.md). For
anything that does *not* work, see [`gotchas.md`](gotchas.md); for dumping and
in-game testing see [`workflow.md`](workflow.md).

## The pipeline

```
CONTACT                                  TEAM
 BasePowerLevel                           GameDifficultyModel.teamPowerLevel
 InfluenceScore                                    │
        └── CalculateContactPowerLevel() ──┬───────┘
                                           ▼
 ① MissionFactory.ConfigureProcGenPowerLevels(DataLayer)
       → MissionRequestPowerLevelSet { TeamPowerLevel,
             UnscaledMissionPowerLevel ── REWARDS
             ScaledMissionPowerLevel   ── ENEMIES
             ScaledMatrixPowerLevel }
         .AdjustScaledMissionPowerLevel(long)   ── per-type PL shifts
         .AdjustScaledMatrixPowerLevel(long)
                                           ▼
 ② RulesUtil.CalculateMissionPayment(UnscaledPL)     → base credits
    RulesUtil.CalculateMissionExperience(UnscaledPL) → base XP per merc
    RulesUtil.CalculateMissionBonus(UnscaledPL)      → secondary-objective unit
                                           ▼
 ③ MISSION TYPE modifiers
       hardcoded  → MissionFactory.BuildMissionRequest_<TYPE>(…)
       templated  → MissionFactory.BuildProcRequestFromDatabase(dac, key, req)
       sets PriceMod / ExperienceMod / NoPayment / PowerLevelBonus /
            BonusPayment / BonusExperience / loot tiers
                                           ▼
 ④ STRUCTURE multipliers — SegmentList → RoomList. More stages, more reward.
                                           ▼
 ⑤ MissionFactory.ProcessMissionRequest(…) → GameMissionModel
       { Payment, Experience, PowerLevel, PowerLevelUnscaled, InfluenceBonus }
                                           ▼
 ⑥ CONTEXT at payout
       ContactEffectModel.MissionPayMod / GlobalPayMod
       EffectModel.SpecialCode 54 / 59 / 60 / 70  (Face talents)
       GameDifficultyModel.MissionEconomy / ExperienceMultiplier
                                           ▼
 ⑦ View_MissionRoomVictoryReward
```

---

## ① The base curve

| PL | Payment | XP/merc | Bonus | Datawarehouse | Processor | Financial | Manufactorium |
|---|---|---|---|---|---|---|---|
| 0 | 150 | 100 | 10 | 1 | 0 | 1 | 1 |
| 1 | 150 | 100 | 25 | 1 | 0 | 1 | 1 |
| 2 | 225 | 120 | 30 | 1 | 0 | 1 | 1 |
| 3 | 350 | 145 | 35 | 1 | 0 | 1 | 1 |
| 4 | 500 | 190 | 40 | 2 | 0 | 2 | 1 |
| 5 | 650 | 235 | 45 | 2 | 1 | 2 | 1 |
| 6 | 800 | 280 | 50 | 3 | 1 | 3 | 2 |
| 7 | 1000 | 340 | 55 | 3 | 1 | 3 | 2 |
| 8 | 1500 | 390 | 60 | 3 | 1 | 3 | 2 |
| 9 | 2000 | 440 | 65 | 4 | 2 | 4 | 2 |
| 10 | 2800 | 500 | 70 | 4 | 2 | 4 | 3 |
| 11–25 | 2800 | 500 | 70 | 4 | 2 | 4 | 3 |

Payment grows ×18.7 across the range; XP only ×5. Both stop at 10.

PL 0–10 is re-confirmed on every sweep. The 11–25 row needs a sweep run past the
shipped `[Mission] CurveSweepMaxPowerLevel` — see [`workflow.md`](workflow.md).

XP is **per deployed merc**, not per mission. A 1-merc mission also loses the
SimStream share entirely (`Mission.Completion.SimStream.TooFew`).

`CalculateMissionBonus` is the unit secondary objectives are denominated in.

The **Matrix loot valuers are identity functions** — `CalcluateMatrixLootFileValue`
and `CalculateMatrixLootAccountValue` return their base unchanged, over two
independent sweeps with zero deviations. Matrix file and account credit value
does not scale with power level. (Do not patch them; see
[`gotchas.md`](gotchas.md).)

`CalculateFavorExchange` is capped at 3 — documented in
[`progression.md`](progression.md).

---

## How a payout is assembled

**A mission's total is a sum of independent terms, not a division of one pot.**
`GameMissionModel.Payment` is only the first term — the *primary mission
payment* (`MissionDetailInfo.Rewards.Money`: *"Earn {0} for completing primary
objectives."*). Each objective then pays its own term.

```
Base job payment B = CalculateMissionPayment(PowerLevelUnscaled) x contact
Primary payment    = B x (1 + BonusPayment/100)          <- no stage term
Per-objective      = RewardQuantity, in credits          each
Mission total      = primary + sum(per-objective)
```

**The terms routinely sum past 100% of B**, so do not read `BonusPayment` as "the
share you get up front" or treat B as a ceiling. A mission with a small primary
payment and several objective payments can be worth well more than B.

Worked example — the captured `M_PGenTreaty_StealFiles`, full job payment 1300:

```
primary    = 130                        <- what the probe records (B x -90%)
per file   = 391  (30.1% of 1300)  x3  = 1173
security   = 325  (25.0% of 1300)
total                                  = 1628
```

The objective rows carry **credits**, not percentages — `RewardQuantity` is 391
and 325. `PctOfFullPayment` in `_mission_objectives.csv` is computed by the
dumper, not stored by the game. **[fitted]** That the figures land on round
percentages of the full job payment is the reason to believe the game derives
them from one: Kill3 pays 398 of 1325 (30.0%), StealFiles 391 of 1300 (30.1%)
with a 325 (25.0%) security objective, HackFile 312 of 1562.5 (20.0%). The
stored field is absolute; the percentage is the inference.

Evidence that reward payments are percentages, not credit amounts:

- `RewardTypes` carries both `Payment = 7` and `PaymentStatic = 13`. Two types
  are only needed if one is relative and the other absolute.
- `RewardTypes.Trust5Pay20 = 15` is spelled out in the game's own dialogue:
  *"+5% Trust and +20% Job Payment per lead researcher murdered."* A named
  reward type whose name encodes two percentages.
- `Dialog.D_PGen_StealFiles_Intro.9`: *"The three files are scattered
  throughout the zone's lootboxes… our payment increases with each."*
- The victory screen has separate lines for `Mission.Completion.FullPayment`
  ("Full Mission Payment"), `TeamPayment ({0}%)`, `BonusPayment for {0}` and
  `FailedBonusPayment for {0}`.

These rows hang off `GameMissionModel.RewardList`, which is empty when
`ProcessMissionRequest` returns, so the `rewards` probe cannot see them. They are
attached later and land in `GameMissionRewardModel`, a `GameDb` table. Read them
there, not from the probe.

---

## The measured model

**[measured]** 101 generated missions across 13 runs — 19 types, 19 paying
contacts, every one at `PowerLevelUnscaled` 7 and `PowerLevel` 12.

⚠️ **Divide by the run's `BaseCurve`, not the stock curve.** `_mission_*.csv`
append across sessions, and runs made with `[RewardCurve]` live carry a
different base — 570 and 10000 both appear in the current dump. Two phantom
findings (a contact whose rate "drifted", three payouts at "exactly 10×") came
from ignoring that column. Both were this mod's own overrides.

```
XP per merc = CalculateMissionExperience(PL) x (1 + BonusExperience/100) x stage
Payment     = CalculateMissionPayment(PL)    x (1 + BonusPayment/100)    x contact
```

XP fits exactly. `stage` is 1.000 on every single-stage mission and 1.500 on
every MultiSkyrise. There is no contact term on XP, **no stage term on payment**,
and no crew-size term on either leg — StealFiles and ExposedVIP both carry
`MaxCharacters = 4` and both fit at 1.000.

| Contact | Type | BonusPayment | Base × bonus | Payment | `contact` |
|---|---|---|---|---|---|
| 59 | HackCPU | +5 | 1050 | 1432 | 1.3638 |
| 59 | HackCPU | −20 | 800 | 1091 | 1.3638 |
| 59 | HackCPU | −20 | 800 | 1091 | 1.3638 |
| 22 | StealFiles | −90 | 100 | 151 | 1.5100 |
| 22 | StealFiles | −90 | 100 | 151 | 1.5100 |
| 48 | ExposedVIP | +10 | 1100 | 1432 | 1.3018 |
| 17 | MultiSkyrise | +50 | 1500 | 2474 | 1.6493 |

Contact 59 returns the same ratio at `+5` and at `−20`, which proves the bonus
and the contact modifier **compose multiplicatively**. Contact 17's term is
1.6493 — the same 1.65 it charges on its single-stage EscortVIP, which is how we
know payment carries no stage multiplier.

### The contact term is Trust

Every pay modifier in the game states itself as an additive percentage:
`Job.Effects.SpecialCodes.MissionPriceBonus` is *"+{0}% bonus on all Job
Payments"*, `…FacePersuasionDealMaker` is *"+{0}% Mission Payment with
Dealmaker"*, `Att.Persuasion.BonusesDesc` is *"+1% Mission Payment with
Dealmaker, per 1 Persuasion"*, and `Contacts.Traits.GlobalPayBuff` /
`GlobalPayDebuff` are *"+{0}% / {0}% All Payments"*.

So the contact term is `1 + P/100`, where **P = Trust + contact trait pay mods +
Face talent pay mods**, summed before the multiply.

The measured P values across 19 contacts run from 11.6 to 107.1. They are
**fractional** — every trait and talent modifier in the tables is an integer, so
the non-integer part comes from elsewhere.

✅ **The confound is broken. P belongs to the contact.** Across the 101 captured
generations: contact 18 offered **nine different types** and every one paid
×2.071, while `M_PGenTreaty_BlackmailVIP` came from **six different contacts**
and paid five distinct multipliers — 1.252, 1.302 (twice), 1.327, 1.662, 2.071.
**P is also stable over time** — contact 59's `HackCPU` is ×1.364 in all 25
captures across 13 runs, so nothing observed moves a contact's rate mid-campaign.

**[fitted]** A fit over 15 contacts, after subtracting each one's trait
`MissionPayMod` from `ContactEffectModel`:

```
P ≈ 23.52 + 1.296 x GameContactModel.ContactRep + trait MissionPayMod
```

13 of 15 land within 1.4 points; the outliers are contact 1 at +5.99 and contact
18 at +2.67. The intercept is the crew-side constant (Face talents and
Persuasion) and should move if you respec — the cheapest test. **The coefficient
is unconfirmed**; see Open questions.

**XP carries no contact term at all** **[measured]** — it fits without one on
every captured mission, which is what makes the XP leg the clean place to
measure stage multipliers.

---

## ② Type and source — either can zero the payout

Payment can be zeroed by **what the mission is** or by **where it came from**,
and the two are independent.

| Zero-pay case | Kind or source | Mechanism |
|---|---|---|
| Raid | kind | worth 0 at baseline; rewards are what you steal on site |
| Self-generated solo hack (Counter-Intel Pod → *Find Hack Mission*) | source | `BonusPayment = −100`, and `ContactId = 0` so no contact modifier applies |
| Obligation repayment (some story missions) | source | `NoPayment` |
| **Contact offer, any content** | — | **normal**: base curve, then modifiers |

Observed:

| MissionTypeId | Payment | XP | BonusPayment | BonusExperience | ContactId | MaxChars |
|---|---|---|---|---|---|---|
| `M_PGen_HackingStation_Loot3_HackLoot` | 0 | 85 | −100 | −75 | 0 | 1 |
| `M_PGen_HackingStation_Loot2_HackLoot` | 0 | 85 | −100 | −75 | 0 | 1 |
| `M_PGenTreaty_MultiSkyrise` | 2474 | 1071 | +50 | +110 | 17 | 4 |

The two hack rows hit **both** zero-pay routes at once, which makes them a poor
sample. They are not evidence that hacking missions do not pay: measured,
`M_PGenTreaty_HackCPU` from a contact pays 1432 at PL 7, three times over.

But `M_PGenTreaty_HackFile` from a contact carries `BonusPayment = −100` and
pays 0. Zero-pay is a property of the specific type, not of hacking or of
self-generation alone.

### Where the type modifiers live

**Not in a table.** `MissionModel` is 9 handwritten story rows — useful as a
worked example of the units (`PriceMod` and `ExpMod` are percentages, shipped
values run −60 to +100) but not a lever on proc-gen. Two routes instead:

- **Hardcoded** — 75 `MissionFactory.BuildMissionRequest_*` overloads, one per
  type.
- **Database template** — `BuildProcRequestFromDatabase(dac, key, request)`,
  keyed on the `MissionTypeId` string.

  The modifiers are **not** in `BlockModel`. That table is story and dialogue
  blocks; its 30 kept columns are dialogue plumbing (`BlockId`, `GroupId`,
  `StoryNodeId`, `ActorId`, `Dialog`, `PreState*`, `PostState*`, `EventId`,
  `EventType`, `QuipType`, `Weight`), with no `PriceMod` or `ExperienceMod`
  among them. What it does give you is the mission **keys**, as `StoryNodeId`
  values like `SN_PGenTreaty_StealFiles_Start`, and the goal structure —
  StealFiles is three `..._Goal1/2/3` blocks feeding a `GoalCheck` requiring
  `EQL_3_TEMP_Cybersite_StealFile_Done`. `PriceMod` and `ExperienceMod` are read
  off the request object by the probe, not out of a row. Siege, Alpha Strike and
  similar have no builder method and come through here.

**[measured]** `MissionProcGenRequest.ExperienceMod` and
`MissionRequestModel.BonusExperience` are different fields, and **only
`BonusExperience` reaches the result.** All 15 distinct template keys captured so
far carry `ExperienceMod = -40`, including MultiSkyrise whose request shows
`BonusExperience = +110`; observed XP tracks `BonusExperience` alone, with no
`-40` term anywhere. Template `PriceMod` is likewise 0 on all of them while
`BonusPayment` varies, so both request-side bonuses are set outside the
template.

<details>
<summary>The 47 proc-gen mission keys recovered from <code>BlockModel</code>'s story-node ids</summary>

Three of the 47 are written below as `A / B` pairs sharing a prefix, so the
block spells out 44 lines.

```
COMBAT
  M_PGenPower_AlphaStrike_LZ_Battle_ReloadHovers
  M_PGenTreaty_SiegeBattle          M_PGenWardWar_SiegeBattle
  M_PGenTreaty_Battle               M_PGenTreaty_KillBossBattle
  M_PGenTreaty_KillBoss             M_PGenWardWar_HoverBoss_Battle
  M_PGenTreatyRip_Kill3             M_PGenTreaty_WB_Kill3
  M_PGenWardWar_Battle_EscortVIP  (mixed)

HACK
  M_PGen_HackingStation_Loot1_HackLoot   M_PGen_HackingStation_Loot2_HackLoot
  M_PGen_HackingStation_Loot3_HackLoot   M_PGenTreatyRip_HackOnly
  M_PGenTreaty_HackCPU     M_PGenTreatyRip_HackCPU   M_PGenTreaty_HackFile
  M_PGenPower_BroDear_M1_HackCPU / M3_HackCPU
  M_PGenPower_PowerPlayCyberBrain_M1_HackCPU
  M_PGenPower_PowerPlayCyberMatrix_M1_HackCPU
  M_PGenPower_PowerPlayCyberNeural_M1_HackCPU
  M_PGenPower_PowerPlayCyberTank_M1_HackCPU
  M_PGenPower_PowerPlaySimple_M1_HackCPU

HEIST / VIP / OTHER
  M_PGenTreaty_HeistCPU     M_PGenTreaty_HeistFiles   M_PGenTreaty_StealFiles
  M_PGenTreatyRip_StealFiles M_PGenTreaty_MultiSkyrise M_PGenTreaty_Passage
  M_PGenTreaty_AssassinVIP  M_PGenTreatyRip_AssassinVIP
  M_PGenTreaty_EscortVIP    M_PGenTreatyRip_EscortVIP
  M_PGenTreaty_ExposedVIP   M_PGenWardWar_ExposedVIP
  M_PGenTreaty_BlackmailVIP M_PGenTreaty_BlackmailMsg
  M_PGenTreaty_Gang_Scav    M_PGenTreatyRip_Gang_Scav M_PGenTreatyRip_Scav
  M_PGenTreaty_WB_Scav      M_PGenPower_BroDear_M2_LockedExit / M4_LockedExit
  M_PGenPower_PowerPlaySyn_M1_BlackmailMsg / M3_AssassinVIP
  M_PGenPower_SynDebts_M4Ghoul_AssassinVIP
```

Entrenched Target has no key under this pattern; it may be a room or objective
rather than a mission type.
</details>

---

## ③ Structure: stages multiply rewards

A mission is `SegmentList` → each segment holds a `RoomList`. The UI calls a
room a **Stage**.

**[measured]** `M_PGenTreaty_MultiSkyrise` is the only multi-stage type captured
so far, and it multiplies **XP only** by exactly 1.5:

```
XP:      340 × (1 + 110/100) = 714  × 1.5 = 1071   observed 1071
Payment: 1000 × (1 + 50/100) = 1500 × 1.6493      observed 2474   (contact only)
```

Two contacts settle it, single- against multi-stage, at the same payment ratio:

| Contact | Single-stage | Multi-stage |
|---|---|---|
| 17 | EscortVIP ×1.6500 | MultiSkyrise ×1.6493 |
| 50 | EscortVIP ×1.5625 | MultiSkyrise ×1.5627 |

XP over the same four missions goes ×1.0000 → ×1.5000. If payment carried the
stage term, MultiSkyrise would pay 3711. Whether 1.5 is flat per mission, per
segment or per room is open — that needs different stage counts.

Each room also carries its own loot (`RoomLootTier1..4`, `MatrixLootRoom`,
`MatrixFiles`, `MatrixAccounts`, `MatrixBlueprints`), so stage count drives loot
volume directly and separately from any payment multiplier.

---

## ④ Context modifiers — mostly already data-driven

### Contact effects — `ContactEffectModel`, 161 rows

| Column | Effect |
|---|---|
| `MissionPayMod` | % change to this contact's mission payments |
| `GlobalPayMod` | % change to all payments |
| `GlobalTrustMod` | % change to Trust gains |
| `FavorRate`, `InfluenceMod`, `SecondaryInterest` | relationship economy |
| 16 further per-category cost mods | shops and services |

The largest `MissionPayMod` families: Greedy 1–4 at −10/−15/−25/−35, Generous
1–4 at +15/+20/+30/+40, Ops First 1–4 at +15/+20/+25/+35, Skeptical 1–4 at
−10/−10/−15/−20, Addict 1–4 at −5/−7/−10/−15, HI-Priority +25. Range is −35 to
+40, all whole numbers. A mission with `ContactId = 0` gets none of this.

The measured per-contact multipliers — 19 of them, 1.116 to 2.071 — are **not
reachable from this table alone.** `MissionPayMod` ships only whole percentages
from −35 to +40 and `GlobalPayMod` only 3/4/5; no combination produces 1.3638.
See "The contact term is Trust" above.

### Face talents — `EffectModel.SpecialCode` / `SpecialValue` / `SpecialMerge`

| Code | Name | Shipped |
|---|---|---|
| 54 | `MissionPriceBonus` | 10508 (+25), 10510 (−35), 17034 "Dealmaker" (+10, **merge=Add**) |
| 59 / 60 | `MissionPriceBonusStreetSyndicate` / `…MilsecCorp` | 17037 / 17040 (+25) |
| 55 / 56 | `MissionInfluenceBonus…` | 17035 / 17038 (+1) |
| 57 / 58 | `MissionSecondaryBonus…` | 17036 / 17039 (+1) |
| 70 | `FaceHandlingTeamXP` | team-wide mission XP %; named in the enum, no shipped row uses it |
| 92 | `PayRateIncrease` | 10513 "Cash Grab" (+6) |

`SpecialMerge` is `0 = Max, 1 = Min, 2 = Add`. Only Dealmaker is `Add`;
everything else takes the single best source. **Flipping a merge mode is a
bigger balance change than raising any value.**

Trust also gates services (`ContactServiceModel.MinimumRep`), but
`MissionAdvantageModel.TrustMin` is 0 on all 116 rows as shipped, so leverages
are priced (`BaseCost`, `FavorCost`, `ItemCost`, `TokenCost`), not Trust-gated.

### Global economy

`GameDifficultyModel.MissionEconomy` and `ExperienceMultiplier`, set on the
game's own custom-difficulty sliders and widened by `[Difficulty]` — see
[`power-and-progression.md`](power-and-progression.md).

---

## ⑤ Secondary objectives and loot

`GameMissionRewardModel` (GameDb, per save): `MissionId`, `RewardTypeId`,
`RewardItemId`, `RewardQuantity`, `RewardDescription`, `MaxAlarmLevel`,
`MaxTurns`, `RewardGoalType`, `RewardGoalQuantity`, `IsHidden`,
`RequiresGameStateId`, `VictoryEligible`, `GameStateMultiplier`.

`RewardTypes`: `None=0, Blueprint=1, Weapon=2, Armor=3, Account=4,
Descriptive=5, Experience=6, Payment=7, Advantage=8, SegmentRoomAdvantage=9,
Favor=10, Trust=11, Influence=12, PaymentStatic=13, NBSCubes=14, Trust5Pay20=15,
File=16`.

Conditions come from `MissionProcSecondaryObjectivesRequest`: `AllowTurns` /
`ExtraTurns`, `AllowKills` / `ExtraKills`, `AllowMaxKills`, `AllowSecurity` /
`ExtraSecurity`, `AllowHiddenVIP`.

Drops are covered in [`loot.md`](loot.md).

---

## Levers, in the order they are worth doing

1. **Replace the base curve** — `[RewardCurve]`, a postfix on
   `RulesUtil.CalculateMissionPayment` / `…Experience` / `…Bonus`
   (`static long f(long)`, the cleanest patch target in the game). This is where
   you fix the PL 10 flatline; keys in [`progression.md`](progression.md), and
   the two things not to do here in [`gotchas.md`](gotchas.md).
2. **Per-type multipliers** — `[MissionRewards]`, a **prefix** on
   `ProcessMissionRequest` that adjusts `BonusPayment`, `BonusExperience` and
   `PowerLevelBonus` so the game does its own arithmetic on your inputs. On by
   default; `Enabled` is the section's only cfg key and the per-type adjustments
   live in `ckf.hardmode.missions.json`. See "Per-type overrides" below.
3. **Contact and Face modifiers** — plain table edits to `ContactEffectModel`
   and `EffectModel`, no patching. Both are `DataDb`.
4. **Global economy** — the game's own `MissionEconomy` and
   `ExperienceMultiplier` difficulty sliders, widened by `[Difficulty]
   SliderRangeMultiplier`.

Team Power Level is **not** done here — see [`progression.md`](progression.md).

## Per-type overrides

`BepInEx/config/ckf.hardmode.missions.json` carries **one entry per
`MissionTypeId`**, 70 of them, matched exactly — there is no pattern layer, so a
family is reached one type at a time. Each entry has `BonusPayment`,
`BonusExperience` and `PowerLevelBonus` slots taking the `.cfg` adjustment
syntax (`=40`, `+25`, `-25`, `x1.5`; blank leaves the value alone) plus a
reference-only `shipped` block the plugin never reads. Full schema in
[`config-reference.md`](config-reference.md).

| Source of the roster | Types | What is known |
|---|---|---|
| `_mission_generated.csv` | 19 | Measured `BonusPayment` / `BonusExperience` / `PowerLevelBonus` |
| `MissionModel` | 9 | Table-side `PriceMod` / `ExpMod` / `NoPayment` |
| `BlockModel` story-node keys | 47 | Key only — never generated, so modifiers unknown |

42 of the 70 entries have `"shipped": null` — that type has not been generated
in a captured session, so its stock modifiers are unknown. You can still
override them, but `=N` is then a guess and `xN` is not.

**Filling in the nulls.** A type's modifiers only become observable when the game
actually builds a mission of that type, so there is no single launch that
reaches them all — see [`gotchas.md`](gotchas.md). What works is accumulation:
`_mission_generated.csv` and `_mission_builders.csv` **append** across sessions
with a `Run` stamp. Leave the dumper's mission probes on and play, rotating
contacts and factions — each contact offers a narrow slice of the roster, which
is why 101 generations have still only reached 19 types
([`workflow.md`](workflow.md) has the dump loop). Then merge what is known back
into the roster:

```
python scripts/refresh_mission_roster.py ^
    --dump "<game>/BepInEx/ckf-dump" ^
    --json "<game>/BepInEx/config/ckf.hardmode.missions.json"
```

It preserves every override slot you have edited, refuses to write if it would
lose one, and reports how many entries are still null. Add `--dry-run` to
preview. Some entries may never fill: the `M_*` story-chain keys come from
one-off scripted missions, and a few `BlockModel` keys may be rooms or
objectives rather than mission types.

**[measured] `BonusPayment` is not fixed per type.** Contact 59's
`M_PGenTreaty_HackCPU` shipped `+5`, `−20`, `+30` and `−55` across runs, same
type and same contact, so there is a per-instance component on top of the type.
**Prefer `+N` and `xN` over `=N`**, which flattens that variation away.

---

## Open questions

| Question | The run that closes it |
|---|---|
| ~~Which `ActionClass` each mission kind uses~~ | ✅ settled by the 23 Aug `GameDb` dump — 0 legwork, 1 story + Power Play, 2 Treaty contracts, 3 solo hacks. See [`progression.md`](progression.md) |
| ~~Is the payment multiplier per contact or per mission type?~~ | ✅ **per contact** — contact 18 paid ×2.071 across 9 types; BlackmailVIP paid 5 distinct rates from 6 contacts |
| The contact multiplier's coefficient | `P ≈ 23.52 + 1.296 × ContactRep + traits` puts 13 of 15 contacts within 1.4 points, worst residual +5.99 (contact 1). Needs one contact's payments across a known Trust change with no trait change — nothing in 13 runs has moved a contact's rate, so this needs a deliberate Trust gain |
| The stage multiplier's form (flat? per segment? per room?) | Missions with different stage counts. Only MultiSkyrise has been seen. It applies to XP only |
| Whether rewards move with power level at all | Every mission captured so far is `PowerLevelUnscaled` 7. Needs a session at a different team PL |
| ~~`CalculateFavorExchange` shape~~ | ✅ capped at 3 — see [`progression.md`](progression.md) |
| ~~A contact-offered hack mission's pricing~~ | ✅ pays normally — see ② |
| Hack-only pricing grid (`ProcGenerateHackOnlyPriceAndTurns`) | **Not recoverable by sweep** — see [`gotchas.md`](gotchas.md). Recover it from `_mission_generated.csv` by filtering to hack missions instead |

`Req_RewardCount` is 0 and the loot-tier fields are null at generation time, so
the `rewards` probe writes nothing and `_mission_rewards.csv` stays empty. Reward
rows are attached after `ProcessMissionRequest`; read them from
`GameMissionRewardModel` in a `GameDb` dump instead.
