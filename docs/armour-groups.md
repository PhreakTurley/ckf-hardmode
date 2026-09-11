# Splitting the normalised armour blocks back apart

The PL 1-20 retune (2026-08-26) collapsed `guard-standard` and `adaptive` onto one
ladder each: PL n -> tier n for every PowerGroup, each tier carrying
`max(curve, the best value any PG in the block had at that PL in the shipped game)`.
David approved that at the time and has flagged it for revisiting. This file is the
baseline for undoing it. Nothing else here is a recommendation.

`heavy` is **not** affected — all 25 of its PowerGroups walked one identical
pattern in the shipped game, so it lost no distinction. Neither did the other six
armour blocks, which were already one row per power level.

## What was lost

Two blocks shipped with their PowerGroups at **different offsets into one id run**.
That offset was how the designers said "this enemy is a weaker Guard". Normalising
erased it: every PG in the block now reads identically at all 20 levels.

## The baseline — shipped pointer runs, from `BepInEx/ckf-dump/MonsterTypeModel.csv`

Values come from `ckf-dump/ArmorModel.csv` at these ids. **Read them from the dump,
never from `ckf.hardmode.d/`** — see the "What 'current' means" note in
[`tuning-enemies.md`](tuning-enemies.md).

### `guard-standard` — 3 patterns, 24 PowerGroups

| n | PL 1-10 rows | PL 11-20 rows | PowerGroups |
|---|---|---|---|
| 12 | 22001 22001 22002 22003 22003 22004 22005 22005 22006 22007 | 22007 x10 | 1, 25000, 25002, 27000, 27060, 30000, 30040, 40000, 40100, 40150, 42000, 90000 |
| 10 | 22002 22002 22003 22004 22004 22005 22006 22007 22008 22009 | 22009 x10 | 3100, 3101, 3500, 3520, 3540, 3600, 4000, 4150, 12000, 12001 |
| 2 | 22000 22000 22001 22002 22003 22003 22004 22004 22005 22005 | 22005 x10 | 3000 Street Warrior, 12050 Free Gunner |

The 10-PG pattern is the **strongest**, not the most common. `BallisticArmorDegraded`
at PL 10 was 50 for it, 40 for the other two.

### `adaptive` — 4 patterns, 43 PowerGroups

| n | PL 1-10 rows | PL 11-20 rows | PowerGroups |
|---|---|---|---|
| 31 | 22202 22202 22203 22203 22204 22204 22205 22205 22206 22206 | 22206 x10 | 100, 160, 25001, 25003, 27030, 27040, 30020, 30060, 30120, 30140, 40002, 40003, 40101, 40130, 42040, 42060, 90001, 90002, 126001-126003, 127001, 127003, 127340, 127350, 127360, 127382-127384, 127392, 127393 |
| 9 | 22200 22201 22201 22202 22202 22203 22204 22204 22204 22205 | 22205 x10 | 3200, 3201, 3400, 3650, 3700, 3720, 3740, 4100, 12060 |
| 2 | 22200 22200 22201 22201 22202 22202 22203 22203 22204 22205 | 22205 x10 | 125001 Macha Stalker, 125002 Macha Blue |
| 1 | 22200 22200 22201 22201 22202 22202 22203 22203 22204 22206 | 22205/22206 alternating | 300 Guard Bladesman |

PG 300's PL 11-20 run alternates 22205 and 22206 rather than holding one row. Treat
it as noise unless it turns out to be deliberate.

## What the split costs

One pattern per block can keep the canonical run it already has
(`22000`-`22019`, `901000`-`901019`), so only the others need private rows:

- `guard-standard`: 2 private runs = **40 new rows**, 240 `ArmorTypeId` cells repointed
- `adaptive`: 3 private runs = **60 new rows**, 240 cells repointed

**100 new `ArmorModel` rows, 480 pointer cells.** `901080` onward is free — the
highest armour id in use is `901079`.

The runs must be *private*: the shipped runs overlap (guard-standard pattern 1's
PL 3 row **is** pattern 2's PL 1 row), which is why they cannot simply be left
pointing at the shipped ids and retuned in place.

## What to recompute from

Per pattern, feed formula (C) the pattern's own shipped PL 1-10 value sequence —
the dump values at that pattern's PL 1-10 rows above — instead of the block-wide
`max`-across-PowerGroups sequence the retune used. Everything else in §8 is
unchanged. The 25 single-power-level enemies still sit on `21999`, `22001`, `22200`
and `22202`; editing those shipped rows moves them, which §10 says is harmless.
