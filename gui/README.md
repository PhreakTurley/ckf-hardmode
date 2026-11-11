# CKF Balance Editor (`gui/`)

A local web page that edits Hard Mode and Workshop player tuning under the game's
`BepInEx/config/`. Hard Mode controls come from `schema/*.schema.json`; player
catalogs come from the selected official database. Use this page to run it
from source, understand a refused save, or maintain the frozen executable.
Per-key meanings are in
[`../docs/config-reference.md`](../docs/config-reference.md); the schema format
is in [`../schema/SCHEMA-FORMAT.md`](../schema/SCHEMA-FORMAT.md).

The plugin version is `4.2.0`; the ten settings documents carry layout stamp `4.1.0`.
The plugin version and settings-layout stamp are independent even when their
values happen to agree. The editor writes the live files and keeps no backup.

| File | Role |
|---|---|
| `serve.py` | Stdlib-only server. Does all file I/O and all validation. |
| `app.html` | The page. No CDN, no build step. Names no file, field, column or cfg key. |
| `settings.json` | Per-machine game/config paths, `stripReadme`, and optional Modkit paths. Not committed. |
| `modkit.py` | Guarded handoff of talent and player-balance sources to Modkit. |
| `player_balance.py` | Workshop tuning, official-data catalogs, and SQL generation. |
| `ckf-config-editor.spec` | PyInstaller spec used by `scripts/make_release.py`. |

## Run the editor from source

```
python gui/serve.py                         # free port on 127.0.0.1, opens a browser
python gui/serve.py --no-browser
python gui/serve.py --port 8765
python gui/serve.py --game "<game root>"
python gui/serve.py --config "<game root>\BepInEx\config"
```

| Flag | Effect |
|---|---|
| `--config DIR` | Use this `BepInEx/config` directory, bypassing `gameDir`. It must be a directory, not the `.cfg` file. |
| `--game DIR` | Game root; the config is `DIR/BepInEx/config`. |
| `--port N` | Bind this port instead of a free one. |
| `--no-browser` | Don't open a browser. |
| `--selftest` | Run the verification suite (see [Self-tests](#self-tests)). |
| `--selftest-js` | Run `app.html`'s pure functions under `node`. |
| `--legacy-cyberware-help` | With `--selftest`, run the two retired cyberware prose checks. Default runs report each as `NOT RUN`; the Workshop catalogs replace those help panels. |
| `--frozen-exe PATH` | With `--selftest`: also run the frozen-exe cases against a built exe. |
| `--migrate` | Convert a 3.x layout to the current slice layout (introduced in 4.0; settings stamp 4.1.0) and rename the originals to `*.pre-4.0-backup`. Refuses, writing nothing, if an input is missing, the slice layout already exists, a backup exists, or `MonsterTypeModel.csv` cannot be read. Maintainer-only; players install a fresh zip. |
| `--run-check-schema --config DIR` | Must be the first argument. Runs `schema/check_schema.py` in-process and exits with its code. This is how the frozen exe validates a save. |

**Game directory.** Resolved by `serve.py:load_settings` / `default_game_dir`:

1. `configDirOverride` if set (the page sets it when the typed path ends in `BepInEx/config`).
2. Else `gameDir`. A blank or whitespace `gameDir` counts as absent.
3. Absent: when frozen, the exe's own directory if `CyberKnights.exe` sits beside it; otherwise `C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint`.

The directory can be changed in the page header and is saved to settings. At startup the editor tests whether it can write there by creating and deleting a file. The result is `ok`, `denied`, `missing`, `error` or `unset`, and it shows in the page. A save that hits a permission error is refused with the OS error text.

The editor commits straight into the live config directory. It validates a
temporary proposed tree and uses temporary files for its atomic rename, but it
keeps no persistent staging copy and no backup. To reset, re-extract
`BepInEx\config` from the release zip.

Procedure: [`../docs/workflow.md`](../docs/workflow.md). Traps: [`../docs/gotchas.md`](../docs/gotchas.md).

## Party Size Mod

**Party Size Mod** is a separate navigation section for the single official
`Rule` row 83, `Mission Max MercDefault`. `party_size.py:rule` queries that
identity directly and refuses a missing or renamed row. The section reads the
current official baseline and description. Its only tuning value is a positive
integer maximum, stored in `BepInEx/config/ckf.party-size.json`; there is no
implicit setting when the file is absent. Save uses the editor's guarded
transaction. This setting is independent of Hard Mode's switches.

After saving, choose the dedicated initialized uploader mod folder in this
section and click **Send Party Size Mod to Modkit**. The separate
`partySizeProjectDir` setting leaves the player-balance destination alone. The
handoff writes only `source_data/stories.manifest` and `party-size.json`, with
one native parser `Rule` update containing only `RuleId`, `Value` and
`SQL: update`. It refuses a manifest for another mod, changed inputs or an
incompatible parser declaration, and verifies written bytes. Rule 83 is
excluded from the Player Balance catalog and rejected by that exporter.

In the official uploader select this mod, then **Prepare Mod Data**. Inspect
`upload_content/_data/data.sql`: it must contain one `UPDATE Rule SET Value=... WHERE RuleId=83;`
statement; the locale file is empty. The resulting data mod requires no
BepInEx plugin. For the first test, submit with **Private** visibility,
subscribe, wait for Steam's download, then activate the mod in the game's Mods
screen. Later iterations can use **Local Install Mod**. These are the
[official setup steps](https://cyberknightswiki.tresebrothers.com/Modding_Quick_Start#Setup_Your_Mod).
Preparation verifies the payload, not mission behavior; check the mission
selection screen in game before publishing publicly.

Verification: `python gui/test_party_size.py` checks scope, stale inputs and
actual installed-parser output (reported skipped when unavailable);
`python gui/test_party_size_ui.py` exercises the section and save payload in
the Node DOM harness with current official data.

## Faster Contact Limit Breaks

**Faster Contact Limit Breaks** has its own navigation section for official
`Rule` rows 84 and 85. `contact_limit_breaks.py:rules` selects only those two
identities and verifies their names. The section shows both current official
baselines and descriptions. The minimum and maximum are positive integer turn
counts, with minimum no greater than maximum. They live only in
`BepInEx/config/ckf.contact-limit-breaks.json`; an absent file has no implicit
setting. A no-op save preserves both standalone mods' original bytes.

Save, choose the dedicated initialized uploader mod folder, then click
**Send Faster Contact Limit Breaks to Modkit**. Its independent
`contactBreaksProjectDir` setting leaves the other destinations alone. The
handoff writes `source_data/stories.manifest` and `contact-limit-breaks.json`,
containing only two native parser updates for `RuleId` 84 and 85 and their
`Value` fields. `rule_mod.py:send` shares guarded file handoff with Party Size
Mod and refuses another mod's manifest. The Player Balance exporter excludes
and rejects these two rules.

Use **Prepare Mod Data** in the selected uploader project. Its `data.sql`
contains exactly two `UPDATE Rule SET Value=... WHERE RuleId=...;` statements,
for 84 and 85; its locale file is empty. Follow the same private upload,
subscription, activation and in-game testing steps as [Party Size Mod](#party-size-mod).
The two standalone data mods require no BepInEx plugin.

Verification: `python gui/test_contact_limit_breaks.py` checks row scope,
independent destinations, invalid turn ranges, no-op byte preservation and
installed-parser output; `python gui/test_contact_limit_breaks_ui.py` exercises
both controls and the independent save payload.

## Send talents to Modkit Uploader

Open **Workshop export** above the editor. Set **Workshop
source repository** to a checkout of `ckf-talent-balance` containing
`scripts/export_talent_balance.py` with `build_export()`. Set **Modkit mod
folder** to the initialized `WorkshopContent/<ModName>` folder beside its
`<ModName>.workshop.json`, then click **Save folders**. The paths persist as
`talentProjectDir` and `modkitProjectDir` in the editor's settings file.

1. Edit values and click **Save** in the editor.
2. Click **Send player balance to Modkit**. It regenerates the standalone repository's
   `source_content/talent-balance.json` and `provenance/SOURCE.json`, then copies
   the manifest and parser JSON into the Modkit project's `source_data`.
3. In Modkit Uploader, click **Prepare Mod Data**, then **Local Install Mod**.
   Test the changes in game before submitting the prepared version to Workshop.

The export includes all eleven classes even when their BepInEx slice switches
are off. Keep those talent slices off when testing the Workshop package to
avoid applying both implementations. The handoff uses the standalone exporter
for native talent field mappings and `player_balance.py` for the additional
Workshop SQL. Unmoved Hard Mode settings remain in the BepInEx workflow.

The button requires saved edits and saved folder paths. The server validates
the config, checks source and destination fingerprints before replacement,
verifies the written bytes, and rolls back its own completed replacements if
the handoff fails. A conflicting Modkit manifest is refused for review.
The handoff reads the selected project's `WorkshopContent/config.json`, converts
mapped enum numbers to the parser's named values, and validates the final native
records against its field, type and value-mapping declarations. Unknown or
ambiguous mappings refuse the handoff before replacing any output. The contract
is fingerprinted with the other inputs and its hash is recorded in provenance.
Preparing SQL, installing locally, and submitting remain uploader actions.

### Workshop player catalogs

`BepInEx/config/ckf.player-balance.json` is the only authoring source for the
Workshop-owned cyberware, weapon, weapon-mod, consumable, leverage, trait and rule adjustments. It is
outside Hard Mode's overlay directory. Records are sparse adjustments keyed by
SQL table, content id and column. Clearing a cell removes its adjustment.
Shared effects have one stored value wherever the editor displays them.

Workshop adjustment cells treat plain numbers as assignments, including
negative numbers: `-10` sets to -10. `+10` adds 10 and `x1.5` multiplies by 1.5.
`=N` remains an accepted input alias; the editor displays and saves assignments
without that prefix. `=+10` becomes `10`, preserving assignment rather than
turning it into addition. `+-10` explicitly subtracts 10.
The preview, sorting and SQL export use this grammar. Consumable talent icons
use literal icon keys instead of numeric adjustments. The legacy importer
translates old `-N` subtraction into `+-N` to preserve its effect. The Hard Mode
expanded-sheet grammar below remains a separate format.

The weapon tabs put Melee, Pistol, Revolver, SMG, Shotgun, E-Rifle, Urban Assault,
Assault Rifle, Sniper Rifle, Railgun, Claws and Eye Lasers first. Canine Attack Rig belongs
with Drone weapons. Weapon and weapon-mod catalogs require a positive acquisition
reference from the selected official database: an attainable item service, direct
mission loot, a blueprint with `Lootable = 1`, or an explicit mission-loot
reference to the blueprint regardless of its `Lootable` flag. Blueprint
`ServiceOptionId` assignments do not establish acquisition; a resale category
is insufficient evidence that the player can obtain the blueprint. Weapons also
include cyberweapon talent references, canine/feline weapon
classes supported by player pet-owning jobs, pet prebuilt equipment, every
weapon tier in a class named by a pet chassis, and
the two weapon fields of explicit story `BlockCondition` `Equip` records.
Services are matched by flow and option together. Saved service and cyberweapon
pointer adjustments can add acquisition references; official references remain
included. A blueprint's existence alone is insufficient. No general character
template or recruitment rule is inferred. `player_balance.py:player_gear_references`
owns this inclusive static catalog policy; it does not calculate campaign
reachability or drop probabilities. Hover a name to inspect its source references.

Shared weapons remain editable and carry an **Also used by enemies** marker.
Enemy markers include both official and local overlay references, so a Hard Mode
repoint cannot erase a Workshop warning. The presence or absence of enemy
references does not decide player availability.
Crafted Intrinsic mods are explicitly included as player crafting options,
independently of item drops or blueprint availability.

Every weapon and weapon-mod grid has a read-only **Blueprint** column. It
shows **Blueprint** when a matching blueprint has `Lootable = 1` or an explicit
`MissionLoot` blueprint reference, including when `Lootable = 0`; otherwise the
cell is blank. Hover it to inspect the blueprint and loot-row references.
The marker uses the same `player_balance.py:blueprint_drop_references` index
as catalog eligibility. Resale assignments and the explicit Crafted Intrinsic
inclusion do not set the marker. The column stays visible with uniform values,
is searchable and sortable, and never enters saved adjustments or SQL exports.

**Other weapon overrides** appears only while weapons or weapon mods without
an acquisition reference have saved adjustments. Its separate tables retain
editable adjustments, including explicit zero and baseline-equal values. Clearing
the last adjustment and saving removes the record on reload; clearing one of
several adjustments keeps it visible. Catalog filtering never deletes tuning.

Weapon mods have three top-level categories: **Weapon Mods**, **Crafted
Intrinsic** and **Intrinsic**. Intrinsic-labelled mod classes go under Intrinsic;
other fitments that display a numbered slot go under Crafted Intrinsic.
Each category retains the independent weapon/slot subsections. Within each one, rows
group by their current `Weapon3DAsset.Thumbnail` and include an Icon column.
The join follows each mod's `Asset3DTypeId`, including saved adjustments;
different asset ids pointing to the same thumbnail share an icon group.
Groups sort by their displayed icon labels, with thumbnail paths separating
identically labelled groups. Within each group, rows default to PL, rarity, cost and name.
`player_balance.py:mod_fitment` joins `WeaponClassMod` slot declarations to
`WeaponMod.ModClassId`, applies `Exclusions`, and uses `Table.Column.ModType.*`
localization for slot names and crafting integrations. Every mod displays its
fitment. Obtainable mods without either a class mapping or a localization
declaration remain visible with an explicit unresolved fitment. The catalog
response also records these records in `unresolvedMods`.

Every weapon page ends with Special Rule notes from
`Gear.Weapon.SpecialRule.<id>` and `.Rule` localization. The notes cover the
whole section, including other pages and filtered-out rows, and update for
unsaved adjustments. Missing descriptions and game-supplied format arguments
remain explicit. These strings describe the game's rules; the editor does not
infer gameplay from assembly method names.

The default view hides uniform columns. Weapon and weapon-mod tables recalculate
visibility from effective values across the whole table when an edit is finished
(leave the cell or press Enter). A column whose values become equal hides even
if it has overrides. Invalid entries and single-row overrides remain editable.
**Show all columns** reveals hidden fields and their saved or pending overrides;
clearing those overrides restores the original visibility. Other catalogs retain
explicit overrides, including zero. Leverage and linked bonus grids show fields
with at least one nonzero baseline. Weapon and weapon-mod tables grow with
the page instead of using an inner vertical scrollbar; wide tables retain
horizontal scrolling. Names stay fixed while the grid scrolls horizontally;
large catalogs are searchable and paginated. Red marks overrides or a global
implant multiplier; yellow marks other nonzero baselines.

Weapons, weapon mods, consumables and implants default to ascending Cost.
PL, rarity and cost columns stay immediately after the name when visible. Melee and SMG rows first
group by `Weapon3DAsset.Thumbnail`, joined through `Asset3DTypeId`; the Icon
column displays the thumbnail's asset name. Weapon headers group damage,
accuracy, armor crit, crit damage, range, recoil, noise, arc, reload size and
weapon effect in that order. Varying rarity and weapon-effect fields are
included. Columns size to their longest heading or value across the full
category, including rows on other pages.

Equipment tables have **Sort by** and **Ascending / Descending** controls.
Choose Name, Service, Icon where available, or any numeric field, including
linked fields and fields hidden by the default view. Sorting uses current
adjusted values and global implant multipliers, before pagination. Missing
linked values sort last in either direction. Icon groups and weapon-mod slot
subsections stay together. **Catalog order** restores the underlying catalog order.
Each table remembers its choice while the editor is open; sorting is a view
preference and never changes tuning or Workshop exports. After editing a sort
field, click **Re-sort** to reorder the table without interrupting typing.

**Claws** and **Eye Lasers** join weapon stats, attacks and their linked self,
target and matrix effects into one row per weapon. The join follows effective
`Talent.Weapon` assignments and retains multiple attacks separately. The
weapon name uses the linked implant names, including their tier suffixes.
The **Cost** column and Cost sorting use the linked implant's price, including
its individual adjustments and global Price multiplier. Editing Cost here edits
that implant's `Cost`; existing weapon-cost adjustments remain preserved in
Workshop tuning. A missing or ambiguous implant link leaves Cost unavailable
and reports the link problem.
The regular **Service** column shows deduplicated service names from those
implants, linked through `ImplantTalentId` or `ImplantTalentId2`. Option ids and
owning implants stay in the tooltip. It follows saved adjustments and pending
edits made in Cyberware; it provides no second editable service assignment.
These rows have no separate Cyberware Service column; Service sorting and
searching use the linked implant services.
Claws omits attack range from both default and advanced columns. Other uniform
attack fields move to **Show all columns**; linked effect fields retain the
nonzero policy until edits make their effective values uniform. Existing saved
adjustments to omitted fields remain preserved and exportable.
Missing attack/effect links remain explicit. All editable joined cells retain
their native table/id/column for saving and export.

Weapons, weapon mods, consumables and cyberware always show a **Service** column with
localized names and display levels. `player_balance.py:service_catalog` joins
`ServiceOptionId` within `ContactService.ServiceFlow` (weapons 1, mods 3,
items 7, implants 8), so an option id cannot pick up a service from another catalog.
`player_balance.py:contact_services` treats `UpgradeReady = 2` as the terminal
marker within each `(ServiceFlow, ServiceGroupId)` ladder. The lowest marked
`ServiceLevel` is the cap, inclusive; higher internal levels are unattainable,
regardless of their `DisplayLevel`. Ladders without a marker remain included.
Above-cap services cannot establish weapon, mod or cyberware acquisition and are suppressed
from Service labels, including options shared with an attainable service.
Weapon/mod and consumable rows fall back to their other acquisition labels
below. Consumables use typed item and blueprint output references, including
explicit story `AddItem` grants. Nonpositive, unknown and above-cap consumable
service assignments use **Mission**, **Loot**, **Blueprint**, or both drop labels
according to those references; rows without a known source have a blank label
and an explanatory tooltip.
Cyberware without an attainable service shows **Starting Gear**, **Mission**,
or **Starting Gear / Mission**, according to its inclusive eligibility sources.
This applies to nonpositive, unknown and above-cap assignments, and to linked
cyberware service references on weapon rows. Actual attainable service names
still take precedence; invalid pending assignments remain explicit.
Cap details and source records remain in tooltips.
For weapons and mods, another attainable service or any other supported
acquisition route keeps the gear in its normal catalog. Otherwise only rows with saved overrides remain,
in **Other weapon overrides**, until those overrides are cleared and saved.
This is an editor filtering policy, not a complete campaign reachability check.
Saved and pending service adjustments affect the label; service names are
searchable. Matched service names always take precedence. For weapon,
weapon-mod and consumable grids, nonpositive assignments instead show their
availability:
**Mission** only when explicit loot/story references are the sole route;
otherwise **Loot**, **Blueprint**, or **Loot / Blueprint** according to item and
blueprint sources. Membership in a generic item or blueprint pool, or a
`Lootable = 1` blueprint, rules out Mission-only classification. Generic pool
ids are declared in `player_balance.py:GENERIC_GEAR_LOOT_GROUPS` and
`GENERIC_BLUEPRINT_LOOT_GROUPS`; `gear_service_fallbacks` owns the label policy.
Rows supported only by other sources show **Crafting**, **Cyberware**, or **Pet**.
Records retained solely for overrides have a blank availability label.
Outside cyberware, unmatched positive options retain **Unresolved service**
with the option id.
Tooltips retain the matching service or acquisition references. This is display
metadata: saving and SQL export still use the original service assignment.

Shotgun, Assault Rifle and Urban Assault rows include an **Icon / model** picker.
Choices use short visual names; unchanged and adjusted selections use the same
label format. The first choice restores the official visual. Hover for the asset
id, complete icon/model paths and example weapons, or search by thumbnail token. Choices come from official weapon references
in that class. The picker edits each weapon's `Asset3DTypeId`, so its icon and
3D model change together; it never edits the shared `Weapon3DAsset` row.
Selecting the official visual removes its adjustment. Saved assignments preview
on reload and export through Workshop player tuning.
Validation rejects fractional, arithmetic and unresolved weapon asset assignments.

Weapon mod and intrinsic fitments with multiple thumbnail paths include a
**Visual** picker. Choices come from official mod references in the same category
and fitment, including graphics with an empty model resource. Changing a visual
moves the row into that thumbnail's group immediately, while retaining its
category and fitment. The picker saves `WeaponMod.Asset3DTypeId`; its first
choice restores the official assignment. In the Assault Rifle + Urban Assault + E-Rifle
optic fitment, Scope Sowo precedes Scope Rifle. Weapon and mod icon columns hide
when every row in the table has the same effective thumbnail, even if other
choices are available. **Show all columns** reveals them for editing. Visibility
uses the full table, including filtered-out rows and other pages.

Cyberware catalogs require a positive source reference under
`player_balance.py:player_implant_references`: an attainable implant service,
explicit `Backstory.Implant`/`Implant1`–`Implant3` assignment, an implant's reference
to a defined backstory group, a player-job required implant class, or a pet
prebuilt's `CyberSlot1`–`CyberSlot5` loadout. Job-required classes retain all tiers,
including jobs not enabled for selection. Chassis slot compatibility alone does
not establish acquisition.

The inclusive story policy also retains every nonzero `Implant.Deactivated`
entry and any known implant it points to. This includes self references and
negative flags without interpreting their individual meanings. Generic
`ActivateCyber` story conditions are cited when present; they do not identify
specific implant ids. This policy preserves potential story equipment without
claiming exact campaign reachability. Hover implant names for source references.

Unreferenced implants leave the normal lists. **Other cyberware overrides**
retains them while they or their linked effects have explicit adjustments.
Clearing those adjustments and saving removes them from that page; global
implant multipliers alone do not retain individual rows. Filtering preserves
all tuning and export targets.

Cyberware tabs follow ocular, arms, skin, skeletal, deep brain, fast brain,
spinal, heart, lungs and legs, followed by other slots. Each slot has one table
with one row per implant, grouping its **Implant**, **Effects** and **Matrix
effects** fields. The joins follow saved `ImplantEffectId` and `MatrixEffectId`
assignments; each cell retains its native table, id and column for saving and
export. Shared effects identify the other implants using them, and editing a
shared field updates its other visible cells. Missing positive assignments
produce a warning and no editable cells for the missing target. Global implant
multipliers still apply to implant cost, installation time and stress.

Traits have independent score subsections, using saved score adjustments,
and linked effects group by
their owning trait names. Missing individual trait labels resolve through the
official `TraitGroup` locale key; unnamed linked effects display their related
trait level. Shared effects retain the same table/id identity
across subsections. Each grid has its own pagination.

**Cyber Knight Traits** has its own subsection, outside the score groups.
`player_balance.py:knight_trait_groups` joins nonzero-`NewGame` backstories
with `JobTypeId=1` (Cyber Knight) through their trait tags to `Trait.TagMatch`,
excludes tags referenced by other jobs' backstories, and includes the resulting
`TraitGroup` families. The catalog carries the backstory ids and fields as
classification evidence. It does not infer membership from display names.

Leverage has independent **Other leverage**, **Face leverage**, **0-token
leverage**, **Matrix-only leverage** and **Favor-cost leverage** subsections.
Face membership uses direct `Talent.ActionId` references for Face talents
targeting `LEVERAGE`. The remaining tests, in that order, use effective
`TokenCost=0`, the matrix-only flag and nonzero `FavorCost`, including saved
adjustments. Every row belongs to exactly one subsection. Other leverage
starts expanded and the special groups start collapsed; searching opens matches.

**Rules** under Player Balance reads every current `Rule` row and groups it by
`GroupId`. Names and descriptions come from `ConfigName` and `ConfigDesc`.
Numeric adjustments export with the rest of Player Balance, except Rule 82:
it is labeled **Managed by Enemy Balance**, is read-only here, and Player
Balance refuses to save or export an override for it. Its export owner remains
the [Enemy Balance workflow](../docs/enemy-difficulty-workshop.md).

**Consumables** has a page per `ItemClass`: Medical, Grenades, Devices, Chems,
Sploitkits and Matrix, plus explicitly named pages for new classes. Normal
tables include only items with a positive player acquisition reference: an
attainable item service (official or adjusted), direct item loot, a droppable
or explicitly looted item blueprint, or an explicit story item grant. Story
grants include `AddItem` and positive `Item` rewards with `OptionId = 7`;
other item types and removal conditions do not qualify.

**Other consumable overrides** retains items without those sources while the
item or its linked talent/effects have adjustments, including literal icon
assignments and explicit zeroes. Clear those adjustments and save to remove
the rows; unsaved view updates keep existing saved rows available for review.
The remaining tuning is preserved.

Each table joins item stats, actions, effects and matrix effects with one
row per item and grouped column headings. **Tag** selects the gameplay category
(Medical, Combat Drug and the other official tags). For obtainable items,
changing it immediately moves the item to its destination section, carrying
pending stat and visual edits with it. Unavailable items stay in the override
section when their tag changes. This view update writes nothing until **Save**; a refused update
keeps pending edits and offers **Retry view update**.

**Talent icon** edits the linked `Talent.IconPng`; **Item model** edits
`Item.Asset3DTypeId`. **Talent asset** separately edits `Talent.ExtraAsset`
where applicable. Medical and drug choices share a themed pool; thrown
grenades use their own pool, including healing grenades. Other item families
keep their own choices. Original and current assignments remain available for
resetting. Uniform talent-icon, item-model and talent-asset columns hide
automatically, including when pending edits make them identical. **Show all
columns** reveals them for editing. Consumables also show the read-only
**Blueprint** drop marker used by weapons and mods. Shared talent visuals use
one stored adjustment and identify other items using the record in their
tooltips.

Saved and pending item/action pointers determine the join. Separate self/target
effects get separate column groups when needed;
a common target is represented once. Missing targets are named as unresolved,
and absent links have no editable cells. Each cell retains its native
table/id/column address for saving. Shared actions and effects keep one stored
adjustment, synchronize their visible cells as you type, and identify other
items using the same record in their tooltips. These adjustments export through
Player Balance. The legacy Player Weapons, Consumables, Game Constants and
Mission Power Level Ceiling controls are omitted from the navigation; their
declarations remain available to validation and the plugin.

Numeric baseline placeholders show the number alone. Legacy `_comment` fields
remain on disk for compatibility and byte-preserving saves but have no raw
comment column in the UI. Talent grids retain their semantic Node & details
display so node names and associations remain readable.

**All cyberware** edits price, installation-time and implant-stress multipliers.
SQL applies individual adjustments first and global multipliers last, matching
the former rule order. The global UPDATE has no row selector: it also reaches
modules and rows introduced after export. Integer conversions use ties-to-even
rounding before arithmetic and on each integer write. Implant placeholders
include the global sweep; tooltips identify its multiplier.

Fatigue's configured traits, their effects, and the limit-break overlay effects
are read-only in the Workshop catalog. Their source and runtime owner remain
Hard Mode. The separate Hard Mode controls remain available.

Set **Official data.db** to the developer-provided content database. Every model
request opens a fresh read transaction. While the editor is open, it checks for
replacement every 20 seconds and reloads clean working copies. Pending edits
are preserved with a warning; saves and exports refuse changed fingerprints.
Talent catalogs refresh through `talent_catalog.complete` when the database
changes, preserving exported assignments; a failed refresh reports its reason.
An absent, corrupt or incompatible database shows a warning instead of a stale
catalog. No encrypted game/save database is used.

`transfer_player_balance.py` is an explicit one-time maintainer transfer. It
guards and verifies a batch that imports legacy cyberware adjustments, clears
their old cells, neutralizes the old global settings, and clears the two moved
or retired combat-rule cells. It refuses to overwrite existing player tuning.

## What it edits

Every file a schema names in `targets`, all under `BepInEx/config/`:

| File | What |
|---|---|
| `ckf.hardmode.cfg` | 49 keys: `[General] Enabled` and 48 `[Slices]` toggles. |
| `ckf.hardmode.d/*.json` | Ten settings documents stamped `4.1.0` (`difficulty`, `elapse`, `fatigue`, `implants-global`, `missions`, `modelrules`, `powerlevel`, `rewardcurve`, `selfcheck`, `teampl`), plus `MissionPowerLevelModel.generated.json`, which the editor regenerates from `teampl.json` and never edits directly. |
| `ckf.hardmode.d/*.csv` | The overlay and lever sheets a schema lists in `targets.overlays`. Only lever cells are editable. |

Not opened: `ArmorModel.csv`, `WeaponModel.csv` and `MonsterTypeModel.csv`, the generated enemy-gear overlays, which no schema claims. The nav's *Enemy Gear* group says so. `ckf.hardmode.selfcheck.csv` is not edited either.

## How editing works

### The `.cfg`

`serve.py:CfgFile` edits the file line by line:

- An existing key's value line is replaced in place and keeps its own line ending. A file with nothing edited is written back byte for byte, BOM included.
- A declared key that is missing is appended as `Key = Value` after its section's last line. A missing section is created at the end of the file. No comments are written, because BepInEx writes those on the next launch.
- Refused: a key no schema declares, a value with a line break, a value whose first non-blank character is `#`, and any cfg edit when the file could not be read.
- Keys are never deleted. BepInEx re-adds a bound key at its code default.

A gate checkbox is disabled only when the slice has no slot (`app.html`: `cb.disabled = !slot`); a key absent from the file stays settable because saving appends it. `gatedByMaster` is a separate pill: it means `[General] Enabled = false`, which stops `Plugin.Load()` before any slice, a different fact from the slice's own key being false.

Slice dependencies (`requires` invariants, `serve.py:requires_pass`): turning a slice on also turns on the slices it needs, and a note says what changed. Turning off a slice that an enabled slice needs is refused, and the refusal names the dependent slice. `linkedEnable` groups move together from one checkbox. Their keys are spelled `<file>#<section>.<path>`.

### Sidecar JSON

- Written as strict JSON. With `stripReadme` on (the default), a top-level `_readme` block is removed and the save notes say so.
- Top-level keys no schema declares are kept on disk and written back unchanged, and the page lists them. Annotation keys inside rows are hidden from the grids and preserved.
- Unset is not zero. Each value is a pair: present or absent, plus the value. On the wire, `null` means absent. The writer removes an absent key rather than writing `0`, and an unchanged value keeps its exact on-disk text (`1.0` stays `1.0`).

| Control | Empty means |
|---|---|
| Numeric cell | Absent (hatched, `— unset —` placeholder). A typed `0` is a real zero. |
| Text cell | An empty string, which is a real value. On `"format": "adjust"` columns the plugin treats empty and absent the same, so clearing one turns that slot off. |
| Matrix cell | Removes the override row. The inherited stock value shows as the placeholder. Rows and columns added with "add row"/"add col" start unset. |
| Curve chart | An unset point is not plotted, so the line breaks. |

### Lever sheets

The server grades each column (`serve.py:overlay_roles`, `overlay_editable`) and the page reads the result as data (`entry.roles`, `entry.editable`). Direct overlays use their first-column id as the row key; expanded sheets use their expander's identity columns.

### Complete talent catalogs

`talent_catalog.py` is the guarded annotation pass used when official data changes. It adds missing
class JobNode rows and related records to the already declared talent sheets,
leaves all new override cells blank, and preserves existing override cells.
Class ownership comes from `JobNodeModel.JobId`, including every declared
version; ids are never assigned to a class by their digit prefix.

Comments show the node name. Attribute nodes
keep Left/Center/Right names in the EffectModel table, where their comments
list connections without claiming a required path through them. Numeric tuning
belongs in editable cells, with numeric baseline placeholders. Comments omit tuning numbers, old balance notes, and repeated ids.
The `_shipped` JSON control cell carries the complete editable baselines,
including zeros and the JobNode IconPng text field, without displaying them as prose.
The pass reads the selected official content database and also accepts explicit
historical captures with coverage checks. It adds declared node tuning and all
numeric Effect fields from the Modkit parser contract, excluding keys and text
asset fields, creating the Hacker effect and Wireghost talent sheets when needed.
It refuses ambiguous or missing references, then compares the
exported assignments before writing so a catalog update cannot change tuning.
Attribute EffectModel rows also carry `_attribute_nodes`, a hidden list of
directly linked JobNode ids. The Modkit exporter uses those captured links for
automatic attribute icons; it does not join records by their display names.

The `_group` and `_node_kind` controls record section and node classifications
for the legacy sheet renderer. The joined view reads the official node links
directly. These controls are not editable or exported as SQL fields.
`talent_editor.py:catalog` builds the class pages from the selected official
content database. The first table joins JobNode and Talent fields on each node;
effect and matrix-effect tables follow. Attributes join node and effect fields,
ordered Left, Center, Right, with Extra Item Carry and its carry upgrades last.
Class roots stay hidden; base talents remain visible. Every table scrolls with
the page. Filtering and **Show all columns** follow the weapon editor's layout.
Zero-only and metadata columns are omitted by default; explicit overrides,
node icons, effect pointers and the declared always-visible attribute fields remain
available. The Talents and upgrades table omits the node Effect and Matrix effect
pointers, Talent self/target/matrix effect pointers, and Talent icon; the Effects
table omits its icon. These view
choices also apply with **Show all columns** and preserve stored adjustments.
**Show all columns** exposes the remaining declared fields.

Each cell retains its native table/id/column address. Existing sheet columns
save through the byte-preserving sheet writer. Newly exposed fields use sparse
Workshop tuning in `ckf.player-balance.json`. Clearing a cell restores its official
baseline. Icon fields offer existing `IconPng` or `IconAsset` values; effect
pointers offer the appropriate table's ids. Saved pointers determine the next
loaded view. A manual Workshop node icon takes precedence over an automatically
derived attribute icon; conflicting authored native assignments still refuse export.

Explicit overrides are red. Nonzero numeric baselines are yellow, except that
JobNode BuyCost 1 and Talent baselines stay plain. Text baselines stay plain.

**Remove** is available only on upgrade nodes with a positive `SubTree`.
Base talents and class roots cannot be removed. **Restore** undoes a removal.
The requested ids are stored as `removedJobNodes` in Workshop tuning.
`talent_tree.py:plan` replaces incoming prerequisites with the removed upgrades'
nearest surviving prerequisites, preserving all slots and refusing overflow
beyond three. Export applies those repairs before deleting the selected rows.
Surviving upgrades are retained, and clearing a removal restores their original
connections on the next export.

Save, Validate and Workshop export check structural reachability from each
class's declared default nodes, following directed `NodeReq1`–`NodeReq3` edges.
This is a graph check, not a claim about the game's purchase conditions.
Per David's policy, unreachable nodes and dangling requirements already present
in the selected shipped database are exempt; newly unreachable nodes or dangling
requirements block the operation. Exemptions are recomputed from that database,
not stored in a tolerance list. Checks use proposed sheet edits and Workshop
adjustments together. No save database is opened or written.

Page-level details and usage instructions appear in **Editing help**, after
the controls and tables. Short field descriptions and blocking errors stay
beside the controls they explain.

To refresh the annotations from an independently captured stock dump:

```bat
cd /d "D:\ckf-data-modding"
python "D:\ckf-data-modding\gui\talent_catalog.py" --config "C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint\BepInEx\config" --data "D:\ckf-data-modding\Official\data.db" --project "D:\ckf-data-modding\ckf-talent-balance"
```

| Role | Editable | Why |
|---|---|---|
| `lever` (not index 0) | yes | An override value. |
| `identity` | no | Names which rows the line expands into. Identity names come from the expander modules' `IDENTITY` lists. |
| `control` | no | Header starts with `_` (`_comment`, `_clone`, …). |
| index 0 | no | The key column. Held out even if it would grade `lever`. |

- A row is addressed by its full identity-key tuple, never by position. A key that matches zero rows or more than one row is refused.
- A blank cell means "leave the game's column alone". The writer emits an empty field, never `0` or `""`.
- A save replaces one field's character span on one line. The header, other rows, quoting, column order and trailing newline are untouched.
- An empty lever cell shows the sheet's shipped value as a placeholder when the `_comment` prose carries `Shipped: …` (`serve.py:_SHIPPED_RE`).
- Shared rows stay writable and carry `repoint: true`.
- If any expander module fails to import (`SHEET_SOURCE_ERROR`), every sheet refuses writes (`serve.py:overlay_writable`). A shortened identity list would otherwise make identity columns editable.

**Cell grammar.** On expanded sheets each cell is an adjustment (`serve.py:parse_adjust`):

| Cell | Meaning |
|---|---|
| blank | no override |
| `N` or `=N` | set |
| `+N` / `-N` | add |
| `*N`, `xN`, `XN` | multiply |

`NaN` and `Infinity` are refused, which is stricter than .NET's `double.TryParse`. On direct sheets the operator is in the column header (`Col`, `Col*`, `Col+`, `Col>`, `Col<`: set, multiply, add, clampMin, clampMax), and a cell must be a number. The one exception is a plain-set column: non-numeric text there is accepted with a warning note. `app.html:overlayCellProblem` mirrors `serve.py:overlay_check_cell` so the page can mark a bad cell before saving, but only the server refuses.

**Refused lever edits** (all raise `SaveRefused`, nothing written): the key, an identity or a control column; a cell the grammar rejects; a line break in a cell; a row key with no match, several matches or the wrong number of parts; an unknown or duplicated column name; a sheet no schema declares; a sheet that is unreadable or not UTF-8.

### Hidden and collapsed columns

Columns can leave the default grid view for three independent reasons. All keep the column in the model, the working copy and the save. The sheet's notes name each one with its reason, and a `Show N column(s)` button brings them back for that table.

The attribute EffectModel grid keeps any column with an explicit override
(including zero or the same override on every row), differing shipped values,
or an unknown baseline in its attribute rows. Pending edits count as overrides.
These protected columns bypass every hide and collapse rule. Remaining fields
are filtered using
`serve.py:ATTRIBUTE_EFFECT_COLUMNS`: permanent fields represented on captured
attribute nodes, plus `MoveSpeedMitigate`. It excludes downside fields, temporary
effects and effect metadata, including `EffectClassification`. This section
policy does not remove data or restrict the regular talent grid; showing
collapsed columns still respects it. All four attributes and Move Speed
Mitigation always appear in the attribute grid, including on classes with only
zero baselines for those fields.

The regular EffectModel talent grid omits `AttStrong`, `AttFast`, `AttWill`,
`AttTech` and `MaxHitPoints`, including when collapsed columns are shown.
This presentation rule leaves their stored values and save payload untouched;
the attribute grid retains its override and variation protections.

- **Hidden by name.** `serve.py:HIDDEN_COLUMNS` covers `ImplantLevel`, `Deactivated`, `Rarity`, `PowerLevel` and `ImplantConflictId` ("item metadata, not a combat lever"). Never index 0. There is no row-count exemption.
- **Never changes.** `app.html:overlaySuppressed` hides a column whose value is the same on every row, except for key columns, sheets with fewer than two rows, editable columns that are blank everywhere, and talent-catalog lever columns. Catalog tuning stays visible even when all its overrides are equal.
- **Untouched zero defaults.** `app.html:overlayZeroColumns` collapses plain-set numeric columns only when every cell in its visibility scope is blank and its measured shipped baseline is zero. EffectModel talent catalogs use the whole class's sheet for both their attribute and talent grids; other tables use their displayed rows. Any explicit override, including zero, keeps the column visible, as do missing baselines, text and other operators. Pending edits are included.

The named and constant rules reach the page as separate keys (`entry['hidden']`, `entry['constant']`, from `overlay_hidden` and `overlay_constant`); keep them separate. Zero detection uses the values and baselines already in the model. `app.html` names no column.

Rows can be withheld too. `serve.py:GUI_EXCLUDED_ROWS` withholds Workshop-owned
rows from legacy overlay grids while preserving their file contents. The
Consumables catalog reads every item row from the selected database.

The Team PL matrix draws `MissionPowerLevel` 1–10 only (`serve.py:AXIS_WINDOWS`). A value outside that range is still drawn, and the legend explains why. The save uses every row.

## Save and validation

`serve.py:App.api_save`, in order:

1. **Stale check.** If the SHA-256 of any file the editor reads (`fingerprints`, which covers the cfg, the sidecars, the mirror and every declared sheet) changed since the page loaded, the save is refused.
2. **Build.** Adjust-grammar check, then `requires_pass`, then `apply_edits`. Any refusal raises `SaveRefused` rather than `assert`, so the checks survive `python -O`. The Team PL mirror is regenerated through `scripts/gen_teampl_labels.py` in the same save as `teampl.json`.
3. **Validate.** Every file `check_schema` reads (`files_check_schema_reads`) is copied to a temp directory with the proposed bytes overlaid, and `schema/check_schema.py` runs on that directory in a child process (`run_check_schema`). `RANGE` and `INVARIANT` block the save; `STALE` and `MISSING` are reported only. The save is also blocked if the checker could not run, or if its trailing `N problem(s).` line is missing or disagrees with the problem lines it printed.
4. **Commit** (`commit`). Each changed file is written to a temp file beside its target and fsynced. Then a journal (`.ckf-gui-save-journal.json`) naming the renames is written atomically, the renames run back to back with the mirror first (`mirror_first`), and the journal is deleted. Unchanged files are skipped. On startup `recover_journal` finishes any renames a crash interrupted, following only renames that stay inside the config directory and within one directory.
5. **Report.** `check_schema` runs again on the real directory. The response includes the notes and a reminder to restart the game, because each subsystem reads its config once in `Plugin.Load()`.

`check_schema.py` declares no columns for lever sheets, so every sheet save carries `NOT VALIDATED AGAINST A SCHEMA` in its notes. Only the grammar and row identity were checked. **Validate** runs steps 2–3 without writing. The Save button is disabled when nothing has changed, the config directory is missing, or the checker did not run at load.

## How rendering is driven by the schema

- Each field's `ui` picks the control: `form`, `table`, `curve`, `matrix`, `readonly`, `hidden`. The selftest asserts the set is exactly these six. A lever cell is an ordinary `table` cell that the server marked editable.
- `matrix` is laid over the field named by its `over`. A `readonly` field that another field declares as its `over` underlay is drawn as that matrix's grid; otherwise it is a plain grid.
- `table` has two on-disk shapes. With `keyedBy` it is an object keyed by that column (the two fatigue curves, `byPowerLevel` and `knight.byPowerLevel`, by `powerLevel`; `elapse.tiers` by `name`); without it, an array. The shape found on disk is preserved, and `keyedBy` only decides the shape of a table that doesn't exist yet. Saving an absent table empty doesn't create `{}` or `[]`.
- A string column counts as an adjust column when it declares `"format": "adjust"` (the five slot columns in `missions.json`). With no declaration, a column counts when every non-empty value parses as an adjustment.
- `retroactive` (on `teampl`'s `enabled` and `override`) is passed to the page as data. The page builds no warning or confirmation from it.
- A gate that could not be read shows as unknown, never as off. Each subsystem page has one gate control with three states: on, off, and indeterminate (unreadable). A key missing from the file is still settable ("not in the file yet — saving adds it").
- **Nav.** Groups and order come from `serve.py:SECTION_GROUPS` and `SECTION_LAST`. The master-switch section is derived from `MASTER_KEY` and pinned first. A section with several gates folds them into a `<details>` summary that reads `on/declared`, adds ` ?` when some gates are unreadable, and reads `N pages` when the section declares no gates.
- **Help text.** Uses `uiDoc`, falling back to `doc`. At render time `strip_maintainer_marks` removes evidence tags (`[measured …]` etc.), parentheticals made up entirely of citations, and a trailing citation. The schema files are not changed.
- Per-sheet notes render inside a closed `<details>`, and their text stays in the DOM.
- **Grid column width** (`app.html:colWidth`): 120% of the widest content plus 2ch, capped at 44ch.

Display-only tables in `serve.py` (none of them changes what is read or written): `SECTION_GROUPS`, `SECTION_LAST`, `AXIS_WINDOWS`, `REFERENCE_GROUPING` (groups `RuleModel.ruleReference` by `GroupId`), `HIDDEN_COLUMNS`, `GUI_EXCLUDED_ROWS`, and the derived `COST_LABELS` and `ROW_LABEL_SHEETS` (weapon-class ids drawn by name).

## Security

- Binds `127.0.0.1` only.
- GET serves only `/` and `/app.html` (the same fixed file) and `/api/model`. POST serves `/api/validate`, `/api/save`, `/api/settings` and `/api/quit`. No request path is ever mapped to a file.
- Every request must have a matching `Host` (otherwise 421). Every API request, including `/api/model`, needs the per-process token in `X-CKF-Token`, and a present `Origin` must match. The server substitutes the token into the page when it serves it.
- POST bodies are capped at 32 MB. Responses send a restrictive `Content-Security-Policy`, `nosniff` and `no-store`.
- The only path a client can supply is the game/config directory. Filenames come from the schemas' `targets`.

## Self-tests

`python gui/serve.py --selftest [--config DIR] [--frozen-exe EXE]`

The suite only reads the source config and works inside temp directories. The source is `--config` if given, else `<repo>/live-config` if that directory exists, else the config `settings.json` points at. If none of these exists, the suite exits and names what it looked for. Copy a config that is still being written (for example a synced or staged mount) to a local directory first, or the copy can fail partway.

Sections cover: the adjustment grammar; that every schema field gets a control; round trip without edits; unset vs zero; both table shapes; adjust-column inference; the server and the save transaction (mirror, the four check classes, stale fingerprints, lever-sheet writes and every refusal, `SHEET_SOURCE_ERROR` injection); `.cfg` mixed line endings and the append/section-create scenarios; concurrent requests during validation; a crash between renames; the HTTP guards; presentation (order, grouping, prose stripping, `uiDoc` on every schema); hidden, collapsed and cleared values reaching disk; `app.html` pure functions; a rendered `app.html` under a CSS-less DOM stub with `fetch` stubbed; the frozen re-entry (both argv shapes, `--run-check-schema` as a subprocess, and broken child processes that must count as "could not run"); fixture-source selection; and game-directory resolution.

- `hardcoded_names_in_app_html` fails if `app.html` names a schema path, column, cfg key, section or file. `undeclared_globals_in_app_html` fails if the page assigns an ALL-CAPS name it never declares.
- `--frozen-exe EXE` runs the frozen cases against a built exe: it serves the page, answers `/api/model` with a complete checker result, reads `docs/mission-reference.json` from its bundle, and writes settings beside itself. Teardown kills the whole process tree (`_kill_tree`) and asks the OS what is still running (`_procs_from`, `_procs_settle`). Without the flag these cases report NOT RUN, which is not a pass.
- There is no migrator block. It converted `tests/fixture-3.0.0` and compared the output byte for byte against the live config, which only ever held while that config was the shipped defaults; it was deleted rather than left reporting NOT RUN (AGENTS.md §10). `--migrate` itself is unaffected, and nothing now compares `MIGRATION_DOC_VERSION` with `Defaults.DocVersion`.
- A case that cannot run reports NOT RUN with a reason and is not counted as a pass.

`--selftest-js` extracts the region of `app.html` between `/*==CKF-PURE-BEGIN==*/` and `/*==CKF-PURE-END==*/` and runs it under `node`. Keep DOM and network code outside that region. It exits 2 if `node` is not on PATH.

The suite checks structure only. No automated check sees CSS or a drawn page, so layout, placeholders, dirty marking and the collapsed-column styling have to be checked by eye in a browser.

### Migrator details

- `migration_cfg_stamp_header` replaces only the version token in the `.cfg`'s BepInEx header line; a header of any other shape is refused before anything is written.
- Only a top-level `enabled` is removed, and only from the sections in `MIGRATION_RETIRED_GATE_SECTIONS`. The nested `credits.enabled`, `stress.enabled` and `woundResist.enabled` are live settings and stay.
- `MIGRATION_CLOSED_DIVERGENCES` is a record of closed divergences. Nothing reads it now that the selftest's diff is gone; it is kept as the record, and an entry is never the way to make a check pass.
- `IMPLANTS_GLOBAL_DOC` copies `implants-global.json`'s `_doc` word for word. Edit both together.

## Build the maintainer release executable

Players use the executable from the release zip. Building and packaging that
executable is a maintainer path. `scripts/make_release.py` runs PyInstaller on
`gui/ckf-config-editor.spec` into `dist/`, then runs
`serve.py --selftest --frozen-exe` against the result before packaging. By
hand:

```
pip install pyinstaller
pyinstaller gui\ckf-config-editor.spec          # -> dist\CKF-Config-Editor.exe
python gui\serve.py --selftest --frozen-exe dist\CKF-Config-Editor.exe
```

- The output is a single file; nothing is installed on the player's machine.
- Run the spec from the repo root. It bundles `gui/app.html`, `schema/*.schema.json`, `schema/check_schema.py`, `scripts/gen_teampl_labels.py` and `docs/mission-reference.json`. `check_schema` and `gen_teampl_labels` are both hidden imports and data files. Keep `check_schema.py` as a data file: together with the `--schema` that `run_check_schema_entry` adds when the caller names none, it is what lets the frozen checker find the schemas. Remove both and the exe validates nothing.
- `console=True`, so the listening URL and any traceback stay visible. `upx=False`, because UPX-packed exes get flagged by antivirus.
- The bundle keeps the repo layout (`gui/`, `schema/`, `scripts/`, `docs/`) under `sys._MEIPASS`, so `serve.py` derives every path the same way it does in a checkout.
- Frozen, settings are written beside the exe as `CKF-Config-Editor.settings.json`, which after install is the game root. `_MEIPASS` is deleted when the exe exits.
- Frozen, `sys.executable` is the exe itself, so `check_schema_argv` validates by spawning `CKF-Config-Editor.exe --run-check-schema --config DIR` without `--schema`, and the child resolves its own bundle. Each validation pays one bootloader unpack. The save-blocking rules are the same frozen and unfrozen.

## Known issues

- **A refused save discards all pending edits.** The Save handler calls `await load()` unconditionally after `/api/save` (`app.html:3113`), which rebuilds the working copy. **Validate** doesn't reload.
- **Nav rows can't be reached by keyboard.** Each `.navitem` is a `div` with `onclick` and no `tabindex` or `role` (`app.html:1616-1620`). The `<summary>` and the gate checkboxes inside it can be focused.
- **Stale source comments in `serve.py`.** The module docstring (`serve.py:14-27`) still describes the 3.x layout (a one-key `.cfg`, `ckf.hardmode.json`, sheets not owned). `serve.py:1056-1060` says the editor never writes overlay files. `serve.py:209-215` says "these four tables" and "nothing else in this file names … a column", but there are more tables, and `overlay_labels` checks for a column literally named `Cost` (`serve.py:1699-1700`).

## Related

- [`../release/README.md`](../release/README.md): the templates packaged with the exe
- [`../docs/workflow.md`](../docs/workflow.md)
- [`../docs/gotchas.md`](../docs/gotchas.md)
- [`../schema/SCHEMA-FORMAT.md`](../schema/SCHEMA-FORMAT.md) ([`ui` kinds](../schema/SCHEMA-FORMAT.md#ui))
