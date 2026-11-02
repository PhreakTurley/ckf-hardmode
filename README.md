# CKF Hard Mode

CKF Hard Mode is a configurable BepInEx 6 IL2CPP plugin for *Cyber Knights: Flashpoint*. The download combines Player Rebalance and Enemy Rebalance with wider custom-difficulty sliders, mission fatigue, and the related limit-break effect changes. Older Hard Mode systems remain available but are disabled by default.

The code and much of the prose were produced with language models. David made the design and tuning decisions.

This project is not affiliated with Trese Brothers Games. Trese Brothers cannot support it.

## Install the mod

Download the current archive from the repository's [Releases page](https://github.com/PhreakTurley/ckf-hardmode/releases/latest). Extract it into the folder that contains `CyberKnights.exe`, then follow the included `README.txt`.

The plugin identifies itself as version `4.2.0`. Version `1.0.0` was the first public release. References to versions `2.x` through `3.0.0` describe private development builds.

Disable the separate Player Rebalance and Enemy Rebalance Workshop mods before enabling their bundled equivalents. Neither Workshop subscription is required. See [bundled rebalances](docs/bundled-rebalances.md) for package preparation and compatibility.

## Back up your save

Fatigue writes to the active save. The optional mission-elapse penalty also writes when enabled. Back up this directory before your first run:

```text
%USERPROFILE%\AppData\LocalLow\TreseBrothersGames\CyberKnights\
```

The project does not inspect or decrypt the save databases.

## Configure each feature

The release installs two configuration surfaces:

- `BepInEx\config\ckf.hardmode.cfg`: the master switch and slice switches
- `BepInEx\config\ckf.hardmode.d\`: settings files, overlays, and lever sheets

Use `CKF-Config-Editor.exe` to edit them, or edit the files while the game is closed. Relaunch the game after every configuration change.

`[General] Enabled` stops the entire plugin. Each `[Slices]` key controls one subsystem or data slice. Turning a slice off preserves its file and values.

Major slices include:

| Area | Switches |
|---|---|
| Bundled content | `PlayerRebalance`, `EnemyRebalance` |
| Rule engine | `ModelRules`, `RuleModel`, `SelfCheck` |
| Mission systems | `PowerLevel`, `Progression`, `MissionRewards`, `RewardCurve`, `Elapse` |
| Character systems | `Fatigue`, `LimitBreakTraits`, eleven `Talents*` slices |
| Equipment | `GearClasses`, six `Consumables*` slices |
| Legacy enemy data | `LegacyEnemyData`, `SpawnWeights` |
| Game settings | `Difficulty` |

`ModelRules` gates the legacy table overlays and lever sheets. `LimitBreakTraits` has a restricted path that applies only its effect overlay while `ModelRules` is off. The bundled native rebalances are independent of that engine.

Five talent keys retain legacy names so upgrades do not orphan saved settings:

| Config key | In-game class |
|---|---|
| `TalentsAEX` | Agent EX |
| `TalentsCS` | Cybersword |
| `TalentsSawbones` | Scourge |
| `TalentsWarMachine` | Warmachine |
| `TalentsWraith` | Wireghost |

The generated [configuration reference](docs/config-reference.md) describes every switch and field.

Cyberware authoring uses the [player-balance workflow](gui/README.md#workshop-player-catalogs); the combined download includes its prepared native payload.
Its legacy Hard Mode switches are retained for compatibility and have no effect.

## Upgrade from version 1.0.0

1. Copy `BepInEx\config` if you want to preserve custom tuning
2. Extract the new archive over the game directory and allow replacements
3. Delete `BepInEx\config\ckf.hardmode.json`
4. Relaunch the game

The pre-4.0 merged document and the current slice layout cannot coexist. When both are present, Hard Mode refuses to patch the game and reports the conflict in `BepInEx\LogOutput.log`.

## Build from source

The public checkout can build the plugin and editor:

```bat
cd mods\CKFHardMode
dotnet build -c Release
```

```bat
python gui\serve.py
pyinstaller gui\ckf-config-editor.spec
```

The plugin build needs a BepInEx 6 IL2CPP game installation that has completed its first launch. See the [Hard Mode developer guide](mods/CKFHardMode/README.md) and [config editor guide](gui/README.md).

A full player release also needs maintainer-only inputs: the live tuning, the pinned unpacked BepInEx tree, and the built plugin. See the [project workflow](docs/workflow.md).

## Navigate the repository

| Path | Purpose |
|---|---|
| `mods/CKFHardMode/` | Shipped plugin source |
| `schema/` | Configuration declarations and invariants |
| `gui/` | Local config editor |
| `release/` | Templates rendered into the player archive |
| `scripts/` | Generators and release tooling needed by a public source build |
| `docs/` | Architecture, workflow, references, and measured mechanic research |

Start with the [documentation index](docs/README.md) and [architecture map](docs/architecture.md).

## License status

The project's own source has no license file, so all rights are reserved by default. The release redistributes an unmodified BepInEx build under LGPL-2.1; `release/LICENSE-BepInEx.txt.in` identifies the covered files and source build.
