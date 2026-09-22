# The rule engine

How the Hard Mode row-edit engine selects rows and rewrites them: rule JSON
syntax, operations, curves, clone syntax, and the rule index. The CSV overlay
dialect that compiles to these rules is in [`overlays.md`](overlays.md); which
id to clone into is in [`cloning-rows.md`](cloning-rows.md).

A Harmony postfix on each `GetRow<X>Model` materializer (`ModelRules.AfterGetRow`)
sees a row after the game has built it and rewrites columns before the game uses
it. Retuning is a text edit and a relaunch, with no rebuild.

| Need | Use |
|---|---|
| Explicit values for named rows | [`overlays.md`](overlays.md) |
| A broad selector or curve | JSON syntax on this page |
| A new id | Clone syntax here, then the id policy in [`cloning-rows.md`](cloning-rows.md) |
| A table or key name | [`tables.md`](tables.md) and the current dump |

## Where rules come from

The 4.0 layout has no main rules file. Every rule comes from
`BepInEx/config/ckf.hardmode.d/` (`Overlays.Load`):

| File in `ckf.hardmode.d/` | Read as |
|---|---|
| `<Table>[.anything].csv` / `.tsv` | an overlay: one rule per line ([`overlays.md`](overlays.md)) |
| a lever sheet (`gear-classes.csv`, `cyberweapons-*.csv`, `implants-slotNN.csv`, `consumables-*.csv`) | expanded into rules by its own expander (`GearClasses`, `Cyberweapons`, `Implants`, `Consumables`) |
| one of the ten settings files (`modelrules.json`, `fatigue.json`, … `implants-global.json`) | not rules; `ConfigDoc` reads it (`ConfigDoc.OwnsFile`) |
| any other `.json` | a rules file in the JSON shape below (e.g. `MissionPowerLevelModel.generated.json`) |

Subfolders are not read. Files are walked in ordinal filename order, and a file
whose `[Slices]` toggle in `ckf.hardmode.cfg` is `false` is never opened
(`Slices.VerdictForOverlay`). A file no slice claims is always read.

`BepInEx/config/ckf.hardmode.rules.json` is still read if it exists, before the
directory, and its presence is logged as an Error: its rules apply before every
sheet, so a non-`set` rule in it stacks on top of the sheet that replaced it
(`Plugin.Load`, `ModelRules.LoadRules`). Nothing creates this file.

The engine is gated by `[Slices] ModelRules`. Its settings (`traceRules`,
`probeWritableColumns`, `probeTables`, `probeOutput`) are in
`ckf.hardmode.d/modelrules.json`, declared in
[`../schema/modelrules.schema.json`](../schema/modelrules.schema.json).

Commands for validating and reading the log are in [`workflow.md`](workflow.md).
Traps (`Id` is not the key, alias columns that discard writes, `multiply`
compounding on `Game*` models) are in [`gotchas.md`](gotchas.md).

## Write a JSON rule

```json
{
  "rules": [
    {
      "comment": "Free text. Ignored by the engine.",
      "model": "WeaponModel",
      "where":    { "WeaponId": 20000 },
      "whereMin": { "PowerLevel": 5 },
      "whereMax": { "PowerLevel": 9 },
      "set":      { "Accuracy1": 60 },
      "multiply": { "BallisticDamage1": 1.25 },
      "add":      { "ActionPoints1": 5 },
      "clampMin": { "Accuracy1": 40 },
      "clampMax": { "Accuracy1": 95 }
    }
  ]
}
```

- `//` comments and trailing commas are allowed.
- `"model": "Weapon"` works: `Model` is appended if missing (case-insensitive).
- A rule with no `model` is dropped with a warning.
- A property the engine does not know (`"mulitply"`) is named in a warning and
  ignored. A rule with no operation at all is warned about
  (`ModelRules.WarnIfEmpty`).

## Select rows

| Key | Meaning |
|---|---|
| `where` | Exact match. Numbers compare within 1e-9. Strings compare ordinal, case-sensitive, against the column rendered in invariant culture. Booleans compare as booleans. |
| `whereMin` | Numeric `>=`. |
| `whereMax` | Numeric `<=`. |

All selectors must pass. Omit them all to match every row.

- A selector naming a column that does not exist never matches; warned once per
  table and column.
- A numeric selector on a non-numeric column never matches; warned once.
- A `where` value that is `null`, an array or an object matches nothing; warned
  once.

## Apply operations in a fixed order

Applied in this order, always: `set` → `multiply` → `add` → `clampMin` →
`clampMax` (`ModelRules.Apply`). `clampMax` runs last, so it wins when the two
clamps disagree.

`set` takes a number, string, boolean or curve. The other four take a number or
a curve.

| Case | Behaviour |
|---|---|
| Integer column | Result rounds to nearest, halves to even: `25 x 1.5` stores `38` (`Accessors.SetNumber`). |
| Negative value | `multiply` scales it as expected: `-50 x 1.3 = -65`. |
| String given to `set` on a numeric column | Parsed as an invariant number; a non-number is warned about and not written. |
| Unknown column | Warned once; the rule does nothing to it. |
| Column with no setter | Warned once; the rule does nothing to it. |
| Write rejected (overflow, wrong shape) | Warned once per table, column and reason; the column is unchanged. |
| Model with no materializer | Named at startup: `ModelRules: no materializer for X — rules targeting those will never run.` |

A column can also have a setter that takes the value and discards it. A rule
against one looks applied and changes nothing. `probeWritableColumns: true` in
`modelrules.json` finds them in one launch; see
[`../mods/CKFHardMode/README.md`](../mods/CKFHardMode/README.md#when-a-rule-looks-applied-and-changes-nothing).

---

## Curves

Anywhere a number is accepted, a curve object can go instead:

```json
{ "perLevelAbove": [10, 2.2] }
```

"2.2 per level above 10." The value is
`base + step * max(0, level - threshold)`, then clamped by `min`/`max`
(`ModelRules.Evaluate`).

| Field | Meaning |
|---|---|
| `perLevelAbove` | `[threshold, step]`. Required. |
| `base` | Value at and below the threshold. Defaults to 0 on `add` and 1 on `multiply`. Required on `set`, `clampMin` and `clampMax`; a curve there without one is skipped with a warning. |
| `levelColumn` | Column read as "level". Default `PowerLevel`. |
| `geometric` | `true`: `base * step^n` instead of `base + step*n`. |
| `every` | Advance one step per N levels. Values below 1 are replaced by 1 with a warning. |
| `min` / `max` | Clamp the computed value. |
| `gapFrom` | `multiply` and `set` only, with different meanings (below). Ignored with a warning elsewhere. |
| `linearAbove`, `linearPerLevel` | `multiply` with `gapFrom` only, and both together; otherwise ignored with a warning. |

### `levelColumn`

A curve reads the column on the row being edited. `perLevelAbove` on a
`WeaponModel` row keys off the weapon's own `PowerLevel`, not the level of the
enemy carrying it, so one row cannot vary by holder. Scaling gear by enemy level
takes one row per tier and a pointer per archetype
([`cloning-rows.md`](cloning-rows.md)).

Any numeric column works. On armour the id is the ladder position and
`PowerLevel` is cosmetic, so a whole-family rule uses
`"levelColumn": "ArmorId"` with the family's first id as threshold. A
`levelColumn` that does not exist makes the curve flat at `base`, with one
warning.

### Choose linear or geometric growth

`base + step*n` moves a value in equal amounts; `base * step^n` moves it by a
proportion. Percentages want the second: "damage taken falls 4.5% of itself per
level" cannot be a linear slope without stalling or overshooting.

### Step at fixed intervals

Counts completed intervals: with step 1 and `every: 5`, the value is +1 at the
fifth level above the threshold, not +5. Use it for small integer columns such as
`MaxArmorPoints`, where a per-level slope is decided entirely by rounding.

### `gapFrom`

For percentage columns such as armour, where what matters is what gets through:
50 → 75 halves damage taken, and so does 80 → 90.

On `multiply`, `gapFrom` scales the gap instead of the value:

```
new = gapFrom - (gapFrom - old) * factor
```

A falling factor raises the value. Per row (`ModelRules.Arith`):

- a column at or below 0 is left alone (0 means the stat is absent);
- a row already at or above `gapFrom` is left alone;
- a factor at or below 0 is clamped to 0.01, with a warning.

`linearAbove` / `linearPerLevel` add a second regime: at or above
`linearAbove` the column is multiplied outright by
`1 + linearPerLevel * max(0, level - threshold)`. For armour that split sits at
the engine's 95% damage-reduction cap.

On `set`, `gapFrom` means the curve computed the gap and the column stores
`gapFrom - value`: write the ladder as damage taken, store armour.

### Examples

```json
{ "model": "MonsterTypeModel", "whereMin": { "PowerLevel": 11 },
  "add": { "CritRate": { "perLevelAbove": [10, 2.2] } } }
```

```json
{ "model": "MonsterTypeModel", "whereMin": { "PowerLevel": 11 },
  "set": { "WeaponTypeId": { "perLevelAbove": [10, 1], "base": 20009 } } }
```
Walks a contiguous block of ids, one per level.

```json
{ "model": "ArmorModel", "whereMin": { "ArmorId": 21999 }, "whereMax": { "ArmorId": 22009 },
  "set": { "BallisticArmorDegraded": { "perLevelAbove": [21999, 0.955], "base": 78,
                                       "geometric": true, "gapFrom": 100,
                                       "levelColumn": "ArmorId" } } }
```

```json
{ "model": "ArmorModel", "whereMin": { "ArmorId": 22010 },
  "multiply": { "BallisticArmor": { "perLevelAbove": [10, -0.035], "base": 1,
                                    "gapFrom": 100, "linearAbove": 95,
                                    "linearPerLevel": 0.06 } },
  "add": { "MaxArmorPoints": { "perLevelAbove": [10, 1], "every": 4, "base": 0 } } }
```

---

## Clone syntax

A rule with a `clone` field inserts a copy of one row instead of editing rows
(`RowClone`).

```json
{ "comment": "Guard Rifle tier 11: tier 10 plus 15%.",
  "model": "WeaponModel",
  "clone": { "WeaponId": 20009 },
  "as":    { "WeaponId": 20020 },
  "multiply": { "BallisticDamage1": 1.15, "BallisticDamage2": 1.15 } }
```

- `clone` names exactly one column and a numeric id: the source row. The column
  must be the one the table's by-id reader looks rows up by (`WeaponId`,
  `ArmorId`, `MonsterTypeId`, `EffectId`). If the row the reader returns does
  not carry that id, the clone is refused with an Error when it is built.
- `as` is required and must set the same id column to the new id. Its other
  columns are written literally, before the operations.
- `set` / `multiply` / `add` / `clampMin` / `clampMax` then apply to the copy.
- `where` / `whereMin` / `whereMax` are ignored with a warning.
- A clone rule never edits existing rows.

The copy is the source row as the game materializes it, so it inherits whatever
other rules did to the source, then gets `as` and its own operations.

In the overlay dialect a clone is a line with a `_clone` cell
([`overlays.md`](overlays.md)).

### Serve clones through readers

Rules reach rows through `GetRow*Model`, which only sees rows the game chose to
read. Clones are served by hooking the table's readers instead: by-id readers on
every database that declares one, and filtered list readers. Which readers
exist per table, and which paths are proven, is in
[`cloning-rows.md`](cloning-rows.md#serving-paths).

A cloned row never appears in a CKF Data Dump sweep: the dumper captures rows in
its own `GetRow*` postfix, and a clone is appended after that. The log confirms a
clone: `RowClone: built ...`, then `RowClone: served ...`.

`serveOn` decides which filtered lists a clone joins:

| `serveOn` | Behaviour |
|---|---|
| `auto` (default) | The list already contains the source row, and the reader's arguments pass the clone's own gate columns. |
| `provenance` | Source-row test only. |
| `always` | Every list for that table. |
| `never` | By-id only, for a row that exists only to be pointed at. |

Any other value is warned about and treated as `auto`. The gate map
(`RowClone.GatesPass`) is in [`cloning-rows.md`](cloning-rows.md#spawn-pools).

Refusals, all logged:

- `Game*` models cannot be cloned; those rules are ignored with a warning.
- An `as` id the table already holds is refused (Error).
- Two clone rules inserting the same id: the second is ignored (Error).
- A `set` that writes an id of a clone that was refused, or an id at or above
  `900000` that no clone declares, is an Error at load
  (`RowClone.WarnAboutDanglingReferences`).

Reader hooks are installed only when at least one clone rule exists.

---

## Indexing

Each model gets a plan (`RulePlan.cs`): one column chosen as index, a bucket of
rules per value, and a list of rules that could not be indexed. Per row that is
one number read and one dictionary lookup. Bucket and unindexed list are both in
load order and are merge-walked on the rule's position, so a broad multiply still
runs before a narrow clamp that follows it.

The index column is chosen, not configured. A model is indexed when it has at
least 8 rules and at least half of them select one exact integer column. Every
overlay edit line has that shape. Range selectors, string selectors and
fractional numbers are not indexable.

The load log prints the plan per hooked model:

```
  EffectModel: 133 rule(s) indexed on EffectId — 133 value(s), worst bucket 1, 0 unindexed
  RuleModel: 2 rule(s), no index (every row tests all of them)
```

"no index" is correct for a handful of rules. It is worth acting on only when a
table has hundreds of rules and still reports it.

Columns are read and written through delegates compiled at load
(`Accessors.cs`), always on. The numeric conversion is the same
round-to-nearest, halves-to-even as `Convert.ChangeType`.

Only tables some rule targets are hooked, since each hook is a postfix on the
game's per-row path.

## Tracing

`traceRules: N` in `modelrules.json` logs the first N rows each rule touches:

```
  trace #311 MonsterTypeModel[19] PL 15: CritRate 30 -> 41   [Guard crit slope]
```

`matched, nothing changed` means the rule found the row and no value moved: an
alias column, or a clamp already satisfied. Set it back to 0 afterwards.

---

## Reuse these worked examples

Whole table, no selector: every weapon 25% harder, both firing modes.

```json
{ "model": "WeaponModel",
  "multiply": { "BallisticDamage1": 1.25, "BallisticDamage2": 1.25,
                "PureDamage1": 1.25, "PureDamage2": 1.25 } }
```

Stacking, then a floor: a general slope, a steeper one above a threshold, a
clamp that runs last.

```json
{ "model": "CharacterLevelModel", "multiply": { "Xp": 2.0 } }
{ "model": "CharacterLevelModel", "whereMin": { "Level": 20 },
  "multiply": { "Xp": 1.5 } }
{ "model": "CharacterLevelModel", "multiply": { "Job": 0.75, "Talent": 0.75 },
  "clampMin": { "Job": 1, "Talent": 1 } }
```

A string selector: `RuleModel` groups constants under one `GroupId`.

```json
{ "model": "RuleModel", "where": { "GroupId": "HEAT" },
  "multiply": { "Value": 1.5 } }
```

Player-only or enemy-only weapon rules cannot use an id band; see
[`player-vs-enemy-gear.md`](../overlays/_reference/player-vs-enemy-gear.md).

## Validate a rule set

```text
python scripts\validate_rules.py --game "<game root>" --dump "<dump dir>" --enabled-set
```

An `ERROR` is a launch blocker. Warnings about unknown or read-only columns mean
the requested write will not take effect. If static validation passes but a row
does not move, use `traceRules` or the writable-column probe described in
[`../mods/CKFHardMode/README.md`](../mods/CKFHardMode/README.md), then restore
the diagnostic setting. The complete gate order is in
[`workflow.md`](workflow.md).

## Related

- [`overlays.md`](overlays.md)
- [`cloning-rows.md`](cloning-rows.md)
- [`tables.md`](tables.md)
- [`gotchas.md`](gotchas.md)
