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

        private sealed class Col
        {
            public string Name;
            public Op Op;
            public bool Control;
        }

        public static void Load(string dir, Action<Rule> adopt)
        {
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

            int lines = 0, clones = 0, bad = 0;
            foreach (var f in files)
            {
                try
                {
                    if (f.EndsWith(".json", StringComparison.OrdinalIgnoreCase))
                        lines += LoadJson(f, adopt);
                    else
                        lines += LoadTable(f, adopt, ref clones, ref bad);
                }
                catch (Exception e)
                {
                    Plugin.Log.LogError($"Overlays: {Path.GetFileName(f)} failed to load: "
                                      + e.Message);
                }
            }

            Plugin.Log.LogInfo($"Overlays: {files.Count} file(s), {lines} row(s) merged"
                + (clones > 0 ? $", {clones} of them inserts" : "")
                + (bad > 0 ? $", {bad} line(s) skipped — see the warnings above" : "."));
        }

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

        private static int LoadTable(string path, Action<Rule> adopt, ref int clones, ref int bad)
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
            int rows = 0;

            for (int n = 0; n < raw.Length; n++)
            {
                var line = raw[n];
                if (n == 0 && line.Length > 0 && line[0] == '﻿') line = line.Substring(1);
                if (line.Trim().Length == 0) continue;
                if (line.TrimStart().StartsWith("#", StringComparison.Ordinal)) continue;

                var cells = SplitLine(line, sep);

                // A row whose every cell is blank — ",,,," — is a spacer. The
                // code has always called it one; it just counted it as a bad
                // line anyway, so the summary read "N line(s) skipped — see the
                // warnings above" with no warning above it. Genuinely malformed
                // lines are still counted, and every one of them now warns.
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

                if (BuildRule(name, n + 1, model, keyColumn, cols, cells, adopt, ref clones))
                    rows++;
                else bad++;
            }

            if (header == null)
                Plugin.Log.LogWarning($"Overlays[{name}]: no header row found.");

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

        private static bool BuildRule(string file, int lineNo, string model, string keyColumn,
                                      Col[] cols, string[] cells, Action<Rule> adopt,
                                      ref int clones)
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
                return false;
            }

            long id;
            if (!long.TryParse(idText, NumberStyles.Integer, CultureInfo.InvariantCulture, out id))
            {
                Plugin.Log.LogWarning($"Overlays[{file}:{lineNo}]: '{idText}' is not an id.");
                return false;
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
                return CloneRule(file, lineNo, model, keyColumn, id, cloneFrom, serveOn,
                                 label ?? $"{file}:{lineNo}", cols, cells, adopt);
            }

            var rule = new Rule
            {
                Model = model,
                Comment = label,
                OverlayKeyColumn = keyColumn,
                OverlayKeyValue = id,
            };

            bool any = false;
            for (int i = 1; i < cols.Length; i++)
            {
                var c = cols[i];
                if (c == null || c.Control || c.Name.Length == 0) continue;
                var v = Cell(i);
                if (v.Length == 0) continue;                   // leave the column alone

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
                Plugin.Log.LogWarning($"Overlays[{file}:{lineNo}]: {keyColumn} {id} is named but "
                    + "every value cell is empty, so there is nothing to apply to it.");
                return false;
            }
            adopt(rule);
            return true;
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
