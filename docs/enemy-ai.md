# Enemy AI

Use this page to interpret the game's named per-turn AI log and the traced
reposition tables. Enemy-stat levers are in
[`tuning-enemies.md`](tuning-enemies.md); the two `RuleModel` rows containing
`AI` affect presentation or relevance, not behavior
([`gotchas.md`](gotchas.md)).

The baseline capture is `[measured, Logs/PlayedLogB.log]`: one mission and 269
traced unit turns in which the player was never engaged. Combat-reposition
sections name their separate `Logs/Run71.log` sample explicitly. The later
live-fight capture is `Logs/Run77.log`.

## Capture and instrumentation

The game builds a named per-turn account and prints it to the Unity log:

```
TURN LOG 9 for Qumu (MK FireCON) on INIT 21
-) Starting turn as Alerted
-) Starting position at (-0.46, -1.99, -15.77)
...
-) Ending turn as Alerted
```

That reaches `LogOutput.log` only with `[Logging.Disk] WriteUnityLog = true` in
`BepInEx.cfg`, whose shipped default is `false` ([`gotchas.md`](gotchas.md)). For
return values the log does not print, `AIController.AddTurnLog(String)`
and `AIRepositionPlanner.AddTurnRepositionLog(String)` are the append calls; a
Data Dump `[Diagnostics] TraceMethods` postfix on them prints the string. The
live spec is in `ckf.datadump.cfg`; `FindMethods` prints each signature so an
unresolved name shows as a warning rather than silence.

Named states resolve through `_id_constants.csv`: `AiCurrentState` Planning 0,
EndingTurn 1, Patrol 2, Hunting 3, Chasing 4, Attacking 5, Reposition 6,
Delaying 7, Dying 8, PostTalentAction 9. `AiAlarmLevel` DeepSleep -2, Asleep -1,
Unaware 0, Suspicious 1, Alerted 2, Spotted 3, Aggro 4, HeadHunterVIP 5,
HeadHunterKnight 6.

## Alarm levels

Nine, not the three the HUD shows. `AiAlarmLevel`, from `_id_constants.csv`:

| | | | |
|---|---|---|---|
| DeepSleep | -2 | Spotted | 3 |
| Asleep | -1 | Aggro | 4 |
| Unaware | 0 | HeadHunterVIP | 5 |
| Suspicious | 1 | HeadHunterKnight | 6 |
| Alerted | 2 | | |

`MonsterTypeModel` carries a movement speed per tier: `PatrolSpeed`, `ChasingSpeed`,
`AggroSpeed` (2.75 / 3.75 / 4.25 on most rows).

**A second ladder runs alongside it, per merc.** `CharacterAlarmLevel` is how known
one of *your* characters is: NeverSeen 0, Suspected 1, BeingHunted 2, Spotted 3,
Marked 4. It lives on `RPG.Control.PlayerAlarmLevel`
(`GetUnitAlarmLevel(GameCharacterModel)`, `UpdateCurrentTurnAlarmLevel`,
`ResetAITurnAlarmLevel`) and it is an argument to the enemy's own
`AIEventsResponseDispatcher.RespondToEvent(Int64, EventHints, Boolean, CharacterAlarmLevel)`,
so how an enemy reacts depends on which merc tripped it and how known that merc
already was.

**Escalation is event-driven, not proximity-driven.**
`AIEventsResponseDispatcher` raises `CreateSuspicionEvent(Vector3, Int64, EventHints, Boolean)`,
`CreateSpottedEvent(PlayerController)`, `CreateEnemySpottedEvent(AIController)`,
`CreateSpottedAttackEvent(...)`, `CreateAlertedByDeBuffEvent()` and
`CreateTokenSpottedEvent(ITalentToken)`. The cause rides along as `EventHints`:
None 0, GunfireFriendly 9, Gunfire 10, GrenadeExplosion 11, LureTalent 12,
NoiseSneaking 13, NoiseRunning 14, NoiseGunfire 15, SuspiciousHalfSpotted 16.

**It spreads.** `RPG.Control.AIGroupInteraction` has
`IsCanShareAlertLevelWithOther(AIController)`, `IsInteractionIncreaseOwnAlertLevel(AIController)`
and `TrySendAlertQuip(AiAlarmLevel, AIController)`. The chatter names the rungs it
can push a neighbour to: `AIQuipType` LocalAlertChatter 24,
LocalAlertRaiseToSuspicious 25, LocalAlertRaiseToAlerted 26, LocalAlertRaiseToSpotted 27.
Nothing in that set raises a neighbour to Aggro or either HeadHunter level
`[fitted]`.

**Detection is several channels, not one.** `AIDetectorCheck` fills an
`EnemyDetectorState` with `SoundDetected`, `VisualDetected`, `PressureDetected`,
`ProximityMineDetected`, `ShockFieldDetected`, `OverwatchDetected` and
`InSmokeArea`, against the unit's `SightDistance`, `DetectDistance`, `FieldOfView`
and `SoundDetectRadius`.

**Sleep is separate from unawareness.** `IsSleeping()`, and `RuleModel` RuleId 6
`AI Sleepy Distance` 40 is what wakes a unit; `IsBehaviorAlwaysAwake()` exempts
one. `IsBehaviorRunOnceAlerted()` changes movement once a unit is alerted.
The `AiAlarmLevel` enum places HeadHunterVIP and HeadHunterKnight above Aggro.
`IsHeadHunter()`, `IsVIPHunter()`, and `RuleModel` 49-50, Base Head Hunter Chance
15 and Head Hunter Chance Per Heat 4, are related metadata. The two values
identify special enemy types, not a normal guard's next escalation step
`[source: David]`.

`[source: David]` VIP Hunters are specific story-related enemies. Head Hunters
are elite enemies with a chance to spawn, outside the typical enemy roster.
Apart from the target knowledge named as "cheating" in the turn log, both
follow the normal enemy AI rules. Alerted is an elevated non-combat state that
allows defensive talents, including the grenade action seen in Run77.

## Combat entry is gated by Aggro in the captured turns

`[measured, Logs/Run71.log — 63 unit turns across 6 combat turns, 16 named units]`
The split is total. Every turn that ran the combat reposition carried the line

```
#) Identified <merc> that is Spotted+, we are Spotted+, calculating attack vector
#) PlannerExecuteReposition with a Best Shot or Viable Target
```

and every turn that did not, did not.

| Turn starts at | n | Destination source | Ran combat reposition |
|---|---|---|---|
| Aggro | 35 | none — combat reposition | 35 |
| Alerted | 20 | SecurityOrder 19, MonsterEvent 1 | 2, both after escalating to Aggro mid-turn |
| Suspicious | 5 | SecurityOrder 2, Patrol 1 | 2, both after escalating to Aggro mid-turn |
| Asleep | 3 | none | 0 |

**In this Run71 sample, Alerted or Suspicious enemies following a security
dispatch order did not enter the combat reposition path before reaching Aggro.**
Their turn is `Update 4.1) We have a valid destination with
source SecurityOrder at (x,y,z) which is N m away`, it walks there, and on
arrival `UnitMover has stopped, Chasing State Returning to Planning from
Chasing` and the turn ends. The distance it stops at is the order's destination,
not a range to your team. Worked cases: Thedo on turn 5 (Alerted, SecurityOrder
12.0 m away) and Qapo on turns 3, 4 and 5 (Alerted, SecurityOrder 18.7 m away on
turn 5), both stopping short of the fight; Qapo reached Aggro only on turn 6 and
repositioned and attacked in the same turn. Psi on turn 3 does it from
Suspicious. An enemy that runs up, stops with action points to spare and ends
its turn has arrived at its order, and nothing about range or the reposition
planner is involved.

In Run71, `P) Alarm level spotted, will not skip` appears on exactly the 35
Aggro-start turns and nowhere else; `P) we are asleep (Asleep)` on the 3 Asleep
turns. Run77 also prints the spotted line for Spotted and HeadHunterVIP turns.

### Combat-reposition sequence

```
#) Planning classic reposition to closest viable target: <merc>
#) Reposition planning completed with 58 options
#) Trying reposition to weight 33 at RPG.Control.RepositionOption
#) Succeeded and starting preplanned movement.
Finished AiCurrentState.Reposition
#) have repositioned, attacking Best target of 2
```

39 planner runs, 37 reaching `Trying reposition`, 37 succeeding, 27 ending in an
attack. `fullMove` was `True` 32 times and `False` 7. Every one of the 26 runs
whose hint block said `Impassible Blocked? True` was `fullMove = True`; all 7
`False` runs had `Impassible Blocked? False`, and 5 of those 7 also had
`Inside Optimal: True`. A unit already in optimal range with a clear path is the
case that shifts rather than advances `[fitted]` — the three printed hints do not
determine it on their own.

## Run77: a live fight and separate grenade actions

`[measured, Logs/Run77.log]` The capture has 86 named unit turns across game
turns 1–12. The starting alarm tiers were Alerted 43, Suspicious 15, Unaware 10,
Aggro 9, Asleep 5, HeadHunterVIP 3 and Spotted 1 (`TURN LOG` blocks, lines
8629–24030). Five turns changed tier: Qupo Spotted → Aggro (turn 2, line 9528),
Sitha Suspicious → Aggro (turn 3, line 11829), Fifo Suspicious → Alerted (turn 5,
line 14128), Zyn Suspicious → Alerted (turn 7, line 17296), and Drako Alerted →
Aggro (turn 11, line 21640). These are end-of-turn observations; the log does
not identify every event that caused a change.

The buffered turn logs and the owner-tagged live traces both show 15 combat
reposition calls: `PlannerExecuteReposition(..., fullMove)` was `True` 12 times
and `False` 3 times (trace lines 9481–21603). The 15 turns started Aggro 9,
HeadHunterVIP 3, Spotted 1, Suspicious 1 and Alerted 1. The last three ended
Aggro. Sitha began with a SecurityOrder destination and Drako with a
MonsterEvent destination; each logged another `AiCurrentState.Planning` pass
before combat reposition (lines 11834–12023 and 21645–21668). Qupo's Spotted
turn chose an enemy target, shifted, then logged `Attacking - Target is invalid`
(lines 9535–9570). A reposition call therefore does not by itself establish a
completed attack.

`[measured, Logs/Run77.log]` Brain Worm was used before Qupo's turn (lines
9034–9046), and Qupo's planning named Gux and Jeq, both enemies, as viable
targets (lines 9535–9547). `[source: David]` Qupo was the Brain Worm target;
the debuff made this first attacking enemy turn against its allies. The log
does not itself name the Brain Worm target.

`[measured, Logs/Run77.log]` Drako followed a SecurityOrder on turn 10 (lines
20678–20685), then entered combat reposition and a Fighter action on turn 11
(lines 21624–21633 and 21640–21692). `[source: David]` Drako was a normal guard
sent by security dispatch; he turned, saw the team, and was the only other
enemy who actually attacked during this mission.

The three HeadHunterVIP turns name Dakota as the target and say `VIP Hunters
cheat and always know about the VIP` (lines 12391–12560). Eight Aggro turns
for Saga, War Elephant, Kabo and Pota instead print `Head Hunters cheat and
always know about the target` while naming multiple mercs (lines 14525–16223).
Those are the game's own planning messages; the capture does not reveal how
the individual units were selected for these roles.

`[measured, Logs/Run77.log]` Zyn (F-Duster, entity 1154) ran an
`AIGrenadeFighter` action ending in `AttackImpact()` on turns 7, 8, 9, 11 and
12 (live lines 17276–17290, 18055–18069, 19442–19456, 22213–22227 and
23628–23643). Its named turn log ended Alerted on all five turns (lines
17296–17304, 18075–18345, 19462–19475, 22233–22246 and 23649–23701).
None of these turns logged combat reposition. Thus the standard combat
reposition path does not cover this grenade action. The log does not name the
grenade target.

`[measured, Logs/Run77.log]` The trace setup announced patches for
`AIController.CanMove` and `AIRepositionPlanner.AddTurnRepositionLog` (lines
2206 and 2266), but neither emitted a live trace row. Other traced methods did,
including 15 `PlannerExecuteReposition` rows and 52
`PrintTurnRepositionLog` rows. The silence leaves it unresolved whether these
two append/decision methods were not called or their patches did not observe
the calls.

## Measured reposition-planner behavior

All of this is `[measured, Logs/Run71.log]`: 41 option tables, 704 candidate
positions, 16 named units, every enemy at PL 18.

### Line of sight is the gate, and the range band decides whether it applies

`No Line of Sight` (49 rows) and `Beyond Flank Allowance` (17 rows) appear
**only** in tables whose hint block says `Inside Max: True`. Zero of either when
the target is beyond max weapon range.

Out of max range, a position without line of sight is not discarded — it is kept
and scored as `Advancing!`, `Getting into range!` or `Getting optimal range!`.
In range, it is discarded. So an out-of-range unit plans from a candidate set in
which nothing can shoot: all 13 out-of-range tables contained zero positions with
line of sight, and in every one the winning position had none.

### Whether a unit advances into cover is a property of the map, not the unit

Perfect separation across 114 rows:

| label | n | Cover From Target | Cover Points | Cover Weight | Dist Weight |
|---|---|---|---|---|---|
| `Advancing!` | 53 | `-` on all 53 | 0 on all 53 | 1.00 on all 53 | 1.25 |
| `Getting optimal range!` | 138 | `-` on all | 0 on all | 1.00 on all | 2.50 / 1.50 / 1.25 |
| `Taking cover!` | 61 | `X` on all 61 | mean 2.18, max 3 | 4.50 (42) or 3.50 (19) | 1.00 - 2.50 |

The label names what the square offers. A unit that runs straight at the player
without taking cover had no candidate square with cover from the target; every
option it saw carried Cover Weight 1.00. Nothing about the archetype enters into
it.

`Cover Weight` takes the values 1.00, 3.50 and 4.50; `Dist Weight` takes 1.00,
1.25, 1.50, 2.25 and 2.50. Cover therefore multiplies by up to 4.5 against a
distance term that never exceeds 2.5.

### A unit out of range can stop almost where it stands

Best option's resulting distance, for every unit whose target was beyond max
range:

| unit | start | after | closed | winning label |
|---|---|---|---|---|
| Gux (WB Guard) | 60.30 | 38 | 22.3 | Advancing! |
| Fwi (WB Assault) | 54.69 | 31 | 23.7 | Advancing! |
| Rhi (WB Assault) | 46.47 | 23 | 23.5 | Advancing! |
| Uma (WB Guard) | 47.07 | 29 | 18.1 | Getting into range! |
| Gux (WB Guard) | 37.95 | 18 | 20.0 | Taking cover! |
| Alto (WB FireCOM) | 37.61 | 17 | 20.6 | Getting optimal range! |
| Thul (WB Assault) | 32.45 | 12 | 20.5 | Getting optimal range! |
| Fwi (WB Assault) | 30.82 | 8 | 22.8 | Taking cover! |
| Omxi (WB FireCOM) | 27.53 | 14 | 13.5 | Getting optimal range! |
| Rhi (WB Assault) | 22.20 | 10 | 12.2 | Flanking! |
| **Alto (WB FireCOM)** | **26.77** | **19** | **7.8** | **Taking cover!** |
| **Thedo (WB FireCOM)** | **30.58** | **30** | **0.6** | **Taking cover!** |

The two outliers are also the two largest candidate sets, 49 and 58 options
against 3-35 everywhere else.

### Both a straight-line and a path distance are tracked

Every table's hint block prints both: `Starting Distance: 4.153407 / Nav:
17.594`. `RepositionOption` carries `DistanceToTarget` and
`NavDistanceToTarget` as separate fields, and each option row has a `Nav Assist`
flag `[measured, CoreRPG_v1.dll metadata]`.

The two diverge often and by a lot. 7 of 39 tables had a nav-to-straight-line
ratio of 1.47 or more: Beta 4.15 / 17.59 (ratio 4.24), Uma 5.15 / 13.41 (2.60),
Gux 5.55 / 11.32 (2.04), Sixo 7.69 / 14.01 (1.82), Beta 17.69 / 31.15 (1.76),
Qupo 13.32 / 19.84 (1.49), Epsilon 11.87 / 17.51 (1.48). That is the shape of a
position that is close through a wall and far around it.

## `FlankAllowance`

`MonsterTypeModel.FlankAllowance` is a per-archetype angle. Shipped values rise
with power level for four of these five examples
`[measured, sheets/raw/MonsterTypeModel.csv]`:

| Archetype | PL 1 | PL 10 | PL 18 |
|---|---|---|---|
| WB Guard | 60 | 90 | 90 |
| WB Assault, WB FireCOM, Suppressant | 90 | 115 | 115 |
| WB Captain | 120 | 180 | 180 |
| Guard Sniper | 90 | 180 | 180 |
| Hover Tank | 120 | 120 | 120 |

Inspect the live `MonsterTypeModel.csv` overlay for current tuning; mutable
overlay values are not recorded in this document.

What the reposition log shows `[measured, Run71.log]`:

- A rejected row reads `<angle>  Beyond Flank Allowance` and carries `Weight -1`.
- All 17 such rows had `LOS? -`, `Cover From Target -` and `Cover Points 0`.
  **Not one row with `LOS? X` was ever flagged**, against 80 rows labelled
  `Flanking!` that all have line of sight. The test never reaches a position that
  can see its target.
- Restricted to the population where it does apply - inside max range, no line of
  sight, no cover from target - the angle separates `No Line of Sight` from
  `Beyond Flank Allowance` cleanly, with no overlap in any table: Rhi 4.3-42.5
  against 88.4-97.1, Beta 18.3-69.7 against 80.8-87.8, Omxi 23.7-48.5 against
  104.2-115.0, Epsilon up to 72.4 against 86.7-106.5.
- **Both labels produce `Weight -1`.** In this capture FlankAllowance decided
  which rejection reason was printed and changed no position the planner chose.
- One row read `NaN  Beyond Flank Allowance`, on the unit's own current position.

### Open: what the angle is compared against

Four bracketed observations do not
determine a rule, and no plausible relation to the shipped or overlaid
`FlankAllowance` follows from them without inventing a constant. Whether the
column is the compared quantity at all is `[unverified]`, and so is whether the
mod's overlaid values reach this test. Do not write a formula here until one is
read.

What would settle it: `RPG.Control.RepositionOption.CalculateCombatWeight(RepositionPlanner,
AIController, ICombatEntity, Single, Single, Single, Boolean)` takes three
`Single` arguments and has a large unique body, so it is a safe patch target
under [`patching-rules.md`](patching-rules.md). Tracing it prints the numbers the
planner is handed, and the same rows answer whether the weight uses
`DistanceToTarget` or `NavDistanceToTarget`.
`RepositionOption.IsPointWithinAngleView(Vector3, Vector3, Single, Vector3)` is
the angle test itself; its body is plausibly one expression, so it must not be
patched.

## An alarm level that rises mid-turn is noticed sometimes, not always

`[measured, Logs/Run71.log]` A unit that is already Aggro when
`AiCurrentState.Planning` runs always fights: 35 turns, 35 combat repositions.
The question is what happens when the alarm rises *after* planning has already
committed the unit to a destination.

Ten units escalated to Aggro during a turn. Two of them had no destination and
were Aggro by the time the first `Planning` pass ran, so they fought on it (Gux
and Uma, turn 1). The other eight were mid-move on a `SecurityOrder` or
`MonsterEvent` destination when the escalation happened. **Two of those eight
noticed and redirected; six did not.**

The observable difference is a second `AiCurrentState.Planning` pass *during*
the move, before any reposition:

```
AiCurrentState.Planning
Update 4.1) We have a valid destination with source SecurityOrder at (...) 24.15448 m away
   [88 frames of movement]
AiCurrentState.Planning                                    <-- second pass
#) Identified Panther that is Spotted+, we are Spotted+, calculating attack vector
#) PlannerExecuteReposition with a Best Shot or Viable Target
```

The six that failed have exactly one `Planning` line, then the movement frames,
then `AiCurrentState.PostTalentAction`. The Spotted+ check is never re-run, so
the unit walks out its order and the turn ends with it newly Aggro and having
done nothing. Across all 23 destination-following turns in the capture, only
those two ran a second `Planning` pass.

| turn | unit | destination | move frames | second Planning | nearest Aggro ally at turn start |
|---|---|---|---|---|---|
| 4 | Omxi (WB FireCOM) | SecurityOrder 24.2 m | 89 | **yes** | 7.7 m |
| 6 | Qapo (WB Assault) | MonsterEvent 10.2 m | 59 | **yes** | 19.0 m |
| 3 | Epsilon (Suppressant) | SecurityOrder 24.0 m | 56 | no | 18.8 m |
| 3 | Qupo (Guard Sniper) | SecurityOrder 23.5 m | 39 | no | 1.6 m |
| 4 | Sixo (WB Captain) | SecurityOrder 32.3 m | 179 | no | 28.7 m |
| 4 | Alto (WB FireCOM) | SecurityOrder 22.5 m | 149 | no | 10.6 m |
| 5 | Thedo (WB FireCOM) | SecurityOrder 12.0 m | 179 | no | 12.3 m |
| 5 | Oju (WB Captain) | SecurityOrder 15.7 m | 180 | no | 1.5 m |

### Skipping a turn interrupts the movement on ShareAlertLevel or VisualDetectPlayer

`[measured, Run71.log]` Skipping an enemy turn routes it through a fast-forward
that carries an interrupt reason:

```
AIC.FastForward Turn Called with Mover=True and ShareAlertLevel
FastForward distance to interruption is 6.376199 and 6.421266 vs final point 12.79746
CompleteFastForwardMovementWhenMoving (-26.43, 0.03, 2.60) ... Moving and RotationReached
```

14 of the 63 turns called it. The reason was `None` on 10 and named on 4, and
**exactly those 4 produced a distance-to-interruption line**:

| turn | unit | reason | fast-forward stopped at |
|---|---|---|---|
| 1 | Rhi (WB Assault) | `ShareAlertLevel` | 50% of the final point |
| 2 | Rhi (WB Assault) | `ShareAlertLevel` | 79% |
| 3 | Beta (WB Guard) | `ShareAlertLevel` | 69% |
| 3 | Qapo (WB Assault) | `VisualDetectPlayer` | 55% |

`MoverBase.fastForwardWhenMoveDistanceBeforeInterrupt`
`[measured, CoreRPG_v1.dll metadata]` is the field behind it. The two named
reasons are exactly the two events a player describes as "it stopped the moment
it noticed something".

What this does **not** establish is that the unit's movement is truncated.
`CompleteFastForwardMovementWhenMoving` hands back to normal movement, and
Qapo's turn-3 move covered its full 24.1 m despite being interrupted at 55% of a
19.1 m segment. So the interrupt ends the *fast-forward*, and the rest is played
out at normal speed. Whether that also changes what the unit decides is
`[unverified]`.

### No post-stop window or clean turn-length measure

`[measured]` Counting the turn manager's own `ReadyToEndTurn` polls between a
movement-stop marker and the unit's next `-> True`: 0 polls in the large
majority of cases, with a handful at 1, 2 and ~32. There is no consistent
window in which a stopped unit sits before its turn resolves, so a "timeout
after standing still" does not show up in this capture.

Frame counts cannot establish a per-turn time budget in this capture. Skipped
turns are fast-forwarded, compressing their frame counts, and 14 of the 63 turns
were skipped. Excluding them leaves no stable relation: Omxi on turn 3 took 11.1
frames per metre against 1.3–2.9 for neighboring turns.

Log-order rules:

- **The Unity TURN LOG is buffered and flushed when the turn ends.** Its lines
  appear in the file after the turn they describe, so they cannot be interleaved
  with live `[MoverBase]` or `TRACE` lines, and trace rows that sit inside a
  `TURN LOG` block usually belong to the *next* unit. Order within the buffered
  blob is real; order between the blob and anything else is not.
- **`[MoverBase] Calling() stop because we are at the destination and rotation`
  is the arrival marker**, 68 occurrences. `Update.Patrol/Chasing) UnitMover has
  stopped` is only the Patrol/Chasing handler; its absence does not establish
  that a unit failed to arrive.

### Open: what triggers the second planning pass

Three candidates are ruled out by the
table above.

- Not movement duration. The two that re-planned took 59 and 89 frames; six
  turns that did not re-plan took 30 to 56, and the full range across all
  moving turns is 30 to 253 with no cutoff anywhere.
- Not distance to the destination, which spans 10.2 to 32.3 m on both sides.
- Not proximity to an Aggro ally. Qupo stood 1.6 m and Oju 1.5 m from one and
  never re-planned; Qapo re-planned from 19.0 m.

Nothing else in the turn log separates the two groups. Do not write a trigger
here until one is read. `AIController.PrePlanTurn` and the `PrePlannedSkipTurn`,
`PrePlannedDestinationSource` and `PrePlannedDestinationIsValid` fields are where
a per-turn commitment would live `[measured, CoreRPG_v1.dll metadata]`; none has
been traced with the instance tag yet.

### Additional observed state behavior

`[measured, Logs/PlayedLogA.txt]` 46 turns, every one `Starting turn as Alerted`
and `Ending turn as Alerted`. Not one transition between tiers was captured, and
no tier other than Alerted appeared as a turn state.

`[measured, Logs/PlayedLogB.log]` eight `[!!] Wakes up from Asleep and rolls
Initiative of N` — waking rolls initiative on the spot.

`[measured, PlayedLogA.txt]` alarm decays on a schedule: ` [-] Alarm Reduced by 0`
fires once per game turn, immediately after `## PROCESSING NEW TURN (n)` and
before the monster-event tally. It reduced by 0 on all seven turns captured, so
the decay step exists and its size under other conditions is unknown.

Hunting carries a turn budget: `H) Completed Hunt Move this turn, reducing Hunt
Turns to N`, observed counting 3, 2, 1, 0 (`AIController.GetHuntMoveTurns()`).
A hunt ends with `H) Hunt to target is COMPLETED AI Position=(...). Cancel Hunting.`

## Two turn shapes

**Nothing to do** — 40 of 269 turns. `PrePlanTurn` returns `True` and the unit
ends without moving:

```
PrePlanTurn                                      -> True
ReadyToEndTurn                                   -> True
AddTurnLog  AiCurrentState.PostTalentAction
AddTurnLog  AiCurrentState.Attacking - talent try no target
AddTurnLog  #) Considering valid filter options after Reposition 0
ReadyToEndTurn                                   -> True
```

**A patrol leg** — 229 of 269. `PrePlanTurn` returns `False` and the turn runs
live, `ReadyToEndTurn` polled once a frame while the unit walks:

```
AddTurnLog  P-Patrol) Destination is set ((2.05, 0.01, 18.81)) and SKIP FLAG = False
PrePlanTurn                                      -> False
ReadyToEndTurn  x31                              -> False
AddTurnLog  AiCurrentState.Planning
AddTurnLog  Update 4.1) We have a valid destination with source Patrol at (...) which is 12.57 m away
AddTurnLog  Update 4.1) Starting UnitMover for patrol
ReadyToEndTurn  x60-x239                         -> False
AddTurnLog  Update.Patrol/Chasing) UnitMover has stopped, Patrol State Returning to Planning from Patrol
AddTurnLog  Update.Patrol/Chasing) have arrived at patrol waypoint, setting up patrol point advance and ending turn
ReadyToEndTurn                                   -> True
<the same three-line coda>
```

`PrePlanTurn -> True` is not "the unit is busy": every `True` in the sample was
followed immediately by `ReadyToEndTurn -> True` and a turn with no movement.
A stunned unit is the exception to both shapes — `P) we are Stunned!`,
`PrePlanTurn -> False`, then `ReadyToEndTurn -> True` straight away.

## The coda is not a bug signature

Every traced turn ends with the same three lines, whatever it did:

```
AiCurrentState.PostTalentAction
AiCurrentState.Attacking - talent try no target
#) Considering valid filter options after Reposition N
```

24 codas in the sample; 23 carried the `Reposition` line (the stunned unit's did
not). `N` was 0 fourteen times and 1 nine times. These fire after a *completed*
patrol move as readily as after a no-op turn, so "Attacking - talent try no
target" means the end-of-turn talent check found nobody in range. It is not
evidence that a unit failed to act.

## A patrolling unit ends its turn on arrival

`have arrived at patrol waypoint, setting up patrol point advance and ending
turn` closed 9 of the 15 patrol legs in the sample. The turn ends at the
waypoint whatever action points remain: patrol legs are not sized to the AP
budget. An unaware patroller that walks into the player's line of sight,
reaches its waypoint and stops has done exactly this and nothing is wrong.
`[fitted]` as the explanation for a single such sighting in this session — the
trace carries no per-unit identity in this capture, so no row can be matched to
a particular enemy. The identity tag added to `Trace.cs` afterwards closes that
gap.

Every `Destination is set` line in the sample carried `SKIP FLAG = False`,
15 of 15.

## Empty instruments in the baseline capture

An instrument's silence is not evidence, so what was watched and stayed empty:

- **No combat reposition.** `AIRepositionPlanner.CalculateRepositionOptions` and
  `PlannerExecuteReposition` were patched and produced zero rows in 3,600 lines.
  All 801 `RepositionOption.LogThis` rows end `Hunting.`, so only
  `RepositionPlanner.CalculateHuntWeights` ran. The `fullMove` boolean that picks
  advance over shift was never evaluated, so the half-move question
  ([`TASKS.md`](../TASKS.md)) has no data yet.
- **`AIController.CanMove` produced zero rows** across both captures while
  patched. Not called on these paths, or the patch did not take; unresolved.
- **`AddTurnRepositionLog` produced zero rows while `PrintTurnRepositionLog`
  fired 104 times.** Either the reposition log is printed empty, or the patch
  did not take. Both are one-line string appends, which is the IL2CPP
  body-folding trap in [`gotchas.md`](gotchas.md) `[fitted]`. The instance tag
  disambiguates it: a folded call now surfaces with its real owner in the tag.

## Instrument limits

- **One per-frame message can eat a whole cap.** `#) Execute Talents for
  Investigate Action 0` repeated 278, 240 and 106 times consecutively and took
  630 of the 800-line `AddTurnLog` budget. `Trace.cs` now collapses consecutive
  identical lines and a suppressed repeat does not count against the cap.
- **Trace printed no instance** before that same change, so two units' turns read
  identically. It now prefixes `[<UnitDisplayName> #<EntityId>]`, and a type with
  neither (`AIRepositionPlanner`) is named through its owner.
- **A tail capture is not a capture.** `Logs/PlayedLogA.txt` is the end of a
  session: `AddTurnLog` and `ReadyToEndTurn` had already hit their caps, so it
  holds only `LogThis`, `PrintTurnRepositionLog`, `PrePlanTurn` and `CanHunt`.
