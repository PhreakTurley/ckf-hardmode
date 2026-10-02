# First-party data modding atlas

This is the starting map for moving parts of CKF Hard Mode from BepInEx to the game's first-party data modding tools. It records the published tool surface, the current Hard Mode owners, and the questions that must be answered before choosing a port order or Workshop bundle. It is an architecture reference, not a migration plan or a claim of behavioral parity. Recheck the wiki and the live source before implementing a slice.

## Read the first-party documentation

The [Data Parser schema index](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema) links eight table references:

| Area | Parser table names | Reference |
|---|---|---|
| Characters | `Backstory`, `CharacterLevel`, `Job`, `JobNode`, `Implant`, `Talent`, `Trait` | [Characters](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema_Characters) |
| Contacts | `ContactBackstory`, `ContactPowerLevel`, `ContactService`, `ContactTrait`, `ContactType` | [Contacts](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema_Contacts) |
| Story | `Block`, `BlockCondition`, `Dialog`, `DialogQuip`, `Legwork`, `StoryMatch`, `StoryNode`, `Tag` | [Story](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema_Story) |
| Missions | `Mission`, `MissionAdvantage`, `MissionAdvantageMatch`, `MissionBlock`, `MissionRoom`, `MissionPowerLevel` | [Missions](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema_Missions) |
| Enemies | `MonsterGroup`, `MonsterGroupMember`, `MonsterTalent`, `MonsterType` | [Enemies](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema_Enemies) |
| Combat | `Armor`, `Effect`, `Item`, `Weapon`, `Weapon3DAsset`, `WeaponClassMod`, `WeaponMod` | [Combat](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema_Combat) |
| Matrix | `Cyberdeck`, `CyberdeckProgram`, `MatrixDeckCard`, `MatrixEffect`, `MatrixFile`, `MatrixFileSet`, `MatrixIC`, `MatrixNodeType` | [Matrix](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema_Matrix) |
| Extras | `BankAccount`, `Cosmetic`, `CosmeticAdjustment`, `CosmeticColor`, `CosmeticGroup`, `Faction`, `Journal`, `Names`, `PetChassis`, `PetPrebuilt`, `Rule`, `SafehouseModule`, `SecurityDeckCard` | [Extras](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema_Extras) |

These are parser/SQL names, not Hard Mode's `*Model` type names. Each reference gives fields, types, defaults, value mappings and underlying SQL columns. Use that mapping for each port; never derive a SQL table or column name by stripping `Model`. The references describe authoring contracts, not proof that a particular Hard Mode change survives game loading.

The other primary pages are [Data Modding](https://cyberknightswiki.tresebrothers.com/Modding_Data) and the [Mod Uploader](https://cyberknightswiki.tresebrothers.com/Modding_Mod_Uploader). The official [weapon use case](https://cyberknightswiki.tresebrothers.com/Modding_Use_Cases#Use_Case:_Add_or_Modify_Weapons) shows raw SQL, `RawSQL`/`RawText`, and native parser JSON producing comparable output. The [modding home](https://cyberknightswiki.tresebrothers.com/Modding) currently labels support a preview; check its status when implementation begins.

## Know the first-party artifact path

The documented final data payload is `upload_content\_data\data.sql` with `upload_content\_data\en-US.json` and optional other locale JSON files. The parser takes JSON source listed one path per line in `stories.manifest` (`#` starts a comment), validates native table records, supplies omitted values on inserts, and generates SQL and localization files when the uploader prepares data. A native record with `"SQL": "update"` emits an `UPDATE` containing only supplied fields; omitted defaults do not enter that update. Existing localization keys are changed through `RawText`; a new record's `Name` can generate its localization key. `RawSQL` and `RawText` pass through without native schema validation. Directly authored SQL and locale files are also documented. Sources: [Data Parser process](https://cyberknightswiki.tresebrothers.com/Modding_Data#Data_Parser_Authoring_Process), [direct files](https://cyberknightswiki.tresebrothers.com/Modding_Data#Directly_Provide_Files_from_Another_Tool), [weapon use case](https://cyberknightswiki.tresebrothers.com/Modding_Use_Cases#Method_C:_Data_Parser_JSON).

The [uploader's folder diagram](https://cyberknightswiki.tresebrothers.com/Modding_Mod_Uploader#Mod_Content_Organization) places `<ModName>.workshop.json` next to a `<ModName>` folder under `Cyber Knights Modkit\WorkshopContent\`; the folder has `source_content\` and `upload_content\_data\`. The Data Modding page calls the manifest folder `source_data\` and one direct-file paragraph calls the target `upload_ready\_data\`. Those names disagree with the uploader diagram and with that same page's explicit output-file list. Inspect an installed uploader project before locking source paths into a build script. Keep source-controlled authoring files outside `upload_content`: the uploader says Prepare Data Mod and Refresh Project Files delete and replace that prepared directory. Source: [Uploader preparation](https://cyberknightswiki.tresebrothers.com/Modding_Mod_Uploader#Preparing_for_Publishing).

One uploader mod can carry data modifications and Unity addressables. Its internal codename creates a local folder and workshop JSON; title, icon, description, tags, visibility, translation flag and change notes are uploader metadata. The first successful Submit creates a permanent Workshop item tied to the Steam account. Later submissions overwrite all Workshop files and go live immediately. Steam must be running and signed in; the publishing account needs the game and must be in good standing. Source: [Uploader](https://cyberknightswiki.tresebrothers.com/Modding_Mod_Uploader). The [player instructions](https://cyberknightswiki.tresebrothers.com/Modding#For_Players_of_Mods) describe Workshop subscription followed by activation in game, applying across saved and new games.

The first-party pages do not establish SQL execution order among active Workshop mods, collision handling, transaction behavior, or the ordering of Workshop SQL versus BepInEx hooks. Treat each as an open integration question. In particular, two systems aimed at the same `(table, id, column)` must not be enabled together until ordering and ownership are verified.

## Locate today's Hard Mode owner

The current flow is `schema/*.schema.json` → generated C# binds/config reference/editor controls → live `BepInEx\config\ckf.hardmode.cfg` and `ckf.hardmode.d\*` → `CKFHardMode.dll`. `Plugin.Load` initializes the switches and settings, then `ModelRules` and the independent runtime subsystems. `Overlays.Load` scans the flat live directory in filename order and checks `Slices.OverlayOwner` before reading a switched-off file. `ModelRules` edits materialized rows; `RowClone` serves synthetic rows through readers. See [architecture](architecture.md), [Hard Mode subsystem guide](../mods/CKFHardMode/README.md), [rule engine](rule-engine.md), [overlay format](overlays.md), and code members `Plugin.Load`, `Overlays.Load`, `ModelRules.Init`, `RowClone.Init`, `Slices.OverlayOwner`.

The game installation contains the only tuning copy. Do not create a second set of current tuning values in this repository as a migration input. A future exporter should read the selected live config into temporary staging, record source hashes, and generate reviewable first-party source/output from it. The existing editor saves the live BepInEx config; `scripts/make_release.py` packages that config with the DLL, BepInEx and editor. No first-party export or Workshop packaging path exists in this repository yet.

## Porting surface by owner

The table below identifies candidates to investigate. “Candidate” means the wiki documents the corresponding SQL table; it does not mean the parser accepts every current operation or the game behaves identically after SQL modification. Current ownership is from `mods/CKFHardMode/README.md` and the named source members.

| Current Hard Mode unit | Current implementation | First-party investigation |
|---|---|---|
| Direct talent balance, 11 class slices | `EffectModel.<tag>.csv`, `JobNodeModel.<tag>.csv`, `TalentModel.<tag>.csv`, and Hacker `MatrixEffectModel.hkr.csv` through `Overlays.Load` | Candidate native updates to `Effect`, `JobNode`, `Talent`, `MatrixEffect`; keep each class's cross-table edits together. |
| Enemy gear and archetypes | `ArmorModel.csv`, `WeaponModel.csv`, `MonsterTypeModel.csv`; no independent slice gate | Candidate `Armor`, `Weapon`, `MonsterType` updates/inserts. Preserve row pointers, tier selection and localized names. |
| Faction spawn pools | `MonsterGroupMemberModel.spawn-*.csv` through `RowClone` where `_clone` is used | Candidate `MonsterGroupMember` insert/update. SQL-side power-level filtering makes this a distinct behavior test; see [cloning rows](cloning-rows.md) and [gotchas](gotchas.md). |
| Rule constants | `RuleModel.csv` | Candidate `Rule` updates; check the schema's `RuleId`/`Group`/`Name`/`Value` mapping. |
| Limit-break trait effects | `EffectModel.limitbreak.csv` under `LimitBreakTraits` | Candidate `Effect` updates. This is separate from Fatigue's runtime trait grants. |
| Mission Power Level label | `MissionPowerLevelModel.generated.json` under `ModelRules` | Candidate `MissionPowerLevel` update for the label only. Keep it coupled to `Progression`'s award logic until both are verified together. |
| Gear-class lever sheet | `GearClasses.Expand`, driven by `gear-classes.csv` and post-overlay `MonsterTypeModel.WeaponTypeId` | Export expanded `Weapon` edits only after reproducing the player/enemy partition from the chosen config and data revision. |
| Cyberweapon lever sheets | `Cyberweapons.Expand` reads two CSVs | Export paired `Weapon` and `Talent` edits as one tuning unit. |
| Implant global and slot levers | `Implants.ExpandGlobal` plus 11 slot CSVs | Export related `Implant` and `Effect` edits; avoid applying the global multiplier twice. |
| Consumable family levers | `Consumables.Expand` reads six family CSVs | Export related `Item`, `Talent`, `Effect`, `MatrixEffect` edits as each lever requires. |
| Row clones from any overlay/rule | `_clone`/`as` through `RowClone` | Test SQL inserts separately from updates. Parser defaults do not imply a clone of every source-column value. Check new ID ownership, references, reader behavior and localization. |
| General table rules | `ModelRules` set/multiply/add/clamps/curves | Native sparse `UPDATE` directly represents supplied set values. Arithmetic, clamping and curves require an explicit translation strategy and parity check; do not silently evaluate them against an old dump. |

The likely continuing BepInEx owners are `PowerLevelCap`, `Fatigue`, `Elapse`, `MissionRewards`, `RewardCurve`, and `Difficulty`. Their current source uses calculations, hooks, save writes, or static slider bounds rather than only content-table changes. `Progression` is mixed: it changes the saved award through `GameDb.SumGameMissionScore` and mirrors the display via a `MissionPowerLevelModel` row. `SelfCheck` is a diagnostic, not content. See the corresponding source members (`PowerLevelCap.Init`, `Fatigue.Init`, `Elapse.Init`, `MissionRewards.Init`, `RewardCurve.Init`, `Progression.Init`, `Plugin.Load`) and their owning docs. A SQL replacement for a runtime subsystem remains possible only after identifying and testing the actual underlying data path.

## Parser constraints that matter to this port

Use each [schema subpage](https://cyberknightswiki.tresebrothers.com/Modding_Data_Parser_Schema) as the declaration for a generated record. The references distinguish IDs that must be authored from IDs allocated from `Metadata.StartingId`; they also spell out enum mappings, defaults, and SQL-column aliases. Examples with bearing on Hard Mode include explicit IDs for `JobNode`, `Implant`, `Talent`, the four enemy tables, all seven combat tables, all eight Matrix tables, and `Rule`; some story/character/contact records have automatic IDs. Story state operands and some link fields have required prefixes. The Story reference still contains TODO field descriptions, so a field listing alone cannot establish behavior. These are wiki contracts awaiting confirmation with the actual parser and game.

For every conversion, key records by `(table, id)`. Preserve the difference between a sparse update and a new insert, including defaults, copied source columns, foreign keys, names and execution order. The game's shipped values come from a fresh Data Dump or an official game-version resource, not the live tuning files. The dump is a check, not the source of parser declarations. Existing pointer and column gates stay active for the BepInEx side; extend validation for generated SQL instead of relaxing a failing gate.

## Repeat this procedure for each future slice

1. **Freeze the input for review.** Name the live config files, their hashes, the game build, and the shipped-data capture used for the conversion. Read the live files immediately before export. Keep `(table, id)` as the identity of every source and target row.
2. **Write an ownership ledger.** For every affected `(table, id, column)`, record the current input file, its `[Slices]` gate, any earlier rule it depends on, the proposed Workshop item, and whether BepInEx will still touch it. Include inserted rows, pointers, localization keys, and the runtime hooks that consume them. This ledger is the basis for bundle boundaries.
3. **Translate the operation.** Native parser JSON is the first candidate for a plain sparse update or independently authored insert. For clone semantics, arithmetic, curves, or a field the native parser cannot express, choose an explicit generated SQL transformation or keep the BepInEx rule. Record the reason and the expected SQL. Treat a multi-table lever expansion as one unit even if its output spans several tables.
4. **Prepare and inspect locally.** Run the installed uploader's Prepare Data action after confirming its actual source path. Inspect `data.sql`, locale JSON, parser diagnostics, row identities, statement order, and any generated defaults. The generated files are artifacts; edit their source and regenerate. Do not use Submit as a test step.
5. **Compare behavior at the right sampling moment.** Validate SQL pointers and unique IDs, turn off only the corresponding BepInEx owner, then exercise the affected game read. For a row selected by SQL filters, test the selection path; for a clone, test both by-id and filtered-list access; for a label paired with a saved award, test both outputs. A missing trace is meaningful only after establishing that the instrument covered that path.
6. **Move the owner and packaging together.** Once parity is observed, update the editor/exporter, BepInEx gates and release packaging so that the value has one maintained source and one runtime owner. Re-run the live BepInEx checks and the new SQL checks. Record the final Workshop item boundary, companion DLL requirement, install/activation sequence, and rollback path in the owning release docs.

This sequence is a proposed migration method. No port or bundle has been implemented yet, and save-writing test paths still require review before execution under `AGENTS.md`.

## Questions to settle before bundling

1. **Runtime order.** When does activated Workshop SQL run relative to BepInEx startup, DataDb materialization, and a save load? Does a save capture inserted content rows? Observe each path in game.
2. **SQL behavior.** What does a failed statement do to the rest of one mod or several mods? How are mod conflicts ordered and reported? Test with controlled, reversible rows.
3. **Unit of distribution.** Should one Workshop item hold all table data while the DLL continues as a separate install, or should coherent slices become independent Workshop items? Decide after checking dependency edges, activation controls, update behavior and user install steps.
4. **Switch ownership.** How will an enabled Workshop data slice interact with the existing `[Slices]` gate? Define a single owner for each table/column before shipping either side.
5. **Authoring source.** Verify the uploader's actual source folder and manifest rules. Choose native parser JSON, generated direct SQL/localization, or a combination per table; keep one maintained source for each value.
6. **ID and locale policy.** Reserve IDs per SQL table, validate pointer targets and prefix rules, and decide how a new name and a changed existing name are generated. Test subscription/unsubscription against existing saves.
7. **Verification and release.** Compare selected config input, generated SQL/text, parser diagnostics, game log and in-game behavior. Update the editor and release builder only after the source and bundle contract is chosen. `Submit` publishes immediately, so prepare and review locally before that step.

The first migration slice should be chosen only after these questions have evidence. Favor a self-contained table edit with an observable in-game read, then exercise a multi-table lever and a cloned row; these expose progressively more of the integration boundary. Keep every finding as an observation with a source and evidence tag, and leave a cause unstated when the logs do not establish one.
