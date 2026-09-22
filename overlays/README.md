# Enemy scaling overlay set: reference and generator

Local reference material for the PL 1-20 enemy gear set, and how that set was
generated. The set itself is not in this folder. Row format:
[`../docs/overlays.md`](../docs/overlays.md). What the cells mean:
[`../docs/tuning-enemies.md`](../docs/tuning-enemies.md).

Start with `_reference/powergroups.csv` when you have an enemy,
`_reference/gear-tiers.csv` when you have a block and power level, and
[`_reference/gear-blocks.md`](_reference/gear-blocks.md) when you need the id
policy for a whole ladder. Do not copy anything from this folder into the game.

## Edit only the live set

The only copy is the live `BepInEx\config\ckf.hardmode.d\`:
`ArmorModel.csv`, `WeaponModel.csv` and `MonsterTypeModel.csv`, one file per
table. `scripts/make_release.py` ships those three (`CONFIG_FILES`). Tune them
in place, in the config editor or by hand; nothing in this folder is copied into
the game.

## Choose the right reference

| File | Is |
|---|---|
| `_reference/gear-blocks.md` | every gear block: its PL 1-10 and PL 11-20 id runs, shipped vs new tiers, PowerGroup count, notes |
| `_reference/gear-tiers.csv` | the tier index: one row per (block, power level) with `Table, Block, PowerLevel, Id, Provenance, ProvidedBy, Variants, PowerGroups` |
| `_reference/powergroups.csv` | every PowerGroup to its armour and weapon block |
| `_reference/pointer-changes.csv` | every gear pointer the set moves, shipped vs new |
| `_reference/player-vs-enemy-gear.md` | how player and enemy gear rows are told apart, and the id ranges for each. The canonical copy of that split |

`_reference/` is not loaded. `Overlays.Load` reads only `.csv`, `.tsv` and
`.json` files in `ckf.hardmode.d` itself, and this folder is not in the game
directory anyway.

## Understand the generated set

- Every gear family an enemy walks is a block of 20 tiers, one per power level:
  9 armour blocks and 20 weapon blocks (`_reference/gear-blocks.md`). Enemies
  that exist at only one power level (story guards, target dummies, VIPs) keep
  their shipped pointers.
- `MonsterTypeModel.csv` already carries the pointer for each archetype row, so
  pointing an enemy at its tier needs no lookup. `gear-tiers.csv` answers the
  reverse question (which id holds a given tier's numbers), and
  `powergroups.csv` maps an enemy to its blocks.
- Tiers the game does not ship are clone lines: a `_clone` column naming the
  source row (`Overlays.cs`). A clone line states every column its block's edit
  lines state, so a tier inherits no tuned number from its source. It still
  inherits the columns no CSV names (`ArmorClass`, the name, and on weapons
  `WeaponClass`, `ModeType`, `AngleFire`, `SpecialRule`, `PrecisionRule`, VFX).
- Each block's PL 10 row is both an edited row and the clone source for PL
  11-20. If you edit such a row, re-record any self-check expectation for the
  tiers cloned from it.
- A file's line count is not its block's size: shipped tiers are edit lines or
  absent, new tiers are clone lines.

Two shipped pointer breaks the set repairs (`scripts/make_enemy_overlays.py`,
block notes):

- `Hover Tank` PL 1 pointed at `ArmorTypeId` 22510, which does not exist.
  PL 1-10 now use 22511-22520.
- `J4 FireCOM` and `J3 Extinguisher` PL 11-20 pointed at `WeaponTypeId`
  23140-23149, none of which existed. The set creates them.

## Read overlay cells

- A cell is a plain number. The operator is in the header: `Col` set, `Col*`
  multiply, `Col+` add, `Col>` clampMin, `Col<` clampMax.
- An empty cell means "leave alone". Clearing a cell backs out a change.

Full spec: [`../docs/overlays.md`](../docs/overlays.md).

## Regenerate only into an empty folder

`scripts/make_enemy_overlays.py` builds the set from a dump and a 3.x-style
`ckf.hardmode.rules.json` that still contains the enemy-gear rules. The 4.0
layout has no rules file, so this is a reset tool: it discards every edit made
since, and needs that older rules file as input.

```
python scripts/make_enemy_overlays.py --dump "<dump dir>" --rules "<rules.json with enemy-gear rules>" --out "<empty folder>"
python scripts/merge_overlays.py --write --src "<that folder>" --out "<merged dir>"
```

All three flags of `make_enemy_overlays.py` are required. `--out` receives
per-family files (`ArmorModel.<block>.csv`, `ArmorModel.<block>-base.csv`,
`WeaponModel.<block>.csv`, `WeaponModel.player-optical.csv`,
`MonsterTypeModel.csv`), a rewritten `ckf.hardmode.rules.json` with the gear
rules removed, a `README.md`, and `_reference/` (`gear-tiers.csv`,
`powergroups.csv`, `gear-blocks.md`, `pointer-changes.csv`,
`rules-removed.json`, `rules-original.json`). It overwrites what is there, so
give it an empty folder. `merge_overlays.py` merges the per-family files into
one file per table, the shape of the live set.

The generator leaves any gear rule whose comment starts with `PLAYER` in the
rules file and never restates it in a CSV. It refuses to write unless every
block tier resolves.

Treat generated output as a candidate, not as the live configuration. Merge it
into a separate directory, compare it with the current live files, and run the
validator from [`../docs/workflow.md`](../docs/workflow.md) before any reviewed
installation step.

## Related

- [`../docs/tuning-enemies.md`](../docs/tuning-enemies.md)
- [`../docs/cloning-rows.md`](../docs/cloning-rows.md)
- [`../docs/overlays.md`](../docs/overlays.md)
