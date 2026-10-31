# Prepare Enemy Difficulty for Workshop

Enemy Difficulty ports the authored Hard Mode enemy gear, archetype adjustments
and opening-roster taper to first-party SQL. It raises `Rule` 82 to 20, while
leaving `Rule` 81 and mission-generation calculations to the game. The native
cap test and slider distinction are documented in [Power level](power-level.md#native-enemy-ceiling-rule82).

This is separate from the `ckf-enemy-scaling` PL4–20 roster project, which
preserves native stats, equipment and talents. The exporter never reads or
changes that project's policy or prepared content. Hard Mode's deprecated
enemy-scaling ownership is documented in [Tuning enemies](tuning-enemies.md).

## Authoring and outputs

`scripts/export_enemy_difficulty.py:build` reads the current official database
through `static_data.StaticData`, the installed Data Parser's declaration, and
the authored files in the game's `BepInEx/config/ckf.hardmode.d` directory:

- `ArmorModel.csv`, `WeaponModel.csv`, `MonsterTypeModel.csv`;
- the twelve `MonsterGroupMemberModel.spawn-*.csv` faction overlays.

For each named input, exactly one active file or parked `.disabled` file must
exist. Both copies or a missing input refuse the export. Slice toggles do not
filter these authoring inputs: preparation must retain the authored enemies
even when BepInEx's enemy changes are switched off. The generated receipt
records the exact paths and hashes. It is not a backup of live configuration.

Ordinary edits become sparse SQL updates. Clone rows become explicit SQL
insert/select statements, inheriting unedited columns from the current source
row after authored source updates. The SQL retains the authored IDs, gate
bounds, faction restrictions, security restrictions, weights and other values.
The BepInEx `_serveOn` control has no SQL equivalent; inserts are ordinary
database rows. New gear retains its authored service setting and receives a
display name. Validate acquisition and encounter behavior in game.

New official enemy ladders receive authored high-PL gear only when their
official PL1–10 equipment signature matches an authored ladder and all matching
donors agree on the PL11–20 equipment. Missing or ambiguous matches refuse the
export. Authored archetype changes are retained, and declared combat-stat
columns cannot backslide above PL10 within a PowerGroup ladder. See
`export_enemy_difficulty.STAT_FLOORS` for the exact columns.

Generated files under local `ckf-enemy-difficulty/` are:

| Path | Purpose |
|---|---|
| `source_content/stories.manifest` and `enemy-difficulty.json` | Data Parser input |
| `prepared/_data/` | Direct SQL and locale output for independent comparison |
| `parser_prepared/_data/` | Actual installed Data Parser output for handoff |
| `review/SOURCE.json` | Source hashes, counts, gear extensions and talent mapping |
| `review/column-ledger.csv` | Each assigned table/id/column and its origin |
| `review/talent-coverage.csv` | Baseline, middle and upper talent identities |
| `review/parser-verification.json` | Independent verification result |

The parser source uses the documented `RawSQL` and `RawText.Generic` format.
The installed parser passes raw statements through; the independent verifier
owns their database validation. The [official use case](https://cyberknightswiki.tresebrothers.com/Modding_Use_Cases#Method_B:_RawSQL_and_RawText_Inside_the_JSON_Data_Parser)
documents that route. The [Data Modding process](https://cyberknightswiki.tresebrothers.com/Modding_Data#Data_Parser_Authoring_Process)
places manifest sources in the uploader project's `source_data/` directory and
prepared files in `upload_content/_data/`.

## Official enemy talent inheritance

The exporter leaves official effects and existing tier rows intact unless an
applicable variant needs an upgrade. Families and the official tier exemplars
are declared in `FAMILIES` and `EXISTING_TIERS`. Matching checks both the ability
name and its baseline effect/type; an unknown same-name variant refuses the
export rather than silently staying weak.

Untiered copies get middle and upper rows at the official thresholds. Numeric
talent improvements use the official upgrade delta, preserving existing variant
differences. Unchanged fields retain their original values, including group,
AI settings, charges, alert conditions and faction predicates. Effect pointers
use the corresponding official upgraded effect. Existing group-860 Shrapnel
Bleeder tiers use the improved group-861 exemplars.

The distinct effects used by Trauma Kit row 15 and Stunbomb row 41600 are
declared in `EFFECT_VARIANTS`. Their upgraded effects are new rows, calculated
from official effect deltas while retaining the variant's starting heal/AP
values and effect ownership. Original Effect rows are never updated. The
reserved inserted ranges begin at `TALENT_ID_START` for MonsterTalent and
`EFFECT_ID_START` for Effect; collisions with official rows refuse the build.
New locale entries name the inserted rows. Player Talent rows are outside the
package's write set.

The verifier checks every PL1–20 band for exactly one eligible version of each
covered ability. It verifies data eligibility, not runtime random selection.

## Build and verify

Run from the Hard Mode checkout using `cmd.exe`:

```bat
cd /d "D:\ckf-data-modding"
python scripts\export_enemy_difficulty.py
python scripts\export_enemy_difficulty.py --check
pwsh -NoProfile -File scripts\prepare_enemy_difficulty.ps1
python scripts\verify_enemy_difficulty.py --sql ckf-enemy-difficulty\parser_prepared\_data\data.sql --report ckf-enemy-difficulty\review\parser-verification.json
python scripts\test_enemy_difficulty.py
```

The PowerShell runner calls the installed `DataParser.Core.Parser.Process`
entry point with fresh output paths, checks success, and verifies committed
bytes. It neither opens the uploader nor submits anything. The independent
verifier applies the actual prepared SQL to an in-memory copy of Official data;
it never opens a campaign save. It compares the authored gear, archetypes,
roster weights and talent bands, checks unchanged columns/tables, resolves all
high-PL weapon/armor pointers, and checks repeat application. Corrupted-payload
tests keep those refusals runnable.

## Hand off and test

The official [Quick Start](https://cyberknightswiki.tresebrothers.com/Modding_Quick_Start#Setup_Your_Mod)
requires an initial Private upload, subscription to that item, and a completed
Steam download. Later development iterations use Local Install without another
upload; Public publication is a separate release step. A manually created
`steamapps/workshop/content/<appid>/<itemid>`
directory does not register the item with Steam. [measured] The failed local
test's `Logs/EnemyDifficulty-undiscovered-Player-20261029.log`,
`ModManager.ReadSteamSubscribedItems` output, listed only the other Workshop
item even though Enemy Difficulty's SQL was present on disk. The uploader's
[Local Install](https://cyberknightswiki.tresebrothers.com/Modding_Mod_Uploader#Local_Install)
copies prepared files into the selected Steam folder; it does not replace
subscription and in-game activation.

After the preceding checks, `scripts/install_enemy_difficulty.py` takes explicit
`--uploader-project` and `--workshop-dir` paths. It first verifies the item is
registered in Steam's `appworkshop_<appid>.acf` installed-item list, refusing
missing or unreadable registration before any writes. It writes parser sources to
`source_data`, prepared SQL/locales to `upload_content/_data`, and the same
payload to the downloaded Workshop item's `_data`. It stages distinct files,
checks expected modification times and hashes before committing, then hashes
the disk copies. It does not change Workshop metadata, publish, subscribe or
activate the mod.

If Steam downloads the published version after a local copy was installed,
repeat Local Install and verify the SQL/locale hashes again. Restart the game,
enable Enemy Difficulty in its Mods list and apply the selection before loading
the test save. Discovery in the startup log, activation and SQL application are
separate observations; verify each before interpreting a generated mission's
power level.

For the Workshop test, keep Hard Mode's master enabled with only its
`Difficulty` slice enabled. Its mission-generation hooks, ModelRules, gear,
spawn and talent changes must be off so they cannot stack with this package.
The exporter does not change that configuration; configure and verify it on
disk as part of the handoff. Data-mod activation in game and a newly generated
mission remain the runtime acceptance step. Verify actual enemy identities,
stats, equipment and talent selection; successful SQL preparation alone does
not establish those outcomes.
