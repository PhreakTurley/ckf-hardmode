# Run the development workflow

Use this page for the dump, edit, validate, test, build, and release sequence. Read the [architecture map](architecture.md) first if you do not yet know which component owns the change.

## Locate the live files

All relative paths in this table start at the game directory:

| Path | Purpose |
|---|---|
| `BepInEx/config/ckf.hardmode.cfg` | Hard Mode master and slice switches |
| `BepInEx/config/ckf.hardmode.d/*.json` | Ten settings documents and generated JSON overlays |
| `BepInEx/config/ckf.hardmode.d/*.csv` | Direct overlays and lever sheets |
| `BepInEx/config/ckf.hardmode.selfcheck.csv` | Self-check expectations |
| `BepInEx/ckf-hardmode/selfcheck.csv` | Default self-check report |
| `BepInEx/config/ckf.datadump.cfg` | Data Dump settings |
| `BepInEx/ckf-dump/*.csv` | Default Data Dump output |
| `BepInEx/interop/CoreRPG_v1.dll` | Generated interop assembly containing `RPG.Database.*` |
| `BepInEx/LogOutput.log` | BepInEx and plugin log |
| `StreamingAssets/Locales/en-US.json` | Unencrypted display-name lookup |
| `%USERPROFILE%\AppData\LocalLow\TreseBrothersGames\CyberKnights\` | Save directory |

The game installation contains the only tuning copy. Hard Mode does not create missing settings files. `Defaults.Install` reports the 17 required paths declared by `Defaults.Expected` and stops there.

Current settings documents and the plugin both carry version `4.1.0`; the settings-layout stamp and public plugin version remain independent and may diverge again.

Remove these legacy files when they appear:

- `ckf.hardmode.json`: the pre-4.0 merged config. Its presence beside any current settings document stops the plugin
- `ckf.hardmode.rules.json`: retired rule file. The plugin still reads it first and logs its presence as an error

## Follow the normal change loop

1. Identify the owning schema, subsystem, overlay, or lever sheet
2. Capture fresh shipped data when the change depends on game rows
3. Edit the live configuration or source file
4. Regenerate any machine-owned outputs
5. Run schema, pointer, and subsystem checks
6. Relaunch or rebuild as required
7. Exercise the affected path in game and save the live log

Close the game before editing a `.cfg`. BepInEx rewrites the file when the process exits, and Hard Mode reads it once at startup.

## Capture shipped table data

Keep Data Dump at `[General] Enabled = false` between sweeps. Before a stock-data sweep, also set Hard Mode's `[General] Enabled = false` so Hard Mode does not rewrite rows before Data Dump records them.

For a normal content sweep:

1. Set Data Dump `[General] Enabled = true`
2. Launch to the main menu
3. Quit the game
4. Restore `[General] Enabled = false`
5. Inspect the configured output directory

`[General] Enabled` gates the table sweep and mission probes only. Diagnostics, ID collection, and specialized probes use their own settings. `TraitProbe` and `WriteProbe` can write to a save even while the general switch is false. Read `mods/CKFDataDump/README.md` before enabling a probe.

The main coverage files are:

| File | What it establishes |
|---|---|
| `_coverage.csv` | Declared, captured, capped, row, and column counts |
| `_readers.csv` | Bulk readers attempted by the sweep |
| `_skipped_tables.csv` | Tables excluded and the reason |
| `_dropped_columns.csv` | Columns omitted from table CSVs and their recorded values |
| `_id_constants.csv` | Runtime constant and enum names mapped to numeric IDs |

An empty file or absent row is not evidence until the hook, reader, sampling moment, and cap are known to cover it. A passive run records only rows the game happens to materialize.

Use these capture modes for specific questions:

| Need | Capture method |
|---|---|
| Save and per-mission tables | Add `GameDb, CoreDb` and sweep from inside a mission |
| Generated mission samples | Enable mission probes and play through mission generation; `_mission_*` files append |
| Stock reward curve | Enable the `curve` mission probe with Hard Mode off |
| Patched reward curve | Use Hard Mode `rewardcurve.json` logging |
| Mission keys and goal chains | Read `BlockModel.csv` |
| Cloned Hard Mode rows | Use `RowClone: built` and `RowClone: served` log lines; clones do not appear in a dump |

## Edit the live configuration

Run the editor from the repository:

```bat
python gui\serve.py
```

You can also use `CKF-Config-Editor.exe` or edit files directly. The editor writes the live config and keeps no backup, so copy the configuration before a large retune.

Use these format references:

- [Overlay CSV and TSV format](overlays.md)
- [Rule engine and JSON rules](rule-engine.md)
- [Schema declarations and invariants](../schema/SCHEMA-FORMAT.md)
- [Generated configuration reference](config-reference.md)

## Validate configuration and pointers

Run both validators from the repository root:

```bat
python schema\check_schema.py --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint"
python scripts\validate_rules.py --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint" --dump "D:\ckf-data-modding\sheets\raw"
```

`check_schema.py` checks declared files, values, ranges, and cross-file invariants. `validate_rules.py` needs a non-empty dump and checks table names, columns, clone sources, ID collisions, and pointers.

Use `--enabled-set` on `validate_rules.py` to resolve pointers against only the slices currently enabled in `ckf.hardmode.cfg`.

Do not launch with a dangling pointer. A missing target row can stop mission loading without a useful game log entry.

## Regenerate machine-owned files

After a schema change, regenerate all schema-derived outputs:

```bat
python scripts\gen_binds.py
python scripts\gen_cfg_template.py
python scripts\gen_docs.py
```

After a Team Power Level table change, regenerate its label mirror:

```bat
python scripts\gen_teampl_labels.py --game "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint"
```

Never hand-edit these outputs:

- `mods/CKFHardMode/Plugin.Binds.g.cs`
- `release/ckf.hardmode.cfg.in`
- `docs/config-reference.md`
- `BepInEx/config/ckf.hardmode.d/MissionPowerLevelModel.generated.json`

## Run offline checks

Use the checks that cover the changed surface:

| Surface | Commands |
|---|---|
| Schema | `python schema\check_schema.py --config config_dir` |
| Generated files | `python scripts\gen_binds.py --check`, `python scripts\gen_cfg_template.py --check`, `python scripts\gen_teampl_labels.py --check --config config_dir` |
| Editor | `python gui\serve.py --selftest --config config_dir`, `python gui\serve.py --selftest-js` |
| Release builder | `python scripts\make_release.py --selftest` |
| Rules and pointers | `python scripts\validate_rules.py --game game_root --dump dump_dir` |
| Lever converters | Each expander's `--check` and `--selftest` modes |
| C# | `dotnet build -c Release project.csproj` |

The private `scripts\run_gates.cmd phase` wrapper records each gate's exit code under `Logs/`. Some gates deliberately return non-zero for planted faults. The [build and release gotchas](gotchas.md#build--release) identify those cases.

Retired 3.x ruleset comparisons remain available only through `--ruleset-3x` on the relevant converters. The obsolete byte-for-byte migration comparison was deleted because the live config became a tuning bench. `gui/serve.py --migrate` remains available for maintainer use.

## Test the change in game

Choose the action that materializes the changed data:

| Change | Exercise |
|---|---|
| Existing gear row | Reload a save and enter a mission |
| Cloned gear tier | Enter a mission whose power level reaches that tier |
| Roster or spawn pool | Generate the mission again from the safehouse; a reload is insufficient |
| Reward or Team Power Level | Complete a mission and inspect the victory screen and log |
| Fatigue or elapse | Advance turns and inspect the subsystem log |

Set `traceRules` in `modelrules.json` to a small positive number when you need before-and-after row values. Restore it to `0` after the capture.

The live `LogOutput.log` can contain Unity messages that a later saved copy does not. Copy it before the next launch.

## Run the Hard Mode self-check

1. Set `[Slices] SelfCheck = true`
2. Launch and enter a mission
3. Quit and run the log checker
4. Restore `SelfCheck = false`

```bat
python scripts\check_run.py "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\LogOutput.log"
```

The self-check compares against explicit expectations. A valid retune can therefore look like a regression until the expectations are reviewed.

## Build Hard Mode

Run the build on the machine with the game and generated BepInEx interop files:

```bat
dotnet build -c Release -p:GameDir="C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint" mods\CKFHardMode\CKFHardMode.csproj
```

The project deploys the DLL to `BepInEx\plugins` when that directory exists. A tuning-only change needs no C# build.

## Build a player release

Run the release builder from the repository root:

```bat
python scripts\make_release.py
```

The full build requires:

- A current `CKFHardMode.dll`
- The pinned private BepInEx vendor tree
- The live configuration or an explicit `--config` directory
- All templates under `release/`
- PyInstaller for the frozen editor

`make_release.py` snapshots the configuration before validation. It refuses an editor save journal, any schema problem, a stale Team Power Level mirror, mismatched layout stamps, a version mismatch, an invalid vendor tree, or a failed editor gate.

The current release declaration requires 16 files from the live config plus the rendered `ckf.hardmode.cfg`. It also packages every additional `.csv`, `.tsv`, or `.json` in `ckf.hardmode.d`, because the plugin reads those extensions.

The builder writes:

```text
dist\CKF-Config-Editor.exe
dist\CKF-Hard-Mode-4.1.0.zip
```

`dist/` is private and ignored. Attach the finished archive to the GitHub Release manually.

Useful flags:

| Flag | Effect |
|---|---|
| `--config config_dir` | Package an explicit config directory |
| `--skip-exe` | Reuse the existing editor executable and still run its gate |
| `--out output_dir` | Change the output directory |
| `--dll plugin_path` | Use an explicit plugin DLL |
| `--vendor vendor_dir` | Use an explicit vendor tree |
| `--selftest` | Exercise release-builder refusal paths without building a release |

## Maintain the two versions

The plugin version changes only for a public release. `scripts/make_release.py:check_versions` requires these values to agree:

- `mods/CKFHardMode/CKFHardMode.csproj` `<Version>`
- `Plugin.PluginVersion`
- The built DLL metadata

The settings-layout stamp changes whenever the shape of a settings document changes. `check_doc_version` requires `Defaults.DocVersion` and every one of the ten settings documents to agree.

`MIGRATION_PLUGIN_VERSION` and `MIGRATION_DOC_VERSION` in `gui/serve.py` are hand-maintained literals. No active check compares them with the C# declarations after the old migration comparison was removed. Review them explicitly when either version changes.

## Recover after a game update

The next launch after `GameAssembly.dll` changes regenerates the interop assemblies. If a plugin can no longer resolve a type or member:

1. Use Data Dump `DumpMembers` or `FindMethods` to inspect the current runtime type
2. Compare the new member names with the source
3. Refresh `docs/_gamedb_surface.txt` when the database surface changed
4. Re-run the affected gates and game path

The [patching rules](patching-rules.md) explain why method names and interop metadata do not establish implementation behavior.
