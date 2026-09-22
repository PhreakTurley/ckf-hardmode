# Reinforcements

Use this page to find the shipped reinforcement-card rows and candidate roster
pools. The table shapes are measured; the runtime selection path has not been
observed in game.

## Escalation-card entry points

Reinforcements are cards in the alarm-escalation deck. `SecurityDeckCardModel`
holds 81 cards across 8 decks, 16 of them reinforcement cards [measured]:

| Card | `CardEventId` |
|---|---|
| Reinforcement Arriving! | 1 |
| Double Reinforcement! | 2 |
| Reinforcement Nearby! | 3 |
| Double Reinforcement Nearby! | 17 |

A room's deck comes from `MissionModel.SecurityDeckId`, overridden per room by
`MissionRoomModel.SecurityDeckOverride` and `GameMissionRoomModel.SecurityDeckId`.

`CardEventQty` is 0 on every reinforcement card, so squad size is not in this
table.

`SecurityDeckCardModel.CardEffectId` references `EffectModel` rows
`65001`–`65005`.

## Candidate reinforcement pools

`MonsterGroupModel.Starting` splits the group table [measured]:

| `Starting` | Groups | Slots per group |
|---|---|---|
| 1 (opening roster) | 75 | 56 have 1, 12 have 3, 7 have 4 |
| 0 (not the opening roster) | 97 | 68 have 1, 13 have 3, 10 have 4 |

`DataDb.ReadMonsterGroupByFactionWithStarting(id, factionId, starting)` and
`ReadMonsterGroupByTypeWithStarting(...)` exist, so the game queries on that
flag.

[unverified] Thirteen three-slot `Starting = 0` groups match packs of three, and
their ids follow the opening group's id plus 50: 100 → 150, 600 → 650, 1100 →
1150, 1600 → 1650, 2000 → 2050, 12100 → 12150. This association comes from
table shape and naming, not a captured runtime lookup.

To confirm, watch for `ReadMonsterGroupMembersByGroup(<n>50, ...)` when
reinforcements arrive. `RowClone` prints each distinct call shape of a filtered
reader as `  RowClone list: <reader>(<args>) returned N row(s)`, but only for a
table that has at least one clone rule, since that is when the reader is hooked.

## Relevant rule-engine levers

All of these are ordinary rules on tables the engine already reaches.

**How often reinforcements come.** The 16 cards carry `CardWeight`,
`MinAlarmLevel`, `MinRoomTurn`, and `PreReq` / `ExclusiveReq`. Weights in use run
1 to 12, and every reinforcement card is at 1 [measured].

```json
{ "model": "SecurityDeckCardModel", "whereMin": { "SecurityDeckCardId": 101 },
  "whereMax": { "SecurityDeckCardId": 102 }, "set": { "CardWeight": 4 } }
```

**Who arrives.** `MonsterGroupMemberModel` for the `n50` groups, as for opening
rosters: `WeightedRoll` to bias, `MinPowerLevel` / `MaxPowerLevel` to gate, and
cloned rows to add members. Cloning into these pools is proven on group 40000
([`cloning-rows.md`](cloning-rows.md#spawn-pools)).

**Where the pools stop evolving.** Reinforcement pools gate lower than opening
rosters [measured]:

```
MinPowerLevel across all groups          0, 2, 3, 4, 5, 6, 7, 8
MinPowerLevel in Starting = 0 groups     0, 3, 4, 5
```

So a reinforcement pool stops changing at PL 5, three levels before the opening
rosters' 8. Re-spacing those gates needs no clone.

## Open questions

- [unverified] Which `Starting = 0` group a reinforcement card selects at
  runtime.
- [unverified] Where reinforcement squad size is chosen; `CardEventQty` is zero
  on every reinforcement card.

## Related

- [`tuning-enemies.md`](tuning-enemies.md#roster-pools-monstergroupmembermodel)
- [`tables.md`](tables.md)
