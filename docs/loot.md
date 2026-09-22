# Loot

Use this page to trace mission-loot rows, Matrix file sets, and the safehouse
token-inject families. Mission payment is a separate path documented in
[`mission-rewards.md`](mission-rewards.md). Rule-engine row editing is documented
in [`rule-engine.md`](rule-engine.md) and [`overlays.md`](overlays.md).

Facts here are [measured] from the dumped tables and `_id_constants.csv` unless tagged otherwise.

## Data tables

| Table | Database | Holds |
|---|---|---|
| `MissionLootModel` | DataDb | The drop table: what a mission can drop |
| `LootBoxDataModel` | DataDb | Placement only: where crates sit and their tier |
| `LootBoxAltPathDataModel` | DataDb | Alt-path variants of the above. CKFDataDump skips it while `[Dump] SkipIrrelevantTables` is on (the default) |
| `GameMissionLootModel` | GameDb | What this save's missions actually dropped |
| `GameMissionRewardModel` | GameDb | Per-save mission rewards |

Loot lists are rolled when a mission is generated. An edit applies only to missions generated after it, not to missions already on the board.

### `MissionLootModel`

- **Rows.** A row is a `(LootGroupId, LootTypeId, LootKey)` triple. `LootTypeId = 3` is `LootTypes.File`, and `LootKey` is then a `MatrixFileId`.
- **Filters.** `PowerLevel` (PL 0–10 in shipped data) and `Rarity` (0–3) act as filters. `0` means no gate.
- **Weighting.** Weighting is by row count: a duplicate row doubles that entry's share. The shipped data already does this.

### `LootBoxDataModel`

- **Contents.** 490 rows. The table does not name a loot group.
- **`LootAssignmentType`** is one of: `RedKey = 1`, `BlueKey = 2`, `GoldKey = 3`, `RandomTier1 = 4`, `Exact = 5`, `None = 6`, `RandomTier2 = 7`, `RandomTier3 = 8`, `RandomTier4 = 9`.
- **Usage:** RandomTier1 244, RandomTier2 124, RandomTier3 66, RandomTier4 49, RedKey 6, BlueKey 1.
- **`MissionLootId`.** It is 0 on 486 rows; the four exceptions are the key items.
- **Tier to group.** The tier becomes a concrete `LootGroupId` at generation time, in `ProcGenerateLootLists` / `ProcGenerateLootListsFromProcGenRequest`. That choice is made in code, not data.

## Loot group IDs

`_id_constants.csv` lists 62 groups: 48 `MissionLootGroupIds` and 14 `MatrixMissionLootGroupIds`. Read it before picking a `LootGroupId`. Other families:

| Family | Ids |
|---|---|
| Items | `ItemMedical` 1000, `ItemCorporateTech` 1001, `ItemStreetGrenades` 1002, `ItemStreetDrugs` 1003, `ItemNano` 1009 |
| Credits and currency | credit chips 4000–4003, `SkyriseInfluenceChips` 4004, NBS cubes 5000–5002 |
| Gear | `Armor` 6000, `WeaponMod` 8000, `Weapon` 100000 |
| Rewards and blueprints | `BlacksiteRewards_*` 9000–9045; blueprint groups (2000-series, 40001–40011, 50000, 60000/60001) |

The Matrix and V-Chip groups:

| Id | Class | Name | Kind |
|---|---|---|---|
| 3000–3003 | `MissionLootGroupIds` | `FilesCorp`, `FilesCriminal`, `FilesCriminalFinancial`, `FilesCorpTechnoReports` | Faction files |
| 21001 | `MatrixMissionLootGroupIds` | `SyndicateMatrixHost` | Story Matrix host |
| 22001 / 23001 | `MatrixMissionLootGroupIds` | `CubeRunMatrixLootRoom1` / `2` | Story Matrix host |
| 24001 / 25001 | `MatrixMissionLootGroupIds` | `M_CarnivoreRoom1` / `2` | Declared, no rows |
| 26001 / 27001 | `MatrixMissionLootGroupIds` | `M_LoopholeHost1` / `2` | Story Matrix host |
| 28001 / 28002 | `MatrixMissionLootGroupIds` | `SibSalvCargo` / `SibSalvPrison` | Story Matrix host |
| 29000 | `MatrixMissionLootGroupIds` | `ProcGenCorp` | Proc-gen Matrix host |
| 30000–30002 | `MatrixMissionLootGroupIds` | `SafehouseTokenInjectFiles1`–`3` | Hacking Station tiers 1–3 |
| 30003 | `MatrixMissionLootGroupIds` | `SafehouseTokenInjectFilesVChips` | Hacking Station, set files |
| 30004 | `MissionLootGroupIds` | `SkyriseVChips` | Field Ops loot box, set files |

- 30003 and 30004 have identical contents (39 rows each).
- The 30000-series tiers match the Hacking Station's `TokenLevel` 1–3 in `SafehouseModuleModel`. The Hacking Station is the only `MatrixConnect = 1` module; it generates 2–9 tokens at 40→16 turns each.

## Matrix file sets (V-Chips)

This section works through Paula Law's and Dr. Ocular's Parts I–V. All eight splicer chips use the same mechanism, but not all of them are five-part sets.

### Layer 1: the part files (`MatrixFileModel`)

| MatrixFileId | Name | MinimumPowerLevel | FileSize | FilePrice |
|---|---|---|---|---|
| 149–153 | Paula Law's V-Chip Part I–V | 2, 3, 4, 4, 4 | 75–175 | 8–24 |
| 154–158 | Dr. Ocular's V-Chip Part I–V | 2, 3, 4, 4, 4 | 75–175 | 8–24 |

- All ten have `FileTypeId = 2` (`RegularFiles`) and `FileGroupId = 9` (`MatrixFileGroupIds.VChips`).
- Group 9 holds exactly 36 part files: groups 30003/30004 have 39 rows each, and 3 of those are duplicated Samdara Parts I–III.

### Layer 2: the set (`MatrixFileSetModel`)

| MatrixFileSetId | Parts | FileOutputId |
|---|---|---|
| 36 | 149–153 | 1035, Paula Law's V-Chip |
| 37 | 154–158 | 1036, Dr. Ocular's V-Chip |

- The output file has `FileActionTypeId = 2` (`CreateContactVCard`), which unlocks the splicer contact.
- The eight completed chips (1026, 1027, 1031–1036) are in no loot group. Compiling the set is the only way to get one.

### Layer 3: how parts drop

**(a) Mission loot tables.** Each chip has five `MissionLootModel` rows in each of five groups. Every row has `PowerLevel = 0` and `Rarity = 0`, so once a group is rolled, a part can drop at any mission power level.

| LootGroupId | Paula MissionLootIds | Ocular MissionLootIds |
|---|---|---|
| 30000 | 30616–30620 | 30608–30612 |
| 30001 | 30511–30515 | 30503–30507 |
| 30002 | 30548–30552 | 30563–30567 |
| 30003 | 6030–6034 | 6035–6039 |
| 30004 | 6069–6073 | 6074–6078 |

**(b) Matrix host stocking.** Hosts draw from a `MatrixFileGroupIds` pool, not a loot group. The gate is `MatrixFileModel.MinimumPowerLevel`: Part I at PL 2, Part II at PL 3, Parts III–V at PL 4.

### Availability across loot groups

| Chip | Loot groups |
|---|---|
| Dr. Samdara's | 3001, 30000–30004 |
| Goldstax's | 3002, 30003, 30004 |
| Splicer Mina | 3002, 30003, 30004 |
| Dr. Sevenfold's | 3003, 30000–30004 |
| Dr. Keros' | 3001, 30000–30004 |
| Vanta Drip's | 29000, 30000–30004 |
| Paula Law's | 30000–30004 |
| Dr. Ocular's | 30000–30004 |

Paula's and Ocular's chips are the only two with no themed group (no faction
file list and no story Matrix host). In the dumped rows, they are reachable only
through the safehouse and V-Chip groups [measured].

### Rule-engine levers

1. Add `MissionLootModel` rows (`LootTypeId = 3`, `LootKey` 149–158) to an existing group. For example, adding them to 3001 gives the same criminal-file exposure Keros and Samdara have.
2. Duplicate rows to reweight, as the shipped data does for Samdara in 30003/30004.
3. Raise `PowerLevel` / `Rarity` on the V-Chip rows. This gates parts rather than loosening them.
4. Lower `MatrixFileModel.MinimumPowerLevel`. This affects Matrix host stocking only.
5. Edit `MatrixFileSetModel`. Setting `MatrixFileId4/5` to 0 turns a five-part chip into a three-part chip.

Both drop paths write to per-save `GameDb` tables (`GameMissionLootModel`, `GameMatrixHostFileModel`, `GameFileDownloadModel`).

## Safehouse token injects

Loot-box family, Field Ops Center (`ModuleClassId` 15):

| Token type | In-game title | Effect |
|---|---|---|
| `InjectLootBoxLoot` | Delayed Shipments | Parent; opens a nested menu |
| `InjectLootBoxLootFiles` | Inject Loot Files | More faction files in loot boxes |
| `InjectLootBoxLootFilesVChips` | Inject Set Files | More file-set pieces in loot boxes |
| `InjectLootBoxLootCreds` / `…CredsRich` | Inject Credit Chips / Rich Credit Chips | More CredChips |
| `InjectLootBoxBlueprints` | Blueprint Shipping Error | More blueprints |
| `InjectLootBoxNBS` | Delayed NBS Shipments | More crafting supplies |

Matrix family, Hacking Station (`ModuleClassId` 5):

| Token type | In-game title | Effect |
|---|---|---|
| `InjectMatrixLootFiles` | Inject Matrix Files | Files on Matrix hosts |
| `InjectMatrixLootFileSets` | Inject Matrix Set Files | Set files on Matrix hosts |
| `InjectMatrixLootAccounts` | Inject Matrix Accounts | Financial instruments |
| `InjectMatrixLootFileBlueprints` | Inject Matrix Blueprints | Blueprints |

## Open questions

- [unverified] How the other 26 V-Chip parts divide across the remaining six
  completed chips.
- [unverified] The split by module was read from rule strings and class
  descriptions. No table binds a `TokenPurchaseTypeId` to a `ModuleClassId`.
  The two menus also overlap in play: spending the Face's talent charge in a
  room adds offers to that room, and the Face's Hacking talent tier 4 is
  labelled "Inject Set Files", the loot-box title.

## Related

- [`mission-rewards.md`](mission-rewards.md)
- [`overlays.md`](overlays.md)
- [`rule-engine.md`](rule-engine.md)
