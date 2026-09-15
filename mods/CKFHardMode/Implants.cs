// Implants — the eleven implant slot tables, expanded into rules at load.
//
// WHY ELEVEN TABLES AND NOT ONE
//
// ImplantModel is 198 rows. 178 of them sit in character slots 1-11 and the
// other 20 are drone modules in slots 100-107, which get NO TABLE at all: per
// David, drones are not in the game yet, so collateral effect on them is
// accepted and the question is revisited when they ship (design.md section 7).
//
// One table would be about two thirds empty, because the live columns follow
// the slot and barely overlap. ArmorRestriction is live ONLY in slot 1.
// BackstoryGroup only in slot 5. ImplantConflictId only in slots 2 and 4.
// MatrixEffectId only in 1, 3, 4 and 11. InstallJobId only in 1-4 and 11.
// [measured, sheets\raw 2026-09-12] The lever-sheets spec forbids a column
// dead for its own rows, so the slot is the table.
//
// ImplantSlot is the table key; ImplantClass is a COLUMN. The two are not the
// same cut: EVERY slot holds more than one class — slot 2 holds seven of them
// — and one class, 16 "E-Inhibitor", spans two slots. See the correction in
// scripts\implants.py's header; design.md section 7 states the relation the
// wrong way round and the sheets follow the measurement.
//
// ONE ROW IS TWO ROWS IN TWO TABLES
//
// The same shape Cyberweapons.cs has, with different halves. An implant row
// carries its own install economics in ImplantModel and points at an
// EffectModel row through ImplantEffectId, which is what the implant actually
// DOES. A player editing "Apex Optimizer" is editing both. So a sheet row
// becomes an ImplantModel rule keyed on ImplantTypeId and an EffectModel rule
// keyed on that row's ImplantEffectId, and a row that sets nothing on one side
// emits only the other. A row whose ImplantEffectId is 0 has no second half at
// all — 79 of the 178 are like that — and a payload cell on such a row is
// REFUSED rather than written somewhere, because there is nowhere to write it.
//
// NO TalentModel COLUMN IS HERE AND THAT IS DELIBERATE
//
// Slot 6 is the claws (ImplantClass 27, 16 rows, every ImplantEffectId 0) and
// slot 8 holds the optical lasers (ImplantClass 32, 18 rows). Both are also
// the subjects of cyberweapons-claws.csv and cyberweapons-lasers.csv. The
// columns do not collide because the split is by MEANING: the implant table
// carries install economics and the implant-side effect, the cyberweapon
// sheets carry the WeaponModel and TalentModel combat stats (design.md section
// 7). `Cost` exists in both and means different things — the implant's clinic
// price runs 80-10200, the weapon's valuation 50-700 — so the GUI labels this
// one "Install cost" and the cyberweapon one "Item value".
//
// A TalentModel column here would be worse than redundant. The five
// TalentModel rules that reach implant talents (80007-80010, 80027-80038) are
// already the laser sheet's rows, claimed there, and two sheets writing one
// (model, id) is load order, not a merge.
//
// THE NINE CritMultiBase RULES LIVE IN SLOT 8
//
// Display-Link, Combat DisplayLink, Target Optimizer, Apex DisplayLink, Apex
// Optimizer and Brightshot Optic 1-4. Each sets EffectModel CritMultiBase from
// a shipped 25 to 0 and leaves CritRate and RangedAttack alone. [measured]
// AFTER THEY RUN, CritMultiBase IS ZERO ON EVERY IMPLANT EFFECT IN THE GAME,
// because those nine were the only implant effects that had one — exactly nine
// of the 98 referenced effects carry a non-zero CritMultiBase and all nine are
// these [measured]. That sentence is not visible from the nine rows, so it is
// in the slot 8 help text as well as here.
//
// Three rows keep a crit multiplier and the sheets SHOW them rather than
// leaving them as an absence: Range Finder at CritMultiStealth 25 (slot 8),
// Chameleon Sheathe at 20 and Chameleon S-Mesh at 25 (slot 1). CritMultiStealth
// is carried by both tables, so all three are visible with their values.
//
// PHASE 9, RESOLVED — THE GLOBAL BLOCK IS APPLIED NOW, AND THIS CLASS STILL
// SAYS SO BY NAME. The heading and the three paragraphs below it are LEFT
// STANDING, verbatim, because they are the reason RefuseGlobal existed and a
// reader who meets ExpandGlobal needs what it replaced. Read them with these
// four corrections:
//
//   * "ckf.hardmode.rules.json is not deleted until Phase 9" — the one
//     unscoped ImplantModel rule IS deleted, in the SAME COMMIT that turned
//     RefuseGlobal into ExpandGlobal. The two halves are not separable:
//     `multiply` is not idempotent, so rule + emitter applies x0.5 twice and
//     rule-gone + refusal applies it zero times. Only the pair leaves every
//     shipped value where it was. That file went 270 rules to 269 [measured].
//   * "RefuseGlobal below emits nothing and LOGS THAT IT EMITTED NOTHING" —
//     the method is ExpandGlobal, it emits ONE unscoped ImplantModel rule
//     carrying the three multipliers, and it logs the three numbers it read.
//   * "ITS REACH IS ACCEPTED, NOT FIXED" is UNCHANGED and still binding. The
//     emitted rule carries no `where` either, so it reaches the same 198 rows
//     including the 20 drone modules. Scoping it would be a FIFTH balance
//     deviation and there are exactly four.
//   * "AND THE clampMin IS GONE ON PURPOSE" is UNCHANGED and still binding.
//     ExpandGlobal does not emit it. That is sanctioned deviation D3, the
//     floor binds on 0 of the 198 rows, and scripts\implants.py's D-CLAMP
//     re-derives that measurement on every run rather than trusting this.
//
// WHAT IS NOT CORRECTED, because it did not change: the numbers themselves.
// Cost x0.5, InstallTime x0.5, ImplantStress x3 on all 198 rows, before and
// after. Only where they come from moved.
//
// THE GLOBAL BLOCK IS STILL NOT APPLIED, AND THIS CLASS SAYS SO BY NAME
//
// implants-global.json carries the three multipliers from the ONE unscoped
// ImplantModel rule in ckf.hardmode.rules.json. That rule is a MULTIPLY, and
// ckf.hardmode.rules.json is not deleted until Phase 9, so anything emitted
// here would be applied on top of it: Cost and InstallTime would land on x0.25
// and ImplantStress on x9, across all 198 rows. That is a balance change on
// every implant in the game and proposal.md's non-goals allow four, all spoken
// for. So RefuseGlobal below emits nothing and LOGS THAT IT EMITTED NOTHING,
// with the precondition named — a file that is read and not applied, silently,
// is the instrument AGENTS.md section 3 is about.
//
// ITS REACH IS ACCEPTED, NOT FIXED. The rule has no `where`, so it reaches all
// 198 rows INCLUDING THE 20 DRONE MODULES NO TABLE SHOWS. Adding
// `where ImplantSlot <= 11` would change Cost, InstallTime and ImplantStress on
// 20 rows that ship today, which is a balance change on rows nobody can play
// with yet. Do not scope it (design.md section 7, tasks.md Phase 7).
//
// AND THE clampMin IS GONE ON PURPOSE. The shipped rule carries
// `clampMin ImplantStress 1`. It NEVER BINDS: ImplantStress is 1 on 197 rows
// (1 -> 3) and 5 on Quantum Rider (5 -> 15), so nothing lands below 1 for it to
// lift [measured]. David removed it from implants-global.json and PHASE 9'S
// MIGRATOR MUST NOT CARRY IT ACROSS. The measurement, not the preference, is
// what makes dropping it safe, and scripts\implants.py's D-CLAMP re-derives it
// on every run rather than trusting this comment.
//
// KEYS ARE (table, id), NEVER id ALONE. EffectModel 80007 and TalentModel
// 80007 are different rows, and the laser sheet owns the second one.
// design.md section 11 names three such pairs and Phase 6 found a fourth;
// table-wide the overlap is 221 ids between TalentModel and EffectModel and
// 130 between EffectModel and MatrixEffectModel. [measured]

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace CKFHardMode
{
    internal static class Implants
    {
        internal const string ImplantModel = "ImplantModel";
        internal const string EffectModel  = "EffectModel";

        internal const string GlobalFile = "implants-global.json";

        // BEGIN LEVER MAP — scripts\implants.py's probe_map() scrapes between
        // this marker and END LEVER MAP and REFUSES if this table and its own
        // disagree, so the two transcriptions cannot drift in silence. It
        // refuses rather than guessing when it cannot find the markers: "could
        // not look" is not "they agree". Do not reformat without updating that
        // reader.
        //
        // These are the CANDIDATE levers. Which of them a given sheet actually
        // carries is decided per slot by the generator from that slot's own
        // rows and arrives here as the file header — there is no hand list per
        // slot, because a hand list is the failure mode Phase 5 deleted. This
        // class reads the header it is given and only needs to know which side
        // of the split each name is on.
        //
        // ImplantStress IS HERE AND IT IS CONSTANT IN THE SHIPPED DATA — 1 on
        // 197 of the 198 rows, so constant inside every slot. "No column dead
        // for its own rows" would drop it, and dropping it would hide the only
        // ImplantModel lever the mod actually pulls. That requirement is about
        // a column carrying no lever; A COLUMN BEING CONSTANT SAYS NOTHING
        // ABOUT WHETHER A RULE WRITES IT. Phase 6 nearly shipped a 16-column
        // laser sheet on exactly this mistake. Cost and InstallTime are in the
        // same position and are varied enough to survive anyway.
        /// <summary>Keys the ImplantModel rule.</summary>
        internal const string ImplantKey = "ImplantTypeId";
        /// <summary>The sheet column that names this row's effect. It keys the
        /// EffectModel rule; the game column it resolves against is EffectId.
        /// The same role TalentId plays on the cyberweapon sheets.</summary>
        internal const string EffectKey = "ImplantEffectId";
        internal const string EffectIdColumn = "EffectId";

        internal static readonly string[] ImplantLevers =
        {
            "ImplantLevel", "ImplantConflictId", "ImplantStress", "ImplantDVMult",
            "ImplantDVScore", "Deactivated", "MatrixEffectId", "ArmorRestriction",
            "InstallTime", "BackstoryGroup", "InstallJobId", "ImplantTalentId",
            "ServiceOptionId", "Rarity", "PowerLevel", "Cost",
        };

        // Identity: shown, NEVER parsed as an adjustment — which is why an
        // ImplantTypeId of 3200 does not become "set ImplantTypeId to 3200".
        // Phase 6 hit that trap the other way round: the editor's first count
        // of "override cells filled" on the claw sheet came back 32 and they
        // were all identity.
        internal static readonly string[] Identity =
        {
            "ImplantName", ImplantKey, "ImplantClass", EffectKey,
        };

        // Display-only, carried by no table: two localisation keys and two
        // columns that repeat the class name on every row of the class.
        internal static readonly string[] DisplayOnly =
        {
            "ImplantDesc", "ImplantClassName", "ImplantClassDesc",
        };

        // The table key itself, carried by no table.
        internal const string SlotColumn = "ImplantSlot";

        // EffectModel identity. EffectClassification is 7 on all 98 referenced
        // effects and carries no information; design.md section 7 names it with
        // Duration, Instant, EffectHealType and Heals, and those four are
        // dropped by the ordinary all-zero test rather than by being listed.
        internal static readonly string[] EffectIdentity =
        {
            "EffectName", EffectIdColumn, "EffectClassification",
        };
        // END LEVER MAP

        // ---- per-slot help text ------------------------------------------
        //
        // THE SENTENCES THAT ARE NOT VISIBLE FROM THE ROWS. Each is printed
        // once per launch beside that sheet's load line, because a fact a
        // player needs in order to read the grid correctly is useless in a
        // design document they do not have.
        //
        // THE SCHEMA OWNS THE OTHER HALF. schema\*.schema.json's `doc` array is
        // what the config editor renders as help, and schema\ is not this
        // phase's directory to write (separate agents own it). These strings
        // are the text that belongs there, verbatim, so the schema owner
        // transcribes rather than re-derives.
        internal static readonly Dictionary<int, string> SlotHelp = new Dictionary<int, string>
        {
            { 1, "Slot 1 is the only slot where ArmorRestriction is live (6 of the 198 "
               + "rows carry a 1; all of them are here). Two rows KEEP a crit multiplier "
               + "and no rule touches either: Chameleon Sheathe at CritMultiStealth 20 "
               + "and Chameleon S-Mesh at 25. Dermal Plating 1's effect row, EffectModel "
               + "50000, is SHARED with all 20 drone modules, which have no table — an "
               + "edit to its payload reaches them too. That marker informs; it does not "
               + "block, because there is only one editable owner and divergence is "
               + "therefore impossible." },
            { 2, "ImplantConflictId is live in slots 2 and 4 only (16 rows carry a 1). "
               + "This slot holds seven different ImplantClass values, including the "
               + "single Pain Inhibitors row of class 16 — the one class that spans two "
               + "slots, its other six rows being the CombatLinks in slot 3." },
            { 3, "ImplantLevel IS NOT A TIER INDEX HERE, so these rows are in dump file "
               + "order rather than sorted. All four CombatLink rows, both M-Grade "
               + "CombatLink rows and all five Cortex Wetgates rows are ImplantLevel 1; "
               + "no column orders those tiers. Do not read the order as a ladder. "
               + "EffectModel 50126 is SHARED by CombatLink 4 and M-Grade CombatLink: "
               + "both are editable here, so giving them different payloads is refused "
               + "and the refusal names both. See docs\\gotchas.md for row 904's "
               + "self-pointing Deactivated, which ships as-is." },
            { 4, "ImplantConflictId is live in slots 2 and 4 only. MatrixEffectId is live "
               + "in slots 1, 3, 4 and 11 only." },
            { 5, "BackstoryGroup is live in slot 5 and nowhere else — exactly one row of "
               + "the 198 carries a 1. No row in this slot has a talent." },
            { 6, "These 25 rows include the 16 cyberweapon claws (ImplantClass 27). The "
               + "claws are ALSO in cyberweapons-claws.csv, and the columns do not "
               + "collide: this table carries the install economics and the implant-side "
               + "effect, that sheet carries the weapon and talent combat stats. Cost "
               + "here is the CLINIC PRICE (80-10200 across the table); Cost there is the "
               + "item's valuation (50-700). Every class-27 row has ImplantEffectId 0, so "
               + "its payload cells are blank and there is nothing here to edit for a "
               + "claw's effect." },
            { 7, "ImplantLevel IS NOT A TIER INDEX HERE either, so these rows are in dump "
               + "file order. SynthMuscle 3, SynthMuscle 4 and both SynthBuilder ROM rows "
               + "are all ImplantLevel 3. Do not read the order as a ladder." },
            { 8, "THE NINE CritMultiBase CELLS SET TO 0 ARE THE WHOLE OF THE MOD'S CRIT "
               + "DAMAGE REMOVAL. Display Link, Combat DisplayLink, Target Optimizer, "
               + "Apex DisplayLink, Apex Optimizer and Brightshot Optic 1-4 each ship "
               + "CritMultiBase 25 and are set to 0; CritRate and RangedAttack are left "
               + "alone. AFTER THEY RUN, CritMultiBase IS ZERO ON EVERY IMPLANT EFFECT IN "
               + "THE GAME — those nine were the only implant effects in the whole table "
               + "that had one, and that is not visible from these nine rows. Range "
               + "Finder is the exception that survives: it keeps CritMultiStealth 25 and "
               + "no rule touches it. These 26 rows include the 18 optical lasers "
               + "(ImplantClass 32), which are also in cyberweapons-lasers.csv; Cost here "
               + "is the clinic price, Cost there is the item's valuation." },
            { 9, "MatrixEffectId, InstallJobId, ImplantConflictId, ArmorRestriction and "
               + "BackstoryGroup are all zero on every row of this slot and are not "
               + "shown. 14 of the 18 rows have ImplantEffectId 0." },
            { 10, "Rarity is 0 on every row of this slot and is not shown. See "
                + "docs\\gotchas.md for row 3801's Deactivated = -2, which ships as-is." },
            { 11, "One row, DRAWN AS A GRID like every other implant slot. CONSTANCY "
                + "IS VACUOUS AT ONE ROW: every column is trivially constant, so the "
                + "usual 'omit a column constant across the table's own rows' rule would "
                + "empty this table entirely. Only the all-zero test is applied here, and "
                + "that exemption is unchanged. CORRECTION, 2026-09-14: this sentence read "
                + "\"One row, so this renders as a form rather than a grid\", and the "
                + "editor drew the row as a stack of labelled values instead of a table. "
                + "David opened the editor in a browser on 2026-09-14, looked at the page "
                + "that produced, and overruled it; slot 11 is a table like the other ten. "
                + "THE ONE-ROW CONSTANCY EXEMPTION IS A DIFFERENT RULE AND SURVIVES THE "
                + "REVERSAL -- constant across one row is arithmetic, not an observation. "
                + "See docs\\gotchas.md for Quantum Rider's MatrixEffectId 50014, which "
                + "has no MatrixEffectModel row and ships as-is." },
        };

        internal static readonly Dictionary<string, string> RefusedControl =
            new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase)
        {
            { "_clone", "a clone is never emitted from a lever sheet. RowClone.cs is "
                      + "the path that produces a mission that will not load, and "
                      + "design.md section 11 makes splitting a shared row an explicit "
                      + "per-row opt-in that this dialect does not carry." },
            { "_serveOn", "serveOn belongs to a clone rule, and these sheets emit none." },
        };

        private static readonly HashSet<string> IdentitySet =
            new HashSet<string>(Identity, StringComparer.Ordinal);
        private static readonly HashSet<string> ImplantLeverSet =
            new HashSet<string>(ImplantLevers, StringComparer.Ordinal);

        /// <summary>True for implants-slot01.csv .. implants-slot11.csv.
        /// Overlays.Load asks BEFORE it derives a table name from the filename:
        /// TableOf("implants-slot08.csv") would yield "implants-slot08Model" and
        /// every row would build a rule against a table that does not exist,
        /// surfacing only as an orphan warning long afterwards.</summary>
        internal static bool Owns(string fileName)
        {
            if (fileName == null) return false;
            if (!fileName.StartsWith("implants-slot", StringComparison.OrdinalIgnoreCase)) return false;
            if (!fileName.EndsWith(".csv", StringComparison.OrdinalIgnoreCase)) return false;
            var mid = fileName.Substring("implants-slot".Length,
                                         fileName.Length - "implants-slot".Length - 4);
            int slot;
            return mid.Length == 2
                && int.TryParse(mid, NumberStyles.None, CultureInfo.InvariantCulture, out slot)
                && slot >= 1 && slot <= 11;
        }

        // ---- the (model, id) registry ---------------------------------------
        //
        // (table, id), never id alone. Static rather than per-file so the
        // eleven sheets cannot both claim one row, and reset at the head of
        // each Overlays.Load walk so a second load in one process does not
        // inherit the first walk's claims and refuse everything.
        private static readonly Dictionary<string, string> Claimed =
            new Dictionary<string, string>(StringComparer.Ordinal);

        private static string KeyOf(string model, long id) =>
            model + " " + id.ToString(CultureInfo.InvariantCulture);

        internal static void Reset() { Claimed.Clear(); }

        private sealed class Half
        {
            internal readonly Dictionary<string, JsonElement> Set =
                new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            internal readonly Dictionary<string, JsonElement> Multiply =
                new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            internal readonly Dictionary<string, JsonElement> Add =
                new Dictionary<string, JsonElement>(StringComparer.Ordinal);
            internal bool Any => Set.Count > 0 || Multiply.Count > 0 || Add.Count > 0;
        }

        private sealed class Parsed
        {
            internal int Line;
            internal long ImplantId;
            internal long EffectId;
            internal Half Implant = new Half();
            internal Half Effect  = new Half();
            /// <summary>Raw payload cell text by column, for the divergence
            /// comparison. Raw rather than parsed, so "=0" and "0" are told
            /// apart the way a player typed them.</summary>
            internal readonly Dictionary<string, string> PayloadCells =
                new Dictionary<string, string>(StringComparer.Ordinal);
        }

        /// <summary>Read one slot table and hand every rule it produces to
        /// <paramref name="adopt"/>. Returns the number of RULES emitted; one
        /// sheet row can produce two, one or none.</summary>
        internal static int Expand(string path, Action<Rule> adopt)
        {
            var name = Path.GetFileName(path);

            string[] lines;
            try { lines = File.ReadAllLines(path); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Implants: could not read {path}: {e.Message}. NO rule "
                    + "is emitted from this sheet. This is a refusal, not an empty answer: "
                    + "how many rows it holds is not known, because nothing read it.");
                return 0;
            }
            if (lines.Length < 2)
            {
                Plugin.Log.LogWarning($"Implants: {name} has {lines.Length} line(s); a header "
                    + "and at least one data row are needed. No rule emitted.");
                return 0;
            }

            var header = Overlays.SplitLine(lines[0], ',').Select(h => h.Trim()).ToArray();

            // REFUSED CONTROL COLUMNS, tested before anything is parsed. The
            // whole file is refused rather than the column ignored: a sheet
            // carrying a clone column was authored by something that believed
            // clones come out of here, and the rest of its rows are not more
            // trustworthy than that one.
            foreach (var h in header)
            {
                string why;
                if (!RefusedControl.TryGetValue(h, out why)) continue;
                Plugin.Log.LogError($"Implants: {name} header carries the control column "
                    + $"'{h}', which this dialect REFUSES: {why} NO rule is emitted from "
                    + "this sheet at all.");
                return 0;
            }

            int iAt = Array.IndexOf(header, ImplantKey);
            int eAt = Array.IndexOf(header, EffectKey);
            if (iAt < 0 || eAt < 0)
            {
                Plugin.Log.LogError($"Implants: {name} has no {ImplantKey} column "
                    + $"({(iAt < 0 ? "missing" : "present")}) or no {EffectKey} column "
                    + $"({(eAt < 0 ? "missing" : "present")}) (header: "
                    + string.Join(", ", header) + "). One row is two rows in two tables and "
                    + "both keys are needed to split it, so NO rule is emitted — not even "
                    + "the half that could be built.");
                return 0;
            }

            // A header column that is neither identity, a known ImplantModel
            // lever, a control column nor a plausible EffectModel payload name
            // cannot be told from a payload column here — this class does not
            // hold the EffectModel schema. So the split is: a name in
            // ImplantLevers writes ImplantModel, anything else that is not
            // identity or control writes EffectModel, and a misspelling
            // surfaces repo-side as an unknown column from validate_rules.py
            // rather than being silently dropped here. Named at load anyway.
            var payloadColumns = header
                .Where(h => h.Length > 0 && !IdentitySet.Contains(h)
                         && !ImplantLeverSet.Contains(h)
                         && !h.StartsWith("_", StringComparison.Ordinal))
                .ToArray();

            int rows = 0, refused = 0, cells = 0, blankRows = 0;
            var parsed = new List<Parsed>();

            for (int i = 1; i < lines.Length; i++)
            {
                if (string.IsNullOrWhiteSpace(lines[i])) continue;
                rows++;
                var c = Overlays.SplitLine(lines[i], ',');

                long implantId, effectId;
                if (iAt >= c.Length || eAt >= c.Length
                    || !long.TryParse((c[iAt] ?? "").Trim(), NumberStyles.Integer,
                                      CultureInfo.InvariantCulture, out implantId)
                    || !long.TryParse((c[eAt] ?? "").Trim(), NumberStyles.Integer,
                                      CultureInfo.InvariantCulture, out effectId))
                {
                    // BOTH HALVES, or neither. Emitting the ImplantModel half
                    // from a row whose effect id is unreadable would leave an
                    // implant with a new price and its old effect, which is a
                    // configuration nobody authored.
                    Plugin.Log.LogWarning($"Implants[{name}:{i + 1}]: {ImplantKey}="
                        + $"'{(iAt < c.Length ? c[iAt] : "<short row>")}' / {EffectKey}="
                        + $"'{(eAt < c.Length ? c[eAt] : "<short row>")}' is not a pair of "
                        + "integer ids. The WHOLE row is skipped, both halves of it.");
                    refused++;
                    continue;
                }

                var p = new Parsed { Line = i + 1, ImplantId = implantId, EffectId = effectId };
                for (int h = 0; h < header.Length && h < c.Length; h++)
                {
                    var col = header[h];
                    if (col.Length == 0 || IdentitySet.Contains(col)
                        || col.StartsWith("_", StringComparison.Ordinal)) continue;

                    bool isImplant = ImplantLeverSet.Contains(col);
                    if (!isImplant) p.PayloadCells[col] = (c[h] ?? "").Trim();

                    bool ok;
                    var adj = MissionRewards.Adjust.Parse(c[h], out ok);
                    if (!ok)
                    {
                        // THREE-STATE. A cell like "90x" parses to "no
                        // operation" under a two-state reader and is
                        // indistinguishable from a blank — a tuning change that
                        // silently did not happen.
                        Plugin.Log.LogWarning($"Implants[{name}:{i + 1}]: implant "
                            + $"{implantId}, column {col}: '{c[h]}' is not an adjustment — "
                            + "expected blank, =N, +N, -N or xN. The cell is ignored; the "
                            + "rest of the row still applies.");
                        refused++;
                        continue;
                    }
                    if (adj.Kind == MissionRewards.AdjustKind.None) continue;   // blank

                    if (!isImplant && effectId == 0)
                    {
                        // NOWHERE TO WRITE IT. 79 of the 178 character-slot rows
                        // have ImplantEffectId 0. Writing this cell would need an
                        // EffectModel row that does not exist, and picking one
                        // would be an invention.
                        Plugin.Log.LogWarning($"Implants[{name}:{i + 1}]: implant "
                            + $"{implantId} has {EffectKey} 0 — no EffectModel row — so the "
                            + $"payload cell {col}='{c[h]}' has nowhere to go and is "
                            + "REFUSED. It is not written anywhere and it is not silently "
                            + "dropped either: this line is the whole record of it.");
                        refused++;
                        continue;
                    }

                    var half = isImplant ? p.Implant : p.Effect;
                    var el = Num(adj.Value);
                    switch (adj.Kind)
                    {
                        case MissionRewards.AdjustKind.Set:      half.Set[col] = el; break;
                        case MissionRewards.AdjustKind.Multiply: half.Multiply[col] = el; break;
                        case MissionRewards.AdjustKind.Add:      half.Add[col] = el; break;
                    }
                    cells++;
                }
                if (!p.Implant.Any && !p.Effect.Any) blankRows++;
                parsed.Add(p);
            }

            // ---- reconcile the payload halves that share an effect row -------
            //
            // implants-slot03.csv ships exactly this: CombatLink 4 (908) and
            // M-Grade CombatLink (915) both carry ImplantEffectId 50126, so
            // their payload halves are TWO EDITORS OF ONE EffectModel ROW.
            //
            // Reconciled HERE, before any rule is built, rather than by letting
            // the (model, id) registry reject whichever row arrived second:
            // that would make the surviving edit depend on row order, and it
            // could not name both owners, which is what design.md section 11
            // requires the refusal to do.
            //
            // Identical payloads — including both blank, which is today — are
            // NOT divergence. One rule is emitted and the sharing is marked.
            var byEffect = new Dictionary<long, List<Parsed>>();
            foreach (var p in parsed)
            {
                if (p.EffectId == 0) continue;
                List<Parsed> l;
                if (!byEffect.TryGetValue(p.EffectId, out l)) byEffect[p.EffectId] = l = new List<Parsed>();
                l.Add(p);
            }
            var blocked = new HashSet<long>();
            int sharedMarks = 0;
            foreach (var kv in byEffect.OrderBy(k => k.Key))
            {
                if (kv.Value.Count < 2) continue;
                sharedMarks++;
                var owners = string.Join(", ", kv.Value.Select(
                    p => $"{p.ImplantId} (row {p.Line})"));
                var divergent = payloadColumns.Where(col =>
                    kv.Value.Select(p => p.PayloadCells.ContainsKey(col) ? p.PayloadCells[col] : "")
                            .Distinct(StringComparer.Ordinal).Count() > 1).ToList();
                if (divergent.Count > 0)
                {
                    blocked.Add(kv.Key);
                    Plugin.Log.LogError($"Implants: {name} — {EffectIdColumn} {kv.Key} is "
                        + $"SHARED by {kv.Value.Count} rows of this sheet ({owners}) and they "
                        + $"DIVERGE on {string.Join(", ", divergent)}. One EffectModel row "
                        + "cannot hold two payloads, so NO EffectModel rule is emitted for "
                        + $"{kv.Key} at all — neither owner's version wins. Splitting it is "
                        + "an explicit per-row _clone opt-in (design.md section 11) and "
                        + "nothing has opted in; _clone in this header refuses the whole "
                        + "file. The ImplantModel halves of both rows still apply: they are "
                        + "different rows and do not collide.");
                    refused++;
                }
                else
                {
                    Plugin.Log.LogInfo($"Implants: {name} — {EffectIdColumn} {kv.Key} is "
                        + $"SHARED by {kv.Value.Count} rows of this sheet ({owners}). Both "
                        + "are editable, so the two payload halves CAN diverge; they are "
                        + "identical here, so one rule is emitted and an edit to it reaches "
                        + "both owners. A divergent edit is refused and names both.");
                }
            }

            // ---- build ------------------------------------------------------
            int emitted = 0, implantRules = 0, effectRules = 0;
            var emittedEffects = new HashSet<long>();
            foreach (var p in parsed)
            {
                for (int side = 0; side < 2; side++)
                {
                    var model = side == 0 ? ImplantModel : EffectModel;
                    var half  = side == 0 ? p.Implant : p.Effect;
                    var id    = side == 0 ? p.ImplantId : p.EffectId;
                    if (!half.Any) continue;
                    if (side == 1)
                    {
                        if (blocked.Contains(id)) continue;
                        if (!emittedEffects.Add(id)) continue;   // identical, already emitted
                    }

                    var key = KeyOf(model, id);
                    string already;
                    if (Claimed.TryGetValue(key, out already))
                    {
                        Plugin.Log.LogWarning($"Implants[{name}:{p.Line}]: ({model}, {id}) is "
                            + $"already written by {already}. One row, one key — two rows "
                            + "writing one key is load order, not a merge, so this one is "
                            + "REFUSED rather than applied second. Note the key is (table, "
                            + "id): EffectModel 80007 and TalentModel 80007 are different "
                            + "rows and the laser sheet owns the second.");
                        refused++;
                        continue;
                    }
                    Claimed[key] = $"{name}:{p.Line}";

                    var keyColumn = side == 0 ? ImplantKey : EffectIdColumn;
                    adopt(new Rule
                    {
                        Model   = model,
                        Comment = $"{name} — {keyColumn} {id} (implant {p.ImplantId} / effect "
                                + $"{p.EffectId}, one sheet row split into an {ImplantModel} "
                                + $"rule and an {EffectModel} rule)",
                        Where   = new Dictionary<string, JsonElement> { { keyColumn, Num(id) } },
                        Set      = half.Set.Count > 0 ? half.Set : null,
                        Multiply = half.Multiply.Count > 0 ? half.Multiply : null,
                        Add      = half.Add.Count > 0 ? half.Add : null,
                    });
                    emitted++;
                    if (side == 0) implantRules++; else effectRules++;
                }
            }

            // THE LOAD-TIME REPORT. Every number it can know, printed whether or
            // not it is zero, and a named statement of the one it cannot.
            Plugin.Log.LogInfo($"Implants: {name} — {rows} row(s), {emitted} rule(s) emitted "
                + $"({implantRules} {ImplantModel}, {effectRules} {EffectModel}), {cells} "
                + $"lever cell(s) set, {blankRows} row(s) with every cell blank, {refused} "
                + $"cell(s) or row(s) refused, {sharedMarks} effect row(s) shared by two or "
                + $"more rows of this sheet. {payloadColumns.Length} payload column(s) and "
                + $"{header.Count(h => ImplantLeverSet.Contains(h))} {ImplantModel} lever "
                + "column(s) in this header.");

            int slotNo;
            string help;
            if (int.TryParse(name.Substring("implants-slot".Length, 2), NumberStyles.None,
                             CultureInfo.InvariantCulture, out slotNo)
                && SlotHelp.TryGetValue(slotNo, out help))
                Plugin.Log.LogInfo($"Implants: {name} — {help}");
            else
                Plugin.Log.LogWarning($"Implants: {name} — NO HELP TEXT is declared for this "
                    + "sheet. That is a gap, not an absence of anything to say: the slot "
                    + "number could not be read from the filename or SlotHelp has no entry "
                    + "for it.");

            if (rows > 0 && blankRows == rows)
                Plugin.Log.LogInfo($"Implants: {name} produced NO RULE AT ALL, and that is "
                    + $"the intended state: all {rows} row(s) are present with their shipped "
                    + "values in _comment and no override set. The mod does not tune these "
                    + "today and a shipped override would be a balance change (proposal.md "
                    + "non-goals). Said rather than left as a silent zero — a file that "
                    + "contributed nothing cannot otherwise be told from a file nothing read.");

            Plugin.Log.LogInfo($"Implants: {name} — WHAT THIS CANNOT SEE, said rather than "
                + "left blank: sharing that exists in the SHIPPED data between a row of this "
                + "sheet and a row NO SHEET SHOWS. EffectModel 50000 is Dermal Plating 1's "
                + "and all 20 drone modules', and the drone modules have no table, so there "
                + "is ONE editable owner, divergence is impossible and nothing here can or "
                + "should block. That marking is informational and is owned by the editor "
                + "and by scripts\\implants.py's P-SHARED, which measures it from the dump.");

            return emitted;
        }

        // ---- the blanket implant multipliers -----------------------------
        //
        // THREE NUMBERS, NOT FOUR. See the PHASE 9, RESOLVED banner in the
        // header and implants-global.json's own _doc.
        //
        // implantStressClampMin IS DECLARED HERE AND IS NEVER APPLIED. The
        // shipped file does not carry it and schema\implantsglobal.schema.json
        // does not declare it, but ConfigDoc.Declared (ConfigDoc.cs line 191)
        // still lists it among this slot's legal top-level keys, so a file left
        // over from before it was removed passes ConfigDoc's stray-key guard
        // without a word. A key that passes that guard and then makes
        // ConfigDoc.ReadSection refuse the WHOLE file would switch the three
        // multipliers off over a key the player was just told was fine. So it
        // is parsed, named at Warning, and not applied -- the same treatment
        // PowerLevelCap.Options gives its retired "enabled" (PowerLevelCap.cs
        // line 198).
        //
        // "_doc" is the file's own prose block. It is declared for the same
        // reason: it is a legal key there and it maps to no setting.
        private sealed class GlobalOptions : ConfigDoc.IHasUnknownKeys
        {
            [JsonPropertyName("_doc")]
            public JsonElement Doc { get; set; }
            [JsonPropertyName("costMultiply")]
            public double CostMultiply { get; set; } = 0.5;
            [JsonPropertyName("installTimeMultiply")]
            public double InstallTimeMultiply { get; set; } = 0.5;
            [JsonPropertyName("implantStressMultiply")]
            public double ImplantStressMultiply { get; set; } = 3.0;
            [JsonPropertyName("implantStressClampMin")]
            public double? RetiredClampMin { get; set; }
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
            public Dictionary<string, JsonElement> UnknownKeys { get { return Unknown; } }
        }

        // The three ImplantModel columns the global block writes. Deliberately
        // NOT inside the BEGIN/END LEVER MAP markers: scripts\implants.py's
        // probe_map() scrapes every quoted name between those markers and
        // compares the SET against its own list, so a fourth copy of a name
        // already in ImplantLevers would be measured as an extra.
        private const string CostColumn        = "Cost";
        private const string InstallTimeColumn = "InstallTime";
        private const string StressColumn      = "ImplantStress";

        /// <summary>Called once per load, whether or not implants-global.json
        /// exists. Reads the three blanket implant multipliers and emits them as
        /// ONE unscoped ImplantModel rule. Returns the number of RULES emitted:
        /// 1, or 0 when the slice is off or the file could not be read.
        ///
        /// WAS RefuseGlobal UNTIL PHASE 9, and the old name's reason is still in
        /// the header rather than deleted. RefuseGlobal emitted nothing because
        /// the same three multipliers were live as one unscoped rule in
        /// ckf.hardmode.rules.json and `multiply` is not idempotent. That rule
        /// is deleted, in this same commit; emitting here is what keeps the
        /// numbers applied ONCE rather than zero times.
        ///
        /// NO `where` CLAUSE, DELIBERATELY. The deleted rule had none, so it
        /// reached all 198 ImplantModel rows including the 20 drone modules in
        /// slots 100-107 that no table shows; this one reaches the same 198.
        /// Scoping it to ImplantSlot &lt;= 11 would move Cost, InstallTime and
        /// ImplantStress on those 20 rows, which is a balance change, and
        /// proposal.md's non-goals allow four (design.md section 7).
        ///
        /// NO clampMin, DELIBERATELY. The deleted rule carried
        /// clampMin ImplantStress 1 and it binds on 0 of the 198 rows:
        /// ImplantStress ships as 1 on 197 (1 -&gt; 3) and 5 on Quantum Rider
        /// (5 -&gt; 15), so nothing lands below 1 for the floor to lift
        /// [measured]. Dropping it is sanctioned deviation D3 and
        /// scripts\implants.py's D-CLAMP re-derives the measurement every
        /// run.</summary>
        internal static int ExpandGlobal(string dir, Action<Rule> adopt)
        {
            // The file ConfigDoc actually parsed, against the directory this
            // walk was pointed at. They are the same on every ordinary launch --
            // ModelRules.Init passes ckf.hardmode.d beside the rules file and
            // ConfigDoc.Ensure resolves the same folder under Paths.ConfigPath
            // -- and a harness pointing Overlays.Load somewhere else would
            // otherwise take the multipliers from a file this walk never looked
            // at, with nothing in the log saying which file won.
            var walked = Path.Combine(dir, GlobalFile);
            var parsed = ConfigDoc.Where(ConfigDoc.ImplantsGlobal);
            if (!string.Equals(walked, parsed, StringComparison.OrdinalIgnoreCase))
                Plugin.Log.LogWarning($"Implants: this overlay walk was pointed at {dir}, but "
                    + $"the blanket implant multipliers come from {parsed}, which ConfigDoc "
                    + $"resolved on its own. {walked} was NOT read. On an ordinary launch "
                    + "these are one file; here they are two.");

            // THE GATE IS NEWLY LIVE, AND THAT IS SAID OUT LOUD. Until Phase 9
            // these multipliers arrived as a rule in ckf.hardmode.rules.json,
            // which [Slices] ImplantsGlobal never gated -- switching this key
            // off changed nothing at all. It gates them now. The shipped value
            // is true (Plugin.Binds.g.cs line 134), so no default launch moves.
            if (!Slices.On("ImplantsGlobal"))
            {
                Plugin.Log.LogInfo(Slices.OffBecause("ImplantsGlobal",
                    "the blanket implant multipliers in " + GlobalFile + " are NOT applied "
                    + "this launch: all " + ImplantModel + " rows keep the " + CostColumn
                    + ", " + InstallTimeColumn + " and " + StressColumn + " the game ships. "
                    + "THIS KEY ONLY STARTED GATING ANYTHING IN PHASE 9 -- before that the "
                    + "same three multipliers came from an unscoped rule in "
                    + "ckf.hardmode.rules.json that this key did not reach, so turning it "
                    + "off used to do nothing."));
                return 0;
            }

            var opt = ConfigDoc.ReadSection<GlobalOptions>("Implants", ConfigDoc.ImplantsGlobal,
                "The blanket implant multipliers are NOT applied this launch: every "
                + ImplantModel + " row keeps the " + CostColumn + ", " + InstallTimeColumn
                + " and " + StressColumn + " the game ships. The eleven implant slot sheets "
                + "are unaffected -- they are separate files and were read separately.");
            if (opt == null) return 0;

            if (opt.RetiredClampMin != null)
                Plugin.Log.LogWarning($"Implants: {parsed} still carries "
                    + "\"implantStressClampMin\": "
                    + opt.RetiredClampMin.Value.ToString("R", CultureInfo.InvariantCulture)
                    + ". IT IS READ AND NOT APPLIED. That is not the key being dropped by "
                    + "accident: the floor it asks for binds on 0 of the 198 rows, because "
                    + StressColumn + " ships as 1 on 197 of them and 5 on Quantum Rider, so "
                    + "after the stress multiplier the lowest value is already above it "
                    + "[measured]. Delete the key; no value moves either way.");

            var cost    = opt.CostMultiply.ToString("R", CultureInfo.InvariantCulture);
            var install = opt.InstallTimeMultiply.ToString("R", CultureInfo.InvariantCulture);
            var stress  = opt.ImplantStressMultiply.ToString("R", CultureInfo.InvariantCulture);

            // NO Where, NO WhereMin/WhereMax: ModelRules.Matches returns true on
            // a rule with no selector, so this reaches every row of the model.
            // That is the deleted rule's shape, kept exactly.
            adopt(new Rule
            {
                Model   = ImplantModel,
                Comment = $"BROAD — every implant is cheaper and has less downtime, but "
                        + $"generates more stress ({GlobalFile}: {CostColumn} x{cost}, "
                        + $"{InstallTimeColumn} x{install}, {StressColumn} x{stress}; no "
                        + "where clause, so every row of this model)",
                Multiply = new Dictionary<string, JsonElement>(StringComparer.Ordinal)
                {
                    { CostColumn,        Num(opt.CostMultiply) },
                    { InstallTimeColumn, Num(opt.InstallTimeMultiply) },
                    { StressColumn,      Num(opt.ImplantStressMultiply) },
                },
            });

            Plugin.Log.LogInfo($"Implants: {GlobalFile} — ONE unscoped {ImplantModel} rule "
                + $"emitted: {CostColumn} x{cost}, {InstallTimeColumn} x{install}, "
                + $"{StressColumn} x{stress}. It carries NO 'where', so it reaches EVERY "
                + $"{ImplantModel} row -- 198 in the shipped data: the 178 in character "
                + "slots 1-11 that the eleven sheets show AND the 20 drone modules in slots "
                + "100-107 that no table shows and the editor does not render [measured, "
                + "sheets\\raw 2026-09-12]. That reach is ACCEPTED, not a bug and not to be "
                + "fixed (design.md section 7).");
            Plugin.Log.LogInfo($"Implants: those three numbers are applied ONCE. The unscoped "
                + $"{ImplantModel} rule that used to carry them was deleted from "
                + "ckf.hardmode.rules.json in the same commit that made this line possible, "
                + "because multiply is not idempotent: with both in place Cost and "
                + "InstallTime would land on x0.25 and ImplantStress on x9 across all 198 "
                + "rows. Its clampMin " + StressColumn + " 1 was NOT carried across -- it "
                + "binds on 0 of the 198 rows and dropping it moves no value (sanctioned "
                + "deviation D3; scripts\\implants.py's D-CLAMP re-derives it every run).");
            return 1;
        }

        private static JsonElement Num(double v) =>
            JsonDocument.Parse(v.ToString("R", CultureInfo.InvariantCulture)).RootElement.Clone();

        private static JsonElement Num(long v) =>
            JsonDocument.Parse(v.ToString(CultureInfo.InvariantCulture)).RootElement.Clone();
    }
}
