// Writability — which columns actually accept a write.
//
// A rule against a column that ignores writes fails silently. The engine can
// only see two of the three cases:
//
//   no such column      caught, warned, one line per table+column.
//   no setter           caught the same way, off PropertyInfo.CanWrite.
//   a setter that       INVISIBLE. The write succeeds, the property reports
//   discards the value  the old value back, and the rule looks applied.
//
// The third is not hypothetical and it is not rare. Every weapon carries two
// firing-mode blocks, and the unsuffixed Accuracy / BallisticDamage /
// ActionPoints / ModeType are aliases for whichever mode is selected; the
// talent Adjusted* columns are recomputed from the raw values plus per-
// character adjustment. Both have setters. Both throw your value away.
//
// _dropped_columns.csv from the dump plugin does not help here — it says what
// the dumper chose not to emit, which is a different question. Finding one of
// these by experiment costs a launch each.
//
// So: probe. On one materialized row per table, for every column OF A TYPE THE
// PROBE CAN WRITE — the integers, the floating-point types, decimal, bool and
// string — write a value that cannot equal the current one, read it back, and
// put the original straight back. What comes back tells you which of the three
// cases you are in.
//
// Every other column gets a "skipped" row in the report rather than being left
// out of it, so the file lists every column the type has and says why each one
// carries no verdict. That matters most for ENUM columns: Accessor.IsNumeric
// counts an enum as a number, so a rule can target one and an arithmetic
// operation will happily multiply it — but writing an arbitrary stepped value
// into an enum column is not something to do blind on a row the game is about
// to use, so the probe declines and says so instead of writing.
//
// This is a write onto a row the game is about to use, which is why it is off
// by default and why the original is put back before the postfix returns. The
// restore is ATTEMPTED always, including after a throw — and a restore that
// itself fails is now reported as an error naming the table, the column, the
// row and the value left behind. It used to be swallowed, which left a probe
// value on a live row for the rest of the session with nothing in the log.
//
// The probe runs once per table per launch — on the first row of that table the
// game happens to read — and the report is rewritten each time a new table is
// covered, so the file is useful even if the run never reaches every table.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using BepInEx;

namespace CKFHardMode
{
    internal static class Writability
    {
        public static bool Enabled { get; private set; }

        private static readonly HashSet<string> Extra =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        private static readonly HashSet<string> Done =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        private sealed class Finding
        {
            public string Table, Column, Type, Verdict, Detail;
        }

        private static readonly List<Finding> Findings = new List<Finding>();
        private static string outputPath;

        private const BindingFlags Any = BindingFlags.Public | BindingFlags.NonPublic
                                       | BindingFlags.Instance | BindingFlags.DeclaredOnly;

        public static void Init(bool enabled, string[] extraTables, string output)
        {
            Enabled = enabled;
            foreach (var t in extraTables ?? new string[0])
                Extra.Add(t.EndsWith("Model", StringComparison.OrdinalIgnoreCase) ? t : t + "Model");

            outputPath = string.IsNullOrWhiteSpace(output)
                ? Path.Combine(Paths.BepInExRootPath, "ckf-hardmode", "writable_columns.csv")
                : output;

            if (!enabled) return;

            Plugin.Log.LogWarning("ModelRules: ProbeWritableColumns is ON. Every column of one row "
                + "per table gets a test write and is then restored. It is a diagnostic — turn it "
                + "off once you have the report.");
        }

        // Tables to hook that no rule targets. Rule-targeted tables are hooked
        // anyway, so the probe rides along on those for free.
        public static bool Wants(string modelName) => Enabled && Extra.Contains(modelName);

        public static void Observe(string modelName, object row)
        {
            if (!Enabled || row == null) return;
            if (!Done.Add(modelName)) return;      // first row of this table only

            try
            {
                Probe(modelName, row);
                Write();
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"ModelRules: probing {modelName} failed: "
                    + $"{e.GetType().Name}: {e.Message}");
            }
        }

        private static void Probe(string modelName, object row)
        {
            var t = row.GetType();
            int writable = 0, ignored = 0, readOnly = 0, threw = 0, skipped = 0;

            foreach (var p in AllProps(t))
            {
                if (p.GetIndexParameters().Length != 0) continue;
                if (p.Name.EndsWith("_k__BackingField", StringComparison.Ordinal)) continue;

                var u = Nullable.GetUnderlyingType(p.PropertyType) ?? p.PropertyType;

                var f = new Finding { Table = modelName, Column = p.Name, Type = u.Name };
                Findings.Add(f);

                // A column the probe has no test value for. It used to be left
                // out of the report entirely, so the file did not list every
                // column and there was no way to tell "not probed" from "not
                // there" — an enum column, which a rule CAN target, simply did
                // not appear.
                if (!IsProbeable(u))
                {
                    f.Verdict = "skipped";
                    f.Detail = u.IsEnum
                        ? "enum — a rule can target it, but the probe will not write an "
                          + "arbitrary value into one"
                        : "the probe writes only integers, floats, decimal, bool and string";
                    skipped++;
                    continue;
                }

                if (!p.CanRead) { f.Verdict = "unreadable"; continue; }
                if (!p.CanWrite) { f.Verdict = "read-only"; readOnly++; continue; }

                // Read BEFORE the guarded region. If the getter itself throws
                // there is no original to put back, and a finally that "restores"
                // its uninitialised null would write null over a string or
                // nullable column the probe never even read.
                object original;
                try { original = p.GetValue(row); }
                catch (Exception e)
                {
                    var ge = e.InnerException ?? e;
                    f.Verdict = "unreadable";
                    f.Detail = ge.GetType().Name + ": " + ge.Message;
                    threw++;
                    continue;
                }

                // Hoisted out of the try so the finally can name the value the
                // column may be left holding, and know whether there is
                // anything to put back at all.
                object probe = null;
                bool attempted = false;
                try
                {
                    probe = ProbeValue(original, u);
                    if (probe == null)
                    {
                        f.Verdict = "skipped";
                        f.Detail = "no distinct test value";
                        skipped++;
                        continue;
                    }

                    attempted = true;
                    p.SetValue(row, probe);
                    var readBack = p.GetValue(row);

                    if (Same(readBack, probe))
                    {
                        f.Verdict = "writable";
                        writable++;
                    }
                    else
                    {
                        f.Verdict = "ignored";
                        f.Detail = $"wrote {Show(probe)}, read back {Show(readBack)}";
                        ignored++;
                    }
                }
                catch (Exception e)
                {
                    var inner = e.InnerException ?? e;
                    f.Verdict = "threw";
                    f.Detail = inner.GetType().Name + ": " + inner.Message;
                    threw++;
                }
                finally
                {
                    // ATTEMPTED always, including after a throw — and reported
                    // when it fails, which it used to swallow. A setter that
                    // throws on the second write leaves stat+1, or
                    // Name + "-ckf-probe", on a row the game is about to use,
                    // for the rest of the session. That is a balance change
                    // nobody asked for, and it is not something to be quiet
                    // about. CanWrite was already established above.
                    //
                    // Nothing to put back when no write was ever attempted —
                    // the column had no distinct test value — so that case is
                    // left alone rather than written over with its own value.
                    if (attempted)
                    {
                        try { p.SetValue(row, original); }
                        catch (Exception e)
                        {
                            var re = e.InnerException ?? e;
                            f.Detail = (string.IsNullOrEmpty(f.Detail) ? "" : f.Detail + "; ")
                                     + "RESTORE FAILED: " + re.GetType().Name;
                            Plugin.Log.LogError("ModelRules: the write probe could not restore "
                                + $"{modelName}.{p.Name} on {ModelRules.Label(row)} — "
                                + $"{re.GetType().Name}: {re.Message}. That column may be left "
                                + $"holding the probe value {Show(probe)} instead of "
                                + $"{Show(original)} for the rest of this session. Restart the "
                                + "game before judging anything that reads it.");
                        }
                    }
                }
            }

            Plugin.Log.LogInfo($"ModelRules: probed {modelName} — {writable} writable, "
                + $"{ignored} accept a write and discard it, {readOnly} read-only"
                + (threw > 0 ? $", {threw} threw" : "")
                + (skipped > 0 ? $", {skipped} skipped (not probeable)" : "") + ".");

            var lost = Findings.Where(x => x.Table == modelName && x.Verdict == "ignored")
                               .Select(x => x.Column).ToList();
            if (lost.Count > 0)
                Plugin.Log.LogWarning($"  {modelName}: a rule on " + string.Join(", ", lost)
                    + " will look applied and change nothing.");
        }

        private static IEnumerable<PropertyInfo> AllProps(Type t)
        {
            var seen = new HashSet<string>(StringComparer.Ordinal);
            for (var cur = t; cur != null && cur != typeof(object); cur = cur.BaseType)
            {
                PropertyInfo[] declared;
                try { declared = cur.GetProperties(Any); }
                catch { continue; }
                foreach (var p in declared)
                    if (seen.Add(p.Name)) yield return p;   // nearest declaration wins
            }
        }

        private static bool IsProbeable(Type u) =>
            u == typeof(long) || u == typeof(int) || u == typeof(short) || u == typeof(byte)
         || u == typeof(sbyte) || u == typeof(uint) || u == typeof(ulong) || u == typeof(ushort)
         || u == typeof(float) || u == typeof(double) || u == typeof(decimal)
         || u == typeof(bool) || u == typeof(string);

        // A value that cannot equal the current one, so "read back what I wrote"
        // is a real test rather than a coincidence.
        private static object ProbeValue(object original, Type u)
        {
            try
            {
                if (u == typeof(bool)) return !(original is bool b && b);
                if (u == typeof(string))
                {
                    var s = original as string;
                    return string.IsNullOrEmpty(s) ? "ckf-probe" : s + "-ckf-probe";
                }

                var d = original == null ? 0.0 : Convert.ToDouble(original, CultureInfo.InvariantCulture);

                // Step away from the current value in whichever direction the
                // type has room for.
                double candidate = d + 1.0;
                if (u == typeof(byte)   && d >= byte.MaxValue)   candidate = d - 1.0;
                if (u == typeof(sbyte)  && d >= sbyte.MaxValue)  candidate = d - 1.0;
                if (u == typeof(short)  && d >= short.MaxValue)  candidate = d - 1.0;
                if (u == typeof(ushort) && d >= ushort.MaxValue) candidate = d - 1.0;
                if (u == typeof(int)    && d >= int.MaxValue)    candidate = d - 1.0;
                if (u == typeof(uint)   && d >= uint.MaxValue)   candidate = d - 1.0;
                if (u == typeof(long)   && d >= long.MaxValue)   candidate = d - 1.0;

                if (Math.Abs(candidate - d) < double.Epsilon) return null;
                return Convert.ChangeType(candidate, u, CultureInfo.InvariantCulture);
            }
            catch { return null; }
        }

        private static bool Same(object a, object b)
        {
            if (a == null || b == null) return ReferenceEquals(a, b);
            if (a is string || b is string) return string.Equals(a.ToString(), b.ToString(),
                                                                 StringComparison.Ordinal);
            if (a is bool || b is bool)
            {
                try { return Convert.ToBoolean(a) == Convert.ToBoolean(b); } catch { return false; }
            }
            try
            {
                return Math.Abs(Convert.ToDouble(a, CultureInfo.InvariantCulture)
                              - Convert.ToDouble(b, CultureInfo.InvariantCulture)) < 1e-9;
            }
            catch { return false; }
        }

        private static string Show(object v) =>
            v == null ? "null" : Convert.ToString(v, CultureInfo.InvariantCulture);

        private static void Write()
        {
            try
            {
                var dir = Path.GetDirectoryName(outputPath);
                if (!string.IsNullOrEmpty(dir)) Directory.CreateDirectory(dir);

                var sb = new StringBuilder("Table,Column,Type,Verdict,Detail\n");
                foreach (var f in Findings.OrderBy(x => x.Table, StringComparer.Ordinal)
                                          .ThenBy(x => x.Column, StringComparer.Ordinal))
                    sb.Append(Escape(f.Table)).Append(',')
                      .Append(Escape(f.Column)).Append(',')
                      .Append(Escape(f.Type)).Append(',')
                      .Append(Escape(f.Verdict)).Append(',')
                      .Append(Escape(f.Detail)).Append('\n');

                File.WriteAllText(outputPath, sb.ToString(), new UTF8Encoding(false));
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"ModelRules: could not write {outputPath}: {e.Message}");
                Plugin.Log.LogError("If the game is installed under Program Files, Windows may be "
                    + "blocking the write. Set probeOutput in the \"modelrules\" section of "
                    + "ckf.hardmode.json to a path you own.");
                Enabled = false;      // no point probing further with nowhere to put it
            }
        }

        private static string Escape(string s)
        {
            if (string.IsNullOrEmpty(s)) return "";
            return s.IndexOfAny(new[] { ',', '"', '\n', '\r' }) < 0
                ? s : "\"" + s.Replace("\"", "\"\"") + "\"";
        }
    }
}
