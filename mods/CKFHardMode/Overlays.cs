// Overlays — the bulk authoring format.
//
// ckf.hardmode.rules.json is the right shape for a rule that says something
// general: "every enemy above PL 10 gains 2.2 crit per level". It is the wrong
// shape for the other job, which is stating what one specific row's numbers
// are. That rule is twenty lines of JSON to carry four numbers, and retuning
// 77 armour families one row at a time means tens of thousands of lines of it.
//
// An overlay is the same edit as a table:
//
//     ArmorId, BallisticArmor, PiercingArmor, MaxArmorPoints, _comment
//     22010,   52,             48,            2,              Guard Std 11
//     22011,   54,             50,            2,              Guard Std 12
//
// One line per row edited. The header row is column names straight out of
// BepInEx/ckf-dump/<Table>.csv, so an LLM handed the dump edits a file it can
// already read, and a human opens the result in a spreadsheet and changes one
// cell. An empty cell means "leave that column alone", which is what makes a
// sparse edit as cheap to write as a dense one.
//
// THE OPERATOR LIVES IN THE HEADER, not the cell:
//
//     Column      set to this value
//     Column*     multiply by it
//     Column+     add it
//     Column>     clampMin
//     Column<     clampMax
//
// so every cell stays a plain number. Nothing here starts with '=' or '+',
// which means a spreadsheet will not try to read a cell as a formula.
//
// Three control columns, recognisable by their leading underscore:
//
//     _clone      the id of the row to copy — makes the line an INSERT rather
//                 than an edit, which is how a gear tier above 10 is one line
//     _comment    free text, shown by TraceRules and by the validator
//     _serveOn    auto | provenance | always | never, on a clone line
//
// Files live in BepInEx/config/ckf.hardmode.d/. The table is the part of the
// filename before the first dot, so ArmorModel.csv and
// ArmorModel.guard-standard.csv both target ArmorModel and one table can be
// split across as many files as suits. .tsv is the same thing tab-separated,
// and a .json file in that directory is an ordinary rules file — which is how
// the big rules.json gets split up per table too.
//
// ORDER: rules.json first, then the directory in filename order. Overlays
// therefore win over the broad rules, which is the useful way round — a sweep
// sets the shape of a family and a single line overrides the one row that
// should not follow it.
//
// ONE FILE, ONE SLICE, AND THE SKIP HAPPENS BEFORE THE OPEN. Since 2026-09-13
// each file here may be claimed by a slice toggle in ckf.hardmode.cfg. Load
// asks Slices.VerdictForOverlay for every file BEFORE it opens it, and a file
// whose slice is off is never read: no line is parsed, no Rule is built, and
// ModelRules.Adopt never sees one, so no Rule.Index is allocated for it. That
// is the point. Adopting a rule and discarding its effect afterwards would be
// too late — RulePlan preserves load order, so a rule that was adopted has
// already changed what a later rule sees.
//
// Relative order survives a skip. Files are still walked in Ordinal filename
// order and rules are still adopted in the order their lines appear, so
// removing a file from the walk shifts the absolute Rule.Index of everything
// after it and reorders nothing.
//
// A FILE NO SLICE CLAIMS IS STILL READ. The three enemy-gear overlays are in
// that state today; skipping them would be a silent tuning change. They are
// counted and named separately in the summary line, so "nothing claims this
// file" can never be mistaken for "a slice claims it and the slice is on".
//
// CORRECTION, 2026-09-13 (Phase 3). The paragraph above used to name four files
// in that state: "The three enemy-gear overlays and the MissionPowerLevelModel
// mirror". The mirror has been claimed by the Progression slice since
// 2026-09-13 -- Slices.OverlayOwner carries the row and its own comment says
// why -- so it is three, not four. design.md section 2 carries the same
// correction.
//
// A SETTINGS FILE IS NOT A RULES FILE, AND THE PARSER CANNOT TELL. Since Phase
// 3 of split-config-into-toggleable-slices the ten settings files -- the nine
// subsystem slices plus implants-global.json -- live in this same directory and
// end in .json. RuleFile has one property, "rules", and no extension-data bag,
// so deserialising elapse.json as one would succeed, yield ZERO rules and log
// NOTHING: the exact silent instrument AGENTS.md section 3 forbids. Load asks
// ConfigDoc.OwnsFile about every file before it opens it and skips the ones
// ConfigDoc reads, then NAMES them on their own line so "not parsed as rules"
// is never indistinguishable from "parsed and held nothing".
//
// AN ID-ONLY LINE IS A SPACER, NOT A FAULT.
//
// CORRECTION, 2026-09-13 (Phase 4). Until this date BuildRule treated a line
// whose id parsed but whose every value cell was blank as a BAD line: one
// Warning each, reading
//
//     "Overlays[RuleModel.csv:2]: RuleId 1 is named but every value cell is
//      empty, so there is nothing to apply to it."
//
// and a contribution to the "N line(s) skipped" clause of the summary. That is
// backwards. "An empty cell means leave that column alone" is the dialect this
// file defines, and a generator emits an empty cell wherever no change is
// intended (design.md section 9) -- so every cell empty is the same statement
// about the whole row: leave the row alone. RuleModel.csv, which arrived in
// Phase 4, is 76 data lines of which 74 are exactly that, because the mod tunes
// rows 22 and 23 and states the other 74 so the editor can list them. Those 74
// produced 74 Warnings per launch, which is how a real one gets buried.
//
// They are counted as `untouched` now, separately from `bad`, reported at Info,
// and NOT silenced: the summary carries the count unconditionally -- zero is an
// answer too -- and any file with untouched lines gets ONE line naming it and
// the proportion. scripts/validate_rules.py already grades these INFO ("empty
// overlay line"), so the runtime and the repo-side gate now agree.
//
// A line that carries text which could not be applied is still BAD and still
// warns. The two are told apart by whether any value cell held anything at all,
// not by whether a term came out of it -- otherwise "1.8x" under a header the
// parser rejected would have hidden inside the benign count.
//
// WHY THIS IS FAST. Every edit line compiles to a rule selecting one exact id,
// which is the shape ModelPlan indexes (see RulePlan.cs). Ten thousand overlay
// lines on ArmorModel cost one number read and one dictionary lookup per row —
// not ten thousand comparisons. Edit lines also skip JSON entirely: the
// selector is a long on the rule and the values are constant Terms, so a large
// file costs a few small arrays per line rather than a retained JsonDocument.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;

namespace CKFHardMode
{
    internal static class Overlays
    {
        private enum Op { Set, Multiply, Add, ClampMin, ClampMax }

        /// <summary>What one data line turned out to be. Three answers, not
        /// two: a line that names a row and sets nothing is neither a rule nor
        /// a fault, and collapsing it into either loses the distinction a
        /// reader needs. See the header.</summary>
        private enum LineResult
        {
            Applied,    // a rule was built and adopted
            Untouched,  // names a row, sets nothing: leave the row alone
            Bad         // carried something that could not be applied
        }

        private sealed class Col
        {
            public string Name;
            public Op Op;
            public bool Control;
        }

        public static void Load(string dir, Action<Rule> adopt)
        {
            Load(dir, adopt, Slices.VerdictForOverlay);
        }

        /// <summary>The gated form. <paramref name="verdict"/> is asked about
        /// every file before it is opened; the two-argument overload above
        /// passes Slices.VerdictForOverlay, and a test harness can pass its
        /// own.</summary>
        internal static void Load(string dir, Action<Rule> adopt,
                                  Func<string, Slices.Verdict> verdict)
        {
            // Reset first, so a caller that reads these after an early return
            // below sees this call's answer and not the previous call's.
            SkippedFiles = new List<string>();
            FilesRead = 0;

            // The cyberweapon expander's (model, id) registry is static, so a
            // second Load in one process -- the test harness does this -- would
            // otherwise inherit the first walk's claims and refuse every row of
            // the second. Reset here rather than inside Expand, because the two
            // sheets are separate files and must be able to see each other's
            // claims WITHIN one walk: that is what stops both sheets naming one
            // weapon.
            Cyberweapons.Reset();

            // The implant slot tables' registry is static for the same reason
            // and has one more: the ELEVEN sheets must see each other's claims
            // WITHIN one walk, because EffectModel 50126 is CombatLink 4's and
            // M-Grade CombatLink's and a payload write to it must not land
            // twice. Reset here, not inside Expand.
            Implants.Reset();

            // The consumable sheets' registry is static for the same reason and
            // has the same second one: the SIX sheets must see each other's
            // claims WITHIN one walk. Their keys are (table, id) and they have
            // to be -- inside this phase's own 194 (table, id) pairs, 31 ids
            // appear under two different models, so an id-alone key collapses
            // 194 pairs to 163 and sends 31 writes to the wrong table
            // [measured]. Reset here, not inside Expand.
            Consumables.Reset();

            if (!Directory.Exists(dir))
            {
                Plugin.Log.LogInfo($"Overlays: no {Path.GetFileName(dir)} directory; "
                                 + "nothing to merge. Create it to use per-table CSV overlays.");
                return;
            }

            var files = Directory.GetFiles(dir)
                .Where(f => f.EndsWith(".csv", StringComparison.OrdinalIgnoreCase)
                         || f.EndsWith(".tsv", StringComparison.OrdinalIgnoreCase)
                         || f.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                .OrderBy(Path.GetFileName, StringComparer.Ordinal)
                .ToList();

            if (files.Count == 0)
            {
                Plugin.Log.LogInfo($"Overlays: {Path.GetFileName(dir)} is empty.");
                return;
            }

            int lines = 0, clones = 0, bad = 0, read = 0, untouched = 0;
            var skipped = new List<string>();      // "<file> [Slices] <Key>"
            var unclaimed = new List<string>();    // no slice names this file
            var settings = new List<string>();     // ConfigDoc reads it, not this
            var lever = new List<string>();        // a lever sheet, expanded not parsed

            foreach (var f in files)
            {
                var name = Path.GetFileName(f);

                // NOT A RULES FILE. See the header: deserialising one of the ten
                // settings files as a RuleFile succeeds and yields nothing, with
                // no error anywhere. ConfigDoc owns these, has already read them
                // by the time this runs, and reports on them itself.
                if (ConfigDoc.OwnsFile(name))
                {
                    settings.Add(name);
                    continue;
                }

                // BEFORE THE OPEN. See the header. A skipped file is not read,
                // not parsed and not adopted, so it allocates no Rule.Index.
                var v = verdict == null ? null : verdict(name);
                if (v != null && !v.Open)
                {
                    skipped.Add(name + " [" + Slices.Section + "] " + v.SliceKey);
                    continue;
                }
                if (v == null || v.SliceKey == null) unclaimed.Add(name);

                read++;
                try
                {
                    // A LEVER SHEET IS NOT A TABLE OVERLAY, and it has to be
                    // recognised BEFORE TableOf runs. TableOf derives the target
                    // table from the filename up to the first dot, so
                    // "gear-classes.csv" would become a model called
                    // "gear-classesModel": every row would build a rule against
                    // a table that does not exist, and the only symptom would be
                    // one orphan warning long after the file appeared to load.
                    //
                    // The expander owns the whole parse — its first column is a
                    // player concept, not an id, and its header names levers,
                    // not game columns. design.md section 1.
                    if (GearClasses.Owns(name))
                    {
                        lever.Add(name);
                        lines += GearClasses.Expand(f, adopt);
                    }
                    else if (Cyberweapons.Owns(name))
                    {
                        // The SECOND lever sheet shape, and it needs the same
                        // guard for the same reason: TableOf takes the filename
                        // up to the first dot, so "cyberweapons-lasers.csv"
                        // would become a model called
                        // "cyberweapons-lasersModel". Unlike gear-classes.csv
                        // this one expands into TWO tables per row, which
                        // TableOf could not express even if the name parsed --
                        // see Cyberweapons.cs.
                        lever.Add(name);
                        lines += Cyberweapons.Expand(f, adopt);
                    }
                    else if (Implants.Owns(name))
                    {
                        // The THIRD lever sheet shape, Phase 7, and it needs the
                        // same guard for the same reason: TableOf takes the
                        // filename up to the first dot, so
                        // "implants-slot08.csv" would become a model called
                        // "implants-slot08Model" and 26 rows would build rules
                        // against a table that does not exist. Like the
                        // cyberweapon sheets it expands into TWO tables per row
                        // -- ImplantModel keyed on ImplantTypeId and EffectModel
                        // keyed on that row's ImplantEffectId -- which TableOf
                        // could not express even if the name parsed. See
                        // Implants.cs.
                        lever.Add(name);
                        lines += Implants.Expand(f, adopt);
                    }
                    else if (Consumables.Owns(name))
                    {
                        // The FOURTH lever sheet shape, Phase 8, and it needs the
                        // same guard for the same reason: TableOf takes the
                        // filename up to the first dot and appends "Model"
                        // because it does not already end in one, so
                        // "consumables-medical.csv" would become a model called
                        // "consumables-medicalModel". That is NON-NULL, so it
                        // does not trip LoadTable's null guard, and 18 rows
                        // would build rules against a table that does not exist
                        // -- surfacing only as an orphan warning long
                        // afterwards. Unlike the other three this one expands
                        // into up to FOUR tables per row -- ItemModel keyed on
                        // ItemTypeId, TalentModel keyed on that row's TalentId,
                        // and EffectModel and/or MatrixEffectModel keyed on that
                        // row's EffectId and MatrixEffectId -- which TableOf
                        // could not express even if the name parsed. See
                        // Consumables.cs.
                        lever.Add(name);
                        lines += Consumables.Expand(f, adopt);
                    }
                    else if (f.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                        lines += LoadJson(f, adopt);
                    else
                        lines += LoadTable(f, adopt, ref clones, ref bad, ref untouched);
                }
                catch (Exception e)
                {
                    Plugin.Log.LogError($"Overlays: {name} failed to load: " + e.Message);
                }
            }

            // NAMED, NOT JUST COUNTED. AGENTS.md §3: a line reporting a total
            // without reporting what it left out cannot tell "skipped" from
            // "found nothing". Every skipped file is named with the key that
            // skipped it; a rule count for those files is NOT reported, and
            // cannot be, because the file was never opened.
            foreach (var s in skipped)
                Plugin.Log.LogInfo("Overlays: SKIPPED " + s + " — its slice is off in "
                    + "ckf.hardmode.cfg, so the file was not opened and none of its rows "
                    + "entered the rule plan. How many rows it holds is not known: nothing "
                    + "read it.");

            if (settings.Count > 0)
                Plugin.Log.LogInfo("Overlays: " + settings.Count + " file(s) here are SETTINGS "
                    + "files, not rule files, and were not parsed as rules: "
                    + string.Join(", ", settings) + ". ConfigDoc reads them and reports on "
                    + "them; see its lines above. They still have a toggle in "
                    + "ckf.hardmode.cfg, and it gates the subsystem rather than this walk.");

            if (unclaimed.Count > 0)
                Plugin.Log.LogInfo("Overlays: " + unclaimed.Count + " file(s) are claimed by no "
                    + "slice and were loaded unconditionally: " + string.Join(", ", unclaimed)
                    + ". They have no toggle in ckf.hardmode.cfg.");

            // implants-global.json IS NOT A RULE FILE IN THE OVERLAY DIALECT.
            // It is caught by ConfigDoc.OwnsFile above and counted among the
            // settings files, so this walk never opens it -- which means
            // nothing in this walk would otherwise say a word about it. Its
            // three multipliers still have to reach the rule plan, and
            // Implants.ExpandGlobal is what puts them there: ONE unscoped
            // ImplantModel rule, no `where`, adopted here at the end of the
            // walk. It logs the three numbers it read whether or not it
            // emitted, because a file read and not applied in silence is the
            // instrument AGENTS.md section 3 is about.
            //
            // CORRECTION, PHASE 9. This call was Implants.RefuseGlobal and the
            // paragraph here said it "emitted nothing and why: its three
            // multipliers duplicate a MULTIPLY rule that is still live in
            // ckf.hardmode.rules.json, and emitting them would apply the
            // multipliers twice." That was true and is not any more. The rule
            // was deleted from ckf.hardmode.rules.json in the SAME COMMIT that
            // replaced the refusal with this expander, and neither half moves
            // alone: rule + expander applies x0.5 twice, rule-gone + refusal
            // applies it zero times, and only the pair leaves every shipped
            // value where it was. `set` is idempotent and `multiply` is not,
            // which is why the nine EffectModel rules could ship in Phase 7
            // beside a live rules file and these three could not.
            //
            // Its count joins `lines` like every other expander's, so the total
            // below includes it. It is NOT added to `lever`: that list names
            // the sheet files this walk opened and expanded, and this file was
            // not opened by this walk at all.
            lines += Implants.ExpandGlobal(dir, adopt);

            SkippedFiles = skipped;
            FilesRead = read;

            // `untouched` is printed whether or not it is zero. A counter that
            // appears only when it is non-zero is one a reader cannot tell from
            // an instrument that stopped running (AGENTS.md §3), and zero here
            // is a real answer: every line that named a row also set something.
            //
            // The trailing "." used to come out of the `bad` clause's else
            // branch, so a launch WITH malformed lines ended the sentence
            // without one. It is its own term now.
            Plugin.Log.LogInfo($"Overlays: {files.Count} file(s) in the directory, "
                + $"{settings.Count} of them settings files ConfigDoc reads, "
                + $"{read} read here, {lever.Count} of them lever sheet(s) expanded "
                + $"by their own expander, {skipped.Count} skipped by a disabled slice, "
                + $"{unclaimed.Count} claimed by no slice; {lines} row(s) merged"
                + (clones > 0 ? $", {clones} of them inserts" : "")
                + $", {untouched} line(s) named a row and set nothing"
                + (bad > 0 ? $", {bad} line(s) skipped as malformed — see the warnings above"
                           : "")
                + ".");
        }

        /// <summary>Files the last Load skipped because their slice is off,
        /// each as "&lt;file&gt; [Slices] &lt;Key&gt;". ModelRules' rule-count line
        /// names them, because a total that does not say what it left out cannot
        /// tell "skipped" from "found nothing" (AGENTS.md §3). Empty, never
        /// null, once Load has run; empty before it has, which is why ModelRules
        /// only reads it after the call.</summary>
        internal static List<string> SkippedFiles { get; private set; } = new List<string>();

        /// <summary>How many files the last Load actually opened.</summary>
        internal static int FilesRead { get; private set; }

        // ---- an ordinary rules file, just not the main one -------------------

        private static int LoadJson(string path, Action<Rule> adopt)
        {
            var opts = new JsonSerializerOptions
            {
                ReadCommentHandling = JsonCommentHandling.Skip,
                AllowTrailingCommas = true
            };
            var file = JsonSerializer.Deserialize<RuleFile>(File.ReadAllText(path), opts);
            int n = 0;
            foreach (var r in file?.Rules ?? new List<Rule>())
            {
                // A literal null element in the array. It used to go straight
                // to ModelRules.Adopt and be counted as a merged row.
                if (r == null)
                {
                    Plugin.Log.LogWarning($"Overlays[{Path.GetFileName(path)}]: \"rules\" holds a "
                        + "null entry; skipped. A trailing comma before the closing bracket is "
                        + "the usual cause.");
                    continue;
                }
                adopt(r);
                n++;
            }
            return n;
        }

        // ---- the table format -------------------------------------------------

        // ArmorModel.csv and ArmorModel.guard-standard.csv both mean ArmorModel.
        // Null when there is no table name before the first dot: ".csv" and
        // ".gitkeep.csv" used to yield "" + "Model" == "Model", and every line
        // in such a file then built rules against a model called "Model", which
        // surfaced only as an orphan warning long afterwards.
        private static string TableOf(string path)
        {
            var name = Path.GetFileName(path);
            var cut = name.IndexOf('.');
            var table = (cut < 0 ? name : name.Substring(0, cut)).Trim();
            if (table.Length == 0) return null;
            return table.EndsWith("Model", StringComparison.Ordinal) ? table : table + "Model";
        }

        private static int LoadTable(string path, Action<Rule> adopt, ref int clones,
                                     ref int bad, ref int untouched)
        {
            var name = Path.GetFileName(path);
            var model = TableOf(path);
            if (model == null)
            {
                Plugin.Log.LogWarning($"Overlays[{name}]: the filename carries no table name "
                    + "before its first dot, so there is no model for its lines to target. Name "
                    + "the file <Table>.csv — ArmorModel.csv, or ArmorModel.guard-standard.csv to "
                    + "split one table across several. This file is ignored.");
                return 0;
            }
            var sep = path.EndsWith(".tsv", StringComparison.OrdinalIgnoreCase) ? '\t' : ',';

            var raw = File.ReadAllLines(path, Encoding.UTF8);

            string[] header = null;
            Col[] cols = null;
            string keyColumn = null;
            int rows = 0, untouchedHere = 0, badHere = 0;

            for (int n = 0; n < raw.Length; n++)
            {
                var line = raw[n];
                if (n == 0 && line.Length > 0 && line[0] == '﻿') line = line.Substring(1);
                if (line.Trim().Length == 0) continue;
                if (line.TrimStart().StartsWith("#", StringComparison.Ordinal)) continue;

                var cells = SplitLine(line, sep);

                // A row whose every cell is blank — ",,,," — is a spacer, and
                // is not counted at all: it names no row, so there is nothing
                // for a reader to look up. The code has always called it a
                // spacer; it just counted it as a bad line anyway, so the
                // summary read "N line(s) skipped — see the warnings above"
                // with no warning above it.
                //
                // A line that names a row and leaves every value cell blank is
                // a DIFFERENT thing and is counted, as `untouched` — see the
                // header. It is a statement about a real row: leave it alone.
                if (cells.All(c => (c ?? "").Trim().Length == 0)) continue;

                if (header == null)
                {
                    header = cells;
                    cols = new Col[cells.Length];
                    for (int i = 0; i < cells.Length; i++) cols[i] = ParseHeader(cells[i]);

                    keyColumn = cols.Length > 0 && cols[0] != null && !cols[0].Control
                              ? cols[0].Name : null;
                    if (string.IsNullOrEmpty(keyColumn))
                    {
                        Plugin.Log.LogError($"Overlays[{name}]: the first column must be the "
                            + "table's id column (ArmorId, WeaponId, MonsterTypeId, ...). "
                            + "This file is ignored.");
                        return 0;
                    }
                    if (cols[0].Op != Op.Set)
                        Plugin.Log.LogWarning($"Overlays[{name}]: the id column carries an "
                            + "operator suffix, which is meaningless — it selects the row.");
                    continue;
                }

                switch (BuildRule(name, n + 1, model, keyColumn, cols, cells, adopt, ref clones))
                {
                    case LineResult.Applied:   rows++;          break;
                    case LineResult.Untouched: untouchedHere++; break;
                    default:                   badHere++;       break;
                }
            }

            if (header == null)
                Plugin.Log.LogWarning($"Overlays[{name}]: no header row found.");

            // ONE line per file, not one per row. 74 Warnings is how a real one
            // gets buried, and saying nothing is how "this file has 74 untouched
            // rows" becomes indistinguishable from "this file has 74 malformed
            // lines" — which is the whole point of counting them apart. Info,
            // matching the judgement scripts/validate_rules.py already makes on
            // the same lines.
            if (untouchedHere > 0)
                Plugin.Log.LogInfo($"Overlays[{name}]: {untouchedHere} of "
                    + $"{rows + untouchedHere + badHere} data line(s) name a row and set "
                    + "nothing, so those rows are left exactly as the game ships them. That is "
                    + "the format and not a fault — an empty cell means leave that column "
                    + "alone, and a generator writes an empty cell wherever no change is "
                    + "intended. scripts/validate_rules.py grades the same lines INFO.");

            untouched += untouchedHere;
            bad += badHere;
            return rows;
        }

        private static Col ParseHeader(string cell)
        {
            var s = (cell ?? "").Trim();
            if (s.Length == 0) return new Col { Name = "", Op = Op.Set, Control = true };
            if (s[0] == '_') return new Col { Name = s.ToLowerInvariant(), Control = true };

            var op = Op.Set;
            var last = s[s.Length - 1];
            switch (last)
            {
                case '*': op = Op.Multiply; break;
                case '+': op = Op.Add;      break;
                case '>': op = Op.ClampMin; break;
                case '<': op = Op.ClampMax; break;
            }
            if (op != Op.Set) s = s.Substring(0, s.Length - 1).Trim();
            return new Col { Name = s, Op = op };
        }

        private static LineResult BuildRule(string file, int lineNo, string model,
                                            string keyColumn, Col[] cols, string[] cells,
                                            Action<Rule> adopt, ref int clones)
        {
            string Cell(int i) => i < cells.Length ? (cells[i] ?? "").Trim() : "";

            // A wholly blank row never reaches here — LoadTable treats that as
            // a spacer. An empty id cell on a line that carries values is a
            // different thing: it names no row, so nothing can be applied.
            var idText = Cell(0);
            if (idText.Length == 0)
            {
                Plugin.Log.LogWarning($"Overlays[{file}:{lineNo}]: the first cell is empty, so "
                    + "this line names no row and none of its values can be applied.");
                return LineResult.Bad;
            }

            long id;
            if (!long.TryParse(idText, NumberStyles.Integer, CultureInfo.InvariantCulture, out id))
            {
                Plugin.Log.LogWarning($"Overlays[{file}:{lineNo}]: '{idText}' is not an id.");
                return LineResult.Bad;
            }

            string comment = null, serveOn = null, cloneFrom = null;
            for (int i = 1; i < cols.Length; i++)
            {
                var c = cols[i];
                if (c == null || !c.Control) continue;
                var v = Cell(i);
                if (v.Length == 0) continue;
                if (c.Name == "_comment") comment = v;
                else if (c.Name == "_serveon") serveOn = v;
                else if (c.Name == "_clone") cloneFrom = v;
            }

            // Only a supplied _comment is kept. Synthesising "file:line id" for
            // every line would retain a string per row, which at forty thousand
            // lines is megabytes bought for nothing — Describe() already falls
            // back to the model name, and the trace prints the rule number.
            var label = comment;

            if (cloneFrom != null)
            {
                clones++;
                // A clone line is never `untouched`: "_clone plus an id" is a
                // complete instruction on its own, so it either inserts or it
                // is malformed.
                return CloneRule(file, lineNo, model, keyColumn, id, cloneFrom, serveOn,
                                 label ?? $"{file}:{lineNo}", cols, cells, adopt)
                     ? LineResult.Applied : LineResult.Bad;
            }

            var rule = new Rule
            {
                Model = model,
                Comment = label,
                OverlayKeyColumn = keyColumn,
                OverlayKeyValue = id,
            };

            // `any`  — at least one term came out of a value cell.
            // `text`  — at least one VALUE cell carried something, applied or
            //           not. The two differ exactly on the faulty line, which
            //           is why the second exists: without it, a cell the parser
            //           refused would be indistinguishable from a blank one and
            //           would hide inside the benign `untouched` count.
            //
            // Control columns are skipped by the `c.Control` test below, so a
            // line carrying only a _comment is still untouched. That is right:
            // a comment documents a row, it does not change one.
            bool any = false, text = false;
            for (int i = 1; i < cols.Length; i++)
            {
                var c = cols[i];
                if (c == null || c.Control || c.Name.Length == 0) continue;
                var v = Cell(i);
                if (v.Length == 0) continue;                   // leave the column alone
                text = true;

                double d;
                if (double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                {
                    var term = new Term { Column = c.Name, IsConstant = true, Constant = d };
                    switch (c.Op)
                    {
                        case Op.Set:      (rule.SetTerms ??= new List<Term>()).Add(term); break;
                        case Op.Multiply: (rule.MulTerms ??= new List<Term>()).Add(term); break;
                        case Op.Add:      (rule.AddTerms ??= new List<Term>()).Add(term); break;
                        case Op.ClampMin: (rule.MinTerms ??= new List<Term>()).Add(term); break;
                        case Op.ClampMax: (rule.MaxTerms ??= new List<Term>()).Add(term); break;
                    }
                    any = true;
                }
                else if (c.Op == Op.Set)
                {
                    // A text column — rare, but ActionClass and GroupId are
                    // real. Only a plain set means anything for one.
                    (rule.RawSets ??= new Dictionary<string, object>(StringComparer.Ordinal))
                        [c.Name] = Literal(v);
                    any = true;
                }
                else
                {
                    Plugin.Log.LogWarning($"Overlays[{file}:{lineNo}]: {c.Name} is '{v}', which "
                        + "is not a number, so the operator in its header cannot apply.");
                }
            }

            if (!any)
            {
                // BLANK MEANS UNTOUCHED. No value cell carried anything, so this
                // line says "leave this row alone" — the row-level form of the
                // empty cell. Not a fault, not logged here, counted apart.
                //
                // CORRECTION, 2026-09-13. This branch used to warn
                // unconditionally: "{keyColumn} {id} is named but every value
                // cell is empty, so there is nothing to apply to it." and return
                // false, which put the line in the `bad` count. RuleModel.csv
                // made that 74 Warnings on every launch. See the header.
                if (!text) return LineResult.Untouched;

                // Text was there and none of it survived. Every cell that failed
                // has already warned for itself just above; this names the row
                // so the line is findable.
                Plugin.Log.LogWarning($"Overlays[{file}:{lineNo}]: {keyColumn} {id} is named and "
                    + "carries value(s), but none of them could be applied — see the warning(s) "
                    + "directly above. Nothing is changed on this row.");
                return LineResult.Bad;
            }
            adopt(rule);
            return LineResult.Applied;
        }

        private static object Literal(string v)
        {
            if (string.Equals(v, "true", StringComparison.OrdinalIgnoreCase)) return true;
            if (string.Equals(v, "false", StringComparison.OrdinalIgnoreCase)) return false;
            return v;
        }

        // An insert goes through the ordinary clone machinery, so it is built
        // as JSON and handed to the same deserializer the rules file uses.
        // There are far fewer of these than edits — one per row that does not
        // exist — so the cost of a small document each is not worth avoiding,
        // and it means RowClone sees nothing new.
        private static bool CloneRule(string file, int lineNo, string model, string keyColumn,
                                      long id, string cloneFrom, string serveOn, string comment,
                                      Col[] cols, string[] cells, Action<Rule> adopt)
        {
            long source;
            if (!long.TryParse(cloneFrom, NumberStyles.Integer, CultureInfo.InvariantCulture,
                               out source))
            {
                Plugin.Log.LogWarning($"Overlays[{file}:{lineNo}]: _clone is '{cloneFrom}', "
                                    + "which is not an id.");
                return false;
            }

            string Cell(int i) => i < cells.Length ? (cells[i] ?? "").Trim() : "";

            var sb = new StringBuilder();
            sb.Append("{\"model\":").Append(Quote(model))
              .Append(",\"comment\":").Append(Quote(comment))
              .Append(",\"clone\":{").Append(Quote(keyColumn)).Append(':').Append(source)
              .Append("},\"as\":{").Append(Quote(keyColumn)).Append(':').Append(id);

            // Plain columns describe what the new row IS, so they belong in
            // "as", which runs before the operations — a curve on the copy then
            // reads the values this line just gave it.
            for (int i = 1; i < cols.Length; i++)
            {
                var c = cols[i];
                if (c == null || c.Control || c.Name.Length == 0 || c.Op != Op.Set) continue;
                var v = Cell(i);
                if (v.Length == 0) continue;
                sb.Append(',').Append(Quote(c.Name)).Append(':').Append(Json(v));
            }
            sb.Append('}');

            var ops = new (string Name, Op Op)[]
            {
                ("multiply", Op.Multiply), ("add", Op.Add),
                ("clampMin", Op.ClampMin), ("clampMax", Op.ClampMax),
            };

            foreach (var op in ops)
            {
                string body = null;
                for (int i = 1; i < cols.Length; i++)
                {
                    var c = cols[i];
                    if (c == null || c.Control || c.Name.Length == 0 || c.Op != op.Op) continue;
                    var v = Cell(i);
                    if (v.Length == 0) continue;
                    body = (body == null ? "" : body + ",") + Quote(c.Name) + ":" + Json(v);
                }
                if (body != null)
                    sb.Append(",\"").Append(op.Name).Append("\":{").Append(body).Append('}');
            }

            if (!string.IsNullOrEmpty(serveOn))
                sb.Append(",\"serveOn\":").Append(Quote(serveOn));

            sb.Append('}');

            try
            {
                var rule = JsonSerializer.Deserialize<Rule>(sb.ToString());
                adopt(rule);
                return true;
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"Overlays[{file}:{lineNo}]: could not build the insert: "
                                    + e.Message);
                return false;
            }
        }

        private static string Json(string v)
        {
            double d;
            if (double.TryParse(v, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                return d.ToString("R", CultureInfo.InvariantCulture);
            if (string.Equals(v, "true", StringComparison.OrdinalIgnoreCase))  return "true";
            if (string.Equals(v, "false", StringComparison.OrdinalIgnoreCase)) return "false";
            return Quote(v);
        }

        private static string Quote(string s) =>
            JsonSerializer.Serialize(s ?? "");

        // ---- CSV ---------------------------------------------------------------
        //
        // RFC 4180 as far as a config file needs it: quoted fields may hold the
        // separator, and a doubled quote inside a quoted field is one quote. A
        // comment column with a comma in it is the only reason this is not a
        // string.Split.
        internal static string[] SplitLine(string line, char sep)
        {
            var outp = new List<string>();
            var cur = new StringBuilder();
            bool quoted = false;

            for (int i = 0; i < line.Length; i++)
            {
                var ch = line[i];
                if (quoted)
                {
                    if (ch == '"')
                    {
                        if (i + 1 < line.Length && line[i + 1] == '"') { cur.Append('"'); i++; }
                        else quoted = false;
                    }
                    else cur.Append(ch);
                }
                else if (ch == '"' && cur.Length == 0) quoted = true;
                else if (ch == sep) { outp.Add(cur.ToString()); cur.Clear(); }
                else cur.Append(ch);
            }
            outp.Add(cur.ToString());
            return outp.ToArray();
        }
    }
}
