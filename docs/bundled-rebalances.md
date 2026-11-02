# Prepare the combined Hard Mode download

`BundledRebalances.Init` reads the `PlayerRebalance` and `EnemyRebalance`
switches independently of `ModelRules`. For each enabled package it checks the
SQL and locale hashes in `receipt.json`. Its `GetSortedModsList` postfix adds
an active, process-local native mod entry pointing at that package. The game's
native mod loader owns SQL and locale loading; this plugin opens no database.

`BeforeWriteList` removes the synthetic entries from the argument passed to
`WriteToModsListFile`, preserving the caller's list and the player's real mod
selections. An active Player Rebalance or Enemy Rebalance Workshop item causes
the bundled handoff to refuse both packages, rather than apply overlapping
copies. Disable the corresponding Workshop items before enabling the bundled
versions. Other mods retain their normal order; bundled entries are appended
in player, enemy order.

The release enables the two native packages, slider widening, fatigue and the
limit-break effect overlay through schema defaults. Other Hard Mode slices
default to off. `LimitBreakTraits` can run through `ModelRules.Init`'s restricted
path with `ModelRules` off: only `EffectModel.limitbreak.csv` is opened as an
overlay, with no general rules file, other overlay, clones or writable-column
probe. The existing progression/general-engine consistency gate remains in
place. The old enemy overlays have their own `LegacyEnemyData` switch.

## Payload preparation

The single generated package location is the live game's config directory:

```text
BepInEx/config/ckf.hardmode.rebalances/
    player/receipt.json
    player/_data/data.sql
    player/_data/en-US.json
    enemy/receipt.json
    enemy/_data/data.sql
    enemy/_data/en-US.json
```

These are build outputs, not a second tuning source. Edit the live authoring
files using the [balance editor](../gui/README.md#workshop-player-catalogs),
then regenerate. The native SQL/locale packages are not edited by the frozen
editor. Their authoring and parser toolchain is a maintainer requirement;
ordinary installation requires neither the Mod Uploader nor Workshop
subscriptions.

From `cmd.exe`:

```bat
cd /d "D:\ckf-data-modding"
python ckf-enemy-scaling\scripts\build_overlays.py
python scripts\build_bundled_rebalances.py --config "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config"
python scripts\build_bundled_rebalances.py --config "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config" --check
```

The builder composes the existing talent exporter and player authoring document,
and the [enemy exporter](enemy-difficulty-workshop.md). It runs the installed
Data Parser into fresh temporary paths, then runs each package's independent
verifier against Official data. It also compares the complete combined database
in both application orders and refuses order-dependent results. Only the
developer-provided Official database and in-memory copies are opened.

Live input fingerprints are checked before replacement. Output commits use
unique staging names, modification-time/content guards and byte readback.
`--check` regenerates and verifies without replacing the installed packages.
The release builder requires all six files and checks their receipts again
inside the configuration snapshot before packaging them.

## Verification boundary

The native handoff harness is `tests/bundled-rebalances/Harness.csproj` in the
maintainer checkout. It checks active entries, folder resolution, repeated
requests, exclusion from saved mod selections, overlap refusal and corrupt
payload rejection. The existing fatigue harness covers its runtime logic. See the [workflow](workflow.md) for the release gates.

[measured] `Logs/HardMode-bundled-startup-20261102.log`, rows 528–529,
records both bundled entries supplied to the native list.
`Logs/HardMode-bundled-startup-Player-20261102.log`, rows 150–206, records
both SQL transactions committed and both locale files loaded from the bundled
folders. This was a main-menu startup with both Workshop copies inactive; no
campaign was loaded. Mission behavior remains subject to the Workshop packages'
documented in-game acceptance checks.
