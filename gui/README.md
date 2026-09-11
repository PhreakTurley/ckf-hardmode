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

`--selftest` copies its fixtures from `--config` if you name one, else from
`<repo>/live-config` if that exists (a cloud session assembles one by staging
the game's config beside the checkout), else from the game config
`settings.json` already points at. It only ever READS that directory. If none
of the three resolves it says so and names what it looked for — until
2026-09-04 it took `<repo>/live-config` unconditionally and died on a
`FileNotFoundError` out of `copytree` on any machine without one.

It binds **a free port on 127.0.0.1** — no fixed port, no other interface — and
opens a browser at it. **It edits the live `BepInEx/config/` files in place**:
`ckf.hardmode.json`, the one key left in the `.cfg`, and the generated mirror.
There is no staging copy
you review afterwards; a save writes to the game's own config directory. The
first save of a session takes a backup (below).

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

The directory is editable in the header and remembered in `settings.json`. That path is
normally under Program Files, so on startup the tool probes it for write access
by creating and deleting a file — `ok`, `denied` with the OS error, `missing`,
or `error`. A denied probe shows in a banner; a save that hits a permission
error is refused with the error text, never swallowed.

Procedure: `../docs/workflow.md`. Per-key reference:
`../docs/config-reference.md`. Traps: `../docs/gotchas.md`.

`--run-check-schema` is not for people. It runs `schema/check_schema.py` in
this process and exits with its code, and it is how the frozen exe validates a
save — see "Freezing it" below.

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
over the real exe when `--frozen-exe` names one. **Without `--frozen-exe` the
two exe cases are reported NOT RUN, with the reason** — they are not counted as
passes.

---

## What it owns

Every file the schemas declare as a `target` — `ckf.hardmode.json`, whose nine
sections are every setting the mod has, and `ckf.hardmode.cfg`, which since 3.0
holds one key — plus `ckf.hardmode.d/MissionPowerLevelModel.generated.json`,
regenerated whenever `teampl.override` is saved, in the same transaction. Which
keys live in each is `../docs/config-reference.md`'s business.

**The `.cfg` half is one value line.** `[General] Enabled` stays a BepInEx bind
because it is the switch that has to work when `ckf.hardmode.json` does not
exist at all, and this tool replaces its value line and does nothing else to
that file. The append-a-missing-key path went with the other 21 keys, and so did
the two round-trip refusals it needed — a value starting with `#` reading back
as a comment, and a value carrying a line break leaving a stray line — because
neither can be reached by a bool. A key the file does not carry is refused
rather than created: BepInEx writes that file from the keys the plugin binds,
and a line this tool appended would be one the plugin does not read.

**The `.cfg` is edited line by line.** Value lines are replaced in place; a
declared key that is absent gets a bare `Key = Value` appended under the right
section header. **No comment is ever written** — BepInEx owns those. Line
endings are held **per line**: an edited line keeps the ending it had, and an
unedited file round-trips byte for byte. Sidecars are written as strict JSON;
the `_readme` block is removed under the `stripReadme` setting, so the behaviour
is inspectable rather than silent.

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
Row identity in the grids is positional, so writing against a stale read could
reattach preserved unknown keys to the wrong row and nothing downstream would
notice.

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

Three refusals sit outside those classes: an **unparseable adjustment** (the
plugin logs and ignores it — a silent no-op); **type errors**; and **a cfg value
that would not survive the round trip** (a leading `#` reads back as a comment;
an embedded line break leaves a stray line). All three raise `SaveRefused`,
never `assert` — `assert` vanishes under `python -O`.

---

## Rendering: schema in, controls out

`app.html` contains **no schema field path, column name, cfg key, section name
or filename** — only the `ui` values, which are the dispatch itself; `--selftest`
asserts this (`hardcoded_names_in_app_html`).

The `ui` values are defined in `../schema/SCHEMA-FORMAT.md`, §`ui`. Two carry
dispatch specific to this tool: **`matrix`** is laid over the field named by its
`over`, and **`readonly`** is drawn as a matrix on the axes of the field that
declares it as its `over` underlay when there is one — so a reference table and
the control it backs are the same grid — otherwise as a plain grid. A schema
field the section does not have yet gets an empty grid, and saving it empty does
*not* invent a `{}` on disk.

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
already used — because both keys in the one group that exists moved out of the
`.cfg`. `app.html` resolves them against the units the model carries rather than
by splitting on a dot, so a path containing dots cannot be mis-parsed. **Every
save returns a relaunch reminder** — each subsystem reads its config once in
`Plugin.Load()`.

### Layout: where a field lives, and how wide a column gets

**A field's location is one identifying part per line**, outermost first: the
file, the section inside it, then each step of the key path. `pathParts` in
`app.html` splits on the separators the server already keys by — `#` between
file and section, `.` between the steps of a path — and `pathCode` gives each
part its own `<span>`. It still names nothing: the parts come from the schema's
`targets`. The single arrow-joined line it replaced is asserted gone
(`no location is still one arrow-joined line`).

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

## Presentation: the three declared names

Order and grouping are in no schema, so they are written down **once, in
`serve.py`, under `PRESENTATION TABLES`**, with the reason beside each. All
three are display only: nothing they do changes what is read or written.

| Table | What it says | Why it cannot be derived |
|---|---|---|
| `SECTION_GROUPS` | `Progression` + `RewardCurve` present as one section, *What a mission pays* | Two subsystems, two files, two cfg keys, one question. Nothing in either schema points at the other. |
| `SECTION_LAST` | `SelfCheck` goes last | It is a verification tool, off by default and deliberately so. No schema key says "this one is a diagnostic". |
| `AXIS_WINDOWS` | the Team PL matrix draws `MissionPowerLevel` 1–10 | The game's table runs −10…10; the negative band is unexplained and PL 0 is worth nothing, so 33 of the 63 cells crowd out the 30 anyone edits. |

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

---

## Prose: what is stripped

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
would leave a sentence with no subject. `--selftest` runs the strip over all 56
field docs and asserts nothing came out but those two patterns, that no doc was
emptied, and that no brackets came out unbalanced.

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

`python3 gui/serve.py --selftest` — **285 checks**, or **301** with
`--frozen-exe`, everything written inside a temp directory, the source config
copied and never touched. It covers the
adjustment grammar against `MissionRewards.Adjust.Parse`, schema-field coverage,
both round-trip directions, unset-vs-zero, both table shapes, the mirror, the
four validation classes, backups, the cfg's line-level fidelity **including a
file whose line endings are mixed**, **an out-of-range save attempted repeatedly
with four threads calling `/api/model`**, the journal, the stale-read guard and
the HTTP guards. `app.html`'s pure functions run under `node` from the region
between the `/*==CKF-PURE-BEGIN==*/` sentinels — keep anything touching the DOM
or the network outside them.

**And the page is rendered, not just parsed.** `--selftest` runs `node --check`
over both `<script>` blocks, builds a DOM small enough to live in `serve.py`,
drops app.html's own two blocks on top with `fetch` stubbed to return a real
model read from a real config directory, and asserts against the resulting tree:
section order, the grouped section, the reference table in the last card, the
two Team PL grids carrying identical headers and rows, every reference cell
disabled, one checkbox standing for both gates, and no `∅` on an adjustment
cell. It runs twice — over the live config, and over one carrying an override in
a hidden column.

It also covers the frozen build: both shapes of the `check_schema` child argv,
the `--run-check-schema` dispatch as a real subprocess, and three broken child
processes — one that exits nonzero after printing a clean summary, one that
prints a problem line and no summary, one whose count disagrees with its lines
— each of which must read as could-not-run and block a save that is otherwise
accepted. With `--frozen-exe` the same runs against the exe, which then also
has to serve `app.html`, answer `/api/model` with a complete validator result,
read `docs/mission-reference.json` out of its bundle, and write its settings
beside itself rather than into a bundle that is deleted on exit.

**Not verified: how any of it looks.** No control has been clicked, no grid
drawn, no point dragged, no layout seen, here or in any headless session.

**Not verified on Linux: the Windows exe.** `--frozen-exe` was exercised against
a PyInstaller build made in the cloud container, which is an ELF. It proves the
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
