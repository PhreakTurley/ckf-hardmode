# CKF Hard Mode

In the interest of full transparency all of the code and much of the text you can read was written by an LLM. All design and tuning choices were made by me.

The mod is a BepInEx 6 (IL2CPP) plugin for *Cyber Knights: Flashpoint*.

The mod has several features. Most of them can be turned on or off individually:
1. Talent rebalance (buffs and nerfs), plus game rule tweaks that generally make the game harder
2. Missions can now generate at Power Level 11-20, if your difficulty settings put them that high. Enemies' stats and gear will continue to scale up to PL 20.
3. Greater freedom in tweaking the game's own difficulty modifiers (4x prices, 400% XP gain, etc.). You can easily grow this further.
4. Mission rewards overhauled: PL gain per mission has changed to get teams to around PL 9-10 at the end of retirement. Pure Combat missions give more money/XP. Pure hacking missions generate less PL.
5. New mechanic: Fatigue. Mercenaries might end up "Running Empty" (rolled vs Wound Resist), reducing their Initiative and XP gain for several days. If they run a mission while Running Empty, they'll be "Off-Duty" for several days.
6. New mechanic: Guaranteed pay. Skipping a mission will still deduct credits roughly equal to what you'd have paid them for it. If the mission was for a Contact one of your mercs like, they'll take bonus Stress for ignoring their friend.

Every number it uses is in a config file, editable through the GUI editor that ships with it. And if you don't like a mechanic, just turn it off with the included GUI.

Not made by Trese Brothers Games and they cannot support it.

Earlier builds (2.x through 3.0.0) were private; notes in the code, schema and
docs that cite those versions refer to them. 1.0.0 was the first public
release.

## Get the mod

Download the latest zip from this repo's
[Releases page](../../releases/latest). Extract it into the game's install
folder (the one holding `CyberKnights.exe`) — full instructions are in the
zip's `README.txt`.

## One switch per part of the mod

The mod is built in slices. Each part is one file under
`BepInEx\config\ckf.hardmode.d\` and one on/off switch in
`BepInEx\config\ckf.hardmode.cfg` — 42 switches under `[Slices]`, plus
`[General] Enabled`, the master switch that turns everything off at once.

Set a switch to `false` and that part alone stops applying. Everything else
still runs, and the part's own file is left alone: turn it back on and your
numbers are still there. Relaunch the game to apply a change. The editor
presents the same switches, or you can edit the `.cfg` in Notepad.

| Switch | What it does |
|---|---|
| `ConsumablesChems`, `ConsumablesDevices`, `ConsumablesGrenades`, `ConsumablesMatrix`, `ConsumablesMedical`, `ConsumablesSploitkits` | the six consumable families |
| `CyberweaponsClaws`, `CyberweaponsLasers` | claw and eye-laser cyberweapons |
| `Difficulty` | widens the game's own custom-difficulty sliders past their stock bounds |
| `Elapse` | the mission elapse penalty — what it costs to let a mission's clock run down |
| `Fatigue` | mission fatigue: Running Empty and Off-Duty |
| `GearClasses` | player weapon classes — recoil and the rest |
| `ImplantsGlobal` | implant multipliers that apply across the board |
| `ImplantsSlot01` … `ImplantsSlot11` | implant tuning, one switch per implant slot |
| `MissionRewards` | per-mission-type reward overrides |
| `ModelRules` | the declarative row-by-row game table edits |
| `PowerLevel` | the mission power level ceiling — lets missions generate above PL 10 |
| `Progression` | the Team Power Level award, and the victory-screen labels that mirror it |
| `RewardCurve` | the baseline reward curve |
| `RuleModel` | the game's own rule constants |
| `SelfCheck` | **off by default.** A diagnostic that writes a report and changes nothing |
| the eleven `Talents*` switches | the talent rebalance, one per class — see the table below |

**Five talent switches are named after a class the game does not have.** The
key names predate the class names and are kept exactly as they are, because
renaming one would orphan the setting a player had saved under it. Read the
right-hand column, not the key:

| Switch | Class |
|---|---|
| `TalentsAEX` | Agent EX |
| `TalentsCS` | Cybersword |
| `TalentsCyberKnight` | Cyber Knight |
| `TalentsGunslinger` | Gunslinger |
| `TalentsHacker` | Hacker |
| `TalentsSawbones` | **Scourge** |
| `TalentsSniper` | Sniper |
| `TalentsSoldier` | Soldier |
| `TalentsVanguard` | Vanguard |
| `TalentsWarMachine` | Warmachine |
| `TalentsWraith` | **Wireghost** |

## Updating from an earlier version

**Extract the new zip over your game folder and let it overwrite everything.**
There is nothing to convert and nothing to migrate: you get the version's
tuning. If you had retuned settings you want to keep, copy `BepInEx\config`
somewhere else first — the zip's copy replaces yours.

**Then delete `BepInEx\config\ckf.hardmode.json` by hand,** if you are coming
from version 3 or earlier. Before or after extracting; either is fine.

Up to version 3 every setting lived in that one file. From version 4 each part
of the mod has its own file in `BepInEx\config\ckf.hardmode.d\`. Extracting the
zip puts the new files there, but **extracting never deletes anything**, so the
old `ckf.hardmode.json` is still sitting beside them.

With both on disk the mod **refuses to run**. It does not pick one — two files
holding the same settings means one is ignored, and quietly choosing which of
your edits count is the one thing it will not do. It stops, says so in
`BepInEx\LogOutput.log`, and the game runs completely unmodified:

```
ConfigDoc: BOTH CONFIG LAYOUTS ARE ON DISK.
Plugin: stopping here. The game runs UNMODIFIED this launch.
```

Nothing is damaged and nothing is lost, but the mod does nothing at all until
you delete the old file. Delete it and relaunch. Coming from version 4, there
is nothing to delete.

## Repo layout

```
mods/CKFHardMode/   the plugin source
schema/             the config schema — one file per slice; source of
                    truth for the config, gen_binds.py, gen_cfg_template.py
                    and gen_docs.py
gui/                the config editor (serve.py + app.html)
release/            the templates make_release.py renders into the player zip
scripts/            gen_binds.py, gen_cfg_template.py, gen_docs.py,
                    gen_teampl_labels.py, make_release.py (builds the zip)
docs/               mechanics references and the workflow — start at
                    docs/README.md
tests/fixture-3.0.0/  a frozen 3.x install, the migrator's test input
vendor/README.md    which BepInEx build to unpack into vendor/ before a release
```

`schema/*.schema.json` is the source of truth for the config: `gen_binds.py`
emits `mods/CKFHardMode/Plugin.Binds.g.cs`, `gen_cfg_template.py` emits
`release/ckf.hardmode.cfg.in`, and `gen_docs.py` emits
`docs/config-reference.md`. None of the three is hand-edited.

The tuning itself — the slice files and the overlay CSVs — is not kept in this
repo. It lives in the game's `BepInEx\config\`, where the editor edits it and
the game reads it, and each release zip carries the set it was built from.

## Building a release

```
cd mods\CKFHardMode
dotnet build -c Release
cd ..\..
python scripts\make_release.py
```

`make_release.py` packages the config directory the editor is pointed at (the
game folder set in the editor, saved in `gui/settings.json`), or the one named
with `--config "<game>\BepInEx\config"`. It checks the versions agree, runs
`check_schema.py` and the Team PL mirror check over that config, builds the
editor exe with PyInstaller, runs the editor's own test suite against it, and
writes `dist\CKF-Hard-Mode-<version>.zip`. It needs the pinned BepInEx unpacked
into `vendor\` first — see `vendor/README.md`. `--selftest` runs the script's
own checks without producing a zip. `release/README.md` says what each
template is and where it lands.

`dist/` is not committed; the zip is attached to a GitHub Release.

## Converting a 3.x install — a maintainer's tool, not a player's

`python gui\serve.py --migrate --config "<game>\BepInEx\config"` converts a 3.x
config directory into the slice layout and renames the originals to
`.pre-4.0-backup`. It refuses, writing nothing, if an input is missing, if the
slice layout is already there, if a backup exists, or if it cannot read the
post-overlay `MonsterTypeModel.csv`.

**It is not part of a player's upgrade.** Players overwrite and delete the old
file, as above. The migrator exists so that nothing was lost when this version
was built here, and it stays for the same reason after any future refactor.
[David's ruling, 2026-09-15]

Its verification block — 67 cases, including seven fault injections — is
**retired from the default `serve.py --selftest`** and runs under
`python gui\serve.py --selftest --migration --config <dir>`. The default suite
reports all twelve of its subsections `NOT RUN` by name; it never passes them
and never hides them.

## Start here

- **Install, dump, edit, test** — [`docs/workflow.md`](docs/workflow.md)
- **Every setting, what it does and what it defaults to** —
  [`docs/config-reference.md`](docs/config-reference.md), or run the GUI:
  `python gui/serve.py`
- **Traps, dead ends and settings that silently do nothing** —
  [`docs/gotchas.md`](docs/gotchas.md)
- **Everything else** — [`docs/README.md`](docs/README.md) is the index

## License

The mod's own source (`mods/`, `schema/`, `gui/`, `scripts/`) has no license
file attached yet — all rights reserved by default. The zip bundles a
redistributed BepInEx build under LGPL-2.1; see `release/LICENSE-BepInEx.txt.in`
for that license's text and what it covers.
