#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""implants.py -- the eleven implant slot tables: generate, check, selftest.

WHY THIS SCRIPT EXISTS

split-config-into-toggleable-slices turns ImplantModel into eleven per-slot
lever sheets plus one global block.  This script is the repo-side half: it
GENERATES the eleven CSVs from the dump, CHECKS the sheets against the dump
and the plugin's column map, and (under --ruleset-3x) compares what the sheets
compile to against the 3.x rules they replaced.  mods/CKFHardMode/Implants.cs is the runtime half; the two
transcribe one column map and check_map_matches_plugin() refuses if they differ.

THE THREE THINGS IT IS CAREFUL ABOUT

1. A COLUMN BEING CONSTANT SAYS NOTHING ABOUT WHETHER A RULE WRITES IT.
   SpecialRule and ApCost are constant on the laser rows in the dump and are
   still levers (see cyberweapons.py).  Here the same trap is ImplantStress: it
   is 1 on 197 of 198 rows, so it is constant inside every slot, and the global
   multiplier (implants-global.json) scales it.  P-DROP below checks EVERY
   dropped column against the live writers and fails on a column one writes.

2. A BASELINE BUILT FROM THE NEW SIDE'S COLUMN MAP AGREES ABOUT WHAT IT CANNOT
   SEE: a --check whose shipped baseline comes from the sheets' own headers
   compares clean over a dropped column.  The baseline here is
   the union of every column EITHER side touches, read from the dump, and a
   triple with no readable shipped value is NAMED, not skipped.

3. AN INSTRUMENT'S SILENCE IS NOT EVIDENCE (AGENTS.md).  Every count
   is printed whether or not it is zero, and anything not converted is reported
   by name on its own line rather than being absent from the comparison.
"""

import argparse, csv, io, json, os, re, sys
from collections import OrderedDict, defaultdict

SLOTS = list(range(1, 12))
IMPLANT_MODEL = "ImplantModel"
EFFECT_MODEL  = "EffectModel"
IMPLANT_KEY   = "ImplantTypeId"
EFFECT_KEY    = "ImplantEffectId"          # the sheet column that keys the EffectModel rule
EFFECT_ID_COL = "EffectId"                 # the game column it resolves against

GLOBAL_FILE = "implants-global.json"
RULES_FILE  = "ckf.hardmode.rules.json"

# ---------------------------------------------------------------------------
# ckf.hardmode.rules.json IS NOT PART OF THE 4.0 LAYOUT, AND THAT IS DECLARED
# HERE RATHER THAN DISCOVERED BY A BRANCH NOBODY SEES
#
# A bare `if os.path.exists(...)` around the rules file would let the script
# carry on with a smaller view of what writes, silently. That matters here
# specifically: columns_for drops a column that is constant across a slot
# UNLESS a live writer writes it, so a writer that disappears from view takes
# its column out of the sheets with nothing said (ImplantStress was dropped
# from ten of the eleven sheets that way before implants-global.json was
# counted as a writer).
#
# So absence is a STATE with a name, asserted against RULES_FILE_EXPECTED:
#
#   "gone"    the 4.0 layout.  Absent is correct; PRESENT is the surprise, and
#             it is reported as a problem -- a rules file that comes back is
#             read before every sheet and applies on top of it.
#   "present" the 3.x layout.  Absent is the surprise.
#
# Whichever way round, the state is PRINTED on every run, and the pair
# (expected, found) is printed with it.  A run that cannot say which layout it
# read is not a run that agreed with anything.
RULES_FILE_EXPECTED = "gone"

# THE NINE TRIPLES THE 3.x RULES FILE CARRIED FOR THESE ELEVEN TABLES
# [measured: resolve_old() over that file, 9 triples, 0 unscoped].  Every one
# was `set` and was converted into implants-slot08.csv.
#
# Under --ruleset-3x, check_declared_triples() asserts the SHEETS still write
# all nine, with the same operator and the same value, naming each one that
# is missing.  An empty old side compared against anything would be exactly the
# green-over-nothing this file's header rejects.
DECLARED_LAST_RULES_TRIPLES = OrderedDict([
    ((EFFECT_MODEL, 50007, "CritMultiBase"), ("set", 0.0)),   # Display Link (ImplantTypeId 3400)
    ((EFFECT_MODEL, 50052, "CritMultiBase"), ("set", 0.0)),   # Combat DisplayLink (3300)
    ((EFFECT_MODEL, 50053, "CritMultiBase"), ("set", 0.0)),   # Target Optimizer (3301)
    ((EFFECT_MODEL, 50105, "CritMultiBase"), ("set", 0.0)),   # Apex DisplayLink (3304)
    ((EFFECT_MODEL, 50106, "CritMultiBase"), ("set", 0.0)),   # Apex Optimizer (3305)
    ((EFFECT_MODEL, 50107, "CritMultiBase"), ("set", 0.0)),   # Brightshot Optic 1 (3200)
    ((EFFECT_MODEL, 50108, "CritMultiBase"), ("set", 0.0)),   # Brightshot Optic 2 (3201)
    ((EFFECT_MODEL, 50109, "CritMultiBase"), ("set", 0.0)),   # Brightshot Optic 3 (3202)
    ((EFFECT_MODEL, 50110, "CritMultiBase"), ("set", 0.0)),   # Brightshot Optic 4 (3203)
])

# The columns the rules file was the ONLY live witness for, as far as LiveRules
# could see: with the file present LiveRules.columns[EffectModel] carried these
# three and without it, it does not [measured, both constructions of LiveRules
# against the same config directory].  Named because P-DROP asks
# LiveRules whether anything writes a dropped column, and the honest answer for
# these three is now "nothing this script can see" rather than "nothing".  The
# lever sheets themselves are deliberately NOT folded into LiveRules -- the
# sheets are what columns_for is deciding, and a checker built from the thing it
# checks is the self-consistent blindness probe_drop's docstring warns about.
RULES_FILE_ONLY_COLUMNS = {EFFECT_MODEL: ["CritMultiBase", "DroneDamage", "PureDamageMelee"]}

def sheet_name(slot):
    return "implants-slot%02d.csv" % slot

# ---------------------------------------------------------------------------
# BEGIN LEVER MAP
#
# Scraped by check_map_matches_plugin() out of mods/CKFHardMode/Implants.cs
# between its own BEGIN LEVER MAP / END LEVER MAP markers and compared against
# this table.  The reader REFUSES rather than guessing when it cannot find the
# markers: "could not look" is not "they agree".
#
# These are the CANDIDATE levers -- every ImplantModel column that is not
# identity or display text, and every EffectModel column that is not identity.
# Which of them a given slot actually carries is decided per slot by
# columns_for(), from that slot's own rows.  Nothing here is hand-listed per
# slot: a hand list is the failure mode Phase 5 deleted.
#
# NO TalentModel COLUMN IS HERE AND THAT IS DELIBERATE.  Slot 6 (claws,
# ImplantClass 27) and slot 8 (optical lasers, ImplantClass 32) are also the
# subjects of cyberweapons-claws.csv and cyberweapons-lasers.csv.  design.md
# section 7: the implant table carries install economics and the implant-side
# effect, the cyberweapon sheets carry the WeaponModel and TalentModel combat
# stats.  The five TalentModel rules that reach implant talents (80007-80010,
# 80027-80038) are the cyberweapon sheets' rows, already claimed there, and a
# TalentModel column here would let two sheets write one (model, id).
IMPLANT_LEVERS = [
    "ImplantLevel", "ImplantConflictId", "ImplantStress", "ImplantDVMult",
    "ImplantDVScore", "Deactivated", "MatrixEffectId", "ArmorRestriction",
    "InstallTime", "BackstoryGroup", "InstallJobId", "ImplantTalentId",
    "ServiceOptionId", "Rarity", "PowerLevel", "Cost",
]

# Identity: shown, never parsed as an adjustment.  ImplantTypeId keys the
# ImplantModel rule; ImplantEffectId keys the EffectModel rule (the same role
# TalentId plays on the cyberweapon sheets); ImplantClass is design.md section
# 7's "the slot is the table key; the class is a column"; ImplantName is there
# so the file reads in a spreadsheet.
IMPLANT_IDENTITY = ["ImplantName", IMPLANT_KEY, "ImplantClass", EFFECT_KEY]

# Display-only ImplantModel columns, never carried: two are localisation keys
# and two repeat the class name on every row of the class.
IMPLANT_TEXT = ["ImplantDesc", "ImplantClassName", "ImplantClassDesc"]

# EFFECTMODEL PRESENTATION AND RUNTIME-STATE COLUMNS -- NEVER LEVERS.
#
# columns_for() walks `dump.eff_cols` -- every column of the dumped
# EffectModel table -- skipping EFFECT_IDENTITY, these columns, and columns
# that are zero on every effect row.
#
# The dump's column set is a property of WHEN THE DUMP WAS TAKEN, not of the
# game tables: the dumper can omit a column constant across all rows, so a dump
# taken after a real play session carries columns an earlier one did not
# (`IconAsset`, an asset path, is one [measured]). Without this list such a
# column would become a lever and widen the generated sheets. None of the
# columns that appear that way is a lever (David's rule, as for
# consumables.py).
EFFECT_PRESENTATION = [
    "IconAsset",          # asset path
    "VFX",                # asset reference
    "ManualEffectName",   # display string
    "OwnerEntityId",      # runtime instance state
    "isInit",             # runtime instance state
    "effectsSet",         # runtime instance state
    "HasInitSpecialCode", # runtime instance state
]

# ImplantSlot is the table key itself and is carried by no table.
IMPLANT_TABLE_KEY = "ImplantSlot"

# EffectModel identity.  EffectClassification is 7 on all 98 referenced effects
# [measured] and carries no information, which is why it is here and not among
# the payload levers; design.md section 7 names it with Duration, Instant,
# EffectHealType and Heals, and those four are dropped by the ordinary
# all-zero test rather than by being listed.
EFFECT_IDENTITY = ["EffectName", EFFECT_ID_COL, "EffectClassification"]
# END LEVER MAP
# ---------------------------------------------------------------------------

CONTROL_COMMENT = "_comment"
REFUSED_CONTROL = {
    "_clone":   "a clone is never emitted from a lever sheet (design.md section 11)",
    "_serveOn": "serveOn belongs to a clone rule, and these sheets emit none",
}


def read_csv(path):
    with io.open(path, "r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def strip_jsonc(text):
    """The rules file's 76-line header is // comments before the array opens."""
    return re.sub(r"^\s*//.*$", "", text, flags=re.M)


def nz(v):
    return v is not None and v.strip() not in ("", "0")


class Dump(object):
    def __init__(self, dump_dir):
        self.dir = dump_dir
        self.implants = read_csv(os.path.join(dump_dir, "ImplantModel.csv"))
        self.effects  = read_csv(os.path.join(dump_dir, "EffectModel.csv"))
        self.imp_cols = list(self.implants[0].keys())
        self.eff_cols = list(self.effects[0].keys())
        self.eff_by_id = OrderedDict((int(r[EFFECT_ID_COL]), r) for r in self.effects)
        self.imp_by_id = OrderedDict((int(r[IMPLANT_KEY]), r) for r in self.implants)

    def rows_for(self, slot):
        return [r for r in self.implants if int(r[IMPLANT_TABLE_KEY]) == slot]

    def effect_ids_for(self, slot):
        out = []
        for r in self.rows_for(slot):
            e = int(r[EFFECT_KEY])
            if e and e not in out:
                out.append(e)
        return out


class LiveRules(object):
    """Every write the live config performs on ImplantModel or EffectModel.

    Read from ckf.hardmode.rules.json AND from every overlay CSV in
    ckf.hardmode.d, because a dropped column has to be checked against
    everything that writes, not against the one file that is easy to parse.
    An unreadable source RAISES; it is not counted as "writes nothing".

    AND FROM implants-global.json.  The blanket implant multipliers live there,
    and mods\CKFHardMode\Implants.cs ExpandGlobal emits them as one unscoped
    ImplantModel rule, no `where`, at the end of the overlay walk.

    Not reading it is not a silent nothing.  columns_for drops a constant
    column unless a live writer writes it, ImplantStress is constant inside
    every slot, so a LiveRules blind to implants-global.json drops ImplantStress
    from ten of the eleven tables -- the trap this file's own F3 cases exist to
    catch [measured: F3b and F3c fail without this source].
    """

    def __init__(self, config_dir, rules_path=None):
        self.writes = defaultdict(set)     # (model, id) -> {column}
        self.columns = defaultdict(set)    # model -> {column}
        self.unscoped = []                 # rules with no selector at all
        self.sources = []
        if rules_path is None:
            rules_path = os.path.join(config_dir, RULES_FILE)
        self.rules_path = rules_path
        # Present -> read; absent -> recorded. found/expected are both
        # recorded and both printed, and a mismatch either way is a problem
        # the caller raises; a bare `if os.path.exists` would say nothing.
        self.rules_file_found = os.path.exists(rules_path)
        self.rules_file_expected = RULES_FILE_EXPECTED
        self.rules_file_surprise = (
            (self.rules_file_found and RULES_FILE_EXPECTED == "gone")
            or (not self.rules_file_found and RULES_FILE_EXPECTED == "present"))
        if self.rules_file_found:
            self._read_rules(rules_path)
        d = os.path.join(config_dir, "ckf.hardmode.d")
        if os.path.isdir(d):
            for name in sorted(os.listdir(d)):
                if not name.lower().endswith(".csv"):
                    continue
                model = name.split(".")[0]
                if model not in (IMPLANT_MODEL, EFFECT_MODEL):
                    continue
                self._read_overlay(os.path.join(d, name), model)
            g = os.path.join(d, GLOBAL_FILE)
            if os.path.exists(g):
                self._read_global(g)

    def state_line(self):
        """One sentence, printed on every run, naming what was expected, what was
        found and what follows from it."""
        if self.rules_file_found:
            return ("  %s: PRESENT (expected %s) -- read as a source of implant "
                    "writes." % (RULES_FILE, self.rules_file_expected))
        return ("  %s: NOT ON DISK (expected %s) -- not part of the 4.0 layout; the "
                "ckf.hardmode.d sheets and %s are the only sources of implant "
                "writes this run. The nine triples it used to carry were "
                "asserted against DECLARED_LAST_RULES_TRIPLES instead of "
                "compared against it; that assertion (P-GONE) is RETIRED from "
                "--check, %s %s -- run it with %s."
                % (RULES_FILE, self.rules_file_expected, GLOBAL_FILE,
                   RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON,
                   RULESET_3X_RETIRED_FLAG))

    def surprise_problem(self):
        """The surprise, in whichever direction it happened, or None."""
        if not self.rules_file_surprise:
            return None
        if self.rules_file_found:
            return ("RULES-FILE: %s is ON DISK and RULES_FILE_EXPECTED is %r. It "
                    "is not part of the 4.0 layout; a plugin that reads it applies it "
                    "BEFORE every overlay and every lever sheet, so any rule in it that "
                    "is not a plain `set` applies on top of the sheet that "
                    "replaced it. Either it came back by accident and should go, "
                    "or the deletion was reverted and RULES_FILE_EXPECTED should "
                    "say so." % (self.rules_path, self.rules_file_expected))
        return ("RULES-FILE: %s is NOT on disk and RULES_FILE_EXPECTED is %r. "
                "Every implant write this script can see comes from the sheets "
                "and %s; a green run would mean COULD NOT LOOK, not agreement."
                % (self.rules_path, self.rules_file_expected, GLOBAL_FILE))

    def _read_rules(self, path):
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            doc = json.loads(strip_jsonc(fh.read()))
        self.sources.append((path, len(doc["rules"])))
        for r in doc["rules"]:
            model = r.get("model")
            if model not in (IMPLANT_MODEL, EFFECT_MODEL):
                continue
            cols = set()
            for op in ("set", "multiply", "add", "clampMin", "clampMax"):
                cols |= set(r.get(op, {}).keys())
            if not cols:
                continue
            self.columns[model] |= cols
            where = r.get("where") or {}
            if where:
                k = list(where.keys())[0]
                self.writes[(model, int(where[k]))] |= cols
            elif "whereMin" in r:
                k = list(r["whereMin"].keys())[0]
                lo, hi = int(r["whereMin"][k]), int(r["whereMax"][k])
                for i in range(lo, hi + 1):
                    self.writes[(model, i)] |= cols
            else:
                self.unscoped.append((model, sorted(cols), r))

    # The keys implants-global.json carries and the ImplantModel column each
    # one multiplies.  A TRANSCRIPTION of schema/implantsglobal.schema.json's
    # `fields` and of Implants.cs's GlobalOptions, not a second declaration:
    # schema/ is not this file's to edit and the plugin is the thing that
    # actually emits.  A key here that the file does not carry contributes
    # nothing; a key in the file that is not here is not read, and ConfigDoc's
    # own stray-key guard is what reports that at load.
    GLOBAL_MULTIPLIES = OrderedDict([
        ("costMultiply",          "Cost"),
        ("installTimeMultiply",   "InstallTime"),
        ("implantStressMultiply", "ImplantStress"),
    ])

    def _read_global(self, path):
        """The blanket implant multipliers, as ONE unscoped ImplantModel write.

        UNSCOPED IS THE POINT.  The rule this replaced had no `where` and
        reached all 198 ImplantModel rows including the 20 drone modules no
        table shows; ExpandGlobal emits none either.  Registering it as
        unscoped is what makes writes_column answer True for every id rather
        than for the 178 this file happens to enumerate.

        implantStressClampMin is NOT read here even when a leftover file
        carries it: the plugin does not emit it (sanctioned deviation D3) and
        D-CLAMP below re-derives that it binds on 0 of the 198 rows.
        """
        with io.open(path, "r", encoding="utf-8-sig") as fh:
            doc = json.loads(strip_jsonc(fh.read()))
        terms = OrderedDict((col, doc[key])
                            for key, col in self.GLOBAL_MULTIPLIES.items() if key in doc)
        self.sources.append((path, len(terms)))
        if not terms:
            return
        self.columns[IMPLANT_MODEL] |= set(terms)
        self.unscoped.append((IMPLANT_MODEL, sorted(terms),
                              {"model": IMPLANT_MODEL, "multiply": terms}))

    def _read_overlay(self, path, model):
        rows = read_csv(path)
        self.sources.append((path, len(rows)))
        if not rows:
            return
        key = list(rows[0].keys())[0]
        for r in rows:
            try:
                rid = int(r[key])
            except (TypeError, ValueError):
                continue
            cols = set(c for c in r
                       if c and not c.startswith("_") and c != key and nz(r[c]))
            self.columns[model] |= cols
            self.writes[(model, rid)] |= cols

    def writes_column(self, model, ids, column):
        """Does anything live write `column` on any of `ids`?  Unscoped rules
        reach every row of their model, so they count for every id."""
        for m, cols, _ in self.unscoped:
            if m == model and column in cols:
                return True
        return any(column in self.writes.get((model, i), ()) for i in ids)


def columns_for(dump, live, slot):
    """The columns this slot's table carries, and why each dropped one went.

    THE RULE, stated once:

      carried  iff  the column is non-zero on at least one of this slot's own
                    rows
               AND  (it varies across them
                     OR this table has a single row
                     OR a live rule writes it on a row this table owns)

    The first clause is the lever-sheets spec's "no table shows a column dead
    for its own rows".  The second is the same spec's "or constant" -- with two
    exceptions that are not cosmetic:

      * A SINGLE-ROW TABLE.  Slot 11 is one row, so EVERY column is constant
        across it and the plain reading empties the table.  Constancy is
        VACUOUS AT n=1 -- constant across one row is arithmetic, not an
        observation -- so only the all-zero test applies.

        This rests on the n=1 arithmetic, not on how the GUI lays the table
        out (every sheet is drawn as a grid).

      * A COLUMN A LIVE WRITER WRITES.  ImplantStress is constant inside every
        slot and the global multiplier (implants-global.json) scales it;
        dropping it would hide an ImplantModel lever the mod actually pulls.
    """
    rows = dump.rows_for(slot)
    ids = [int(r[IMPLANT_KEY]) for r in rows]
    eff_ids = dump.effect_ids_for(slot)
    eff_rows = [dump.eff_by_id[e] for e in eff_ids]
    single = len(rows) == 1

    carried, dropped = [], []
    for col in IMPLANT_LEVERS:
        vals = [r[col] for r in rows]
        if not any(nz(v) for v in vals):
            dropped.append((col, IMPLANT_MODEL, "zero on all %d row(s)" % len(rows), "0"))
            continue
        if len(set(vals)) == 1 and not single \
                and not live.writes_column(IMPLANT_MODEL, ids, col):
            dropped.append((col, IMPLANT_MODEL,
                            "constant across all %d row(s)" % len(rows), vals[0]))
            continue
        carried.append((col, IMPLANT_MODEL))

    eff_carried, eff_dropped = [], []
    for col in dump.eff_cols:
        if col in EFFECT_IDENTITY:
            continue
        if col in EFFECT_PRESENTATION:
            # Declared non-lever. Named in the dropped list rather than skipped
            # in silence, so the census says it was excluded on purpose and a
            # reader can tell that from "the dump did not carry it".
            eff_dropped.append((col, EFFECT_MODEL,
                                "declared presentation/runtime-state, never a "
                                "lever (EFFECT_PRESENTATION)", "-"))
            continue
        vals = [r[col] for r in eff_rows]
        if not eff_rows or not any(nz(v) for v in vals):
            eff_dropped.append((col, EFFECT_MODEL,
                                "zero on all %d effect(s)" % len(eff_rows), "0"))
            continue
        if len(set(vals)) == 1 and len(eff_rows) > 1 \
                and not live.writes_column(EFFECT_MODEL, eff_ids, col):
            eff_dropped.append((col, EFFECT_MODEL,
                                "constant across all %d effect(s)" % len(eff_rows), vals[0]))
            continue
        eff_carried.append((col, EFFECT_MODEL))

    return carried + eff_carried, dropped + eff_dropped


# ---------------------------------------------------------------------------
# SHARED ROWS.  design.md section 11.
#
# BLOCKING and INFORMATIONAL are two different dispositions and the difference
# is not a judgement call -- it is whether the second owner has a table.
#
#   EffectId 50126  CombatLink 4 (908) and M-Grade CombatLink (915), both slot
#                   3, both in implants-slot03.csv.  TWO EDITABLE OWNERS, so
#                   the two rows can be given different payloads for one
#                   EffectModel row.  That is divergence, it is refused, and
#                   the refusal names both owners.
#
#   EffectId 50000  Dermal Plating 1 (200, slot 1) and all 20 drone modules in
#                   slots 100-107.  The drone modules have NO TABLE (design.md
#                   section 7: drones are not in the game yet), so there is ONE
#                   editable owner.  Divergence is impossible and the refusal
#                   can never fire.  It gets an INFORMATIONAL marker -- the
#                   edit also reaches the drone modules -- and nothing blocks.
#
# Blocking on 50000 would be an instrument with no operand it can resolve --
# the same defect check_schema.py's `ordered` and `linkedEnable` censuses
# exist to prevent.
# ---------------------------------------------------------------------------
def shared_rows(dump):
    """effect id -> (editable owners, unshown owners), for ids with >1 owner."""
    owners = defaultdict(list)
    for r in dump.implants:
        e = int(r[EFFECT_KEY])
        if e:
            owners[e].append((int(r[IMPLANT_KEY]), r["ImplantName"], int(r[IMPLANT_TABLE_KEY])))
    out = OrderedDict()
    for e in sorted(owners):
        if len(owners[e]) < 2:
            continue
        shown   = [o for o in owners[e] if o[2] in SLOTS]
        unshown = [o for o in owners[e] if o[2] not in SLOTS]
        out[e] = (shown, unshown)
    return out


# ---------------------------------------------------------------------------
# THE OVERRIDES THE SHEETS SHIP.
#
# Exactly nine cells, all in implants-slot08.csv, all EffectModel CritMultiBase
# = 0.  They are the nine rules Phase 4 routed here rather than into a talent
# pack (tasks.md Phase 7) and they are the ONLY tuning this phase carries: a
# tenth shipped override would be a balance change and proposal.md's non-goals
# allow exactly four, all spoken for.
#
# Keyed by (slot, effect id, column) so the emitter cannot put a cell on a row
# whose effect is not the one named.
SHIPPED_OVERRIDES = OrderedDict([
    ((8, 50007, "CritMultiBase"), "=0"),
    ((8, 50052, "CritMultiBase"), "=0"),
    ((8, 50053, "CritMultiBase"), "=0"),
    ((8, 50105, "CritMultiBase"), "=0"),
    ((8, 50106, "CritMultiBase"), "=0"),
    ((8, 50107, "CritMultiBase"), "=0"),
    ((8, 50108, "CritMultiBase"), "=0"),
    ((8, 50109, "CritMultiBase"), "=0"),
    ((8, 50110, "CritMultiBase"), "=0"),
])

# The one unscoped ImplantModel rule.  NOT CONVERTED THIS PHASE, and that is a
# decision with a measurement behind it -- see --check's D-GLOBAL block and
# implants-global.json's own _doc.
UNSCOPED_TERMS = OrderedDict([("Cost", 0.5), ("InstallTime", 0.5), ("ImplantStress", 3.0)])
UNSCOPED_CLAMPMIN = OrderedDict([("ImplantStress", 1.0)])


def build_sheet(dump, live, slot):
    """Return (header, rows) for one slot table.  rows are lists of strings."""
    cols, dropped = columns_for(dump, live, slot)
    header = list(IMPLANT_IDENTITY) + [c for c, _ in cols] + [CONTROL_COMMENT]
    out = []
    for r in dump.rows_for(slot):
        iid = int(r[IMPLANT_KEY])
        eid = int(r[EFFECT_KEY])
        erow = dump.eff_by_id.get(eid) if eid else None
        cells = [r["ImplantName"], str(iid), r["ImplantClass"], str(eid)]
        shipped = []
        for col, model in cols:
            if model == IMPLANT_MODEL:
                ship = r[col]
                cells.append(SHIPPED_OVERRIDES.get((slot, iid, col), ""))
            else:
                # A row with no effect has no payload: the cell is blank and
                # says so in _comment as "no effect row", which is a different
                # answer from "the effect ships 0 there".
                ship = erow[col] if erow is not None else None
                cells.append(SHIPPED_OVERRIDES.get((slot, eid, col), "") if erow is not None else "")
            shipped.append("%s %s" % (col, "-" if ship is None else ship))
        who = "%s (class %s %s)" % (r["ImplantName"], r["ImplantClass"], r["ImplantClassName"])
        if eid:
            note = "effect %d %s" % (eid, dump.eff_by_id[eid]["EffectName"])
        else:
            note = "no effect row (ImplantEffectId 0), so every payload cell is blank"
        cells.append("%s. %s. Shipped: %s." % (who, note, "; ".join(shipped)))
        out.append(cells)
    return header, out, dropped


def csv_text(header, rows):
    """LF, no quoting beyond what csv needs.  The sheets are LF like every
    other CSV in ckf.hardmode.d; SCHEMA-FORMAT.md and check_schema.py are the
    CRLF pair and neither is written here."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow(r)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# THE EXPANDER MIRROR.  What Implants.cs will do at load, in Python, so that
# --check compares the RULES the sheets compile to rather than the cells.
# ---------------------------------------------------------------------------
ADJUST = re.compile(r"^\s*(=|\+|-|x|\*)?\s*(-?\d+(?:\.\d+)?)\s*$", re.I)


def parse_adjust(cell):
    """Three-state, like MissionRewards.Adjust.Parse: (kind, value, ok).
    A blank is ("none", 0, True).  '90x' is ("", 0, False) -- NOT a blank."""
    if cell is None or cell.strip() == "":
        return ("none", 0.0, True)
    m = ADJUST.match(cell)
    if not m:
        return ("", 0.0, False)
    op, num = m.group(1), float(m.group(2))
    if op in ("x", "X", "*"):
        return ("multiply", num, True)
    if op == "+":
        return ("add", num, True)
    if op == "-":
        return ("add", -num, True)
    return ("set", num, True)


def expand(header, rows, sheet, problems, marks=None, unshown_owners=None):
    """Sheet -> list of rules, mirroring Implants.Expand.

    Two rows of one sheet can carry the same ImplantEffectId -- implants-slot03
    ships exactly that, CombatLink 4 (908) and M-Grade CombatLink (915) both on
    EffectId 50126.  The payload halves of those rows are therefore two editors
    of ONE EffectModel row, and they are reconciled BEFORE any rule is built:

      identical (including both blank) -> one rule, emitted once, marked shared
      different                        -> REFUSED, naming both owners

    Refusing after the fact -- letting the (model, id) registry reject whichever
    row arrived second -- would make the surviving edit depend on row order,
    which is the shape Cyberweapons.cs's registry warning calls "load order, not
    a merge".  Here the reconciliation is explicit so the refusal can name both.
    """
    marks = marks if marks is not None else []
    unshown_owners = unshown_owners or {}
    for h in header:
        if h in REFUSED_CONTROL:
            problems.append("%s: header carries refused control column '%s' (%s); "
                            "the WHOLE file is refused" % (sheet, h, REFUSED_CONTROL[h]))
            return []
    if IMPLANT_KEY not in header or EFFECT_KEY not in header:
        problems.append("%s: missing %s or %s; no rule emitted"
                        % (sheet, IMPLANT_KEY, EFFECT_KEY))
        return []

    idx = dict((h, i) for i, h in enumerate(header))
    known_imp = set(IMPLANT_LEVERS)
    payload_cols = [h for h in header
                    if h not in IMPLANT_IDENTITY and h != CONTROL_COMMENT
                    and not h.startswith("_") and h not in known_imp]

    # ---- pass 1: read every row's two halves -----------------------------
    parsed = []
    for n, r in enumerate(rows, start=2):
        try:
            iid, eid = int(r[idx[IMPLANT_KEY]]), int(r[idx[EFFECT_KEY]])
        except (TypeError, ValueError):
            problems.append("%s:%d %s/%s is not a pair of integer ids; the WHOLE row "
                            "is skipped, both halves of it" % (sheet, n, IMPLANT_KEY, EFFECT_KEY))
            continue
        imp_ops, eff_ops, eff_cells = defaultdict(OrderedDict), defaultdict(OrderedDict), OrderedDict()
        for h in header:
            if h in IMPLANT_IDENTITY or h == CONTROL_COMMENT or h.startswith("_"):
                continue
            cell = r[idx[h]] if idx[h] < len(r) else ""
            kind, val, ok = parse_adjust(cell)
            if not ok:
                problems.append("%s:%d column %s: '%s' is not an adjustment -- expected "
                                "blank, =N, +N, -N or xN" % (sheet, n, h, cell))
                continue
            if h in known_imp:
                if kind != "none":
                    imp_ops[kind][h] = val
                continue
            eff_cells[h] = (cell or "").strip()
            if kind == "none":
                continue
            if not eid:
                problems.append("%s:%d column %s is a payload column and this row's %s "
                                "is 0; there is no EffectModel row to write"
                                % (sheet, n, h, EFFECT_KEY))
                continue
            eff_ops[kind][h] = val
        parsed.append((n, iid, eid, imp_ops, eff_ops, eff_cells))

    # ---- pass 2: reconcile the payload halves that share an effect row ----
    by_effect = OrderedDict()
    for n, iid, eid, _, eff_ops, eff_cells in parsed:
        if eid:
            by_effect.setdefault(eid, []).append((n, iid, eff_ops, eff_cells))
    blocked = set()
    for eid, owners in by_effect.items():
        extra = unshown_owners.get(eid, [])
        if len(owners) > 1:
            base = owners[0][3]
            divergent = [c for c in payload_cols
                         if len(set(o[3].get(c, "") for o in owners)) > 1]
            names = ", ".join("%s (row %d)" % (o[1], o[0]) for o in owners)
            if divergent:
                blocked.add(eid)
                problems.append(
                    "%s: EffectId %d is written by %d rows of this sheet -- %s -- and "
                    "they DIVERGE on %s. One EffectModel row cannot hold two payloads, so "
                    "NO EffectModel rule is emitted for %d at all. Splitting it is an "
                    "explicit per-row _clone opt-in (design.md section 11) and nothing has "
                    "opted in." % (sheet, eid, len(owners), names, ", ".join(divergent), eid))
            else:
                marks.append(("blocking", eid, [o[1] for o in owners], extra,
                              "%s: EffectId %d is SHARED by %s. Both are editable, so the "
                              "two payload halves can diverge; they are identical here and "
                              "one rule is emitted. A divergent edit is refused, naming "
                              "both." % (sheet, eid, names)))
        elif extra:
            marks.append(("informational", eid, [owners[0][1]], extra,
                          "%s: EffectId %d also reaches %d row(s) no table shows (%s). "
                          "There is ONE editable owner, so divergence is impossible and "
                          "nothing blocks -- this marker informs, it does not refuse."
                          % (sheet, eid, len(extra),
                             ", ".join("%d %s slot %d" % o for o in extra[:3])
                             + ("..." if len(extra) > 3 else ""))))

    # ---- pass 3: build the rules -----------------------------------------
    rules, claimed, seen_effect = [], {}, set()
    for n, iid, eid, imp_ops, eff_ops, _ in parsed:
        for model, key, ops in ((IMPLANT_MODEL, iid, imp_ops), (EFFECT_MODEL, eid, eff_ops)):
            if not ops:
                continue
            if model == EFFECT_MODEL:
                if eid in blocked:
                    continue
                if eid in seen_effect:
                    continue          # identical payload, already emitted once
                seen_effect.add(eid)
            k = (model, key)
            if k in claimed:
                problems.append("%s:%d (%s, %d) is already written by %s -- REFUSED. The "
                                "key is (table, id): TalentModel 80007 and EffectModel "
                                "80007 are different rows."
                                % (sheet, n, model, key, claimed[k]))
                continue
            claimed[k] = "%s:%d" % (sheet, n)
            rules.append({
                "model": model,
                "where": {IMPLANT_KEY if model == IMPLANT_MODEL else EFFECT_ID_COL: key},
                "ops": OrderedDict((kind, OrderedDict(cols)) for kind, cols in sorted(ops.items())),
                "from": "%s:%d" % (sheet, n),
            })
    return rules


# ---------------------------------------------------------------------------
# --check : DOUBLE APPLICATION, AND WHETHER IT IS A NO-OP
#
# Applies only when a 3.x ckf.hardmode.rules.json is present beside the
# sheets: a converted rule is then applied TWICE, once from the rules file and
# once from the sheet.  Whether that is safe is a property of the OPERATOR,
# not of the totals:
#
#   set      idempotent.  set X=0 twice is X=0.
#   multiply NOT idempotent.  x0.5 twice is x0.25.
#
#   D-SET     the nine EffectModel rules the slot 8 table carries are `set` and
#             nothing else -- no multiply, add, clampMin, clampMax or clone.
#             Double application is a no-op.
#
#   D-GLOBAL  the 3.x unscoped ImplantModel rule is a `multiply` with a
#             `clampMin`.  With it present, implants-global.json would land
#             Cost and InstallTime on x0.25 and ImplantStress on x9 across all
#             198 rows, so it is counted, named and reported rather than
#             skipped.  In the 4.0 layout the rule is gone and
#             implants-global.json is the only source of the multipliers.
# ---------------------------------------------------------------------------
def resolve_old(dump, live_rules_path):
    """The rules file's implant writes, resolved against the dump into
    (model, id, column) -> value.  A range selector is expanded; an unscoped
    rule is returned separately rather than silently folded in.

    RETURNS FOUR THINGS NOW, not three.  The fourth is whether the file was
    there at all.  Wrapping the open in a try and returning three empty dicts
    would be wrong, because "no old side" and "an old side
    with nothing in it" would then print the same "0 differ" line.  The caller
    branches on the flag.
    """
    if not os.path.exists(live_rules_path):
        return OrderedDict(), [], defaultdict(set), False
    with io.open(live_rules_path, "r", encoding="utf-8-sig") as fh:
        doc = json.loads(strip_jsonc(fh.read()))
    triples, unscoped, ops_seen = OrderedDict(), [], defaultdict(set)
    for r in doc["rules"]:
        model = r.get("model")
        if model not in (IMPLANT_MODEL, EFFECT_MODEL):
            continue
        ids = []
        if r.get("where"):
            k = list(r["where"].keys())[0]
            ids = [int(r["where"][k])]
        elif "whereMin" in r:
            k = list(r["whereMin"].keys())[0]
            ids = list(range(int(r["whereMin"][k]), int(r["whereMax"][k]) + 1))
        else:
            unscoped.append(r)
            continue
        shown_effects = set(e for s in SLOTS for e in dump.effect_ids_for(s))
        for i in ids:
            if model == EFFECT_MODEL and i not in shown_effects:
                continue        # not an implant effect; another phase owns it
            for op in ("set", "multiply", "add", "clampMin", "clampMax"):
                for col, val in r.get(op, {}).items():
                    ops_seen[(model, i)].add(op)
                    triples[(model, i, col)] = (op, float(val))
    return triples, unscoped, ops_seen, True


def resolve_new(sheets, dump, problems, marks):
    unshown = dict((e, un) for e, (sh, un) in shared_rows(dump).items() if un)
    triples = OrderedDict()
    per_sheet = OrderedDict()
    for name, (header, rows) in sheets.items():
        rs = expand(header, rows, name, problems, marks, unshown)
        per_sheet[name] = rs
        for r in rs:
            key = list(r["where"].values())[0]
            for kind, cols in r["ops"].items():
                for col, val in cols.items():
                    triples[(r["model"], key, col)] = (kind, float(val))
    return triples, per_sheet


def shipped_value(dump, model, rid, col):
    row = (dump.imp_by_id if model == IMPLANT_MODEL else dump.eff_by_id).get(rid)
    if row is None or col not in row:
        return None
    try:
        return float(row[col])
    except (TypeError, ValueError):
        return None


def apply_op(base, kind, val):
    if kind == "set":
        return val
    if kind == "multiply":
        return base * val
    if kind == "add":
        return base + val
    if kind == "clampMin":
        return max(base, val)
    if kind == "clampMax":
        return min(base, val)
    raise ValueError(kind)


# ---------------------------------------------------------------------------
# P-GONE IS RETIRED FROM THE DEFAULT --check.
# ---------------------------------------------------------------------------
#
# David's rule: deviation from the 3.0 ruleset is tuning, not a mistake.
#
# WHAT IS RETIRED. One instrument, and only from the DEFAULT --check:
# check_declared_triples(), which asserts that the sheets still emit all nine
# triples the 3.x ckf.hardmode.rules.json carried, with the same operator and
# the same value. It was built to catch a value LOST BY ACCIDENT during
# conversion -- columns_for quietly dropping a column with nothing left that
# knew the column was written -- and it cannot tell a deliberately cleared cell
# from an accidentally dropped column, so every tuning edit to one of those
# nine CritMultiBase cells would report a problem. scripts/cyberweapons.py
# (P-GONE, UNDECLARED CHANGE), scripts/gear_classes.py and the gui/serve.py
# migration block retire their equivalents the same way.
#
# WHAT IS NOT RETIRED, AND IT IS EVERYTHING ELSE IN --check. P-COL, P-ROW,
# P-DROP, P-MAP, P-HELP, P-SHARED, D-CLAMP, D-GLOBAL and the RULES-FILE state
# declaration all run on every --check and all still go red. So does
# RULES_FILE_ONLY_COLUMNS, which is a live note about what LiveRules can see
# and is reported separately (report_rules_file_only_columns).
#
# WHAT IS NOT DELETED. check_declared_triples() and DECLARED_LAST_RULES_TRIPLES
# are reachable:
#
#     python scripts/implants.py --check --ruleset-3x --game <root>
#
# and the three selftest cases that fault it (C4, F9, F10) run under the same
# flag.
#
# HOW THE DEFAULT --check REPORTS IT. NOT RUN, by name, never PASS and never
# absent. AGENTS.md: an instrument's silence is not evidence, and a
# retired check must SAY it is not running.

RULESET_3X_RETIRED_ON = "2026-09-15"
RULESET_3X_RETIRED_BY = "David's ruling"
RULESET_3X_RETIRED_FLAG = "--ruleset-3x"
RULESET_3X_RETIRED_WHY = (
    "RETIRED from the default --check, %s %s. Run it with "
    "`implants.py --check %s --game <root>`."
    % (RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON, RULESET_3X_RETIRED_FLAG))

RULESET_3X_RETIRED_CHECKS = (
    "P-GONE -- the 9 triples the 3.x ckf.hardmode.rules.json carried for "
    "these tables are STILL EMITTED by the sheets, same operator, same value",
)

RULESET_3X_RETIRED_CASES = (
    "C4: the sheets write every triple the deleted rules file carried",
    "F9: a declared triple the sheets no longer write at all (the Phase 9a "
    "failure, on this file's own nine)",
    "F10: a declared triple the sheets write with a different value",
)


def ruleset_3x_report_retired(out):
    """P-GONE as a RECORDED NON-RUN. Appends lines, returns no problems."""
    for line in (
        "P-GONE: NOT RUN. The 3.x-conformance assertion is RETIRED from "
        "--check.",
        "  %s, %s. The %d check(s) and %d fault case(s) below are reported by "
        "name and never pass."
        % (RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON,
           len(RULESET_3X_RETIRED_CHECKS), len(RULESET_3X_RETIRED_CASES)),
        '  THE RULING: "Stop considering deviation from the 3.0 ruleset a '
        'mistake. Remove all consideration that this is a problem."',
        "  WHY. It compares the sheets against the 3.0 ruleset they were "
        "converted from. It was built to catch a value lost by ACCIDENT during "
        "conversion, and conversion is over; it cannot tell tuning from loss.",
        "  NOT A TOLERANCE LIST. No triple was excused; the comparison left "
        "the default suite.",
        "  EVERYTHING ELSE RAN. P-COL, P-ROW, P-DROP, P-MAP, P-HELP, P-SHARED, "
        "D-CLAMP, D-GLOBAL and the RULES-FILE state declaration are unchanged.",
    ):
        out.append(line)
    for name in RULESET_3X_RETIRED_CHECKS:
        out.append("  NOT RUN  %s" % name)
        out.append("           %s" % RULESET_3X_RETIRED_WHY)
    for name in RULESET_3X_RETIRED_CASES:
        out.append("  NOT RUN  selftest %s" % name)
        out.append("           %s" % RULESET_3X_RETIRED_WHY)
    return []


def report_rules_file_only_columns(out):
    """NOT part of P-GONE and NOT retired with it.

    The columns LiveRules can no longer see a writer for. Named, counted, and
    not inferred from silence. P-DROP asks LiveRules whether anything writes a
    dropped column, and the honest answer for these three is "nothing this
    script can see" rather than "nothing" -- which is a statement about THIS
    RUN's evidence, not a comparison against the 3.0 ruleset, so it is not
    retired with P-GONE.
    """
    for model, cols in sorted(RULES_FILE_ONLY_COLUMNS.items()):
        out.append("P-DROP-WITNESS: %d %s column(s) had the rules file as their "
                   "only witness in LiveRules and now have none: %s. columns_for "
                   "keeps or drops on that evidence, so the eleven headers were "
                   "compared built both ways; they were identical [measured]."
                   % (len(cols), model, ", ".join(cols)))
    return []


def check_declared_triples(new, dump, out):
    """P-GONE -- the nine triples ckf.hardmode.rules.json carried for these
    tables, asserted against what the SHEETS emit today.

    This is P-CHECK's old side when no rules file is present.  It is a
    typed-in oracle (DECLARED_LAST_RULES_TRIPLES), so it cannot move when the
    sheets move, which is the whole point: the Phase 9a failure was a sheet
    quietly losing a column because the only thing that knew the column was
    written had gone away.  Nine equalities, each named, and the count printed
    whether or not it is zero.
    """
    problems, equal, missing, differ = [], 0, [], []
    for key, (op, val) in DECLARED_LAST_RULES_TRIPLES.items():
        got = new.get(key)
        if got is None:
            missing.append(key)
        elif got[0] != op or abs(float(got[1]) - float(val)) > 1e-9:
            differ.append((key, (op, val), got))
        else:
            equal += 1
    out.append("P-GONE: %d declared triple(s) from the deleted %s, asserted "
               "against what the sheets emit: %d equal, %d MISSING, %d DIFFER."
               % (len(DECLARED_LAST_RULES_TRIPLES), RULES_FILE, equal,
                  len(missing), len(differ)))
    for k in missing:
        base = shipped_value(dump, k[0], k[1], k[2])
        problems.append("P-GONE: %s %d %s was written by the deleted rules file "
                        "and NO SHEET WRITES IT NOW (shipped value %r), so the "
                        "value reverts. Reported because %s was passed. This "
                        "shape was the Phase 9a failure when it was an accident "
                        "of conversion; a cleared override is the same shape and "
                        "is tuning."
                        % (k[0], k[1], k[2], base, RULESET_3X_RETIRED_FLAG))
    for (k, want, got) in differ:
        problems.append("P-GONE: %s %d %s was %r in the deleted rules file and "
                        "is %r in the sheets." % (k[0], k[1], k[2], want, got))
    # RULES_FILE_ONLY_COLUMNS is reported by report_rules_file_only_columns(),
    # not here: it is a live note about what LiveRules can see, not part of the
    # 3.x comparison, and it runs on every --check.
    return problems


def d_clamp(dump, out, problems):
    """D-CLAMP -- independent of the rules file, so it runs on both paths.
    Re-derives from the dump that the dropped clampMin binds on no row."""
    stresses = sorted(set(r["ImplantStress"] for r in dump.implants))
    binds = [r[IMPLANT_KEY] for r in dump.implants
             if float(r["ImplantStress"]) * UNSCOPED_TERMS["ImplantStress"]
             < UNSCOPED_CLAMPMIN["ImplantStress"]]
    out.append("D-CLAMP: ImplantStress ships as %s across %d rows; after x%g the lowest is "
               "%g and clampMin %g binds on %d row(s). It is dropped from "
               "implants-global.json per David; this is the measurement that says dropping "
               "it moves no value."
               % (stresses, len(dump.implants), UNSCOPED_TERMS["ImplantStress"],
                  min(float(x) for x in stresses) * UNSCOPED_TERMS["ImplantStress"],
                  UNSCOPED_CLAMPMIN["ImplantStress"], len(binds)))
    if binds:
        problems.append("D-CLAMP: clampMin binds on %d row(s): %s" % (len(binds), binds))
    return problems


def do_check(dump, config_dir, sheets, out, run_3x=False):
    """Apply both sides to the dump and compare every value either side moves.

    THE BASELINE IS THE UNION OF WHAT EITHER SIDE TOUCHES, READ FROM THE DUMP.
    Phase 6's first --check built it from the NEW side's column map, so a triple
    the OLD rules write and the new sheet has no column for produced a None
    baseline and was dropped by the null guard -- exactly the hole a 16-column
    laser sheet would have shipped through.  A triple with no readable shipped
    value is NAMED here and counted, never skipped.
    """
    rules_path = os.path.join(config_dir, RULES_FILE)
    old, unscoped, ops_seen, had_rules_file = resolve_old(dump, rules_path)
    problems, marks = [], []
    new, per_sheet = resolve_new(sheets, dump, problems, marks)

    # THE OLD SIDE CAN BE GONE NOW, AND THAT IS NOT "NO DIFFERENCES".
    # Running the union compare below over an empty old side would print
    # "N triple(s) compared; N equal, 0 differ" and mean nothing whatever --
    # every key would come from the new side alone and be compared against
    # itself. That is the green-over-nothing this file exists to refuse, so the
    # compare is REPLACED by P-GONE rather than run over half a subject.
    if not had_rules_file:
        out.append("P-CHECK: NOT RUN -- %s is not on disk (not part of the 4.0 layout). "
                   "Its side of the comparison does not exist, and a union "
                   "compare with an empty old side would report '0 differ' over "
                   "nothing. P-GONE asserts the nine triples it carried "
                   "against the sheets instead, from a typed-in oracle; P-GONE "
                   "is itself RETIRED from the default --check (%s, %s) and says "
                   "so below by name."
                   % (RULES_FILE, RULESET_3X_RETIRED_ON, RULESET_3X_RETIRED_BY))
        out.append("D-SET: NOT RUN -- double application needs two applications. "
                   "With no rules file the sheets apply once. The 9 triples a "
                   "3.x rules file duplicates are all `set` [measured].")
        out.append("D-GLOBAL: 0 unscoped ImplantModel rule(s) in the rules file, "
                   "because there is no rules file. %s is the only source of the "
                   "three multipliers." % GLOBAL_FILE)
        # THE 3.x-CONFORMANCE ASSERTION IS RETIRED FROM HERE (David's rule).
        # See RULESET_3X_RETIRED_WHY. Recorded non-run on
        # the default path; runs in full under --ruleset-3x.
        if run_3x:
            out.append("RUNNING the retired P-GONE assertion because %s was "
                       "passed. It was retired from the default --check by %s, "
                       "%s. What follows is a DIVERGENCE REPORT against the 3.0 "
                       "ruleset, not a defect list."
                       % (RULESET_3X_RETIRED_FLAG, RULESET_3X_RETIRED_BY,
                          RULESET_3X_RETIRED_ON))
            problems += check_declared_triples(new, dump, out)
        else:
            ruleset_3x_report_retired(out)
        report_rules_file_only_columns(out)
        emitted_imp = [k for k in new if k[0] == IMPLANT_MODEL]
        out.append("D-GLOBAL: the sheets emit %d %s write(s); 0 is still the "
                   "expected answer -- the blanket multipliers are %s's, expanded "
                   "by Implants.ExpandGlobal."
                   % (len(emitted_imp), IMPLANT_MODEL, GLOBAL_FILE))
        if emitted_imp:
            problems.append("D-GLOBAL: the sheets emit %d ImplantModel write(s)."
                            % len(emitted_imp))
        d_clamp(dump, out, problems)
        return problems, marks, per_sheet

    keys = list(OrderedDict.fromkeys(list(old.keys()) + list(new.keys())))
    differ, unreadable, same = [], [], 0
    for k in keys:
        model, rid, col = k
        base = shipped_value(dump, model, rid, col)
        if base is None:
            unreadable.append(k)
            continue
        o = apply_op(base, *old[k]) if k in old else base
        n = apply_op(base, *new[k]) if k in new else base
        if abs(o - n) > 1e-9:
            differ.append((k, base, o, n))
        else:
            same += 1

    out.append("P-CHECK: %d triple(s) compared over the union of both sides; "
               "%d equal, %d differ, %d had no readable shipped value and are NAMED "
               "below rather than skipped." % (len(keys), same, len(differ), len(unreadable)))
    for k in unreadable:
        out.append("  UNREADABLE %s %s %s -- no shipped value in the dump" % k)
    for (k, b, o, n) in differ:
        out.append("  DIFFERS %s %s %s: shipped %s, old rules -> %s, sheets -> %s"
                   % (k[0], k[1], k[2], b, o, n))

    # D-SET: every converted rule is `set` and nothing else.
    converted = [k for k in new if k in old]
    ops = sorted(set(old[k][0] for k in converted) | set(new[k][0] for k in converted))
    out.append("D-SET: %d converted triple(s); operators in use on both sides: %s. "
               "Double application is a no-op iff that list is ['set'] only."
               % (len(converted), ops))
    if ops and ops != ["set"]:
        problems.append("D-SET: a converted rule uses %s, which is not idempotent; "
                        "double application against the still-present rules file would "
                        "MOVE VALUES: the old rule must be deleted in the same commit as "
                        "the sheet that converts it." % [o for o in ops if o != "set"])

    # D-GLOBAL: named and counted. In the 4.0 layout the unscoped ImplantModel
    # rule is gone and Implants.ExpandGlobal emits implants-global.json
    # instead, so 0 is the expected answer.
    out.append("D-GLOBAL: %d unscoped ImplantModel rule(s) in the rules file. The 4.0 "
               "layout has none; implants-global.json is the only source of the three "
               "multipliers, so 0 is the expected answer." % len(unscoped))
    for r in unscoped:
        terms = OrderedDict()
        for op in ("multiply", "set", "add", "clampMin", "clampMax"):
            if op in r:
                terms[op] = r[op]
        out.append("  %s %s -- reaches ALL %d %s rows (no where clause), including the %d "
                   "drone-module rows in slots 100-107 that no table shows."
                   % (r.get("model"), json.dumps(terms), len(dump.implants), IMPLANT_MODEL,
                      len([x for x in dump.implants if int(x[IMPLANT_TABLE_KEY]) not in SLOTS])))
        if "multiply" in terms:
            out.append("  It is a MULTIPLY, so double application is NOT a no-op: "
                       + ", ".join("%s would land on x%g instead of x%g"
                                   % (c, v * v, v) for c, v in terms["multiply"].items())
                       + ". implants-global.json must not be applied while this rule "
                         "is present.")
    emitted_imp = [k for k in new if k[0] == IMPLANT_MODEL]
    out.append("D-GLOBAL: the sheets emit %d %s write(s); 0 is the expected answer "
               "while a rules file is present." % (len(emitted_imp), IMPLANT_MODEL))
    if emitted_imp:
        problems.append("D-GLOBAL: the sheets emit %d ImplantModel write(s) while the "
                        "unscoped multiply is still live." % len(emitted_imp))

    d_clamp(dump, out, problems)
    return problems, marks, per_sheet


# ---------------------------------------------------------------------------
# PROBES.  Each is a positive enumeration over generated output, never an
# inspection, and each prints its count whether or not it is zero.
# ---------------------------------------------------------------------------
def probe_drop(dump, live, out, checker=None):
    """P-DROP -- for EVERY column every table drops, no live rule writes it on
    a row that table owns.  This is the Phase 6 trap as an assertion.

    `checker` defaults to `live` but is separable ON PURPOSE: the fault case
    that matters is a dropper that cannot see the rules deciding to drop, and a
    checker that CAN seeing that it should not have.  Passing one object as both
    makes the probe self-consistent and blind in exactly the way Phase 6's
    --check was."""
    checker = checker or live
    bad, n = [], 0
    for slot in SLOTS:
        ids = [int(r[IMPLANT_KEY]) for r in dump.rows_for(slot)]
        eids = dump.effect_ids_for(slot)
        _, dropped = columns_for(dump, live, slot)
        for col, model, why, val in dropped:
            n += 1
            subj = ids if model == IMPLANT_MODEL else eids
            if checker.writes_column(model, subj, col):
                bad.append("slot %d drops %s.%s (%s) but a live rule WRITES it"
                           % (slot, model, col, why))
    out.append("P-DROP: %d dropped column(s) across the 11 tables, each checked against "
               "every live rule and overlay; %d written by something. A column being "
               "constant says nothing about whether a rule writes it (Phase 6)."
               % (n, len(bad)))
    return bad


def probe_columns(dump, live, sheets, out):
    """P-COL -- no table carries a column dead for its own rows, asserted over
    the GENERATED HEADERS rather than by inspection."""
    bad = []
    for slot in SLOTS:
        name = sheet_name(slot)
        header, rows = sheets[name]
        rs = dump.rows_for(slot)
        eids = dump.effect_ids_for(slot)
        erows = [dump.eff_by_id[e] for e in eids]
        for h in header:
            if h in IMPLANT_IDENTITY or h == CONTROL_COMMENT:
                continue
            if h in set(IMPLANT_LEVERS):
                if not any(nz(r[h]) for r in rs):
                    bad.append("%s carries %s, zero on all %d of its rows" % (name, h, len(rs)))
            else:
                if not erows or not any(nz(r[h]) for r in erows):
                    bad.append("%s carries payload %s, zero on all %d of its effects"
                               % (name, h, len(erows)))
    out.append("P-COL: %d table(s), %d header column(s) total, %d dead."
               % (len(sheets), sum(len(h) for h, _ in sheets.values()), len(bad)))
    return bad


def probe_rows(dump, sheets, out):
    """P-ROW -- every character-slot row is in exactly one table, and no drone
    module is in any."""
    seen = defaultdict(list)
    for slot in SLOTS:
        header, rows = sheets[sheet_name(slot)]
        i = header.index(IMPLANT_KEY)
        for r in rows:
            seen[int(r[i])].append(slot)
    bad = []
    expect = [int(r[IMPLANT_KEY]) for r in dump.implants if int(r[IMPLANT_TABLE_KEY]) in SLOTS]
    drones = [int(r[IMPLANT_KEY]) for r in dump.implants if int(r[IMPLANT_TABLE_KEY]) not in SLOTS]
    for i in expect:
        if len(seen.get(i, [])) != 1:
            bad.append("implant %d appears in %s" % (i, seen.get(i, []) or "no table"))
    for i in drones:
        if i in seen:
            bad.append("drone module %d appears in %s" % (i, seen[i]))
    out.append("P-ROW: %d character-slot row(s) over %d table(s), each in exactly one; "
               "%d drone-module row(s) in slots 100-107, none in any table; %d problem(s)."
               % (len(expect), len(SLOTS), len(drones), len(bad)))
    return bad


def probe_shared(dump, marks, out):
    """P-SHARED -- the sharing that exists in the SHIPPED data, measured from
    the dump.  The runtime marking can only see repoints the sheets write; this
    half is the one that sees what ships."""
    shared = shared_rows(dump)
    bad = []
    for eid, (shown, unshown) in shared.items():
        kind = "blocking" if len(shown) > 1 else "informational"
        got = [m for m in marks if m[1] == eid]
        if not got:
            bad.append("EffectId %d is shared by %d owner(s) and carries NO marker"
                       % (eid, len(shown) + len(unshown)))
        elif got[0][0] != kind:
            bad.append("EffectId %d marked %s, expected %s" % (eid, got[0][0], kind))
    out.append("P-SHARED: %d implant effect row(s) with more than one owner: %s. "
               "%d problem(s)."
               % (len(shared),
                  ", ".join("%d (%d editable owner(s), %d unshown)"
                            % (e, len(s), len(u)) for e, (s, u) in shared.items()),
                  len(bad)))
    for eid, (shown, unshown) in shared.items():
        out.append("  %d -> editable: %s%s"
                   % (eid, ", ".join("%d %s slot %d" % o for o in shown),
                      ("; unshown: %d row(s) in slots %s"
                       % (len(unshown), sorted(set(o[2] for o in unshown)))) if unshown else ""))
    singles = [e for e in (e for s in SLOTS for e in dump.effect_ids_for(s)) if e not in shared]
    out.append("  %d of the %d referenced implant effect rows have exactly one owner."
               % (len(set(singles)), len(set(e for s in SLOTS for e in dump.effect_ids_for(s)))))
    return bad


def probe_help(plugin_path, out):
    """P-HELP -- all eleven slots declare help text in Implants.cs's SlotHelp,
    and the sentences that are not visible from the rows are actually in it.

    The schema's `doc` array is the other half of this and schema\\ is not this
    phase's directory to write, so the plugin holds the text verbatim and the
    schema owner transcribes.  A missing entry is a GAP, not a slot with nothing
    to say, and Implants.Expand says so at load for the same reason.
    """
    if not os.path.exists(plugin_path):
        return ["P-HELP: %s not found; COULD NOT LOOK, which is not agreement." % plugin_path]
    text = io.open(plugin_path, "r", encoding="utf-8").read()
    m = re.search(r"SlotHelp\s*=\s*new Dictionary<int, string>\s*\{(.*?)\n        \};",
                  text, re.S)
    if not m:
        return ["P-HELP: Implants.cs has no SlotHelp table; COULD NOT LOOK."]
    block = m.group(1)
    # Entries are split on their OWN opening lines rather than on a closing
    # brace: the entries end with `" },` at the end of a continued string, and a
    # pattern anchored on a lone `},` line matched nothing and reported every
    # sentence missing from a table that had them all.
    starts = [(int(mm.group(1)), mm.start()) for mm in
              re.finditer(r"^\s*\{\s*(\d+),", block, re.M)]
    entries = {}
    for i, (slot, at) in enumerate(starts):
        stop = starts[i + 1][1] if i + 1 < len(starts) else len(block)
        entries[slot] = re.sub(r'"\s*\+\s*"', "", block[at:stop])
    bad = []
    for s in SLOTS:
        if s not in entries:
            bad.append("P-HELP: slot %d declares no help text" % s)
    if 8 in entries and "EVERY IMPLANT EFFECT IN THE GAME" not in entries[8]:
        bad.append("P-HELP: slot 8's help text does not carry the sentence that "
                   "CritMultiBase ends up zero on EVERY implant effect in the game -- "
                   "which is the one fact its nine rows cannot show")
    for s in (3, 7):
        if s in entries and "file order" not in entries[s]:
            bad.append("P-HELP: slot %d's help text does not say the rows are in file "
                       "order, so a player can read the order as a tier ladder" % s)
    out.append("P-HELP: %d of %d slot(s) declare help text; %d problem(s)."
               % (len(set(entries) & set(SLOTS)), len(SLOTS), len(bad)))
    return bad


def probe_map(plugin_path, out):
    """P-MAP -- this file's lever map and Implants.cs's are one transcription.
    REFUSES rather than guessing if it cannot find the markers."""
    if not os.path.exists(plugin_path):
        return ["P-MAP: %s not found; COULD NOT LOOK. This is a refusal, not agreement."
                % plugin_path]
    text = io.open(plugin_path, "r", encoding="utf-8").read()
    # THE MARKERS ARE ANCHORED TO WHOLE COMMENT LINES, and that is a correction
    # rather than a style.  The first version matched
    # r"BEGIN LEVER MAP(.*?)END LEVER MAP" anywhere in the file, and the block's
    # own prose says "between this marker and END LEVER MAP" -- so the non-greedy
    # match ended INSIDE the paragraph explaining the markers, scraped a
    # four-line comment, and reported all 27 names missing from a file that had
    # every one of them.  An instrument that matches a MENTION of its own marker
    # is measuring the comment, not the table.
    m = re.search(r"^[ \t]*//[ \t]*BEGIN LEVER MAP\b(.*?)^[ \t]*//[ \t]*END LEVER MAP[ \t]*$",
                  text, re.S | re.M)
    if not m:
        return ["P-MAP: %s has no BEGIN/END LEVER MAP marker LINES; COULD NOT LOOK. "
                "This is a refusal, not agreement." % plugin_path]
    block = m.group(1)
    theirs = re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"', block)
    mine = list(IMPLANT_LEVERS) + list(IMPLANT_IDENTITY) + list(IMPLANT_TEXT) \
         + [IMPLANT_TABLE_KEY] + list(EFFECT_IDENTITY)
    missing = [x for x in mine if x not in theirs]
    extra = [x for x in theirs if x not in mine]
    out.append("P-MAP: %d name(s) in Implants.cs's lever map, %d here; %d missing there, "
               "%d extra there." % (len(theirs), len(mine), len(missing), len(extra)))
    bad = []
    if missing:
        bad.append("P-MAP: Implants.cs is missing %s" % missing)
    if extra:
        bad.append("P-MAP: Implants.cs carries %s which this file does not" % extra)
    return bad


# ---------------------------------------------------------------------------
# --selftest : controls first, then faults.  A fault case that a broken probe
# would also "pass" is not a fault case, so each pair is (inject, expect).
# ---------------------------------------------------------------------------
def selftest(dump, live, sheets, plugin_path, run_3x=False):
    passed, failed, notrun = [], [], []

    def ck(name, cond, why=""):
        (passed if cond else failed).append(name + ((" -- " + why) if why and not cond else ""))

    def skip_3x(name):
        """A retired fault case, reported by name and never passed.

        It touches neither `passed` nor `failed`, so a green --selftest cannot
        be read as having exercised the 3.x assertion. AGENTS.md."""
        notrun.append(name)

    # ---- controls -----------------------------------------------------
    out = []
    ck("C1 the unmodified tables produce no dead column", not probe_columns(dump, live, sheets, out))
    ck("C2 the unmodified tables cover every character-slot row once",
       not probe_rows(dump, sheets, out))
    ck("C3 no dropped column is written by a live rule", not probe_drop(dump, live, out))

    # ---- faults on the compaction assertion ---------------------------
    s = dict(sheets)
    h, r = sheets[sheet_name(3)]
    dead = list(h[:-1]) + ["Stunned", CONTROL_COMMENT]
    dead_rows = [list(x[:-1]) + ["", x[-1]] for x in r]
    s[sheet_name(3)] = (dead, dead_rows)
    ck("F1 a payload column zero on every one of a slot's effects is caught",
       bool(probe_columns(dump, live, s, [])))

    s = dict(sheets)
    h, r = sheets[sheet_name(1)]
    s[sheet_name(1)] = (list(h[:-1]) + ["BackstoryGroup", CONTROL_COMMENT],
                        [list(x[:-1]) + ["", x[-1]] for x in r])
    ck("F2 an ImplantModel column zero on every one of a slot's rows is caught",
       bool(probe_columns(dump, live, s, [])))

    # F3 is the Phase 6 trap itself: a rule-written column dropped for being
    # constant.  Injected by telling the dropper that nothing writes anything.
    class Blind(object):
        unscoped = []
        writes = {}
        def writes_column(self, *a):
            return False
    blind = Blind()
    _, dropped = columns_for(dump, blind, 8)
    ck("F3 with the live rules hidden, ImplantStress is dropped -- the Phase 6 trap",
       any(c == "ImplantStress" for c, _, _, _ in dropped))
    ck("F3b and with them visible it is carried",
       not any(c == "ImplantStress" for c, _, _, _ in columns_for(dump, live, 8)[1]))
    ck("F3c and P-DROP, checked against the real rules, catches the blind dropper",
       bool(probe_drop(dump, blind, [], checker=live)))

    # ---- faults on P-GONE, the assertion that replaced P-CHECK's old side --
    #
    # P-CHECK compared two live sides and could be faulted by moving one of
    # them. P-GONE compares ONE live side against a typed-in table, so its
    # faults are injected into the live side: the sheets stop writing a
    # declared triple, or write it differently: a value the 3.x rules file
    # carried, quietly no longer written.
    #
    # RETIRED FROM THE DEFAULT SUITE with the instrument they fault.
    # A fault case that still passes for a check the default suite no longer
    # runs is exactly the false green this file exists to refuse, so C4, F9 and
    # F10 are reported NOT RUN by name and run under --ruleset-3x.
    if run_3x:
        _new_ok, _ = resolve_new(sheets, dump, [], [])
        ck("C4 the sheets write every triple the deleted rules file carried",
           not check_declared_triples(_new_ok, dump, []))
        _dropped = OrderedDict((k, v) for k, v in _new_ok.items()
                               if k not in DECLARED_LAST_RULES_TRIPLES)
        ck("F9 a declared triple the sheets no longer write at all is caught -- "
           "the Phase 9a failure, on this file's own nine",
           len(check_declared_triples(_dropped, dump, [])) ==
           len(DECLARED_LAST_RULES_TRIPLES))
        _moved = OrderedDict(_new_ok)
        _k0 = list(DECLARED_LAST_RULES_TRIPLES)[0]
        _moved[_k0] = ("set", 99.0)
        ck("F10 a declared triple the sheets write with a different value is "
           "caught", bool(check_declared_triples(_moved, dump, [])))
    else:
        for _n in RULESET_3X_RETIRED_CASES:
            skip_3x(_n)

    # ---- faults on the rules-file state declaration --------------------
    #
    # The state is (expected, found). Both directions of surprise are faulted
    # here, because a missing file and a returning file are different failures
    # and neither may be silent.
    class _Live(object):
        rules_path = "<injected>"
        def __init__(self, found, expected):
            self.rules_file_found = found
            self.rules_file_expected = expected
            self.rules_file_surprise = ((found and expected == "gone")
                                        or (not found and expected == "present"))
        state_line = LiveRules.state_line
        surprise_problem = LiveRules.surprise_problem
    ck("F11 a rules file that comes back when it is declared gone is a problem",
       bool(_Live(True, "gone").surprise_problem()))
    ck("F12 a rules file that is missing when it is declared present is a problem",
       bool(_Live(False, "present").surprise_problem()))
    ck("F13 and neither declared-and-agreeing state is",
       not _Live(False, "gone").surprise_problem()
       and not _Live(True, "present").surprise_problem())
    ck("F14 the state line names what was expected and what was found, either way",
       "expected gone" in _Live(False, "gone").state_line()
       and "NOT ON DISK" in _Live(False, "gone").state_line()
       and "PRESENT" in _Live(True, "present").state_line())

    # ---- faults on the row census -------------------------------------
    s = dict(sheets)
    h, r = sheets[sheet_name(9)]
    s[sheet_name(9)] = (h, r[:-1])
    ck("F4 a missing row is caught", bool(probe_rows(dump, s, [])))
    s = dict(sheets)
    h1, r1 = sheets[sheet_name(1)]
    drone = [x for x in dump.implants if int(x[IMPLANT_TABLE_KEY]) not in SLOTS][0]
    ghost = list(r1[0]); ghost[h1.index(IMPLANT_KEY)] = drone[IMPLANT_KEY]
    s[sheet_name(1)] = (h1, r1 + [ghost])
    ck("F5 a drone module smuggled into a table is caught", bool(probe_rows(dump, s, [])))

    # ---- faults on the shared-row dispositions ------------------------
    problems, marks = [], []
    h3, r3 = sheets[sheet_name(3)]
    expand(h3, r3, sheet_name(3), problems, marks,
           dict((e, u) for e, (sh, u) in shared_rows(dump).items() if u))
    ck("F6 the shipped slot 3 sheet is not divergent", not problems, str(problems))
    ck("F7 50126 carries a blocking marker",
       any(m[0] == "blocking" and m[1] == 50126 for m in marks), str(marks))

    col = next(c for c in h3 if c not in IMPLANT_IDENTITY and c != CONTROL_COMMENT
               and c not in set(IMPLANT_LEVERS))
    div = [list(x) for x in r3]
    owners = [i for i, x in enumerate(div) if int(x[h3.index(EFFECT_KEY)]) == 50126]
    div[owners[0]][h3.index(col)] = "=1"
    div[owners[1]][h3.index(col)] = "=2"
    p2, m2 = [], []
    rules = expand(h3, div, sheet_name(3), p2, m2, {})
    ck("F8 a divergent edit on 50126 is REFUSED",
       any("DIVERGE" in x for x in p2), str(p2))
    ck("F8b and it names both owners",
       any("908" in x and "915" in x for x in p2), str(p2))
    ck("F8c and no EffectModel rule for 50126 is emitted",
       not any(r["model"] == EFFECT_MODEL and list(r["where"].values())[0] == 50126
               for r in rules))

    same = [list(x) for x in r3]
    same[owners[0]][h3.index(col)] = "=1"
    same[owners[1]][h3.index(col)] = "=1"
    p3, m3 = [], []
    rules3 = expand(h3, same, sheet_name(3), p3, m3, {})
    ck("F9 an identical edit on both owners is NOT divergence", not p3, str(p3))
    ck("F9b and emits exactly one EffectModel rule for 50126",
       len([r for r in rules3 if r["model"] == EFFECT_MODEL
            and list(r["where"].values())[0] == 50126]) == 1)

    h1, r1 = sheets[sheet_name(1)]
    p4, m4 = [], []
    expand(h1, r1, sheet_name(1), p4, m4,
           dict((e, u) for e, (sh, u) in shared_rows(dump).items() if u))
    ck("F10 50000 carries an INFORMATIONAL marker, not a blocking one",
       any(m[0] == "informational" and m[1] == 50000 for m in m4), str(m4))
    ck("F10b and nothing about 50000 is refused",
       not any("50000" in x for x in p4), str(p4))
    col1 = next(c for c in h1 if c not in IMPLANT_IDENTITY and c != CONTROL_COMMENT
                and c not in set(IMPLANT_LEVERS))
    ed = [list(x) for x in r1]
    at = next(i for i, x in enumerate(ed) if int(x[h1.index(EFFECT_KEY)]) == 50000)
    ed[at][h1.index(col1)] = "=7"
    p5, m5 = [], []
    r5 = expand(h1, ed, sheet_name(1), p5, m5,
                dict((e, u) for e, (sh, u) in shared_rows(dump).items() if u))
    ck("F11 an edit on 50000 is ALLOWED and emits its rule",
       not p5 and any(r["model"] == EFFECT_MODEL and list(r["where"].values())[0] == 50000
                      for r in r5), str(p5))

    # ---- faults on the dialect ----------------------------------------
    p6 = []
    expand(list(h3[:-1]) + ["_clone", CONTROL_COMMENT],
           [list(x[:-1]) + ["", x[-1]] for x in r3], sheet_name(3), p6)
    ck("F12 _clone in a header refuses the whole file",
       any("refused control column" in x for x in p6) , str(p6))
    p7 = []
    expand(list(h3[:-1]) + ["_serveOn", CONTROL_COMMENT],
           [list(x[:-1]) + ["", x[-1]] for x in r3], sheet_name(3), p7)
    ck("F13 _serveOn in a header refuses the whole file", bool(p7))

    bad = [list(x) for x in r3]
    bad[0][h3.index(col)] = "90x"
    p8 = []
    expand(h3, bad, sheet_name(3), p8)
    ck("F14 an unparseable cell is named, not read as blank",
       any("is not an adjustment" in x for x in p8), str(p8))
    ck("F15 blank and 0 are different answers",
       parse_adjust("") == ("none", 0.0, True) and parse_adjust("=0") == ("set", 0.0, True))
    ck("F16 a bare number is a set", parse_adjust("25") == ("set", 25.0, True))
    ck("F17 -N is an add of a negative", parse_adjust("-5") == ("add", -5.0, True))
    ck("F18 xN is a multiply", parse_adjust("x1.5") == ("multiply", 1.5, True))

    # ---- the no-payload-without-an-effect guard ------------------------
    h6, r6 = sheets[sheet_name(6)]
    pay = next(c for c in h6 if c not in IMPLANT_IDENTITY and c != CONTROL_COMMENT
               and c not in set(IMPLANT_LEVERS))
    z = [list(x) for x in r6]
    at0 = next(i for i, x in enumerate(z) if int(x[h6.index(EFFECT_KEY)]) == 0)
    z[at0][h6.index(pay)] = "=3"
    p9 = []
    expand(h6, z, sheet_name(6), p9)
    ck("F19 a payload cell on a row with no effect row is refused, not written",
       any("no EffectModel row to write" in x for x in p9), str(p9))

    # ---- the global block stays inert ----------------------------------
    allrules = []
    for name, (hh, rr) in sheets.items():
        allrules += expand(hh, rr, name, [], [], {})
    ck("F20 the sheets emit no ImplantModel rule while the unscoped multiply lives",
       not any(r["model"] == IMPLANT_MODEL for r in allrules))
    ck("F21 the sheets emit exactly the nine CritMultiBase rules",
       len(allrules) == 9 and all(r["model"] == EFFECT_MODEL and
                                  list(r["ops"].keys()) == ["set"] and
                                  list(r["ops"]["set"].keys()) == ["CritMultiBase"]
                                  for r in allrules), "%d rule(s)" % len(allrules))

    # ---- the plugin map ------------------------------------------------
    ck("F22 the plugin's lever map matches this file's", not probe_map(plugin_path, []),
       str(probe_map(plugin_path, [])))

    # F23/F24 are the regression for probe_map's own defect: its first version
    # matched the marker names ANYWHERE, so a block whose prose names its own
    # end marker was scraped four lines in and reported every name missing.
    import tempfile
    def with_text(t):
        fh = tempfile.NamedTemporaryFile("w", suffix=".cs", delete=False, encoding="utf-8")
        fh.write(t); fh.close(); return fh.name
    real = io.open(plugin_path, "r", encoding="utf-8").read()
    ck("F23 a block whose prose mentions END LEVER MAP is still scraped whole",
       "END LEVER MAP and REFUSES" in real and not probe_map(plugin_path, []))
    ck("F24 a file with no marker LINES is a refusal, not agreement",
       bool(probe_map(with_text("class X { string a = \"Cost\"; }"), [])))
    ck("F25 a plugin map missing a lever is caught",
       bool(probe_map(with_text(real.replace('"ImplantStress",', "")), [])))
    ck("F26 all eleven slots declare help text", not probe_help(plugin_path, []),
       str(probe_help(plugin_path, [])))
    lines9 = real.split("\n")
    at9 = next(i for i, l in enumerate(lines9) if l.lstrip().startswith("{ 9,"))
    end9 = next(i for i in range(at9 + 1, len(lines9))
                if lines9[i].lstrip().startswith("{ 10,"))
    ck("F27 a slot with no help text is caught",
       bool(probe_help(with_text("\n".join(lines9[:at9] + lines9[end9:])), [])))
    ck("F28 slot 8 losing its 'every implant effect' sentence is caught",
       bool(probe_help(with_text(real.replace("EVERY IMPLANT EFFECT IN", "something else")), [])))

    return passed, failed, notrun


def build_all(dump, live):
    sheets, drops = OrderedDict(), OrderedDict()
    for slot in SLOTS:
        header, rows, dropped = build_sheet(dump, live, slot)
        sheets[sheet_name(slot)] = (header, rows)
        drops[sheet_name(slot)] = dropped
    return sheets, drops


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--game", help="game root (holds BepInEx\\config)")
    ap.add_argument("--dump", default=os.path.join("sheets", "raw"),
                    help="dumped CSV directory (default sheets\\raw)")
    ap.add_argument("--plugin", default=os.path.join("mods", "CKFHardMode", "Implants.cs"))
    ap.add_argument("--emit", action="store_true", help="write the eleven CSVs")
    ap.add_argument("--check", action="store_true", help="prove double application is a no-op")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--ruleset-3x", dest="ruleset_3x", action="store_true",
                    help="ALSO run the retired P-GONE assertion and the three "
                         "selftest cases that fault it. Retired from the "
                         "default suite %s %s; what it prints is a divergence "
                         "from the 3.0 ruleset, which is not by itself a defect."
                         % (RULESET_3X_RETIRED_BY, RULESET_3X_RETIRED_ON))
    a = ap.parse_args(argv)

    dump = Dump(a.dump)
    config_dir = os.path.join(a.game, "BepInEx", "config") if a.game else None
    if config_dir is None:
        sys.stderr.write(
            "REFUSED  --game is required.\n"
            "\n"
            "Every probe in this script reads the live rules and overlays: P-DROP asks\n"
            "whether anything writes a dropped column, P-CHECK compares the converted\n"
            "triples against the shipped values, D-GLOBAL reads the unscoped rule and\n"
            "D-CLAMP re-derives the floor. With no config directory there is nothing to\n"
            "read and a green run would mean COULD NOT LOOK, not agreement.\n"
            "\n"
            "  python scripts\\implants.py --selftest --game \"<game root>\"\n"
            "\n"
            "This path used to fall back to LiveRules(\".\", rules_path=os.devnull),\n"
            "which read an empty string and died in json.loads with an uncaught\n"
            "JSONDecodeError. It had never run. The other three converters\n"
            "(cyberweapons.py, gear_classes.py, rules_to_overlays.py) already refuse\n"
            "here; this one now says the same thing.\n")
        return 2
    live = LiveRules(config_dir)
    sheets, drops = build_all(dump, live)

    out, problems = [], []
    out.append("implants.py -- %d ImplantModel row(s), %d in character slots 1-11, "
               "%d drone-module rows in slots 100-107 that get no table."
               % (len(dump.implants),
                  sum(len(dump.rows_for(s)) for s in SLOTS),
                  len([r for r in dump.implants if int(r[IMPLANT_TABLE_KEY]) not in SLOTS])))
    out.append(live.state_line())
    for p, n in live.sources:
        out.append("  read %s (%d entries)" % (os.path.basename(p), n))
    _surprise = live.surprise_problem()
    if _surprise:
        problems.append(_surprise)

    for slot in SLOTS:
        name = sheet_name(slot)
        header, rows = sheets[name]
        text = csv_text(header, rows)
        eids = dump.effect_ids_for(slot)
        out.append("  %s: %d row(s), %d column(s), %d byte(s); %d effect row(s); "
                   "%d column(s) dropped" % (name, len(rows), len(header),
                                             len(text.encode("utf-8")), len(eids),
                                             len(drops[name])))

    problems += probe_columns(dump, live, sheets, out)
    problems += probe_rows(dump, sheets, out)
    problems += probe_drop(dump, live, out)
    problems += probe_map(a.plugin, out)
    problems += probe_help(a.plugin, out)

    marks = []
    if a.check:
        if not config_dir:
            problems.append("--check needs --game: it compares against the live rules file. "
                            "COULD NOT LOOK is not agreement.")
        else:
            p, marks, _ = do_check(dump, config_dir, sheets, out,
                                   run_3x=a.ruleset_3x)
            problems += p
    problems += probe_shared(dump, marks or
                             (lambda: [m for m in _collect_marks(dump, sheets)])(), out)

    if a.emit:
        if not config_dir:
            problems.append("--emit needs --game")
        else:
            d = os.path.join(config_dir, "ckf.hardmode.d")
            for slot in SLOTS:
                name = sheet_name(slot)
                header, rows = sheets[name]
                with io.open(os.path.join(d, name), "w", encoding="utf-8", newline="") as fh:
                    fh.write(csv_text(header, rows))
                out.append("  wrote %s" % name)

    if a.selftest:
        passed, failed, notrun = selftest(dump, live, sheets, a.plugin,
                                          run_3x=a.ruleset_3x)
        out.append("selftest: %d passed, %d failed, %d not run"
                   % (len(passed), len(failed), len(notrun)))
        for f in failed:
            out.append("  FAIL %s" % f)
        # NAMED, NOT COUNTED AWAY. A reader has to see WHICH coverage is not
        # running without opening this file.
        for n in notrun:
            out.append("  NOT RUN %s" % n)
            out.append("          %s" % RULESET_3X_RETIRED_WHY)
        problems += failed

    print("\n".join(out))
    if problems:
        print("\n%d problem(s):" % len(problems))
        for p in problems:
            print("  " + p)
        return 1
    print("\n0 problem(s).")
    return 0


def _collect_marks(dump, sheets):
    marks, unshown = [], dict((e, u) for e, (sh, u) in shared_rows(dump).items() if u)
    for name, (h, r) in sheets.items():
        expand(h, r, name, [], marks, unshown)
    return marks


if __name__ == "__main__":
    sys.exit(main())


# ---------------------------------------------------------------------------
# THE VALIDATOR ADAPTER.
#
# scripts/validate_rules.py imports this module rather than transcribing the
# expansion a third time.  The shape matches scripts/cyberweapons.py's on
# purpose: SHEET_NAMES, Problem, read_sheet and expand, so validate_rules.py's
# lever-sheet dispatch grows one branch and not one dialect.
#
# WHY THE VALIDATOR NEEDS THIS AT ALL.  A filename it does not recognise as a
# lever sheet is parsed as a DIRECT OVERLAY, and the first thing that happens
# then is that the filename before the first dot becomes a model name:
# "implants-slot08.csv" would build 26 rules against a table called
# "implants-slot08Model".  That does not fail loudly.  Its only symptom is an
# orphan warning long afterwards (docs/overlays.md), which is why
# is_lever_sheet() is a list of the expanders' OWN declared names.
# ---------------------------------------------------------------------------
SHEET_NAMES = frozenset(sheet_name(s) for s in SLOTS)


class Problem(Exception):
    pass


class Emitted(object):
    __slots__ = ("model", "key", "rid", "ops")

    def __init__(self, model, key, rid, ops):
        self.model, self.key, self.rid, self.ops = model, key, rid, ops


def read_sheet(path):
    """(header, rows) from one slot table, or raise Problem.  A read that fails
    RAISES; it is never reported as an empty sheet."""
    try:
        with io.open(path, "r", encoding="utf-8-sig", newline="") as fh:
            rows = list(csv.reader(fh))
    except Exception as e:
        raise Problem("could not read %s: %s. Nothing here is checked against it; "
                      "this is a refusal, not an empty sheet." % (path, e))
    if len(rows) < 2:
        raise Problem("%s has %d line(s); a header and at least one data row are "
                      "needed." % (os.path.basename(path), len(rows)))
    return [h.strip() for h in rows[0]], rows[1:]


def expand_sheet(path, report=None):
    """Expand one slot table exactly as Implants.Expand does at load.
    Appends refusal text to `report`; returns a list of Emitted."""
    report = report if report is not None else []
    header, rows = read_sheet(path)
    name = os.path.basename(path)
    rules = expand(header, rows, name, report, [], {})
    out = []
    for r in rules:
        key, rid = list(r["where"].items())[0]
        ops = []
        for kind, cols in r["ops"].items():
            for col, val in cols.items():
                ops.append((kind, col, val))
        out.append(Emitted(r["model"], key, rid, ops))
    return out
