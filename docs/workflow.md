# Workflow

Install, dump, edit, test. This is the only copy of this procedure; the plugin
READMEs cover building from source and nothing else.

## Files

| Path | Owner |
|---|---|
| `BepInEx/config/ckf.hardmode.json` | Hard Mode settings — nine sections, one per subsystem |
| `BepInEx/config/ckf.hardmode.cfg` | one key, `[General] Enabled`, the master switch. BepInEx owns this file |
| `BepInEx/config/ckf.hardmode.rules.json` | Hard Mode row edits (player gear, talents, effects) |
| `BepInEx/config/ckf.hardmode.d/*.csv` | Hard Mode overlays — enemy gear and archetypes |
| `BepInEx/config/ckf.hardmode.selfcheck.csv` | the regression suite's expectations |
| `BepInEx/config/ckf.hardmode.{elapse,fatigue,missions,rewardcurve,teampl}.json` | the 2.x sidecars, if a 2.x install left them there. Nothing reads them |
| `BepInEx/config/ckf.datadump.cfg` | Data Dump settings |
| `BepInEx/ckf-dump/*.csv` | Data Dump output |
| `BepInEx/interop/CoreRPG_v1.dll` | where `RPG.Database.*` lives — **not** `Assembly-CSharp.dll` |
| `BepInEx/LogOutput.log` | what every mod reports at startup |
| `<game>/StreamingAssets/Locales/en-US.json` | unencrypted; maps numeric ids to display names |

**Correction, 2026-09-07.** That row used to read
"`BepInEx/config/ckf.hardmode.*.json.pre-3.0-backup` | the 2.x sidecars. Nothing
reads them". Nothing produces a file with that suffix any more: `Defaults.cs`
used to migrate a 2.x config directory into `ckf.hardmode.json` and rename each
sidecar `.pre-3.0-backup` as it went, and that migration was removed today along
with everything else it wrote. A sidecar already renamed by an earlier 3.0
launch is still on disk under the old suffix and is still read by nothing; a 2.x
directory that has not seen one keeps its sidecars under their own names, which
is what the row now says.

Every one of these arrives by extracting the release zip over the game folder.
Nothing in the mod creates a config file, so a file you delete stays deleted
until you extract the zip again — and that overwrites the settings files with
the shipped ones, so copy anything you have retuned somewhere else first.

Back up saves before the first real run:
`%USERPROFILE%\AppData\LocalLow\TreseBrothersGames\CyberKnights\`

## The loop

1. Both plugins installed, Data Dump `[General] Enabled = false`.
2. Need column names, or want to see what exists? Set `Enabled = true`, launch,
   reach the main menu, quit, set it back to `false`.
3. Read `BepInEx/ckf-dump/<Table>.csv`. **The header row is the real column
   names** — that is what rules and overlays are written against.
4. Edit `ckf.hardmode.rules.json` (see [`rule-engine.md`](rule-engine.md)) or an
   overlay CSV (see [`overlays.md`](overlays.md)).
5. Run `python scripts/validate_rules.py`. It catches the dangling pointers that
   otherwise show up as a black screen.
6. Relaunch. Rules and overlays are a text edit, not a rebuild — only new C#
   needs `dotnet build`. That is true of the shipped defaults too: retuning
   what the zip carries is an edit to the live `BepInEx\config\` (in the editor
   or by hand) plus `python scripts/make_release.py`, with no build in the loop.

**Close the game before editing a `.cfg`.** BepInEx rewrites it on exit and will
undo an edit made while it is running. Keep every `.cfg` value on one line.

## What a dump actually contains

192 tables exist across the three databases. A default run — `Databases =
DataDb`, `SkipIrrelevantTables = true` — captures about 50 and skips about 28 as
art, writing or map placement. `_coverage.csv` lists what was captured with row
and column counts; `_skipped_tables.csv` lists what was skipped and why;
`_readers.csv` lists every reader attempted.

| You need | Do this |
|---|---|
| Per-save tables (`Game*`) | `[Dump] Databases = DataDb, GameDb` **and dump from inside a mission** — they are genuinely empty at the menu |
| Mission generation data (`_mission_*.csv`) | Leave Data Dump enabled and play a few in-game days; nothing is written until the factory builds a mission. These files **append** across sessions, so coverage accumulates |
| The reward curve (`_reward_curve.csv`) | A direct-call sweep, finished before the main menu — but check `[Mission] CurveSweepMaxPowerLevel`. The shipped config sets it to 10, which hides the flatline above PL 10. It can never show a *patched* curve; use `rewardcurve.logEffectiveCurve` for that |
| Mission keys and goal structure | Nothing — `BlockModel` is in the default sweep (~1.9 MB). It holds story and dialogue blocks, so you get the `SN_*` mission keys and the goal chains, **not** price or XP modifiers |
| A column that was trimmed away | Check `_dropped_columns.csv`; it records the value of every constant column removed |

If the game lives under `Program Files`, Windows may block the write — point
`[Dump] OutputDirectory` somewhere you own.

## Finding an id

Names are numeric ids everywhere. `en-US.json` is the index, keyed by the same
numbers: `WeaponName.20000`, `Monster.Name.400`, `Talent.Name.<id>`,
`ArmorName.<id>`, `JobNode.Name.<id>`, `Effect.Name.<id>`.

A talent, its base effect and its locale entries usually **share one id**
(`Talent.Name.11013` / `Effect.Name.11013`), which is the fastest way to find a
talent's effect row.

For ids that are not names — loot groups, file groups, reward types — read
`_id_constants.csv`, which resolves every named constant off the running game.

## Testing a change in game

Which action exercises which kind of change:

| Change | What tests it |
|---|---|
| Gear stats on an existing row | Reload a save and open a mission — rows are re-materialised on read |
| A cloned gear tier | Reload and enter a mission at a power level that reaches that tier |
| Roster composition, spawn pools | A **restart**, not a reload — the roster is built once at mission generation |
| Rewards, Team PL | Complete a mission and read the victory screen, then the log |
| Fatigue, elapse | Advance turns; both hook the timeline |

**Turn Data Dump off before testing gear.** Its sweep calls `ReadArmors()`, the
clones get appended to the returned list, and the game then resolves armour out
of that list rather than by id and dies on a null.

### Reading the log

| Line | Means |
|---|---|
| `ModelRules: loaded N rule(s) across M model type(s)` | the rules file parsed |
| `ModelRules: 192 materializer(s) found` | every table's row builder was hooked |
| `<table>: no index` | every row tests every rule — fine, just slower |
| `matched, nothing changed` | the rule found the row and the write was discarded. Usually a computed column; see [`gotchas.md`](gotchas.md) |
| `RowClone: N clone(s) built, N served` | clones materialised and were handed out. `built` without `served` means nothing is reaching them |
| `RowClone: <reader>(<id>) found nothing` | a dangling pointer. Fix it before launching again |
| `Difficulty: GameDifficultyModel — N properties, M Min/Max pair(s), widened M by xK` | the slider ranges were stretched |
| `Fatigue: a save was loaded` | the load postfix found the real seam |
| `Elapse: first tick` | the elapse reader is alive. A quiet session with `0 of them` is a broken reader, not a quiet board |

Set `traceRules` in the `modelrules` section to N to log the first N row edits with before and
after values. Keep a copy of the **live** log — it carries Unity messages the
saved copy does not.

For a full verification pass, set `selfcheck.enabled` true for one launch,
read the result, and turn it back off. Against a stale baseline it reports a
retune as a regression.

## Building a release

One command, from the repo root:

```
python scripts\make_release.py
```

It rebuilds `CKF-Config-Editor.exe`, runs `gui\serve.py --selftest
--frozen-exe` against it, and writes `dist\CKF-Hard-Mode-<version>.zip`.
Every check except the gate runs before anything is written, so those refusals
leave `dist\` as they found it. The gate needs the rebuilt exe, so a gate
refusal leaves it in `dist\`, with `dist\selftest-failed.log`. (**Correction,
2026-09-11:** this used to say every refusal left `dist\` untouched; `build()`
writes the exe before `gate()` runs.) `--selftest` proves each refusal can fire;
`--skip-exe` reuses the binary already in `dist\`. PyInstaller's scratch goes
to `dist\build\`.

Two things it needs and will not create:

| | |
|---|---|
| `mods\CKFHardMode\bin\Release\net6.0\CKFHardMode.dll` | `dotnet build -c Release`. It refuses if the DLL predates the version bump |
| `vendor\BepInEx-6.0.0-be.785\` | the pinned BepInEx build, unpacked once from https://builds.bepinex.dev/projects/bepinex_be. It refuses on any other build or commit |

The config files ship as loose files under `BepInEx\config\`, not inside the
DLL, and they come from the live config directory: the one the editor edits
(`gui\settings.json`), or `--config DIR`. `CONFIG_FILES` in `make_release.py`
names the seven it requires; a missing one refuses by name. Any other `.csv`,
`.tsv` or `.json` in `ckf.hardmode.d\` ships too, because the loader reads it;
anything else there is left out and named. The master switch is rendered from
`release\ckf.hardmode.cfg.in`, not copied from the live `.cfg`.

An editor save journal left in the live directory refuses. Otherwise the files
are copied to a temporary snapshot, and everything after reads the snapshot:
`schema\check_schema.py` (any problem refuses), `scripts\gen_teampl_labels.py
--check`, `Defaults.DocVersion` against the document's `_version`, the gate
(run with `--config <snapshot>`), and the zip. An editor save made during the
build cannot reach the zip unchecked.

**Correction, 2026-09-11.** This section used to say the sources were in this
repo — three in `mods\CKFHardMode\defaults\`, four in `overlays\`. Those were
hand-synced copies of the live files and were deleted today; the live directory
is now the only copy.

**A retune is a config edit and this one command.** Editing the live config and
re-running `make_release.py` is the whole loop; `dotnet build` is only for
changed C#.

A `FAIL` from the gate refuses the release. A `NOT RUN` is printed with its
reason and does not — the one that fires in practice is antivirus holding a
just-executed exe.

The version lives in `CKFHardMode.csproj` `<Version>` and in `Plugin.cs`
`PluginVersion`, and the two have to agree. `release/README.md` covers the two
text files that go in the zip.

## After a game update

`GameAssembly.dll` changes and BepInEx regenerates the interop assemblies on the
next launch — slow, expected. If a mod then logs "could not resolve", point Data
Dump's `[Diagnostics] DumpMembers` at the type and compare names.
