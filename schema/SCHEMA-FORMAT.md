# CKF Hard Mode config schema — format

One schema file per subsystem, in `schema/<subsystem>.schema.json`. The schema
is the single source of truth for every configurable value: name, location,
type, default, range, documentation, and what gates it.

**This document is the grammar** — what keys a schema file may carry and what
each one means, not a list of the values themselves.
`../docs/config-reference.md`, generated from the schemas by `scripts/gen_docs.py`,
is the per-key reference and is authoritative for any actual value;
`../docs/gotchas.md` owns traps and dead ends; `../docs/workflow.md` owns install,
dump and test procedure.

If a value is not in a schema file it does not exist: `schema/check_schema.py`
reports any cfg key no schema declares as `STALE`. It is the verifier for
everything below — run it against a config directory rather than reading a field
count out of this document, which nothing regenerates.

Readers: `gen_binds.py` (emits `Plugin.Binds.g.cs` from every `"in": "cfg"`
field, and compares the slice set against the key set in both directions;
`--check` verifies without rewriting), `gen_docs.py`,
`gen_teampl_labels.py` (the one `mirror` invariant), the GUI, and
`check_schema.py`. `validate_rules.py` uses `range`, `type` and `invariants` but
does **not** read the schema today.

**The config files are pure data.** Every `//` block and `_readme` array was
moved out of the sidecars into `../docs/config-reference.md` via the `doc` strings;
the merged document parses under strict `json.load`. Prose with no schema home
was not carried forward.

**One file, nine sections, one cfg key (3.0).** The five 2.x sidecars became five
sections of `ckf.hardmode.json` in Phase 2, and Phase 3 added four more —
`difficulty`, `modelrules`, `powerlevel`, `selfcheck` — out of the 21 cfg keys it
deleted. `[General] Enabled` is the only key left in `ckf.hardmode.cfg`, because
it is the switch that has to work when the merged document does not exist at all.

**Correction, 2026-09-13 — that is no longer the shape.** The paragraph above
describes 3.0 and is kept as the record of it; it is not the current state.
Phase 1 of `split-config-into-toggleable-slices` declares **43 cfg keys across
43 schema files**: `[General] Enabled` plus one `[Slices]` key per slice. The
reason is the one the paragraph gives, generalised — a gate cannot live inside
the file it gates, so every toggle moves to the file that must parse before any
other loading happens. **All forty-three are bound and on disk.**
`Slices.Init` walks `Binds.All` and binds each key
(`../mods/CKFHardMode/Slices.cs`); `Plugin.Load` calls it above the
master-switch bail-out, so BepInEx writes every line on any launch, including
one where the mod is off. That is now measured on disk rather than derived from
the C#: after a launch on 2026-09-13, `check_schema.py --game` printed

```
0 problem(s). 43 cfg key(s) on disk, 43 declared across 43 schema file(s).
```

at rc 0. [measured, `../Logs/gates-phase1b.txt`, gate 01]

**Correction, 2026-09-13, same day.** The paragraph above first read
"Forty-two of the forty-three are **declared and not yet on disk**: nothing
calls `Bind` for them (`Plugin.cs:161` is the plugin's only `Binds.Bind` call
site), so BepInEx writes no line for them and `check_schema.py` reports each as
`MISSING`." That was measured and true when written, and stopped being true
hours later when `Slices.cs` was added. It is left visible because it is the
second time in this document that a statement about another file's current
state has gone stale without anything regenerating it — the same failure the
2026-08-31 note below describes.

**Correction, 2026-08-31.** That paragraph used to end "the sidecars on disk
still carry them until that pass runs" — true when written, false once the strip
ran. It is noted rather than deleted because it is the shape of claim that goes
stale silently: a statement about the current state of a file, in a document
nothing regenerates. Cite what a file *is*, not what it is *about to become*.

---

## Top level

```json
{
  "subsystem":  "Elapse",
  "title":      "Mission elapse penalty",
  "doc":        ["line", "line"],
  "targets":    { "json": "ckf.hardmode.json", "section": "elapse",
                  "legacyJson": "ckf.hardmode.elapse.json" },
  "enable":     { "json": "enabled" },
  "fields":     [ ... ],
  "invariants": [ ... ]
}
```

| Key | Meaning |
|---|---|
| `subsystem` | The subsystem's name, and the GUI tab. It was the `.cfg` section name too until 3.0 left one section in that file; the document section it owns is `targets.section`, which is the same name lower-cased except for Progression (`teampl`) and MissionRewards (`missions`). |
| `title` | Human name for the GUI, in **Title Case** — `Mission Fatigue`, `Baseline Reward Curve`. `gui/serve.py --selftest` asserts it. |
| `doc` | Array of lines. Source for `../docs/config-reference.md` and, where no `uiDoc` is present, the GUI's section text. |
| `uiDoc` | Optional. Same shape as `doc`; a blank entry is a paragraph break and nothing else. The **player-facing** description. The GUI prefers it and falls back to `doc`. |
| `targets` | Which files this subsystem writes. `json` is a path **relative to the config directory**, `ckf.hardmode.d/<slice>.json` — `check_schema.py` joins it onto `--config`/`--game`'s `BepInEx/config`, so the subdirectory is part of the name. `overlays` is a **list** of such paths, for direct-overlay CSVs; see below. `legacyJson` is the 2.x sidecar it came from, or an explicit `null` for the four sections created in 3.0. `cfg` is `ckf.hardmode.cfg` and **declaring it is what makes the schema a slice**: `gen_binds.py` requires exactly one `"in": "cfg"` field in a schema that declares it, and none in a schema that does not. |
| `enable` | The AND-chain, outermost first. Since 3.0 there is one link for every subsystem: `json`, the section's own `enabled`, read after the document loads. `cfg` survives on `general.schema.json`, the master switch. A field may add a level below with `enabledBy`. |
| `invariants` | Cross-file rules. See below. |

**Changed in 3.0: `targets` and `enable`.** Both used to name `ckf.hardmode.cfg`
on all ten schemas, because 21 settings lived there. Phase 3 moved them into the
merged document.

**Correction, 2026-09-13.** That paragraph used to end: "so a schema that still
declares `"cfg"` in `targets` and is not `general.schema.json` is stale rather
than valid: `gen_binds.py` would emit a BepInEx bind for its keys, and BepInEx
would write them back into a file nothing reads." **That rule is reversed.**
`targets.cfg` on a schema other than `general.schema.json` is now the normal,
required case — it is the declaration that the schema is a slice — and a
`[Slices]` key is read by the plugin rather than by nothing. The reasoning in
the old sentence was sound for 3.0 and wrong the moment the toggles moved back;
it is quoted rather than deleted because a rule stated as a permanent property
of the format, with a mechanism attached, is exactly the shape that survives the
change it no longer describes.

`enable` has **not** moved with it. Every subsystem's `enable.cfg`/`enable.json`
chain is untouched by Phase 1 task 1; the nine subsystem sections still carry
their own `enabled` field and that field is still the live gate. Phase 1's third
checkbox is what deletes it and repoints `enable` at the `[Slices]` key. Until
then a subsystem has two declarations and one live gate, and the live one is the
JSON field. [measured 2026-09-13]

### `targets.overlays` — the files in `ckf.hardmode.d/` this slice owns

```json
"targets": {
  "cfg": "ckf.hardmode.cfg",
  "overlays": [
    "ckf.hardmode.d/EffectModel.sol.csv",
    "ckf.hardmode.d/JobNodeModel.sol.csv",
    "ckf.hardmode.d/TalentModel.sol.csv"
  ]
}
```

A list of paths relative to the config directory. `check_schema.py` asserts each
one **exists**, records which schema claimed it, and never opens it.

**IT ASSERTS NOTHING ABOUT WHAT KIND OF FILE IT IS**, and that is deliberate.
`design.md` §1 splits these files in two — a **direct overlay**, whose filename
names a game table and whose rows are rows of it, and a **lever sheet**, whose
rows are player concepts that one expander turns into many writes. `targets.overlays`
holds both. Established by reading the five members that touch an entry rather
than from the key's name: the `claimed_overlays` build loop (`main`) only does
`setdefault(rel, []).append(subsystem)`; the existence check calls
`os.path.exists(os.path.join(cfgdir, rel))`; `on_disk` filters `os.listdir` on
the `.csv`/`.tsv` extension, which is the same filter `Overlays.Load` uses to
pick files out of that directory and says nothing about their rows; `unclaimed`
and the double-claim check are set membership on the path string; the census
line counts. **Nothing opens a file, splits a filename on `.`, reads a header, or
consults a dump.** [measured 2026-09-13] So the key is honest for both kinds and
no second key is needed.

**If a dialect check is ever added here, that is when a kind marker earns its
place** — a check that verified "the first column is the table's id column"
would be wrong about `gear-classes.csv` in a way that looks right, inferring a
game table called `gear-classes` that does not exist. Add the marker with the
check that needs it, not before.

**Until then the schema states the kind in prose, and every lever sheet must.**
Nothing parses it — that is the difference between this and the `_comment`
parsing rejected under `"in": "reference"`, which would have made a free-text
field load-bearing. This is a reader's note, and Phases 6, 7 and 8 add more
lever sheets:

| file | kind | why |
|---|---|---|
| the 32 pack CSVs, `RuleModel.csv` | direct overlay | filename names the table; first column is its id column |
| `gear-classes.csv` | **lever sheet** | 10 rows, 24 columns, first column `WeaponClass` carrying ids 1, 2, 3, 4, 5, 6, 10, 11, 12, 14. No game table is called `gear-classes`, and a row is a class, not a row of one. `GearClasses.cs` expands each into a rule with a `WeaponClass` selector and an enemy-id exclusion set. [measured 2026-09-13] |
| `cyberweapons-lasers.csv` | **lever sheet** | 17 rows, 19 columns (18 named + `_comment`). First column is `WeaponName` and repeats four times per family. `Cyberweapons.cs` splits each row into a `WeaponModel` rule and a `TalentModel` rule. [measured 2026-09-13] |
| `cyberweapons-claws.csv` | **lever sheet** | 16 rows, 13 columns (12 named + `_comment`). Same shape and same expander. [measured 2026-09-13] |
| `implants-slot01.csv` … `implants-slot11.csv` | **lever sheet** ×11 | 178 rows and 82,856 bytes in total, 15 to 33 columns each, first column `ImplantName`. No game table is called `implants-slotNN`; `implants.py` expands each row into `ImplantModel` and `EffectModel` writes. [measured 2026-09-13] |

`gear-classes.csv`'s 22 lever columns are `WeaponModel` column **names**, which
is what makes it read as a direct overlay at a glance. The row is what differs,
and the row is what the distinction is about.

**Why a second key rather than reusing `targets.json`.** `targets.json` is
single-valued and JSON-only, and both halves are load-bearing. The pre-pass in
`main` does `load_jsonc(p)` unconditionally, so a `targets.json` pointing at a
CSV that is present raises an uncaught `json.decoder.JSONDecodeError` and **the
run dies with a traceback instead of producing a graded problem** — gate 01
stops being a check. With the file merely absent it reports
`MISSING … sidecar <name> not on disk`, which is a plausible-looking line with
the wrong reason. [measured 2026-09-13, both] Single-valued is the other half:
a talent pack is two or three files, and one schema could not name them.

**The schema does not declare overlay columns.** The header of the file is the
authority: `scripts/rules_to_overlays.py` derives each file's columns from what
that pack's rules actually touch, and across the 32 pack files they range from
2 to 15. A static `row[]` would be 32 hand-copies that go stale the next time
that script runs. The dialect itself is `Overlays.cs`'s header comment — the
table is the filename before the first dot, the first column is the id column,
the operator is a suffix on the column name (`Column` set, `Column*` multiply,
`Column+` add, `Column>` clampMin, `Column<` clampMax), and `_clone`,
`_comment` and `_serveOn` are control columns. Across all 33 files shipped on
2026-09-13 the header tokens are **198 plain-set columns and 33 `_comment`, with
no operator suffix, no `_clone` and no `_serveOn`** [measured].

**One section per class is not a `targets` question.** A schema is a subsystem
is a section, so eleven pack schemas already give eleven sections; the two or
three CSVs are tables *within* one section, the way `teampl`'s `table` and
`override` are. No new `ui` value is needed for them either: there is no field
per file, so nothing dispatches on one.

**Two checks, both of which exist because silence is the failure here.**

- **A declared overlay that is not on disk is `MISSING`, not a skip.** A pack
  that lists three files and finds two would otherwise read as "that class has
  no rules for this model", which is `AGENTS.md` §3's instrument silence.
- **A `.csv`/`.tsv` in `ckf.hardmode.d/` that no schema's `targets.overlays`
  names is `STALE`.** On 2026-09-13, 33 overlay files carrying 312 rows landed
  in that directory and `check_schema.py`'s output did not move by one
  character, because nothing declared them — the plugin applied them and
  nothing validated them. A file claimed by **two** schemas is `STALE` as well:
  one file, one slice.

Three files are unclaimed **by design** and are named rather than counted:
`ArmorModel.csv`, `WeaponModel.csv` and `MonsterTypeModel.csv` — enemy gear, out
of scope per the proposal's non-goals. `MissionPowerLevelModel.generated.json`
is not in this census at all: it is a schema *output*, written by
`scripts/gen_teampl_labels.py` and checked by `teampl`'s `mirror` invariant.

The `overlays:` census line prints on every run:

```
overlays: 33 declared across 12 schema file(s), 36 csv/tsv on disk, 0 unclaimed, 3 unclaimed by design (ArmorModel.csv, WeaponModel.csv, MonsterTypeModel.csv).
```

### A one-row table needs nothing declared, and here is the re-test

Phase 6 concluded that the `levers` and `slotTable` `ui` kinds have nothing to
key on while the editor writes no sheet. **Re-tested against `implants-slot11.csv`
rather than assumed to carry over**, because a single-row table was the case
thought most likely to break it.

It still needs nothing, and since 2026-09-14 it needs even less: **slot 11 is
drawn as a grid like every other slot**, so there is no second layout for a
schema field to select. `implants-slot11.csv` is 1 row and 15 columns, 492
bytes; nothing about how it renders is declared anywhere, and the same
reasoning that kept `row[]` out of `targets.overlays` still applies — the header
is the authority, and so is the row count.

**Correction, 2026-09-14.** The two paragraphs above read "`design.md` §7 says
slot 11 renders as a **form, not a grid**, and that is a different control from
every other slot", and then "**The discriminator is the row count, and the row
count is in the file** — ... A schema field saying \"this one is a form\" would
restate what the file says". `gui\serve.py` did publish `form: true` for an
expanded sheet of exactly one row and `gui\app.html` drew it as a stack of
labelled values. **David opened the config editor in a browser on 2026-09-14,
looked at the page that produced, and overruled it**; the `form` key is gone
from the server entirely and slot 11 draws as a table like the other ten
(`design.md` §7). The conclusion of the re-test — that nothing needs declaring —
survives the reversal and is if anything stronger; only its example changed.

**What is NOT derivable, and is therefore written down**, is why slot 11's column
set is chosen differently from the other ten. At one row every column is
trivially constant, so "omit any column constant across the table's own rows"
would empty the table entirely; only the all-zero test is applied there. That
sentence is in `Implants.SlotHelp` and transcribed into
`implantsslot11.schema.json`, because a reader cannot derive an exception from
the file that the exception produced. **That exemption is a different rule from
the form and survives it**: it rests on constancy being vacuous at one row, not
on any layout.

**The transcription is kept by hand, and nothing checks it.** The slot schemas'
own `doc` arrays say "scripts/implants.py's P-HELP fails if the two diverge".
That is false: `probe_help` reads only `mods/CKFHardMode/Implants.cs` — every
slot has an entry, slot 8's carries "EVERY IMPLANT EFFECT IN THE GAME", slots 3
and 7 say "file order" — and `implants.py` opens no schema file anywhere
[measured 2026-09-14]. `implantsslot11.schema.json` now says so; the other ten
still carry the false sentence.

### The per-slot help has one source and this is not it

`Implants.SlotHelp` (`mods/CKFHardMode/Implants.cs`) carries the eleven strings;
the `doc` arrays of `implantsslot01` … `implantsslot11` carry a **verbatim
transcription**, and `scripts/implants.py`'s `P-HELP` fails if the two diverge —
specifically if slot 8 loses the sentence that `CritMultiBase` is zero on every
implant effect in the game after those nine rules run, or if slots 3 or 7 lose
"file order". A paraphrase breaks a gate. Transcribe; do not re-derive.

### The divergent-edit refusal is not a `check_schema.py` invariant

`specs/mod-slices/spec.md` requires that two owners of one shared row given
different values for the same column are refused, both owners named, the save
blocked. Its scenario says `check_schema.py` reports it as `INVARIANT`.
**It does not, it should not yet, and the reason is worth stating before someone
builds it.**

**`inv_value` cannot resolve either operand.** Its two spellings are
`Section.Key`, resolved against `load_cfg`'s dict, and `<file>#<dotted path>`,
resolved with `load_jsonc` and `dig`. A shared row's payload lives in a **CSV
cell**, addressed by file, row key and column. `load_jsonc` on a CSV raises an
uncaught `JSONDecodeError` — measured when `targets.overlays` was designed — and
there is no third spelling. An `INVARIANT` here would need a new key-resolution
mechanism, and inventing one to serve a check with nothing to check is the wrong
order.

**There is also nothing to check.** The divergence is an edit to the *payload* of
a shared effect row. `scripts/cyberweapons.py` declares the one shared row —
`EffectModel 2051`, owned by Lumen Spear 4 (weapon 25007, talent 80030) and
Luem Trident (25016, 80060) — and **neither sheet carries an `EffectModel`
column**: the lasers' 18 named columns and the claws' 12 do not include one
[measured 2026-09-13, the live files]. The `SelfEffect` and `TargetEffect` cells
are **pointers**: writing one repoints that talent at a different effect row and
does not change what 2051 does, so the two owners repoint independently with no
interaction.

**Where it lives instead, and why that is the right layer.**
`cyberweapons.py`'s `check_divergent_shared_edits` (`P-DIVERGE`) runs over the
**generated rules**, where a payload write appears as
`(model, id, column) → value` — the only representation in which the comparison
is expressible at all. It names both owners as the scenario requires, it is
fault-exercised by injection in `--selftest`, and it prints its subject count so
that "no divergence" and "nothing to look at" stay different statements. Its own
report says `0` is the expected answer this phase.

**The condition that would change this is nameable and close.** A lever sheet
carrying an `EffectModel` or `MatrixEffectModel` **payload** column gives the
check a live subject. `design.md` §7 puts the effect payload in the implant slot
tables and §11 names `EffectId 50126` as shared between CombatLink 4 and M-Grade
CombatLink — **Phase 7**. Even then the comparison wants the expanded rules, not
the cells, so the answer is to keep it in the expander layer and not to move it
here. `SHARED_ROW_SPLIT_OPTIN` is declared and empty, nothing emits from it, and
the only code reading it asserts it is empty; that is the shape "declared and
unexercised" should have.

### `"in": "reference"` — data the schema carries itself

A field whose values are **in the schema**, under `rows`, rather than in a
config file. `check_schema.py` skips the disk lookup for it and range-checks
`rows` against the field's own `row[]` column declarations, which is the only
thing about it that is checkable — there is nothing on disk to compare it to,
and that is the point.

One field uses it: `rulemodel.ruleReference`, 76 rows of `RuleId`, `GroupId`,
`ConfigName` and `Shipped`. `design.md` §9 requires the editor to group the
control by `GroupId` and to show the shipped value beside the override field,
and **none of that is in any shippable file**: the overlay carries `RuleId`,
`Value` and `_comment` and nothing else. `GroupId` could not be added to that
header, because it is a real game column and a header naming it is a `set` over
all 76 rows — metadata that behaves like a tuning change. Nor is it parsed back
out of `_comment`: that column is prose for a human reading the CSV in a
spreadsheet, and making a free-text field load-bearing is the defect
`proposal.md` §1 exists to remove.

**It is a snapshot of a dump and says so.** Derived from `sheets/raw/RuleModel.csv`
on 2026-09-13. A dump is not shippable and no runtime behaviour may depend on
one being present, which is why the snapshot is here rather than read at load.
**Nothing will notice when it goes stale** — a game update that renumbers or
regroups these rows makes it wrong silently — so it is anchored on the two rows
the mod overrides: id 22 `Surprised Bonus` ships 25, id 23
`Glancing Distance Limit` ships 5, and the overlay sets 15 and 4. If those
disagree with a fresh dump, re-derive the block.

### Slices

A **slice** is one toggleable unit of tuning. It is a schema file that declares
`targets.cfg`, and its toggle is that file's single `"in": "cfg"` field. A slice
is the toggle, not the file: a talent-balance class pack is two or three CSVs
behind one key, because its rows are rows of two or three different game tables
and the overlay dialect keys the target table off the filename.

Forty-two slices are declared, plus `general.schema.json`, which declares
`targets.cfg` and `General.Enabled` and is the master switch rather than a slice
— it satisfies the same one-file-one-key rule, which is why the generator does
not need to special-case it.

| Group | Count | Keys |
|---|---|---|
| the nine existing subsystems | 9 | `Slices.Difficulty`, `Slices.Elapse`, `Slices.Fatigue`, `Slices.MissionRewards`, `Slices.ModelRules`, `Slices.PowerLevel`, `Slices.Progression`, `Slices.RewardCurve`, `Slices.SelfCheck` |
| weapon sheets | 3 | `Slices.GearClasses`, `Slices.CyberweaponsLasers`, `Slices.CyberweaponsClaws` |
| implants | 12 | `Slices.ImplantsGlobal`, `Slices.ImplantsSlot01` … `Slices.ImplantsSlot11` |
| consumables | 6 | `Slices.ConsumablesMedical`, `…Grenades`, `…Devices`, `…Chems`, `…Matrix`, `…Sploitkits` |
| game constants | 1 | `Slices.RuleModel` |
| talent-balance class packs | 11 | `Slices.TalentsSoldier`, `…WarMachine`, `…Sniper`, `…Sawbones`, `…Vanguard`, `…Hacker`, `…Gunslinger`, `…AEX`, `…CyberKnight`, `…CS`, `…Wraith` |

The key is `Slices.<subsystem>`, the schema's own `subsystem` value — which is
why two of the nine are not spelled like their document section: `teampl`'s
subsystem is `Progression` and `missions`' is `MissionRewards`.

`gen_binds.py` compares the slice set and the key set **in both directions** and
exits non-zero on any of four disagreements: a slice with no key, a key with no
slice, two keys in one slice, and an `enable.cfg` naming a key no schema
declares as a field — the last because `check_schema.py` counts such a key as
declared (`check_schema.py:235-237`) and then never looks for it on disk, so
nothing else would report it. All four stop a plain run as well as `--check`,
so a disagreement cannot produce a quietly smaller table.

**The eight `"path": "enabled"` json fields are gone.** Deleting them took the
declared `"in": "json"` field count from **47 to 39** and the total field count
from 90 to 82. [measured 2026-09-13, `schema/*.schema.json`] The key itself is
still **parsed** out of the document into a report-only `bool? RetiredEnabled`
carrying `[JsonPropertyName("enabled")]`, because four subsystems refuse a whole
section on an unknown key (`../mods/CKFHardMode/ConfigDoc.cs:255-265`) and an
upgraded document would otherwise switch **off**. `Slices.ReportRetiredGate`
(`Slices.cs:314-334`) names it — Warning normally, Error when the retired value
is `false` and the `[Slices]` key is not. Nothing branches on it: `RetiredEnabled`
has one declaration and one report call per subsystem and no read. It is a
migration report, not a second gate.

**Nothing points at the retired keys any more.** Both places that did have been
repointed, on 2026-09-13, after the eight fields were deleted:

1. All eight schemas carried `"enable": { "json": "enabled" }`, which named a
   key nothing reads. Each now carries `{ "cfg": "Slices.<subsystem>" }`, and
   `difficulty.schema.json` — which had no `enable` block at all while its gate
   was live in `Plugin.Load` — was given `{ "cfg": "Slices.Difficulty" }` on the
   same grounds, so all **nine** subsystems declare their chain. The
   `cfg` spelling in `enable` is not new — `general.schema.json` has always used
   it and `check_schema.py:235-237` reads it — so this is the existing form, now
   used nine times instead of once.
2. `teampl.schema.json`'s `linkedEnable` named
   `ckf.hardmode.json#teampl.enabled` and `ckf.hardmode.json#modelrules.enabled`.
   It now names `Slices.Progression` and `Slices.ModelRules`.

**Correction, 2026-09-13.** The paragraph these replace said both were "named
rather than fixed because `enable` is read by `gui/serve.py`, which another
agent owns". The second one could not wait, and the reason is in its own
mechanism: `inv_value` resolves a `file#path` key against the **live document**
(`check_schema.py:128-137`), and the retired `"enabled"` keys are still in that
document on purpose, so the old spelling went on enforcing a pairing between two
keys nothing reads. A half-on pair is reported `INVARIANT`, and `serve.py`'s
`BLOCKING` refuses a save on `INVARIANT` — a live save-blocker sitting on dead
data.

**Both spellings are one function, and the `cfg` side is exercised.**
`inv_value` takes `Section.Key` against `load_cfg`'s dict
(`check_schema.py:138-140`) and `file#path` against a document (128-137);
`inv_bool` (143-147) exists to coerce the raw string a cfg key arrives as, and
says so. A `linkedEnable` naming two cfg keys was measured against
`check_schema.py` on a three-schema fixture: half-on reported
`INVARIANT ... linked group half on` and exited 1; both-on and both-off reported
0 problems and exited 0. No invariant machinery was added — `requires` remains
Phase 2's, per `design.md` §4. [measured 2026-09-13]

**One coverage loss, stated rather than hidden.** Under `--no-cfg` the cfg dict
is empty (`check_schema.py:199`), so `inv_value` returns not-found, `states`
stays empty and line 313's `if states and ...` skips the group **in silence**.
The `file#path` spelling was checked under `--no-cfg`, because the document is
read either way. Gate 02 (`--config defaults --no-cfg`) is a recorded non-run
today and Phase 9 defines its successor; whatever that becomes has to read the
`.cfg` or this group is unchecked there. [measured 2026-09-13, same fixture]

**A slice may claim a generated file.** `Slices.Progression` claims
`ckf.hardmode.d/MissionPowerLevelModel.generated.json`, the victory-screen label
mirror `scripts/gen_teampl_labels.py` writes from `teampl.override` merged over
`teampl.table`. It reaches the game through the overlay path rather than through
Progression (`Overlays.cs:38-45` makes a `.json` there an ordinary rules file),
so without the claim `[Slices] Progression = false` reverts the award to stock
and leaves the mirror rewriting the label — a stock award with a lying label,
which is the state `teampl.schema.json`'s own `linkedEnable` `reason` records as
logging nothing. **Correction, 2026-09-13:** the change's `design.md` §2 lists
that file in the "enemy gear, unchanged" block at lines 78-81. It is neither. §1
and §12 are the passages to follow.

**Correction, 2026-09-13: `targets.section` is gone, and `targets.json` names a
file in `ckf.hardmode.d/`.** The row above used to read "`json` is
`ckf.hardmode.json` for every subsystem that has settings; `section` is its
top-level key in it". Phase 3 split that document into ten files and **each one
holds its subsystem's fields at the top level** — `powerlevel.json` is
`{ "_version", "enabled", "minCap", "maxCap", "matrixMaxCap", "logFirst" }`,
with no `powerlevel` wrapper. [measured 2026-09-13, the files on disk] So the
nine schemas keep `json` and **drop `section`**; a `section` left behind would
report `MISSING … has no "<section>" section` against a file that has no wrapper
to find.

The filenames were taken from a listing of
`<game>\BepInEx\config\ckf.hardmode.d`, not derived from the subsystem name,
because two do not match: `MissionRewards` → `missions.json` and `Progression`
→ `teampl.json`.

Measured against a copy of the live config directory with the merged document
absent: **9 problems, rc 1** with the old `targets` (one
`MISSING <Subsystem>: sidecar ckf.hardmode.json not on disk` per schema) and
**0 problems, rc 0** with the new. [measured 2026-09-13]

**One guard goes quiet, and it is not a regression to fix here.** The stray
top-level-key check only runs for a file some schema `claimed`, and `claimed` is
populated only when a schema declares a `section`. With no sections left it
checks nothing. That guard existed because a *shared* document could carry a
misspelled section name that belonged to no POCO; one file per subsystem
restores the guard the split originally gave for free — a stray top-level key
lands in the C# POCO's `[JsonExtensionData]` bag and
`ConfigDoc.ReadSection`'s `UnknownKeys` branch refuses the file by name. The
check is not lost, it moved back into the plugin. Stated here because a guard
that stops running without saying so is the failure `AGENTS.md` §3 names.

**The `mirror` invariant had to move with the file, and it was already dead.**
`teampl.schema.json`'s `mirror` named `ckf.hardmode.json#teampl.override[]` and
`#teampl.table[]`; both now name `ckf.hardmode.d/teampl.json#override[]` and
`#table[]`. `check_schema.py`'s `mirror` branch resolves `source` with
`os.path.exists` and **`continue`s when it is absent** — so with the merged
document gone the whole comparison was skipped in silence. Falsified rather than
argued: a label cell perturbed from `0.25` to `0.5` in
`MissionPowerLevelModel.generated.json` produced **zero** `INVARIANT` lines
under the old spelling and
`INVARIANT mirror: ['ActionClass', 'MissionPowerLevel']=(1, 1) award 0.25 vs
label 0.5` under the new. [measured 2026-09-13]

**`gen_teampl_labels.py` still reads the merged document and will fail when it
is deleted.** It joins `ckf.hardmode.json` onto the config directory in `main`
and falls back only to the 2.x `ckf.hardmode.teampl.json`, so against the split
directory it exits 1 with `not found: …\ckf.hardmode.json (nor the legacy
…\ckf.hardmode.teampl.json)`. [measured 2026-09-13] That is gate 05 and a
`scripts/` fix, not a `schema/` one; the mirror above is repointed so
`check_schema.py` covers the same disagreement in the meantime.

**`ckf.hardmode.cfg`'s line endings have changed twice, and `schema/` does not
depend on them.** Three observations, in order, with nothing between them:

| date | state |
|---|---|
| 2026-09-03 | written CRLF by hand, by `consolidate-config-and-ship` |
| 2026-09-13, morning | 162 bytes, 8 LF, 0 CRLF |
| 2026-09-13, after the launch that wrote the 43 keys | 3,238 bytes, 179 CRLF, 0 bare LF |

[measured, all three] **What changed it between the first and the second is not
established, and no mechanism is offered here.** A guess in this document
becomes the next agent's fact; if the cause is ever found, it goes in
`../docs/gotchas.md` with its evidence.

`load_cfg` (`check_schema.py`) is the only thing in `schema/` that reads that
file, and it is agnostic twice over: it opens in text mode with the default
`newline=None`, so Python's universal-newline translation turns `\r\n`, `\r`
and `\n` all into `\n` before the loop sees them, and it then calls
`line.rstrip('\r\n')` on every line anyway. Fed the same six keys as CRLF, as
LF and as bare CR, it returns three identical dictionaries. [measured
2026-09-13, fixture] Nothing in `schema/` writes the `.cfg`.

**Anything in this repository that does not read that file through `load_cfg`
has to establish the endings for itself rather than inheriting an assumption
from here.** The `.cfg` has been both.

**Every schema declares its own gate, all 43 of them.** A slice schema carries
`"enable": { "cfg": "Slices.<subsystem>" }` naming its own `"in": "cfg"` field.
This is not decoration: `enable` is the only thing `enable_index`
(`../gui/serve.py`) builds a chain from, and a schema without one gets an empty
`gates` list, `effective: "n/a"`, and **no toggle in the nav** — a declared key
with no switch. The 33 slice schemas were in that state until 2026-09-13.

**A cfg gate does not imply a document section, and nothing downstream assumes
it does.** The ten subsystem schemas gate a section; the 33 slice schemas gate
files and have no `targets.json` at all. Every consumer branches on the
spelling before any section lookup, checked one by one:

| where | what it does with a cfg gate |
|---|---|
| `enable_index` (`serve.py`) | the `cfg` branch reads `model['cfg']` only; `sidecar_unit(sch)` is computed but used solely by the `json` branch and the `enabledBy` block loop, both skipped when it is `None` |
| `sidecar_unit` (`serve.py`) | returns `None` when `targets.json` is absent, which is what makes those two skips fire |
| `check_schema.py` | reads `enable.cfg` into `declared_cfg` in a step of its own, outside the `if sidecar:` block, and never checks it for presence |
| `gateFieldOf` (`../gui/app.html`) | resolves `en.cfg` to the schema's own `"in": "cfg"` field by path |
| `fieldValue` (`app.html`) | returns `W.cfg[f.path]` for a cfg field **before** calling `sidecarOf`, which would be `null` |
| `setBool` / `linkedSlot` (`app.html`) | resolve the cfg spelling first |
| the gate-exercising selftest (`serve.py`) | sets `unit = None` on the cfg branch and guards the section read with `if unit:` |

[measured 2026-09-13] So the 33 join the nine that already existed rather than
creating a new case. Their keys are absent from `ckf.hardmode.cfg` until the
game is launched, which makes them `state: None`, `detail: "key absent from the
cfg"`, `effective: "unknown"` — **never `off`**, which is the distinction
`AGENTS.md` §3 exists for and which the index already draws.

**A citation into a file under active edit names a member, not a line.**
`Slices.Init`, `Slices.ReportRetiredGate`, `ConfigDoc.ReadSection`,
`Plugin.Load` — file name plus member, no line range. This is a departure from
the rest of this document and from the older schemas' `doc` strings, which cite
`Elapse.cs:833-835` and the like, and it applies to **citations added from
2026-09-13 into `mods/CKFHardMode/*.cs`**; the existing line citations are left
alone rather than rewritten wholesale.

The reason is measured, not stylistic. Phase 1 put four citations into two C#
files that the same phase was still editing. **Three of the four were stale
within hours**: `Slices.cs:191-211` (the bind loop) became `:204-240`,
`Slices.cs:211` (the one `Binds.Bind`) became `:224`, and `ConfigDoc.cs:255-265`
(the unknown-key refusal) became `:271-280`. Only `Plugin.cs:186` survived.
[measured 2026-09-13, against the files on disk] A stale line number does not
fail — it points at whatever now occupies the line, which is the silent-wrong
answer this repository keeps paying for. A member name survives every edit that
does not rename it, and a rename makes the citation return nothing under `grep`,
which is a loud failure.

Phases 4-8 add per-slice expanders to `ModelRules` and will cite them from these
same `doc` strings. **Nothing keeps a number in sync and nothing should be built
to** — the fix is to stop writing the number.

Quoted history is exempt. A correction that quotes what a doc used to say
reproduces it verbatim, line number included, because the quotation is evidence
of what was claimed.

**Three of the nine subsystems' toggles are new behaviour, not a move.**
`Slices.Difficulty` is a gate that did not exist: `difficulty.schema.json`
declared no `enable` block and the `difficulty` section carries no `enabled`
field. It defaults `true`, so nothing changes. `Slices.SelfCheck` defaults
`false`, matching the `selfcheck` section's own `enabled`, the one default among
the nine that is not `true`. Every new slice defaults `true`, which is what the
rules in `ckf.hardmode.rules.json` do today. [measured 2026-09-13]

**Removed, 2026-08-31: `docTarget`.** Its three values (`comments`, `readme`,
`none`) chose where a subsystem's `doc` lines were written back. There is now
one destination for all of them, `../docs/config-reference.md`, so the key selects
nothing. The ten schema files were cleaned first and this document was not, so
the format went on showing the key marked "Obsolete — being removed", a state no
file was actually in. It is gone from both. A schema that still carries it is
stale, not valid: nothing reads it, and `check_schema.py` never did.

**`doc` and `uiDoc` have different readers and both are kept.** `doc` is the
maintainer record: the `.cs` citations, run numbers, evidence tags and
corrections that `AGENTS.md` §5 requires to stay visible, and
`../docs/config-reference.md`'s source. `uiDoc` is the same subsystem written for
someone playing the game, and by construction carries no citation, run number,
evidence tag, cross-reference to a planning document, or account of what a
previous version got wrong. **Every claim in a `uiDoc` must already be
established** in that subsystem's own `doc`, a field `doc`, or an invariant
`reason` — it is a rewrite for a different reader, not a place to add facts. A
claim tagged `[unverified]` is restated as the plain uncertainty it is or left
out; it is never promoted to unqualified fact. `gen_docs.py` renders both, `doc`
first, so the maintainer document shows what the player is being told.

**A field may carry a `uiDoc` too**, one level down: a single string, the
player-facing version of that field's `doc`, under the same content rule. Use
one wherever the `doc` explains **how the mod does it** rather than **what the
control does** — a C# mechanism, a correction, a long `[unverified]` note.

Where a field has no `uiDoc`, the GUI shows its `doc` with the maintainer marks
stripped at render time; `../docs/config-reference.md` renders it unstripped either
way. The strip is the safety net for `doc`. A `uiDoc` should have nothing in it
to strip, and `--selftest` asserts that none does.

---

## Fields

```json
{
  "path":       "stress.cap",
  "in":         "json",
  "type":       "int",
  "default":    10,
  "range":      [1, 10],
  "label":      "Stress cap",
  "doc":        "Maximum Stress a single merc can be taken to by an expiry.",
  "uiDoc":      "Do not take a merc above this Stress value. Set it outside 1-10 and the mod refuses the whole config.",
  "enabledBy":  "stress.enabled",
  "ui":         "form"
}
```

**Correction, 2026-08-31.** This block used to show `stress.cap` with
`"range": [0, 100]`; the real range is `[1, 10]`. The example uses a live field
path, so a stale value here reads as the field's real declaration — which is how
it survived. `Elapse.cs` rejects a cap outside 1-10, which is the authority.

`path` — for `"in": "cfg"`, `Section.Key`. For `"in": "json"`, a dotted path
from the SECTION root, not from the file root. Both are the literal address the
generator writes to; nothing derives one from the other. Phase 3 moved 21 fields
from the first form to the second: `[PowerLevel] MaxCap` became `maxCap` in the
`powerlevel` section, and the change is a rewrite of `path` and `in` rather than
anything structural.

### `type`

| Type | Notes |
|---|---|
| `bool` | |
| `int`, `float` | `range` is `[min, max]` inclusive |
| `floatOrNaN` | `NaN` means "leave the game's own value alone". No field carries it today; the last ones were the 20 `[Difficulty]` scalar knobs removed in 2.11.0. |
| `string` | |
| `stringList` | Comma-separated in cfg, a JSON array in the document. The one-line rule was a cfg rule — a list split across lines silently kept only the first entry — and `modelrules.probeTables`, the only `stringList` there was, is a JSON array since 3.0, so nothing carries the comma-separated spelling today. |
| `enum` | With `"values": [...]` |
| `table` | A JSON array of objects. Needs `row`. |

### When a numeric field gets a `range`, and when it does not

Recorded 2026-09-13, from a sweep of all 43 schemas rather than from a rule
anyone had written down. **41 numeric declarations: 27 carry a `range`, 14 do
not** [measured 2026-09-13, `fields[]` plus `fields[].row[]` of type `int`,
`float` or `floatOrNaN` across `schema/*.schema.json`]. So "every numeric field
carries a range" is not true of this repository, and the 14 are not an oversight
— they are the fields with nothing to derive a bound from.

`check_schema.check_range` returns on its first line when a field's `range` is
null or absent, so **an unranged numeric field is not checked at all**, at any
magnitude. `RANGE` is in `serve.py`'s `BLOCKING`, so a declared range also
refuses a save. A range is therefore a statement about how far a player may
push a number, and it is enforced.

The 27 fall into three kinds, and the kind is what decides the bounds:

| Kind | The range is | Examples |
|---|---|---|
| Enforced | the bound the code itself rejects outside of, with the member named in the field's `doc` | `elapse.stress.cap` `[1, 10]` — "the plugin rejects the whole config if this is outside 1-10 (`Elapse.cs`), so the range here is the plugin's, not a guard rail" |
| Domain | the domain of the quantity or of the game-table column it indexes | percent `[0, 100]`, fraction `[0.0, 1.0]`, `PowerLevel` `[0, 25]` / `[1, 20]`, `teampl.override[].ActionClass` `[0, 3]` — "what the save files rows under" |
| Guard rail | a round number that contains every shipped value with room, floor at the value that switches the effect off | `elapse.tiers[].multiplier` `[0.0, 10.0]`, `teampl.override[].PowerLevelFraction` `[-5.0, 5.0]` — whose `doc` says outright "THE RANGES BELOW ARE GUARD RAILS FOR THE EDITOR, NOT ENGINE LIMITS" |

The 14 unranged are ids (`fatigue.*.traitId`), durations
(`*.durationDays`), affected-merc counts, the three `rewardcurve.curve[]`
money/XP columns, and the `teampl.table[]` reference columns — quantities with
no authority, no unit domain and no shipped band to round off.

**There is no arithmetic relation between a range and the field's default, and
looking for one is a dead end.** Defaults sit at the floor
(`elapse.logFirst`, `modelrules.traceRules`, `credits.percentOfBalance`), at
the ceiling (`elapse.stress.cap`), and in the interior
(`difficulty.sliderRangeMultiplier`, `elapse.seedSalt`,
`fatigue.woundResist.minChancePercent`); ceiling-over-largest-shipped-value
runs from about 6.7× to about 33×.

**Multipliers.** Two are declared and they do not share bounds, because they
do not do the same thing. `elapse.tiers[].multiplier` `[0.0, 10.0]` is a plain
value-scaler: 0 zeroes the number, 1 leaves it alone. `difficulty.sliderRangeMultiplier`
`[1.0, 100.0]` widens a Min/Max pair rather than scaling a value, and its own
`doc` says "1 = leave the stock ranges alone", so below 1 is not what the field
is for. **A new plain value-scaler takes the first one's `[0.0, 10.0]`** — that
is what `implantsglobal`'s `costMultiply`, `installTimeMultiply` and
`implantStressMultiply` carry, and the derivation rests on that one prior
declaration, which is worth knowing before treating it as settled.

**Clamp bounds.** Four are declared — `powerlevel.minCap`, `maxCap`,
`matrixMaxCap`, `elapse.stress.cap` — and all four take the domain of the
column they clamp, with an authority for that domain. A clamp on a column whose
legal domain nothing in this repository states cannot meet the convention, and
gets no range rather than a guessed one: `implantsglobal.implantStressClampMin`
is the one such field today, and its `doc` says so and names the open question.

### `ui`

This is the canonical copy of this table; `../docs/config-reference.md` and
`../gui/README.md` link here rather than restating it.

| Value | Renders as |
|---|---|
| `form` | A labelled control, type-appropriate |
| `table` | An editable grid (`row` gives the columns) |
| `curve` | A table plus an editable line chart, x = first `row` column |
| `matrix` | A 2-D grid; needs `axes` |
| `readonly` | Shown, not editable — reference data the mod checks itself against |
| `hidden` | In the schema so the stale-key diff stays complete, never rendered. Reserved for reflection plumbing — type, method and property names, row filters — where a typo breaks the mod and no validation can catch it. |

### `table` fields

```json
{
  "path": "credits.byPowerLevel", "in": "json", "type": "table", "ui": "table",
  "row": [
    { "name": "minPowerLevel", "type": "int", "range": [0, 25] },
    { "name": "amount",        "type": "int", "range": [0, 100000] }
  ],
  "sortBy": "minPowerLevel"
}
```

A `matrix` field adds `axes`, naming the two key columns and the value column:

```json
"axes": { "row": "ActionClass", "col": "MissionPowerLevel", "value": "PowerLevelFraction" }
```

#### Row-column keys

A `row` entry takes `name`, `type` and `range`, and one key beyond them:

| Key | Meaning |
|---|---|
| `"format": "adjust"` | This string column carries the adjustment grammar `MissionRewards.Adjust.Parse` reads (approx. `MissionRewards.cs:392-415`): `""` leave alone, `=N` set, `+N` add, `-N` add a negative, `xN` / `XN` / `*N` multiply, a bare number set. The GUI validates the cell against it on save and describes it on hover. A column the schema does not mark falls back to the GUI's inference from the values on disk. |

Only the five slot columns of `missionrewards.missions` carry it —
`BonusPayment`, `BonusExperience`, `PowerLevelBonus`, `ObjectivePayment`,
`SecondaryPayment` — exactly the five `LoadOverrides` hands to `Adjust.Parse`.
`type` and `note` are not among them. **The declaration replaces value
inference:** before this key existed the GUI worked the set out from the values
in the file, a guess a differently-populated file can change under you.

#### `keyedBy`, and its one correction

`keyedBy` names the column that becomes the JSON object key when the table is
serialised as an object rather than an array. A field without `keyedBy` is an
array.

Five fields declare it. Four are in `fatigue.schema.json`, all
`"keyedBy": "powerLevel"` — `runningEmpty.byPowerLevel`,
`runningEmpty.knight.byPowerLevel`, `offDuty.byPowerLevel` and
`offDuty.knight.byPowerLevel` — plus `elapse.tiers`, keyed by `name`. Those five
are objects on disk. `elapse.credits.byPowerLevel`,
`elapse.stress.byPowerLevel`, `rewardcurve.curve`, `teampl.table` and
`teampl.override` carry no `keyedBy` and are arrays.
[measured: `grep keyedBy schema/*.schema.json`]

**Correction, 2026-08-31.** `missionrewards.schema.json` declared
`"keyedBy": "type"` on its `missions` field. That was wrong. The block on disk
is a JSON array of 70 row objects, and `MissionRewards` declares
`[JsonPropertyName("missions")] public List<MissionOverride> Missions` (approx.
`MissionRewards.cs:297-298`) — an object there would fail the plugin's read
outright. The `keyedBy` was removed and the array stands; the file carries no
`keyedBy` at all today. How the wrong value came to be written is not recorded
anywhere in this repository and is not guessed at here. [measured]

### `enabledBy`

A `bool` that gates this field; the GUI greys the field when it is false. This
is the third level of the enable chain — `elapse.json` has two (`credits`,
`stress`) and `fatigue.json` one (`woundResist`). For `"in": "json"` the value
is a path relative to the same sidecar; for `"in": "cfg"` it is a full
`Section.Key` — `ProbeTables` and `ProbeOutput` are meaningless unless
`ModelRules.ProbeWritableColumns` is on, and `SelfCheck.File` /
`SelfCheck.Output` unless `SelfCheck.Enabled` is. Only the GUI reads this;
`check_schema.py` ignores it.

### Optional flags

| Flag | Meaning |
|---|---|
| `"absent": "..."` | What an omitted value **means**, when that differs from `default`. e.g. `rewardcurve.curve` treats `-1`, any negative value, or a missing column as "keep the game's number" — `RewardCurve`'s absent/`-1` convention, whose own initialiser is `-1` (approx. `RewardCurve.cs:249-251`). |
| `"optional": true` | Omission from the file **is legal**. `check_schema.py` skips its `MISSING` check for this field; every other check still applies when it is present. |
| `"retroactive": true` | Editing this re-prices existing save data. Two fields carry it, both in `teampl.schema.json`: `Progression.Enabled` and `override`. It is **data, not a warning** — the GUI passes it to the page but builds nothing out of it: no pill, no red block, no confirm gate. The retroactive effect is stated as a plain fact in the field's own `doc` and `uiDoc` instead. See `../gui/README.md`. |
| `"oneLine": true` | Implied by `stringList` in cfg; stated for clarity. |

**`optional` and `absent` are different keys and neither implies the other.**
`absent` documents what an omitted value means; `optional` says the omission is
allowed at all. A field may carry both, either, or neither. Overloading `absent`
to mean "may be omitted" was considered and rejected: eleven fields carry
`absent` and all eleven sit on disk today, and folding the two together would
have silenced `MISSING` for all of them. (It said "twelve" until 2026-09-07;
`fatigue.runningEmpty.maxAffected` was one of the eight flat fatigue settings
removed that day, and it carried `absent`.) [measured 2026-09-07,
`schema/*.schema.json` against `live-config/ckf.hardmode.json`]

That was falsified rather than argued — five cases, each run against a scratch
copy of `live-config/` (and, for the fifth, of `schema/` too), with
`live-config/ckf.hardmode.json` confirmed byte-identical by `md5sum -c`
afterwards:

| Case | The field carries | Result |
|---|---|---|
| Delete `fatigue.runningEmpty.traitId` from the document | neither flag | 1 `MISSING`, exit 1 |
| Delete `powerlevel.matrixMaxCap` from the document | `absent`, **no** `optional` | 1 `MISSING`, exit 1 |
| Delete the whole `fatigue.runningEmpty.byPowerLevel` block | `absent`, **no** `optional` | 1 `MISSING`, exit 1 |
| Set `fatigue.runningEmpty.knight.byPowerLevel`'s first anchor to `chancePercent: 500` | `optional` + `absent` | 1 `RANGE`, exit 1 — no `MISSING` was suppressed that should have fired, and the field's other checks still ran |
| Delete all three `optional` curves from the document, then strip `"optional": true` from `fatigue.schema.json` | — | **0 problems, exit 0** with the flags in place; the 3 `MISSING` lines and exit 1 once they are stripped |

Rows two and three are the point of not overloading `absent`: a field that
documents what its omission means is still required to be on disk. The fourth
shows `optional` narrows nothing but `MISSING`. The fifth shows the flag, not
the file, is what silences those three — a document with all three curves
deleted is clean while the flags are there and reports all three the moment they
are gone. [measured 2026-09-07]

**Correction, 2026-09-07.** The first two rows used to read "Delete
`runningEmpty.chancePercent` from the sidecar" and "Delete
`runningEmpty.maxAffected` from the sidecar". **Both of those fields were
removed from the config surface today**, along with the other six flat fatigue
settings that had a `byPowerLevel` analogue, so the experiment as written can no
longer be run: there is nothing to delete. They are replaced above by
`fatigue.runningEmpty.traitId`, which carries neither flag, and
`powerlevel.matrixMaxCap`, which carries `absent` and no `optional` — the two
shapes the original rows were chosen to demonstrate. The substitution is not
like-for-like in one respect worth stating: with the flat fields gone,
`runningEmpty.byPowerLevel` is the **only** field left in
`fatigue.schema.json` carrying `absent` without `optional`, which is why the
second row now has to leave the `fatigue` section to find its case. The fifth
row changed for a different reason, given under `optional: true` below.

Three fields carry `optional: true`, all in `fatigue.schema.json`:
`offDuty.byPowerLevel`, `offDuty.knight.byPowerLevel` and
`runningEmpty.knight.byPowerLevel`. `Fatigue.cs` reads all three; each is a
plain `Dictionary<string, LevelPoint>` with no initialiser, which
`System.Text.Json` leaves null when the key is absent, and `Curve()` returns
null for a null or empty dictionary (`Fatigue.cs:1915`). What the resolver does
with that null depends on which curve is missing: an absent
`runningEmpty.knight.byPowerLevel` sends the Cyber Knight to the general
`runningEmpty.byPowerLevel` curve, and an `offDuty.byPowerLevel` absent
alongside `offDuty.knight.byPowerLevel` leaves `OffDutyDaysFor` with no duration
at all, so nobody is escalated, the merc keeps the first stage and the missing
key is logged once (`Fatigue.cs:2012-2070`). All three are in the shipped
`ckf.hardmode.json`, at twenty anchors each. [measured 2026-09-07,
`mods/CKFHardMode/defaults/ckf.hardmode.json` and `live-config/ckf.hardmode.json`;
re-measured 2026-09-11 in the live `BepInEx\config\ckf.hardmode.json`, which is
now the only copy — the `defaults/` one was deleted that day]

**Correction, 2026-09-07.** That paragraph used to end: "`Curve()` returns null
for a null or empty dictionary, so the resolver falls through to the flat value.
None of the three is in the shipped `ckf.hardmode.fatigue.json`." The `Curve()`
half of the first sentence is still right; everything after it was wrong, in two
separate ways.

- **There is no flat value to fall through to.** The eight flat fatigue settings
  were removed from the config surface today, so the chain is Knight curve, then
  general curve, then "no value" — and "no value" is a stated outcome, logged and
  costing the roll or the write, not a substituted number
  (`Fatigue.cs:1997-2070`). The sentence was a compression even while the flat
  settings existed: the chain then was Knight curve, the Knight's own flat
  setting, the general curve, and only then the general flat value — four steps,
  recorded in `fatigue.schema.json`'s `doc` for
  `runningEmpty.knight.byPowerLevel`. "The flat value" named neither of the two
  it could have meant.
- **All three are in the shipped file, and it is not the file named.**
  `ckf.hardmode.fatigue.json` is the retired 2.x sidecar; what ships is the
  `fatigue` section of `ckf.hardmode.json`, and it carries all twenty anchors of
  each of the three curves. The mistake is the same one corrected in
  `fatigue.schema.json`'s own `doc` strings on this date, and it came from the
  same place: prose written against the sidecar and never re-checked after the
  3.0 merge. It is what makes the falsification table's fifth case need a
  prepared document — against the shipped one, stripping `optional` changes
  nothing.

Do not add `optional` merely because the deserialiser tolerates an absence — on
that test most of `fatigue.json` would qualify and `MISSING` would stop being
worth running. It marks a field whose omission is the documented, shipped
state.

---

## Invariants

Cross-file rules `validate_rules.py` enforces and the GUI applies on save.

### `mirror` — one side is generated from the other

```json
{
  "kind": "mirror",
  "source": "ckf.hardmode.teampl.json#override[]",
  "target": "ckf.hardmode.d/MissionPowerLevelModel.generated.json",
  "match": ["ActionClass", "MissionPowerLevel"],
  "value": "PowerLevelFraction",
  "mergeWith": "ckf.hardmode.teampl.json#table[]",
  "generated": true
}
```

`mergeWith` matters: a cell absent from `override` keeps its `table` value
(`Progression.Merged`), so the comparison is against the merged table, not
`override` alone. `generated: true` means the target is machine-owned: the GUI
rewrites it wholesale and nothing hand-edits it.

### `ordered` — keys that must be non-decreasing

```json
{
  "kind": "ordered",
  "keys": ["ckf.hardmode.d/powerlevel.json#minCap",
           "ckf.hardmode.d/powerlevel.json#maxCap"],
  "reason": "maxCap below minCap leaves nothing to clamp into; PowerLevelCap.Init logs an error and installs no hook."
}
```

Each key must be less than or equal to the one after it. A group with a key that
does not resolve, or that resolves to something that is not a number, is **not
compared and says so** — a named `SKIPPED` line and a `0 compared` on the
`ordered:` census.

**Correction, 2026-09-13.** This paragraph used to end "Skipped **silently** if
any key is absent or non-numeric — the `MISSING` and `RANGE` checks own those."
Both halves were wrong. It is no longer silent, and `MISSING`/`RANGE` do not own
those cases: they are per-*field* checks, and an invariant may name a key that no
field declares, so neither would necessarily have said anything. The example
block above also carried the pre-Phase-3 spelling.

**How an invariant names a key.** Two spellings, both accepted by
`check_schema.py`'s `inv_value`: `Section.Key` is a cfg key, and
`<file>#<dotted path>` is a path inside a config document — the notation
`mirror` has always used for its `source` and `target`. The `<file>` half is a
path relative to the config directory, so a slice file is
`ckf.hardmode.d/<slice>.json`, and `inv_value` reads it **off disk by that
name**: a key naming a file that is no longer there does not fall back to
anything, and a key naming a file that still exists but is no longer the live
one is graded out of the wrong file. Both were measured against `ordered` on
2026-09-13 and are why the census below exists.

**Correction, 2026-09-13.** The sentence here used to read "Phase 3 moved both
`ordered` and `linkedEnable` from the first to the second, because the keys they
name moved." That describes the 3.0 merge, and the move has since reversed twice:
`linkedEnable`'s two keys went back to `Section.Key` when the gates returned to
`ckf.hardmode.cfg`, and `ordered`'s two moved from `ckf.hardmode.json#powerlevel.*`
to `ckf.hardmode.d/powerlevel.json#*` when the document split.

### `linkedEnable` — flags that must move together

```json
{
  "kind": "linkedEnable",
  "keys": ["Slices.Progression",
           "Slices.ModelRules"],
  "reason": "Progression alone gives a correct award with a stock label; ModelRules alone gives a stock award with a lying label. Neither direction logs anything."
}
```

**A group is compared only when every key in it was read.** This used to keep
whichever keys resolved and compare those, so one key of a pair readable and the
other not produced a single state, which cannot disagree with itself, and the
group passed without anything being compared. A partially read group is now a
`SKIPPED` line naming the unread key. [measured 2026-09-13: replacing one of the
two keys with a name nothing declares printed
`SKIPPED Progression: linkedEnable -- Slices.NoSuchKeyOnDisk did not resolve
against the config directory, so the group was not compared` and
`linkedEnable: 1 declared, 0 compared, 1 skipped`, where it had previously
printed nothing]

### Every invariant kind carries a skip census

Three lines, printed on **every** run whether or not anything was skipped:

```
requires: 2 declared, 2 compared, 0 vacuous (dependent off), 0 skipped.
ordered: 1 declared, 1 compared, 0 skipped.
linkedEnable: 1 declared, 1 compared, 0 skipped.
```

`requires` was given one when it was added; `ordered` and `linkedEnable` were
not, and got theirs on 2026-09-13. **`0 problem(s).` is not the whole answer —
`N declared, 0 compared` is how a run says it declined to look.** The case that
forced this: after Phase 3 split the merged document, `powerlevel`'s `ordered`
pair still named `ckf.hardmode.json`, `inv_value` returned not-found, and the
comparison was dropped. `minCap` set to 20 against a `maxCap` of 1 — the exact
condition the invariant exists to catch — printed `0 problem(s).` at rc 0.
[measured 2026-09-13] With the census it prints the same `0 problem(s).` but also
`ordered: 1 declared, 0 compared, 1 skipped` and a line naming the key.

This is the eighth instrument in this repository caught reporting success over
something it could not look at; `AGENTS.md` §3 lists the earlier ones. A skip is
still **not** a problem and does not change the exit code — "could not look" is
not "wrong" — so the census is the only thing that distinguishes them.

### `requires` — a slice that needs another slice

```json
{
  "kind": "requires",
  "key": "ckf.hardmode.cfg#Slices.CyberweaponsLasers",
  "needs": ["ckf.hardmode.cfg#Slices.ImplantsSlot08"],
  "reason": "Laser damage rules and the slot-8 implant payloads describe the same items."
}
```

The fourth kind, added by Phase 2 of `split-config-into-toggleable-slices` per
its `design.md` §4. **It is directed, which `linkedEnable` is not.** `key` names
the dependent; `needs` names every key that must be true when `key` is true.
`key` false is always legal with `needs` in any state — that is the whole
difference from `linkedEnable`, which would call the same configuration a
half-on group.

`check_schema.py` grades it in four ways, and only one of them is a violated
invariant:

| Condition | Grade |
|---|---|
| `key` true, a `needs` key false | `INVARIANT`, naming both keys and the `reason` |
| `key` names a key no schema declares | `MISSING` — nothing can enforce it |
| a `needs` entry names a key no schema declares | `STALE` — the declaration, not the config, is wrong |
| `needs` is absent or empty | `MISSING` — a check with no subject |

`INVARIANT` is the grade `gui/serve.py` already lists in
`BLOCKING = ('RANGE', 'INVARIANT')`, so a hand-edited `.cfg` that violates a
`requires` cannot get a half-configured state past the editor either. The
editor's own two directions — auto-enable upward on a save that turns a slice
on, refusal downward on a save that turns off a slice something needs — are
`tasks.md` Phase 2's fourth and fifth checkboxes and are not this file's
business.

**A `requires` it could not evaluate is not a pass.** Four instruments in this
repo were found reporting success over an empty input inside one day, so this
one says when it declined to look. Every group that could not be compared
prints a `SKIPPED` line naming which key was unreadable and why — the key is
declared but not on disk, or `--no-cfg` meant the `.cfg` was never read at all,
which are different facts and are worded differently. `SKIPPED` lines are not
problems and do not move the exit code; the guard is the census line, printed
on **every** run whether or not anything was skipped:

```
requires: 2 declared, 2 compared, 0 vacuous (dependent off), 0 skipped.
```

`0 declared` and `2 declared, 0 compared` are different facts, and a census that
only appeared when something went wrong could not tell them apart. `vacuous`
counts the groups whose dependent was false, which are satisfied without
comparing anything. Under `--config <dir> --no-cfg` **every** `requires` naming
a cfg key is skipped and the run still exits 0 — measured, and printed as
`requires: 2 declared, 0 compared, 0 vacuous (dependent off), 2 skipped.` This
is the same coverage loss already recorded above for `linkedEnable`, and it is
now visible in the output rather than only in this document.

**A `requires` is declarable before either slice has a file.** It is a statement
about two `.cfg` keys, not about two files, and all 43 keys are on disk. So the
two declared today are enforced today even though `cyberweapons-claws.csv` and
`cyberweapons-lasers.csv` arrive in Phase 6 and `implants-slot06.csv` and
`implants-slot08.csv` in Phase 7. This is the opposite of the `linkedEnable` note in
the Phase 1 record above — a linked group needs **both** keys on disk before it
can be enforced, and so does a `requires`; the difference is only that these
four keys already are.

**Correction, 2026-09-13 — the key spelling.** `tasks.md`'s Phase 2 checkbox 2
says "`inv_value` already reads a key in either space via `mirror`'s
`<file>#<path>` notation, so no new key resolution is needed", and `design.md`
§4's example spells its key `ckf.hardmode.cfg#Slices.CyberweaponsLasers`. Both
cannot be true. The two spellings `inv_value` read were `Section.Key` and
`<json file>#<dotted path>`; a key prefixed with the **`.cfg`'s own** name took
the `#` branch, handed an INI file to `load_jsonc`, and raised

```
json.decoder.JSONDecodeError: Expecting value: line 1 column 1 (char 0)
```

— an uncaught traceback, not a miss and not a problem line. Measured 2026-09-13
against the unmodified `check_schema.py`, with that spelling on a `linkedEnable`
over the live 43-key `ckf.hardmode.cfg`. `inv_key` is the new resolution the
checkbox says is not needed: it strips a leading `ckf.hardmode.cfg#` and leaves
every other key alone, so `Slices.Progression` and
`ckf.hardmode.cfg#Slices.Progression` are one key for all four invariant kinds.
The example above is therefore what is on disk, and
`teampl.schema.json`'s bare `Slices.Progression` keeps working unchanged.

**Correction, 2026-09-13 — the subsystem name in an invariant message.** The
invariants loop never rebound `name`, so it held whatever the field loop above
left in it: the last schema in sorted order, `Progression`. No existing kind's
message used `name`, so nothing ever showed it. The first `requires` message
did, reporting a `CyberweaponsClaws` declaration as `Progression:`. Fixed in the
same pass; recorded because it is a defect that was invisible for as long as no
message named the thing it got wrong.

### Which `requires` exist, and how they were derived

`design.md` §4 gives **one** example and no rule for finding the rest, so the
set was derived from `sheets\raw\` and is recorded here with its evidence.
Two are declared.

| `key` | `needs` | Where |
|---|---|---|
| `Slices.CyberweaponsLasers` | `Slices.ImplantsSlot08` | `cyberweaponslasers.schema.json` |
| `Slices.CyberweaponsClaws` | `Slices.ImplantsSlot06` | `cyberweaponsclaws.schema.json` |

The derivation, in one measurement. `TalentModel` has exactly **33** rows with a
non-zero `Weapon`, and every one of the 33 is pointed at by an `ImplantModel`
row's `ImplantTalentId`: **17** from `ImplantClass 32` / `ImplantSlot 8`
(`WeaponClass 17`, Cyber Weapon Eyes) and **16** from `ImplantClass 27` /
`ImplantSlot 6` (`WeaponClass 16`, Cyber Weapon Claws), with no other class or
slot contributing and none left over. So each cyberweapon sheet and one implant
slot table describe the same items, and the claw sheet stands to slot 6 exactly
as the laser sheet stands to slot 8 — which `design.md` §7 states for both slots
and §4 does not.
[measured 2026-09-13, `../sheets/raw/TalentModel.csv`, `ImplantModel.csv`,
`WeaponModel.csv`]

Two details the measurement adds. `ImplantClass 32` has **18** rows, not 17: the
extra one is `ImplantTypeId 3217` "Lumen Trident", which carries
`ImplantTalentId 0` and so has no laser sheet row. And the laser pair collides
on an effect payload where the claw pair does not — Brightshot Optic 1-4 are 4
of the 17 laser rows and 4 of the slot-8 implant rows, and both sides carry a
crit column for the same item against different tables (`WeaponModel`
`CritMultiBase`/`CritMultiStealth` on the laser sheet, `EffectModel`
`CritMultiBase` on the slot-8 sheet, shipped 25). Exactly nine implant effects
in the whole referenced set have a non-zero `CritMultiBase`, all nine in slot 8
— the set `design.md` §7 calls "the nine `CritMultiBase` rules". Every
`ImplantClass 27` row has `ImplantEffectId 0`, and `TargetEffect`, `SelfEffect`
and `MatrixEffect` are 0 on all 16 claw talents, so the claw declaration rests
on item identity alone. [measured 2026-09-13]

**Candidates examined and not declared**, so the next pass does not re-derive
them:

- **`ImplantsGlobal` and the eleven slot tables.** `implants-global.json`'s one
  unscoped rule writes `Cost`, `InstallTime` and `ImplantStress` on all 198
  `ImplantModel` rows, which is every row of every slot table [measured]. Not
  declared: neither side is meaningless without the other, so there is no
  direction. What it is instead is a load-order question — a `Cost *0.5` and a
  `Cost =N` in two slices compose differently depending on which file
  `RulePlan` sees first — and that belongs to the phase that writes those files.
- **`ImplantsSlot02` and `ImplantsSlot04`.** `ImplantConflictId` is non-zero on
  16 rows, all with the value `1`, split 8 in slot 2 (classes 5, 40) and 8 in
  slot 4 (classes 17, 18), so one conflict group spans two slices [measured].
  Not declared: the relation holds for one column of 16 rows, not for the
  slices, and `requires`' unit is a whole `.cfg` key. Forcing slot 4 on whenever
  slot 2 is on, for a column a player may never touch, is the wrong instrument;
  the divergent-edit refusal `design.md` §11 describes is the right one.
- **`GearClasses` and either cyberweapon sheet.** Disjoint by construction:
  §5 gives gear classes `WeaponClass` 1, 2, 3, 4, 5, 6, 10, 11, 12 and 14, and
  the claws are 16 and the lasers 17 [measured]. No overlap, no declaration.
- **The eleven talent-balance packs, against each other and against everything
  else.** An ownership sweep over `ImplantModel`, `EffectModel`,
  `MatrixEffectModel`, `TalentModel`, `WeaponModel`, `ItemModel` and
  `JobNodeModel` found **no** `(table, id)` owned by two slices, other than the
  sentinel `NodeTalent1Id = -1`, which matches no `TalentModel` row and appears
  on 5 nodes across three packs [measured]. The one `JobNodeModel` `NodeReq`
  crossing a `JobId` boundary runs from Assassin (`JobId 4`) to Cyber Knight
  (`JobId 1`), and Assassin has no slice; the one dangling `NodeReq` is in Face
  (`JobId 17`), which also has no slice. This independently reproduces
  `design.md` §11's "referenced exactly once across all 65 tables".
- **`RuleModel` against anything.** No column in any sliced table resolves to a
  `RuleModel` `RuleId`; `TalentModel.AltRuleType` takes only 0 and 100
  [measured]. Nothing to declare.

**One candidate is NOT settled here and needs David.** The Warmachine pack
(`JobId 2`) contains nodes `Claw Master` and `Laser Master`, whose
`NodeTalentAdjustmentId` values 20 and 21 resolve to `TalentModel` rows named
"Any Cyber Claw Talent" and "Any Optical Laser Talent" — marker rows with
`Weapon = 0`, `TalentIsCyber 1`, that are **not** among the 33 and are **not**
rows either cyberweapon sheet writes. [measured 2026-09-13,
`../sheets/raw/JobNodeModel.csv`, `TalentModel.csv`] So there is no row overlap
and no cross-slice pointer, and on the mechanical test there is nothing to
declare. Whether `Slices.TalentsWarMachine` nevertheless **requires**
`Slices.CyberweaponsClaws` / `Slices.CyberweaponsLasers` turns on how the game
resolves that wildcard against the concrete claw and laser talents, which was
not read and is not guessed at here. A third family, "Any Cybernetic Pulse
Generator Talent" (`NodeTalentAdjustmentId 22`), has a Warmachine node and no
cyberweapon slice at all. The question is left open rather than answered.

---

## The third sanctioned deviation from "no balance changes"

`proposal.md`'s non-goal is that every value shipping today ships after this
change, with two named exceptions — the deleted `MonsterTypeModel` PL 11+ rule,
and the accidental ×1.8 drone recoil going away. **Both have now happened.**
Phase 5 took `ckf.hardmode.rules.json` from **287 to 270 rules** — the 16 recoil
ranges and the one `MonsterTypeModel` PL 11+ rule, 17 in total — and
`validate_rules.py` now reports **3,608 rules** where it reported 3,621.
[measured 2026-09-13, reported by the Phase 5 agent, not re-measured here] The
sentence above read "going away" in the future tense until this note was added;
nothing under `schema/` ever carried either count, so there was no other
occurrence to correct. **Removing
`implantStressClampMin` is a third, and it is recorded as one rather than
folded into the no-op it provably is.** A value ships today and will not after.

**The measurement, so the next agent does not restore it as an omission.**
`ImplantModel` has 198 rows; `ImplantStress` is `1` on 197 of them and `5` on
Quantum Rider. The clamp is compared against the **post-multiply** value, and
the multiply is ×3, so the two reachable values are 3 and 15 — both above a
floor of 1. **The clamp cannot bind on any row of the shipped data.** [measured
2026-09-13, `../sheets/raw/ImplantModel.csv`] David's ruling, 2026-09-13:
remove it, "it's useless".

**The live rule still carries it.** The one unscoped `ImplantModel` rule in
`ckf.hardmode.rules.json` is

```json
{ "model": "ImplantModel",
  "multiply": { "Cost": 0.5, "InstallTime": 0.5, "ImplantStress": 3 },
  "clampMin": { "ImplantStress": 1 } }
```

[measured 2026-09-13, the live file] **Phase 9's converter must not carry that
`clampMin` across.** A converter written to preserve every operand of every rule
will reintroduce it, and a later diff of shipped-versus-converted will show the
absence as a defect unless this paragraph is read first. Three multiplies go
across; the clamp does not.

`design.md` §7 and `implants-global.json`'s own `_doc` both describe the clamp
and were written before this ruling. Neither is wrong about what the rule says;
they are now describing an operand the schema deliberately does not declare.

## What the schema deliberately does not cover

`../gui/README.md` links here rather than restating this.

`ckf.hardmode.rules.json`, the `ckf.hardmode.d/*.csv` overlays, and
`ckf.hardmode.selfcheck.csv`. Those are bulk table authoring — 293 rules, 2,427
`MonsterTypeModel` rows, 102 expectations — with their own grammar
(`ModelRules.cs`) and their own editor, the spreadsheet. The one exception is
the generated `MissionPowerLevelModel` file above, which is a schema output, not
a schema input.

Annotation blocks in `missions.json` — `shipped`, `roomFlags`,
`objectivePayments` and the top-level `secondaryObjectives` — are captured
reference data that nothing deserialises and no schema declares. They are read
and written back untouched; the format has no "annotation marker" for them.

---

## Drift

`check_schema.py` reports four classes:

1. **Stale** — a key on disk with no schema field. This is what made the 12 dead
   keys invisible until a manual grep found them.
2. **Missing** — a schema field with no key on disk, unless the field declares
   `"optional": true`.
3. **Out of range** — a value outside its declared `range`.
4. **Broken invariant** — a `mirror` whose two sides disagree, a
   `linkedEnable` group that is half on, an `ordered` group out of order, or a
   `requires` whose dependent is true while a key it needs is false.

A fifth line is **not** a drift class: `SKIPPED`, printed once per `requires`
that could not be compared, plus the `requires:` census line printed on every
run. Neither moves the exit code. They exist so that a clean run states how much
of the `requires` set it actually looked at, rather than letting an unread key
read as a pass.
