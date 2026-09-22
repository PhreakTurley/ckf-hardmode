# Game constants (RuleModel)

Use this page to look up a `RuleModel.RuleId` and its shipped integer `Value`.
Use [`overlays.md`](overlays.md) for CSV syntax and
[`rule-engine.md`](rule-engine.md) for JSON selectors and operations.

The table contains 76 rows. Every row has a readable `ConfigName` and a writable
integer `Value`; the values below are [measured] from the shipped `RuleModel`
dump.

## How the mod edits them

- **The overlay.** The `RuleModel` slice (`[Slices] RuleModel`) gates
  `ckf.hardmode.d/RuleModel.csv`. Its columns are `RuleId,Value,_comment`; a
  blank `Value` leaves that row alone. Which rows it changes is up to the file;
  read it or `LogOutput.log`.
- **Header operators.** The overlay header takes the usual operator suffixes,
  for example `Value*` to multiply (see [`overlays.md`](overlays.md)).
- **Whole groups.** To edit a whole `GroupId`, use a JSON rule in a `.json` file
  in `ckf.hardmode.d` (see [`rule-engine.md`](rule-engine.md)):

```json
{ "model": "RuleModel", "where": { "GroupId": "HEAT" }, "multiply": { "Value": 1.5 } }
```

- **`GroupId` matching** is exact and case-sensitive. The groups are `HEAT`,
  `COMBAT`, `CHARACTER`, `MAP`, `MATRIX`, `ECONOMY`, `CONTACT`, `SAFEHOUSE`
  and `STORY`.
- **Rounding.** `Value` is an integer, so fractional results round to the
  nearest whole number with halves to even (`Accessors.SetNumber`).
- **Negative values.** `multiply` works on them: -50 × 1.3 = -65.
- **COMBAT group.** Its shipped values mix signs and units. Target rows by
  `RuleId` unless one operation is intentionally defined for the whole group.

## COMBAT (17)

| Id | Value | Name |
|---|---|---|
| 3 | -10 | Obstructed Penalty |
| 4 | -25 | Soft Cover Penalty |
| 5 | -50 | Hard Cover Penalty |
| 14 | 50 | Default Crit Dmg |
| 15 | 3 | FA Shots Max |
| 16 | 4 | FA Targets Max |
| 17 | 80 | Glancing Limit |
| 18 | 60 | Precision Burst Limit |
| 19 | 70 | Max Glancing Reduction |
| 20 | 30 | Min Glancing Reduction |
| 22 | 25 | Surprised Bonus |
| 23 | 5 | Glancing Distance Limit |
| 40 | 100 | Max Injury Time |
| 60 | 25 | Smoke Minimum Penalty |
| 61 | 60 | Smoke Maximum Penalty |
| 62 | 5 | Smoke Minimum Penalty Distance |
| 63 | 25 | Smoke Maximum Penalty Distance |

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

## MAP (2)

| Id | Value | Name |
|---|---|---|
| 6 | 40 | AI Sleepy Distance |
| 12 | 30 | AI Skip Turn Distance |

## MATRIX, ECONOMY, CONTACT, SAFEHOUSE

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
| 65 | 40 | Next Vignette Delay for PL 3 |
| 66 | 20 | Next Chatter Delay for PL 3 |
| 67 | 60 | Next Recruit Delay for PL 3 |
| 68 | 20 | Vignette Base Chance for PL 3 |
| 69 | 12 | Chatter Base Chance for PL 3 |
| 70 | 20 | Recruit Base Chance for PL 3 |
| 71 | 2 | Vignette Turn Rate for PL 3 |
| 72 | 5 | Chatter Turn Rate for PL 3 |
| 73 | 2 | Recruit Turn Rate for PL 3 |
| 74 | 50 | Next Proc-Gen Mission Delay for PL 3 |
| 75 | 44 | Proc-Gen Mission Base Chance for PL 3 |
| 76 | 3 | Proc-Gen Mission Turn Rate for PL 3 |

The `ConfigName` values on ids 65–76 mirror ids 28–39 with `for PL 3`
suffixes [measured]. When the game selects the second set has not been observed
[unverified]; do not infer the selection rule from the names alone.

## Validate an edit

Run the rule validator before launch, then read `LogOutput.log` to see which
`RuleModel` rows the enabled files changed. Use `traceRules` only when the normal
summary does not identify the row; reset it afterward. Commands and log paths
are in [`workflow.md`](workflow.md).

## Related

- [`rule-engine.md`](rule-engine.md)
- [`overlays.md`](overlays.md)
- [`gotchas.md`](gotchas.md)
