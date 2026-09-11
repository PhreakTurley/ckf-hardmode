// SelfCheck — assert what the config should produce, in one launch, no sweep.
//
// THE PROBLEM THIS SOLVES is stated in docs/verifying-2.5.md: verifying the
// arithmetic needs every affected row to be read, the only thing that forced
// that was a CKF Data Dump whole-table sweep, and Run 42 showed a sweep and
// cloning cannot be used together — the mission hung on load. The doc's own
// conclusion was "verify from an ordinary play session instead and accept
// partial coverage."
//
// Partial coverage is not necessary. A whole-table read is the dangerous thing;
// a BY-ID read is what the game itself does, and Runs 40, 41 and 43 all served
// clones that way with no trouble. So this reads exactly the rows an
// expectations file names, by id, through the game's own reader — the same call
// the game makes when a monster resolves its gear — and compares the columns
// against values written down in advance.
//
// That means every rule in the file can be checked whether or not a mission
// happens to spawn the enemy that uses it, and the answer is arithmetic:
//
//   SelfCheck: PASS ArmorModel 22007 BallisticArmorDegraded = 46   [A: the old regression]
//   SelfCheck: FAIL ArmorModel 22106 BallisticArmor = 35, expected 0
//                   [C: the zero-column guard]
//
// It reads rows the game has not asked for, so it is a diagnostic rather than
// part of play, and it is OFF by default — David's ruling 2026-08-31, the one
// exception to "every feature switch defaults true". It is a verification-launch
// tool: retune, turn it on, regenerate the expectations, read the block, turn it
// off. What it does is safe by construction — it is
// one nested by-id read, shallower than the read RowClone already performs
// inside the same hook to materialize a clone — but it is still work the game
// did not ask for, and one of those reads builds a clone earlier than the game
// would have.
//
// TIMING. The database objects are instance-bound and there is no singleton to
// ask, so an instance can only be captured off a call the game makes. This
// patches nothing of its own, because a database is per-TYPE and not
// per-table — one DataDb instance can call ReadMonsterType and ReadEffect just
// as well as ReadArmor.
//
// TWO HOOKS HAND ONE OVER. There used to be only one.
//
//   ModelRules.AfterGetRow   the __instance of every hooked materializer.
//                            Installed whenever ModelRules has anything to
//                            hook, which is the ordinary case.
//   RowClone.Remember        the __instance of every hooked reader. Installed
//                            only when the rules file carries a clone rule.
//
// RowClone was the only source, so a rules file with no clone rules — which is
// what the shipped config is — printed "waiting for a database instance" and
// then nothing at all: no PASS, no FAIL, no SKIP list, no CSV. That is the
// exact failure the note above Offer() says this file was rewritten to prevent.
//
// AND IT MAKES CLONES MATERIALIZE EARLY, which is a real consequence and not
// only a timing detail: reading a cloned id by id builds it there and then,
// against whatever database instance is live at that moment. RowClone used to
// pin that instance for the rest of the session — see the comment on
// RowClone.Instance — so a self-check at the menu could leave every later
// serve re-reading through a stale database. Fixed in 2.7.2; the live instance
// now wins. If this file is ever moved earlier again, that is the invariant to
// keep.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text;
using System.Text.Json;
using System.Text.Json.Serialization;
using HarmonyLib;   // AccessTools only; this file installs no patches.

namespace CKFHardMode
{
    internal static class SelfCheck
    {
        private sealed class Expectation
        {
            public string Table;
            public long Id;
            public string Column;
            public double? Expect;       // null: report the value, do not judge
            public string Note;
            public int Line;

            public string Actual = "";
            public string Verdict = "";

            // Why the row could not be judged, set on every attempt that did
            // not produce a row this expectation's id names. "the table does
            // not hold this id" and "never read" are different answers and the
            // report says which.
            public string Miss;
        }

        private static readonly List<Expectation> Wanted = new List<Expectation>();
        private static readonly List<Type> Dbs = new List<Type>();

        private static string outputPath;
        private static bool enabled;
        private static bool ran, running;

        // model name -> the row type its materializer returns, and the database
        // that declares it. Same derivation RowClone uses.
        private static readonly Dictionary<string, Type> ModelTypes =
            new Dictionary<string, Type>(StringComparer.OrdinalIgnoreCase);
        private static readonly Dictionary<string, Type> ModelHome =
            new Dictionary<string, Type>(StringComparer.OrdinalIgnoreCase);

        // model name -> the by-id reader, per database that has one.
        private static readonly Dictionary<string, Dictionary<Type, MethodInfo>> Readers =
            new Dictionary<string, Dictionary<Type, MethodInfo>>(StringComparer.OrdinalIgnoreCase);

        private static readonly Dictionary<Type, object> Instances =
            new Dictionary<Type, object>();

        // Offers seen. A deadline on this guarantees a report even if a
        // database this file needs is never handed over at all.
        private static int offers;
        private const int OfferDeadline = 500;

        // ...and a deadline in wall-clock time beside it, because counting
        // offers is not counting time. A quiet session — one that loads a save
        // and sits at the base — can read a few dozen rows and stop, so the
        // 500th offer never arrives and the report was never written at all,
        // which is the silence the note above Offer() promises not to produce.
        //
        // Five minutes from Init. Nothing in this source measures how long a
        // load takes, so the number is deliberately generous rather than
        // derived: a launch that reaches any database reader at all reaches it
        // far inside five minutes, and a report five minutes late is still a
        // report. Whichever deadline arrives first settles it, and both only
        // fire on the next offer — this file installs no timer.
        private static readonly TimeSpan TimeDeadline = TimeSpan.FromMinutes(5.0);
        private static System.Diagnostics.Stopwatch clock;

        // Read on ModelRules' per-row hot path to decide whether to offer at
        // all, so it reads two static bools and does nothing else.
        internal static bool Wants => enabled && !ran;

        // ---- setup -------------------------------------------------------------

        // 3.0: the three [SelfCheck] cfg keys are the "selfcheck" section of
        // ckf.hardmode.json. The section is new — it has no 2.x sidecar behind
        // it — and it is flat, so ConfigDoc.ReadSection does the grading and
        // the unknown-key report.
        private sealed class Options : ConfigDoc.IHasUnknownKeys
        {
            // enabled defaults to false here and true everywhere else; that is
            // deliberate — this is a diagnostic, not part of play — and the
            // schema carries the same false.
            [JsonPropertyName("enabled")] public bool Enabled { get; set; }
            [JsonPropertyName("file")]    public string File { get; set; } = "";
            [JsonPropertyName("output")]  public string Output { get; set; } = "";
            [JsonExtensionData] public Dictionary<string, JsonElement> Unknown { get; set; }
            public Dictionary<string, JsonElement> UnknownKeys { get { return Unknown; } }
        }

        // dbTypes comes from ModelRules.ResolvedDbs. Plugin.Load calls this
        // whether or not ModelRules ran, so this subsystem's own setting is
        // honoured either way; it used to be initialised from inside
        // ModelRules.Init, which meant the whole [SelfCheck] section vanished
        // from ckf.hardmode.cfg on a launch with ModelRules off, taking the
        // user's setting with it. The keys are not BepInEx binds any more, so
        // that particular failure cannot recur — but the call still belongs
        // here, because a launch with ModelRules off is exactly the one where
        // this subsystem has something to say.
        public static void Init(string configDir, List<Type> dbTypes)
        {
            // absentIsOrdinary: this is the one subsystem that ships OFF, so a
            // document with no "selfcheck" section is an ordinary configuration
            // and says nothing about a mistake. An UNREADABLE document is still
            // an Error - the same split MissionRewards makes.
            var opt = ConfigDoc.ReadSection<Options>("SelfCheck", ConfigDoc.SelfCheck,
                "The regression suite does not run this launch and no report is written, "
                + "which is also what it does when it is simply switched off.",
                absentIsOrdinary: true);
            if (opt == null) return;

            enabled = opt.Enabled;
            if (!enabled) return;

            var path = string.IsNullOrWhiteSpace(opt.File)
                ? Path.Combine(configDir, "ckf.hardmode.selfcheck.csv")
                : opt.File;

            outputPath = string.IsNullOrWhiteSpace(opt.Output)
                ? Path.Combine(Path.GetDirectoryName(configDir) ?? ".",
                               "ckf-hardmode", "selfcheck.csv")
                : opt.Output;

            if (!Load(path)) { enabled = false; return; }

            // No database types means nothing hooks a materializer or a reader,
            // so no instance can ever arrive and not one expectation can be
            // read. Say so at load rather than waiting silently for a hook that
            // does not exist.
            if (dbTypes == null || dbTypes.Count == 0)
            {
                enabled = false;
                Plugin.Log.LogError($"SelfCheck: enabled, and {Wanted.Count} expectation(s) "
                    + "loaded, but it was handed no database types. Those come from ModelRules, "
                    + "which resolves them only when \"enabled\" is true in the \""
                    + ConfigDoc.ModelRules + "\" section of " + ConfigDoc.FileName + ", the "
                    + "rules file gives it something to hook, and its initialisation finished. "
                    + "Nothing will hand SelfCheck a database instance, so NOTHING IS CHECKED "
                    + "this launch and no report is written. There should be a line above "
                    + "saying which of those three it was.");
                return;
            }

            Dbs.AddRange(dbTypes);
            Resolve();

            clock = System.Diagnostics.Stopwatch.StartNew();

            Plugin.Log.LogInfo($"SelfCheck: {Wanted.Count} expectation(s) over "
                + $"{Wanted.Select(w => w.Table + "/" + w.Id).Distinct().Count()} row(s); "
                + "waiting for a hooked materializer or reader to hand over a database instance. "
                + "It patches nothing of its own — one DataDb instance answers every DataDb "
                + $"table. It reports at the latest {TimeDeadline.TotalMinutes:0} minutes from "
                + $"now, or after {OfferDeadline} instances, whichever comes first.");
        }

        private static bool Load(string path)
        {
            if (!File.Exists(path))
            {
                Plugin.Log.LogWarning($"SelfCheck: enabled, but there is no {path}. "
                    + "Columns: Table,Id,Column,Expect,Note.");
                return false;
            }

            var raw = File.ReadAllLines(path, Encoding.UTF8);
            bool header = false;

            for (int n = 0; n < raw.Length; n++)
            {
                var line = raw[n];
                if (n == 0 && line.Length > 0 && line[0] == '﻿') line = line.Substring(1);
                if (line.Trim().Length == 0) continue;
                if (line.TrimStart().StartsWith("#", StringComparison.Ordinal)) continue;

                var c = Overlays.SplitLine(line, ',');
                if (!header)
                {
                    header = true;
                    if (c.Length > 0 && c[0].Trim().Equals("Table", StringComparison.OrdinalIgnoreCase))
                        continue;                       // it was a header; otherwise fall through
                }
                if (c.Length < 3) continue;

                var table = c[0].Trim();
                // OrdinalIgnoreCase, not Ordinal: ModelTypes, ModelHome and
                // Readers are all case-insensitive, so an expectations file
                // saying "armormodel" used to become "armormodelModel" and get
                // reported as having no materializer.
                if (!table.EndsWith("Model", StringComparison.OrdinalIgnoreCase)) table += "Model";

                long id;
                if (!long.TryParse(c[1].Trim(), NumberStyles.Integer,
                                   CultureInfo.InvariantCulture, out id))
                {
                    Plugin.Log.LogWarning($"SelfCheck[{n + 1}]: '{c[1]}' is not an id.");
                    continue;
                }

                double d;
                double? expect = null;
                var text = c.Length > 3 ? c[3].Trim() : "";
                if (text.Length > 0)
                {
                    if (double.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out d))
                        expect = d;
                    else
                    {
                        Plugin.Log.LogWarning($"SelfCheck[{n + 1}]: expected value '{text}' is "
                            + "not a number; the column will be reported, not judged.");
                    }
                }

                Wanted.Add(new Expectation
                {
                    Table = table,
                    Id = id,
                    Column = c[2].Trim(),
                    Expect = expect,
                    Note = c.Length > 4 ? c[4].Trim() : "",
                    Line = n + 1,
                });
            }

            if (Wanted.Count == 0)
                Plugin.Log.LogWarning($"SelfCheck: {path} holds no expectations.");
            return Wanted.Count > 0;
        }

        // The row type and the by-id reader, derived exactly as RowClone does —
        // off the materializer's return type, and then any Read* taking one
        // integer and returning that type. Never off the method's NAME, which
        // is not reliably Read<Table>.
        private static void Resolve()
        {
            foreach (var db in Dbs)
                foreach (var m in AccessTools.GetDeclaredMethods(db))
                    if (m.Name.StartsWith("GetRow", StringComparison.Ordinal)
                        && m.Name.EndsWith("Model", StringComparison.Ordinal)
                        && m.ReturnType != null && !m.ReturnType.IsValueType)
                    {
                        var key = m.Name.Substring("GetRow".Length);
                        if (ModelTypes.ContainsKey(key)) continue;
                        ModelTypes[key] = m.ReturnType;
                        ModelHome[key] = db;
                    }

            foreach (var table in Wanted.Select(w => w.Table).Distinct())
            {
                Type rowType;
                if (!ModelTypes.TryGetValue(table, out rowType))
                {
                    Plugin.Log.LogWarning($"SelfCheck: no materializer for {table}; its "
                        + "expectations cannot be checked.");
                    continue;
                }

                var found = new Dictionary<Type, MethodInfo>();
                foreach (var db in Dbs)
                    foreach (var m in AccessTools.GetDeclaredMethods(db))
                    {
                        if (m.IsAbstract || m.ReturnType != rowType) continue;
                        if (!m.Name.StartsWith("Read", StringComparison.Ordinal)) continue;
                        var ps = m.GetParameters();
                        if (ps.Length != 1) continue;
                        var pt = Nullable.GetUnderlyingType(ps[0].ParameterType)
                                 ?? ps[0].ParameterType;
                        if (pt != typeof(long) && pt != typeof(int)) continue;
                        if (!found.ContainsKey(db)) found[db] = m;
                    }

                if (found.Count == 0)
                    Plugin.Log.LogWarning($"SelfCheck: {table} has no by-id reader; its "
                        + "expectations cannot be checked.");
                else
                    Readers[table] = found;
            }
        }

        // ---- the check ----------------------------------------------------------
        //
        // ONE INSTANCE IS NOT ENOUGH, and assuming it was cost 96 of 102 checks
        // in Log10. A database is per-TYPE, so a DataDb instance can call every
        // DataDb reader — that part was right. What was wrong was finishing on
        // the FIRST instance offered: that one was a GameDb, and the only
        // content table GameDb can read is WeaponModel, because GameDb declares
        // a ReadWeapon(long) of its own. Six WeaponModel checks resolved and the
        // other ninety-six were reported "row not read".
        //
        // So this resolves incrementally. Every new database type that arrives
        // settles whatever it can, and the report goes out when nothing is left
        // pending — or at a deadline, so that a database which never arrives
        // produces an honest SKIP list instead of silence.
        //
        // This still patches nothing of its own: ModelRules and RowClone hook
        // the materializers and the readers and hand over what they see.
        // SelfCheck used to add capture-only prefixes to five more readers,
        // which is what got a DataDb instance early — but docs/patching-rules.md
        // is explicit that IL2CPP folds function bodies and that the dangerous
        // case is invisible to managed code. Waiting for the instance is the
        // cheaper trade.
        public static void Offer(Type dbType, object instance)
        {
            if (!enabled || ran || running || dbType == null || instance == null) return;

            offers++;

            // Either deadline settles it: enough instances, or enough time. The
            // clock is only read here, so an offer is still what triggers the
            // report — there is no timer and nothing runs on its own thread.
            var due = offers >= OfferDeadline
                   || (clock != null && clock.Elapsed >= TimeDeadline);

            var isNew = !Instances.ContainsKey(dbType);
            if (isNew) Instances[dbType] = instance;
            else if (!due) return;                     // nothing new to try yet

            running = true;
            try
            {
                var pending = Settle();
                if (pending == 0 || due)
                {
                    if (pending > 0)
                        Plugin.Log.LogWarning($"SelfCheck: reporting with {pending} "
                            + "expectation(s) still unread — the database that owns those "
                            + "tables was never handed over"
                            + (offers >= OfferDeadline
                                ? $" in {offers} instances."
                                : $" in {clock.Elapsed.TotalMinutes:0.#} minutes.")
                            + " They show as SKIP.");
                    Report();
                    ran = true;
                }
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"SelfCheck: {e.GetType().Name}: {e.Message}");
                ran = true;
            }
            finally { running = false; }
        }

        // Settle every expectation that can be settled with the instances held
        // now. Returns how many are still unread.
        private static int Settle()
        {
            int pending = 0;

            foreach (var group in Wanted.GroupBy(w => w.Table + "|" + w.Id))
            {
                if (group.All(w => w.Verdict.Length > 0)) continue;   // already settled

                var first = group.First();
                string miss;
                var row = ReadRow(first.Table, first.Id, out miss);
                if (row == null)
                {
                    // Still pending: another database may arrive later and hold
                    // the row. The reason travels with each expectation so that
                    // the final report can say which kind of miss this was.
                    foreach (var w in group) w.Miss = miss;
                    pending += group.Count();
                    continue;
                }

                foreach (var w in group)
                {
                    // The row is in hand, so an earlier attempt's miss reason no
                    // longer describes this expectation and must not be counted
                    // against it in the report.
                    w.Miss = null;

                    var acc = Accessors.Get(row.GetType(), w.Column);
                    if (acc == null || !acc.Exists)
                    {
                        w.Verdict = "SKIP";
                        w.Actual = NoSuchColumn;
                        continue;
                    }

                    double v;
                    if (!acc.TryGetNumber(row, out v))
                    {
                        var raw = acc.GetRaw(row);
                        w.Actual = raw == null ? "null" : raw.ToString();
                        w.Verdict = w.Expect.HasValue ? "FAIL" : "INFO";
                        continue;
                    }

                    w.Actual = v.ToString("0.####", CultureInfo.InvariantCulture);
                    if (!w.Expect.HasValue) { w.Verdict = "INFO"; continue; }

                    w.Verdict = Math.Abs(v - w.Expect.Value) <= Tolerance(acc, w.Expect.Value)
                              ? "PASS" : "FAIL";
                }
            }
            return pending;
        }

        private static void Report()
        {
            foreach (var w in Wanted)
                if (w.Verdict.Length == 0)
                {
                    w.Verdict = "SKIP";
                    w.Actual = w.Miss ?? MissUnread;
                }

            int pass = Wanted.Count(w => w.Verdict == "PASS");
            int fail = Wanted.Count(w => w.Verdict == "FAIL");

            // INFO and SKIP are not the same thing and used to be one number.
            // INFO is a row that WAS read and carries no expected value, so
            // there was nothing to judge — deliberate, and a clean result. SKIP
            // is a row that was never read, or was read and turned out not to
            // exist. An all-INFO expectations file used to print "12 were never
            // read — this is NOT a clean pass", which was false about all twelve.
            int info = Wanted.Count(w => w.Verdict == "INFO");
            int skip = Wanted.Count(w => w.Verdict == "SKIP");
            int absent = Wanted.Count(w => w.Verdict == "SKIP" && w.Miss != null
                                        && w.Miss != MissUnread);

            foreach (var w in Wanted)
            {
                var note = string.IsNullOrEmpty(w.Note) ? "" : $"   [{w.Note}]";
                var line = w.Verdict == "PASS"
                    ? $"SelfCheck: PASS {w.Table} {w.Id} {w.Column} = {w.Actual}{note}"
                    : w.Verdict == "FAIL"
                    ? $"SelfCheck: FAIL {w.Table} {w.Id} {w.Column} = {w.Actual}, "
                      + $"expected {w.Expect.Value.ToString("0.###", CultureInfo.InvariantCulture)}{note}"
                    : $"SelfCheck: {w.Verdict} {w.Table} {w.Id} {w.Column} = {w.Actual}{note}";

                if (w.Verdict == "FAIL") Plugin.Log.LogError(line);
                else Plugin.Log.LogInfo(line);
            }

            // "all expectations met" with ninety-six of them unread is how
            // Log10 read, and it is the wrong thing for a checker to say.
            // Silence about what was not checked is not a pass. An INFO row is
            // not silence, though: it was read, and the file asked for no
            // judgement on it, so a file whose only unjudged rows are INFO is a
            // clean pass.
            int noColumn = Wanted.Count(w => w.Verdict == "SKIP" && w.Actual == NoSuchColumn);
            int unread = skip - absent - noColumn;

            var parts = new List<string>();
            if (unread > 0)   parts.Add($"{unread} never read");
            if (absent > 0)   parts.Add($"{absent} name a row their table does not hold");
            if (noColumn > 0) parts.Add($"{noColumn} name a column their row does not have");
            var breakdown = parts.Count > 0 ? " (" + string.Join(", ", parts) + ")" : "";

            var verdict = fail > 0 ? $"{fail} FAILED"
                        : skip > 0 ? $"nothing contradicted, but {skip} could not be judged"
                                     + breakdown + " — this is NOT a clean pass"
                        : info > 0 ? $"all {pass} judged expectation(s) met; the other {info} "
                                     + "carry no expected value and were reported, not judged. "
                                     + "Clean pass"
                        : "all expectations met";
            Plugin.Log.LogInfo($"SelfCheck: {Wanted.Count} expectation(s) — {pass} passed, "
                             + $"{fail} failed, {info} reported only, {skip} not judged. "
                             + $"{verdict}.");
            if (fail > 0)
                Plugin.Log.LogError("SelfCheck: a failure here is arithmetic, not a judgement "
                    + "call — the config does not produce what the expectations file says it "
                    + "should. Search this log for 'SelfCheck: FAIL'.");

            Write();
        }

        // How close counts as equal, and it matters which.
        //
        // An integer column rounds on write, so half a unit is the same number.
        // A float column must NOT get that slack: ChasingSpeed 3.75 x 1.1 is
        // 4.125, and a half-unit window would call 3.75 a pass — which is
        // exactly the case where the rule failed to fire.
        private static double Tolerance(Accessor acc, double expected)
        {
            var code = Type.GetTypeCode(acc.Underlying);
            bool integral = code != TypeCode.Single && code != TypeCode.Double
                                                    && code != TypeCode.Decimal;
            if (integral) return 0.5;
            return Math.Max(1e-4, Math.Abs(expected) * 1e-6);
        }

        // The two ways an expectation ends up unjudged, and they are not the
        // same answer: "never read" means no database that could answer this
        // table ever arrived, and "holds no row with id N" means one did answer
        // and the row is not there. NoSuchColumn is the third — the row was
        // read, and it has no column by that name.
        private const string MissUnread = "row not read";
        private const string NoSuchColumn = "no such column";

        // The read the game itself makes. NOT under RowClone's re-entrancy
        // guard: the guard exists so that materializing a clone does not
        // recurse, and setting it here would take the clone-serving prefix out
        // of the path — which is one of the things being checked.
        //
        // `miss` says why nothing came back, for the report.
        private static object ReadRow(string table, long id, out string miss)
        {
            miss = MissUnread;

            Dictionary<Type, MethodInfo> byDb;
            if (!Readers.TryGetValue(table, out byDb)) return null;

            // Prefer the database that declares the materializer, then anything
            // we hold an instance for.
            Type home;
            ModelHome.TryGetValue(table, out home);

            foreach (var db in Enumerable.Repeat(home, 1).Concat(byDb.Keys))
            {
                MethodInfo reader;
                object instance;
                if (db == null) continue;
                if (!byDb.TryGetValue(db, out reader)) continue;
                if (!Instances.TryGetValue(db, out instance) && !reader.IsStatic) continue;

                try
                {
                    var row = reader.Invoke(reader.IsStatic ? null : instance,
                                            new object[] { Convert.ChangeType(id,
                                                Nullable.GetUnderlyingType(
                                                    reader.GetParameters()[0].ParameterType)
                                                ?? reader.GetParameters()[0].ParameterType) });
                    if (row == null) continue;

                    // NOT "non-null is the row". A by-id reader answers a miss
                    // with a live object whose every column is defaulted — the
                    // same behaviour RowClone.ReadById exists for — so an
                    // expectation of 0 on an id no rule ever created used to
                    // read 0 off a defaulted row and report PASS. Green for a
                    // row that does not exist is worse than no answer, so the
                    // row is accepted only when its own id column carries the
                    // id that was asked for.
                    if (IsRow(row, table, id)) return row;
                    miss = $"{table} holds no row with id {id}";
                }
                catch (Exception e)
                {
                    // GameDb.ReadWeapon throws on an id it does not hold where
                    // DataDb returns a defaulted row. Try the next database
                    // rather than treating a throw as an answer.
                    Plugin.Log.LogWarning($"SelfCheck: {db.Name}.{reader.Name}({id}) threw "
                        + $"{(e.InnerException ?? e).GetType().Name}; trying another database.");
                }
            }
            return null;
        }

        // Does this row carry the id that was asked for?
        //
        // The id column is the table's name without "Model" plus "Id" —
        // ArmorModel.ArmorId — which is the derivation ModelRules.Label and
        // RowClone both use. A row whose id column is missing or unreadable is
        // NOT accepted: it cannot be confirmed to be the row asked for, and
        // judging it would be the false PASS this check exists to stop.
        private static bool IsRow(object row, string table, long id)
        {
            var column = (table.EndsWith("Model", StringComparison.OrdinalIgnoreCase)
                        ? table.Substring(0, table.Length - "Model".Length) : table) + "Id";

            var acc = Accessors.Get(row.GetType(), column);
            if (acc == null || !acc.Exists || !acc.Numeric)
            {
                if (WarnedIdColumns.Add(table))
                    Plugin.Log.LogWarning($"SelfCheck: {table} has no readable numeric "
                        + $"'{column}', so a row read from it cannot be confirmed to be the row "
                        + "asked for. Its expectations are reported as SKIP rather than judged "
                        + "against a row that may be a defaulted miss.");
                return false;
            }

            double v;
            if (!acc.TryGetNumber(row, out v)) return false;
            return (long)Math.Round(v) == id;
        }

        private static readonly HashSet<string> WarnedIdColumns =
            new HashSet<string>(StringComparer.OrdinalIgnoreCase);

        private static void Write()
        {
            if (string.IsNullOrEmpty(outputPath)) return;
            try
            {
                Directory.CreateDirectory(Path.GetDirectoryName(outputPath));
                var sb = new StringBuilder("Verdict,Table,Id,Column,Actual,Expected,Note,Line\n");
                foreach (var w in Wanted)
                    sb.Append(w.Verdict).Append(',')
                      .Append(w.Table).Append(',').Append(w.Id).Append(',')
                      .Append(w.Column).Append(',')
                      .Append(Csv(w.Actual)).Append(',')
                      .Append(w.Expect.HasValue
                              ? w.Expect.Value.ToString("0.###", CultureInfo.InvariantCulture) : "")
                      .Append(',').Append(Csv(w.Note)).Append(',').Append(w.Line).Append('\n');
                File.WriteAllText(outputPath, sb.ToString());
                Plugin.Log.LogInfo($"SelfCheck: wrote {outputPath}");
            }
            catch (Exception e)
            {
                Plugin.Log.LogWarning($"SelfCheck: could not write {outputPath}: {e.Message}");
            }
        }

        private static string Csv(string s)
        {
            s = s ?? "";
            return s.IndexOfAny(new[] { ',', '"', '\n' }) < 0
                 ? s : "\"" + s.Replace("\"", "\"\"") + "\"";
        }

    }
}
