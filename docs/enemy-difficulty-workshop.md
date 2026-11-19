# Prepare Enemy Difficulty for Workshop

For armor edits and preparation to both Hard Mode and this Modkit project,
use the editor's [Enemy Armors page](../gui/README.md#enemy-armors).

Enemy Difficulty applies authored enemy armor and armor assignments, reads
`Rule82.Value` from the editor's **Enemy Balance → Rules** field, applies reviewed
surgical native corrections from a separate Workshop authoring document, and includes the reviewed PL1–20 Patrol,
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
the installed Data Parser declaration, and live armor inputs under
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
It is the single live authoring document for sparse native corrections and enemy
rules, kept outside Git like the armor inputs. The editor saves the Enemy Balance
rule in `rules` as a sparse `"82": {"Value": <integer>}` assignment. Clearing it
restores the shipped Rule 82 value; Validate clears an equal-to-shipped assignment
in the editor, and Save persists its removal. Preparation reads this field for
both the bundled Hard Mode payload and the uploader/installed Workshop payload.
The roster input's own Rule assignment is excluded from the merged export.
Each surgical update names its table, id, changed fields, expected native values
and replacements. Surgical fixes must point to
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

The parser source uses the `EnemyVariety` story key. The mod reserves
`560000–564999`, with `560000–560999` for new Armor rows and
`561000–564999` for new MonsterGroupMember rows. The export maps the reviewed
roster's generated identities into that range and retains its native member
identities. Reserved IDs occupied in Official data refuse preparation.
Identical insertions can be replayed, and a different row occupying the same
authored ID causes a SQL collision.

Enemy armor is exported as authored PL1–20 clones. Each clone inherits
unspecified fields from its Official donor and receives a localized name
with its effective PL. The export snapshots donor values so that a change
to the donor by another mod cannot change the clone's values. Enemy
assignments point at the authored rows while the shipped armor rows retain
their original fields and names. Every effective enemy armor reference is
checked. The BepInEx `_serveOn` control has no SQL equivalent.

For newly shipped complete PL1–20 ladders absent from the authoring sheet, the
exporter extends only armor pointers. Their native PL1–10 armor signature must
match authored donors, and every donor must agree on the full PL1–20 assignment.
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
every PL1–20 using the shipped member-reader SQL and its
[exclusive upper bounds](gotchas.md#game-data--databases). The retained below-PL1
preservation comparison runs with
`ckf-enemy-scaling/scripts/verify_prepared.py --include-nonpositive-pl`; default
runs name it `NOT RUN`. Corruption cases also cover the VIP/reinforcement removal gates,
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
