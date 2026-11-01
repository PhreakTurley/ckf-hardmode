# Prepare Enemy Difficulty for Workshop

Enemy Difficulty applies authored enemy armor and armor assignments, sets
`Rule82.Value` to 20, and applies reviewed surgical native corrections from a
separate Workshop authoring document, and includes the reviewed PL1–20 Patrol,
reinforcement and VIP roster progression. Other native weapon, talent, effect
and stat scaling remains unchanged.

Roster authoring has one maintained source in the maintainer's
`ckf-enemy-scaling/` directory. Enemy Difficulty incorporates its prepared roster
SQL; it is not a second Workshop item. The exporter refuses stale roster output
and does not alter the policy. The legacy Hard Mode spawn sheets are not read
or combined with it.
Hard Mode's deprecated enemy-scaling ownership is documented in
[Tuning enemies](tuning-enemies.md).

## Authoring and outputs

`scripts/export_enemy_difficulty.py:build` reads the current official database,
the installed Data Parser declaration, and legacy armor inputs under
`BepInEx/config/ckf.hardmode.d`:

- all authored fields in `ArmorModel.csv`;
- only `ArmorTypeId` from `MonsterTypeModel.csv`.

Build the roster input with `ckf-enemy-scaling/scripts/build_overlays.py` before
exporting. Its policy, builder, planner, prepared SQL/locale and receipt hashes
are included in Enemy Difficulty's provenance. The roster input owns only
`MonsterGroupMember`; the enemy ceiling is emitted once by Enemy Difficulty.
Patrol uses the reviewed inclusions and small-integer weight progression.
VIP and Armored VIP remove Basic at PL15–20; reinforcements remove Basic at
PL20, with a fallback per slot/security band when no alternative is eligible.
Other pools retain shipped effective behavior. The roster policy uses matching
PL numbers, preserves non-Patrol PL1 and restores native behavior above PL20.

The additional surgical source is `BepInEx/config/ckf.enemy-difficulty.json`.
It is the single live authoring document for sparse native corrections, kept
outside Git like the armor inputs. Each update names its table, id, changed
fields, expected native values and replacements. Surgical fixes must point to
existing native rows; weapon, talent and effect repair clones are rejected.
Expected-value disagreements refuse export, so an updated official row cannot silently receive a stale patch.

The supported surgical fields are declared in `FIX_COLUMNS` in the exporter.
The verifier interprets the document independently and compares every native
row and field. Regressing weapon/effect assignments reuse previously effective
native rows; source rows and unrelated consumers remain unchanged. The
exporter records the fix document's hash in `review/SOURCE.json` and origins in the column ledger.

Other columns in the legacy monster sheet do not become SQL assignments. The
weapon sheet is not an export input. For each named input, exactly
one active file or parked `.disabled` file must exist. Both copies or a missing
input refuse the export. The receipt records input paths and hashes; it is not
a backup of live configuration.

Armor edits become sparse updates. Armor clones inherit unedited fields from
their source after authored source updates, retain their explicit identities,
and receive localized names. The BepInEx `_serveOn` control has no SQL equivalent.

For newly shipped complete PL1–20 ladders absent from the authoring sheet, the
exporter extends only armor pointers. Their native PL1–10 armor signature must
match authored donors, and every donor must agree on the PL11–20 result.
Missing or ambiguous matches refuse preparation. No broad stat floors, weapon
extensions or talent upgrades are generated. Non-armor corrections and any
native-pointer replacements must be explicitly declared in the surgical document.

Generated files under local `ckf-enemy-difficulty/` are:

| Path | Purpose |
|---|---|
| `source_content/stories.manifest` and `enemy-difficulty.json` | Data Parser input |
| `prepared/_data/` | Direct SQL and locale output for independent comparison |
| `parser_prepared/_data/` | Actual installed Data Parser output for handoff |
| `review/SOURCE.json` | Source hashes, counts and armor extensions |
| `review/column-ledger.csv` | Each assigned table/id/column and its origin |
| `review/parser-verification.json` | Independent verification result |

The parser source uses the documented `RawSQL` and `RawText.Generic` format.
The installed parser passes raw statements through; the independent verifier
owns their database validation. The [official use case](https://cyberknightswiki.tresebrothers.com/Modding_Use_Cases#Method_B:_RawSQL_and_RawText_Inside_the_JSON_Data_Parser)
documents that route. The [Data Modding process](https://cyberknightswiki.tresebrothers.com/Modding_Data#Data_Parser_Authoring_Process)
places manifest sources in the uploader project's `source_data/` directory and
prepared files in `upload_content/_data/`.

## Build and verify

Run from the Hard Mode checkout using `cmd.exe`:

```bat
cd /d "D:\ckf-data-modding"
python ckf-enemy-scaling\scripts\build_overlays.py
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
it never opens a campaign save. It independently evaluates armor inputs,
compares every row and column, checks authored armor pointers and localized
clones, and checks repeat application. Its SQL authorizer limits table and
column writes; the complete row comparison enforces the exact reviewed id,
field and value set. Weapon, talent, effect, stat, rule and roster corruption
cases remain runnable, including changes outside the reviewed surgical rows,
native source rows accidentally changed, forbidden repair clones and stale
native preconditions. The roster verifier independently reconstructs the policy from official data,
checks its SQL in isolation, and the combined verifier requires every merged
roster row/field to match that verified result. Weighted pools are checked at
every PL1–20. Corruption cases also cover the VIP/reinforcement removal gates,
restored legacy rows and deletion of unowned roster members. The old global native
weapon/armor and talent-effect resolution checks remain runnable with `verify_enemy_difficulty.py --native-integrity`; default runs
report each by name as `NOT RUN`. Authored armor-pointer validation always runs.
This distinguishes native reference defects from defects introduced by the mod.

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
mission remain the runtime acceptance step. Verify actual enemy armor, roster
composition and surgical corrections; successful SQL preparation alone does
not establish their in-game behavior.
