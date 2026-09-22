# Armour-group split reference

Use this reference when changing how enemy armour PowerGroups share ladders. It
records the shipped pointer patterns and the row/pointer cost of restoring those
patterns after normalisation. It is not a tuning recommendation.

The PL 1–20 armour retune collapsed each of those two blocks onto one ladder: PL
n → tier n for every PowerGroup, each tier carrying the larger of the curve value
and the best value any PowerGroup in the block had at that PL in the shipped
game.

`heavy` lost nothing: all 25 of its PowerGroups walked one identical pattern in
the shipped game. Neither did the other six armour blocks, which were already one
row per power level.

## What normalisation removed

Two blocks shipped with their PowerGroups at different offsets into one id run.
The offset was how the designers made one enemy a weaker Guard than another.
After normalising, every PowerGroup in the block reads identically at all 20
levels.

## Shipped pointer runs

From the dump's `MonsterTypeModel.csv` [measured]. Values at these ids come from
the dump's `ArmorModel.csv`. Read them from the dump, not from
`ckf.hardmode.d/ArmorModel.csv`, which holds retuned values for the shipped ids.

### `guard-standard`: 3 patterns, 24 PowerGroups

| n | PL 1–10 rows | PL 11–20 rows | PowerGroups |
|---|---|---|---|
| 12 | 22001 22001 22002 22003 22003 22004 22005 22005 22006 22007 | 22007 x10 | 1, 25000, 25002, 27000, 27060, 30000, 30040, 40000, 40100, 40150, 42000, 90000 |
| 10 | 22002 22002 22003 22004 22004 22005 22006 22007 22008 22009 | 22009 x10 | 3100, 3101, 3500, 3520, 3540, 3600, 4000, 4150, 12000, 12001 |
| 2 | 22000 22000 22001 22002 22003 22003 22004 22004 22005 22005 | 22005 x10 | 3000 Street Warrior, 12050 Free Gunner |

The 10-PowerGroup pattern is the strongest, not the most common:
`BallisticArmorDegraded` at PL 10 was 50 for it and 40 for the other two.

### `adaptive`: 4 patterns, 43 PowerGroups

| n | PL 1–10 rows | PL 11–20 rows | PowerGroups |
|---|---|---|---|
| 31 | 22202 22202 22203 22203 22204 22204 22205 22205 22206 22206 | 22206 x10 | 100, 160, 25001, 25003, 27030, 27040, 30020, 30060, 30120, 30140, 40002, 40003, 40101, 40130, 42040, 42060, 90001, 90002, 126001–126003, 127001, 127003, 127340, 127350, 127360, 127382–127384, 127392, 127393 |
| 9 | 22200 22201 22201 22202 22202 22203 22204 22204 22204 22205 | 22205 x10 | 3200, 3201, 3400, 3650, 3700, 3720, 3740, 4100, 12060 |
| 2 | 22200 22200 22201 22201 22202 22202 22203 22203 22204 22205 | 22205 x10 | 125001 Macha Stalker, 125002 Macha Blue |
| 1 | 22200 22200 22201 22201 22202 22202 22203 22203 22204 22206 | 22205/22206 alternating | 300 Guard Bladesman |

PowerGroup 300's PL 11–20 run alternates 22205 and 22206.

## What a split costs

One pattern per block keeps the canonical run it has (`22000`–`22019` for
`guard-standard`, `901000`–`901019` for `adaptive`); the others need private
runs:

- `guard-standard`: 2 private runs = 40 new rows, 240 `ArmorTypeId` cells
  repointed.
- `adaptive`: 3 private runs = 60 new rows, 240 cells repointed.

Total: 100 new `ArmorModel` rows and 480 pointer cells. No id range is reserved
here; inspect the live overlay before assigning ids.

The runs must be private: the shipped runs overlap (guard-standard pattern 1's
PL 3 row is pattern 2's PL 1 row), so they cannot be left pointing at shipped
ids and retuned in place.

## Recompute inputs

For each pattern, feed the retune curve that pattern's own shipped PL 1–10 value
sequence (the dump values at its PL 1–10 rows above) instead of the block-wide
maximum across PowerGroups.

The 25 single-power-level enemies still point at shipped rows including
`21999`, `22001`, `22200` and `22202`; editing those rows moves them
(`overlays/_reference/gear-blocks.md`, "The 25 PowerGroups with no ladder").

## Open questions

- [unverified] Whether PowerGroup 300's alternating PL 11–20 pointers are
  deliberate or incidental.

## Related

- [`tuning-enemies.md`](tuning-enemies.md#armour)
- [`cloning-rows.md`](cloning-rows.md)
