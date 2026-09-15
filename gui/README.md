# `gui/` — the CKF Hard Mode config editor

One local web page that edits every configurable value in the mod, rendered
entirely from `schema/*.schema.json`.

```
gui/
  serve.py        stdlib only. Binds a free port on 127.0.0.1, opens a browser,
                  does all file I/O and all validation.
  app.html        one page. No CDN, no build step, no dependencies.
  settings.json   remembers the game directory. Created on first run. Not committed.
```

**Brought level with the 4.0 slice layout on 2026-09-14.** Before that this file
described the 3.x tool — a single `ckf.hardmode.json` with nine sections, a
`.cfg` holding one key, and an editor that never wrote a sheet. All three of
those are gone. If you find a claim here that contradicts the code, the code
wins and the claim is a bug in this file.

## Running it

```
python3 gui/serve.py
python3 gui/serve.py --no-browser
python3 gui/serve.py --port 8765         # bind this port instead of a free one
python3 gui/serve.py --config "C:\...\Cyber Knights Flashpoint\BepInEx\config"
python3 gui/serve.py --selftest          # the verification suite; writes only into a temp dir
python3 gui/serve.py --selftest --frozen-exe dist\CKF-Config-Editor.exe
python3 gui/serve.py --selftest-js       # just app.html's pure functions, under node
python3 gui/serve.py --run-check-schema --config DIR    # run check_schema and exit
```

**`--config` takes the config DIRECTORY, not a file.** Handing it
`<dir>\ckf.hardmode.cfg` dies in `_sandbox` with `NotADirectoryError`. This has
cost more than one person a run.

`--selftest` copies its fixtures from `--config` if you name one, else from
`<repo>/live-config` if that exists (a cloud session assembles one by staging
the game's config beside the checkout), else from the game config
`settings.json` already points at. It only ever READS that directory. If none
of the three resolves it says so and names what it looked for — until
2026-09-04 it took `<repo>/live-config` unconditionally and died on a
`FileNotFoundError` out of `copytree` on any machine without one.

**`copytree` also races a network or agent file-staging layer.** If your config
copy lives under a mount that is still being written, `--selftest` can fail on
scratch files that vanish underneath it. Copy the config to a quiesced local
directory and point `--config` at that.

It binds **a free port on 127.0.0.1** — no fixed port, no other interface — and
opens a browser at it. **It edits the live `BepInEx/config/` files in place.**
There is no staging copy you review afterwards; a save writes to the game's own
config directory. The first save of a session takes a backup (below).

**The game directory.** Frozen, it defaults to **the exe's own directory when
`CyberKnights.exe` is beside it** — the install step is "extract everything into
the folder holding `CyberKnights.exe`", so after an install the exe is in the
game root. The marker has to be there, so an exe run out of a downloads folder
falls back rather than naming it as the game. Unfrozen, and frozen without the
marker, it falls back to
`C:\Program Files (x86)\Steam\steamapps\common\Cyber Knights Flashpoint`,
which is right for exactly one install: a default Steam library on C:.

**A blank `gameDir` is the same state as an absent one** and takes the default.
`setdefault` only fills an absent key, so a settings file carrying
`"gameDir": ""` — what clearing the box in the header writes — used to survive
every restart, and re-extracting the zip did not clear it because the zip does
not carry that file. It opened the editor with an empty box on what looked like
a fresh install (David, 2026-09-07). Section 18 of `--selftest` covers absent,
blank, whitespace, a real value, both frozen branches, and that an explicit
`configDirOverride` still wins.

The directory is editable in the header and remembered in `settings.json`. That
path is normally under Program Files, so on startup the tool probes it for write
access by creating and deleting a file — `ok`, `denied` with the OS error,
`missing`, or `error`. A denied probe shows in a banner; a save that hits a
permission error is refused with the error text, never swallowed.

Procedure: `../docs/workflow.md`. Per-key reference:
`../docs/config-reference.md`. Traps: `../docs/gotchas.md`.

`--run-check-schema` is not for people. It runs `schema/check_schema.py` in
this process and exits with its code, and it is how the frozen exe validates a
save — see "Freezing it" below.

---

## What it owns

**43 `.cfg` keys, 11 sidecar JSONs, and 53 overlay/lever sheets.** Everything the
schemas declare as a `target`, all of it under the game's `BepInEx/config/`:

| | |
|---|---|
| `ckf.hardmode.cfg` | **43 keys in two sections** — `[General] Enabled` plus 42 `[Slices]` toggles, one per slice. `check_schema.py` asserts 43 on disk against 43 declared across 43 schema files |
| `ckf.hardmode.d/*.json` | eleven sidecars: `difficulty`, `elapse`, `fatigue`, `implants-global`, `missions`, `modelrules`, `powerlevel`, `rewardcurve`, `selfcheck`, `teampl`, and the generated `MissionPowerLevelModel.generated.json` |
| `ckf.hardmode.d/*.csv` | **53 declared overlay and lever sheets** of the 56 CSVs in the directory. The other three — `ArmorModel.csv`, `WeaponModel.csv`, `MonsterTypeModel.csv` — are **unclaimed by design**: they are generated enemy-gear overlays and this editor does not open them |

`ckf.hardmode.json` is gone. So is the 3.x arrangement where the `.cfg` held one
key; `gen_binds.py` emits a bind per slice and `--check` fails in both directions
if the key set and the declared slice set disagree.

**The `.cfg` is edited line by line.** Value lines are replaced in place; a
declared key that is absent gets a bare `Key = Value` appended under the right
section header. **No comment is ever written** — BepInEx owns those, and it
rewrites the file from the keys the plugin binds every time the game exits. Line
endings are held **per line**: an edited line keeps the ending it had, and an
unedited file round-trips byte for byte. A key the file does not carry and no
schema declares is refused rather than created.

Sidecars are written as strict JSON; the `_readme` block is removed under the
`stripReadme` setting, so the behaviour is inspectable rather than silent.

**First save of a session copies each file it is about to touch to
`<name>.pre-gui-backup`.** An existing backup is never overwritten, so it is
always the state before the *first* edit.

It does **not** delete a key from the `.cfg`; removal is BepInEx's business.
Annotation keys no schema declares (`shipped`, `roomFlags`, `objectivePayments`
in `missions.json` rows, and the top-level `secondaryObjectives`) are read,
hidden from the grids, and written back untouched. What the schema does not
cover at all: `../schema/SCHEMA-FORMAT.md`, "What the schema deliberately does
not cover".

---

## Lever sheets: what is editable, and what refuses

**Until 2026-09-14 this editor never wrote a sheet, and three places in the
source said it never would.** David reversed that rule and scoped the reversal
himself. Anything you find in this repository still asserting "the editor never
writes an overlay" is stale.

### What is editable

**A cell is editable if and only if the server graded its column `lever` AND the
column is not at index 0.** That is **563 columns across 53 sheets**, of 732
columns in total [measured, the live config, 2026-09-14].

**The client does not decide this.** `app.html` names no column and no file — a
selftest enforces it — so the affordance arrives as data: `entry.roles` and
`entry.editable`, computed in `serve.py` from the expanders' own declared
`IDENTITY` lists.

Three classes stay read-only, each for a different reason and none of them
"it would be awkward":

| | Why it is read-only |
|---|---|
| **identity** | It names *which* rows the line expands into. Changing it does not change what the row does, it changes what the row is about — and for the implant and cyberweapon sheets that is the join the expander makes against the game table, so a typo silently produces a rule matching nothing |
| **control** | `_comment`, `_clone`, anything whose header starts `_`. `_comment` is the prose the "ships N" hint is parsed out of; `_clone` is `Overlays.cs`'s row-clone source id. Neither is an override |
| **index 0** | The key column — the game table's own id on a direct overlay, the first identity column on an expanded sheet. Held out explicitly *as well as* by role, so a sheet whose first column ever graded `lever` still could not have its key rewritten |

**Rows are addressed by the identity-key tuple, never by the ordinal.** This is
not belt-and-braces: the first column alone is **not unique on 9 of the 53
sheets** — `cyberweapons-lasers.csv` is 17 rows over five distinct names, four of
which appear four times each — while the identity tuple is **unique on 53 of 53**.

### What a blank cell means, and what gets written

**A blank cell means "leave the game's column alone."** The writer emits an
**empty field** — not `0`, not `""`. Those are different things to the plugin and
writing the wrong one is a silent balance change.

**The writer replaces one field's character span in one line.** It does not
re-render the file. The header, every other row, the `_comment` prose, the
quoting (which the sheets use where a comment carries a comma), the column order
and the trailing newline all survive a save untouched.

### What refuses, by name

A write to the key column, an identity column or a control column; an
ungrammatical adjust cell; a line break in a cell; a row the key tuple does not
find; wrong key arity; an unknown column; an undeclared sheet; and a sheet that
is absent or unparseable. All raise `SaveRefused` and **no file on disk is
modified**.

**One case is accepted rather than refused, and says so.** Non-numeric text under
a `set` operator is taken **with a named warning** — **11 of the 379 filled
direct lever cells are `IconPng` strings**, which are legitimately text. Every
overlay save also carries **`NOT VALIDATED AGAINST A SCHEMA`** in its notes,
because `check_schema.py` declares no columns for these sheets: the save was
checked for grammar and for row identity, and for nothing else.

**If the expanders could not be imported, every sheet refuses writes.** A failed
import leaves `SHEET_SOURCE_ERROR` set and `SHEET_IDENTITY` short — and a short
identity list would grade a real identity column as `lever` and make it editable.
So the failure mode is "nothing is writable", never "more is writable". The
refusal is asserted by injecting the error into a selftest run.

**A shared row stays writable** and carries `repoint: true`, so an edit that also
reaches another slot's table is marked rather than blocked.

### The defect the read-only rule was hiding

Worth knowing because it is the shape of thing to look for elsewhere.
`files_check_schema_reads` returned **12 paths and no sheet**, and
`stage_and_validate` copies exactly that list. So every validate and every save
ran `check_schema` over a staging directory with **no sheet in it** and got back
**53 `MISSING` problems for 53 files that were all present**. `MISSING` is not in
`BLOCKING`, so no save ever failed and nobody noticed. The same omission meant
`fingerprints` did not cover the sheets, so a sheet edited on disk between read
and save could not be detected. That function now returns **65** paths — the
original 12 plus all 53 sheets — and the stale-fingerprint refusal for a sheet is
asserted.

---

## Suppressing a column that never changes

David asked to "suppress any column that never changes within a table". **Taken
literally the rule hides most of the tool**, and the measurement is why: of the
563 editable lever columns, **169 vary, 3 are constant at a real value, and 391
are constant only because every cell in them is blank**. On **19 of the 53
sheets not one editable column varies**.

A blank override column is not "nothing to edit". It is **no override set** — it
is exactly the empty cell there was no way to type into, which is the complaint
the write path exists to answer. So the rule has three exceptions, and each is a
measurement rather than a preference:

1. **Never the key column.** It is the row's name.
2. **Never a sheet with fewer than two rows.** A column is constant across one
   row by arithmetic; that is a tautology, not an observation about the data.
   `TalentModel.cs.csv` is one row with one lever column and would otherwise lose
   its only editable cell.
3. **Never an editable column whose one value is blank** — the 391 above.

**What survives is ten columns in the shipped config**: eight non-editable
columns holding the same value on every row (and all eight of them hold nothing
— five `EffectClassification` columns on consumable sheets, three
`MatrixEffectId` columns on implant slots), plus two editable `BuyCost` columns
pinned at `1` on `JobNodeModel.sn.csv` and `JobNodeModel.wg.csv`.

**Collapsing is not dropping.** A suppressed column stays in the model, in the
working copy and in the save. The grid names each one — with its role, its value
and its row count — in the sheet's own notes, and offers a
`Show N column(s) that never change` button to put them back. This is the same
standard `AXIS_WINDOWS` holds itself to below.

---

## Unset is not zero

Sparse rows and absent keys are legal and meaningful, and writing a zero where a
key should be absent corrupts config without any log line:

- `byPowerLevel["1"]` carries no `durationDays`
- `elapse.tiers.standard` carries no `patterns`
- `rewardcurve` treats a missing column or a negative one as "keep the game's
  number" — `RewardCurve`'s absent/`-1` convention, whose own `Tier` initialiser
  is `-1` (approx. `RewardCurve.cs:249-251`)
- a `fatigue.runningEmpty.byPowerLevel` anchor's `maxAffected` absent means no
  ceiling, while `0` is a real ceiling of zero — an `int?` (approx.
  `Fatigue.cs:404`). CITATION CORRECTION, 2026-09-07: this named the flat
  `fatigue.runningEmpty.maxAffected`, which was removed from the config surface
  that day along with every other flat value that had a `byPowerLevel`
  analogue. The anchor field is where the convention lives now.

Every value in the model is a pair: present, and the value. On the wire a cell
is `null` for absent, a number for present. The writer *pops* the key rather
than writing a zero, and an unchanged value keeps its exact on-disk text (so
`1.0` does not become `1` passing through a browser with one number type).

In the page:

- **numeric cell** — an empty box is unset, drawn hatched with a `— unset —`
  placeholder; `0` typed in is a real zero.
- **text cell** — an empty box is a real empty string, because `""` is a
  meaningful adjustment spec. Unset is the separate `∅` button — **except on a
  column declaring `"format": "adjust"`**, where `∅` is not offered and clearing
  the box turns the slot off. `MissionRewards.Adjust.Parse` returns `none` for
  both `""` and `null` (approx. `MissionRewards.cs:392-415`), so on those five
  columns and only those, a present `""` and an absent key are the same thing to
  the plugin. The distinction is load-bearing everywhere else and is untouched
  there; `--selftest` asserts the scope both ways.
- **lever cell** — an empty box is **no override set**, and the sheet's shipped
  value for that row and column is shown as the placeholder where the
  `_comment` prose carries one. This is a third convention, distinct from both
  of the above, and it is why the suppression rule has exception 3.
- **scalar field in the document** — an `unset` button, with the meaning of absent
  (the schema's `absent`, or the default) stated beside it.
- **matrix cell** — clearing it removes the override row and the cell shows the
  inherited stock value as a placeholder. **A row or column added with "add row"
  / "add col" starts unset too**, not at zero: `teampl.override` is one of the
  two `retroactive` fields in the mod, `Progression.Merged()` consults
  `Overrides` before `Cells`, and neither guard can tell a `0` from an absence —
  a `0` is inside the declared range and the mirror faithfully agrees with its
  source, so `check_schema` reports a clean file.
- **curve chart** — an unset point is not plotted, so the line breaks; a zero
  sits on the axis.

---

## The save transaction, and the mirror

`teampl.json` and `ckf.hardmode.d/MissionPowerLevelModel.generated.json` are two
halves of one invariant (`teampl.schema.json`'s `mirror`). `serve.py` imports
`scripts/gen_teampl_labels.py` and regenerates the mirror through its
`merged_cells` / `rules_for` / `render` in the same save as its source.

The commit is four phases:

1. Every proposed file is written to a temporary **beside its target** — same
   directory, so the rename is atomic — and `fsync`ed. A crash here leaves only
   temporaries; the config is untouched.
2. A journal naming the pending renames is committed atomically
   (`.ckf-gui-save-journal.json`, itself written-then-renamed).
3. The renames run back to back with nothing between them but the renames.
4. The journal is removed.

A crash between the two renames leaves the journal and the temporaries the
renames did not reach. **Two `os.replace` calls cannot be made one atomic
operation with the standard library**, so the journal is what makes the pair
recoverable: the next start calls `recover_journal()`, which finishes the
outstanding renames and deletes the journal. It follows only renames that stay
inside the config directory and whose two halves share a directory.

**The mirror is renamed first.** Both orders leave a detectable disagreement if
a crash lands between them; the mirror goes first because it is the
machine-owned half, fully derivable from `teampl.json`, so regenerating it from
whatever `teampl.json` then holds converges — and the hand-authored source of
truth is the last file touched.

**A save is refused if any file's SHA-256 changed since the page loaded it.**
Row identity in the JSON grids is positional, so writing against a stale read
could reattach preserved unknown keys to the wrong row and nothing downstream
would notice. **The sheets are covered by this too** — they were not until
2026-09-14, and the refusal is now asserted.

---

## Validation

`schema/check_schema.py` is **run, not reimplemented**, in a child process
reading its own pipe. Its four classes (`../schema/SCHEMA-FORMAT.md`, "Drift")
are the only ones the GUI knows. A save is staged into a temp directory — every
file `check_schema` reads, derived from the schemas rather than guessed, with
the proposed bytes overlaid — and the checker pointed at it. The mirror is
regenerated *before* staging, so the `mirror` invariant is checked against what
would actually land on disk.

**RANGE and INVARIANT block the save; STALE and MISSING are reported only.** If
`check_schema` could not run, the save is blocked too — an instrument's silence
is not evidence (`AGENTS.md` §3). So is a merely incomplete result: the trailing
`N problem(s).` line must be present and `N` must match the problem lines
parsed, or a truncated pipe reads exactly like a clean file.

**`check_schema` declares no columns for the lever sheets**, so it can say a
sheet is present and well-formed and nothing about what is in it. That is why
every overlay save carries `NOT VALIDATED AGAINST A SCHEMA`, and why the
per-cell grammar check in `overlay_check_cell` is not redundant with it.

Refusals outside the four classes: an **unparseable adjustment** (the plugin logs
and ignores it — a silent no-op); **type errors**; **a cfg value that would not
survive the round trip** (a leading `#` reads back as a comment; an embedded line
break leaves a stray line); and the nine lever-sheet refusals listed above. All
raise `SaveRefused`, never `assert` — `assert` vanishes under `python -O`.

---

## Rendering: schema in, controls out

`app.html` contains **no schema field path, column name, cfg key, section name
or filename** — only the `ui` values, which are the dispatch itself; `--selftest`
asserts this (`hardcoded_names_in_app_html`).

**There are six `ui` kinds and there have only ever been six**: `form`, `table`,
`curve`, `matrix`, `readonly`, `hidden`. `design.md` §12 proposed `levers` and
`slotTable`; **neither was built and no phase builds them**, and `serve.py`'s
selftest asserts the kind set is exactly those six. **The lever-sheet write path
did not add a seventh** — a lever cell is an ordinary `table` cell that the
server marked editable.

Two kinds carry dispatch specific to this tool: **`matrix`** is laid over the
field named by its `over`, and **`readonly`** is drawn as a matrix on the axes of
the field that declares it as its `over` underlay when there is one — so a
reference table and the control it backs are the same grid — otherwise as a plain
grid. A schema field the section does not have yet gets an empty grid, and saving
it empty does *not* invent a `{}` on disk.

**Two serialisation shapes behind one `type: "table"`.** A field with `keyedBy`
is an object on disk keyed by that column; without it, an array. **Five** fields
declare `keyedBy`: the four fatigue curves (`runningEmpty.byPowerLevel`,
`runningEmpty.knight.byPowerLevel`, `offDuty.byPowerLevel`,
`offDuty.knight.byPowerLevel`), all keyed by `powerLevel`, plus `elapse.tiers`
keyed by `name`. Everything else — `elapse.credits.byPowerLevel`,
`rewardcurve.curve`, `teampl.override` — is an array. Both shapes round-trip;
the shape is **read from the data and preserved**, and `keyedBy` only picks one
for a field with nothing on disk yet.

**REMOVED IN 3.0: one checkbox for a subsystem gated twice.** `Elapse` and
`Fatigue` used to be gated by a cfg key *and* by their sidecar's top-level
`enabled`, and the page collapsed the pair into one control — with an
*indeterminate* state and a red block for the case where the two disagreed on
disk, which was a real failure mode: the subsystem read `Enabled = true`, did
nothing, and logged nothing about why.

Phase 3 deleted the outer gate. `[Elapse] Enabled` and `[Fatigue] Enabled` are
gone from the `.cfg` and the section's own `"enabled"` is the whole chain, so no
subsystem declares two gates, there is no pair to collapse and no pair to
disagree. `enable_pair`, `pairRow`, `pairState` and the `displayGates` /
`pairDisagrees` payload went with them. A gate that could not be read still
shows `unknown` in the index, never `off`.

**`retroactive` is data, not a warning.** The key stays on the two fields that
carry it (`teampl.schema.json`'s `enabled` and `override`) and
`--selftest` asserts it reaches the page, but nothing on the page is built out
of it: **no pill, no red block, no confirm-before-saving gate.** That
Progression re-prices missions already finished is a fact about what the control
does, so it is written into that field's help and the subsystem's `uiDoc` like
any other fact. Nothing here overwrites a save file.

**`linkedEnable` groups** come from the schema's invariants; one checkbox writes
every key in the group, and saving them half on is refused by INVARIANT. Since
3.0 a group's keys are spelled `<file>#<section>.<path>` — the notation `mirror`
already used. `app.html` resolves them against the units the model carries rather
than by splitting on a dot, so a path containing dots cannot be mis-parsed.
**Every save returns a relaunch reminder** — each subsystem reads its config once
in `Plugin.Load()`.

### The sidebar

The nav lists five groups. Two sections are large enough that the old layout
broke on them: **Cyberware holds 12 subsystems and Consumables 6**, and
`navItem()` used to concatenate one gate checkbox per subsystem **before** the
title — so twelve boxes pushed the section name off the edge of the nav.

The gates now fold into **one summary chip** behind a `<details>`, with the name
first and the name as the only element that grows. Three properties the chip is
required to keep, because each of them was a lie the old index could tell:

- it reads `Cyberware 12/12` — **on** out of **declared**;
- it counts **on** and **unreadable** separately and never folds unknown into
  off: twelve gates nobody could read reads `0/12 ?`, not `0/12`;
- a section that declares **no** gate says `N pages`, not `0/0`, which would read
  as all-off.

The nav is **244px** and the base font **14.5px**; they were 338px and 16.25px,
which left a 24-column lever sheet scrolling sideways inside a pane narrower
than the table. That is roughly 110px of grid back on every page.

### Layout: where a field lives, and how wide a column gets

**A field's location is one identifying part per line**, outermost first: the
file, the section inside it, then each step of the key path. `pathParts` in
`app.html` splits on the separators the server already keys by — `#` between
file and section, `.` between the steps of a path — and `pathCode` gives each
part its own `<span>`. It still names nothing: the parts come from the schema's
`targets`.

**A grid column is 120% of the widest thing it has to hold**, plus 2ch for the
input's own padding, since `box-sizing: border-box` means a width in `ch` is the
outside of the box and without that term the margin is spent on padding. The
content is the longest value plus one, a floor by kind, and the longest heading
segment — **uncapped**, where a 12ch cap used to let a heading claim a width it
then had to wrap out of. The ceiling is 44ch: a 46-character mission id still
does not get a 47ch column. Headings keep their zero-width break opportunities
at the camelCase seams, so a wide heading wraps a word at a time rather than
being chopped.

---

## Presentation: the declared names

Order, grouping and labelling are in no schema, so they are written down **once,
in `serve.py`, under `PRESENTATION TABLES`**, with the reason beside each. All of
them are display only: nothing they do changes what is read or written.

| Table | What it says | Why it cannot be derived |
|---|---|---|
| `SECTION_GROUPS` | the five nav groups and the sections inside them, including `Progression` + `RewardCurve` presented as one section, *What a Mission Pays* | Two subsystems, two files, two cfg keys, one question. Nothing in either schema points at the other |
| `SECTION_LAST` | `SelfCheck` goes last | It is a verification tool, off by default and deliberately so. No schema key says "this one is a diagnostic" |
| `AXIS_WINDOWS` | the Team PL matrix draws `MissionPowerLevel` 1–10 | The game's table runs −10…10; the negative band is unexplained and PL 0 is worth nothing, so 33 of the 63 cells crowd out the 30 anyone edits |
| `MASTER_KEY` | `General.Enabled` is the master gate | No schema field marks a subsystem as the master gate, but `Plugin.cs` returns out of `Load()` before any subsystem initialises when it is false, so the index would lie without it |
| `COST_LABELS` | the three cost-column groupings | **Derived**, not typed |
| `ROW_LABEL_SHEETS` | `gear-classes.csv`'s ten `WeaponClass` ids draw by name | **Derived** off `gear_classes.SHEET_NAME`. The names come from `sheets/raw/WeaponModel.csv`'s `WeaponClassName`, which carries exactly one distinct name per id across 535 rows: 1 Melee, 2 Pistol, 3 `AR (Assault Rifle)`, 4 Shotgun, 5 E-Rifle, 6 Sniper Rifle, 10 SMG, 11 Revolver, 12 `UAR (Urban Assault Rifle)`, 14 Railgun |

**The header above `PRESENTATION TABLES` says "these four tables" and there are
six.** The last two are derived rather than literal, so the header's claim about
*literals* is still true — but a reader finds six things and four claimed, and
that is a bug in the comment, not in the code.

### Hiding a column never drops a value

`AXIS_WINDOWS` is a window on the *drawing*; the save is built from every row
the table holds, not from the cells on screen. Two rules keep that visible
rather than merely true:

- a coordinate outside the window that **carries a value is drawn anyway**, with
  the legend saying why it is there;
- the legend names the coordinates it is not drawing and states that a save
  leaves them alone.

`--selftest` proves it: an override built at `MissionPowerLevel 0`, outside the
window, survives a save, a read-back and the mirror, and is drawn on re-render.
**The lever-sheet suppression rule holds itself to the same standard** — see
"Suppressing a column that never changes" above.

---

## Prose: what is stripped, and where the volume actually comes from

`uiDoc`-over-`doc` and the paragraph rules are defined in
`../schema/SCHEMA-FORMAT.md`; `--selftest` asserts every schema carries a
`uiDoc`, so no player reads maintainer text through the fallback. Field help is
stripped of maintainer marks at render time — the GUI only;
`../docs/config-reference.md` goes on rendering the unstripped `doc`. Two
patterns, both deliberately narrow, because a regex that eats half a sentence is
worse than one that leaves a citation behind:

- **a parenthetical whose whole content is a citation** — `(Elapse.cs:833-835)`,
  `(Fatigue.cs:152, 161, 1423-1426)`. A parenthetical mixing a citation with
  prose is left alone: `(RewardCurve.cs:249-251, and the C# initialiser is -1)`
  survives intact.
- **an evidence tag** — `[measured]`, `[unverified: …]`, and the other two words
  of `AGENTS.md` §4. `[PowerLevel]`, `[RewardCurve]`, `[Diagnostics]` and
  `[JsonPropertyName("missions")]` are a column, two former cfg sections and a
  C# attribute, and are left alone.

A citation that is the **subject** of its sentence is left in place; removing it
would leave a sentence with no subject.

**The prose channel that actually dominates the page is not this one.** The
`uiDoc` path was already working — all 43 schemas report `docSource: "uiDoc"` —
and only a small fraction of the schema prose reaches the panel. **The volume is
`ov.notes`: 517 strings, 98,113 characters** [measured against the live config].
They are per column **pair**, so they grow quadratically:
`EffectModel.sol.csv` alone ships **81**, each the same sentence with two names
substituted.

They now render inside a `<details>` disclosure rather than as loose stacked
legends, which took the full-page render from 135,921 chars / 886 lines to
28,801 / 358 — with **every note string still present in the rendered
`textContent`**, which is the property that makes this a fold and not a deletion.
**The real fix is generator-side and nobody owns it**: emit one note per
*column*, listing that column's exclusive partners, and 517 lines become perhaps
60 without losing a fact.

---

## Security

It binds a socket, so:

- **127.0.0.1 only**, on a free port. Verified reachable on loopback and refused
  on this host's non-loopback address while the server was confirmed alive.
- Exactly two GET routes (`/`, `/app.html`, both serving the same fixed file)
  plus `/api/*`. No path is ever taken from the request; no directory is served.
- A per-process token, substituted into the page at serve time, required as
  `X-CKF-Token` on every API request — **including the read endpoint**. Another
  local page can POST to the port but cannot read the token, and cannot set a
  custom header cross-origin without a preflight this server does not answer. A
  write endpoint any page could reach would be a real hole; that is why the read
  endpoint is covered too.
- `Origin`, when present, must match; `Host` must match; both are checked before
  anything else.
- The only client-supplied path is the game directory. Filenames come from the
  schemas' `targets`, never from the request.

---

## The adjustment grammar

**Which string columns use it.** The five slot columns in `missions.json` do;
`note` does not. Since `app.html` may not name a field, the GUI reads an
explicit `"format": "adjust"` on a row column — those five declare it, and it is
what the dropped `∅` button keys off. Failing that it infers: a column counts
when at least one non-empty value parses and every non-empty value parses. The
inference is now only the fallback for a table whose schema says nothing.

**Lever cells use the same grammar**: `+N`, `-N`, `*N`, `=N`, and empty, reaching
`add`, `add` with a negative, `multiply` and `set` respectively. `overlayCellProblem`
in `app.html` is a transcription of `serve.py`'s `overlay_check_cell`, so a cell
the server will refuse is coloured before the round trip rather than after it —
**the client refuses nothing and blocks nothing; the server stays the
authority.**

**The validator is deliberately stricter than the plugin in one place.** .NET
recognises `NaN` and `Infinity` in `double.TryParse` regardless of
`NumberStyles`, so C# would accept `=NaN` and hand
`(long)Math.Round(double.NaN)` to a reward. The GUI refuses it. Narrower than
the plugin, never wider.

**`missionrewards.schema.json` and the array shape — resolved.** The schema once
declared `"keyedBy": "type"` on `missions` while the file on disk was an array.
The `keyedBy` was removed; the schema carries none at all today and the array
stands, which is what `MissionRewards` deserialises into
`List<MissionOverride>`. Shape preservation here is not a workaround for a
disagreement — there is none. See `../schema/SCHEMA-FORMAT.md`, "`keyedBy`, and
its one correction".

---

## Verification

`python3 gui/serve.py --selftest --config DIR` — **1353 passed, 0 failed, 3 not
run**, rc=0, everything written inside a temp directory and the source config
copied and never touched [measured 2026-09-14, Python 3.11.15, node v22.22.2].
**The 3 not-run are the `--frozen-exe` cases and only `--frozen-exe` clears
them** — they are reported with their reason and are not counted as passes.

It covers the adjustment grammar against `MissionRewards.Adjust.Parse`,
schema-field coverage, both round-trip directions, unset-vs-zero, both table
shapes, the mirror, the four validation classes, backups, the cfg's line-level
fidelity **including a file whose line endings are mixed**, **an out-of-range
save attempted repeatedly with four threads calling `/api/model`**, the journal,
the stale-read guard, the HTTP guards, the lever-sheet write path and its
refusals, and the 3.x→4.0 migration.

Two sub-reports it prints inside that run:

- **`node render of app.html`: 1659 passed, 0 failed.** The page is *rendered*,
  not just parsed: `node --check` over both `<script>` blocks, a DOM small enough
  to live in `serve.py`, app.html's own two blocks dropped on top with `fetch`
  stubbed to return a real model read from a real config directory, and
  assertions against the resulting tree.
- **`node render (hidden column occupied)`: 5 passed** — the same render over a
  config carrying an override in a column outside `AXIS_WINDOWS`.

`python3 gui/serve.py --selftest-js` — **96 passed, 0 failed**. `app.html`'s pure
functions under `node`, from the region between the `/*==CKF-PURE-BEGIN==*/`
sentinels. Keep anything touching the DOM or the network outside them.

**The migration block is the only instrument in the repository that compares
BUILT BYTES against DISK BYTES.** `serve.py` says so in its own voice. It is not
`make_release.py --selftest`, which has 112 cases and none of them is that
comparison; the two were conflated in an earlier handoff. This is the check that
found the `implants.py` column bug, so mis-attributing it means aiming the next
investigation at the wrong script.

It also covers the frozen build: both shapes of the `check_schema` child argv,
the `--run-check-schema` dispatch as a real subprocess, and three broken child
processes — one that exits nonzero after printing a clean summary, one that
prints a problem line and no summary, one whose count disagrees with its lines
— each of which must read as could-not-run and block a save that is otherwise
accepted. With `--frozen-exe` the same runs against the exe, which then also
has to serve `app.html`, answer `/api/model` with a complete validator result,
read `docs/mission-reference.json` out of its bundle, and write its settings
beside itself rather than into a bundle that is deleted on exit.

### NOT VERIFIED: how any of it looks

**No control has been clicked, no grid drawn, no point dragged, no layout seen —
here or in any headless session — and nobody opened this in a browser on
2026-09-14 either.** Every check above is `node` plus `serve.py`'s DOM stub,
**which has no CSS**. The following are asserted to be present in the DOM and
have never been seen rendered:

- the sidebar fold and its summary chip, in all three of its states;
- the `::placeholder` "ships N" text in an empty lever cell;
- the dirty marking on an edited lever cell, and the mark a cell gets when the
  client predicts a refusal;
- `opacity:.62` on a column restored by the `Show N column(s) that never change`
  button;
- **every CSS number in the file**, including the 244px nav and the 14.5px base.

**Not verified on Linux: the Windows exe.** `--frozen-exe` was exercised against
a PyInstaller build made in a cloud container, which is an ELF. It proves the
spec is coherent, that the re-entry works when `sys.frozen` is set, and that the
bundle holds what the server reads. It does not prove anything about
`CKF-Config-Editor.exe` until that is built on Windows and `--selftest
--frozen-exe` is pointed at it.

**The frozen case tears down a process TREE, and asks the OS whether it
worked.** A one-file exe is two processes — the bootloader and the application
it launches. `terminate()` is `TerminateProcess` on the bootloader on Windows:
it returns immediately and does not touch the child, so a `terminate()` with a
`taskkill` fallback behind a timeout never reaches the fallback, and the child
goes on holding the exe image. `_kill_tree` therefore does the tree kill FIRST
(`taskkill /F /T`, or a process group on POSIX), and the check afterwards asks
`_procs_from` — `tasklist` or `pgrep` — rather than trusting the `Popen`
handle, which can only see the process it started.

Two of those properties have no sampling moment on Linux, and are written down
rather than assumed [measured 2026-09-04]: the bootloader forwards `SIGTERM` to
its child there, so the Windows regression above passes; and a running binary
unlinks fine, so a leaked process does not block the delete. What the sweep can
still reach is a kill that does nothing and a `_procs_from` that cannot look —
and "could not look" is required to fail, not to read as "nothing running"
(`AGENTS.md` §3). The delete is reported NOT RUN, with the path, when nothing
is running but the directory survives: on Windows that is antivirus or the
search indexer holding a just-executed exe, not a process this suite leaked.

---

## Freezing it into an exe

```
cd D:\ckf-data-modding
pip install pyinstaller
pyinstaller gui\ckf-config-editor.spec        ->  dist\CKF-Config-Editor.exe
python gui\serve.py --selftest --frozen-exe dist\CKF-Config-Editor.exe
```

One file, nothing installed on the player's machine. `gui/ckf-config-editor.spec`
carries the reasoning; the two things worth knowing here:

**The bundle keeps the repo's shape.** PyInstaller unpacks `gui/`, `schema/`,
`scripts/` and `docs/` into a temp directory it names `sys._MEIPASS`, so
`serve.py`'s `REPO` is that directory and every path it derives is the one it
derives from a checkout. Nothing downstream asks which case it is in.
`settings.json` is the exception, because it is written and `_MEIPASS` is
deleted on exit: frozen, it lands beside the exe as
`CKF-Config-Editor.settings.json`, which in the zip is the game root.

**The validator is the exe itself.** `check_schema` is run in a child process,
never reimplemented, and frozen `sys.executable` IS the exe — handing it a
script path would relaunch the GUI and open a browser. So it spawns
`CKF-Config-Editor.exe --run-check-schema --config DIR`, which `main()`
dispatches before argparse exists. Every save pays one bootloader unpack; that
is the price of not having a second copy of the validator.

The save-blocking rules do not get to change when it is frozen: a child that
could not run, or that came back incomplete, still blocks the save.
`--selftest` asserts that over a substituted child process on any machine, and
over the real exe when `--frozen-exe` names one.

---

## Known warts, not fixed

- **A refused save discards every pending edit.** The `#save` handler calls
  `await load()` unconditionally after `/api/save`, which rebuilds the working
  copy and drops all pending cfg, sidecar and lever-cell edits. Lever cells are
  partly protected — bad cells are marked before Save, and `Validate` does not
  reload — but the wart reaches every control on the page.
- **`.navitem` is a `div` with an `onclick` and no `tabindex` or `role`**, so the
  section rows are not keyboard reachable. The `<summary>` and the gate
  checkboxes are natively focusable, so the fold works from the keyboard but the
  row it sits in does not.
- **`overlay_labels` writes the literal `out['Cost']`** about a thousand lines
  below the sentence that says nothing in the file names a field.
- **`app.html`'s suppression comment does not add up.** It says what survives the
  three exceptions is "16 … 9 of which hold nothing" non-editable columns plus 3
  editable, and then correctly concludes "Ten columns in the shipped config".
  The measured answer is **8 non-editable, all 8 blank, plus 2 editable** — which
  is where the ten comes from. 16 and 9 are the counts *before* two of the three
  exceptions are applied. The code is right; the comment is not.

### Four defects this tool shipped

Kept visible rather than edited out (`AGENTS.md` §5). Each has a `--selftest`
check that fails against the old code.

- **The validator could be silently emptied by a concurrent request.**
  `run_check_schema` captured a library's stdout by swapping the process global.
  `/api/model` takes no lock and `ThreadingHTTPServer` runs handlers in
  parallel, so one call's output landed in the other's buffer: a save read an
  empty problem list as a clean file and wrote an out-of-range
  `PowerLevelFraction` to `ckf.hardmode.teampl.json`, mirrored. **The rate was
  not reproduced consistently** — separate runs recorded materially different
  accept ratios, so no figure is quoted here; the defect is that it can happen
  at all. Fixed by running `check_schema` in a child process, which has no
  shared stdout to corrupt. The missing lock was the symptom, the process global
  was the defect.
- **"add row" / "add col" wrote a real `0` into a retroactive field.** `X && 0`
  is `0`, not `null`. Every other path in the matrix editor uses `null`.
- **A strict-mode write to a name nothing declared.** `RETRO_OK = {}` in
  `load()` outlived the retroactive confirm-before-saving gate 3.0 deleted: no
  declaration, no reader, and under `'use strict'` a `ReferenceError` the first
  time the line ran. Every start showed **"Could not load the config —
  ReferenceError: RETRO_OK is not defined"** and an otherwise empty page.
  Nothing caught it because nothing could: `node --check` parses the file
  clean, `--selftest-js` exercises the pure block, and the render harness builds
  from `FIXTURE` without going through `load()`.
  `undeclared_globals_in_app_html` is the check — every ALL-CAPS name the file
  assigns to has to be declared in it, ALL-CAPS being the file's own convention
  for a module-level binding.
- **One LF-only line in a CRLF `.cfg` re-pointed a key at another section.** The
  file was split on a single separator sniffed from the whole file, merging an
  LF-ended line into the next. On `live-config` that lost `General.Enabled` from
  the index and the write **appended a second `Enabled` line to `[General]`** —
  the master switch, which is what `AGENTS.md` §6 names Run53 for. Because
  `check_schema.load_cfg` iterates `for line in f`, it read the same file
  correctly and `stage_and_validate` could not catch the disagreement.
