# Prepare the combined Hard Mode download

`BundledRebalances.Init` reads the `PlayerRebalance`, `HireEveryone`, and
`EnemyRebalance` switches independently of `ModelRules`. For each enabled package
it checks the SQL and locale hashes in `receipt.json`. Its
`GetSortedModsList` postfix adds an active, process-local entry for the game's
native mod loader.

`BeforeWriteList` removes the synthetic entries from the argument passed to
`WriteToModsListFile`, preserving the caller's list and the player's real mod
selections. An active Workshop copy of any enabled bundled mod blocks the
bundled handoff. Disable the corresponding Workshop copies before using the
bundle. The game's loader applies the bundled entries after other mods, in
Player Rebalance, Hire Everyone, Enemy Difficulty order.

The release enables the three native packages and Slider Widening. Mission
Fatigue, Limit Break Traits, the legacy enemy overlays, and the other slices
are opt-in through the configuration editor.

## Payload preparation

The archive places the packages under the game's config directory.

```text
BepInEx/config/ckf.hardmode.rebalances/
    player/receipt.json
    player/_data/data.sql
    player/_data/en-US.json
    hire/receipt.json
    hire/_data/data.sql
    hire/_data/en-US.json
    enemy/receipt.json
    enemy/_data/data.sql
    enemy/_data/en-US.json
```

Use the [balance editor](../gui/README.md#workshop-player-catalogs) to author
and install the individual Workshop mods locally. For an exact installed-setup
release, stage the installed SQL and English locale files with the live Hard
Mode tuning. Use a new output directory under the ignored `dist/` tree.

From `cmd.exe`:

```bat
cd /d "D:\ckf-data-modding"
python scripts\build_bundled_rebalances.py --config "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config" --capture-installed "C:\Program Files (x86)\Steam\steamapps\workshop\content\1021210" --out "D:\ckf-data-modding\dist\task-tmp\release-config"
```

The staging command uses each package's verifier against Official data, checks
the three packages together in the installed order, and records hashes for the
exact SQL and locale bytes. It reads the live inputs without replacing them.
Pass the staged directory to `make_release.py --config`. The release builder
checks all three receipts again before packaging. Remove the staging directory
after verifying the ZIP.

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
