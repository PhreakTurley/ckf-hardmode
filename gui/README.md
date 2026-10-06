# Config editor (`gui/`)

A local web page that edits the live Hard Mode config under the game's
`BepInEx/config/`, rendered from `schema/*.schema.json`. Use this page to run it
from source, understand a refused save, or maintain the frozen executable.
Per-key meanings are in
[`../docs/config-reference.md`](../docs/config-reference.md); the schema format
is in [`../schema/SCHEMA-FORMAT.md`](../schema/SCHEMA-FORMAT.md).

The plugin and the ten settings documents currently carry version `4.1.0`.
The plugin version and settings-layout stamp are independent even when their
values happen to agree. The editor writes the live files and keeps no backup.

| File | Role |
|---|---|
| `serve.py` | Stdlib-only server. Does all file I/O and all validation. |
| `app.html` | The page. No CDN, no build step. Names no file, field, column or cfg key. |
| `settings.json` | Per-machine game/config paths, `stripReadme`, and optional Modkit paths. Not committed. |
| `modkit.py` | Guarded handoff to the separate talent repository's exporter. |
| `ckf-config-editor.spec` | PyInstaller spec used by `scripts/make_release.py`. |

## Run the editor from source

```
python gui/serve.py                         # free port on 127.0.0.1, opens a browser
python gui/serve.py --no-browser
python gui/serve.py --port 8765
python gui/serve.py --game "<game root>"
python gui/serve.py --config "<game root>\BepInEx\config"
```

| Flag | Effect |
|---|---|
| `--config DIR` | Use this `BepInEx/config` directory, bypassing `gameDir`. It must be a directory, not the `.cfg` file. |
| `--game DIR` | Game root; the config is `DIR/BepInEx/config`. |
| `--port N` | Bind this port instead of a free one. |
| `--no-browser` | Don't open a browser. |
| `--selftest` | Run the verification suite (see [Self-tests](#self-tests)). |
| `--selftest-js` | Run `app.html`'s pure functions under `node`. |
| `--frozen-exe PATH` | With `--selftest`: also run the frozen-exe cases against a built exe. |
| `--migrate` | Convert a 3.x layout to the current slice layout (introduced in 4.0; settings stamp 4.1.0) and rename the originals to `*.pre-4.0-backup`. Refuses, writing nothing, if an input is missing, the slice layout already exists, a backup exists, or `MonsterTypeModel.csv` cannot be read. Maintainer-only; players install a fresh zip. |
| `--run-check-schema --config DIR` | Must be the first argument. Runs `schema/check_schema.py` in-process and exits with its code. This is how the frozen exe validates a save. |

**Game directory.** Resolved by `serve.py:load_settings` / `default_game_dir`:

1. `configDirOverride` if set (the page sets it when the typed path ends in `BepInEx/config`).
2. Else `gameDir`. A blank or whitespace `gameDir` counts as absent.
3. Absent: when frozen, the exe's own directory if `CyberKnights.exe` sits beside it; otherwise `C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint`.

The directory can be changed in the page header and is saved to settings. At startup the editor tests whether it can write there by creating and deleting a file. The result is `ok`, `denied`, `missing`, `error` or `unset`, and it shows in the page. A save that hits a permission error is refused with the OS error text.

The editor commits straight into the live config directory. It validates a
temporary proposed tree and uses temporary files for its atomic rename, but it
keeps no persistent staging copy and no backup. To reset, re-extract
`BepInEx\config` from the release zip.

Procedure: [`../docs/workflow.md`](../docs/workflow.md). Traps: [`../docs/gotchas.md`](../docs/gotchas.md).

## Send talents to Modkit Uploader

Open **Send talent changes to Modkit Uploader** above the editor. Set **Talent
source repository** to a checkout of `ckf-talent-balance` containing
`scripts/export_talent_balance.py` with `build_export()`. Set **Modkit mod
folder** to the initialized `WorkshopContent/<ModName>` folder beside its
`<ModName>.workshop.json`, then click **Save folders**. The paths persist as
`talentProjectDir` and `modkitProjectDir` in the editor's settings file.

1. Edit talent values and click **Save** in the editor.
2. Click **Send talents to Modkit**. It regenerates the standalone repository's
   `source_content/talent-balance.json` and `provenance/SOURCE.json`, then copies
   the manifest and parser JSON into the Modkit project's `source_data`.
3. In Modkit Uploader, click **Prepare Mod Data**, then **Local Install Mod**.
   Test the changes in game before submitting the prepared version to Workshop.

The export includes all eleven classes even when their BepInEx slice switches
are off. Keep those talent slices off when testing the Workshop package to
avoid applying both implementations. The handoff uses the standalone exporter
for every table/field mapping; it exports only talent overlays. Other Hard Mode
settings remain in the BepInEx workflow.

The button requires saved edits and saved folder paths. The server validates
the config, checks source and destination fingerprints before replacement,
verifies the written bytes, and rolls back its own completed replacements if
the handoff fails. A conflicting Modkit manifest is refused for review.
Preparing SQL, installing locally, and submitting remain uploader actions.

## What it edits

Every file a schema names in `targets`, all under `BepInEx/config/`:

| File | What |
|---|---|
| `ckf.hardmode.cfg` | 45 keys: `[General] Enabled` and 44 `[Slices]` toggles. |
| `ckf.hardmode.d/*.json` | Ten settings documents stamped `4.1.0` (`difficulty`, `elapse`, `fatigue`, `implants-global`, `missions`, `modelrules`, `powerlevel`, `rewardcurve`, `selfcheck`, `teampl`), plus `MissionPowerLevelModel.generated.json`, which the editor regenerates from `teampl.json` and never edits directly. |
| `ckf.hardmode.d/*.csv` | The overlay and lever sheets a schema lists in `targets.overlays`. Only lever cells are editable. |

Not opened: `ArmorModel.csv`, `WeaponModel.csv` and `MonsterTypeModel.csv`, the generated enemy-gear overlays, which no schema claims. The nav's *Enemy Gear* group says so. `ckf.hardmode.selfcheck.csv` is not edited either.

## How editing works

### The `.cfg`

`serve.py:CfgFile` edits the file line by line:

- An existing key's value line is replaced in place and keeps its own line ending. A file with nothing edited is written back byte for byte, BOM included.
- A declared key that is missing is appended as `Key = Value` after its section's last line. A missing section is created at the end of the file. No comments are written, because BepInEx writes those on the next launch.
- Refused: a key no schema declares, a value with a line break, a value whose first non-blank character is `#`, and any cfg edit when the file could not be read.
- Keys are never deleted. BepInEx re-adds a bound key at its code default.

A gate checkbox is disabled only when the slice has no slot (`app.html`: `cb.disabled = !slot`); a key absent from the file stays settable because saving appends it. `gatedByMaster` is a separate pill: it means `[General] Enabled = false`, which stops `Plugin.Load()` before any slice, a different fact from the slice's own key being false.

Slice dependencies (`requires` invariants, `serve.py:requires_pass`): turning a slice on also turns on the slices it needs, and a note says what changed. Turning off a slice that an enabled slice needs is refused, and the refusal names the dependent slice. `linkedEnable` groups move together from one checkbox. Their keys are spelled `<file>#<section>.<path>`.

### Sidecar JSON

- Written as strict JSON. With `stripReadme` on (the default), a top-level `_readme` block is removed and the save notes say so.
- Top-level keys no schema declares are kept on disk and written back unchanged, and the page lists them. Annotation keys inside rows are hidden from the grids and preserved.
- Unset is not zero. Each value is a pair: present or absent, plus the value. On the wire, `null` means absent. The writer removes an absent key rather than writing `0`, and an unchanged value keeps its exact on-disk text (`1.0` stays `1.0`).

| Control | Empty means |
|---|---|
| Numeric cell | Absent (hatched, `— unset —` placeholder). A typed `0` is a real zero. |
| Text cell | An empty string, which is a real value. On `"format": "adjust"` columns the plugin treats empty and absent the same, so clearing one turns that slot off. |
| Matrix cell | Removes the override row. The inherited stock value shows as the placeholder. Rows and columns added with "add row"/"add col" start unset. |
| Curve chart | An unset point is not plotted, so the line breaks. |

### Lever sheets

The server grades each column (`serve.py:overlay_roles`, `overlay_editable`) and the page reads the result as data (`entry.roles`, `entry.editable`).

### Complete talent catalogs

`talent_catalog.py` is an explicit maintainer annotation pass. It adds missing
class JobNode rows and related records to the already declared talent sheets,
leaves all new override cells blank, and preserves existing override cells.
Class ownership comes from `JobNodeModel.JobId`, including every captured
version; ids are never assigned to a class by their digit prefix.

Comments show the node name and its parent when different. Attribute nodes
keep Left/Center/Right names in the EffectModel table, where their comments
list connections without claiming a required path through them. Numeric tuning belongs in editable cells, with **ships N**
placeholders. Comments omit tuning numbers, old balance notes, and repeated ids.
The `_shipped` JSON control cell carries the complete editable baselines,
including zeros, without displaying them as prose. It comes from the supplied
Data Dump. The pass adds declared node tuning and attribute effect columns,
creating the Hacker effect sheet when needed. It checks dump
coverage and refuses ambiguous or missing references, then compares the
exported assignments before writing so a catalog update cannot change tuning.

The `_group` control column becomes section headings in the editor, separating
**Talents and upgrades** from **Attribute nodes** across the class's sheets.
Neither `_group` nor `_shipped` is editable or exported as an SQL field.
Comments appear beside node ids; `_shipped` supplies the placeholders. The installed editor
reads this information from the live sheets and requires no dump.

TalentModel appears first. JobNodeModel groups each base node with its attached
upgrades, ordered by name with numeric suffixes compared numerically. Attribute
JobNode grids are omitted when their measured values and overrides are only
BuyCost 1 and zero for the other editable fields; changed or unknown values
keep the grid visible. All rows remain in the files and save model.

To refresh the annotations from an independently captured stock dump:

```bat
cd /d "D:\ckf-data-modding"
python "D:\ckf-data-modding\gui\talent_catalog.py" --config "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config" --dump "D:\ckf-data-modding\sheets\raw" --project "D:\ckf-data-modding\ckf-talent-balance"
```

| Role | Editable | Why |
|---|---|---|
| `lever` (not index 0) | yes | An override value. |
| `identity` | no | Names which rows the line expands into. Identity names come from the expander modules' `IDENTITY` lists. |
| `control` | no | Header starts with `_` (`_comment`, `_clone`, …). |
| index 0 | no | The key column. Held out even if it would grade `lever`. |

- A row is addressed by its full identity-key tuple, never by position. A key that matches zero rows or more than one row is refused.
- A blank cell means "leave the game's column alone". The writer emits an empty field, never `0` or `""`.
- A save replaces one field's character span on one line. The header, other rows, quoting, column order and trailing newline are untouched.
- An empty lever cell shows the sheet's shipped value as a placeholder when the `_comment` prose carries `Shipped: …` (`serve.py:_SHIPPED_RE`).
- Shared rows stay writable and carry `repoint: true`.
- If any expander module fails to import (`SHEET_SOURCE_ERROR`), every sheet refuses writes (`serve.py:overlay_writable`). A shortened identity list would otherwise make identity columns editable.

**Cell grammar.** On expanded sheets each cell is an adjustment (`serve.py:parse_adjust`):

| Cell | Meaning |
|---|---|
| blank | no override |
| `N` or `=N` | set |
| `+N` / `-N` | add |
| `*N`, `xN`, `XN` | multiply |

`NaN` and `Infinity` are refused, which is stricter than .NET's `double.TryParse`. On direct sheets the operator is in the column header (`Col`, `Col*`, `Col+`, `Col>`, `Col<`: set, multiply, add, clampMin, clampMax), and a cell must be a number. The one exception is a plain-set column: non-numeric text there is accepted with a warning note. `app.html:overlayCellProblem` mirrors `serve.py:overlay_check_cell` so the page can mark a bad cell before saving, but only the server refuses.

**Refused lever edits** (all raise `SaveRefused`, nothing written): the key, an identity or a control column; a cell the grammar rejects; a line break in a cell; a row key with no match, several matches or the wrong number of parts; an unknown or duplicated column name; a sheet no schema declares; a sheet that is unreadable or not UTF-8.

### Hidden and collapsed columns

Columns can leave the default grid view for three independent reasons. All keep the column in the model, the working copy and the save. The sheet's notes name each one with its reason, and a `Show N column(s)` button brings them back for that table.

- **Hidden by name.** `serve.py:HIDDEN_COLUMNS` covers `ImplantLevel`, `Deactivated`, `Rarity`, `PowerLevel` and `ImplantConflictId` ("item metadata, not a combat lever"). Never index 0. There is no row-count exemption.
- **Never changes.** `app.html:overlaySuppressed` hides a column whose value is the same on every row, with three exceptions: never the key column, never on a sheet with fewer than two rows, and never an editable column that is blank everywhere (blank means no override is set, so there is still something to edit).
- **Always zero.** `app.html:overlayZeroColumns` collapses plain-set numeric columns whose effective values are zero on every row of the displayed table. Blank cells use their measured shipped baselines; missing baselines, invalid cells and other operators keep the column visible. Pending edits are included. Attribute and talent sections are checked separately.

The named and constant rules reach the page as separate keys (`entry['hidden']`, `entry['constant']`, from `overlay_hidden` and `overlay_constant`); keep them separate. Zero detection uses the values and baselines already in the model. `app.html` names no column.

Rows can be withheld too. `serve.py:GUI_EXCLUDED_ROWS` withholds `consumables-matrix.csv` `ItemTypeId 5403`. The row stays in the file, and the plugin still expands it.

The Team PL matrix draws `MissionPowerLevel` 1–10 only (`serve.py:AXIS_WINDOWS`). A value outside that range is still drawn, and the legend explains why. The save uses every row.

## Save and validation

`serve.py:App.api_save`, in order:

1. **Stale check.** If the SHA-256 of any file the editor reads (`fingerprints`, which covers the cfg, the sidecars, the mirror and every declared sheet) changed since the page loaded, the save is refused.
2. **Build.** Adjust-grammar check, then `requires_pass`, then `apply_edits`. Any refusal raises `SaveRefused` rather than `assert`, so the checks survive `python -O`. The Team PL mirror is regenerated through `scripts/gen_teampl_labels.py` in the same save as `teampl.json`.
3. **Validate.** Every file `check_schema` reads (`files_check_schema_reads`) is copied to a temp directory with the proposed bytes overlaid, and `schema/check_schema.py` runs on that directory in a child process (`run_check_schema`). `RANGE` and `INVARIANT` block the save; `STALE` and `MISSING` are reported only. The save is also blocked if the checker could not run, or if its trailing `N problem(s).` line is missing or disagrees with the problem lines it printed.
4. **Commit** (`commit`). Each changed file is written to a temp file beside its target and fsynced. Then a journal (`.ckf-gui-save-journal.json`) naming the renames is written atomically, the renames run back to back with the mirror first (`mirror_first`), and the journal is deleted. Unchanged files are skipped. On startup `recover_journal` finishes any renames a crash interrupted, following only renames that stay inside the config directory and within one directory.
5. **Report.** `check_schema` runs again on the real directory. The response includes the notes and a reminder to restart the game, because each subsystem reads its config once in `Plugin.Load()`.

`check_schema.py` declares no columns for lever sheets, so every sheet save carries `NOT VALIDATED AGAINST A SCHEMA` in its notes. Only the grammar and row identity were checked. **Validate** runs steps 2–3 without writing. The Save button is disabled when nothing has changed, the config directory is missing, or the checker did not run at load.

## How rendering is driven by the schema

- Each field's `ui` picks the control: `form`, `table`, `curve`, `matrix`, `readonly`, `hidden`. The selftest asserts the set is exactly these six. A lever cell is an ordinary `table` cell that the server marked editable.
- `matrix` is laid over the field named by its `over`. A `readonly` field that another field declares as its `over` underlay is drawn as that matrix's grid; otherwise it is a plain grid.
- `table` has two on-disk shapes. With `keyedBy` it is an object keyed by that column (the two fatigue curves, `byPowerLevel` and `knight.byPowerLevel`, by `powerLevel`; `elapse.tiers` by `name`); without it, an array. The shape found on disk is preserved, and `keyedBy` only decides the shape of a table that doesn't exist yet. Saving an absent table empty doesn't create `{}` or `[]`.
- A string column counts as an adjust column when it declares `"format": "adjust"` (the five slot columns in `missions.json`). With no declaration, a column counts when every non-empty value parses as an adjustment.
- `retroactive` (on `teampl`'s `enabled` and `override`) is passed to the page as data. The page builds no warning or confirmation from it.
- A gate that could not be read shows as unknown, never as off. Each subsystem page has one gate control with three states: on, off, and indeterminate (unreadable). A key missing from the file is still settable ("not in the file yet — saving adds it").
- **Nav.** Groups and order come from `serve.py:SECTION_GROUPS` and `SECTION_LAST`. The master-switch section is derived from `MASTER_KEY` and pinned first. A section with several gates folds them into a `<details>` summary that reads `on/declared`, adds ` ?` when some gates are unreadable, and reads `N pages` when the section declares no gates.
- **Help text.** Uses `uiDoc`, falling back to `doc`. At render time `strip_maintainer_marks` removes evidence tags (`[measured …]` etc.), parentheticals made up entirely of citations, and a trailing citation. The schema files are not changed.
- Per-sheet notes render inside a closed `<details>`, and their text stays in the DOM.
- **Grid column width** (`app.html:colWidth`): 120% of the widest content plus 2ch, capped at 44ch.

Display-only tables in `serve.py` (none of them changes what is read or written): `SECTION_GROUPS`, `SECTION_LAST`, `AXIS_WINDOWS`, `REFERENCE_GROUPING` (groups `RuleModel.ruleReference` by `GroupId`), `HIDDEN_COLUMNS`, `GUI_EXCLUDED_ROWS`, and the derived `COST_LABELS` and `ROW_LABEL_SHEETS` (weapon-class ids drawn by name).

## Security

- Binds `127.0.0.1` only.
- GET serves only `/` and `/app.html` (the same fixed file) and `/api/model`. POST serves `/api/validate`, `/api/save`, `/api/settings` and `/api/quit`. No request path is ever mapped to a file.
- Every request must have a matching `Host` (otherwise 421). Every API request, including `/api/model`, needs the per-process token in `X-CKF-Token`, and a present `Origin` must match. The server substitutes the token into the page when it serves it.
- POST bodies are capped at 32 MB. Responses send a restrictive `Content-Security-Policy`, `nosniff` and `no-store`.
- The only path a client can supply is the game/config directory. Filenames come from the schemas' `targets`.

## Self-tests

`python gui/serve.py --selftest [--config DIR] [--frozen-exe EXE]`

The suite only reads the source config and works inside temp directories. The source is `--config` if given, else `<repo>/live-config` if that directory exists, else the config `settings.json` points at. If none of these exists, the suite exits and names what it looked for. Copy a config that is still being written (for example a synced or staged mount) to a local directory first, or the copy can fail partway.

Sections cover: the adjustment grammar; that every schema field gets a control; round trip without edits; unset vs zero; both table shapes; adjust-column inference; the server and the save transaction (mirror, the four check classes, stale fingerprints, lever-sheet writes and every refusal, `SHEET_SOURCE_ERROR` injection); `.cfg` mixed line endings and the append/section-create scenarios; concurrent requests during validation; a crash between renames; the HTTP guards; presentation (order, grouping, prose stripping, `uiDoc` on every schema); hidden, collapsed and cleared values reaching disk; `app.html` pure functions; a rendered `app.html` under a CSS-less DOM stub with `fetch` stubbed; the frozen re-entry (both argv shapes, `--run-check-schema` as a subprocess, and broken child processes that must count as "could not run"); fixture-source selection; and game-directory resolution.

- `hardcoded_names_in_app_html` fails if `app.html` names a schema path, column, cfg key, section or file. `undeclared_globals_in_app_html` fails if the page assigns an ALL-CAPS name it never declares.
- `--frozen-exe EXE` runs the frozen cases against a built exe: it serves the page, answers `/api/model` with a complete checker result, reads `docs/mission-reference.json` from its bundle, and writes settings beside itself. Teardown kills the whole process tree (`_kill_tree`) and asks the OS what is still running (`_procs_from`, `_procs_settle`). Without the flag these cases report NOT RUN, which is not a pass.
- There is no migrator block. It converted `tests/fixture-3.0.0` and compared the output byte for byte against the live config, which only ever held while that config was the shipped defaults; it was deleted rather than left reporting NOT RUN (AGENTS.md §10). `--migrate` itself is unaffected, and nothing now compares `MIGRATION_DOC_VERSION` with `Defaults.DocVersion`.
- A case that cannot run reports NOT RUN with a reason and is not counted as a pass.

`--selftest-js` extracts the region of `app.html` between `/*==CKF-PURE-BEGIN==*/` and `/*==CKF-PURE-END==*/` and runs it under `node`. Keep DOM and network code outside that region. It exits 2 if `node` is not on PATH.

The suite checks structure only. No automated check sees CSS or a drawn page, so layout, placeholders, dirty marking and the collapsed-column styling have to be checked by eye in a browser.

### Migrator details

- `migration_cfg_stamp_header` replaces only the version token in the `.cfg`'s BepInEx header line; a header of any other shape is refused before anything is written.
- Only a top-level `enabled` is removed, and only from the sections in `MIGRATION_RETIRED_GATE_SECTIONS`. The nested `credits.enabled`, `stress.enabled` and `woundResist.enabled` are live settings and stay.
- `MIGRATION_CLOSED_DIVERGENCES` is a record of closed divergences. Nothing reads it now that the selftest's diff is gone; it is kept as the record, and an entry is never the way to make a check pass.
- `IMPLANTS_GLOBAL_DOC` copies `implants-global.json`'s `_doc` word for word. Edit both together.

## Build the maintainer release executable

Players use the executable from the release zip. Building and packaging that
executable is a maintainer path. `scripts/make_release.py` runs PyInstaller on
`gui/ckf-config-editor.spec` into `dist/`, then runs
`serve.py --selftest --frozen-exe` against the result before packaging. By
hand:

```
pip install pyinstaller
pyinstaller gui\ckf-config-editor.spec          # -> dist\CKF-Config-Editor.exe
python gui\serve.py --selftest --frozen-exe dist\CKF-Config-Editor.exe
```

- The output is a single file; nothing is installed on the player's machine.
- Run the spec from the repo root. It bundles `gui/app.html`, `schema/*.schema.json`, `schema/check_schema.py`, `scripts/gen_teampl_labels.py` and `docs/mission-reference.json`. `check_schema` and `gen_teampl_labels` are both hidden imports and data files. Keep `check_schema.py` as a data file: together with the `--schema` that `run_check_schema_entry` adds when the caller names none, it is what lets the frozen checker find the schemas. Remove both and the exe validates nothing.
- `console=True`, so the listening URL and any traceback stay visible. `upx=False`, because UPX-packed exes get flagged by antivirus.
- The bundle keeps the repo layout (`gui/`, `schema/`, `scripts/`, `docs/`) under `sys._MEIPASS`, so `serve.py` derives every path the same way it does in a checkout.
- Frozen, settings are written beside the exe as `CKF-Config-Editor.settings.json`, which after install is the game root. `_MEIPASS` is deleted when the exe exits.
- Frozen, `sys.executable` is the exe itself, so `check_schema_argv` validates by spawning `CKF-Config-Editor.exe --run-check-schema --config DIR` without `--schema`, and the child resolves its own bundle. Each validation pays one bootloader unpack. The save-blocking rules are the same frozen and unfrozen.

## Known issues

- **A refused save discards all pending edits.** The Save handler calls `await load()` unconditionally after `/api/save` (`app.html:3113`), which rebuilds the working copy. **Validate** doesn't reload.
- **Nav rows can't be reached by keyboard.** Each `.navitem` is a `div` with `onclick` and no `tabindex` or `role` (`app.html:1616-1620`). The `<summary>` and the gate checkboxes inside it can be focused.
- **Stale source comments in `serve.py`.** The module docstring (`serve.py:14-27`) still describes the 3.x layout (a one-key `.cfg`, `ckf.hardmode.json`, sheets not owned). `serve.py:1056-1060` says the editor never writes overlay files. `serve.py:209-215` says "these four tables" and "nothing else in this file names … a column", but there are more tables, and `overlay_labels` checks for a column literally named `Cost` (`serve.py:1699-1700`).

## Related

- [`../release/README.md`](../release/README.md): the templates packaged with the exe
- [`../docs/workflow.md`](../docs/workflow.md)
- [`../docs/gotchas.md`](../docs/gotchas.md)
- [`../schema/SCHEMA-FORMAT.md`](../schema/SCHEMA-FORMAT.md) ([`ui` kinds](../schema/SCHEMA-FORMAT.md#ui))
