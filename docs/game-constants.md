# Global game constants (RuleModel)

All 76 rows. Every one has a human-readable `ConfigName` and a **writable
`Value`**. Match a single constant with `RuleId`, or a whole category with
`GroupId`. Most of these knobs are exposed nowhere in the UI.

```json
{ "model": "RuleModel", "where": { "RuleId": 13 }, "set": { "Value": 4 } }
{ "model": "RuleModel", "where": { "GroupId": "HEAT" }, "multiply": { "Value": 1.5 } }
```

Re-dump with CKF Data Dump to refresh; the live values are in
`D:\ckf-data-modding\sheets\raw\RuleModel.csv`.

## COMBAT (17)

| Id | Value | Name | Notes |
|---|---|---|---|
| 3 | -10 | Obstructed Penalty | to-hit penalty through obstruction |
| 4 | -25 | Soft Cover Penalty | |
| 5 | -50 | Hard Cover Penalty | **more negative = cover is stronger** |
| 14 | 50 | Default Crit Dmg | |
| 15 | 3 | FA Shots Max | full-auto shots |
| 16 | 4 | FA Targets Max | |
| 17 | 80 | Glancing Limit | |
| 18 | 60 | Precision Burst Limit | |
| 19 | 70 | Max Glancing Reduction | damage shaved off a glancing hit |
| 20 | 30 | Min Glancing Reduction | |
| 22 | 25 | Surprised Bonus | lower it to weaken ambush play |
| 23 | 5 | Glancing Distance Limit | |
| 40 | 100 | Max Injury Time | raise for longer recoveries |
| 60 | 25 | Smoke Minimum Penalty | |
| 61 | 60 | Smoke Maximum Penalty | |
| 62 | 5 | Smoke Minimum Penalty Distance | |
| 63 | 25 | Smoke Maximum Penalty Distance | |

## CHARACTER (15)

| Id | Value | Name |
|---|---|---|
| 1 | 42 | Max Character Level |
| 2 | 2 | Max Character Jobs |
| 7 | 2 | Max Pending Recruits |
| 8 | 14 | Max Characters |
| 9 | 1 | Max Starting Level |
| 11 | 4 | Max Trait Level |
| 13 | 6 | Max Implants |
| 21 | 10 | Boost Character Level |
| 42 | 12 | Attribute Pool in New Game |
| 43 | 6 | Max Attribute New Game |
| 44 | -20 | Character Level Bonus UHUB |
| 45 | -20 | Character Level Bonus Proc-Gen |
| 55 | 33 | Character Level OVER boost |
| 58 | 7 | Knight Max Implants |
| 64 | 80 | Free Respec Window |

## HEAT (6)

| Id | Value | Name |
|---|---|---|
| 24 | 4 | Minimum Heat per Job |
| 25 | 2 | Heat per Sec Level |
| 26 | 18 | Max Heat from Sec Level |
| 41 | 10 | Heat for Pitched Battle |
| 51 | 10 | Heat from Security Devices |
| 59 | 6 | Heat from Hack Only Mission |

The whole group scales cleanly together — a single `GroupId: "HEAT"` rule with
a multiply makes the world react much harder to how loud you are. This is the
single best value-for-effort difficulty lever in the table.

## MAP (2)

| Id | Value | Name |
|---|---|---|
| 6 | 40 | AI Sleepy Distance |
| 12 | 30 | AI Skip Turn Distance |

Beyond these distances the AI dozes or skips its turn.

## MATRIX (1) · ECONOMY (1) · CONTACT (2) · SAFEHOUSE (1)

| Id | Value | Name | Group |
|---|---|---|---|
| 48 | 10 | Max Programs on a Deck | MATRIX |
| 27 | 60 | Loss of Resale Value | ECONOMY |
| 46 | 60 | Contact Limit Break Starting Date | CONTACT |
| 47 | 60 | Contact Exposure Protection Date | CONTACT |
| 10 | 400 | Maximum Turns | SAFEHOUSE |

## STORY (31)

| Id | Value | Name |
|---|---|---|
| 28 | 36 | Next Vignette Delay |
| 29 | 12 | Next Chatter Delay |
| 30 | 56 | Next Recruit Delay |
| 31 | 25 | Vignette Base Chance |
| 32 | 12 | Chatter Base Chance |
| 33 | 25 | Recruit Base Chance |
| 34 | 2 | Vignette Turn Rate |
| 35 | 5 | Chatter Turn Rate |
| 36 | 2 | Recruit Turn Rate |
| 37 | 48 | Next Proc-Gen Mission Delay |
| 38 | 50 | Proc-Gen Mission Base Chance |
| 39 | 4 | Proc-Gen Mission Turn Rate |
| 49 | 15 | Base Head Hunter Chance |
| 50 | 4 | Head Hunter Chance Per Heat |
| 52 | 60 | Next Proc-Gen Legwork Delay |
| 53 | 20 | Proc-Gen Legwork Base Chance |
| 54 | 3 | Proc-Gen Legwork Turn Rate |
| 56 | 42 | First Turn for Any Story to Proc |
| 57 | 60 | First Turn for Proc-Gen Mission |
| 65 | 40 | Next Vignette Delay **for PL 3** |
| 66 | 20 | Next Chatter Delay **for PL 3** |
| 67 | 60 | Next Recruit Delay **for PL 3** |
| 68 | 20 | Vignette Base Chance **for PL 3** |
| 69 | 12 | Chatter Base Chance **for PL 3** |
| 70 | 20 | Recruit Base Chance **for PL 3** |
| 71 | 2 | Vignette Turn Rate **for PL 3** |
| 72 | 5 | Chatter Turn Rate **for PL 3** |
| 73 | 2 | Recruit Turn Rate **for PL 3** |
| 74 | 50 | Next Proc-Gen Mission Delay **for PL 3** |
| 75 | 44 | Proc-Gen Mission Base Chance **for PL 3** |
| 76 | 3 | Proc-Gen Mission Turn Rate **for PL 3** |

**Ids 65–76 mirror 28–39 for power level 3 and above.** Edit both or the change
only holds early — this is the easiest way to retune story and proc-gen pacing
and then watch it silently stop working.

`Base Head Hunter Chance` (49) and `Head Hunter Chance Per Heat` (50) are the
pressure valve: raise them and building heat gets you actively hunted rather
than merely inconvenienced. Pairs well with the HEAT group multiplier.

## Notes on editing

- `multiply` works correctly on negative values, so cover penalties scale as
  you'd expect (-50 × 1.3 = -65).
- `Value` is an integer column, so fractional results round to the nearest whole
  number (halves to even).
- `GroupId` matching is exact and case-sensitive: `"HEAT"`, `"COMBAT"`,
  `"CHARACTER"`, `"MAP"`, `"MATRIX"`, `"ECONOMY"`, `"CONTACT"`,
  `"SAFEHOUSE"`, `"STORY"`.
- Be careful with blanket `GroupId: "COMBAT"` multipliers — the group mixes
  penalties, limits and thresholds, so a single scalar pushes some values in
  helpful directions and others in harmful ones. Target COMBAT by `RuleId`.
