// Progression — control the Team Power Level a completed mission awards.
//
// HOW THE AWARD ACTUALLY WORKS [measured: traced and reconciled against a save]
// ------------------------------------------------------------------------------
// Team Power Level is not a stored counter and it is not a number anything
// writes. It is a sum over the save's own mission log:
//
//     GameDb.SumGameMissionScore() -> Single
//
//   = SUM over GameMissionScoreModel rows of
//         MissionPowerLevelModel.PowerLevelFraction[ActionClass, MissionPowerLevel]
//
// Verified exactly, not approximately. On the traced save, summing that lookup
// over all 127 GameMissionScoreModel rows gives 7.7075, and over the first 126
// gives 7.6925 — the two numbers the trace printed either side of the insert:
//
//     TRACE GameDb.SumGameMissionScore()      -> 7.6925
//     TRACE GameDb.InsertGameMissionScore(...) -> 127
//     TRACE GameDb.SumGameMissionScore()      -> 7.7075
//
// Rows whose (ActionClass, MissionPowerLevel) has no cell contribute nothing.
// LEGWORK rows are (0, 0) and there is no class-0 band, which is why the
// arithmetic lands on the nose.
//
// THE ROW CARRIES NO NUMBER
// -------------------------
// GameMissionScoreModel has six columns and that is all of them:
//
//     Id, MissionTypeId, MissionPowerLevel, ActionClass, GameTurn, MissionSuccessful
//
// There is no fraction on the row. The award is entirely a function of the two
// join keys.
//
// The victory screen and the sum read MissionPowerLevelModel by two paths:
// the screen goes through the materialiser the rule engine patches; the sum
// reads the table underneath it. A rule on MissionPowerLevelModel alone makes
// the screen say "Team gained 3 PL" while the sum moves 0.015 [measured]. Only
// the screen's path is hookable by a rule, so the sum is replaced here and the
// screen is kept in step by MissionPowerLevelModel.generated.json (generated
// by scripts/gen_teampl_labels.py from this file's grids).
//
// SETTINGS: ckf.hardmode.d/teampl.json (the switch is [Slices] Progression in
// ckf.hardmode.cfg):
//
//   { "_version": ..., "table": [ ... ], "override": [ ... ] }
//
// "table" is the game's own MissionPowerLevelModel and is reference only: it
// is what the reconcile check below is measured against. "override" is where
// the edits go: exact, per (ActionClass, MissionPowerLevel) cell. A cell
// absent from "override" keeps its "table" value. This is the only lever;
// nothing rewrites the inserted row, so InsertGameMissionScore is not patched.
//
// ACCEPTED COST: every Team PL edit is retroactive. There is no way to change
// future awards without re-pricing past ones, and the substituted total
// persists into the save. See the warning below.
//
// ACTIONCLASS — SETTLED BY THE SAVE, NOT INFERRED
// -----------------------------------------------
// 127 completed missions, every one classed by the game itself:
//
//   0  LEGWORK only, always PL 0, always worth nothing
//   1  story missions and Power Play missions
//   2  Treaty contracts — the standard proc-gen board
//   3  solo hacks — every HackCPU / HackFile / HackLoot, whatever generated it
//
// Class 3 wins over its source: M_PGenPower_Icarus_M1_HackCPU is class 3, not
// class 1, and M_PGenTreaty_HackCPU is class 3, not class 2.
//
// RETROACTIVE MODE — replacing the table the sum reads
// ----------------------------------------------------
// This subsystem postfixes SumGameMissionScore and recomputes the whole total
// from "override" merged over "table", so every past mission re-prices at once
// and arbitrary values are reachable: nothing has to be stored in a row.
//
// It works by enumerating GameMissionScoreModel through GameDb's own bulk
// reader and summing our table over the row keys. The reader is found by shape
// — a no-argument method on GameDb returning a list of GameMissionScoreModel —
// rather than by a guessed name.
//
// THE SELF-CHECK, AND WHY IT MATTERS
// -----------------------------------
// Before substituting anything, the same enumeration is summed with the GAME'S
// values and compared against the number the game just returned. If our model
// of the sum is right the two agree to the float; if they do not, something is
// wrong — a filter we cannot see, rows we cannot reach, a changed schema — and
// the retroactive path SHUTS ITSELF OFF rather than writing a number it cannot
// justify. Watch for:
//
//     Progression: reconciled 7.7075 over 127 row(s).
//
// At the main menu there are no rows to enumerate and the game returns 0, which
// is not something to reconcile against; that case says "nothing to reconcile
// yet" and the line above still follows once a save is open. The empty case is
// never counted as a successful reconcile.
//
// A cache is kept and rebuilt whenever EITHER the game's own answer stops
// matching the cached row set OR the number of rows changes. The row count is
// the second signal because the first cannot see a new row that is worth zero in
// the stock table — every LEGWORK row is (0, 0) and worth nothing — so without
// it a LEGWORK mission would leave the cache stale for the rest of the session.
//
// Loading a save also drops all of it, through the same
// ViewModel_GameManagement.LoadGame / .LoadGameSlot seam Elapse and Fatigue use.
//
// > WARNING: the substituted total is what the game then persists. A traced
// > log shows CoreGameDataModel.PowerLevel holding the same number the sum
// > returned [measured]. Turning this off later leaves that mirror holding a
// > modded figure until something recomputes it. This is a save-affecting
// > setting, and the only mode this subsystem has.
//
// VERIFYING
// ---------
// CKF Data Dump: [Diagnostics] TraceMethods = RPG.Database.GameDb.SumGameMissionScore
// The difference across the insert is the award. The victory screen is not
// evidence: it reads a different path at a different time.

using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Text.Json;
using System.Text.Json.Serialization;
using BepInEx;
using HarmonyLib;

namespace CKFHardMode
{
    internal static class Progression
    {
        private const string TypeName = "RPG.Database.GameDb";

        // The save-load seam. Elapse and Fatigue patch the same pair for the
        // same reason: ViewModel_GameManagement.LoadGame(CoreGameDataModel) and
        // .LoadGameSlot(CoreGameDataModel, CoreGameSaveSlotModel) are the only
        // two methods in the interop assembly that name loading a saved game.
        // Whether either fires on the path the player takes is not determinable
        // from this source; the warning in PatchSum is what a play session
        // answers that with.
        private const string GameManagementTypeName = "ViewModel_GameManagement";

        // A row filed under a class with no band contributes nothing to the sum.
        // [measured] LEGWORK rows are (0,0) and the total reconciles to the
        // traced figure only if they are worth zero.

        private static bool enabled;
        // The game's MissionPowerLevelModel, as loaded from the config file.
        private static readonly Dictionary<(long, long), double> Cells =
            new Dictionary<(long, long), double>();

        // Retroactive mode: (ActionClass, MissionPowerLevel) -> replacement value.
        // Arbitrary. A cell absent here keeps its stock value.
        private static readonly Dictionary<(long, long), double> Overrides =
            new Dictionary<(long, long), double>();

        private sealed class Cell
        {
            [JsonPropertyName("ActionClass")]        public int ActionClass { get; set; }
            [JsonPropertyName("MissionPowerLevel")]  public int MissionPowerLevel { get; set; }
            [JsonPropertyName("PowerLevelFraction")] public double PowerLevelFraction { get; set; }
        }

        private sealed class FileShape
        {
            // RETIRED gate. The switch is [Slices] Progression in
            // ckf.hardmode.cfg, because a gate cannot live inside the file it
            // gates. "enabled" is still parsed so a file carrying it is not
            // refused; nothing branches on it.
            [JsonPropertyName("enabled")]  public bool? RetiredEnabled { get; set; }
            [JsonPropertyName("table")]    public List<Cell> Table { get; set; } = new List<Cell>();
            [JsonPropertyName("override")] public List<Cell> Override { get; set; } = new List<Cell>();
        }

        public static void Init(Harmony harmony)
        {
            // THE GATE IS READ FIRST, from ckf.hardmode.cfg. teampl.json carries
            // only the two grids, so a file that could not be read cannot take
            // this subsystem's switch with it.
            if (!Slices.On("Progression"))
            {
                Plugin.Log.LogInfo(Slices.OffBecause("Progression",
                    "the sum is left exactly as the game computes it."));
                enabled = false;
                return;
            }

            // Load leaves `enabled` false when the file could not be read, which
            // it says at Error rather than letting this read like someone turned
            // it off.
            Load();
            if (!enabled) return;                        // Load already said why

            if (Cells.Count == 0)
            {
                Plugin.Log.LogError("Progression: no \"table\" in "
                    + ConfigDoc.Where(ConfigDoc.TeamPl) + ". Without the game's own cell values "
                    + "there is no way to tell what an award is worth. Regenerate it from "
                    + "ckf-dump/MissionPowerLevelModel.csv. Doing nothing.");
                return;
            }

            var t = AccessTools.TypeByName(TypeName);
            if (t == null)
            {
                Plugin.Log.LogError($"Progression: could not resolve {TypeName}.");
                return;
            }

            // Always retroactive: it is the subsystem's only mode.
            PatchSum(harmony, t);
        }

        // ---- retroactive mode -------------------------------------------------

        private const string SumName = "SumGameMissionScore";

        private static MethodInfo readAll;          // GameDb -> list of GameMissionScoreModel
        private static Dictionary<(long, long), long> counts;   // cached row-key histogram
        // Row count the cached histogram was built from; -1 when unknown. The
        // second invalidation signal — see AfterSum.
        private static long cachedRows = -1;
        private static bool inSum, retroDead, reconciled, announcedEmpty;
        private static int reconcileFailures;
        private static int consecutiveFailures;
        // True once ViewModel_GameManagement.LoadGame/.LoadGameSlot is patched,
        // which is the only thing that resets this subsystem's session state.
        private static bool loadHooked;

        private static void PatchSum(Harmony harmony, Type t)
        {
            if (Overrides.Count == 0)
            {
                Plugin.Log.LogWarning("Progression: enabled, but \"override\" in "
                    + ConfigDoc.Where(ConfigDoc.TeamPl) + " is empty. Nothing would change, "
                    + "so the sum is left alone.");
                return;
            }

            var sum = AccessTools.Method(t, SumName);
            if (sum == null)
            {
                Plugin.Log.LogError($"Progression: {t.Name}.{SumName} not found. Retroactive "
                    + "mode needs it. Run [Diagnostics] FindMethods = SumGameMissionScore.");
                return;
            }

            // Folding check. SumGameMissionScore is a no-argument method returning a
            // float, which is exactly the shape the linker likes to merge. Two
            // proxies on one native address means patching either patches both.
            var ptr = NativePointer(sum);
            if (ptr != IntPtr.Zero)
            {
                foreach (var other in AccessTools.GetDeclaredMethods(t))
                {
                    if (other.Name == SumName) continue;
                    if (NativePointer(other) != ptr) continue;
                    Plugin.Log.LogError($"Progression: {SumName} and {other.Name} resolve to the "
                        + "SAME native method — the linker folded them together. Patching either "
                        + "would patch both. Retroactive mode is off, and it is now this "
                        + "subsystem's only mode, so nothing will be changed.");
                    return;
                }
            }

            // Find the bulk reader by SHAPE, not by a guessed name: no arguments,
            // returning something whose type mentions GameMissionScoreModel.
            foreach (var m in AccessTools.GetDeclaredMethods(t))
            {
                if (m.GetParameters().Length != 0) continue;
                if (m.ReturnType == null) continue;
                var rt = m.ReturnType.ToString();
                if (rt.IndexOf("GameMissionScoreModel", StringComparison.Ordinal) < 0) continue;
                if (rt.IndexOf("List", StringComparison.Ordinal) < 0
                 && rt.IndexOf("[]", StringComparison.Ordinal) < 0) continue;
                readAll = m;
                break;
            }
            if (readAll == null)
            {
                Plugin.Log.LogError($"Progression: no no-argument bulk reader on {t.Name} returns "
                    + "a list of GameMissionScoreModel, so the rows cannot be enumerated and the "
                    + "sum cannot be recomputed. Retroactive mode is off, and it is now this "
                    + "subsystem's only mode, so nothing will be changed.");
                return;
            }

            try
            {
                harmony.Patch(sum, postfix:
                    new HarmonyMethod(AccessTools.Method(typeof(Progression), nameof(AfterSum))));
                Plugin.Log.LogInfo($"Progression: RETROACTIVE — patched {t.Name}.{SumName}, "
                    + $"enumerating via {readAll.Name}(), {Overrides.Count} override cell(s). "
                    + "Every past mission re-prices. Watch for the reconcile line.");
            }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Progression: could not patch {SumName}: {e.Message}");
                return;
            }

            // Everything cached below belongs to ONE save: the row histogram,
            // the reconcile, and the run of failures that can switch retroactive
            // mode off. It is reset on load, or a different playthrough would be
            // summed against the previous one's state. Same seam Elapse and
            // Fatigue use, and the same warning when it does not take.
            loadHooked = PatchLoadHooks(harmony) > 0;
            if (!loadHooked)
                Plugin.Log.LogWarning($"Progression: could not patch {GameManagementTypeName}"
                    + ".LoadGame/LoadGameSlot, so nothing clears this session's state when you "
                    + "load a save. The cached row histogram and the reconcile are re-checked on "
                    + "every sum and correct themselves, but if retroactive mode ever gives up "
                    + "it stays off for the rest of the process — restart the game rather than "
                    + "reloading. Worth reporting.");
        }

        // Postfix on ViewModel_GameManagement.LoadGame / .LoadGameSlot. Takes no
        // arguments on purpose: it wants the fact that a load happened, nothing
        // out of it, and a signature that cannot go stale when the model types
        // move. Same shape as Elapse.AfterLoadGame and Fatigue.AfterLoadGame.
        public static void AfterLoadGame()
        {
            if (!enabled) return;
            try { ForgetSession("a save was loaded"); }
            catch (Exception e)
            {
                Plugin.Log.LogError($"Progression: the load hook threw and was swallowed: {e}");
            }
        }

        // Everything this session remembers that belonged to the save that was
        // open. The histogram is that save's rows and the reconcile is that
        // save's arithmetic, so both go. retroDead and the failure counters go
        // too: a transient throw during the transition INTO this load must not
        // switch the subsystem off permanently, and a freshly loaded save
        // deserves a fresh attempt.
        //
        // announcedEmpty is deliberately NOT reset. It suppresses a repeated
        // message rather than carrying state; clearing it would put the same
        // "nothing to reconcile yet" line in the log after every load.
        private static void ForgetSession(string why)
        {
            long rows = Total(counts);
            bool wasDead = retroDead;

            counts = null;
            cachedRows = -1;
            reconciled = false;
            reconcileFailures = 0;
            consecutiveFailures = 0;
            retroDead = false;

            Plugin.Log.LogInfo($"Progression: {why} — dropped the cached row histogram "
                + $"({rows} row(s)) and the reconcile."
                + (wasDead ? " Retroactive mode had given up; it is armed again." : "")
                + $" The next {SumName} re-enumerates and reconciles against the loaded save.");
        }

        // LoadGame and LoadGameSlot, postfixed. Two interop proxies resolving to
        // one il2cpp method would mean two detours on one address, so the same
        // NativeMethodInfoPtr_* check the folding guard above uses is applied
        // here — this is Elapse.Patch's AlreadyClaimed, spelled with the pointer
        // helper this file already has.
        private static int PatchLoadHooks(Harmony harmony)
        {
            var t = AccessTools.TypeByName(GameManagementTypeName);
            if (t == null)
            {
                Plugin.Log.LogWarning($"Progression: could not resolve "
                    + $"{GameManagementTypeName}.");
                return 0;
            }

            var pf = new HarmonyMethod(AccessTools.Method(typeof(Progression),
                                                          nameof(AfterLoadGame)));
            var claimed = new Dictionary<IntPtr, string>();
            int ok = 0;
            foreach (var m in AccessTools.GetDeclaredMethods(t))
            {
                if (m.IsAbstract) continue;
                if (m.Name != "LoadGame" && m.Name != "LoadGameSlot") continue;

                var ptr = NativePointer(m);
                string owner;
                if (ptr != IntPtr.Zero && claimed.TryGetValue(ptr, out owner))
                {
                    Plugin.Log.LogWarning($"Progression: NOT patching {t.Name}.{m.Name} — it is "
                        + $"the same il2cpp method as {owner}.");
                    continue;
                }

                try
                {
                    harmony.Patch(m, postfix: pf);
                    if (ptr != IntPtr.Zero) claimed[ptr] = m.Name;
                    ok++;
                }
                catch (Exception e)
                {
                    Plugin.Log.LogWarning($"Progression: could not patch {t.Name}.{m.Name}: "
                        + e.Message);
                }
            }
            return ok;
        }

        public static void AfterSum(object __instance, ref float __result)
        {
            if (retroDead || inSum) return;
            bool faulted = false;
            try
            {
                inSum = true;

                // TWO independent invalidation signals. The drift test alone
                // cannot see a new row that is worth ZERO in the game's own
                // table: LEGWORK rows are (ActionClass 0, MissionPowerLevel 0)
                // and there is no class-0 band, so completing a LEGWORK mission
                // moves the game's sum by 0.0. The cached histogram would then
                // stay stale for the rest of the session and an override on that
                // cell would never reach the new row. The ROW COUNT moves whether
                // the row is worth anything or not, so it is checked as well.
                //
                // COST: the bulk read runs once per SumGameMissionScore call.
                // The per-row reflective walk — two property reads per row — is
                // still done only when a signal trips; reading Count off the
                // list the reader already returned is what buys that.
                object list;
                if (!TryReadRows(__instance, out list)) { faulted = true; return; }
                if (list == null) { counts = null; cachedRows = -1; return; }

                // -1 means the count could not be read, which forces a rebuild
                // every call: slower, never stale.
                long rows = RowCount(list);

                if (counts == null || rows < 0 || rows != cachedRows
                    || Math.Abs(Predict(Cells) - __result) > 1e-3)
                {
                    Ingest(list, rows);

                    double check = Predict(Cells);
                    if (Math.Abs(check - __result) > 1e-3)
                    {
                        // Our arithmetic does not reproduce the game's. Refuse to
                        // substitute rather than write a number we cannot justify.
                        if (++reconcileFailures >= 2)
                        {
                            retroDead = true;
                            Plugin.Log.LogError("Progression: RETROACTIVE MODE OFF. Summing the "
                                + $"game's own values over {Total(counts)} enumerated row(s) gives "
                                + $"{check:0.#####}, but {SumName} returned {__result:0.#####}. "
                                + "Something is in the sum that this cannot see — a filter, rows "
                                + "from another reader, or a changed schema. Nothing has been "
                                + "changed, and retroactive mode is now this subsystem's only "
                                + "mode, so Team PL is left exactly as the game computed it.");
                        }
                        counts = null;
                        cachedRows = -1;
                        return;
                    }

                    // A ZERO-ROW enumeration is not a reconcile. At the main menu
                    // nothing is enumerated and the game returns 0, so check ==
                    // __result holds trivially. Taking that as proof would print
                    // the confidence line once and never again for the real rows,
                    // and it is the one line the header tells the operator to
                    // watch for. Require at least one row before claiming the
                    // arithmetic reproduces the game's.
                    long got = Total(counts);
                    if (got == 0)
                    {
                        if (!announcedEmpty)
                        {
                            announcedEmpty = true;
                            Plugin.Log.LogInfo($"Progression: nothing to reconcile yet — "
                                + $"{readAll.Name}() returned 0 row(s) and {SumName} returned "
                                + $"{__result:0.#####}. No save's mission log is visible, so "
                                + "nothing has been checked and nothing is being substituted. "
                                + "The reconcile line follows once a save is loaded.");
                        }
                    }
                    else if (!reconciled)
                    {
                        reconciled = true;
                        Plugin.Log.LogInfo($"Progression: reconciled {__result:0.#####} over "
                            + $"{got} row(s). Substituting the override table.");
                    }
                    reconcileFailures = 0;
                }

                float ours = (float)Predict(Merged);
                if (Math.Abs(ours - __result) < 1e-6) return;
                __result = ours;
            }
            catch (Exception e)
            {
                faulted = true;
                NoteFailure($"{e.GetType().Name}: {e.Message}.");
            }
            finally
            {
                // Any call that got through without a throw clears the run: the
                // threshold below is about CONSECUTIVE failures.
                if (!faulted) consecutiveFailures = 0;
                inSum = false;
            }
        }

        // One throw is not evidence the subsystem is broken. A bulk read can
        // fail while a save is being swapped in underneath it and succeed on the
        // next call, so the first one must not kill retroactive mode for the
        // whole process. Three consecutive failures with no
        // successful call in between is the threshold: high enough that a single
        // load transition cannot reach it, low enough that a reader which is
        // genuinely gone is off long before it can matter.
        private const int FailuresBeforeGivingUp = 3;

        private static void NoteFailure(string what)
        {
            if (++consecutiveFailures < FailuresBeforeGivingUp)
            {
                Plugin.Log.LogWarning($"Progression: {what} Retroactive mode is STILL ON — that "
                    + $"is consecutive failure {consecutiveFailures} of {FailuresBeforeGivingUp}, "
                    + "and a save-load transition can produce one. Team PL is left as the game "
                    + "computed it for this call only.");
                return;
            }

            retroDead = true;
            Plugin.Log.LogError($"Progression: {what} That is {consecutiveFailures} consecutive "
                + "failures with no successful call in between, so RETROACTIVE MODE IS OFF — and "
                + "it is this subsystem's only mode, so Team PL is left exactly as the game "
                + "computed it. "
                + (loadHooked ? "Loading a save re-arms it."
                              : "The save-load hook did not take, so nothing re-arms it: "
                              + "restart the game."));
        }

        // Stock values with the overrides laid on top.
        private static double Merged((long, long) k)
            => Overrides.TryGetValue(k, out var v) ? v
             : Cells.TryGetValue(k, out var c) ? c : 0.0;

        private static double Predict(Func<(long, long), double> value)
        {
            double s = 0.0;
            if (counts == null) return s;
            foreach (var kv in counts) s += value(kv.Key) * kv.Value;
            return s;
        }

        private static double Predict(Dictionary<(long, long), double> table)
            => Predict(k => table.TryGetValue(k, out var v) ? v : 0.0);

        private static long Total(Dictionary<(long, long), long> c)
        {
            long n = 0;
            if (c != null) foreach (var kv in c) n += kv.Value;
            return n;
        }

        // The bulk read on its own. A throw here is counted rather than fatal —
        // see NoteFailure.
        private static bool TryReadRows(object instance, out object list)
        {
            list = null;
            try { list = readAll.Invoke(instance, null); return true; }
            catch (Exception e)
            {
                NoteFailure($"{readAll.Name}() threw {e.GetType().Name}: {e.Message}.");
                return false;
            }
        }

        // How many rows the reader returned, without touching one. This is the
        // invalidation signal that a zero-valued new row still moves; -1 when the
        // list exposes no readable Count, which makes AfterSum rebuild every call.
        private static long RowCount(object list)
        {
            if (list is System.Collections.ICollection coll) return coll.Count;
            try
            {
                var p = AccessTools.Property(list.GetType(), "Count");
                if (p == null) return -1;
                var v = p.GetValue(list);
                return v == null ? -1 : Convert.ToInt64(v, CultureInfo.InvariantCulture);
            }
            catch { return -1; }
        }

        // Walk the rows the reader returned and rebuild the histogram. `rows` is
        // what RowCount said about this same list and is remembered as-is, so
        // the next call compares like with like: rows the walk skips still count
        // towards the signal, which is the safe direction.
        private static void Ingest(object list, long rows)
        {
            var fresh = new Dictionary<(long, long), long>();

            int n = 0;
            foreach (var row in Rows(list))
            {
                if (row == null) continue;
                long ac = ReadLong(row, "ActionClass");
                long pl = ReadLong(row, "MissionPowerLevel");
                if (ac == long.MinValue || pl == long.MinValue) continue;
                var k = (ac, pl);
                fresh.TryGetValue(k, out long had);
                fresh[k] = had + 1;
                if (++n > 100000) break;
            }
            counts = fresh;
            cachedRows = rows;
        }

        // Il2Cpp lists are not managed IEnumerable, so fall back to Count + indexer.
        private static IEnumerable<object> Rows(object list)
        {
            if (list is System.Collections.IEnumerable managed)
            {
                foreach (var o in managed) yield return o;
                yield break;
            }
            var t = list.GetType();
            var countProp = AccessTools.Property(t, "Count");
            var item = AccessTools.Method(t, "get_Item", new[] { typeof(int) });
            if (countProp == null || item == null) yield break;
            int c = Convert.ToInt32(countProp.GetValue(list), CultureInfo.InvariantCulture);
            for (int i = 0; i < c; i++)
            {
                object v = null;
                try { v = item.Invoke(list, new object[] { i }); }
                catch { }
                yield return v;
            }
        }

        private static IntPtr NativePointer(MethodInfo m)
        {
            try
            {
                var f = m.DeclaringType
                    .GetFields(BindingFlags.NonPublic | BindingFlags.Public | BindingFlags.Static)
                    .FirstOrDefault(x => x.FieldType == typeof(IntPtr)
                                      && x.Name.StartsWith("NativeMethodInfoPtr_" + m.Name + "_",
                                                           StringComparison.Ordinal));
                return f == null ? IntPtr.Zero : (IntPtr)f.GetValue(null);
            }
            catch { return IntPtr.Zero; }
        }

        // The text comes from ConfigDoc (teampl.json).
        private static void Load()
        {
            var path = ConfigDoc.Where(ConfigDoc.TeamPl);
            try
            {
                var text = ConfigDoc.SectionText(ConfigDoc.TeamPl);
                if (text == null)
                {
                    // An absent file and an unreadable file are different
                    // findings and do not share a log level (AGENTS.md).
                    var why = $"Progression: {ConfigDoc.WhyNo(ConfigDoc.TeamPl)}. It carries the "
                        + "game's own cell values, which this needs. Doing nothing.";
                    if (ConfigDoc.CouldNotRead(ConfigDoc.TeamPl)) Plugin.Log.LogError(why);
                    else Plugin.Log.LogWarning(why);
                    return;
                }
                var opts = new JsonSerializerOptions
                {
                    ReadCommentHandling = JsonCommentHandling.Skip,
                    AllowTrailingCommas = true
                };
                var f = JsonSerializer.Deserialize<FileShape>(text, opts);
                if (f == null)
                {
                    Plugin.Log.LogError($"Progression: {path} parsed to nothing. Doing nothing.");
                    return;
                }

                Slices.ReportRetiredGate("Progression", ConfigDoc.TeamPl,
                                         "Progression", f.RetiredEnabled);
                enabled = true;

                foreach (var c in f.Table)
                    Cells[(c.ActionClass, c.MissionPowerLevel)] = c.PowerLevelFraction;

                foreach (var c in f.Override)
                    Overrides[(c.ActionClass, c.MissionPowerLevel)] = c.PowerLevelFraction;

            }
            catch (Exception e)
            {
                enabled = false;
                Plugin.Log.LogError($"Progression: failed to read {path}: {e.Message}. Nothing "
                    + "is patched and the sum is left exactly as the game computes it.");
            }
        }

        private static long ReadLong(object row, string name)
        {
            try
            {
                var p = AccessTools.Property(row.GetType(), name);
                if (p == null) return long.MinValue;
                var v = p.GetValue(row);
                return v == null ? long.MinValue
                                 : Convert.ToInt64(v, CultureInfo.InvariantCulture);
            }
            catch { return long.MinValue; }
        }
    }
}
