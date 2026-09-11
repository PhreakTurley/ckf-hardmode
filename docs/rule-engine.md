# The rule engine

`BepInEx/config/ckf.hardmode.rules.json` applies declarative edits to database
rows as the game reads them.

**For stating what a lot of specific rows' numbers are — the bulk retuning job
— use a per-table overlay instead: [`overlays.md`](overlays.md).** This file is
for rules that state a *shape*: selectors, curves, and clone syntax. Overlays
compile to rules and everything here applies to them, but the syntax is one CSV
line per row rather than a JSON object. A Harmony postfix on each `GetRow<X>Model`
materializer sees the row after the game has decrypted and built it, and
rewrites fields before the game looks at them.

Created on first run with four example rules, which **every later launch loads
like any other rule** and which all do nothing — placeholder columns, and
selectors on `Id`. Replace all four.

The install/dump/edit/test loop, reading the log, and the `validate_rules.py` /
`check_run.py` command lines are in [`workflow.md`](workflow.md). The things
that do not work and must not be done are in [`gotchas.md`](gotchas.md) — read
it before writing a first rule; `Id` is not the key, several columns silently
ignore writes, and `multiply` compounds on `Game*` models.

## Shape

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

`//` comments and trailing commas are allowed. `"model": "Weapon"` works —
`Model` is appended if missing.

## Selectors

| Key | Meaning |
|---|---|
| `where` | Exact match. Numbers compare within 1e-9; **strings are case-sensitive ordinal**; booleans compare as booleans. |
| `whereMin` | Numeric `>=`. |
| `whereMax` | Numeric `<=`. |

All selectors must pass. Omit them all to match every row in the table.

A selector naming a column that does not exist **can never match**, so the rule
silently stops working — the engine warns once per bad column name per table.

A `where` value that is neither a number, a string nor a boolean — `null`, an
array, an object — matches **nothing**, and says so once. It used to pass
silently, which turned one malformed selector into a whole-table edit.

## Operations

Applied in this order, always:
**`set` → `multiply` → `add` → `clampMin` → `clampMax`.**

Every one of them takes either a plain value or a **curve**. `clampMax` running
last means it wins over `clampMin` if the two disagree.

| Behaviour | Note |
|---|---|
| Integer columns | Results convert back to the column's type, rounded to nearest, halves to even — not truncated. `25 x 1.5` gives `38`. |
| Negative values | `multiply` works as expected: `-50 x 1.3 = -65`. |
| Unknown column | One warning, rule does nothing. |
| Read-only column | One warning, rule does nothing. |
| Unknown table | Named explicitly at startup, because it would otherwise be silent. |

### Which columns accept a write

A column can also exist, have a setter, take your value, recompute and discard
it — and against one of those a rule looks applied and changes nothing.
`[ModelRules] ProbeWritableColumns = true` settles it per column, on one launch;
see the `ProbeWritableColumns` section of
[`../mods/CKFHardMode/README.md`](../mods/CKFHardMode/README.md) ("When a rule
looks applied and changes nothing") for the output format and cost.

---

## Curves

Anywhere a number is accepted, an object can go instead:

```json
{ "perLevelAbove": [10, 2.2] }
```

"2.2 per level above 10." All the fields:

| Field | Meaning |
|---|---|
| `perLevelAbove` | `[threshold, step]`. Required. |
| `base` | The value at and below the threshold. Defaults to 0 on `add`, 1 on `multiply`; **required** on `set`, `clampMin` and `clampMax`, which have no neutral value to fall back on. |
| `levelColumn` | Which column is "level". Defaults to `PowerLevel`. |
| `geometric` | `true` makes `step` a ratio: `base * step^n` instead of `base + step*n`. |
| `every` | Advance one step per N levels instead of every level. |
| `min` / `max` | Clamp the computed value. |
| `gapFrom` | See below. Different meaning on `set` and on `multiply`. |
| `linearAbove`, `linearPerLevel` | `multiply` only, and only with `gapFrom`. |

### `levelColumn` — "level" is whatever you say it is

A curve reads a column **on the row being edited**, so `perLevelAbove` on a
`WeaponModel` row keys off the *weapon's* `PowerLevel`, not the power level of
whatever enemy is carrying it. **One row cannot vary per holder.** Scaling gear
by enemy level means one row per tier plus a pointer that picks the right one —
see [`cloning-rows.md`](cloning-rows.md).

Any column works. On armour the id is the ladder position and `PowerLevel` is
cosmetic, so `"levelColumn": "ArmorId"` with a threshold of the family's first
id is what a whole-family rule keys on.

### `geometric` — when the step is a ratio

`base + step*n` walks a value in equal amounts. `base * step^n` shrinks or grows
it by a proportion. Percentages want the second: "damage taken falls 4.5% of
itself per level" cannot be written as a linear slope without either stalling at
the top of the range or running past it.

### `every` — steps, not slopes

`MaxArmorPoints` runs 1 to 4 across an entire shipped family. A per-level slope
on a column like that is decided entirely by rounding. `"every": 5` advances one
step per five levels and reads as what it does.

### `gapFrom` — for percentage columns

Armour is a percentage of damage prevented, so what matters is what gets
through. **50 -> 75 halves the damage taken, and so does 80 -> 90.** Multiplying
the number makes a high-armour row improve far faster than a low one.

**On `multiply`**, `gapFrom` scales the gap instead of the value:

```
new = gapFrom - (gapFrom - old) * factor
```

A *falling* factor is what raises the value. `linearAbove` and `linearPerLevel`
add a second regime above a split point, where the column stops behaving like a
percentage and is multiplied outright — for armour, above the engine's 95%
damage-reduction cap, where the extra buys resistance to degradation instead.
Both must be given together.

**On `set`**, `gapFrom` means the curve computed the *gap* and the column stores
the complement — write the ladder as damage taken, store armour.

Three safeguards, all silent unless they fire: a column at `0` is left alone
(zero means the stat is absent, not small); a factor at or below zero would
close the gap completely and is clamped with a warning; a row already past
`gapFrom` is left alone rather than driven backwards.

### Examples

```json
{ "model": "MonsterTypeModel", "whereMin": { "PowerLevel": 11 },
  "add": { "CritRate": { "perLevelAbove": [10, 2.2] } } }
```

```json
{ "model": "MonsterTypeModel", "whereMin": { "PowerLevel": 11 },
  "set": { "WeaponTypeId": { "perLevelAbove": [10, 1], "base": 20009 } } }
```
Walks a contiguous block of ids, one per level — one rule instead of ten.

```json
{ "model": "ArmorModel", "whereMin": { "ArmorId": 21999 }, "whereMax": { "ArmorId": 22009 },
  "set": { "BallisticArmorDegraded": { "perLevelAbove": [21999, 0.955], "base": 78,
                                       "geometric": true, "gapFrom": 100,
                                       "levelColumn": "ArmorId" } } }
```
Overwrites eleven shipped rows with one formula.

```json
{ "model": "ArmorModel", "whereMin": { "ArmorId": 22010 },
  "multiply": { "BallisticArmor": { "perLevelAbove": [10, -0.035], "base": 1,
                                    "gapFrom": 100, "linearAbove": 95,
                                    "linearPerLevel": 0.06 } },
  "add": { "MaxArmorPoints": { "perLevelAbove": [10, 1], "every": 4, "base": 0 } } }
```

---

## Clone syntax

A rule with a `clone` field copies one row and serves the copy, rather than
editing anything.

```json
{ "comment": "Guard Rifle tier 11: tier 10 plus 15%.",
  "model": "WeaponModel",
  "clone": { "WeaponId": 20009 },
  "as":    { "WeaponId": 20020 },
  "multiply": { "BallisticDamage1": 1.15, "BallisticDamage2": 1.15 } }
```

- `clone` names **the column the table's by-id reader looks rows up by** and the
  id of the row to copy — `WeaponId`, `MonsterTypeId`, `EffectId`. Naming any
  other column is caught at load and the rule is refused, because the reader
  would look the value up as a primary id and clone a different row.
- `as` gives the new row its own id, and any other columns that should differ.
  It is required, and it must set the id column.
- `set` / `multiply` / `add` / `clampMin` / `clampMax` then apply to the copy.
- `where` / `whereMin` / `whereMax` are meaningless on a clone rule and are
  ignored with a warning.

The copy is made by asking the game for the source row, which materializes a
fresh private object, and writing over it. So **the clone inherits whatever your
other rules did to its source**, then gets its own operations on top.

Which id to insert under, and which serving paths have been exercised, are in
[`cloning-rows.md`](cloning-rows.md). Clone lines in the current setup are
written as overlay CSV `_clone` cells, not as JSON — see
[`overlays.md`](overlays.md).

### Where a cloned row shows up

Rules reach rows through `GetRow*Model`, which only ever sees rows the game
decided to read. Insertion cannot work that way, so cloning hooks the readers
instead — by-id, filtered-list and zero-arg bulk. Which ones, per table, is in
[`cloning-rows.md`](cloning-rows.md) §2.

**A cloned row does not appear in a CKF Data Dump sweep.** The dumper captures
rows in its own `GetRow*` postfix, and a synthetic row is appended to the
reader's result after every `GetRow*` call has returned, so it never passes that
hook. The log is where a clone is confirmed.

Whether a clone joins a particular list is decided by two tests, and
`"serveOn"` picks which apply:

| `serveOn` | Behaviour |
|---|---|
| `auto` *(default)* | Both tests: the list already contains the source row, **and** the reader's arguments pass the row's own gate columns. |
| `provenance` | Source-row test only; ignore the gate map. |
| `always` | Append to every list for that table. |
| `never` | By-id only, for a row that exists purely to be pointed at. |

The **provenance** test — is the row this was copied from already in this list? —
is right by construction and needs no column names, since a clone differs from
its source only where `as` says it does. The **gate** map covers what provenance
cannot see: that a `MinPowerLevel` 14 squad member must stay out of a PL 2 roll.
What that map contains, and which readers on which database actually serve a
clone, are in [`cloning-rows.md`](cloning-rows.md) §2.

Limits, all of them checked at load or first read and reported as errors:

- `Game*` models cannot be cloned at all. Nothing here writes to the save.
- An `as` id that the table already uses is refused, as is one used by another
  clone rule.
- `[ModelRules] EnableRowCloning = false` takes the reader hooks out entirely.
  A rules file with no `clone` in it installs none of them either way.

---

## Indexing

Rules are matched per row. Testing every rule for a table against every row is
what the engine cost before 2.7.0 — a full `ReadArmors()` was ~127k `Matches()`
calls — and the whole point of overlays is that the file gets much bigger.

Since 2.7.0 each model gets a **plan**: one column chosen as an index, a bucket
per value, and a list of whatever could not be indexed. Per row that is one
number read and one dictionary lookup. Order is preserved — the bucket and the
unindexed list are both in file order and are merge-walked on the rule's
position, so a broad multiply still runs before a narrow clamp that follows it.

**The column is chosen, not configured.** A model is indexed when at least half
its rules select one exact integer column. Every overlay edit line is that shape
by construction, and so is most of `rules.json`.

The load log says what each model chose:

```
  EffectModel: 133 rule(s) indexed on EffectId — 133 value(s), worst bucket 1, 0 unindexed
  RuleModel: 2 rule(s), no index (every row tests all of them)
```

**"no index" is correct, not broken** — it is the old behaviour, and at a
handful of rules it is the right one. It is worth acting on when a table has
hundreds of rules and still says it. Two reasons a table stays unindexed: a
range selector (`whereMin`/`whereMax` on `ArmorId` spans buckets), and a `where`
on a string or a fractional number. Only exact integer columns bucket, so where
the rows are known an overlay line per row is indexable and a range rule is not.

400 rows swept [measured]:

| Model | Rules | Scan | Indexed | |
|---|---|---|---|---|
| `EffectModel` | 133 | 5.95 ms | 0.023 ms | 259x |
| `JobNodeModel` | 72 | 3.16 ms | 0.017 ms | 186x |
| `MissionPowerLevelModel` | 33 | 1.34 ms | 0.007 ms | 183x |
| `TalentModel` | 43 | 1.96 ms | 0.287 ms | 6.8x |
| `RuleModel` | 2 | 0.084 ms | 0.084 ms | 1.0x |

`[ModelRules] CompiledAccessors = true` (the default) is the other half:
columns are read and written through delegates compiled at load rather than
reflection per row, worth a further 1.6–2.1x. **It changes no result** — the
numeric conversion is the same round-to-nearest, halves-to-even that
`Convert.ChangeType` did, so `25 x 1.5` still stores `38`. Turn it off only to
rule codegen out while diagnosing something; the engine then behaves exactly as
2.5.2 did, slower.

## What the file currently holds

The current `ckf.hardmode.rules.json` holds **293 rules across 8 model types**
[measured]: `EffectModel` 133, `JobNodeModel` 72, `TalentModel` 43,
`WeaponModel` 33, `MatrixEffectModel` 8, `RuleModel` 2, `ImplantModel` 1,
`MonsterTypeModel` 1. **Zero of them are clone rules.** Every clone line lives
in an overlay CSV's `_clone` column, not in `rules.json`.

Only tables a rule targets get hooked, so the load log's hooked count tracks
that model-type count; every hook is a postfix on the game's per-row hot path,
so hooking a table nothing edits is pure overhead. A model name with no
materializer is named at startup (`no materializer for WeponModel — rules
targeting those will never run`).

---

## Worked examples

**Whole table, no selector** — every weapon 25% harder, both firing modes

```json
{ "model": "WeaponModel",
  "multiply": { "BallisticDamage1": 1.25, "BallisticDamage2": 1.25,
                "PureDamage1": 1.25, "PureDamage2": 1.25 } }
```

**A numeric band** — enemy weapons start at id 20000, player weapons are low

```json
{ "model": "WeaponModel", "whereMin": { "WeaponId": 20000 },
  "multiply": { "BallisticDamage1": 1.4, "BallisticDamage2": 1.4 } }
```

**Two rules stacking, and a floor** — a general slope, then a steeper one above
a threshold, then a clamp that runs last

```json
{ "model": "CharacterLevelModel", "multiply": { "Xp": 2.0 } }
{ "model": "CharacterLevelModel", "whereMin": { "Level": 20 },
  "multiply": { "Xp": 1.5 } }
{ "model": "CharacterLevelModel", "multiply": { "Job": 0.75, "Talent": 0.75 },
  "clampMin": { "Job": 1, "Talent": 1 } }
```

**A string selector** — `RuleModel` groups a whole set of constants under one
`GroupId`

```json
{ "model": "RuleModel", "where": { "GroupId": "HEAT" },
  "multiply": { "Value": 1.5 } }
```
