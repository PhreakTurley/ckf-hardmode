# Loot

Loot is fully data-driven and lives in five tables:

| Table | Database | Holds |
|---|---|---|
| `MissionLootModel` | DataDb | **The drop table proper** — what a mission can drop |
| `LootBoxDataModel` | DataDb | Placement only: where crates sit and what tier they are |
| `LootBoxAltPathDataModel` | DataDb | Alt-path variants of the above — in the dumper's default skip list; see [`workflow.md`](workflow.md) |
| `GameMissionLootModel` | GameDb | What this save's mission *did* drop |
| `GameMissionRewardModel` | GameDb | Per-save mission rewards |

**Loot lists are rolled at mission generation**, so edits land on missions
generated after the change, not on ones already on the board.

## `MissionLootModel` — the drop table

A row is a `(LootGroupId, LootTypeId, LootKey)` triple. `LootTypeId = 3` is
`LootTypes.File`, and `LootKey` is then a `MatrixFileId`. Rows also carry
`PowerLevel` and `Rarity` as live filters (global spread PL 0–10, Rarity 0–3) —
**`0` means no gate.**

**Weighting is by row multiplicity.** A duplicate row doubles that entry's
share. This is the shipped precedent for reweighting.

## `LootBoxDataModel` — placement, not contents

490 rows. Does **not** name a loot group. Each box carries a
`LootAssignmentType`:

`RedKey = 1`, `BlueKey = 2`, `GoldKey = 3`, `RandomTier1 = 4`, `Exact = 5`,
`None = 6`, `RandomTier2 = 7`, `RandomTier3 = 8`, `RandomTier4 = 9`

Observed usage: RandomTier1 244, RandomTier2 124, RandomTier3 66, RandomTier4
49, RedKey 6, BlueKey 1. `MissionLootId` is 0 on 486 of 490 rows; the four
exceptions are the key items.

The tier becomes a concrete `LootGroupId` at mission-generation time, in
`ProcGenerateLootLists` / `ProcGenerateLootListsFromProcGenRequest`. **That
selection is code, not data.**

## Loot group ids

Resolved off the running game into `_id_constants.csv`. Below are the Matrix and
V-Chip groups; the file carries all 62 — 48 `MissionLootGroupIds` and 14
`MatrixMissionLootGroupIds`. **Read it before picking a `LootGroupId`** — everything outside this corner is
missing here: the item families
(`ItemMedical` 1000, `ItemCorporateTech` 1001, `ItemStreetGrenades` 1002,
`ItemStreetDrugs` 1003, `ItemNano` 1009), credit chips (4000–4003),
`SkyriseInfluenceChips` 4004, NBS cubes (5000–5002), `Armor` 6000,
`WeaponMod` 8000, `Weapon` 100000, the `BlacksiteRewards_*` block (9000–9045)
and the blueprint groups (2000-series, 40001–40011, 50000, 60000/60001).

| Id | Class | Name | Kind |
|---|---|---|---|
| 3000 | `MissionLootGroupIds` | `FilesCorp` | faction files |
| 3001 | `MissionLootGroupIds` | `FilesCriminal` | faction files |
| 3002 | `MissionLootGroupIds` | `FilesCriminalFinancial` | faction files |
| 3003 | `MissionLootGroupIds` | `FilesCorpTechnoReports` | faction files |
| 21001 | `MatrixMissionLootGroupIds` | `SyndicateMatrixHost` | story Matrix host |
| 22001 / 23001 | `MatrixMissionLootGroupIds` | `CubeRunMatrixLootRoom1` / `2` | story Matrix host |
| 24001 / 25001 | `MatrixMissionLootGroupIds` | `M_CarnivoreRoom1` / `2` | declared, **no rows** |
| 26001 / 27001 | `MatrixMissionLootGroupIds` | `M_LoopholeHost1` / `2` | story Matrix host |
| 28001 / 28002 | `MatrixMissionLootGroupIds` | `SibSalvCargo` / `SibSalvPrison` | story Matrix host |
| 29000 | `MatrixMissionLootGroupIds` | `ProcGenCorp` | proc-gen Matrix host |
| 30000 / 30001 / 30002 | `MatrixMissionLootGroupIds` | `SafehouseTokenInjectFiles1` / `2` / `3` | Hacking Station tiers 1–3 |
| 30003 | `MatrixMissionLootGroupIds` | `SafehouseTokenInjectFilesVChips` | Hacking Station, set files |
| 30004 | `MissionLootGroupIds` | `SkyriseVChips` | Field Ops loot box, set files |

30003 and 30004 hold identical contents (39 rows each), authored as one block.

The 30000-series tiers match the Hacking Station's `TokenLevel` 1–3 in
`SafehouseModuleModel` — the only `MatrixConnect = 1` module, generating 2–9
tokens at 40→16 turns each.

---

## Matrix file sets (V-Chips)

Worked against Paula Law's and Dr. Ocular's Parts I–V. The mechanism is the same
for all eight splicer chips, but they are **not all five-part sets** — see the
count under Layer 1.

### Layer 1 — the file exists (`MatrixFileModel`)

| MatrixFileId | Name | MinimumPowerLevel | FileSize | FilePrice |
|---|---|---|---|---|
| 149–153 | Paula Law's V-Chip Part I–V | 2, 3, 4, 4, 4 | 75–175 | 8–24 |
| 154–158 | Dr. Ocular's V-Chip Part I–V | 2, 3, 4, 4, 4 | 75–175 | 8–24 |

All ten share `FileTypeId = 2` (`RegularFiles`) and **`FileGroupId = 9`**
(`MatrixFileGroupIds.VChips`) — group 9 holds exactly the **36** V-Chip part
files and nothing else.

36 is right, and it is **not** eight five-part chips (which would be 40). The
check is on this page: all eight chips list 30003 and 30004 among their loot
groups, those two groups hold 39 rows each, and three of those are the
duplicated Samdara Parts I–III noted under Levers — 39 − 3 = 36 distinct part
files. Paula's and Ocular's are five-part sets, as the id ranges show;
*[unverified]* how the other 26 parts divide across the remaining six chips.

### Layer 2 — the parts are worth collecting (`MatrixFileSetModel`)

| MatrixFileSetId | Parts | FileOutputId |
|---|---|---|
| 36 | 149–153 | 1035 — Paula Law's V-Chip |
| 37 | 154–158 | 1036 — Dr. Ocular's V-Chip |

The output file carries `FileActionTypeId = 2` (`CreateContactVCard`), which
unlocks the splicer contact. The **completed** chips (1026, 1027, 1031–1036 —
eight ids, one per chip) appear in no loot group at all; compiling the set is
the only way to get one.

### Layer 3 — the parts drop, two independent ways

**(a) Mission loot tables.** Five `MissionLootModel` rows per chip in each of
five groups — 25 rows per chip, ten per group counting both chips. Every row has
`PowerLevel = 0` and `Rarity = 0`, so once a group is rolled a part is eligible
at any mission power level.

| LootGroupId | Paula MissionLootIds | Ocular MissionLootIds |
|---|---|---|
| 30000 | 30616–30620 | 30608–30612 |
| 30001 | 30511–30515 | 30503–30507 |
| 30002 | 30548–30552 | 30563–30567 |
| 30003 | 6030–6034 | 6035–6039 |
| 30004 | 6069–6073 | 6074–6078 |

**(b) Matrix host stocking.** Hosts draw from a `MatrixFileGroupIds` pool rather
than a loot group, and the gate is `MatrixFileModel.MinimumPowerLevel`, **not**
`MissionLootModel`. For both chips: Part I at PL 2, Part II at PL 3, Parts III–V
at PL 4.

### Why Paula and Ocular are hard to find

| Chip | Loot groups |
|---|---|
| Dr. Samdara's | 3001, 30000, 30001, 30002, 30003, 30004 |
| Goldstax's | 3002, 30003, 30004 |
| Splicer Mina | 3002, 30003, 30004 |
| Dr. Sevenfold's | 3003, 30000, 30001, 30002, 30003, 30004 |
| Dr. Keros' | 3001, 30000, 30001, 30002, 30003, 30004 |
| Vanta Drip's | 29000, 30000, 30001, 30002, 30003, 30004 |
| **Paula Law's** | **30000, 30001, 30002, 30003, 30004** |
| **Dr. Ocular's** | **30000, 30001, 30002, 30003, 30004** |

They are the only two with **no themed-group entry** — no faction file list and
no story Matrix host — so they are reachable only through the safehouse/V-Chip
groups.

### Levers, least to most invasive

1. **Add rows to `MissionLootModel`.** `LootTypeId = 3`, `LootKey = 149…158`,
   any existing `LootGroupId`. Putting Paula's parts in 3001 gives them the same
   criminal-file exposure Keros and Samdara have.
2. **Duplicate rows to reweight.** Samdara's Parts I–III already appear twice in
   30003/30004, doubling their share — the shipped precedent.
3. **`PowerLevel` / `Rarity`.** Both 0 on every V-Chip row today; raising them
   would gate the parts rather than loosen them.
4. **`MatrixFileModel.MinimumPowerLevel`.** Matrix host stocking only. Dropping
   Parts III–V from 4 to 2 makes the set reachable from early hosts.
5. **`MatrixFileSetModel`.** Cutting `MatrixFileId4/5` to 0 turns a five-part
   chip into a three-part chip.

Both drop paths write to per-save `GameDb` tables (`GameMissionLootModel`,
`GameMatrixHostFileModel`, `GameFileDownloadModel`).

---

## Safehouse token injects

Which action feeds which pool.

**Loot-box family — Field Ops Center** (`ModuleClassId` 15)

| Token type | In-game title | Effect |
|---|---|---|
| `InjectLootBoxLoot` | Delayed Shipments | parent, opens a nested menu |
| `InjectLootBoxLootFiles` | Inject Loot Files | more **faction** files in lootboxes |
| `InjectLootBoxLootFilesVChips` | **Inject Set Files** | more pieces of **file sets** in lootboxes |
| `InjectLootBoxLootCreds` / `…CredsRich` | Inject Credit Chips / Rich Credit Chips | more CredChips |
| `InjectLootBoxBlueprints` | Blueprint Shipping Error | more blueprints |
| `InjectLootBoxNBS` | Delayed NBS Shipments | more crafting supplies |

**Matrix family — Hacking Station** (`ModuleClassId` 5)

| Token type | In-game title | Effect |
|---|---|---|
| `InjectMatrixLootFiles` | Inject Matrix Files | files on Matrix hosts |
| `InjectMatrixLootFileSets` | **Inject Matrix Set Files** | set files on Matrix hosts |
| `InjectMatrixLootAccounts` | Inject Matrix Accounts | financial instruments |
| `InjectMatrixLootFileBlueprints` | Inject Matrix Blueprints | blueprints |

*[unverified] The module split is read off the rule strings and class
descriptions, not proven row-by-row — there is no table binding a
`TokenPurchaseTypeId` to a `ModuleClassId`.* It is also not clean in practice:
spending the Face's talent charge in a room adds offers to that room, and the
Face's Hacking talent tier 4 is labelled exactly **"Inject Set Files"**, the
loot-box title. The two menus overlap once the Face talent is in play.