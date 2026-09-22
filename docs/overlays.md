# Overlays: the CSV rule dialect

The per-table CSV format for stating specific rows' values, which is how every
table edit in `ckf.hardmode.d/` is written. Rule semantics (operation order,
clone serving) are in [`rule-engine.md`](rule-engine.md); lever sheets
(`gear-classes.csv` and the like) have their own headers and are described by
their schemas, not here.

Use an overlay when each row should receive an explicit value. Use JSON rules
when the change is a curve or broad selector. Use
[`cloning-rows.md`](cloning-rows.md) before inserting a row.

```
ArmorId, BallisticArmorDegraded, PhysicalArmorDegraded, MaxArmorPoints, _comment
22010,   52,                     48,                    2,              Guard Std 11
22011,   54,                     50,                    2,              Guard Std 12
```

One line per row. The header row is column names exactly as in the dump's
`<Table>.csv`, so a file can be edited in a spreadsheet or handed to an LLM
together with the dump. An empty cell means "leave that column alone".

Each edit line compiles to a rule selecting one exact id (`Overlays.BuildRule`),
which is the shape the rule index buckets on
([`rule-engine.md`](rule-engine.md#indexing)); per-row cost stays flat as a file
grows. Edit lines carry no JSON, and a `_comment` is kept only when the file
supplies one.

## Files

Location: `BepInEx/config/ckf.hardmode.d/`. Subfolders are not read.

- The table is the filename up to the first dot, with `Model` appended if
  missing (`Overlays.TableOf`). `ArmorModel.csv` and
  `ArmorModel.guard-standard.csv` both target `ArmorModel`, so a table can be
  split across files. A filename with nothing before the first dot is ignored
  with a warning.
- `.csv` is comma-separated, `.tsv` tab-separated. Other `.json` files are
  rules files ([`rule-engine.md`](rule-engine.md#where-rules-come-from)).
- Files load in ordinal filename order, so where two lines touch one row the
  later file's line applies last.
- Encoding: UTF-8; a leading BOM is stripped. In PowerShell, `>` writes UTF-16,
  which the loader does not read; use `| Out-File -Encoding utf8 "<path>"`.
- A file's `[Slices]` toggle, if a slice claims it, decides whether it is opened
  at all (`Slices.OverlayOwner`). The shipped enemy-gear files `ArmorModel.csv`,
  `WeaponModel.csv` and `MonsterTypeModel.csv` are claimed by no slice and always
  load.

## Choose an operation in the header

The operator is a suffix on the column name, so every cell stays a plain number
and a spreadsheet never reads one as a formula (`Overlays.ParseHeader`).

| Header | Does |
|---|---|
| `Column` | set |
| `Column*` | multiply |
| `Column+` | add |
| `Column>` | clampMin |
| `Column<` | clampMax |

A bare `-7` under `Column` sets −7. One column may appear more than once with
different operators; order is always set → multiply → add → clampMin →
clampMax.

A non-numeric cell is kept as a literal only under a plain `Column` (set);
`true` / `false` become booleans. Under an operator suffix it is warned about
and skipped.

The first column must be the table's id column, with no suffix. If it is empty
or a control column, the file is ignored with an Error.

Control columns start with `_` (case-insensitive):

| Column | Does |
|---|---|
| `_clone` | id of the row to copy; makes the line an insert |
| `_comment` | free text, shown in trace lines and by the validator |
| `_serveOn` | `auto` / `provenance` / `always` / `never`, on a clone line |

CSV quoting follows RFC 4180 as far as a quote that opens a field and a doubled
quote inside one (`Overlays.SplitLine`).

## Read line outcomes

| Line | Result |
|---|---|
| blank, or every cell empty | skipped, not counted |
| starts with `#` | comment, skipped |
| id parses, every value cell empty | counted as "named a row and set nothing"; the row is left as shipped. One Info line per file. |
| id cell empty but values present, or id not an integer | warned, counted as malformed |
| values present but none could be applied | warned, counted as malformed |

The summary line reports files read, rows merged, inserts, untouched lines and
malformed lines:
`Overlays: N file(s) in the directory, ... ; M row(s) merged, K of them inserts, U line(s) named a row and set nothing.`

## Clone lines

```
ArmorId, _clone, BallisticArmorDegraded, MaxArmorPoints, _comment
22010,   22009,  52,                     2,              Guard Std 11
```

A non-empty `_clone` cell makes the line an insert (`Overlays.CloneRule`):

- the first cell is the new id, `_clone` the source id;
- plain `Column` cells go into `as`, which is written before any operation, so
  they state what the new row is;
- `*`, `+`, `>`, `<` cells then apply on top of those values;
- `_serveOn` becomes `serveOn`.

Two rules for clone lines:

- State every column the file carries, including zeros. A column left empty is
  inherited from the `_clone` source, so a later edit to the source moves every
  tier built from it for that column. Columns no CSV names at all (class, mode,
  firing arc, `SpecialRule`, `PrecisionRule`, VFX, name) always come from the
  source, which is why a clone source must stay inside its own family.
- A clone inherits every gate its source carries. Set `MaxPowerLevel` and similar
  explicitly.

Id choice and serving are in [`cloning-rows.md`](cloning-rows.md). Which ids are
enemy gear is in
[`player-vs-enemy-gear.md`](../overlays/_reference/player-vs-enemy-gear.md).

## Use JSON for curves

Curves. `perLevelAbove`, `gapFrom`, `geometric`, `every` and `levelColumn` exist
only in JSON rules. An overlay states values; a JSON rule states a shape.

## Generate a file from the dump

`scripts/make_overlay.py` writes an overlay pre-filled from the dump to stdout.

| Mode | Writes |
|---|---|
| `edit <Table> --ids A-B` | one line per existing row, with its current values |
| `ladder <Table> --from SRC --ids A-B` | one clone line per new id, pre-filled with the source row's values |

Other flags: `--dump <dump dir>`, or `--game <install dir>`, which looks in
`BepInEx/ckf-dump` (pass `--dump` when `[Dump] OutputDirectory` points elsewhere); `--columns a,b,c`
(default: the numeric columns that vary across the table); `--key` for a table
the script's `KEYS` map does not know; `--comment`.

```
python scripts\make_overlay.py edit ArmorModel --ids 22400-22409 --columns BallisticArmorDegraded,PhysicalArmorDegraded,MaxArmorPoints --dump "<dump dir>" > "<game dir>\BepInEx\config\ckf.hardmode.d\ArmorModel.guard-superheavy.csv"
```

Table names are the dump's file names in full (`ArmorModel`, not `Armor`).

## Validate before launch

Run from the repository root:

```text
python scripts\validate_rules.py --game "<game root>" --dump "<dump dir>" --enabled-set
```

The validator catches a pointer to an id that neither the dump nor a clone
provides. Exit code is 1 if anything is at `ERROR`. The full gate sequence is in
[`workflow.md`](workflow.md).

| Reported | Level | Means |
|---|---|---|
| `dangling pointer` | E | a `set` or curve aims a pointer column at an id neither the table nor any clone provides |
| `unknown table` | E | the model has no materializer |
| `clone source missing` | E | `_clone` names a row that is not in the table |
| `clone shape` | E | `clone` does not name the table's by-id key |
| `id collision` | E | an `as` id the table already uses, or two clones claiming one id |
| `overlay header` | E | the file's header cannot be used |
| `unknown column` | W | a name in no dump header; the rule never fires |
| `read-only column` | W | an alias or computed column; the write is discarded |
| `gated clone source` | W | the source row's own `MaxPowerLevel` excludes the clone from the calls it is meant for |
| `edits a clone source` | W | this row is copied by clone lines; only columns those lines leave empty move with it |
| `duplicate overlay id` | W | the same row set twice; the later file wins |
| `row does not exist` | W | an edit line for an id nothing provides |
| `column not in the dump` | I | the column was dropped or its table skipped by the dumper (`_dropped_columns.csv`, `_skipped_tables.csv`) |
| `empty overlay line` | I | a line that names a row and sets nothing |

Warnings from `*.zz-verify*` files are counted separately: those are fixtures
that plant faults on purpose.

The validator also checks the consumable lever sheets (see the script's
docstring). `--enabled-set` resolves pointers against only the files whose
slices are on in `ckf.hardmode.cfg`.

The lever converters (`gear_classes.py`, `cyberweapons.py`, `implants.py`,
`consumables.py`) have their own `--check`. In `cyberweapons.py`, P-DIVERGE
(`check_divergent_shared_edits`) refuses two owners of one shared row that
give the same column different values.

To assert exact values in game, add rows to `ckf.hardmode.selfcheck.csv` and set
`[Slices] SelfCheck = true` for that launch ([`workflow.md`](workflow.md)).

## Related

- [`rule-engine.md`](rule-engine.md)
- [`cloning-rows.md`](cloning-rows.md)
- [`tuning-enemies.md`](tuning-enemies.md)
- `overlays/README.md` (not published): the enemy-gear overlay generator
