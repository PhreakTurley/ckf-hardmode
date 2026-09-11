# Reinforcements

Mid-mission arrivals, and the tables that decide them. **Read from the data;
none of it has been changed or tested in-game yet.**

## The mechanism

Reinforcements are cards in the alarm-escalation deck. `SecurityDeckCardModel`
holds 81 cards across 8 decks; **16 of them are reinforcement cards**:

| Card | `CardEventId` |
|---|---|
| Reinforcement Arriving! | 1 |
| Reinforcement Nearby! | 3 |
| Double Reinforcement! | 2 |
| Double Reinforcement Nearby! | 17 |

Which deck a room draws from comes from `MissionModel.SecurityDeckId`, with
`MissionRoomModel.SecurityDeckOverride` and `GameMissionRoomModel.SecurityDeckId`
per room.

`CardEventQty` is **0** on every reinforcement card, so the size of the arriving
squad is not in this table.

## Where the squad comes from

`MonsterGroupModel.Starting` splits the group table in two:

| `Starting` | Groups | Distinct slots |
|---|---|---|
| 1 (opening roster) | 75 | 56 have 1, 12 have 3, 7 have 4 |
| 0 (not the opening roster) | 97 | 68 have 1, **13 have 3**, 10 have 4 |

`DataDb.ReadMonsterGroupByFactionWithStarting(id, factionId, starting)` and
`ReadMonsterGroupByTypeWithStarting(...)` exist, so the game does query on that
flag.

**Thirteen `Starting = 0` groups have exactly three slots**, which matches packs
of three. Their ids follow a convention — the reinforcement group is the opening
group's id plus 50: 100 → 150, 600 → 650, 1100 → 1150, 1600 → 1650,
2000 → 2050, 12100 → 12150.

That is inference from shape and naming, not something observed firing. Confirm
by watching `ReadMonsterGroupMembersByGroup(<n>50, ...)` in the log when
reinforcements arrive — the list diagnostic prints the arguments.

## The levers

All ordinary rules on tables the engine already reaches.

**How often reinforcements come** — the 16 cards carry `CardWeight`,
`MinAlarmLevel`, `MinRoomTurn`, and `PreReq` / `ExclusiveReq`. Weights in use
are 1 to 12; every reinforcement card sits at weight 1, so they are rare draws
against cards weighted up to 12.

```json
{ "model": "SecurityDeckCardModel", "whereMin": { "SecurityDeckCardId": 101 },
  "whereMax": { "SecurityDeckCardId": 102 }, "set": { "CardWeight": 4 } }
```

**Who arrives** — `MonsterGroupMemberModel` for the `n50` groups, exactly as for
the opening roster: `WeightedRoll` to bias the pool, `MinPowerLevel` /
`MaxPowerLevel` to gate, and cloned rows to add members that were never there.
Cloning into these pools is proven (Run 40, on group 40000).

**Where the ceiling is.** Reinforcement pools gate lower than opening rosters:

```
MinPowerLevel across all groups          0, 2, 3, 4, 5, 6, 7, 8
MinPowerLevel in Starting = 0 groups     0, 3, 4, 5
```

So a reinforcement pool stops evolving at PL 5, five levels earlier than the
opening roster's 8, and fifteen short of the lifted cap. Re-spacing those gates
is an ordinary rule and needs no clone.

## Correction to the id policy

`EffectModel` rows `65001`-`65005` were listed among the 74 "referenced by
nothing" by an earlier unreferenced-row scan. They are
referenced — by `SecurityDeckCardModel.CardEffectId`. That scan did not check
this table. **Treat the unreferenced list as unproven** until something re-runs
it across every table that holds an `EffectId`.
