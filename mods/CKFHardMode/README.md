# CKF Hard Mode

Custom difficulty beyond the in-game sliders, without touching the encrypted
database. See `../../docs/power-and-progression.md` for how this works and why.

**This plugin changes how the game plays and does nothing else.** Everything
that only *read* the game — dumping tables, listing a type's members, tracing a
method — lives in **CKF Data Dump**, a separate plugin with its own GUID and
config file. Neither depends on the other.

This file covers **installing, building and reading the log**. It documents no
config keys: every key, its type, its default and its prose is generated from
`schema/*.schema.json` into
[`../../docs/config-reference.md`](../../docs/config-reference.md).

## The ten subsystems

Nine sections in `ckf.hardmode.json`, plus the one key left in
`ckf.hardmode.cfg`. 3.0 moved 21 of the 22 cfg keys into the document; the
section names below are its top-level keys.

| Section | What it does |
|---|---|
| `[General] Enabled` (cfg) | Master switch, and the only BepInEx bind left. Off runs the game unmodified without removing the plugin. It stays in the `.cfg` because it is the switch that has to work when `ckf.hardmode.json` does not exist at all |
| `"difficulty"` | Widens the game's own custom-difficulty sliders past their stock `Min`/`Max` bounds. Sets no values itself — the sliders do that |
| `"modelrules"` | Applies per-row edits from `rules.json` and the `ckf.hardmode.d/` overlays, inserts rows the shipped tables lack, and carries the writable-column probe and the rule trace |
| `"powerlevel"` | Clamps the computed mission Power Level to its own bounds instead of the game's ceiling of 10 |
| `"teampl"` | Substitutes the Team Power Level a mission awards, per `(ActionClass, MissionPowerLevel)` cell. **Retroactive** — re-prices every past mission at load |
| `"missions"` | Adjusts payment, XP and mission level per `MissionTypeId`, before the game does its own arithmetic |
| `"rewardcurve"` | Replaces the game's hardcoded baseline payment / XP / bonus step table, keyed on `PowerLevelUnscaled` |
| `"fatigue"` | Tires mercs out across missions via the game's own temporary traits, scaled by power level, mitigated by Wound Resist. **Writes to your save** |
| `"elapse"` | Charges the crew when a mission's window closes unplayed: credits off the balance, Stress onto mercs linked to that contact. **Writes to your save** |
| `"selfcheck"` | Asserts named rows' columns against expected values at startup. Diagnostic; off by default |

> **`"fatigue"` and `"elapse"` both ship with `"enabled": true`, and both
> write into your save.** Fatigue inserts into
> `GameCharacterTrait`; Elapse calls `SaveManager.SpendCredits` and writes
> `NegativeTraitValue` onto the engine's cached `PlayerModel`. Neither is a
> read-only adjustment of what the game loads. Back up your saves, or set both
> sections' `"enabled"` to `false`, before the first real run.

## 1. Install BepInEx 6 (IL2CPP)

BepInEx **6** is required — IL2CPP support does not exist in BepInEx 5. As of
now the IL2CPP builds are still published as *bleeding-edge* rather than a
final stable release.

Download `BepInEx-Unity.IL2CPP-win-x64` from the
[BepInEx releases / builds page](https://github.com/bepinex/bepinex/releases)
and extract it into the **game root** — the folder containing the game `.exe`,
not the `_Data` folder.

Launch the game once and let it sit. The first run generates the Il2CppInterop
assemblies and takes noticeably longer than a normal launch. When it's done
you should have:

```
<game>/BepInEx/config/BepInEx.cfg
<game>/BepInEx/LogOutput.log
<game>/BepInEx/interop/CoreRPG_v1.dll     <- the important one; RPG.Database.* lives here
<game>/BepInEx/plugins/                   <- create if missing
```

If `interop/CoreRPG_v1.dll` isn't there, interop generation didn't finish —
check `LogOutput.log` before going further.

**After a game update**, `GameAssembly.dll` changes and the interop assemblies
go stale. BepInEx regenerates them on the next launch, slowly again. If a mod
then logs "could not resolve", the game renamed something — point CKF Data
Dump's `[Diagnostics] DumpMembers` at the type and compare.

## 2. Build

Requires the .NET SDK (6.0 or newer).

```
cd mods\CKFHardMode
dotnet build -c Release -p:GameDir="C:\Path\To\Cyber Knights Flashpoint"
```

`GameDir` defaults to the usual Steam location; override it if yours differs.
On success the build copies `CKFHardMode.dll` into `BepInEx\plugins\`
automatically.

## 3. Configure

No key is reproduced here, because they are generated. Everything lives in
`BepInEx/config/`: `ckf.hardmode.json` — one document holding nine subsystem
sections — plus `ckf.hardmode.cfg` (one key), the `ckf.hardmode.d/` overlay
directory, `ckf.hardmode.rules.json` and `ckf.hardmode.selfcheck.csv`.

**3.0 merged five sidecars and then 21 cfg keys into that one document.**
Phase 2 turned `ckf.hardmode.{elapse,fatigue,missions,rewardcurve,teampl}.json`
into five sections, byte-for-byte what each file used to hold, with nothing
inside a section moved. Phase 3 then emptied `ckf.hardmode.cfg` into four more
sections — `modelrules`, `powerlevel`, `selfcheck`, `difficulty` — and folded
each subsystem's `Enabled` into its section's own `"enabled"`.

**Correction, 2026-09-07.** That paragraph used to end "the 2.x files are kept
as `.pre-3.0-backup` and nothing reads them". It described a migration in
`Defaults.cs` which, on a first 3.0 launch, folded each 2.x sidecar into the
document and renamed it. The migration was deleted today along with everything
else `Defaults.cs` wrote, so **nothing creates a `.pre-3.0-backup` any more and
a 2.x config directory is not migrated at all.** Extracting the zip drops the
shipped `ckf.hardmode.json` in beside whatever sidecars are already there; the
sidecars keep their own names, are read by nothing, and if you want your 2.x
values you copy them across by hand.

`ConfigDoc.cs` reads the document once and hands each loader its section, and
reports at Error any top-level key that is not one of the nine sections or
`_version` — a misspelled section belongs to no loader, so without that check a
whole block of settings would be ignored in silence.

**What the merge costs, said plainly.** One syntax error anywhere in
`ckf.hardmode.json` now takes every subsystem down, and since Phase 3 it takes
their switches with it rather than only their amounts. That is stated in the
log: `ConfigDoc` reports the parse failure at Error, and each subsystem says
whether it is off because the document could not be read or because someone set
its `"enabled"` to false. `[General] Enabled` is unaffected — it is a BepInEx
bind and BepInEx writes its file whatever else on disk is broken.

### Where those files come from

**The release zip carries them as loose files; extracting it is what puts them
on disk.** `scripts/make_release.py` writes these eight under `BepInEx/config/`
in the zip — the seven named in its `CONFIG_FILES`, copied from the live
`BepInEx\config\` the editor edits (or `--config DIR`), plus
`ckf.hardmode.cfg` rendered from `release/ckf.hardmode.cfg.in`. Any other
`.csv`/`.tsv`/`.json` in the live `ckf.hardmode.d/` ships too:

| File | What it is |
|---|---|
| `ckf.hardmode.json` | the merged config document, nine sections |
| `ckf.hardmode.cfg` | the one key left, `[General] Enabled` |
| `ckf.hardmode.rules.json` | 293 row-edit rules over 8 model types |
| `ckf.hardmode.selfcheck.csv` | the regression suite's expectations |
| `ckf.hardmode.d/ArmorModel.csv` | 180 overlay rows |
| `ckf.hardmode.d/WeaponModel.csv` | 385 overlay rows |
| `ckf.hardmode.d/MonsterTypeModel.csv` | 2427 overlay rows |
| `ckf.hardmode.d/MissionPowerLevelModel.generated.json` | 30 victory-screen label rules |

`ckf.hardmode.cfg` is on the list even though BepInEx rewrites it on launch from
the key `Plugin.cs` binds: shipping it means the player's first launch is not
what creates it, and a config directory without it is worth reporting, because
it means the extraction did not land here.

**Correction, 2026-09-07.** Everything above used to read differently, and all
of it was true up to today:

- *Claimed:* "Since 3.0 the DLL carries them. Seven files are
  `EmbeddedResource`s in `CKFHardMode.dll`." *Actually:* the seven
  `<EmbeddedResource>` entries were removed from `CKFHardMode.csproj` today.
  **The DLL embeds nothing at all.** The list above is eight rather than seven
  because the `.cfg` — previously excluded on the grounds that BepInEx owns it —
  is now shipped and checked with the rest.
- *Claimed:* "**Write-if-absent, never overwrite.** … A file you delete comes
  back at the shipped values on the next launch, which is the way to reset one
  … one summary line — `Defaults: N written, M already present, K failed, of 7
  embedded file(s)`." *Actually:* `Defaults.Install()` **writes nothing, renames
  nothing and deletes nothing.** It counts how many of the eight paths exist,
  logs one summary line — `Defaults: N of 8 config file(s) present.` — and names
  every file that is missing or that it could not check. A file you delete stays
  deleted; the way to reset one is to extract the zip's `BepInEx\config` over
  the game folder again, which overwrites the settings files with the shipped
  ones, so copy anything you have retuned somewhere else first.
- *Claimed:* "**Upgrades fill missing keys and nothing else** … the previous
  copy is saved as `ckf.hardmode.json.pre-<version>-backup`." *Actually:* the
  key-fill pass is gone with the rest of the writing, so **nothing creates a
  `.pre-<version>-backup`** and a document from an older build is left exactly
  as it is. `Defaults.DocVersion` still exists and still names the document's
  layout version; what reads it now is `check_doc_version()` in
  `make_release.py`, which refuses a release where that literal disagrees with
  the `_version` in the `ckf.hardmode.json` being packaged (the live config's,
  since 2026-09-11).
- *Claimed:* "**Upgrading from 2.x.** A config directory with the five 2.x
  sidecars and no `ckf.hardmode.json` is migrated on the first 3.0 launch."
  *Actually:* **there is no migration.** See the correction under "3. Configure"
  above.

**Correction, 2026-09-11.** The paragraph below used to place the shipped
files in this repo, under `mods/CKFHardMode/defaults/` and `overlays/`. Those
were hand-synced copies of the live files and were deleted today; the live
`BepInEx\config\` is the only copy, and `make_release.py` packages it.

**What this buys.** Retuning the mod is editing the live config, in the editor
or by hand, and re-running `python scripts/make_release.py`. There is no
`dotnet build` in that loop unless
the C# changed. The check that used to prove the DLL carried the current bytes
of each default — `check_embedded` in `make_release.py`, a substring search over
the assembly — is deleted along with the `embedded_sources` table it walked,
because there is nothing left in the DLL to be stale.

**The 21 keys that used to be in `ckf.hardmode.cfg` are NOT read across.**
David's ruling, 2026-09-03. They come from the shipped default, and the log says
so at Warning, naming the sections your old `.cfg` still has — BepInEx leaves a
key it did not bind, so the file and your old values are both still there to
copy from. `docs/config-reference.md` says which section each key went to.

| I want to… | Do this |
|---|---|
| Know what a key does | [`../../docs/config-reference.md`](../../docs/config-reference.md) |
| Edit without a text editor | `python gui/serve.py` |
| Check the live install | `python schema/check_schema.py --game "<game dir>"` |
| Check what the zip will ship | the live install is what ships, so the line above; `make_release.py` runs the same check on its snapshot and refuses on any problem |
| Install, dump, change, test | [`../../docs/workflow.md`](../../docs/workflow.md) |
| Write or debug a rule | [`../../docs/rule-engine.md`](../../docs/rule-engine.md) |
| Write an overlay CSV | [`../../docs/overlays.md`](../../docs/overlays.md) |
| Avoid a known trap | [`../../docs/gotchas.md`](../../docs/gotchas.md) |

Relaunch to apply — config is a text edit, not a rebuild. Only new C# needs
`dotnet build`. The one-line rule that used to apply to a comma-separated `.cfg`
list is gone with the keys: `modelrules.probeTables` is a JSON array now.

### Rules and overlays

`ckf.hardmode.rules.json` holds per-row edits. **The overlay directory has no
config key** — `ckf.hardmode.d/` is read if it exists, and merged after
`rules.json` in filename order, so an overlay line wins over a broad sweep that
also caught the row. A `.csv`/`.tsv` there is a per-table overlay, one line per
row edited; a `.json` there is an ordinary rules file, which is how `rules.json`
gets split up per table.

The shipped set is **three CSVs, one per table** — `ArmorModel.csv` (180 rows),
`WeaponModel.csv` (385), `MonsterTypeModel.csv` (2427) — plus the generated
`MissionPowerLevelModel.generated.json` (30 rules). It was 51 files split per
gear family until 2026-09-03; `scripts/merge_overlays.py` merged them and proves
the compiled rule set is unchanged.

`Overlays.Load` globs `.csv`, `.tsv` **and** `.json`, so its "N file(s)" count
includes the generated mirror: four files, not three, and 3022 rows rather than
the CSVs' 2992.

**Clones come from overlays, not from `rules.json`.** A row is inserted by an
overlay CSV's `_clone` column, naming the id of the row to copy. The live
`ckf.hardmode.rules.json` has **zero** clone rules: 293 rules over eight models,
none of them a clone (`EffectModel` 133, `JobNodeModel` 72, `TalentModel` 43,
`WeaponModel` 33, `MatrixEffectModel` 8, `RuleModel` 2, `ImplantModel` 1,
`MonsterTypeModel` 1) [measured, live install].

`overlays/ckf.hardmode.rules.json` was a byte-for-byte copy of the live file,
re-synced 2026-09-03, until it was deleted 2026-09-11; the live file is the only
copy. The pre-teampl-split copy it replaced (326 rules) is kept at
`overlays/_archive/ckf.hardmode.rules.pre-teampl-split.json`.

**Correction, 2026-09-03.** That archived file was described here as holding 33
`MissionPowerLevelModel` rows "that now live in
`ckf.hardmode.d/MissionPowerLevelModel.generated.json`". Only **30** of them do.
The other three — `(ActionClass 1, MissionPowerLevel 0) → 0.08`,
`(2, 0) → 0.04`, `(3, 0) → 0.02` — set exactly the value the stock table already
holds at those cells, so they were no-ops. `teampl.json`'s `override` carries
only cells that differ from stock and covers `MissionPowerLevel` 1–10; the `table`
underlay spans −10 to 10 and supplies `(1,0) = 0.08` itself
[measured, live `teampl` section]. Nothing was lost in the split. None
of the 30 cells that did move are no-ops.

**Column names come from CKF Data Dump.** Run it once, then read the header row
of `BepInEx/ckf-dump/<Table>.csv`. A rule naming a column that doesn't exist
logs one warning and does nothing; a rule naming a *table* that doesn't exist is
listed by name at startup, because otherwise it fails silently.

## Reading the log

`BepInEx/LogOutput.log` is where every claim below is checked.

### Rules loaded

```
ModelRules: loaded 293 rule(s) across 8 model type(s), plus N clone rule(s).
Overlays: 4 file(s), 3022 row(s) merged, 372 of them inserts.
ModelRules: 192 materializer(s) found, 11 hooked across 11 model type(s).
  EffectModel: 133 rule(s) indexed on EffectId — 133 value(s), worst bucket 1, 0 unindexed
  ArmorModel: 9 rule(s) indexed on ArmorId — 7 value(s), worst bucket 2, 1 unindexed
  RuleModel: 2 rule(s), no index (every row tests all of them)
```

The counts are the combined load, `rules.json` plus overlays — which is why a
clone count appears at all. Then one line per hooked table. **"no index" means
every row tests every rule for that table** — fine at two rules, worth a look at several hundred. A model gets
an index when at least half its rules select one exact integer column; see
[`../../docs/rule-engine.md`](../../docs/rule-engine.md) §Indexing. Only tables
a rule targets get hooked, because every hook is a postfix the game runs per
row.

### Confirming a rule landed

`TraceRules = N` logs the first N rows each rule changes:

```
  trace #311 MonsterTypeModel[19] PL 15: CritRate 30 -> 41   [Guard crit slope]
```

`PL` is printed whenever the row has one, which is what makes a `perLevelAbove`
curve readable — one line per level. A rule that matched but moved nothing says
**`matched, nothing changed`, which is what a read-only column looks like.**

Rows are only read when the game needs them, so a rule on PL 11-20 archetypes
traces nothing at the main menu. Turning CKF Data Dump on sweeps every bulk
reader at load and makes every rule fire there instead;
[`../../docs/workflow.md`](../../docs/workflow.md) is the one-launch procedure.

### When a rule looks applied and changes nothing

Some columns have a setter that recomputes and throws your value away. The
unsuffixed weapon stats (`Accuracy`, `BallisticDamage`, `ActionPoints`) are
aliases for the selected firing mode; the talent `Adjusted*` columns are
derived. Neither is read-only, so nothing warns.

`ProbeWritableColumns = true` writes a test value onto one row per table, reads
it back, restores the original, and reports the verdict per column to
`BepInEx/ckf-hardmode/writable_columns.csv`:

```
Table,Column,Type,Verdict,Detail
WeaponModel,Accuracy,Int64,ignored,"wrote 61, read back 60"
WeaponModel,Accuracy1,Int64,writable,
WeaponModel,WeaponName,String,read-only,
```

It is a write on the game's hot path — restored immediately, but still a write —
so it is off by default. Turn it on for one launch when a rule is not landing.

### Fatigue

`logGrants` gives one line per merc per mission plus a summary, and shows the
whole Wound Resist sum behind every threshold. Armour counts toward that sum
since 2026-09-10 and shows as `gear +N` and `armor N` on the roll line. A merc logged as skipped was
already Off-Duty and deployed anyway, which the game permits for a
story-required mission. Two lines are worth looking for on the first run:

- **`Fatigue: a save was loaded`** after loading a slot means the postfix on
  `ViewModel_GameManagement.LoadGame`/`LoadGameSlot` found the real seam. That
  patch is a guess made from the type table of an interop assembly whose method
  bodies are all native stubs, so the log is the only thing that can confirm it.
  Nothing depends on the guess — the replay guard's database check covers
  reloads on its own — but if you never see the line, say so.
- A warning naming **`ReadGameCharacter`** means that reader is gone, every merc
  reads as not-the-Knight, and the Cyber Knight is no longer getting his own
  odds and duration.

**The flat settings were removed on 2026-09-07** — David's ruling. Every fatigue
setting that had a `byPowerLevel` analogue is off the config surface, because a
one-anchor curve at power level 1 does the same job: `runningEmpty.chancePercent`,
`.durationDays`, `.minAffected`, `.maxAffected`,
`runningEmpty.knight.chancePercent`, `runningEmpty.knight.durationDays`,
`offDuty.durationDays` and `offDuty.knight.durationDays`. The four `byPowerLevel`
tables are now the only place those numbers live. Three consequences to know
about:

- **Your existing config still loads.** The mod refuses a file carrying a key it
  does not recognise, so those eight keys are still accepted and are simply
  ignored. A file that carries any of them gets one line at load naming which,
  and deleting them changes nothing.
- **`runningEmpty.byPowerLevel` is now required** while fatigue is enabled.
  Without it there is no chance, no duration and no counts anywhere, so the
  feature refuses to load rather than run on numbers nobody chose. If one field
  is missing from every anchor of a curve, the roll or the grant that needed it
  does not happen and the log names the key and the merc — except `minAffected`,
  whose absence legitimately means "no floor" and is only a warning.
- **A mission whose power level could not be read now uses the lowest anchor** of
  each curve instead of the old flat value. The once-per-session warning about an
  unreadable `PowerLevel` is still there and says so.

**Solo missions are exempt** (2026-09-10). A mission with one merc on it rolls
nobody and escalates nobody; the log says `Solo missions are exempt`.

**Every roll line says what each Wound Resist reader returned** (2026-09-10), for
example `; read trait 6, effect 0, implant 3 (2 with WoundRes, 3 via DataDb), job
14`. `via DataDb` means the row came back without its joined effect and the mod
looked it up; `UNRESOLVED` means that lookup failed and the row counted 0. Run63
is why: it logged `no resist` for four mercs, and nothing in the log could say
whether they had no resist or the mod never saw it.

Full design: [`../../docs/character-fatigue.md`](../../docs/character-fatigue.md).

### Elapse

Once per session, on the first tick:

```
Elapse: first tick at turn 1384: 565 game-log row(s), 20 of them LogTypeId 202; board 4 mission(s), 3 with a contact, PowerLevelUnscaled 5-7; 0 expiry row(s) stamped 1383.
```

**That line is the instrument proving it can see.** The reference save should
show about 20 `LogTypeId 202` rows; a session reporting `0 of them` is a broken
reader, not a quiet board.

Then one block per expiry, for the first `LogFirst` of them, naming the mission,
its contact, its tier and its power level, and every write it made. Spends are
recorded at warning level, and a stress write must say **`via cached
PlayerModel`** — writing the database row alone does not move the bar.

Warnings to take seriously: `has no match in the previous board snapshot` on any
tick but the first after a load; `two live missions share the title`; `came back
null or unconvertible`; `The write may not have taken`; `no cached PlayerModel
for merc`. Full design:
[`../../docs/mission-elapse-penalty.md`](../../docs/mission-elapse-penalty.md).

### When nothing at all happened

Check for `Disabled via config; nothing patched` first. Run53 / Log15 was a
whole session spent discovering `[General] Enabled` was off.

## How the difficulty patch works

The startup log names every bound that moved:

```
Difficulty: GameDifficultyModel — 41 properties, 23 Min/Max pair(s), widened 23 by x3.
  PowerLevelScalar [0.5, 1.5] -> [0.17, 4.5]
  BasePowerLevelOffset [-5, 5] -> [-15, 15]
```

A Harmony postfix on `GameDifficultyModel.ReconfigureDifficulty` and
`ConfigureDefaults` lets the game configure difficulty normally, then widens the
`Min`/`Max` bounds afterwards. The bounds land on the model the game itself
uses, so power-level calculation and save writes stay consistent — the game
persists them through its own code path.

`SliderRangeMultiplier` stretches each bound by direction, not by sign-blind
multiplication. Set it to `1` to leave the ranges stock.

| Bound | Multiplier 3 applied as | Example |
|---|---|---|
| Positive ceiling | multiplied | `1.5` -> `4.5` |
| Negative floor | multiplied, further down | `-5` -> `-15` |
| Positive floor | divided, toward zero | `0.5` -> `0.17` |
| Exactly zero | left alone | `0` -> `0` |

Bounds are stretched from the values captured the first time the model is seen,
not from whatever is on it now: the postfix runs on every reconfigure, and
scaling the current maximum would compound each time.

All members are resolved reflectively rather than against compile-time types, so
the plugin builds without exact signatures and logs a warning instead of
crashing when a game update renames something.

## Mission rewards and Team Power Level

**There is no pattern layer.** The `missions` section is one entry per
`MissionTypeId`, matched exactly and case-insensitively — no substring bucket,
no `PureCombatTypes`, no `SoloHackTypes`. Every mission is logged with its
classification whether it matched or not, so a type with no entry shows up as a
`[-]` line rather than silence. Field meanings:
[`../../docs/mission-rewards.md`](../../docs/mission-rewards.md).

The `"missions"` section controls payment and XP only. The Team Power Level a mission
awards is a `MissionPowerLevelModel` lookup: 63 rows, three `ActionClass` bands
× 21 relative power levels, exactly ×2 apart. **[measured]**, from 127 completed
missions classed by the game itself:

| ActionClass | Missions | Rate |
|---|---|---|
| 0 | `LEGWORK` only, always PL 0 | no band exists; worth nothing |
| 1 | story and Power Play | full |
| 2 | Treaty contracts — the proc-gen board | half |
| 3 | solo hacks — every `HackCPU` / `HackFile` / `HackLoot` | quarter |

The domain is **0-3**, not 1-3; the shipped table covers only 1-3.
**Class 3 wins over its source**: `M_PGenPower_Icarus_M1_HackCPU` is class 3,
not class 1. Two of the 127 do not fit the naming pattern at all
(`M_SynDebts_StartRaid` is class 2, `M_Era_Treaty31_UNABreakup` is class 3), so
read the class off the row rather than predicting it from the id.

Changing what a hack job awards is therefore a rule, with no patch:

```json
{ "model": "MissionPowerLevelModel", "where": { "ActionClass": 3 },
  "multiply": { "PowerLevelFraction": 0.5 } }
```

> An earlier 2.1.0 build scaled the hack award in code, by bracketing the
> victory screen to attribute an otherwise context-free call on
> `GameDifficultyModel`. That is removed. **A rule beats a hook whenever the
> game has already modelled the distinction you want**, and here it had.

## What the runs established

One line each; full records in the linked docs.

- **Run 42** — a CKF Data Dump sweep and row cloning cannot be used together.
- **Runs 44-47** — fatigue's `GameCharacterTrait` insert, proven live before the
  feature existed: nested inside the `InsertGameScore` postfix, durable across
  save and reload, expiring on schedule.
- **Runs 49-52** — `SaveManager.SpendCredits` moves the balance; writing the
  credits row does not, because the engine writes its live `GameDataModel` back
  over it every tick. `StressScore` is the Discontent bar, not Stress.
- **Runs 48, 56** — every `LogTypeId 202` expiry row seen so far carried
  `turn - 1`, and the `GameMissionModel` row is deleted when the window closes,
  so an expiry resolves against the previous tick's board snapshot.
- **Logs 16-18** — Elapse's reader sees everything, and `Elapse: a save was
  loaded` fires twice because `LoadGame` and `LoadGameSlot` both run. Credits
  worked on the first live run; stress did not, because the roster panel reads
  `SaveManager.playerCache`, not the row. 2.10.1 fixed that and Log 18 confirmed
  it — seven writes, all `via cached PlayerModel`, row and cache equal for six
  ticks. In every case the penalty applied inside the same
  `ProcessTimelineToNextTurn` call that wrote the 202 row; the mod adds no lag.

**[unverified]** Every number shipped in the `elapse` section is a
placeholder. None has been played.

## Notes

- Back up your saves before the first real run:
  `%USERPROFILE%\AppData\LocalLow\TreseBrothersGames\CyberKnights\`
- `[General] Enabled = false` is a true master switch: no rules, no power level,
  progression or difficulty changes, no save writes.
- Editing `DataDb` content models changes base data for every save. Editing
  `Game*` models writes into your actual save.
- Keep this for personal use.
