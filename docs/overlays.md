# Overlays — the bulk authoring format

`ckf.hardmode.rules.json` is right for a rule that says something general:
"every enemy above PL 10 gains 2.2 crit per level". It is wrong for the other
job — stating what one specific row's numbers are. That is twenty lines of JSON
to carry four values, and 77 armour families one row at a time is tens of
thousands of them.

An overlay is the same edit as a table.

```
ArmorId, BallisticArmorDegraded, PhysicalArmorDegraded, MaxArmorPoints, _comment
22010,   52,                     48,                    2,              Guard Std 11
22011,   54,                     50,                    2,              Guard Std 12
```

One line per row edited. **The header row is column names straight out of
`D:\ckf-data-modding\sheets\raw\<Table>.csv`**, so an LLM handed the dump edits a file it can
already read, and a human opens the result in a spreadsheet and changes one
cell. **An empty cell means "leave that column alone"**, so a sparse edit costs
no more to write than a dense one.

Added in Hard Mode 2.7.0. Nothing about `rules.json` changed — every existing
rule loads and behaves exactly as before.

The install/dump/edit/test loop and reading the log are in
[`workflow.md`](workflow.md). The things that do not work are in
[`gotchas.md`](gotchas.md).

---

## Where the files go

`BepInEx/config/ckf.hardmode.d/`

The table is **the part of the filename before the first dot**, so
`ArmorModel.csv` and `ArmorModel.guard-standard.csv` both target `ArmorModel`
and one table can be split across as many files as suits. Three extensions:

| Extension | Is |
|---|---|
| `.csv` | this format, comma-separated |
| `.tsv` | this format, tab-separated |
| `.json` | an ordinary rules file — which is how `rules.json` gets split per table |

**Load order is `rules.json` first, then the directory in filename order.**
Overlays therefore win where they overlap, which is the useful way round: a
sweep sets the shape of a family, and one line overrides the row that should
not follow it.

**The shipped set is one file per table** — `ArmorModel.csv` (180 rows),
`WeaponModel.csv` (385), `MonsterTypeModel.csv` (2427). It used to be 51 files,
one per gear family, split `<family>-base.csv` for edits to shipped rows and
`<family>.csv` for the clone inserts above them. The two shapes are the same
data: a merged file carries the union of its family files' columns, an empty
cell still means "leave that column alone", and an empty `_clone` cell still
means the line is an edit rather than an insert.

`scripts/merge_overlays.py` did the merge and can redo it. Its `--check`
compiles both file sets to a canonical rule list and compares them element by
element in order; `--selftest` proves that comparison can fail, by injecting
nine faults into the merge and asserting each is reported. Splitting a table
back across several files is still legal if a future set wants it.

---

## The operator lives in the header

| Header | Does |
|---|---|
| `Column` | set to the cell's value |
| `Column*` | multiply by it |
| `Column+` | add it |
| `Column>` | clampMin |
| `Column<` | clampMax |

So every **cell stays a plain number**: nothing starts with `=` or `+`, so a
spreadsheet will not read a cell as a formula. A bare `-7` is "set to −7", not
"subtract 7".

One column may appear more than once with different operators. Order is always
`set → multiply → add → clampMin → clampMax`, whatever order the headers are
in, exactly as in `rules.json`.

Three control columns, recognisable by their leading underscore:

| Column | Does |
|---|---|
| `_clone` | the id of the row to copy — makes the line an **insert**, not an edit |
| `_comment` | free text; shown by `TraceRules` and by the validator |
| `_serveOn` | `auto` \| `provenance` \| `always` \| `never`, on a clone line |

A line whose cells are all empty is skipped. So is a line whose id will not
parse, with a warning naming the file and line number. `#` starts a comment
line.

### A gear tier is one line

```
ArmorId, _clone, BallisticArmorDegraded, MaxArmorPoints, _comment
22010,   22009,  52,                     2,              Guard Std 11
22011,   22009,  54,                     2,              Guard Std 12
```

Plain columns on a clone line go into `as`, which runs **before** any
operations — so the values here are what the new row *is*, and a `*` or `+`
column on the same line then applies on top of them.

Everything in [`cloning-rows.md`](cloning-rows.md) still holds: allocate the
ids as an unbroken run, and **a clone inherits every gate its source carried**
— set `MaxPowerLevel` explicitly rather than relying on inheritance.

### Which rows are player gear and which are enemy gear

[`../overlays/_reference/player-vs-enemy-gear.md`](../overlays/_reference/player-vs-enemy-gear.md)
is the canonical derivation and lists the ranges; regenerate it if the ladders
change. Nothing here restates it.

One thing that reference has not caught up with: the weapon split **has been
done** [measured, live install]. `WeaponModel.blade5.csv` puts PL 1-10 at ids
`900160`-`900169`, cloning `52`, `5001`, … , and PL 11-20 at `900010`-`900019`;
`sniper6`, `thrasher` and `shock` are the same shape. The rows shared between
player and enemy are no longer what enemies carry.

### Two rules for a clone line

**State every column, including the ones that are 0.** A column left off a
clone line is inherited from the `_clone` source, so a later edit to that source
moves every tier built from it. Stating all of them leaves a tier depending on
its source only for the columns no CSV names at all: class, mode, firing arc,
`SpecialRule`, `PrecisionRule`, VFX, name. That is also why a clone source must
stay inside its own family.

**Count a family's tiers as shipped + already in `rules.json` + new here.**
`make_enemy_overlays.py` refuses to write unless every block is exactly 20
distinct ids with all 20 provided, and its `_reference/gear-blocks.md` prints
the `ship/rules.json/new` split per block.

### What overlays do NOT do

**Curves.** `perLevelAbove`, `gapFrom`, `geometric`, `every` and `levelColumn`
stay in `rules.json`. The split is deliberate: an overlay states values, a rule
states a shape. Use a rule where one formula covers a family, and an overlay
where the numbers are decided row by row.

---

## Generating and checking a file

### Generate the file pre-filled from the dump

Nobody should author an overlay from a blank file.

One line, cmd.exe. **In PowerShell `>` writes UTF-16 and the loader will not
read it** — there, use `| Out-File -Encoding utf8 "<path>"` instead.

```
python "D:\ckf-data-modding\scripts\make_overlay.py" edit ArmorModel --ids 22400-22409 --columns BallisticArmorDegraded,PhysicalArmorDegraded,MaxArmorPoints --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint" > "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config\ckf.hardmode.d\ArmorModel.guard-superheavy.csv"
```

`edit` writes a line per existing row carrying its **current** values, so the
job is "change these numbers" and a diff against the generated file shows
exactly what was retuned. `ladder` does the same for tiers that do not exist
yet, cloning a source row:

```
python "D:\ckf-data-modding\scripts\make_overlay.py" ladder ArmorModel --from 22409 --ids 22410-22419 --columns BallisticArmorDegraded,PhysicalArmorDegraded,MaxArmorPoints --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint" > "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config\ckf.hardmode.d\ArmorModel.guard-superheavy-ladder.csv"
```

Omit `--columns` and it takes every numeric column the table has.

The four `ArmorModel` clone sources are `22009`, `22105`, `22200` and `22300`;
the validator reports any others, and [`gotchas.md`](gotchas.md) says why not to
target one.

Then edit the numbers, by hand or by handing the file to an LLM along with
`D:\ckf-data-modding\sheets\raw\<Table>.csv` — the format is the dump's own columns.

### Validate before launching

Run `validate_rules.py` — the command line is in [`workflow.md`](workflow.md).
**This is the step that matters.** A pointer aimed at an id that does not exist
is a black screen with no logged exception, and the validator is the only place
that catches it at your desk rather than in a mission.

| Reported | Means |
|---|---|
| `dangling pointer` **E** | a `set` or curve aims a pointer column at an id neither the table nor any clone provides — **the mission will not load** |
| `unknown table` **E** | the model name has no materializer |
| `clone source missing` **E** | `_clone` names a row that is not there |
| `id collision` **E** | an id the table already uses, or two clones claiming one id |
| `clone shape` **E** | `clone` names a column that is not the table's by-id key |
| `unknown column` **W** | a name in no dump header — the rule silently never fires |
| `read-only column` **W** | an alias or computed column; the write is taken and discarded |
| `gated clone source` **W** | the source row's own `MaxPowerLevel` excludes the clone from the calls it is meant for — the Run 37 trap |
| `edits a clone source` **W** | this row is copied by clone rules. It only moves the tiers for columns their clone lines do NOT state — state every column and the warning is bookkeeping, not a defect. Re-record any SelfCheck expectation taken from the source. |
| `duplicate overlay id` **W** | the same row set twice; the later file wins |
| `row does not exist` **W** | an edit line for an id nothing provides |

Truth comes from `D:\ckf-data-modding\sheets\raw\`, written by the live game; it reads
`_dropped_columns.csv` and `_skipped_tables.csv` too, so a column the dumper
trimmed is reported as INFO rather than as a mistake, and it refuses to fall
back to `Aug21Sheets/`.

Exit code is 1 if anything is at ERROR, so it drops into a build step as-is.
Warnings from `*.zz-verify*` files are counted separately and named as fixtures
— those plant faults on purpose. A warning from any other file is worth reading.

To assert exact values in-game rather than eyeball them, add rows to
`ckf.hardmode.selfcheck.csv` and turn `[SelfCheck] Enabled` on for that launch —
[`workflow.md`](workflow.md).

---

## Why this is also the fast path

Every edit line compiles to a rule selecting one exact id, which is the shape
the rule index buckets on (see [`rule-engine.md`](rule-engine.md) §Indexing).
Ten thousand overlay lines on `ArmorModel` cost **one number read and one
dictionary lookup per row**, not ten thousand comparisons. Measured on the
current file, with 400 rows swept:

| Overlay lines | Load | Retained | Sweep, indexed | Sweep, unindexed |
|---|---|---|---|---|
| 1,000 | 3 ms | 1.0 MB | 0.17 ms | 24.6 ms |
| 10,000 | 43 ms | 10.1 MB | 0.17 ms | — |
| 40,000 | 579 ms | 40.5 MB | 0.16 ms | — |

Sweep cost is **flat** as the file grows; load time and memory are what scale,
at roughly **1 MB and 15 ms per thousand lines**. Forty thousand lines is
about half a second of extra load — the practical ceiling is memory, not
per-row cost.

Edit lines carry no JSON at all: the selector is a `long` on the rule and the
values are constant terms, so a line costs a few small arrays rather than a
retained `JsonDocument`. That is also why a `_comment` is only kept when the
file supplies one.
