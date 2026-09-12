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
field; `--check` verifies without rewriting), `gen_docs.py`,
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
| `targets` | Which files this subsystem writes. `json` is `ckf.hardmode.json` for every subsystem that has settings; `section` is its top-level key in it; `legacyJson` is the 2.x sidecar it came from, or an explicit `null` for the four sections created in 3.0. `cfg` appears on `general.schema.json` alone — after Phase 3 that is the only subsystem with a key in `ckf.hardmode.cfg`. |
| `enable` | The AND-chain, outermost first. Since 3.0 there is one link for every subsystem: `json`, the section's own `enabled`, read after the document loads. `cfg` survives on `general.schema.json`, the master switch. A field may add a level below with `enabledBy`. |
| `invariants` | Cross-file rules. See below. |

**Changed in 3.0: `targets` and `enable`.** Both used to name `ckf.hardmode.cfg`
on all ten schemas, because 21 settings lived there. Phase 3 moved them into the
merged document, so a schema that still declares `"cfg"` in `targets` and is not
`general.schema.json` is stale rather than valid: `gen_binds.py` would emit a
BepInEx bind for its keys, and BepInEx would write them back into a file nothing
reads.

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
  "keys": ["ckf.hardmode.json#powerlevel.minCap",
           "ckf.hardmode.json#powerlevel.maxCap"],
  "reason": "maxCap below minCap leaves nothing to clamp into; PowerLevelCap.Init logs an error and installs no hook."
}
```

Each key must be less than or equal to the one after it. Skipped silently if any
key is absent or non-numeric — the `MISSING` and `RANGE` checks own those.

**How an invariant names a key.** Two spellings, both accepted by
`check_schema.py`'s `inv_value`: `Section.Key` is a cfg key, and
`<file>#<dotted path>` is a path inside a config document — the notation
`mirror` has always used for its `source` and `target`. Phase 3 moved both
`ordered` and `linkedEnable` from the first to the second, because the keys they
name moved.

### `linkedEnable` — flags that must move together

```json
{
  "kind": "linkedEnable",
  "keys": ["ckf.hardmode.json#teampl.enabled",
           "ckf.hardmode.json#modelrules.enabled"],
  "reason": "Progression alone gives a correct award with a stock label; ModelRules alone gives a stock award with a lying label. Neither direction logs anything."
}
```

---

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
4. **Broken invariant** — a `mirror` whose two sides disagree, or a
   `linkedEnable` group that is half on.
