# CKF Hard Mode config schema: format

The grammar of `schema/*.schema.json`: which keys a schema file may carry, what each one means, which tool reads it, and what `check_schema.py` enforces. It does not list values. For those, see [`../docs/config-reference.md`](../docs/config-reference.md), which `scripts/gen_docs.py` generates from these files. Traps are in [`../docs/gotchas.md`](../docs/gotchas.md).

Each subsystem or slice has one schema file. The schemas are the only declaration of what is configurable. `check_schema.py` reports any key on disk that no schema declares as `STALE`.

Current declarations: 46 cfg keys (`General.Enabled` plus 45 slice toggles).
The [workflow](../docs/workflow.md#maintain-the-two-versions) owns the independent
plugin version and settings-layout stamp. After changing a
schema, regenerate the binds, cfg template and generated config reference, then
run the checks in [Generators](#generators). Do not hand-edit those generated
outputs.

## Readers

| Reader | Keys it consumes |
|---|---|
| `schema/check_schema.py` | `subsystem`, `targets.json`/`section`/`overlays`, `enable.cfg`, field `path`/`in`/`type`/`range`/`optional`/`keyedBy`/`row`/`rows`, `invariants` |
| `scripts/gen_binds.py` | `targets.cfg`, `enable.cfg`, `"in": "cfg"` fields (`path`, `type`, `default`) |
| `scripts/gen_cfg_template.py` | same key set, through `gen_binds.collect` |
| `scripts/gen_docs.py` | everything; any key outside its `KNOWN_TOP`/`KNOWN_FIELD`/`KNOWN_COL` sets is printed as an "unrendered keys" line |
| `scripts/gen_teampl_labels.py` | the `mirror` invariant whose `target` is its output, plus `targets.legacyJson` |
| `gui/serve.py` + `gui/app.html` | everything except `legacyJson`; runs `check_schema.py` in a child process on validate and save |

`gen_binds.py` reads schemas with strict `json.load`. `check_schema.py`, `serve.py` and `gen_teampl_labels.py` use `check_schema.load_jsonc`, which accepts `//` comments and trailing commas. A schema must therefore be strict JSON.

## Top level

From `elapse.schema.json`:

```json
{
  "subsystem": "Elapse",
  "title": "Mission Elapse Penalty",
  "targets": { "cfg": "ckf.hardmode.cfg", "json": "ckf.hardmode.d/elapse.json",
               "legacyJson": "ckf.hardmode.elapse.json" },
  "enable": { "cfg": "Slices.Elapse" },
  "doc": ["..."],
  "uiDoc": ["..."],
  "fields": [ ... ],
  "invariants": [ ... ]
}
```

| Key | Meaning |
|---|---|
| `subsystem` | Subsystem name. Used in problem messages, as the GUI section id, and as the slice key's name (`Slices.<subsystem>`). Two do not match their file name: `teampl.schema.json` is `Progression`, `missionrewards.schema.json` is `MissionRewards` (file `missions.json`). |
| `title` | Display name, in Title Case. The `serve.py` selftest asserts Title Case ("every section title is Title Case"). Five talent schemas keep a retired class name in their filename and cfg key, because the filename is the binding; `title` has the real name (table in [`../mods/CKFHardMode/README.md`](../mods/CKFHardMode/README.md#content-slices)). |
| `doc` | Array of lines, the maintainer text. Rendered into `config-reference.md`. `""` is a paragraph break. |
| `uiDoc` | Array of lines, the player-facing text. The GUI shows it in place of `doc` (`serve.py:section_prose`). Selftests require every schema to have one and reject a `uiDoc` that contains a source citation or an evidence tag. A `uiDoc` may only restate claims already made in `doc`, a field `doc`, or an invariant `reason`. |
| `targets` | Files this schema owns. See below. |
| `enable` | The gate. Every schema has `{ "cfg": "<Section.Key>" }` naming its own `"in": "cfg"` field. |
| `fields` | Array of field declarations. |
| `invariants` | Optional array of cross-key rules. |

### `targets`

| Key | Meaning |
|---|---|
| `cfg` | Always `"ckf.hardmode.cfg"`. Declaring it makes the schema a slice (see [Slices](#slices)). `gen_binds.py` refuses any other value. |
| `json` | The slice's JSON document, relative to the config directory (`BepInEx/config`), e.g. `ckf.hardmode.d/teampl.json`. Fields sit at the file's top level. Single-valued and JSON-only: `check_schema.py` parses it with `load_jsonc`. |
| `section` | Optional. A top-level key inside `json` that holds the fields. It is still supported by `check_schema.py`, `serve.py:sidecar_unit` and `gen_docs.py`, but no schema declares it. |
| `overlays` | List of CSV/TSV paths under `ckf.hardmode.d/` that this slice owns. |
| `legacyJson` | The 2.x sidecar the section came from, or `null` if there wasn't one. Only `gen_teampl_labels.py` reads it, as a fallback source for the `mirror`. |

A schema has `json`, `overlays`, or neither (`general.schema.json`). No schema has both.

### `targets.overlays`

From `talentssawbones.schema.json`:

```json
"targets": {
  "cfg": "ckf.hardmode.cfg",
  "overlays": [
    "ckf.hardmode.d/EffectModel.sc.csv",
    "ckf.hardmode.d/JobNodeModel.sc.csv",
    "ckf.hardmode.d/TalentModel.sc.csv"
  ]
}
```

`check_schema.py` never opens an overlay. It checks the following:

- Each declared path exists. If a path is absent, the check prints `MISSING <subsystem>: overlay <path> is declared but not on disk`.
- Every `.csv`/`.tsv` file in `ckf.hardmode.d/` is claimed by exactly one schema. An unclaimed file is `STALE`, and so is a file claimed by more than one schema.
- `ArmorModel.csv`, `WeaponModel.csv` and `MonsterTypeModel.csv` are exempt from the unclaimed check (`LEGITIMATELY_UNCLAIMED`) and are named on the census line.

The list may hold either kind of file:

- A direct overlay, where the filename names the game table.
- A lever sheet such as `gear-classes.csv`, `cyberweapons-*.csv` or `implants-slotNN.csv`, where one row is a player concept that an expander turns into writes.

Nothing in the schema marks which kind a file is. The schema also declares no overlay columns, because the file's header is the authority. For the column dialect (operator suffixes, `_comment`, `_clone`), see [`../docs/overlays.md`](../docs/overlays.md).

## Slices

A slice is a schema that declares `targets.cfg`. Its toggle is the schema's one
`"in": "cfg"` field, `Slices.<subsystem>`, a `bool`. `general.schema.json`
follows the same one-file-one-key rule with `General.Enabled`, the master
switch. `Plugin.Binds.g.cs` declares 46 keys: `General.Enabled` plus 45
`Slices.*`.

A slice schema looks like this (`rulemodel.schema.json`, trimmed):

```json
{ "path": "Slices.RuleModel", "in": "cfg", "type": "bool",
  "default": true, "ui": "form", "label": "Enable Game Rule Constants" }
```

`gen_binds.collect` fails (exit 2) if the slice set and the key set disagree in any of these ways:

- A schema declares `targets.cfg` but has no `"in": "cfg"` field.
- A schema declares more than one `"in": "cfg"` field.
- A schema has an `"in": "cfg"` field but no `targets.cfg`.
- `enable.cfg` names a key that no schema declares as a field.

It also fails on a cfg `path` that is not exactly `Section.Key`, an unsupported cfg `type`, a missing `default` or one of the wrong type, a non-finite float default, or the same key declared twice.

In the GUI, `serve.py:enable_index` builds each schema's gate list from `enable`. A schema without `enable` gets no gates and `effective: "n/a"`. A cfg key absent from the file reads as `unknown`, never `off`.

## Fields

From `elapse.schema.json`:

```json
{
  "path": "credits.percentOfBalance", "in": "json", "type": "float",
  "default": 0.0, "range": [0.0, 1.0], "ui": "form",
  "enabledBy": "credits.enabled",
  "label": "Percent of balance",
  "doc": "...", "uiDoc": "..."
}
```

| Key | Meaning |
|---|---|
| `path` | For `"in": "cfg"`: `Section.Key`. For `"in": "json"`: a dotted path from the document root (or from `targets.section` if one is declared). For `"in": "reference"`: a name only. |
| `in` | `cfg`, `json`, or `reference`. |
| `type` | See [type](#type). |
| `default` | Required on cfg fields (`gen_binds.py`). On an absent cfg key, `serve.py` uses it as the effective value. On json fields it is rendered into docs and nothing enforces it. |
| `range` | `[min, max]`, inclusive. See [range](#range). |
| `ui` | See [ui](#ui). |
| `label` | Control label in the GUI. |
| `doc` / `uiDoc` | Single strings: maintainer text and player text. The GUI shows `uiDoc`, falling back to `doc` with citations and evidence tags stripped (`serve.py:field_help`, `strip_maintainer_marks`). |

### `type`

| Type | Notes |
|---|---|
| `bool` | cfg values `true`/`false`, case-insensitive (`check_schema.coerce`). |
| `int`, `float` | Range-checked when `range` is present. |
| `floatOrNaN` | `NaN` means "leave the game's value alone". `check_range` skips NaN. No field uses this type today. |
| `string` | |
| `stringList` | A JSON array in a document, or a comma-separated single line in the cfg. `serve.py` refuses to save a multi-line cfg `stringList`. Binds as CLR `string`. |
| `enum` | Needs `values`. `app.html` renders it as a select. No field uses this type today. `gen_binds.py` has no CLR type for it, so it cannot be a cfg field. |
| `table` | A JSON array of objects, or an object when `keyedBy` is set. Needs `row`. |

A cfg field may only be `bool`, `int`, `float`, `floatOrNaN`, `string` or `stringList` (`gen_binds.CLR_TYPES`).

### `range`

`check_schema.check_range` does nothing when any of the following holds:

- `range` is absent or `null`.
- The value is `null`, a `bool`, not a number, or NaN.

Otherwise it reports a value outside `[lo, hi]` as `RANGE`. In the cfg, a value that fails to coerce to its declared type is also reported as `RANGE` (`... is not a <type>`). `RANGE` is in `serve.py`'s `BLOCKING`, so a range violation refuses a save. A numeric field with no `range` is not bounds-checked at all.

Numeric fields get one of three kinds of range, and the field's `doc` says which:

- **Enforced.** The plugin's own limit, e.g. `stress.cap`.
- **Domain.** The domain of the quantity or column, e.g. percent `[0, 100]` or fraction `[0.0, 1.0]`.
- **Guard rail.** A wide editor limit with no enforced or domain bound behind it, e.g. `tiers[].multiplier` `[0.0, 10.0]`.

Fields with nothing to derive a bound from carry no range, e.g. trait ids, durations, and the `rewardcurve.curve[]` money/XP columns.

### `ui`

This table is the canonical list. The `serve.py` selftest asserts that every field's `ui` is one of these values.

| Value | Renders as |
|---|---|
| `form` | A labelled control for the type. |
| `table` | An editable grid. `row` gives the columns. |
| `curve` | A grid plus an editable line chart. x is the first `row` column. |
| `matrix` | A 2-D grid. Needs `axes`. |
| `readonly` | Shown but not editable. |
| `hidden` | Declared, so the stale-key diff stays complete, but never rendered. No field uses it today. |

### Table fields

A `table` field takes `row` and may add `keyedBy`, `sortBy`, `axes` and `over`. From `elapse.schema.json`:

```json
{
  "path": "credits.byPowerLevel", "in": "json", "type": "table", "ui": "table",
  "enabledBy": "credits.enabled",
  "row": [
    { "name": "minPowerLevel", "type": "int", "range": [0, 25] },
    { "name": "amount", "type": "int", "range": [0, 100000] }
  ],
  "sortBy": "minPowerLevel"
}
```

| Key | Meaning |
|---|---|
| `row` | Column list. Each column has `name` and `type`, and optionally `range` and `format`. `check_schema.py` range-checks every cell whose column declares a `range`. `serve.py:build_table` coerces cells to the column `type` on save. |
| `keyedBy` | The table is a JSON object on disk, keyed by this column. Without `keyedBy`, the table is an array. `check_schema.table_rows` folds the key back into each row, coerced to the column's type, before range-checking it. Examples: `elapse.tiers` (`name`) and fatigue's two curves, `byPowerLevel` and `knight.byPowerLevel` (`powerLevel`). `missionrewards.missions` must stay an array because the plugin reads a `List`. |
| `sortBy` | The column the rows are ordered by. Rendered into docs. The GUI does not sort on it. |
| `axes` | `matrix` only: `{ "row", "col", "value" }` column names. |
| `over` | `matrix` only: the path of the `readonly` table this matrix overlays. `app.html` pairs the two controls through it. |

From `teampl.schema.json`:

```json
{ "path": "override", "in": "json", "type": "table", "ui": "matrix",
  "axes": { "row": "ActionClass", "col": "MissionPowerLevel", "value": "PowerLevelFraction" },
  "over": "table", "retroactive": true, "row": [ ... ] }
```

#### Column `format`

| Value | Meaning |
|---|---|
| `adjust` | The string column uses the adjustment grammar of `MissionRewards.Adjust.Parse`: blank means leave alone, `=N` sets, `+N`/`-N` adds, `xN`/`XN`/`*N` multiplies, and a bare number sets. `serve.py` refuses a save with an unparseable cell (`check_adjust_cell`), and `app.html` flags such a cell. Used on the five slot columns of `missionrewards.missions`. |
| `keep` | A marker that a negative value or an absent cell means "keep the game's number". Used on `rewardcurve.curve`'s `Payment`, `Experience` and `Bonus` columns. It is rendered into docs, but no code branches on the value. |

A string column with no declared `format` gets one inferred from the file by `serve.py:infer_column_formats`: `adjust` if the table shows at least one parseable adjustment and every non-empty value in the column parses, otherwise `text`.

### `"in": "reference"`

This field's data lives in the schema itself, under `rows`, instead of in a config file. From `rulemodel.schema.json`:

```json
{
  "path": "ruleReference", "in": "reference", "type": "table", "ui": "readonly",
  "sortBy": "RuleId",
  "row": [ { "name": "RuleId", "type": "int", "range": [1, 76] },
           { "name": "GroupId", "type": "string" },
           { "name": "ConfigName", "type": "string" },
           { "name": "Shipped", "type": "int", "range": [-50, 400] } ],
  "rows": [ { "RuleId": 1, "GroupId": "CHARACTER", "ConfigName": "Max Character Level", "Shipped": 42 } ]
}
```

`check_schema.py` does not look for this field on disk. It only range-checks `rows` against `row`. `serve.py:reference_fields` shows the field next to the control it annotates, and never includes it in an edit or a save. The rows are a snapshot of a game dump, and nothing detects when they go stale.

### `enabledBy`

A field-level gate below the slice toggle. The value is a `bool` path in the same document (e.g. `"credits.enabled"`). The GUI greys out the field when the gate is false (`app.html:gateState`). `serve.py:enable_index` lists these gates as `blocks`. `app.html` also accepts a `Section.Key` for a cfg field, but no field uses that today. `check_schema.py` ignores `enabledBy`.

Current uses:

- `elapse`: `credits.enabled`, `stress.enabled`
- `fatigue`: `woundResist.enabled`
- `modelrules`: `probeWritableColumns`
- `selfcheck`: `enabled`

### Optional flags

| Flag | Meaning |
|---|---|
| `"optional": true` | The field may be omitted from the file. `check_schema.py` skips only its `MISSING` check, and every other check still applies when the value is present. Use it only when omission is the documented, shipped state. Used on `fatigue`'s `knight.byPowerLevel`. |
| `"absent": "..."` | Prose describing what an omitted value means. Rendered into docs and GUI help. It does not imply `optional`: a field that has only `absent` still reports `MISSING`. |
| `"retroactive": true` | Editing the field re-prices existing save data. `gen_docs.py` renders a banner for it. The GUI builds no gate or warning from it, and the field's `doc`/`uiDoc` state the effect. Used on `teampl.override`. |
| `"oneLine": true` | Known to `gen_docs.py`, which renders it as a flag. No field uses it. |

## Invariants

Cross-key rules, listed in a schema's `invariants`. Each one names keys in one of these spellings (`check_schema.inv_key`, `inv_value`):

| Spelling | Resolves to |
|---|---|
| `Section.Key` | A cfg key, read as a raw string and coerced by `inv_bool`/`inv_float`. |
| `ckf.hardmode.cfg#Section.Key` | The same cfg key. `inv_key` strips the prefix. |
| `<file>#<dotted.path>` | A value inside a JSON file relative to the config directory, read off disk under that name. |

A `requires` key or `needs` entry also counts as declared only if some schema field declares it (`inv_declared`). A json field is declared under the spelling `<targets.json>#<path>`.

`reason` is the human explanation. `check_schema.py` appends it to `linkedEnable`, `ordered` and `requires` messages. `gen_docs.py` renders it for every kind.

### `mirror`

One side is generated from the other. From `teampl.schema.json`:

```json
{
  "kind": "mirror",
  "source": "ckf.hardmode.d/teampl.json#override[]",
  "target": "ckf.hardmode.d/MissionPowerLevelModel.generated.json",
  "match": ["ActionClass", "MissionPowerLevel"],
  "value": "PowerLevelFraction",
  "mergeWith": "ckf.hardmode.d/teampl.json#table[]",
  "generated": true
}
```

`check_schema.py` handles a `mirror` as follows:

1. It merges `source` rows over `mergeWith` rows, keyed by the `match` columns.
2. It keeps only the cells whose value differs from the `mergeWith` value.
3. It compares those cells with the `where`/`set` rules in `target`.

It reports these `INVARIANT` messages:

- `mirror target ... does not exist`
- `... award X has no label rule`
- `... has a label rule but the award is stock`
- `... award X vs label Y`

If the `source` file is absent, the invariant is skipped with no message and no census.

`generated: true` means the target is machine-owned, and `gen_docs.py` renders it that way. `gen_teampl_labels.py` finds its source, merge and output through this declaration (`mirror_for`), and exactly one schema must declare a mirror onto its output. `serve.py` regenerates the target in the same save transaction whenever the source file is edited.

### `ordered`

The keys must be non-decreasing, left to right. From `powerlevel.schema.json`:

```json
{
  "kind": "ordered",
  "keys": ["ckf.hardmode.d/powerlevel.json#minCap",
           "ckf.hardmode.d/powerlevel.json#maxCap"],
  "reason": "maxCap below minCap leaves nothing to clamp into; ..."
}
```

A pair out of order is reported as `INVARIANT <ka> = <va> is above <kb> = <vb>. <reason>`. The group is skipped (`SKIPPED`) if any key does not resolve, or resolves to something that is not a number (including a bool).

### `linkedEnable`

Flags that must all be true or all be false. From `teampl.schema.json`:

```json
{
  "kind": "linkedEnable",
  "keys": ["Slices.Progression", "Slices.ModelRules"],
  "reason": "Progression alone gives a correct award with a stock label; ..."
}
```

A mixed group is reported as `INVARIANT linked group half on: <on> true, <off> false. <reason>`. The group is compared only if every key resolved. Otherwise it is `SKIPPED`, and the message names the unread keys.

### `requires`

A directed dependency. When `key` is true, every key in `needs` must be true. When `key` is false, any state of `needs` is legal. From `cyberweaponslasers.schema.json`:

```json
{
  "kind": "requires",
  "key": "ckf.hardmode.cfg#Slices.CyberweaponsLasers",
  "needs": ["ckf.hardmode.cfg#Slices.ImplantsSlot08"],
  "reason": "Laser damage rules and the slot-8 implant payloads describe the same items."
}
```

`cyberweaponsclaws.schema.json` declares the same shape for `Slices.CyberweaponsClaws` → `Slices.ImplantsSlot06`.

`check_schema.py` grades a `requires` as follows:

| Condition | Grade |
|---|---|
| `key` true and a `needs` key false | `INVARIANT requires: <key> is true but <need>, which it needs, is false.` |
| `key` not declared by any schema | `MISSING` (also counted as skipped) |
| `needs` absent or empty | `MISSING` (also counted as skipped) |
| a `needs` entry not declared by any schema | `STALE` |
| `key` false | counted as `vacuous`, not compared |
| `key` or a `needs` key declared but not on disk, or not read (`--no-cfg`) | `SKIPPED` |

`serve.py:requires_pass` applies the same declarations when a save is made:

- **Upward.** A save that turns a dependent on also turns on everything it needs, transitively, and lists every key it changed.
- **Downward.** A save that turns a needed key off while its dependent stays on is refused with `SaveRefused`.

For a key absent from the cfg, the editor uses the schema `default`. `check_schema.py` reports that same key as `SKIPPED`.

### Skip census

`check_schema.py` prints these lines on every run, whether or not anything was skipped:

```
requires: <n> declared, <n> compared, <n> vacuous (dependent off), <n> skipped.
ordered: <n> declared, <n> compared, <n> skipped.
linkedEnable: <n> declared, <n> compared, <n> skipped.
overlays: <n> declared across <n> schema file(s), <n> csv/tsv on disk, <n> unclaimed, <n> unclaimed by design (<names>).
```

`SKIPPED` lines do not change the exit code. A run that prints `N declared, 0 compared` did not evaluate those invariants, even when it also prints `0 problem(s).`

## What `check_schema.py` enforces

```
python schema/check_schema.py --game <game dir> | --config <BepInEx/config dir> [--schema DIR] [--no-cfg]
```

- `--game` resolves to `<game>/BepInEx/config`.
- `--no-cfg` skips reading `ckf.hardmode.cfg`. Cfg fields are still counted as declared but are not looked for, and every invariant that names a cfg key is `SKIPPED`.

The script exits 1 if it finds any problem and 0 otherwise. Problems print sorted by class and then by message, followed by the `SKIPPED` lines and this summary:

```
<n> problem(s). <n> cfg key(s) on disk, <n> declared across <n> schema file(s).
```

| Class | Raised for |
|---|---|
| `STALE` | a cfg key on disk that no schema declares<br>a top-level key in a `targets.json` file that no schema claims as a `section` (only runs for schemas that declare `section`, so it is inactive today)<br>an unclaimed or double-claimed `.csv`/`.tsv` in `ckf.hardmode.d/`<br>a `requires` whose `needs` entry is undeclared |
| `MISSING` | a declared cfg key absent from the file<br>a declared json path absent from its file, unless `optional`<br>a `targets.json` file not on disk (`sidecar ... not on disk`)<br>a declared `section` not found in its file<br>a declared overlay not on disk<br>a `requires` with an undeclared `key` or empty `needs` |
| `RANGE` | a value outside `range` (including table cells, `keyedBy` keys and `reference` rows)<br>a cfg value that does not coerce to its `type` |
| `INVARIANT` | a violated `mirror`, `ordered`, `linkedEnable` or `requires` |

`serve.py` runs the script on a staging copy of every file the script reads (`files_check_schema_reads`) with the proposed bytes applied. `BLOCKING = ('RANGE', 'INVARIANT')`: those two classes refuse a save, and `STALE` and `MISSING` do not.

`check_schema.py` does not check `enabledBy`, `ui`, `label`, `default` on json fields, `sortBy`, `absent`, `retroactive`, `format`, `generated`, or unknown top-level keys in a slice file. For unknown keys, the plugin reports them at launch (`ConfigDoc.ReadSection`), and the editor lists them without grading (`serve.py:stray_keys`).

A whole missing slice file is `MISSING` like any other absence; `make_release.py` `CONFIG_FILES` is what refuses a release without it.

## Generators

Run these from the repository root after editing a schema. `gen_binds.py` and
the generated docs support public source builds. The cfg template belongs to
the maintainer release path; a DLL-only source build does not use it.

| Script | Output | Check mode |
|---|---|---|
| `scripts/gen_binds.py [--schema DIR] [--out FILE]` | `mods/CKFHardMode/Plugin.Binds.g.cs`: `Binds.All`, one `Def<T>(section, key, default)` per cfg field, sorted by (section, key), with no description argument. `Slices.Init` binds every row. | `--check`: exit 1 if the output is missing or stale |
| `scripts/gen_cfg_template.py [--schema DIR] [--plugin-cs FILE] [--out FILE]` (not published; release builds only) | `release/ckf.hardmode.cfg.in`, the shipped `.cfg` with declared defaults in BepInEx's layout and a literal `@VERSION@` for `make_release.py` to fill. Plugin name and GUID are read from `Plugin.cs`. Uses `gen_binds.collect`. | `--check` |
| `scripts/gen_docs.py [--schema DIR] [--out FILE]` | `docs/config-reference.md`, subsystems in schema-filename order, deterministic | none |
| `scripts/gen_teampl_labels.py --game DIR \| --config DIR [--schema DIR]` | the `mirror` target, `ckf.hardmode.d/MissionPowerLevelModel.generated.json` | `--check`; `--strip-rules` is a one-time migration |

`gen_binds.py` and `gen_cfg_template.py` exit 2 on a schema error.

Every cfg key is a bool: `gen_binds` requires exactly one `"in": "cfg"` field per slice (its toggle), and `gen_cfg_template.bepinex_value` refuses any other type rather than guess how BepInEx would render it. The template, filled in and converted to CRLF, was byte-identical to the `.cfg` BepInEx wrote from the 4.0.0 DLL [measured]. `make_release.py --selftest` runs `gen_cfg_template.py --check`.

After changing any cfg field, re-run `gen_binds.py` and `gen_cfg_template.py`. After changing any schema, re-run `gen_docs.py`.

## What the schema does not cover

- **Overlay and lever-sheet contents.** The schema does not describe columns, rows or operators; the file header is the authority. See [`../docs/overlays.md`](../docs/overlays.md). An editor save of a sheet is therefore reported `NOT VALIDATED AGAINST A SCHEMA` ([`../gui/README.md`](../gui/README.md#save-and-validation)).
- **The enemy-gear overlays.** `ArmorModel.csv`, `WeaponModel.csv` and `MonsterTypeModel.csv` are unclaimed by design.
- **`ckf.hardmode.selfcheck.csv`.** The regression suite's input. `selfcheck.json`'s `file` field only names it.
- **`MissionPowerLevelModel.generated.json`.** This file is a schema output. It is checked by the `mirror` invariant and is outside the overlay census, which counts only `.csv`/`.tsv`.
- **`_`-prefixed metadata keys in slice files** (`_version`, `_doc`). They are not declared, and the editor ignores them by prefix.
- **`ckf.hardmode.rules.json`.** It is not part of the 4.0 layout, and the plugin logs an error if it is present (`Plugin.cs`).

## Related

- [`../docs/config-reference.md`](../docs/config-reference.md): generated per-key reference
- [`../docs/overlays.md`](../docs/overlays.md): overlay CSV dialect
- [`../gui/README.md`](../gui/README.md): the config editor
- [`../docs/workflow.md`](../docs/workflow.md): build, test and release loop
- [`../docs/gotchas.md`](../docs/gotchas.md): traps
