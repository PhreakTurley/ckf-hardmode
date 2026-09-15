# Handoff — `split-config-into-toggleable-slices`

Rewritten 2026-09-14 at the end of Phase 9; **integrated again the same day**
after a wave of six agents landed the lever-sheet write path, the talent-name
correction, the weapon-class labels, the sidebar rework and two Phase 9
leftovers; **integrated again 2026-09-15** when the first real 4.0.0 build
refused and `release\ckf.hardmode.cfg.in` turned out to be a 1.0.0-era stub
(§6, §10, §13). **Phases 0-9 are complete. Phase 10 is not.** This file is
operational, not an OpenSpec artifact: it does not archive with the change
(`tasks.md` Phase 10 is explicit that the change archives without a
`handoff.md`) and it is deleted when the change lands.

It is rewritten rather than patched, twice now, because appended corrections
make it slower to read than the record it points at. Everything load-bearing is
carried forward. **`tasks.md` is the record; this is the operating manual.**

Read in this order: this file, then `AGENTS.md`, then `proposal.md`, `design.md`
and `tasks.md` Phase 10.

---

## 1. What this change is, and where it got to

`ckf.hardmode.json` + `ckf.hardmode.rules.json` — one settings document and one
flat array of 287 rules behind one switch — are gone. In their place:
`ckf.hardmode.d\`, **67 files** (**56 CSV and 11 JSON** [measured, the live
directory, 2026-09-14]), each with its own toggle in `ckf.hardmode.cfg`,
editable by hand with the game and the editor closed.

Two mechanisms, chosen by **what a row means** (`design.md` §1):

- **Direct overlay** — rows are rows of a game table. The filename before the
  first dot names the table; `Overlays.cs` loads it, no new code.
- **Lever sheet** — rows are player concepts (a weapon class, an implant slot
  entry, a consumable). A per-slice expander in the plugin expands one row into
  writes across several models, at load. **The plugin expands, never the editor**
  — hand-editing has to work with everything closed.

Phases 0-7 built the slices. **Phase 8** added the six consumable tables.
**Phase 9** deleted `ckf.hardmode.rules.json`, wired `implants-global.json`, and
shipped the migrator. **Phase 10 is the 4.0.0 release.**

---

## 2. The house rules

Not stylistic. Every one of them was written after something went wrong.

- **Never explain a mechanic you have not read.** Method names are not evidence;
  the interop assembly is marshalling stubs with no bodies. A hedged guess with
  `[unverified]` attached is still a violation.
- **Tag every claim**: `[measured]` / `[fitted]` / `[closed]` / `[unverified]`.
  Untagged reads as fact.
- **Corrections stay visible.** Say what was claimed, what it is, and how the
  mistake happened. Most of the value in `tasks.md` is its correction blocks.
- **Key on `(table, id)`, never on an id alone.** 130 ids are both an `EffectId`
  and a `MatrixEffectId`; 221 both `TalentId` and `EffectId`; 137 both
  `MonsterTypeId` and `WeaponId`. Phase 8's lead broke this three hours after
  quoting it and published 565 where the answer was 0.
- **Declare, do not derive.** See §5 — this is the newest rule and it cost the
  most.
- **Re-derive before you relay.** The single largest source of error in this
  change is repeating a number someone else measured. It cost the talent class
  names (§7) and it cost four counts in the brief that produced this rewrite.
  Numbers are cheap to re-check in a container; §4 tells you how.
- **No dry runs.** Make the change on disk, then report.
- **Hand David `cmd.exe` command lines with literal paths.** Never PowerShell.
- **No balance opinions.** State what numbers do.
- **An instrument's silence is not evidence.** ~23 instruments in this change
  were found reporting success over something they could not see. Assume yours
  is the 24th until you prove otherwise.

From `AGENTS.md`, still in force: **§7** the save databases are SQLite SEE and
that is respected — `unlock_db.py` was deliberately retired, do not revisit it.
**§9** the tuning lives **only** in the game's `BepInEx\config\`; `.gitignore` is
an allowlist. **§6** anything that writes to a save gets a review before it runs.

---

## 3. THE EDITOR NOW WRITES LEVER SHEETS. A stated invariant was reversed.

Read this before you believe anything else in the repository about what the
editor writes. Until 2026-09-14 the tool **never wrote an overlay or lever
sheet**, and that was asserted in at least three places in `gui\serve.py` and
`gui\app.html` — `Document.overlays` ("READ ONLY: no save path writes one"), a
selftest case ("an overlay path may not appear in a save's proposal"), and the
DOM asserts ("this editor never writes an overlay"). **David reversed it on
2026-09-14.** Anything you find still saying otherwise is stale; do not act on
it.

**The reversal is scoped, and he scoped it himself: lever and override columns
only.** The stated reason for the old rule had also lapsed — it named
`scripts\rules_to_overlays.py` as the only thing permitted to write a sheet, and
Phase 9 deleted that script's *subject*, so the sentence named no live writer.
The script itself is still on disk and still refuses at rc=1.

What is writable, all re-derived in a container against the live config on
2026-09-14:

- **563 editable columns across 53 declared sheets**, of 732 columns in total —
  role `lever` and index ≠ 0 [measured; `read_overlays` + `overlay_editable`].
- **Three classes stay read-only, each for its own reason**: the **key column**
  (index 0 — the game table's own id on a direct overlay, the first identity
  column on an expanded sheet), **identity columns** (they name *which* row the
  line is about; a typo there silently produces a rule matching nothing), and
  **control columns** (`_comment`, `_clone`, anything whose header starts `_`).
- **A row is addressed by its identity-key tuple, never by its ordinal.** This
  is not defensive: the first column alone is **not unique on 9 of the 53
  sheets**, while the identity tuple is **unique on 53 of 53** [measured].
  `cyberweapons-lasers.csv` is 17 rows over **5** distinct first-column values —
  `Brightshot Optic`, `Lumen Spear`, `Photon Lance` and `Helios Beam` appear
  **four times each**, `Luem Trident` once.
- **A blank cell means "leave the game's column alone."** The writer emits an
  **empty field** — not `0`, not `""`. One field's character span in one line is
  replaced, so the header, the other rows, the `_comment` prose, the quoting,
  the column order and the trailing newline are never re-rendered.
- **Refusals exist by name** for: the key column, an identity column, a control
  column, an ungrammatical adjust cell, a line break in a cell, a row not found,
  wrong key arity, an unknown column, an undeclared sheet, and an absent or
  unparseable sheet.
- **Non-numeric text under a `set` op is ACCEPTED with a named warning**, not
  refused — **11 of the 379 filled direct lever cells are `IconPng` strings**
  [measured; re-derived through `overlay_check_cell`]. Every overlay save
  carries `NOT VALIDATED AGAINST A SCHEMA` in its notes, because
  `check_schema.py` declares no columns for these sheets.
- **If `SHEET_SOURCE_ERROR` is set, every sheet refuses writes.** A short
  `SHEET_IDENTITY` would grade a real identity column as `lever` and make it
  editable, so a failed expander import disables writing rather than widening
  it. The refusal is asserted by injecting the error.
- Shared-row cells stay writable and carry `repoint: true`.

**Correction, visible.** The brief that commissioned the write path said these
sheets carry per-row `#` comments and that `_SHIPPED_RE` parses them. They do
not. [measured, all **56** CSVs in the live `ckf.hardmode.d`] there are **zero
`#` comment lines and zero blank lines** in any of them. `_comment` is a real
**last column** on all 56 sheets, and the `Shipped:` prose is inside that
field — **284 of 3,598 data rows carry it**, not every row — which is what
`_SHIPPED_RE` (`serve.py:1866`) actually searches.

### The defect the read-only rule had been hiding

`files_check_schema_reads` returned 12 paths and **no overlay**, and
`stage_and_validate` copies exactly that list. So **every validate and every
save was running `check_schema` over a staging directory with no sheet in it**
and getting back **53 `MISSING` problems for files that were all present**.
`MISSING` is not in `BLOCKING`, so no save ever failed — which is why it
survived. The same omission meant `fingerprints` did not cover the sheets, so a
sheet edited on disk between read and save could not be detected. Both fixed,
and the stale-fingerprint refusal for a sheet is now asserted.

### Five columns are hidden by name. Hiding is not dropping.

**Added 2026-09-14 at David's request.** `ImplantLevel`, `Deactivated`,
`ImplantConflictId`, `Rarity` and `PowerLevel` are off the screen on every sheet
that carries them, reason "item metadata, not a combat lever". The names are a
**declared table**, `HIDDEN_COLUMNS` in `gui\serve.py` (`:414`), read by
`overlay_hidden`. `app.html` names no column and must not start — it reads the
per-column reason string the server sends; two selftests keep that true.

**It is not the constancy rule and must not be folded into it.** Constancy is a
fact about the cells and **exempts a sheet of fewer than two rows**, because
constant-across-one-row is arithmetic. A declared hide is a decision about the
column, says nothing about the data, and therefore **has no row-count
exemption**. The two reach the page as separate keys — `constant` and `hidden` —
so each collapsed column gets the reason that actually applies to it. The
selftest asserts both halves, including "the constancy rule still HAS that
exemption, so the two have not been quietly merged". **If you find yourself
merging them, that test is telling you not to.**

**Nothing live was hidden.** Over the 53 declared sheets, counted on the rows the
page draws [measured 2026-09-14, live `ckf.hardmode.d`; re-derived independently
2026-09-14]: `ImplantLevel` 11 sheets / 178 cells, `Deactivated` 7 / 133,
`ImplantConflictId` 2 / 49, `Rarity` 17 / 264, `PowerLevel` 19 / 283 — **0
non-blank in every one**. Off the raw files rather than the drawn rows, `Rarity`
and `PowerLevel` read 265 and 284; the extra row is the one
`consumables-matrix.csv` withholds and its cells are blank too.
**`ArmorModel.csv` (180 rows) and `WeaponModel.csv` (385 rows) do carry a
non-blank `PowerLevel` on all 565 rows** — but they are "unclaimed by design",
no schema declares them and `read_overlay` is only called for a path some
schema's `targets.overlays` names, so this editor never opens them.

**The contract: a hidden column stays in the payload, in the working copy and in
the save**, is named with its reason in the sheet's notes fold, and the "show all
columns" button puts it back. Index 0 is never hidden. The button is shared with
the constancy rule; the *wording* is not.

### The gate is one control now — and two selftests had been asserting opposite rules

**Merged 2026-09-14**, on David's "The 'On' and 'true' checkbox sections are
functionally duplicates ... Combine them." One fact had been rendered three
times: the `<h3>` pill (server, read at load), the "enable chain" meta line, and
a separate `Enable <title>` checkbox in the body card (working copy). The pill
and the box **could disagree and did** — between an unsaved flip and a save the
page said "on" beside an unticked box. `gateControl` is now the single control.

What survives, and why: **three states** (on / off / indeterminate = could not be
read); **the enable chain as its own line** (the box is this slice's key, the
chain is every gate between the key and the code running); **`gatedByMaster` as a
separate pill** — the master returning out of `Plugin.Load()` is a *different
fact* from this slice's key being false, and one control for both could not say
which happened; **"always on"** for a schema with no `enable`; and the
**`setBool` handler**, shared with the nav, so `linkedEnable` groups still move
together and `requiresBlockers` still refuses a stranding flip.

**THE CORRECTION THAT MUST NOT BE LOST.** Merging the controls exposed that the
nav asserted `disabled === (cfg && !present)` and the panel asserted
`disabled === false` **about the same gate, and both passed**. The panel's rule
is the right one, and its reason was already recorded in place in
`gui\app.html`'s `formControl`:

> That was right while `ckf.hardmode.cfg` held every key the plugin bound. It is
> wrong now: 43 schemas declare a cfg key and the live file carries one, so this
> greyed out all 42 slice toggles and the editor could not set a slice at all
> until someone launched the game. `CfgFile.set_value` appends a key the file
> does not carry, so the control stays live.

[verified verbatim 2026-09-14.] `gateBox` now reads `cb.disabled = !slot;`.
**Re-adding the disable re-breaks every slice toggle on a fresh install**, where
`ckf.hardmode.cfg` has not yet been written by a launch. Not loosened: the nav
case still asserts a value, the opposite one; the absent branch is still counted
(`togIndeterminate`, `notInFile`) so "not in the file" cannot go quiet, and the
panel additionally asserts the row says "not in the file yet — saving adds it".

---

## 4. Run the gates yourself — and stage the WHOLE repo

You can run every converter in your own container without David. **Stage the
whole repo when you do.** A partial copy produced **six false reds and one false
green** in a single day, to people who had already read this warning:

| Gate | Reported | What was missing |
|---|---|---|
| 11 | 6 PROBLEMs, `JobNodeModel.IconPng` unknown | `sheets\raw\_dropped_columns.csv` |
| 08 | 1 FAIL in `read_mission_reference()` | `docs\mission-reference.json` |
| 06 | rc=2, `no such directory` | `overlays\` |
| 09 | rc=1, traceback | `mods\CKFHardMode\Defaults.cs`, then `release\*.in` |
| — | "`merge_sidecars.py` does not exist" | it does; never staged |
| — | "`tests\fixture-3.0.0\` does not exist" | it does; never staged |

**And one FALSE GREEN, which is worse than all six.** Gate 15 passed in a
container and failed on David's machine, because both halves of the check read
the same narrow dump. **Two things derived from one wrong source always agree.**
The reds were loud and cost an hour; this one was silent and shipped. When an
instrument compares A to B, ask whether A and B come from the same place.

### How to invoke them without losing a run

Three of these have each cost somebody a run:

- **`serve.py --selftest --config` takes the config DIRECTORY, not a file.**
  Passing `<copy>\ckf.hardmode.cfg` dies in `_sandbox` with `NotADirectoryError`.
- **`validate_rules.py --game` takes the GAME ROOT**, and derives
  `BepInEx\config` under it. Point it at the config directory and it refuses
  with a message about an empty comparison, which reads like a defect and is not.
- **`implants.py --selftest` and `consumables.py --selftest` need `--game` and
  `--dump`** like their `--check` siblings. Without them they refuse at rc=2 —
  correctly. That refusal is not a red.

### The sweep, as measured on 2026-09-14

Run in a container against a whole-repo mirror plus the live config, Python
3.11.15, node v22.22.2. Every row below was re-derived for this rewrite rather
than copied.

| Gate | Result |
|---|---|
| `gui\serve.py --selftest --config <dir>` | **1353 passed, 0 failed, 3 not run**, rc=0. Its `node render of app.html` sub-report is **1659 passed, 0 failed** |
| `gui\serve.py --selftest-js` | 96 passed, 0 failed |
| `schema\check_schema.py --config` / `--game` | 0 problems; **43 cfg keys on disk, 43 declared across 43 schema files**; overlays **53 declared across 32 schema files, 56 csv/tsv on disk, 0 unclaimed, 3 unclaimed by design** |
| `gen_binds.py --check` | up to date, 43 cfg keys |
| `gen_teampl_labels.py --check` | current, 30 rules match |
| `merge_overlays.py --check` | rc=1, honest refusal — unchanged |
| `merge_sidecars.py --selftest` | rc=1, retired — unchanged |
| `rules_to_overlays.py --check` | rc=1, recorded non-run — unchanged |
| `make_release.py --selftest` | **112 passed, 0 failed** |
| `validate_rules.py --game` | rc=2, refusing — correct |
| `validate_rules.py --game --dump sheets\raw` | rc=0, **0 errors, 22 warnings** |
| `validate_rules.py --game --dump --enabled-set` | rc=0, **0 errors, 21 warnings**; 3379 rules from 66 overlay files, 6165 pointer writes resolving 615 distinct `(table, id)` pairs, **0 dangling** |
| `gear_classes.py --check` / `--selftest` | rc=0, 0 problems |
| `cyberweapons.py --check` / `--selftest` | rc=0, 0 problems |
| `implants.py --check` / `--selftest` | rc=0, 0 problems; selftest **44 passed, 0 failed** |
| `consumables.py --check` | rc=0, 0 problems |
| `dotnet build` | **not runnable in the container.** No C# changed on 2026-09-14 |

The 3 not-run are the `--frozen-exe` cases; no exe was built.

### What moved on 2026-09-15, and the row that WAS red

Re-run in a container against a whole-repo mirror plus the live config, Python
3.11.15, node v22.22.2, same shape as the sweep above. Only the rows that moved
are restated; everything else was left alone.

| Gate | 2026-09-14 | 2026-09-15 |
|---|---|---|
| `gui\serve.py --selftest --config <dir>` | 1353 passed, 0 failed, 3 not run | **1300 passed, 0 failed, 15 not run** — as of the migration-block retirement, late 2026-09-15; see "The migration block is RETIRED from the default suite" below. Earlier that day it read 1367/0/3, then 1363/4/3 once David tuned two live files. `--selftest --migration` still reads **1363 passed, 4 failed, 3 not run** |
| its `node render of app.html` | 1659 passed, 0 failed | 1893 passed, 0 failed |
| its `node self-test of app.html` | (not in the table) | 104 passed, 0 failed |
| `make_release.py --selftest` | 112 passed, 0 failed | **114 passed, 0 failed** (two `.cfg` cases added, §10) |
| `gen_cfg_template.py --check` | (did not exist) | **up to date, 43 cfg key(s)** — new **gate 16** |
| `gen_binds.py --check` | up to date, 43 cfg keys | up to date, 43 cfg keys |
| `check_schema.py --config` | 0 problems, 43/43/43 | 0 problems, 43/43/43 |
| `gen_teampl_labels.py --check` | current, 30 rules match | current, 30 rules match |

#### The `.cfg` header stamp — CLOSED, 2026-09-15

**What it was.** For most of 2026-09-15 `serve.py --selftest` read **1359
passed, 4 failed, 3 not run**, and the migration block reported *"compared 68
file(s), 587425 byte(s) … 67 identical, 1 differ"*. The four named themselves:

```
FAIL  68 of the 68 are byte-identical to the live 4.0 layout   ['ckf.hardmode.cfg']
FAIL  nothing differs at all -- the declared divergence set is empty and the
      measured one equals it                                    ['ckf.hardmode.cfg']
FAIL  the .cfg is byte-identical to the shipping one
FAIL  control: with no fault injected the run is the green one -- 68 of 68
      identical, nothing differing at all   (67, [('ckf.hardmode.cfg', 3238, 3238)])
```

The whole difference was **one line** — the two files were 3238 bytes on both
sides:

```
-## Settings file was created by plugin CKF Hard Mode v1.0.0     (migrated)
+## Settings file was created by plugin CKF Hard Mode v4.0.0     (live)
```

`migration_cfg` built the 4.0 `.cfg` as `head = raw_cfg` plus an appended
`[Slices]` block, and its docstring said so — *"the 3.x file kept byte for byte,
with `[Slices]` appended"* — so the migrated file inherited
`tests\fixture-3.0.0`'s `v1.0.0` header by design. The assertion `_cfg ==
read_bytes(os.path.join(src, 'ckf.hardmode.cfg'))` was true only while the live
file still carried that same header. **David's 4.0.0 relaunch on 2026-09-15 had
BepInEx rewrite the live header to `v4.0.0`, and the assertion has been false
since.** Not a regression from any edit: a latent claim about another file that
went false the moment that file moved, which is the class §10 exists for.

It blocked the release, not only the suite. `make_release.build` runs
`gate(exe, …, config_dir=snap)` — `serve.py --selftest` against the snapshot it
is about to zip — and the snapshot's `.cfg` is `release\ckf.hardmode.cfg.in`
rendered with `@VERSION@` → the real plugin version, so the build refused the
same way [measured: the same 4 failures against the built snapshot].

**David's ruling, 2026-09-15: stamp the header with the plugin version.** Not
"compare from the `## Plugin GUID:` line down", and **not** adding
`ckf.hardmode.cfg` to `MIGRATION_CLOSED_DIVERGENCES` — that set being empty is
load-bearing and is what caught this. His reasoning: it is the same defect he
ruled on the day before, in the same migrator, one file over. `run_migration`
had been stamping every slice file with the `_version` of the 3.x document it
had just read, which would have made every migrating player's first launch
report all ten slices behind and `make_release.check_doc_version` refuse their
build. The fix there was `MIGRATION_DOC_VERSION`, and the ruling was **fix the
disagreement, not the gate.**

**The fix, following that precedent exactly.**

- `MIGRATION_PLUGIN_VERSION = '4.0.0'` is declared in `gui\serve.py` beside
  `MIGRATION_DOC_VERSION`, with the same reasoning for why it is a **declared
  literal and not a parse of `Plugin.cs` at migration time**:
  `gui\ckf-config-editor.spec`'s `datas` lists `gui/`, `schema/`, `scripts/` and
  `docs/` and **no `mods/` entry** [measured 2026-09-15], and `--migrate` runs
  from the frozen exe, so parsing `Plugin.cs` there would refuse a migration in
  the one build a player actually has.
- `migration_cfg_stamp_header()` replaces **one token on one line**: the version
  in the BepInEx header, matched by `_MIGRATION_CFG_HEADER` against the whole
  first line. The plugin name, the trailing whitespace, that line's ending and
  every byte after it are returned exactly as they arrived, so the rewrite never
  spans a line ending and a CRLF file stays CRLF without the function knowing
  which it has.
- **A header line that is not that shape is a REFUSAL**, not a rewrite and not
  an append. A `.cfg` announcing a version other than the running plugin's is
  the defect; guessing which of "replace the whole line", "insert a header above
  it" or "leave it" a stranger first line wants would put the silent
  disagreement straight back. The refusal is raised inside `build_migration`, so
  nothing has been written, and the message names the line and says the two ways
  out (restore it, or delete `ckf.hardmode.cfg` and let BepInEx write a fresh
  one).
- `migration_cfg`'s docstring no longer claims the file is kept byte for byte
  without qualification; the correction is in the docstring, visible.
- The injected fault `cfg-key-dropped` is **untouched**: the stamp is applied to
  `raw_cfg` *before* the fault branch replaces `head`, so the fault's
  version-less rebuilt block still reaches the output and still goes red by
  difference on `ckf.hardmode.cfg`.

**Checked against the C#, not against itself.** A new case in section 19c, in
the same block as the `DocVersion` one, reads `PluginVersion` out of
`mods\CKFHardMode\Plugin.cs` and asserts it equals `MIGRATION_PLUGIN_VERSION`.
Two literals, nothing deriving one from the other. **NOT RUN, never PASS**, when
`Plugin.cs` is absent — that is the frozen exe.

**Proved it could fail.** With `head = raw_cfg` put back and nothing else
changed, the run goes to **1360 passed, 7 failed, 3 not run**, the migration
block back to *"67 identical, 1 differ"*, and the byte-identity check names the
file:

```
FAIL  68 of the 68 are byte-identical to the live 4.0 layout   ['ckf.hardmode.cfg']
FAIL  nothing differs at all ...                                ['ckf.hardmode.cfg']
FAIL  control: ... (67, [('ckf.hardmode.cfg', 3238, 3238)])
```

With the stamp in place: **1367 passed, 0 failed, 3 not run**, *"compared 68
file(s), 587425 byte(s) produced against 587425 byte(s) on the live 4.0 layout;
68 identical, 0 differ"*. (That was the count at that moment, with the migration
block still in the default suite; later the same day David's tuning took it to
1363/4/3 and the block was retired. The default suite reads **1300 passed, 0
failed, 15 not run** now — see *The migration block is RETIRED from the default
suite* below. Nothing about the stamp itself changed.)

**Why 1367 and not 1364.** One case was **restated**, not added: *"the 3.x
[General] block survives byte for byte at the head"* asserted
`_cfg.startswith(<the fixture>)`, which included the header line the converter
now restamps. Weakening it to a prefix match below the header would have lost
the claim, so it is split into the two claims it was really making — everything
below the header line is untouched, and the header line differs in the version
token and nothing else — with the fixture's own version read back out of the
fixture rather than typed in, and the two required to actually differ. Four
cases are genuinely new: the `Plugin.cs` comparison; that the `Enabled = false`
conversion is restamped *and* still carries `false`; the stranger-header
refusal; and its control, the identical fixture **with** the header line, which
converts — so the refusal is the header and not the sandbox.

**A side effect worth knowing.** The four other migration faults —
`drop-section`, `range-short`, `d1-reconstructed`, `d3-carried` — used to list
`ckf.hardmode.cfg` in their `differs:` detail alongside the file they were
actually about. That was the latent `.cfg` failure contaminating every fault's
evidence. Their detail lines are now clean.

**Gates 13-15 no longer lose their subject.** `tasks.md`'s Phase 9 and Phase 10
tables still predict that `cyberweapons.py --check` raises
`ckf.hardmode.rules.json is not on disk` and that `implants.py --check` degrades
silently. Phase 9 re-pointed both; all three converters are now rc=0 with 0
problems against a config that has no rules file. The tables are a record of
what was expected, not of what happens — Phase 10's is corrected in place.

**One flake, recorded as a flake.** A single run once produced 4 failures at
`serve.py:9591`, "a gate its linkedEnable group will not let move alone is
refused for a stated INVARIANT", on `TalentsVanguard` / `TalentsWarMachine` /
`TalentsWraith` / `Progression`. Not reproduced in four subsequent runs over
identical bytes, nor in two further full runs since. `App.api_save` /
sandbox-copy territory. **Do not present it as a known defect**; do record it if
you see it again.

#### The retired `enabled` gate is off the live files — CLOSED, 2026-09-15

**What it was.** David's editor opened on a banner: *"8 key(s) in 8 file(s) are
not declared by any schema"*, naming a top-level `enabled` in `elapse.json`,
`fatigue.json`, `missions.json`, `modelrules.json`, `powerlevel.json`,
`rewardcurve.json`, `selfcheck.json` and `teampl.json`. Seven `true`, `selfcheck`
`false`. Those are 3.x orphans: in 3.x each section carried its own gate; in 4.0
the gate is `[Slices].<Name>` in `ckf.hardmode.cfg`, because a gate cannot live
inside the file it gates (`design.md` §3). `run_migration` carried the 3.x
section body across verbatim (`obj = {'_version': version}` then
`obj.update(body)`), and the orphan came with it — so **every migrating player
was born with the same eight-file banner**, not just David.

**What changed. Both sides, together.**

- `gui\serve.py` declares `MIGRATION_RETIRED_GATE_SECTIONS` — a frozenset of the
  eight section names — beside `MIGRATION_MIN_BYTES`, and the split loop pops
  `MIGRATION_RETIRED_GATE_KEY` off `obj` for a section in that set. `obj` is the
  section's own top level and the pop never descends.
- The eight live files in `ckf.hardmode.d` lose the key. `37,459 → 37,306
  bytes`, **−153**, which is `7 × 19` (`  "enabled": true,` + newline) plus
  `1 × 20` (`selfcheck`'s `false`). Every file was rebuilt two independent ways
  — a single-line delete, and a parse / pop / re-render through the editor's own
  `json.dumps(indent=2, ensure_ascii=False) + '\n'` — and the two agreed byte for
  byte on all eight.

**THE EIGHT ARE NAMED, NOT FOUND, and that is the whole care in this change.** A
walk for any key called `enabled` would also take `credits.enabled` and
`stress.enabled` in `elapse.json` and `woundResist.enabled` in `fatigue.json`.
Those three are **not** retired — `Elapse.cs:198-200` and `Fatigue.cs:483-484`
say so in the same comments that retire the top-level one: *"They gate blocks
inside this subsystem rather than the subsystem, so they are settings."*
`woundResist.enabled` is additionally a **declared schema field**
(`fatigue.schema.json`, `in: json`, bool, "Wound Resist mitigation"). They live
one level down, so only a top-level pop on a named section can tell them apart.
All three are on disk, quoted off the written bytes:

```
elapse.json   26-  "credits": {          fatigue.json  342-  "woundResist": {
              27:    "enabled": true,                  343:    "enabled": true,
              72-  "stress": {
              73:    "enabled": true,
```

`difficulty` is deliberately absent from the set: it never carried the key, so an
`enabled` appearing at its top level is a stray and is carried through to be
reported as one — the reading `ConfigDoc.cs`'s `Declared` table already takes.
`implants-global.json` never carried one either and is not a migrated section.

**No C# changed, and none should.** All eight subsystems still parse the key into
a `bool? RetiredEnabled` and still hand it to `Slices.ReportRetiredGate`
(`Elapse`, `Fatigue`, `MissionRewards`, `ModelRules`, `PowerLevelCap`,
`Progression`, `RewardCurve`, `SelfCheck`), and `"enabled"` stays in every one of
the eight `Declared` rows in `ConfigDoc.cs`. A player upgrading a 3.x install by
hand still has the key on disk, and **must** get `ReportRetiredGate`'s Warning
rather than a stray-key Error. Deleting the C# side would turn a handled case
into a reported fault for exactly the people the code was written for.

**What the editor's own instrument says, before and after** — `stray_keys` /
`stray_notes`, `serve.py:3128` / `3183`, which is where the banner comes from:

```
before: top-level keys no schema declares (8 file(s), 8 key(s)):
        elapse.json: enabled; fatigue.json: enabled; missions.json: enabled;
        modelrules.json: enabled; powerlevel.json: enabled;
        rewardcurve.json: enabled; selfcheck.json: enabled; teampl.json: enabled
after:  top-level keys no schema declares (0 file(s), 0 key(s)): none
        undeclared: 0 of 10 file(s) carry a top-level key no schema declares
        (0 key(s) in total; keys beginning "_" are the repo's own metadata …)
```

**Proved the byte-identity check could catch a one-sided change, both ways.**
Neither direction is theoretical; both were run.

| Injected | Migration block | Named |
|---|---|---|
| neither side (the real state) | 587,272 produced / 587,207 live; **66 identical, 2 differ** | `cyberweapons-lasers.csv`, `fatigue.json` |
| **A** — migrator strips it, the eight live files still carry it | 587,272 / 587,360; **59 identical, 9 differ** | the two above **plus all eight** |
| **B** — the eight live files lose it, migrator still writes it | 587,425 / 587,207; **59 identical, 9 differ** | the two above **plus all eight** |

Fault A's eight reconstructed inputs were verified by SHA-256 against the
pre-change bytes before the run, so the red is over the real previous file and
not an approximation of it.

**What "clear out the superfluous parts" did NOT mean, stated because the next
reader will be tempted.** Nothing was deleted from `ckf.hardmode.d` and nothing
should be. **17 of the 53 overlay files carry no override in any lever cell**
[re-derived 2026-09-15, `overlay_roles` over the live directory: 53 files, 33
direct and 20 expanded; 3,199 lever cells of which 471 are filled]:

| | |
|---|---|
| the six `consumables-*.csv` | 2,171 lever cells, **0** filled |
| `cyberweapons-claws.csv` | 144, **0** |
| **ten** implant slots — `01`-`07`, `09`, `10`, `11` | 2,468, **0** |

Only three expanded sheets carry an override at all: `cyberweapons-lasers.csv`
(44 of 255), `implants-slot08.csv` (9 of 468) and `gear-classes.csv` (4 of 220).
**An empty lever sheet is not an empty file** — it is the hand-editing surface
this whole change exists to provide (*"editable by hand with the game and the
editor closed"*), the plugin expands it at load, and deleting one destroys the
ability to tune that subsystem. `GUI_EXCLUDED_ROWS`' single withheld row
(`consumables-matrix.csv`, `ItemTypeId 5403`) stays for the same reason its own
comment gives: it is *"STILL IN THE FILE on disk, and still expanded by the
plugin — hidden here, not removed there."*

> Note the count. An earlier relay of this figure said "eight implant slots",
> which lands on 15 rather than 17. It is **ten** — `implants-slot08.csv` is the
> one slot sheet that does carry overrides.

#### The migration block is RETIRED from the default suite — CLOSED, 2026-09-15

**The state to expect: `gui\serve.py --selftest` is `1300 passed, 0 failed, 15
not run`, rc=0** [measured 2026-09-15, container, whole-repo mirror + the live
config, Python 3.11.15]. The 15 are the 3 `--frozen-exe` cases and the **12
named subsections of section 19**, which are now a recorded non-run.

**David's ruling, 2026-09-15, verbatim:**

> "The migration check was only to make sure nothing was lost when building the
> new version here. Players will simply download a new zip and overwrite
> everything, inheriting whatever tuning I've decided upon. They don't need to
> migrate their files and migration is no longer important. Any further
> refactors will share this feature: **Migration for me but not for end
> users.**"

**What the block was.** Section 19 of `selftest()`: 67 cases that convert the
frozen 3.x install in `tests\fixture-3.0.0\` into the 4.0 slice layout and
compare the 68 produced files, byte for byte, against the live 4.0 config the
run was pointed at — plus the fixture's own shape, the `MonsterTypeModel`
partition, two version stamps read out of the C#, five refusals and seven
injected faults.

**What it caught. Two real defects, both of which reached a player-facing
artefact, and this is why it is retired rather than deleted:**

- **the `_version` stamp.** The conversion carried the 3.x document's stamp
  forward, so a migrated install was born reporting all ten slices behind.
  Closed by `MIGRATION_DOC_VERSION`, checked against `Defaults.DocVersion`.
- **the `.cfg` header stamp.** The conversion carried the 3.x header byte for
  byte, so a converted `ckf.hardmode.cfg` announced the version it had been
  converted **from**. Closed by `migration_cfg_stamp_header` and
  `MIGRATION_PLUGIN_VERSION`, checked against `Plugin.PluginVersion`. The full
  record is under "The `.cfg` header stamp — CLOSED, 2026-09-15" above.

**Why its premise lapsed.** The premise is *"a converted install and a fresh
install produce byte-identical files"*. That held only while David's live config
**was** the shipped defaults. It is his tuning bench and he edits it daily, so
every tuning edit to a file the migrator authors puts the block red, permanently
and by design. At **05:41 on 2026-09-15**, before any of that day's work started,
he saved `ckf.hardmode.d\fatigue.json` and
`ckf.hardmode.d\cyberweapons-lasers.csv` in the editor — real tuning, both files
inside 4 ms — and the block read **66 identical, 2 differ** from then on, naming
exactly those two files at exactly his sizes (6,926 / 6,839 live against 6,958 /
6,872 produced).

**And it blocked the release.** `make_release.build` runs
`gui\serve.py --selftest --frozen-exe <exe> --config <snapshot>` as the gate
before it writes any zip, and `if g['failed']: raise Refused(...)`
(`make_release.py`, `run_selftest_gate`) [measured]. So a permanently red
migration block meant **the release could not be cut while David had tuning on
disk** — the exact opposite of what the instrument is for.

**What was done.** `serve.py` grew `--migration`, an opt-in on `--selftest`:

- **default `--selftest`** prints the reason in full at `[19]` and then calls
  `t.skip()` once per named subsection, so all twelve land inline **and** in the
  report tail. Never PASS, never absent. The constants and the reporter are
  `MIGRATION_RETIRED_ON`, `MIGRATION_RETIRED_CASES` and
  `migration_report_retired`, behind a banner that carries the ruling.
- **`--selftest --migration`** runs the whole block **unchanged**. Not one byte
  of section 19 moved: the guard is an early `return t.report(...)` placed where
  section 19 begins, because section 19 is the last thing `selftest()` does.
  That is what makes the opt-in the same check rather than a reconstruction of
  it — and it is checkable: the block's stdout under `--migration` is
  **byte-identical** to the pre-change baseline [measured, `diff`, 2026-09-15].

| | before | default `--selftest` | `--selftest --migration` |
|---|---|---|---|
| `gui\serve.py --selftest` | 1363 passed, **4 failed**, 3 not run, rc=1 | **1300 passed, 0 failed, 15 not run, rc=0** | 1363 passed, 4 failed, 3 not run, rc=1 |
| section 19 | 63 PASS + 4 FAIL | **12 NOT RUN, by name** | 63 PASS + 4 FAIL, byte-identical to before |
| the comparison line | 66 identical, 2 differ | not printed — the block does not run | 66 identical, 2 differ, same two files |

`run_gates.cmd` carries the opt-in as **GATE 08M**, a recorded non-run in the
sweep, and gate 08's stanza states what it no longer covers.

**DO NOT "FIX" THE RED BY DECLARING THE DIVERGENCE.** The two files were **not**
added to `MIGRATION_CLOSED_DIVERGENCES` and that dict is untouched. Be precise
about what it is: it holds **three** entries — the implants-slot tables whose
divergence was **closed** on 2026-09-14 — and it is a **record, not a tolerance
list**. `_mig_diff` filters nothing through it; the selftest asserts the measured
difference set is **empty**. So the set of *tolerated* divergences is empty and
stays empty. That emptiness is what caught the `.cfg` header stamp. An entry
added to buy a green spends exactly the thing that made the instrument worth
keeping.

**What is NOT retired, and must not be removed:** `run_migration`,
`build_migration`, `migration_cfg`, `MIGRATION_DOC_VERSION`,
`MIGRATION_PLUGIN_VERSION`, `MIGRATION_FAULTS` / `_mfault`,
`tests\fixture-3.0.0\` and the `--migrate` CLI path. Migration stays as David's
own tool. Only the default-suite gating went.

**The player-facing consequence, which is the part that matters.** With the
migrator out of a player's upgrade path, `ConfigDoc.BothLayouts` becomes the
thing every upgrader meets: a zip overwrite does not delete files, so a 3.x
player who installs 4.0 keeps their old `ckf.hardmode.json`, both layouts are on
disk, and `Plugin.Load` returns at `Plugin.cs:245` having applied **no rule that
launch** [measured]. It is loud and safe — it names the file and says the game
ran unmodified — but it is a dud first launch. The instruction *delete
`BepInEx\config\ckf.hardmode.json`* is now stated in `release\README.txt.in`
(which ships inside the zip), the repo root `README.md`,
`mods\CKFHardMode\README.md` §3 and `release-notes-4.0.0.md`. **The refusal
itself was not changed** — `specs/config-surface/spec.md` names it as a
requirement.

**One thing left for David.** `ConfigDoc.cs`'s own error text still reads *"THE
MIGRATOR HAS NOT BEEN RUN"* and tells the player to rename the file the way the
migrator would. Under this ruling players are not expected to run a migrator at
all, so that sentence points at a tool that is no longer theirs. It is **C# and
was deliberately not touched** here. Worth a wording pass next time the DLL is
built.

### David's own runs

He has no shell you can drive — `device_bash` is off for this project. Ask him
to run `D:\ckf-data-modding\scripts\run_gates.cmd <phase>` and read
`D:\ckf-data-modding\Logs\gates-phase<N>.txt`. Greppable: `GATE_EXIT NN
rc=<code> <label>` per gate, `GATE_SUMMARY` at the end. Six gates are green at a
non-zero rc and that is correct, not a failure:

| | Gate | rc | Why |
|---|---|---|---|
| 02 | `check_schema.py --config defaults` | SKIPPED | `defaults\` does not exist and will not. **Its successor is gate 09** — see §6 |
| 03 | `validate_rules.py --game` | **2** | refuses without `--dump`. Do not "fix" by dropping the flag; that is what produced `0 rule(s) checked … No problems found.` |
| 03C | `validate_rules.py --enabled-set` | **0 since Phase 9** | was 2 — see §10 |
| 06 | `merge_overlays.py --check` | **1** | no subject. `overlays\` is **not empty** — it holds `README.md`, `_archive\` and seven files under `_reference\`. What it holds is **no `.csv`/`.tsv` at its top level**, and the script does not recurse |
| 07 | `merge_sidecars.py --selftest` | RETIRED | both ends of its subject are gone. Script still on disk, refusing |
| 11 / 11S | `rules_to_overlays.py` | **1** | **RETIRED Phase 9.** Its subject was deleted. It carries the `DECLARED_*` constants and the `DISPOSITIONS` table, which are now **the only written statement of the rule arithmetic** |

`scripts\*` is gitignored, so `run_gates.cmd` is private and yours to extend.

---

## 5. THE DUMP IS NOT A CONSTANT — and the rule that follows

**The dumper omits a column that is constant across all rows, so the dump's
column set is a property of WHEN THE DUMP WAS TAKEN, not of the game tables.**

Between a dump taken from a shallow state and one taken after a real session,
**128 columns moved out of `_dropped_columns.csv` into the tables** —
`_dropped_columns` 1,336 → 1,208 rows, `TalentModel` 53 → 79 columns, `ItemModel`
10 → 13, `EffectModel` 74 → 89, `MatrixEffectModel` → 37. Strict superset. The
newcomers are asset paths (`Vfx`, `IconPng`, `IconAsset`, `EventSFX`,
`AnimationKey`, `Asset3DTypeId`), display strings (`TalentDesc`,
`ManualTalentName`) and runtime instance state (`IsRowCurrentlySelected`,
`OwnerEntityId`, `isInit`, `effectsSet`). [measured, 2026-09-14]

**David has since turned the Data Dump plugin off**, so `sheets\raw\` will not
move under you. That is stabilising, not a fix.

### Never derive a shipped column set from the dump

It bit twice, in two scripts, and the second time only the migrator could see it:

- `consumables.py` derived its columns as "non-blank and non-zero on at least one
  row". Gate 15 went red the first time David ran it — 228 derived columns
  against 165 shipped. Fixed by **declaring**: `SHEET_COLUMNS` +
  `EXCLUDED_COLUMNS`, with the dump as a *check* — the partition
  `live(dump) == SHEET_COLUMNS ∪ EXCLUDED_COLUMNS` is asserted every run and **a
  live column in neither is a loud named problem**.
- `implants.py` had the same shape and nobody noticed for a phase: `columns_for()`
  walked all 89 `dump.eff_cols` with an identity skip and a zero-check, and
  `IMPLANT_TEXT` covered only ImplantModel columns. It now has
  `EFFECT_PRESENTATION`.

**`EXCLUDED_COLUMNS` is keyed `(model, column)`, never by bare name.**
`EffectPurgeType` and `InitBonus` are excluded on `MatrixEffectModel` and are
**shipped levers on `EffectModel`** — a bare-name list deletes two real levers.

**Per David, 2026-09-14: none of the newly-appeared dump columns become levers,
and the `Adjusted*` family (13 of them, not 10) stays out.** Closed; do not
re-open.

---

## 6. What replaced what

| Gone | Replacement |
|---|---|
| `ckf.hardmode.json` | the ten `ckf.hardmode.d\*.json` settings slices |
| `ckf.hardmode.rules.json`, 269 rules | 238 as overlay CSVs, 22 in the two cyberweapon sheets, 9 in `implants-slot08.csv` |
| the unscoped `ImplantModel` rule | `implants-global.json` + `Implants.ExpandGlobal` |
| gate 02 (`--config defaults`) | **gate 09.** `make_release.py --selftest` parses `Defaults.Expected` out of the C# and compares it against the zip and the live directory |
| gate 11 (rule arithmetic) | the 33 overlay files **are** the rules now; `cyberweapons.py --check` and `implants.py --check` hold the 22 and the 9 as declared triples |
| `release\ckf.hardmode.cfg.in`, hand-written, one key | **generated** by `scripts\gen_cfg_template.py` from `schema\*.schema.json`, 43 keys; held current by **gate 16** |

**THE SHIPPED `.cfg` IS GENERATED, AND THE TEMPLATE WAS A 1.0.0 RELIC.**
`release\ckf.hardmode.cfg.in` is not decoration: `make_release.build` renders it
and `snapshot_config` writes the RENDERED TEMPLATE into the snapshot in place of
the live `.cfg`, so it is the file `check_schema` reads when the build checks
the config it is about to ship. It carried 167 bytes and one key,
`[General] Enabled`, written when that was the only key the plugin bound — it is
byte-identical to `tests\fixture-3.0.0\ckf.hardmode.cfg`, the `.cfg` the 1.0.0
release actually shipped, apart from the version string and the line endings
(the template is LF, the fixture CRLF) [measured 2026-09-15]. The layout moved
to 43 keys without it moving, and the first real 4.0.0 build refused:
`check_schema found 42 problem(s) in the config about to ship`, one `MISSING`
per `[Slices]` key.

It is generated now, on David's ruling of 2026-09-15 (`AGENTS.md` §9: no second
copy kept in sync by hand). `scripts\gen_cfg_template.py` is modelled on
`gen_binds.py` and **imports `gen_binds.collect`** rather than re-reading the
schemas its own way, so the C# bind table and the shipped `.cfg` cannot come to
disagree about which keys exist; the plugin name and GUID in the header come out
of `Plugin.cs`; `@VERSION@` survives for `make_release.render` to fill.

**The format was established against BepInEx's own output, not guessed.**
BepInEx rewrote `BepInEx\config\ckf.hardmode.cfg` from the 4.0.0 DLL on
2026-09-15. The generated template, with `@VERSION@` filled and folded to CRLF
the way `render` folds it, is **byte-identical to that file — 3,238 bytes, zero
differing lines** [measured 2026-09-15]. The two sides come from genuinely
different places (schema JSON → this emitter, versus the C# binds the plugin
executed → BepInEx's writer), so that is evidence and not a tautology. It also
says David has no slice switched away from its default.

**Only `Boolean` is emitted.** All 43 cfg keys are `bool` — `gen_binds` requires
exactly one `"in": "cfg"` field per slice and that field is the toggle — so the
live file vouches for the bool rendering and for no other. `bepinex_value()`
**refuses** an int, float or string default rather than guessing how BepInEx
spells it, and says what to measure.

**There are no embedded resources and `Defaults.cs` writes nothing.** Four Phase 9
checkboxes assumed otherwise and were **struck as obsolete per David**. Consequence,
stated rather than implied: **a player who deletes a slice file does not get it
back.** That is 4.0 behaviour as shipped.

---

## 7. The talent class names were wrong, and the `.cfg` keys stay wrong on purpose

**Five of the eleven schema `title` fields named a class the game does not
have.** They were copied from `design.md` §12's class list and nobody ever
checked the list being copied *from*. Settled by join on 2026-09-14 and now
`[measured]`: first column of `ckf.hardmode.d\JobNodeModel.<tag>.csv` is
`JobNodeId` → `sheets\raw\JobNodeModel.csv` on `JobNodeId` → its `JobId` →
`sheets\raw\JobModel.csv` → `JobName`. **Every id matched; no tag resolved to
more than one `JobId`** [re-derived independently for this rewrite].

| was | is | tag | JobId |
|---|---|---|---|
| AEX | **Agent EX** | `aex` | 5 |
| CS | **Cybersword** | `cs` | 3 |
| Sawbones | **Scourge** | `sc` | 15 |
| War Machine | **Warmachine** | `wm` | 2 |
| Wraith | **Wireghost** | `wg` | 19 |

Six were already right: Cyber Knight (`ck`/1), Gunslinger (`gs`/14), Hacker
(`hkr`/13), Sniper (`sn`/11), Soldier (`sol`/7), Vanguard (`vg`/12).

**The pairing was never the bug.** `talentscs.schema.json` recorded it as
`[fitted — positional]`; the order is right at all eleven positions. The list
was wrong, not the mapping.

**THE OLD NAMES SURVIVE IN TWO PLACES AND BOTH ARE DELIBERATE. Do not tidy
them.**

- The five `.cfg` keys — `Slices.TalentsSawbones`, `Slices.TalentsWraith`,
  `Slices.TalentsCS`, `Slices.TalentsAEX`, `Slices.TalentsWarMachine`.
  `check_schema.py --game` asserts **43 keys on disk against 43 declared**;
  renaming a key breaks that in both directions at once and orphans the player's
  saved setting.
- The five schema **filenames** — `talentssawbones.schema.json` now carries the
  title `Scourge Talent Balance`, `talentswraith.schema.json` carries
  `Wireghost Talent Balance`, and so on. The filename is the binding.

**Also `[measured]`: the digit prefix of a `JobNodeId` is not its `JobId`.**
Every `sc` id begins `16`, and JobId 16 is "Attack Hund"; the owner is JobId 15,
Scourge. `JobNodeId 31166` in the `hkr` pack is a Hacker node, JobId 13.

`design.md` §12 carries the full table. Do not duplicate it; cite it.

---

## 8. Which `MonsterTypeModel` to read, and how weapon classes are named

The most load-bearing decision in the change and the easiest to get wrong
silently. `gear-classes.csv`'s ten rows resolve at load as *"class N minus the
`MonsterTypeModel.WeaponTypeId` set"*, and that set must come from the
**post-overlay `ckf.hardmode.d\MonsterTypeModel.csv`** — **405 distinct ids,
class 3 = 33/43** — not the shipped dump (**208**, class 3 = 25/51).

Read the shipped table and you misclassify **eight class-3 player ARs as enemy
gear**. `GearClasses.cs` and the migrator both make the right choice and both
**refuse** rather than falling back.

**The ten classes now draw by name, not as bare ids.** A sixth presentation
table, `ROW_LABEL_SHEETS`, is derived off `gear_classes.SHEET_NAME` and feeds
`ov.rowLabels`: 1 Melee, 2 Pistol, 3 `AR (Assault Rifle)`, 4 Shotgun, 5 E-Rifle,
6 Sniper Rifle, 10 SMG, 11 Revolver, 12 `UAR (Urban Assault Rifle)`, 14 Railgun
[re-derived]. The names come from `sheets\raw\WeaponModel.csv`'s
`WeaponClassName` — **exactly one distinct name per id across 535 rows**.

Two things to know before you go looking for a better source:

- **`sheets\raw\_id_constants.csv` declares NO `WeaponClass` constants at all**
  — zero occurrences of the string [measured]. That route is empty. Recorded so
  nobody searches it a third time.
- **`WeaponClassModModel.csv` disagrees on the spelling of three of the ten** —
  it says `Assault Rifle` for 3, `Energy Rifle` for 5 and `Bullpup Assault` for
  12, where `WeaponModel` says `AR (Assault Rifle)`, `E-Rifle` and
  `UAR (Urban Assault Rifle)`. `WeaponModel`'s spelling is what ships, because
  it is what a player sees in the game.

---

## 9. Tooling hazards that have cost real work

**A same-path `device_commit_files` re-commit has three times returned
`{"written":[...],"rejected":[]}` and left the OLD bytes on disk** — once
destroying another agent's work. Mitigation, used for every write in Phases 4-10:
stage under a **distinct local filename**, commit with an `expectedMtimeMs`
guard, then **re-stage and hash the file off disk**. Every commit in Phases 8-10
was verified this way; none failed.

**`/mnt/user-data/uploads/` is an accreting snapshot, not a mirror.** A file
staged early persists after it is deleted on the real machine, and a file
rewritten on the real machine does not refresh until you re-stage it. Two audit
subagents once reported a file present that was not. **`device_list_dir` on the
live path is the authority, and you re-stage every file immediately before you
read it.** The reverse also happens: a subagent reported
`ckf.hardmode.rules.json` deleted when it was not, and a user report of the same
was also wrong — the cause was `ModelRules.LoadRules` re-creating it (see §10).

**`serve.py --selftest`'s `copytree` races the file-staging layer.** Two agents
lost runs to `FileNotFoundError` / `shutil.Error` on `.stage-tmp.*` scratch files
because they pointed `--config` straight at a path under `/mnt/user-data/uploads`.
**Copy the stage to a quiesced local mirror first** and point every gate at the
mirror. This applies to the repo as well as the config.

**`serve.py --selftest --config` takes the config DIRECTORY, not a file.**
Passing `<copy>\ckf.hardmode.cfg` dies in `_sandbox` with `NotADirectoryError`
at `serve.py:5509`. One agent lost a run to it. The same family of mistake:
`validate_rules.py --game` wants the game root, not the config directory.

**Line endings: no repo-wide convention — measure per file.** **23 `.cs` files:
3 CRLF** (`ConfigDoc.cs`, `Defaults.cs`, `Plugin.cs`) **and 20 LF**, plus a CRLF
csproj. `run_gates.cmd` is CRLF. The 43 schema JSONs, every CSV, and every
document in `docs\` and `openspec\` are LF. BepInEx writes CRLF. Do not
normalise a file you are only editing.

**A marker scrape that takes the FIRST occurrence is a green over nothing.**
`cyberweapons.py`'s P-MAP uses `src.find('END LEVER MAP')` and survives only
because `Cyberweapons.cs` happens to wrap the phrase in prose. **`Implants.cs`
carries `BEGIN LEVER MAP` once and `END LEVER MAP` three times** — a `find()`
based scrape of it would close on the first and be green over nothing, a live
trap for whoever adds an implants map check. `consumables.py` requires **exactly
one** occurrence and refuses on 0 or 2+. Copy that, not `find()`.

**`Cyberweapons.cs` byte 12606 is a literal NUL** inside the string in `KeyOf` —
an actual `0x00`, not the escape. `grep` calls the file binary because of it. Any
reader must decode through it. Recorded, not fixed.

**Do not redirect stdout on the `openspec` CLI.** It may be interactive.

---

## 10. Instruments known to be dark, newly armed, or mis-attributed

- **`make_release.py --selftest` was green through the build that refused.**
  Its `.cfg` case read *"the master switch renders with its version, its section
  and its key"* and asserted the header, `[General]`, `Enabled = true` and CRLF —
  every one of them true of a 167-byte stub with no `[Slices]` section at all. A
  true assertion standing in for a claim four times its size. **Two cases were
  added on 2026-09-15** and both go red on the old stub [measured]: *"the
  rendered `.cfg` carries a `[Slices]` section, not just the master switch"*
  (counted, not named — the number of slices is declared in `schema\` and a copy
  of it here would be the next thing to go stale) and *"`release\ckf.hardmode.cfg.in`
  is what the schemas say it should be"*, which runs `gen_cfg_template.main(['--check'])`.
  The old case is widened and kept rather than replaced, because it is the
  record of the shape of the failure.
- **The byte-identity check is NOT `make_release.py --selftest`.** That script
  contains no comparison of built bytes against disk bytes; it has 114 cases
  (112 before 2026-09-15) and none of them is one. The only instrument in the repository that compares
  **BUILT BYTES against DISK BYTES** is the migration block of
  `gui\serve.py --selftest` (the comparison loop at `serve.py:11752`), and
  `serve.py:4268` says so in its own voice: *"Nothing else in the repository
  compares BUILT BYTES against DISK BYTES."* Earlier revisions of this file and
  of `tasks.md` Phase 10 credited `make_release.py`; they were wrong. It is what
  found the `implants.py` column bug, so mis-attributing it means mis-aiming the
  next investigation.
- **`ModelRules.LoadRules` used to re-create `ckf.hardmode.rules.json`** if it was
  absent, at Info, into the directory just cleared. Commented out in Phase 9 with
  the four lines quoted. **This is why earlier deletion attempts did not stick.**
- **`implants.py`'s old P-CHECK appended differences to `out`, never to
  `problems`** — a real divergence printed `DIFFERS …` and exited 0. That path no
  longer runs; P-GONE replaces it and raises properly.
- **`validate_rules.py` now has `load_consumable_sheet()`** — the Phase 9
  leftover, closed. It expands one `consumables-*.csv` the way `Consumables.Expand`
  does at load (one sheet row into up to four rules: `ItemModel` on `ItemTypeId`,
  `TalentModel` on `TalentId`, `EffectModel` on `EffectId`, `MatrixEffectModel`
  on `MatrixEffectId`), so the six sheets enter the pointer graph. It **imports**
  `consumables.py`'s `SHEET_COLUMNS` / `EXCLUDED_PAIRS` / `IDENTITY` / `KEY_OF` /
  `parse_sheet` rather than restating them, and lists the directory rather than
  iterating declared names. Its **C-COL half is the part that could not wait**:
  all six sheets ship every lever cell blank, so they emit zero rules, so
  `check()`'s per-rule "unknown column" warning would never fire — a lever aimed
  at a column the game lacks would stay green until a player typed a number into
  it. It deliberately does **not** assert row counts, the join, effect
  resolution, the live column partition (A-PART), the plugin's lever-map
  transcription (P-MAP), shipped values or line endings; those are
  `consumables.py --check`'s and they are green.
- **`--check` in the retired `rules_to_overlays.py` could not see a stray overlay
  file**: it iterated declared files and never listed the directory. `consumables.py`
  lists the directory; if you write a new converter, do that.
- **`serve.py`'s `PRESENTATION TABLES` header says four and there are six.** The
  block at `serve.py:204-211` reads "These four tables are the declared
  exceptions" and "Nothing else in this file names a subsystem, a field or a
  column." `COST_LABELS` (`serve.py:1492`) was already a fifth and
  `ROW_LABEL_SHEETS` (`serve.py:1573`) is a sixth. Both are **derived** rather
  than typed, so the header's count of *literals* is still true — but an agent
  reading it finds six things and four claimed. Also live in the same file and
  not yet fixed: `overlay_labels` writes the literal `out['Cost']` about a
  thousand lines below that sentence.

---

## 11. Open items with no owner

- **`ov.notes` is 76% of every word on screen, and it is a generator-side
  problem.** The `uiDoc` channel was never the culprit: all 43 schemas report
  `docSource: "uiDoc"` and only ~8.7k chars of schema prose reach the panel.
  `ov.notes` is **517 strings, 98,113 chars** [re-derived, off `read_overlays`
  against the live config]. They are per column **pair**, so they grow
  quadratically — `EffectModel.sol.csv` alone ships **81**, each the same
  sentence with two names substituted. The GUI side is done (a `<details>`
  disclosure took the full-page render from 135,921 chars / 886 lines to
  28,801 / 358 with every note still in `textContent`), but **the fix is in the
  generator**: emit one note per *column* listing its exclusive partners and 517
  lines become perhaps 60 without losing a fact. Nobody owns this.
- **`mods\CKFHardMode\Consumables.cs` lines 196-202 tell a reader a real gate
  does not exist.** They say "scripts/consumables.py has its own marker pair but
  NO `check_map_matches_plugin()` … NOTHING COMPARES THIS TABLE TO ANYTHING."
  Both halves are out of date: `consumables.py:2710` defines
  `check_map_matches_plugin`, it uses the exactly-one-marker rule, and it is in
  `ALL_CHECKS` as `map` [measured]. `mods\` was out of scope for the docs sweep.
- **`gui\app.html`'s suppression comment does not add up.** The block at
  `app.html:518-551` says what survives the three exceptions is "a non-editable
  column holding one value on every row (**16** of them, **9** of which hold
  nothing at all)" plus 3 editable, and then correctly concludes "**Ten columns
  in the shipped config.**" The measured answer is **8 non-editable — all 8 of
  them blank — plus 2 editable**, which is where the ten comes from. 16 and 9
  are the counts **before** exceptions 1 and 2 are applied. The code is right;
  its own comment is not.
- **Three status blocks in `specs\lever-sheets\spec.md` are stale.** See §13.
- **A refused save discards every pending edit.** The `#save` handler calls
  `await load()` unconditionally after `/api/save` (`app.html:2896`), which
  rebuilds `W` and drops all pending cfg, sidecar and lever-cell edits. Lever
  cells are partly protected — bad cells are marked before Save, and `Validate`
  does not reload — but the wart affects every control on the page. Pre-existing,
  not fixed.
- **`.navitem` is a `div` with an `onclick` and no `tabindex` / `role`** — not
  keyboard reachable. Predates the sidebar rework. The new `<summary>` and the
  gate checkboxes are natively focusable, so the fold works from the keyboard
  but the row it sits in does not.
- **`overlays\_reference\player-vs-enemy-gear.md` is stale.** Written against the
  508-row dump, it misses 48 player rows, and its 16 range pairs should be
  **deleted outright, not regenerated** — it is the document the drifted
  hand-maintained list was copied from.
- **`gear_classes.py` declares no `SHEET_NAMES`**, so its sheet is classified by
  derivation rather than declaration.
- **`rules_to_overlays.py`'s retirement banner cites the fixture at a container
  path.** It is at `tests\fixture-3.0.0\`.

---

## 12. The four deviations the conversion applied — and why they are not a rule

| | What moves |
|---|---|
| **D1** | `MonsterTypeModel` PL 11+ rule deleted — 1,180 rows, 2,360 values revert |
| **D2** | ×1.8 `RecoilRate2` stops on 30 drone weapons, ids `26000`-`26029` |
| **D3** | `implantStressClampMin` removed — binds on 0 of 198 rows |
| **D4** | Ten player ARs gain ×1.8 `RecoilRate2` — ids 17, 1001, 1005, 1014-1016, 1018-1021 |

**All four are applied *during* conversion, not after it.** Two are deletions with
no expander to reuse, so a migrator written to "preserve every operand" silently
reconstructs D1 and reintroduces D3. The migrator's fault cases cover both.
**The migrator is unchanged and stays that way** — it is David's own tool, it
works, and these four are how the files on disk were produced.

**This section used to open "Exactly four. A fifth is not yours to add — that
is a stop-and-ask." That rule is WITHDRAWN.** David's ruling, 2026-09-15,
verbatim:

> "Stop considering deviation from the 3.0 ruleset a mistake. Remove all
> consideration that this is a problem."

> "Undoing a balance change should have no problems, no? If the eye laser
> special rules ship as-is, that can't possibly be a problem."

`ckf.hardmode.d\` is a **tuning bench**. Editing a lever cell — or clearing an
override so the column reverts to what the game ships — is the tool working.
D1–D4 above are the record of what the *conversion* did. They are not a list of
the only changes permitted since, and nothing may be added to them to buy a
green.

**What this cost, measured.** Four `--check` instruments enforced the old rule
against the live sheets, so from the first tuning edit they produced a problem
per edited cell. On 2026-09-15 David cleared `SpecialRule` on all 16 rows of
`cyberweapons-lasers.csv`; `cyberweapons.py --check` went to **32 problems,
rc=1** — 16 `P-GONE` and 16 `UNDECLARED CHANGE` [measured 2026-09-15]. All four
are now **recorded non-runs**: still on disk, still runnable, and each says by
name on every default run that it is not running.

| where | what is retired | flag that runs it |
|---|---|---|
| `gui\serve.py` | section 19, migration byte-identity, 67 cases / 12 named subsections | `--migration` |
| `scripts\cyberweapons.py` | `P-GONE`, `UNDECLARED CHANGE`, + 8 selftest cases | `--ruleset-3x` |
| `scripts\implants.py` | `P-GONE`, + 3 selftest cases (C4, F9, F10) | `--ruleset-3x` |
| `scripts\gear_classes.py` | `UNDECLARED CHANGE`, the `OLD_RECOIL_RANGES` old side, + 4 selftest cases | `--ruleset-3x` |

`scripts\consumables.py` was examined and carries **nothing of this class** —
its `DECLARED_LAST_RULES_MEASUREMENT` is a record asserted against nothing, and
`A-LIVE`/`A-DROP`/`A-DUMP` ask live questions about overlay collisions, not
about the 3.0 ruleset. `scripts\rules_to_overlays.py` was already retired at
rc=1; its retirement text used to name `cyberweapons.py --check` and
`implants.py --check` P-GONE as "what replaced each half of this gate" and now
carries a visible correction saying nothing checks those two halves any more.

**One real loss of coverage, stated rather than glossed.** `gear_classes.py`
selftest **F4** — "the wrong pointer set" — is retired *whole*, not split. It
was first written as a split on the assumption that the live half caught the
fault by itself; the measurement says otherwise. F4 feeds the shipped-like
pointer set to the expander *and* to the partition, so `partition()` grades the
mistake against itself and returns **0 problems**; `compare()` was its only
detector [measured 2026-09-15]. Closing it needs a new live check, not a
resurrected comparison. **F5** — a holed set graded against the TRUE set — does
not have this shape and still runs.

The durable statement of all this is **`AGENTS.md` §6b**, which binds future
agents whether or not they read this file.

---

## 13. What Phase 10 is, and what is genuinely unverified

**Release 4.0.0.** `tasks.md` Phase 10 is the list. What is already true:

- `make_release.py` is rewritten and **its selftest can actually fail** —
  `CONFIG_FILES` is 15 required names with the `ckf.hardmode.d\` sweep behind it,
  and `config_sources` ships **68 files, 0 skipped**. It reads `Defaults.Expected`
  out of the C# rather than from its own constant. It is **not** the
  byte-identity check — see §10.
- `NOT_SHIPPED_BUT_EXPECTED` is declared and **empty**. Leave it declared: an
  empty tuple says there is no deliberate disagreement today, which is a different
  statement from the constant not existing.
- **The version bump touches `Plugin.PluginVersion` and `<Version>` in the csproj
  together** (`AGENTS.md` §9), and `Defaults.DocVersion` and the ten live slices'
  `_version` move with them. **All four are at 4.0.0 as of 2026-09-15.**
  **Corrected 2026-09-15:** this bullet used to end *"`Defaults.DocVersion` and
  the live documents' `_version` move together, and only when the document's
  shape does — it did not."* The per-file shapes indeed did not move — measured
  against each slice's section in `tests\fixture-3.0.0\ckf.hardmode.json`, all
  nine that existed in 3.x carry the same payload keys (`difficulty` 1, `elapse`
  6, `fatigue` 6, `missions` 2, `modelrules` 5, `powerlevel` 5, `rewardcurve` 3,
  `selfcheck` 3, `teampl` 3) and differ only by the `_version` each slice file
  now carries in its own right, which the 3.x sections did not have
  [measured 2026-09-15]. **David ruled on 2026-09-15 that all four move anyway**:
  he reads "document shape" as the LAYOUT — one merged document becoming 67 files
  behind per-slice toggles — not the per-file schema. `tasks.md` Phase 10's
  premise stands; this bullet was the wrong one.
  **Amended 2026-09-15:** the version bump touches a FOURTH place now —
  `MIGRATION_PLUGIN_VERSION` in `gui\serve.py`, the version the migrator stamps
  into the `.cfg` header. It is a separate stamp from `MIGRATION_DOC_VERSION`:
  that one is `Defaults.DocVersion` (the slice `_version`), this one is
  `Plugin.PluginVersion` (what BepInEx writes into the `.cfg` header). Section
  19c has a case for each, both reading the C# rather than each other. **Bump
  all five together**, and `serve.py --selftest` will name whichever you missed.
- **The stamp is a THREE-sided coupling, not two** [measured 2026-09-15].
  `Defaults.DocVersion`, the ten live `_version` strings, and
  `MIGRATION_DOC_VERSION` in `gui\serve.py`. The third side was
  `version = doc['_version']` in `run_migration`: the converter stamped the 4.0
  layout it wrote with the stamp of the 3.x document it read, which was
  invisible while both were "1.0.0". Moving the first two alone left
  `serve.py --selftest` red at **1359 passed, 3 failed** with the migration
  block reporting *"58 identical, 10 differ"*. It is a declared constant now,
  checked against the C# by a case in section 19c. **Note which instrument sees
  what:** moving `Defaults.DocVersion` alone does NOT move the byte-identity
  check — that run stayed at **1362 passed, 0 failed, 68 of 68** — because
  neither side of that comparison reads the C#. The instrument that catches a
  `DocVersion`-vs-disk disagreement is `make_release.py`'s `check_doc_version`
  (**111 passed, 1 failed**, naming all ten slices).
- **A release build writes `dist\CKF-Hard-Mode-<version>.zip`** — the name is
  `'CKF-Hard-Mode-%s.zip' % version`, and `version` is `check_versions()`, which
  returns the csproj `<Version>` only after it equals `Plugin.cs`
  `PluginVersion` AND appears in the built DLL's metadata blob. A build made
  before the version bump therefore refuses and writes nothing.
  **Old release zips in `dist\` are not protected and do not need to be**
  (David, 2026-09-15): `write_zip` overwrites an existing path, superseded
  builds are disposable, and no instrument depends on one. **Corrected
  2026-09-15:** this bullet used to call `dist\CKF-Hard-Mode-1.0.0.zip` "the
  only surviving copy of a 3.x install" and told you to check what a build would
  overwrite before running it. `tests\fixture-3.0.0\` was extracted from that
  zip and is the migrator's input — see the next bullet — but the zip itself is
  no longer something to work around.
- **`tests\fixture-3.0.0\` is the migrator's only input, and it is not in git**
  — `.gitignore` is an allowlist that never admits it and the tuning lives
  outside the repo (`AGENTS.md` §9). It is what the byte-identity check converts
  from, so it is a live test input rather than an archived build: delete it and
  the one instrument that compares BUILT BYTES to DISK BYTES has no subject.
- **The `.cfg` the zip carries is generated and the build gets past
  `check_config` now** [measured 2026-09-15]. The refusal David hit was
  reproduced over a snapshot built with `snapshot_config` from the live config
  (42 `MISSING` problems, the exact list) and is green over the same snapshot
  with the generated template (`check_doc_version` 4.0.0, `check_json` ok,
  `check_config` passed, `check_schema --config <snap>` 0 problems / 43 keys /
  43 declared). **Corrected 2026-09-15:** this bullet used to end *"The build
  then refuses at the gate for the unrelated, pre-existing migration-header
  failure in §4 — that is the next thing to settle, and it needs a ruling."*
  It was settled the same day. David ruled, `migration_cfg` stamps the header
  with `MIGRATION_PLUGIN_VERSION`, and `serve.py --selftest` read **1367
  passed, 0 failed, 3 not run** — so the gate stopped refusing over the header.
  It reads **1300 passed, 0 failed, 15 not run** today: later that same day
  David's tuning put the migration block red again and the block was retired
  from the default suite. See §4, *The `.cfg` header stamp — CLOSED* and *The
  migration block is RETIRED from the default suite*. **The build itself is still unrun**: it needs the
  editor exe, and there is no dotnet, no PyInstaller and no Windows in the
  container.
- **No full build has been run.** No `dotnet build`, no PyInstaller, no
  `make_release.py` without `--selftest`: there is no dotnet and no Windows in
  the container and the build needs the editor exe. Everything above is the
  selftest path and a hand-built snapshot.
- **`design.md` §12 proposed `levers` and `slotTable` `ui` kinds. They still do
  not exist and no phase builds them.** `serve.py`'s selftest asserts the kind
  set is exactly `form, table, curve, matrix, readonly, hidden`
  (`serve.py:6206`, and `UI_VALUES` at `:12119`). **This did not change when the
  write path landed**: lever cells are edited through the ordinary `table`
  renderer with a server-supplied `editable` flag, not through a new kind. Do
  not hunt for them.

### Nobody has ever seen this in a browser

**The GUI has never been launched against a running game**, and every check in
this document is node plus `serve.py`'s DOM stub, which has no CSS. **The sidebar
fold, the `::placeholder` "ships N" text, the dirty marking, the `opacity:.62` on
a restored column and every CSS number are asserted to be present in the DOM and
have never been seen rendered.**

**Correction, 2026-09-14.** This block used to add "and it was not opened in a
browser on 2026-09-14 either". **It was.** David opened the config editor in a
browser on 2026-09-14 and three changes came directly out of what he saw: the
one-row form was reversed (`design.md` §7), the three gate controls were merged
into one, and the five metadata columns were hidden. He reports that the new
content renders but is not yet good quality. Nothing else has been seen rendered,
and no agent has seen any of it.

The Phase 10 checkbox "Exercise the nav grouping and the six `ui` kinds that
exist, in a browser" is still open **and is now the check that matters most**,
because the write path, the suppression rule, the row labels and the sidebar
rework all changed what that browser will show.

### The spec's stale blocks

Three narrative "Status" blocks in
`openspec\changes\split-config-into-toggleable-slices\specs\lever-sheets\spec.md`
describe a world that ended in Phase 8 or Phase 9. **The normative requirement
and scenario text is fine; only the interleaved status prose is stale.** They
were left for a decision rather than edited, because changing a spec clause is
not a docs-sweep call:

1. The `Status, 2026-09-14` block under *Crit damage removal is edited where the
   implant lives* still says `ckf.hardmode.rules.json` carries nine matching
   rules and that `Implants.cs` "emits nothing from `implants-global.json` …
   (`Implants.RefuseGlobal`, `Implants.cs:637-642`)". The rules file is gone and
   the method is `Implants.ExpandGlobal`.
2. The block under *Consumables are one table per item class* says
   "**Unshipped, 2026-09-14. Nothing under this requirement is built** … Phase 8
   has not started" and that the directory "holds 61 files — 50 CSV and 11 JSON
   — and **zero** of them is a `consumables-*.csv`". Phase 8 shipped; there are
   six of them and the directory holds 67 files, 56 CSV and 11 JSON.
3. The same block's warning not to bind a 44th key is still correct and should
   survive whatever happens to the rest of it.

**Stop and ask David when:** a gate fails in a way implying a design decision was
wrong; a shipped value would change as a side effect *inside the plugin or the
migrator*; anything needs his machine.

**No longer on that list, 2026-09-15** (his ruling; §12 and `AGENTS.md` §6b):
*"a conversion cannot be byte-identical"* — the migration byte-identity block is
retired and the live config is a tuning bench, so it cannot be byte-identical
and that is expected. *"You think a fifth deviation is needed"* — a fifth is no
longer a stop-and-ask, and a value on a lever sheet moving is tuning, not a
design decision. Both lines are kept here rather than deleted because an agent
who read an older copy of this file will be looking for them.

---

## 14. How the last two leads worked, and the error rate

The brief is **direct and verify, do not write it all yourself.** Good units: one
converter, one expander, one schema-plus-wiring, one docs sweep. **Bad units:
anything spanning the C# plugin and `serve.py` at once**, or anything whose
correctness only shows up in a gate you are not running.

It works, and it produces a real error rate. The errors cluster in one place:
**relaying a claim without re-deriving it** — in both directions. A subagent said
a file was on the live disk when it was not; another said one was missing when it
was staged-only; a user report of a deletion was wrong because something was
re-creating the file; five class names were copied out of a planning document
nobody had checked. **Check the live path. Re-run the measurement. Every time.**

Subagents pushed back correctly and repeatedly: on a five-name required set that
should have been fifteen, on a column count, on an instruction that could not be
satisfied as written. **When one pushes back with a measurement, it is usually
right** — on 2026-09-14 every one of six agents found something wrong in its own
brief, and every one of them was right. Three times a subagent caught its own
dark instrument mid-task and said so unprompted; that is the behaviour to ask
for explicitly, because it is what found most of the defects in Phases 8-10.

Nothing was ever caught by anyone remembering correctly. **The documents and the
gates are the memory; you are not.**
