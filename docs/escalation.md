# Security escalation and Sec AI decks

Use this page to trace Security Tally into Security Level, deck filtering, and
card effects. Reinforcement cards and candidate spawn pools are documented
separately in [`reinforcements.md`](reinforcements.md).

Terms are the game's own, from `MissionAdvantageModel.AdvantageRule`: **Sec
Tally** (yellow marks = created this turn, blue marks = committed by earlier
turns), **Security Level**, **Escalation** [measured].

## Turn sequence

The game prints the whole thing to the Unity log (off by default — see
[`gotchas.md`](gotchas.md), `WriteUnityLog`). One block per turn:

```
 [-] Alarm Reduced by 0
====== MONSTER EVENT LIST ====
[+] Increased security Tally by 3 for Monster Event 4 from Monster Nel (MK HeavyLift)
====== SECURITY EVENT LIST ====
[+] Increased security Tally by 1 for Security Event 7 from Security Event List
====== SECURITY ESCALATION CHECK===
[+] Added Tally Per Turn +10
[?] Old Sec Level 12 VS. New Sec Level 13
[C] Read 11 Security Deck Cards
[C] After Filter, remaining 6 Security Deck Cards
```

`[C]` lines appear only when the level rose. **One card per turn, not one per
level**: turns that jumped two levels (13→15, 3→5, 6→8) still printed a single
Read/After Filter pair [measured, `Logs/PlayedLogA.txt`, `Logs/Run71.log`].

## Tally

`Added Tally Per Turn` = the sum of the `[+]` lines **plus a per-turn base**.
The base was constant inside each mission and differed between them: **+4**
across 7 turns of `PlayedLogA.txt`, **+2** across 6 turns of `Run71.log`
[measured]. `GameMissionRoomModel.AlarmLevelPerTurn` is 1–3 across the four
rooms in the save dump, which is the shape of that base [fitted]; the two
captures do not pin it, because an `IncreaseTallyPerTurn` card drawn earlier
would also raise it.

Event costs seen in those two captures [measured]. Ids decode against
`RPG.Core.Constants.MonsterAI.EventTypes` and
`RPG.Core.Constants.SecurityAI.EventTypes`, 1-based in declaration order
[fitted — the ordering reproduces every observed cost sensibly, but the
literals are const ints the interop assembly does not carry]:

| Monster event | Id | Tally |
|---|--:|--:|
| PlayerSpotted | 1 | 2 |
| GunShotNoiseDetected | 3 | 2 |
| BodyDiscovered | 4 | 3 |
| SomethingSpotted | 6 | 2 |
| BodyDiscoveredPrevoiuslyKnown | 9 | 0 |
| HuntTarget | 10 | 0 |
| HuntMove | 16 | 0 |

| Security event | Id | Tally |
|---|--:|--:|
| NoiseDetected | 3 | 1 |
| AgentMissing | 7 | 1 |
| BioScaneField | 10 | 1 |

The cost tables themselves are `MonsterAI.EventAlarmCosts` and
`SecurityAI.SecurityEventAlarmCosts` (11 and 12 members); their values are not
readable from the interop assembly.

## Security Level from cumulative tally

**Level = floor(cumulative tally ÷ 10).** Divisor 10 is the only value in 1–30
consistent with both captures (13 turns, levels 0→8 and 12→19); the two
captures independently pin the running totals to 82–85 and exactly 190
[measured]. `GameMissionRoomModel.AlarmResponseRate` is 10 on every row of the
save dump, and `MissionAdvantageModel` calls one Escalation's worth of tally
"one entire Escalation (blue marks)" that "reduces the current Security Level
by 1" [measured]. The level can gain 2 in a turn.

[measured] Security Level reached 19 in `PlayedLogA.txt`.
`GameMissionRoomModel.MaxAlarmLevel` is 0 on every dumped row; the captures do
not establish an upper runtime cap.

## Gate 1: deck-row filtering

`DataDb.ReadSecurityDeckCards` returns the room's deck already filtered by the
row's own columns. Against the six reads in `Run71.log` the gate is exactly:

```
SecurityDeckId = room deck
MinAlarmLevel  <= new level
MaxAlarmLevel  = 0 or >= new level
MinRoomTurn    <= room turn
MaxRoomTurn    = 0 or >= room turn      (inert: 0 on all 81 rows)
MinPowerLevel  <= mission PL            (inert: 0 on all 81 rows)
```

That model reproduces 4, 8, 8, 10, 11, 11 cards at levels 1, 2, 3, 5, 6, 8 with
room turns 1–6, and deck 2 / turn-offset 1 is the **only** (deck, offset) pair in
the whole table that fits [measured]. It also reproduces `PlayedLogA.txt`'s
constant 11 at levels 13–19. Note the gate reads the **new** level, so the level
gained this turn is the one that decides which cards are on the table.

## Gate 2: runtime-state filtering

`After Filter, remaining N` drops more cards. Three columns feed it:

- **`PreReq`** — a world-state check from `SecurityAI.CardPreReqs`
  (`SleepingProxMines`, `TurretsReady`, `BodyTimersActive`, …). No sleeping
  mines in the room, no mine card.
- **`ExclusiveReq`** — 1 on exactly the 16 reinforcement cards. The enum has one
  member, `NoEnemiesAlive`. Which way the gate points is [unverified].
- **`PreCheck`** — a state token: `NOT_TEMP_SecAI_Rein`,
  `HAS_TEMP_SecAI_ProxMineMinor`. `PostRun` writes the token
  (`ADD_TEMP_SecAI_Rein`), `PostCheck` clears it (`DEL_TEMP_SecAI_Rein`). The
  `TEMP_` prefix and the `StateName`/`StateValue` shape of `GameStateModel` put
  these in the save's state table for the duration of the mission [fitted].

The token pairs are what make some cards escalate in stages: card 104 fires
`ProxMinesWakeup ×3` and sets `ProxMineMinor`, after which 104 is locked out and
card 110 — gated on `HAS_ProxMineMinor` — becomes the mine card.

Observed filter survivors were 1, 5, 4, 6, 4, 5 of 4–11 read (Run71) and
6, 5, 2, 4, 5 of 11 (PlayedLogA) [measured].

## Selection

`CardWeight` ranges from 1–12, with 54 of 81 cards at 1. [unverified] Whether
selection is a weighted roll among survivors; no captured line names the drawn
card. What happens with zero survivors is also unlogged.

`CardTypeId` is 1 and `FilterTypeId`, `Cooldown`, `MaxRoomTurn`, `MinPowerLevel`
are 0 on all 81 rows — inert in the shipped data.

## Card-event dispatch

`CardEventId` → `RPG.Core.Constants.SecurityAI.CardEventIds`, 1-based in
declaration order [fitted, same caveat as the event ids — but every id present in
the table lands on an event whose name matches the card's own text]:

| Id | Event | `CardEventQty` is |
|--:|---|---|
| 1 | SpawnRandomMonster | unused (0) |
| 2 | SpawnRandomMonsterDouble | unused (0) |
| 3 | SpawnCloseMonster | unused (0) |
| 4 | SecurityDeviceReboot | devices rebooted (4–6) |
| 5 | SecurityDeviceMoreLethal | devices switched to lethal (3–6) |
| 6 | IncreaseMatrixHostSecurity | 2 |
| 7 | ApplyUniversalGuardBuff | unused — carries `CardEffectId` |
| 9 | ApplyUniversalPlayerDebuff | unused — carries `CardEffectId` |
| 11 | IncreaseTallyPerTurn | tally added per turn from now on (1–2) |
| 12 | SecurityDeviceWakeup | devices woken (3) |
| 13 | ProxMinesWakeup | mines armed (1–10) |
| 14 | BodyTimerReduce | see below |
| 16 | TurretSpawn | turrets (1–2) |
| 17 | SpawnRandomMonsterDoubleClose | unused (0) |
| 18 | ShockFieldWakeup | fields armed (2–4) |

Ids 8 (`ApplyUniversalDroneBuff`), 10 (`ApplyCyberKnightDebuff`) and 15
(`TurretActivate`) exist in the enum and are used by no shipped card.

`BodyTimerReduce` is the one place the name and the quantity disagree: card 109
is `Qty=3` titled "up to 1 Turn", card 405 is `Qty=1` titled "up to 1 Turn",
card 812 is `Qty=3` titled "up to 3 Turns". Either `Qty` is bodies and the turn
figure is baked into the string, or one of the rows is wrong. Not resolved.

## Five effect cards

Buff and debuff cards carry `CardEffectId` → `EffectModel`, always
`CardEffectDuration = 2` turns [measured]:

| Effect | Name | Does | Applied to |
|--:|---|---|---|
| 65001 | Marked Targets | `CritVulnerable +15` | the player team (`ApplyUniversalPlayerDebuff`) |
| 65002 | Armor Piercing | `PhysicalArmor -10`, `BallisticArmor -10` | the player team |
| 65003 | Nausea Field | `MoveSpeedDebuff -15`, `InitBonus -8` | the player team |
| 65004 | Forced March | `MovePoints +20` | all guards (`ApplyUniversalGuardBuff`) |
| 65005 | Motivation Field | `MoveSpeed +20`, `MovePoints +20` | all guards |

Card 403 is titled "Debuffed AP / MP" and points at 65003, which touches neither
AP nor MP.

## Deck assignment

`RPG.Core.Constants.SecurityAI.SecurityDecks`, ids 0-based in declaration order
[fitted; the eight ids used by cards all land on a named deck, and the deck-2
fit above confirms the *index*, not the name]: 0 None, 1 SigmaFive, 2 SigmaSeven,
3 SigmaNine, 4 SigmaTech, 5 StreetGangSecurity, 6 StoryPitchedBattle,
7 HackingOnly, 8 DemoDeck, 9 SyndicateSecurity, 10 StoryLiveWireNegotiation,
11 SigmaBlack.

Four of the twelve carry no cards: 0 None, 6 StoryPitchedBattle, 7 HackingOnly,
10 StoryLiveWireNegotiation. `RoomFlagTypes` names five
security systems (`SecuritySystemSigma5` 600 … `SecuritySystemGang` 604).

A room's deck: `MissionModel.SecurityDeckId`, overridden by
`MissionRoomModel.SecurityDeckOverride`, landing on
`GameMissionRoomModel.SecurityDeckId`. `MissionProcGenRequest.SecurityDeckId` and
`MissionRoomProcGenRequest.SecurityDeckOverride` carry it through procgen.

## Player counterplay

`MissionAdvantageModel`, `AdvantageActionIds` = `TallyPotential` (yellow),
`TallyCommitted` (blue), `TallyEscalation`:

| Advantage | Rule text |
|---|---|
| Blip | erases up to 4 potential tally this turn |
| SensorNet DDOS | erases up to 5 potential tally this turn |
| Misdirection | erases up to 4 committed tally |
| Sigma 6 / 7 / X Sploitkit | erases one whole Escalation and blocks the next |
| Suppressed Alarm, Alarm Malfunction | no Escalation until end of next turn |
| Suppress Escalation | no Escalation for 2 turns |

`GameManager` exposes the same split: `GetPotentialSecurityTallyWithReduction`,
`GetPotentialSecurityTallyWithoutReduction`, `GetPotentialSecurityTallyReduction`,
`GetCommittedSecurityTallyInCurrentEscalation`, `IsSecurityEscalatingThisTurn`,
`ProcessSecurityDeckCard`.

`GameDifficultyModel` carries `SecurityTallyMod`, `SecurityTallyPerHeat` (25 in
the dumped save), `SecurityTallyMaxPerTurn`, `MatrixTallyMaxPerTurn`,
`MissionReinforcementMinWait`. `GameDifficulty.SecurityTallyMode` names the
presets: ZeroTally, NoTally, ReducedTally, Standard, Hardcore.

## Open questions

- [unverified] Which card a selection picked; no captured line names it.
- [unverified] Whether `CardWeight` is a weighted roll or a sort key.
- [unverified] What builds the per-turn tally base.
- [unverified] The direction of `ExclusiveReq` / `NoEnemiesAlive`.
- [unverified] `PostCheck` versus `PostRun` ordering: several cards both `DEL_`
  and `ADD_` the
  same token.
- [unverified] Every `EventAlarmCosts` value not seen firing in the two
  captures.

## The card table

### Deck 1 — SigmaFive (11 cards)

| Card | W | Event | Qty | PreReq | Ex | Lvl | Turn | Effect | Token | Name |
|---|--:|---|--:|---|:-:|---|--:|---|---|---|
| 101 | 1 | SpawnRandomMonster | 0 | SpawnPointsAvailable | Y | 2+ | 2 |  | NOT_Rein / ADD_Rein | Reinforcement Arriving! |
| 102 | 1 | SpawnCloseMonster | 0 | SpawnPointsAvailable | Y | 1+ | 4 |  | NOT_Rein / ADD_Rein | Reinforcement Nearby! |
| 103 | 1 | SecurityDeviceReboot | 4 | DisabledSecurityDevice |  | any | 5 |  | NOT_Reboot / ADD_Reboot | Rebooting {0} disabled devices! |
| 104 | 10 | ProxMinesWakeup | 3 | SleepingProxMines |  | any | 0 |  | NOT_ProxMineMinor / ADD_ProxMineMinor | Arming {0} Proximity Mines! |
| 105 | 1 | SecurityDeviceMoreLethal | 4 | LethalSecurityDevice |  | any | 2 |  |  | {0} {1} engaging HI-POWER mode! |
| 106 | 1 | IncreaseMatrixHostSecurity | 2 | MatrixHostsPresent |  | any | 0 |  |  | Matrix high-alert! |
| 107 | 1 | IncreaseTallyPerTurn | 1 | AutoTallyEnabled |  | 1–4 | 2 |  |  | +1 Tally per Turn! |
| 108 | 2 | SecurityDeviceWakeup | 3 | SleepingSecurityDevice |  | any | 0 |  |  | Woke {0} sleeping devices! |
| 109 | 6 | BodyTimerReduce | 3 | BodyTimersActive |  | any | 0 |  |  | Reducing Body Timers by up to 1 Turn |
| 110 | 6 | ProxMinesWakeup | 1 | SleepingProxMines |  | any | 0 |  | HAS_ProxMineMinor | Arming {0} Proximity Mines! |
| 113 | 4 | TurretSpawn | 1 | TurretsReady |  | 4+ | 2 |  | NOT_Turret / ADD_Turret | Activating {0} Turret! |

### Deck 2 — SigmaSeven (12 cards)

| Card | W | Event | Qty | PreReq | Ex | Lvl | Turn | Effect | Token | Name |
|---|--:|---|--:|---|:-:|---|--:|---|---|---|
| 201 | 1 | SpawnRandomMonster | 0 | SpawnPointsAvailable | Y | 1+ | 2 |  | NOT_Rein / ADD_Rein | Reinforcement Arriving! |
| 202 | 1 | SpawnCloseMonster | 0 | SpawnPointsAvailable | Y | 1+ | 4 |  | NOT_Rein / ADD_Rein | Reinforcement Nearby! |
| 204 | 1 | SecurityDeviceReboot | 4 | DisabledSecurityDevice |  | any | 5 |  | NOT_Reboot / ADD_Reboot | Rebooting {0} disabled devices! |
| 205 | 1 | SecurityDeviceMoreLethal | 4 | LethalSecurityDevice |  | any | 2 |  |  | {0} {1} engaging HI-POWER mode! |
| 206 | 1 | IncreaseMatrixHostSecurity | 2 | MatrixHostsPresent |  | any | 0 |  |  | Matrix high-alert! |
| 207 | 1 | IncreaseTallyPerTurn | 1 | AutoTallyEnabled |  | 1–4 | 2 |  |  | +1 Tally per Turn! |
| 208 | 10 | ProxMinesWakeup | 3 | SleepingProxMines |  | any | 0 |  | NOT_ProxMineMinor / ADD_ProxMineMinor | Arming {0} Proximity Mines! |
| 209 | 6 | ProxMinesWakeup | 5 | SleepingProxMines |  | any | 0 |  | HAS_ProxMineMinor | Arming {0} Proximity Mines! |
| 210 | 6 | BodyTimerReduce | 2 | BodyTimersActive |  | any | 0 |  |  | Reduce Body Timers by up to 2 Turns |
| 211 | 1 | ApplyUniversalGuardBuff | 0 | CombatEngagedEnemies |  | 2+ | 0 | 65005 ×2t |  | Motivating All Guards! |
| 213 | 1 | TurretSpawn | 2 | TurretsReady |  | 5+ | 2 |  | NOT_Turret / ADD_Turret | Activating {0} Turrets! |
| 214 | 6 | TurretSpawn | 1 | TurretsReady |  | 4+ | 2 |  | NOT_Turret / ADD_Turret | Activating {0} Turret! |

### Deck 3 — SigmaNine (14 cards)

| Card | W | Event | Qty | PreReq | Ex | Lvl | Turn | Effect | Token | Name |
|---|--:|---|--:|---|:-:|---|--:|---|---|---|
| 301 | 1 | SpawnRandomMonster | 0 | SpawnPointsAvailable | Y | 1+ | 2 |  | NOT_Rein / ADD_Rein | Reinforcement Arriving! |
| 302 | 1 | SpawnCloseMonster | 0 | SpawnPointsAvailable | Y | 1+ | 4 |  | NOT_Rein / ADD_Rein | Reinforcement Nearby! |
| 304 | 1 | SecurityDeviceReboot | 4 | DisabledSecurityDevice |  | any | 5 |  | NOT_Reboot / ADD_Reboot | Rebooting {0} disabled devices! |
| 305 | 1 | SecurityDeviceMoreLethal | 5 | LethalSecurityDevice |  | any | 2 |  |  | {0} {1} engaging HI-POWER mode! |
| 306 | 1 | IncreaseMatrixHostSecurity | 2 | MatrixHostsPresent |  | any | 0 |  |  | Matrix high-alert! |
| 307 | 1 | ApplyUniversalPlayerDebuff | 0 | CombatEngagedEnemies |  | 2+ | 0 | 65001 ×2t |  | Buffed Firing Accuracy! |
| 308 | 1 | ApplyUniversalPlayerDebuff | 0 | ArmoredEnemiesPresent |  | 2+ | 0 | 65002 ×2t |  | Buffed Anti-Armor Nano! |
| 309 | 1 | IncreaseTallyPerTurn | 1 | AutoTallyEnabled |  | 1–4 | 2 |  |  | +1 Tally per Turn! |
| 310 | 10 | ShockFieldWakeup | 2 | SleepingShockField |  | any | 0 |  | NOT_ProxMineMinor / ADD_ProxMineMinor | Arming {0} Shock Fields! |
| 311 | 6 | ShockFieldWakeup | 4 | SleepingShockField |  | any | 0 |  | HAS_ProxMineMinor | Arming {0} Shock Fields! |
| 312 | 6 | BodyTimerReduce | 2 | BodyTimersActive |  | any | 0 |  |  | Reduce Body Timers by up to 2 Turns |
| 313 | 1 | ApplyUniversalGuardBuff | 0 | CombatEngagedEnemies |  | 2+ | 0 | 65004 ×2t |  | Encouraging Faster Movement! |
| 314 | 1 | ApplyUniversalGuardBuff | 0 | CombatEngagedEnemies |  | 2+ | 0 | 65005 ×2t |  | Motivating stimulants deployed to all guards! |
| 317 | 8 | TurretSpawn | 1 | TurretsReady |  | 3+ | 2 |  | NOT_Turret / ADD_Turret | Activating {0} Turret! |

### Deck 4 — SigmaTech (9 cards)

| Card | W | Event | Qty | PreReq | Ex | Lvl | Turn | Effect | Token | Name |
|---|--:|---|--:|---|:-:|---|--:|---|---|---|
| 316 | 1 | TurretSpawn | 2 | TurretsReady |  | 4+ | 2 |  | NOT_Turret / ADD_Turret | Activating {0} Turrets! |
| 400 | 1 | SecurityDeviceReboot | 5 | DisabledSecurityDevice |  | any | 5 |  | NOT_Reboot / ADD_Reboot | Rebooting {0} disabled devices! |
| 401 | 1 | SecurityDeviceMoreLethal | 3 | LethalSecurityDevice |  | any | 2 |  |  | {0} {1} engaging HI-POWER mode! |
| 402 | 1 | IncreaseMatrixHostSecurity | 2 | MatrixHostsPresent |  | any | 0 |  |  | Matrix high-alert! |
| 403 | 1 | ApplyUniversalPlayerDebuff | 0 | — |  | 2+ | 0 | 65003 ×2t |  | Debuffed AP / MP |
| 404 | 1 | IncreaseTallyPerTurn | 1 | AutoTallyEnabled |  | 1–4 | 2 |  |  | +1 Tally per Turn! |
| 405 | 6 | BodyTimerReduce | 1 | BodyTimersActive |  | any | 0 |  |  | Reduce Body Timers by up to 1 Turn |
| 407 | 1 | TurretSpawn | 2 | TurretsReady |  | 4+ | 2 |  | NOT_Turret / ADD_Turret | Activating {0} Turrets! |
| 408 | 10 | TurretSpawn | 1 | TurretsReady |  | 3+ | 2 |  | NOT_Turret / ADD_Turret | Activating {0} Turret! |

### Deck 5 — StreetGangSecurity (6 cards)

| Card | W | Event | Qty | PreReq | Ex | Lvl | Turn | Effect | Token | Name |
|---|--:|---|--:|---|:-:|---|--:|---|---|---|
| 501 | 1 | SpawnRandomMonster | 0 | SpawnPointsAvailable | Y | 2+ | 6 |  | NOT_Rein / ADD_Rein | Reinforcement Arriving! |
| 502 | 1 | SpawnCloseMonster | 0 | SpawnPointsAvailable | Y | 1+ | 3 |  | NOT_Rein / ADD_Rein | Reinforcement Nearby! |
| 503 | 2 | IncreaseTallyPerTurn | 1 | AutoTallyEnabled |  | 1–4 | 2 |  |  | +1 Tally per Turn! |
| 504 | 10 | ProxMinesWakeup | 3 | SleepingProxMines |  | any | 0 |  | NOT_ProxMineMinor / ADD_ProxMineMinor | Arming {0} Proximity Mines! |
| 505 | 6 | ProxMinesWakeup | 5 | SleepingProxMines |  | any | 0 |  | HAS_ProxMineMinor | Arming {0} Proximity Mines! |
| 506 | 1 | ApplyUniversalGuardBuff | 0 | CombatEngagedEnemies |  | 2+ | 0 | 65004 ×2t |  | Chemical accellerants for combat! |

### Deck 8 — DemoDeck (6 cards)

| Card | W | Event | Qty | PreReq | Ex | Lvl | Turn | Effect | Token | Name |
|---|--:|---|--:|---|:-:|---|--:|---|---|---|
| 600 | 1 | SpawnRandomMonster | 0 | — | Y | 2+ | 2 |  | NOT_Rein / ADD_Rein | Reinforcement Arriving! |
| 601 | 1 | SpawnCloseMonster | 0 | — | Y | 3+ | 4 |  | NOT_Rein / ADD_Rein | Reinforcement Nearby! |
| 603 | 1 | SecurityDeviceReboot | 4 | DisabledSecurityDevice |  | 1+ | 5 |  | NOT_Reboot / ADD_Reboot | Rebooting {0} disabled devices! |
| 604 | 1 | SecurityDeviceMoreLethal | 5 | LethalSecurityDevice |  | 2+ | 2 |  |  | {0} {1} engaging HI-POWER mode! |
| 606 | 1 | IncreaseTallyPerTurn | 1 | AutoTallyEnabled |  | 2–4 | 2 |  |  | +1 Tally per Turn! |
| 607 | 10 | SecurityDeviceWakeup | 3 | SleepingSecurityDevice |  | any | 0 |  |  | Woke {0} sleeping devices! |

### Deck 9 — SyndicateSecurity (6 cards)

| Card | W | Event | Qty | PreReq | Ex | Lvl | Turn | Effect | Token | Name |
|---|--:|---|--:|---|:-:|---|--:|---|---|---|
| 900 | 1 | SpawnRandomMonster | 0 | SpawnPointsAvailable | Y | 2+ | 6 |  | NOT_Rein / ADD_Rein | Reinforcement Arriving! |
| 901 | 1 | SpawnCloseMonster | 0 | SpawnPointsAvailable | Y | 1+ | 3 |  | NOT_Rein / ADD_Rein | Reinforcement Nearby! |
| 903 | 10 | ProxMinesWakeup | 3 | SleepingProxMines |  | any | 0 |  | NOT_ProxMineMinor / ADD_ProxMineMinor | Arming {0} Proximity Mines! |
| 904 | 1 | SecurityDeviceReboot | 5 | DisabledSecurityDevice |  | any | 5 |  | NOT_Reboot / ADD_Reboot | Rebooting {0} disabled devices! |
| 905 | 2 | IncreaseTallyPerTurn | 1 | AutoTallyEnabled |  | 1–4 | 2 |  |  | +1 Tally per Turn! |
| 906 | 6 | ProxMinesWakeup | 5 | SleepingProxMines |  | any | 0 |  | HAS_ProxMineMinor | Arming {0} Proximity Mines! |

### Deck 11 — SigmaBlack (17 cards)

| Card | W | Event | Qty | PreReq | Ex | Lvl | Turn | Effect | Token | Name |
|---|--:|---|--:|---|:-:|---|--:|---|---|---|
| 800 | 1 | SpawnRandomMonster | 0 | SpawnPointsAvailable | Y | 1–4 | 2 |  | NOT_Rein / ADD_Rein | Reinforcement Arriving! |
| 801 | 1 | SpawnCloseMonster | 0 | SpawnPointsAvailable | Y | 1–4 | 4 |  | NOT_Rein / ADD_Rein | Reinforcement Nearby! |
| 802 | 1 | SpawnRandomMonsterDouble | 0 | SpawnPointsAvailable | Y | 4+ | 2 |  | NOT_Rein / ADD_Rein | Double Reinforcement! |
| 803 | 1 | SpawnRandomMonsterDoubleClose | 0 | SpawnPointsAvailable | Y | 5+ | 3 |  | NOT_Rein / ADD_Rein | Double Reinforcement Nearby! |
| 804 | 1 | SecurityDeviceReboot | 6 | DisabledSecurityDevice |  | any | 2 |  | NOT_Reboot / ADD_Reboot | Rebooting {0} disabled devices! |
| 805 | 1 | SecurityDeviceMoreLethal | 6 | LethalSecurityDevice |  | any | 2 |  |  | {0} {1} engaging HI-POWER mode! |
| 806 | 1 | IncreaseMatrixHostSecurity | 2 | MatrixHostsPresent |  | any | 0 |  |  | Matrix high-alert! |
| 807 | 1 | ApplyUniversalPlayerDebuff | 0 | CombatEngagedEnemies |  | 2+ | 0 | 65001 ×2t |  | Buffed Firing Accuracy! |
| 808 | 1 | ApplyUniversalPlayerDebuff | 0 | ArmoredEnemiesPresent |  | 2+ | 0 | 65002 ×2t |  | Buffed Anti-Armor Nano! |
| 809 | 1 | IncreaseTallyPerTurn | 2 | AutoTallyEnabled |  | 1–4 | 2 |  |  | +2 Tally per Turn! |
| 810 | 10 | ProxMinesWakeup | 6 | SleepingProxMines |  | any | 0 |  | NOT_ProxMineMinor / ADD_ProxMineMinor | Arming {0} Proximity Mines! |
| 811 | 6 | ProxMinesWakeup | 10 | SleepingProxMines |  | any | 0 |  | HAS_ProxMineMinor | Arming {0} Proximity Mines! |
| 812 | 10 | BodyTimerReduce | 3 | BodyTimersActive |  | any | 0 |  |  | Reduce Body Timers by up to 3 Turns |
| 813 | 1 | ApplyUniversalGuardBuff | 0 | CombatEngagedEnemies |  | 2+ | 0 | 65004 ×2t |  | Encouraging Faster Movement! |
| 814 | 1 | ApplyUniversalGuardBuff | 0 | CombatEngagedEnemies |  | 2+ | 0 | 65005 ×2t |  | Motivating stimulants deployed to all guards! |
| 816 | 4 | TurretSpawn | 2 | TurretsReady |  | 3+ | 2 |  | NOT_Turret / ADD_Turret | Activating {0} Turrets! |
| 817 | 12 | TurretSpawn | 1 | TurretsReady |  | 2+ | 2 |  | NOT_Turret / ADD_Turret | Activating {0} Turret! |
