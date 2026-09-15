# Tuning enemies

Every gear family an enemy walks is 20 tiers, one per power level, and every
archetype already points at the right tier for its level. **The numbers in those
tiers are retuned — they are not the values the game shipped.** [measured]
In `ckf.hardmode.d/WeaponModel.csv` the bullpup rows run `BallisticDamage1`
316 -> 498 across PL 11-20 (23040-23049); in `ckf.hardmode.d/ArmorModel.csv`
the guard-standard rows run `BallisticArmorDegraded` 51 -> 62 over the same span
(22010-22019).

Further tuning is editing cells. This page is what the cells mean. The cells
live in the game's `BepInEx\config\ckf.hardmode.d\`, one file per table, and
that is the only copy; [`../overlays/README.md`](../overlays/README.md) covers
how the set was generated and the `_reference/` index.

| To change | Where |
|---|---|
| Enemy stats — HP, crit, AP, talents | `ckf.hardmode.d/MonsterTypeModel.csv`, one line per archetype row |
| What a gear tier is worth | `ckf.hardmode.d/ArmorModel.csv`, `ckf.hardmode.d/WeaponModel.csv` |
| Which tier an enemy carries | the `WeaponTypeId` / `ArmorTypeId` cells in `MonsterTypeModel.csv` |
| Stats no column exists for — damage %, armour, evasion | `EffectModel`, a rule in `ckf.hardmode.rules.json` |
| Who fills a roster slot, and how often | `MonsterGroupMemberModel`, a rule |

**Column names come from `D:\ckf-data-modding\sheets\raw\<Table>.csv`, written by the live
game.** `Aug21Sheets/` is stale and has already put a wrong id in a config.

Related: [`workflow.md`](workflow.md) for installing, dumping, validating and
in-game testing · [`gotchas.md`](gotchas.md) for the traps and dead ends ·
[`overlays.md`](overlays.md) for the CSV format ·
[`../overlays/_reference/player-vs-enemy-gear.md`](../overlays/_reference/player-vs-enemy-gear.md)
for which ids are enemy-facing · [`rule-engine.md`](rule-engine.md) for rule
syntax · [`cloning-rows.md`](cloning-rows.md) for inserting rows ·
the shipped ladders in `overlays/_reference/gear-tiers.csv` for how the game uses each
axis.

---

## 1. Stats — `ckf.hardmode.d/MonsterTypeModel.csv`

One line per archetype row, 2,427 of them, `_comment` naming the PowerGroup and
power level. `MonsterTypeModel` carries rows at every level 1-20, so nothing
here needs a clone.

### Columns that mislead

- **`Evasion` is dead** on this table — 0 on 2,424 of 2,427 rows. [measured]
  Enemy evasion comes from the `EffectId` stat block.
- **`ShotLimit` is gated by `ActionPoints`.** A shot costs AP, so `ShotLimit`
  above what the archetype's AP pays for buys nothing: 817 archetypes carry
  `ShotLimit` 3 at `ActionPoints` 40 against a weapon costing 20. [measured] The
  two axes move together or not at all. Only Hover Tank and H-Support scale AP
  in the shipped data, reaching 60 at PL 11.
- **`EffectId` is blank in the CSV wherever the shipped value is 0**, which
  means "no stat block". The current value is in the `_comment` as `eff:N`.
  Writing a literal 0 makes the validator read it as a pointer at a row that
  does not exist.
- **A column at 0 means the item has no such stat, not a small one.** Leave
  zeros alone.

### `EffectId`

`EffectId` is the widest lever for stats this table has no column for — damage,
armour, `DmgReduction`, `Evasion`, `OverwatchBreak`, `CoverBonus`. An effect row
is a **shared reference, not a consumable**, so pointing a PL 15+ archetype at a
row another archetype already uses costs nothing and does not alter the original
owner. 1,116 of 2,427 archetypes carry `EffectId` 0 — no stat block at all.
[measured]

**Unverified:** no monster-referenced `EffectModel` row sets any damage column
— all 25 leave `BallisticDamage`, `PhysicalDamage`, `PureDamage*` and
`FullAutoDamage` at 0. Whether those apply to a monster's attack has never been
tested. Values elsewhere in the table cluster at 3/5/10/15/20/25 against weapon
damage of 144-500, which reads as percent. [unverified]

## 2. Weapons — `ckf.hardmode.d/WeaponModel.csv`

Twenty blocks, twenty tiers each. `_reference/gear-tiers.csv` gives each
tier's id (its `ProvidedBy` column names the per-family file from before the
merge; in `WeaponModel.csv` the row's `_comment` names the block). The shipped
PL 1-10 shape each new tier continues is in `D:\ckf-data-modding\sheets\raw\WeaponModel.csv`,
which is the ground truth for it.

The columns that carry a weapon: `BallisticDamage1`, `PhysicalDamage1`,
`PureDamage1`, `Accuracy1`, `ActionPoints1`, `ArmorCritRate1`, `RecoilRate1`,
`ShotVolume`, `FAShots`, `MaxRange`. **Always write the suffixed ones** — the
unsuffixed aliases (`BallisticDamage`, `Accuracy`, …) are read-only, and a write
to them is taken and discarded.

**Shipped slope:** the game's own PL 1-10 ladders rise about **1.6x** in damage
— 1.36x on the Guard Rifle, 2.23x on the WB Revolver. [fitted]

`WeaponModel.PowerLevel` is cosmetic. A tier's position is its id and the
pointer in `MonsterTypeModel.csv`.

## 3. Armour — `ckf.hardmode.d/ArmorModel.csv`

Nine blocks, same shape.

**Armour is the percentage of damage prevented, and the engine hard-caps damage
reduction at 95%.** Multiplying the number is therefore wrong: 50 -> 75 halves
the damage taken and so does 80 -> 90, so a plain multiply below the cap
improves a high-armour family far faster than a low one and runs the top of a
ladder into near-immunity.

Work in the gap instead:

```
new = 100 - (100 - old) * factor
```

A factor of 0.65 turns 50 into 67.5, and the damage that tier lets through drops
from 50% to 32.5%. Diminishing returns fall out of the formula: 80 -> 87,
85 -> 90.

Above the 95% cap the extra buys resistance to *degradation*, not reduction —
that has no ceiling.

Two more things to know before typing a number:

- **A column at 0 means the item has no such stat, not a small one.** Guard
  Standard carries `BallisticArmor` 0 and only its `*Degraded` values mean
  anything. Leave zeros alone.
- **`MaxArmorPoints` runs 1 to 4 across an entire family.** [measured] There is
  no room for a per-level slope; decide each tier's value by hand.

`ArmorModel.PowerLevel` is cosmetic — the developers cloned the last three rows
to make Lvl8-10 and did not update it.

## 4. Roster pools — a rule, not a cell

`MonsterGroupMemberModel` fills each slot from a weighted pool.
`MonsterGroupMemberId` is the key; **`MonsterType` holds a PowerGroupId**, not a
MonsterTypeId. Spawning keys off the scaled mission power level, so every gate
is live above the old cap.

```json
{ "model": "MonsterGroupMemberModel", "where": { "MonsterGroupMemberId": 31 },
  "set": { "WeightedRoll": 1 } }
```

Two levers need no clone:

- **`WeightedRoll`** biases the pool at no power-level cost. Shipped values are
  1, 2, 4, 5 and 10.
- **`MinPowerLevel` / `MaxPowerLevel`** decide when an archetype enters or
  leaves. No shipped entry gates above PL 8. [measured] Re-spacing those gates
  across 1-20 changes composition and inserts nothing, but it redistributes
  rather than adds: PL 4-10 gets what PL 11-20 loses.

Adding members is a clone — ids run 1-570 with no gaps, so use the reserved
range, and set the gates explicitly in `as` rather than inheriting them. See
[`cloning-rows.md`](cloning-rows.md).

---

## Reading `TraceRules` output

`[ModelRules] TraceRules = 12` prints what moved:

```
  trace #311 MonsterTypeModel[19] PL 15: CritRate 30 -> 41   [Guard crit slope]
RowClone: built  ArmorModel ArmorId 22017 from 22009 — ... 50 -> 80
RowClone: served ArmorModel ArmorId 22017 from ReadArmor
```

- `built` **without** `served` means the row exists but nothing is reaching it.
- **Silence means nothing asked.** Clones materialise lazily, so only the tiers
  a mission actually uses get built.

Put `TraceRules` back to 0 afterwards. To assert exact values rather than
eyeball them, add rows to `ckf.hardmode.selfcheck.csv` and turn
`[SelfCheck] Enabled` on for that launch — [`workflow.md`](workflow.md).

Installing, validating and which in-game action tests what are in
[`workflow.md`](workflow.md). The traps — black screens, dumper interference,
read-only columns — are in [`gotchas.md`](gotchas.md).

## Still open

- **Reinforcements.** Mid-mission arrivals are alarm-deck cards drawing
  `Starting = 0` monster groups — [`reinforcements.md`](reinforcements.md). Read
  from the data, never observed firing. [unverified]
- **Talent bands** stop at "PL 9+". `MonsterTalentModel` is hooked for cloning
  but has never been exercised — the last untried scaling axis.
- **`EffectModel` damage columns on monsters**, as above. [unverified]
